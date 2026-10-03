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
from app.api.term_schemas import TermsRequest
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation
from app.closure_provenance import validate_closure
from app.core.errors import AuthError
from app.core.validation import normalize_timezone
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.extension_request import ExtensionRequest
from app.models.ledger_event import LedgerEvent
from app.models.mutual_closure_request import MutualClosureRequest
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
EXTENSION_EVENTS = {"EXTENSION_REQUESTED", "EXTENSION_ACCEPTED", "EXTENSION_REJECTED"}
CLOSURE_EVENTS = {
    "MUTUAL_CLOSURE_REQUESTED",
    "MUTUAL_CLOSURE_ACCEPTED",
    "MUTUAL_CLOSURE_REJECTED",
    "MUTUAL_CLOSURE_CANCELLED",
}


def _closure_projection(row, parent, closures):
    request = closures[UUID(row.event_payload["closure_request_id"])]
    validate_closure(request, parent)
    _require(row.amount_minor is None and row.currency is None and row.repayment_id is None)
    _require(row.terms_version_id is None)
    status = row.event_type.removeprefix("MUTUAL_CLOSURE_")
    _require(row.event_payload["status"] == status)
    if status == "REQUESTED":
        _require(row.actor_user_id == request.requested_by_user_id)
        _require(row.occurred_at == request.created_at)
    else:
        _require(request.status.value == status and request.decided_at == row.occurred_at)
        _require(row.actor_user_id == request.decided_by_user_id)
    details = dict(
        closure_request_id=request.id,
        status=status,
        currency=request.currency,
        outstanding_snapshot_minor=request.outstanding_snapshot_minor,
        waived_amount_minor=request.waived_amount_minor,
    )
    if status == "ACCEPTED":
        _require(parent.status.value == "CLOSED" and parent.closed_at == request.decided_at)
        details["resulting_commitment_status"] = "CLOSED"
    return details


def _extension_projection(row, parent, extensions, terms):
    payload = row.event_payload
    request = extensions[UUID(payload["extension_request_id"])]
    base_id = UUID(payload["base_terms_version_id"])
    base = terms[base_id]
    _require(request.commitment_id == base.commitment_id == parent.id)
    _require(request.requested_terms == {"base_terms_version_id": str(base_id)})
    _require(UUID(payload["requested_by_user_id"]) == request.requested_by_user_id)
    _require(request.requested_by_user_id in {parent.borrower_user_id, parent.lender_user_id})
    # Validate the historical single-date source without adding per-event DB queries.
    metadata = base.schedule_definition
    _require(
        type(metadata) is dict
        and set(metadata) == {"schedule_mode", "due_timezone", "installment_dates"}
    )
    normalize_timezone(metadata["due_timezone"])
    logical = TermsRequest(
        due_date=base.due_date,
        interest_type=base.interest_type.value,
        interest_rate_bps=base.interest_rate_bps,
        grace_period_days=base.grace_period_days,
        installment_dates=metadata["installment_dates"],
    )
    _require(logical.schedule_mode == metadata["schedule_mode"] == "single")
    _require(base.version_no >= 1)
    _require(base.created_by_user_id in {parent.borrower_user_id, parent.lender_user_id})
    _require(base.due_date is not None and request.requested_due_date > base.due_date)
    _require(payload["previous_due_date"] == base.due_date.isoformat())
    _require(payload["requested_due_date"] == request.requested_due_date.isoformat())
    _require(row.amount_minor is None and row.currency is None and row.repayment_id is None)
    status = row.event_type.removeprefix("EXTENSION_")
    _require(payload["status"] == status)
    if status == "REQUESTED":
        _require(row.actor_user_id == request.requested_by_user_id)
        _require(row.occurred_at == request.created_at)
    else:
        _require(request.status.value == status and request.decided_at == row.occurred_at)
        _require(row.actor_user_id == request.decided_by_user_id)
        _require(row.actor_user_id != request.requested_by_user_id)
    if status == "ACCEPTED":
        result = terms[UUID(payload["terms_version_id"])]
        _require(result.id == row.terms_version_id and result.id != base_id)
        _require(result.commitment_id == parent.id and result.version_no > base.version_no)
        _require(result.due_date == request.requested_due_date)
        _require(result.created_by_user_id == row.actor_user_id)
        _require(result.effective_at == row.occurred_at)
        _require(
            all(
                getattr(result, key) == getattr(base, key)
                for key in (
                    "interest_type",
                    "interest_rate_bps",
                    "grace_period_days",
                    "schedule_definition",
                )
            )
        )
    else:
        _require(row.terms_version_id == base_id)
    return {
        key: payload[key]
        for key in (
            "extension_request_id",
            "base_terms_version_id",
            "requested_by_user_id",
            "previous_due_date",
            "requested_due_date",
            "status",
        )
    } | ({"terms_version_id": payload["terms_version_id"]} if status == "ACCEPTED" else {})


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
    extension_ids, base_ids = set(), set()
    closure_ids = set()
    for row in rows:
        if row.event_type in CLOSURE_EVENTS:
            payload = row.event_payload
            _require(type(payload) is dict and set(payload) == {"closure_request_id", "status"})
            _require(all(type(v) is str for v in payload.values()))
            closure_ids.add(UUID(payload["closure_request_id"]))
            continue
        if row.event_type in EXTENSION_EVENTS:
            payload = row.event_payload
            _require(type(payload) is dict)
            keys = {
                "extension_request_id",
                "base_terms_version_id",
                "requested_by_user_id",
                "previous_due_date",
                "requested_due_date",
                "status",
            }
            if row.event_type == "EXTENSION_ACCEPTED":
                keys.add("terms_version_id")
            _require(set(payload) == keys and all(type(v) is str for v in payload.values()))
            extension_ids.add(UUID(payload["extension_request_id"]))
            base_ids.add(UUID(payload["base_terms_version_id"]))
            continue
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
    terms = load(
        CommitmentTermsVersion, {r.terms_version_id for r in rows if r.terms_version_id} | base_ids
    )
    extensions = load(ExtensionRequest, extension_ids) if extension_ids else {}
    closures = load(MutualClosureRequest, closure_ids) if closure_ids else {}
    verifications = load(RepaymentVerification, verification_ids)
    participants = {parent.borrower_user_id, parent.lender_user_id}
    result = []
    for row in rows:
        _require(row.commitment_id == parent.id)
        _require(row.actor_user_id in participants and row.actor_user_id in people)
        payload = row.event_payload
        if row.event_type in CLOSURE_EVENTS:
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
                    details=_closure_projection(row, parent, closures),
                )
            )
            continue
        if row.event_type in EXTENSION_EVENTS:
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
                    details=_extension_projection(row, parent, extensions, terms),
                )
            )
            continue
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
