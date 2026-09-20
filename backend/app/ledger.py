"""Read-only, parent-authorized B9 timeline with live keyset pagination.

Ordering is event time plus UUID tie-break, not causality or commit order.
References are batch-loaded once per page; no current balance is calculated.
"""

import base64
import binascii
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError

from app.api.ledger_schemas import LedgerResponse
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation
from app.core.errors import AuthError
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from app.models.user import User

EVENTS = {
    "COMMITMENT_PROPOSED",
    "COMMITMENT_CONFIRMED",
    "COMMITMENT_REJECTED",
    "COMMITMENT_CANCELLED",
    "REPAYMENT_REPORTED",
    "REPAYMENT_VERIFIED",
    "REPAYMENT_DISPUTED",
}


def encode_cursor(identifier, occurred_at, event_id):
    raw = json.dumps([1, str(identifier), occurred_at.isoformat(), str(event_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value, identifier):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 512:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        data = json.loads(raw)
        if (
            type(data) is not list
            or len(data) != 4
            or type(data[0]) is not int
            or data[0] != 1
            or any(type(v) is not str for v in data[1:])
            or UUID(data[1]) != identifier
        ):
            raise ValueError
        stamp = datetime.fromisoformat(data[2])
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(UTC), UUID(data[3])
    except (ValueError, TypeError, binascii.Error, UnicodeError, OverflowError):
        raise AuthError("VALIDATION_ERROR") from None


def _require(condition):
    if not condition:
        raise ValueError("Invalid stored timeline")


def _project(db, parent, rows):
    """Check every public reference before building a closed response."""
    verification_ids = set()
    for row in rows:
        _require(row.event_type in EVENTS and type(row.event_payload) is dict)
        keys = {"status"}
        if row.event_type in ("REPAYMENT_VERIFIED", "REPAYMENT_DISPUTED"):
            keys.add("verification_id")
            value = row.event_payload.get("verification_id")
            _require(type(value) is str)
            verification_ids.add(UUID(value))
        if row.event_type == "REPAYMENT_VERIFIED":
            keys.update(("verified_outstanding", "commitment_status"))
        _require(set(row.event_payload) == keys)

    def load(model, identifiers):
        return {r.id: r for r in db.scalars(select(model).where(model.id.in_(identifiers)))}

    people = {
        r.id: r
        for r in db.execute(
            select(User.id, User.display_name).where(User.id.in_({r.actor_user_id for r in rows}))
        )
    }
    repayments = load(Repayment, {r.repayment_id for r in rows if r.repayment_id})
    terms = load(CommitmentTermsVersion, {r.terms_version_id for r in rows if r.terms_version_id})
    verifications = load(RepaymentVerification, verification_ids)
    participants = {parent.borrower_user_id, parent.lender_user_id}
    result = []
    for row in rows:
        _require(row.commitment_id == parent.id)
        _require(row.actor_user_id in participants and row.actor_user_id in people)
        payload = row.event_payload
        details = {"status": payload["status"]}
        needs_terms = row.event_type in (
            "COMMITMENT_PROPOSED",
            "REPAYMENT_REPORTED",
            "REPAYMENT_VERIFIED",
        )
        if needs_terms:
            _require(row.terms_version_id in terms)
            _require(terms[row.terms_version_id].commitment_id == parent.id)
            details["terms_version_id"] = row.terms_version_id
        else:
            _require(row.terms_version_id is None)
        if row.event_type.startswith("REPAYMENT_"):
            _require(row.repayment_id in repayments)
            repayment = repayments[row.repayment_id]
            _require(repayment.commitment_id == parent.id)
            _require(repayment.reported_by_user_id in participants)
            _require(row.amount_minor == repayment.amount_minor)
            _require(row.currency == repayment.currency == parent.currency)
            details.update(
                repayment_id=row.repayment_id, amount_minor=row.amount_minor, currency=row.currency
            )
            if row.event_type == "REPAYMENT_REPORTED":
                _require(row.actor_user_id == repayment.reported_by_user_id)
            else:
                verification_id = UUID(payload["verification_id"])
                _require(verification_id in verifications)
                verification = verifications[verification_id]
                _require(verification.repayment_id == row.repayment_id)
                _require(verification.decided_by_user_id == row.actor_user_id)
                _require(row.actor_user_id != repayment.reported_by_user_id)
                _require(verification.decision.value == payload["status"])
                details["verification_id"] = verification_id
            if row.event_type == "REPAYMENT_VERIFIED":
                details.update(
                    resulting_verified_outstanding_minor=payload["verified_outstanding"],
                    resulting_commitment_status=payload["commitment_status"],
                )
        else:
            _require(row.repayment_id is None and row.amount_minor is None and row.currency is None)
        result.append(
            dict(
                id=row.id,
                commitment_id=row.commitment_id,
                event_type=row.event_type,
                actor={
                    "id": row.actor_user_id,
                    "display_name": people[row.actor_user_id].display_name,
                },
                occurred_at=row.occurred_at,
                details=details,
            )
        )
    return result


class LedgerService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.authorization = AuthorizationService(sessions)

    @auth_operation
    def list(self, principal, identifier, limit=50, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AuthError("VALIDATION_ERROR")
        try:
            with self.sessions.sessions.begin() as db:
                self.authorization.commitment(db, principal, identifier)
                position = decode_cursor(cursor, identifier)
                parent = db.get(Commitment, identifier)
                query = select(LedgerEvent).where(LedgerEvent.commitment_id == identifier)
                if position:
                    query = query.where(tuple_(LedgerEvent.occurred_at, LedgerEvent.id) > position)
                rows = list(
                    db.scalars(
                        query.order_by(LedgerEvent.occurred_at.asc(), LedgerEvent.id.asc()).limit(
                            limit + 1
                        )
                    )
                )
                # Validate the lookahead as well; corrupt data never becomes a partial page.
                items = _project(db, parent, rows)
                response = LedgerResponse(
                    items=items,
                    next_cursor=(
                        encode_cursor(identifier, rows[limit - 1].occurred_at, rows[limit - 1].id)
                        if len(rows) > limit
                        else None
                    ),
                )
                response.items = response.items[:limit]
                return response
        except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None
