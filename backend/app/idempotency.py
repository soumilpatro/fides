"""B5 synchronous transaction-local idempotency, without durable in-flight rows.

Take the non-blocking scope advisory lock BEFORE User/resource locks. Collisions
fail closed as CONFLICT. A crash rolls back all effects and releases the lock;
there is no orphan reservation to recover. Only successful results are stored.
Expired results may be replaced under the same lock after the 30-day window.
"""

import hashlib
import json
import re
from datetime import timedelta

from sqlalchemy import func, select

from app.auth.safety import utc_now
from app.core.errors import AuthError, FinancialError
from app.models.idempotency_key import IdempotencyKey


def validate_key(key):
    if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key) is None:
        raise AuthError("MALFORMED_REQUEST")
    return key


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class Idempotency:
    def __init__(self, sessions):
        self.sessions = sessions

    def execute(
        self,
        db,
        principal,
        operation,
        resource,
        key,
        payload,
        perform,
        replay_authorize,
        *,
        endpoint=None,
    ):
        validate_key(key)
        # Default preserves every historical B5/B7 scope and request hash.
        if endpoint is None:
            suffix = ("/" + str(resource) + "/" + operation) if resource else ""
            endpoint = f"POST /api/v1/commitments{suffix}"
        scope = canonical([str(principal.user_id), endpoint, key])
        lock_id = int.from_bytes(
            hashlib.sha256(("b5-idempotency:" + scope).encode()).digest()[:8], "big", signed=True
        )
        if not db.scalar(select(func.pg_try_advisory_xact_lock(lock_id))):
            raise FinancialError("CONFLICT")
        digest = hashlib.sha256(
            canonical(
                {
                    "actor": str(principal.user_id),
                    "operation": operation,
                    "resource": str(resource) if resource else None,
                    "request": payload,
                }
            ).encode()
        ).hexdigest()
        record = db.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == principal.user_id,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.idempotency_key == key,
            )
        )
        if record is not None and utc_now(self.sessions.clock, db) < record.expires_at:
            # Authentication is current even when returning a historical success.
            self.sessions.revalidate_user_locked(db, principal)
            replay_authorize(db)
            if record.request_hash != digest:
                raise FinancialError("IDEMPOTENCY_CONFLICT")
            if record.response_status is None or record.response_body is None:
                raise FinancialError("CONFLICT")
            return record.response_status, record.response_body
        status, body = perform(db)
        now = utc_now(self.sessions.clock, db)
        if record is None:
            record = IdempotencyKey(
                user_id=principal.user_id, endpoint=endpoint, idempotency_key=key
            )
            db.add(record)
        record.request_hash = digest
        record.response_status = status
        record.response_body = body
        record.created_at = now
        record.expires_at = now + timedelta(days=30)
        db.flush()
        return status, body
