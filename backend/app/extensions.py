"""B10 single-date extensions. No monetary, installment, or settlement writes.

All mutations use idempotency -> sorted Users -> Commitment -> ExtensionRequest.
The parent lock protects one pending request and max(version_no)+1 allocation.
"""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.extension_schemas import ExtensionResponse
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation, utc_now
from app.commitments import CommitmentService
from app.core.errors import AuthError, FinancialError
from app.core.logging import sanitize_request_id
from app.idempotency import Idempotency
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.enums import CommitmentStatus, ExtensionStatus, UserStatus
from app.models.extension_request import ExtensionRequest
from app.models.ledger_event import LedgerEvent
from app.models.user import User
from app.terms import project_terms

ELIGIBLE = (CommitmentStatus.ACTIVE, CommitmentStatus.PARTIALLY_REPAID)


def base_terms(db, row, parent):
    context = row.requested_terms
    if type(context) is not dict or set(context) != {"base_terms_version_id"}:
        raise ValueError("Invalid extension context")
    value = context["base_terms_version_id"]
    if type(value) is not str:
        raise ValueError("Invalid base reference")
    base = db.get(CommitmentTermsVersion, UUID(value))
    if base is None or base.commitment_id != parent.id or row.commitment_id != parent.id:
        raise ValueError("Invalid extension association")
    if project_terms(db, base, parent).schedule_mode != "single":
        raise ValueError("Invalid historical extension schedule")
    if row.requested_due_date is None or row.requested_due_date <= base.due_date:
        raise ValueError("Invalid historical extension date")
    participants = {parent.borrower_user_id, parent.lender_user_id}
    if row.requested_by_user_id not in participants:
        raise ValueError("Invalid extension requester")
    if row.status == ExtensionStatus.REQUESTED:
        if row.decided_by_user_id is not None or row.decided_at is not None:
            raise ValueError("Undecided request contains a decision")
    elif row.status in (ExtensionStatus.ACCEPTED, ExtensionStatus.REJECTED):
        if (
            row.decided_by_user_id not in participants
            or row.decided_by_user_id == row.requested_by_user_id
            or row.decided_at is None
        ):
            raise ValueError("Invalid extension decision")
    # CANCELLED has no B10 transition; do not invent cancellation lifecycle rules.
    if row.decided_by_user_id is not None and row.decided_by_user_id not in participants:
        raise ValueError("Invalid decision reference")
    return base


class ExtensionService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.authorization = AuthorizationService(sessions)
        self.idempotency = Idempotency(sessions)

    def _lock(self, db, principal, identifier, *, decision):
        query = select(Commitment.borrower_user_id, Commitment.lender_user_id, Commitment.id)
        if decision:
            query = query.join(ExtensionRequest, ExtensionRequest.commitment_id == Commitment.id)
        snapshot = db.execute(
            query.where(
                (ExtensionRequest.id if decision else Commitment.id) == identifier,
                CommitmentService._participants(principal.user_id),
            )
        ).first()
        for user_id in sorted(set(snapshot[:2] if snapshot else ()) | {principal.user_id}):
            db.execute(select(User.id).where(User.id == user_id).with_for_update()).first()
        self.sessions.revalidate_user_locked(db, principal)
        lookup = self.authorization.extension_request if decision else self.authorization.commitment
        access = lookup(db, principal, identifier, lock=True)
        parent = db.get(Commitment, access.commitment_id)
        if tuple(snapshot or ()) != (parent.borrower_user_id, parent.lender_user_id, parent.id):
            raise FinancialError("CONFLICT")
        return parent

    @staticmethod
    def _decision_actor(principal, row, parent):
        if row.requested_by_user_id not in (parent.borrower_user_id, parent.lender_user_id):
            raise ValueError("Invalid requester")
        if principal.user_id == row.requested_by_user_id:
            raise FinancialError("FORBIDDEN")

    @staticmethod
    def _eligible(db, parent):
        if parent.status not in ELIGIBLE:
            raise FinancialError("INVALID_STATE")
        if any(
            db.get(User, u).status != UserStatus.ACTIVE
            for u in (parent.borrower_user_id, parent.lender_user_id)
        ):
            raise ValueError("Inconsistent account eligibility")

    @staticmethod
    def _current(db, parent, now):
        current = db.scalar(
            select(CommitmentTermsVersion)
            .where(
                CommitmentTermsVersion.commitment_id == parent.id,
                CommitmentTermsVersion.effective_at <= now,
            )
            .order_by(CommitmentTermsVersion.version_no.desc())
            .limit(1)
        )
        if current is None:
            raise ValueError("Missing effective terms")
        if project_terms(db, current, parent).schedule_mode != "single":
            raise FinancialError("INVALID_STATE")
        return current

    @staticmethod
    def _response(db, row, parent):
        base = base_terms(db, row, parent)
        people = {
            u.id: {"id": u.id, "display_name": u.display_name}
            for u in db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_({row.requested_by_user_id, row.decided_by_user_id} - {None})
                )
            )
        }
        return ExtensionResponse(
            id=row.id,
            commitment_id=row.commitment_id,
            requested_by=people[row.requested_by_user_id],
            status=row.status,
            base_terms_version_id=base.id,
            previous_due_date=base.due_date,
            requested_due_date=row.requested_due_date,
            reason=row.reason,
            decided_by=people[row.decided_by_user_id] if row.decided_by_user_id else None,
            decided_at=row.decided_at,
            created_at=row.created_at,
        ).model_dump(mode="json")

    @staticmethod
    def _events(db, row, base, terms_id, actor, now, request_id):
        status = row.status.value
        name = "EXTENSION_" + status
        details = dict(
            extension_request_id=str(row.id),
            base_terms_version_id=str(base.id),
            requested_by_user_id=str(row.requested_by_user_id),
            previous_due_date=base.due_date.isoformat(),
            requested_due_date=row.requested_due_date.isoformat(),
            status=status,
        )
        if status == "ACCEPTED":
            details["terms_version_id"] = str(terms_id)
        db.add(
            LedgerEvent(
                commitment_id=row.commitment_id,
                event_type=name,
                actor_user_id=actor,
                terms_version_id=terms_id,
                amount_minor=None,
                currency=None,
                event_payload=details,
                occurred_at=now,
                created_at=now,
            )
        )
        db.add(
            AuditLog(
                actor_user_id=actor,
                object_type="ExtensionRequest",
                object_id=row.id,
                action=name,
                result="SUCCESS",
                created_at=now,
                metadata_={"request_id": sanitize_request_id(request_id)},
            )
        )

    @auth_operation
    def create(self, principal, identifier, body, key, *, request_id=None):
        def perform(db):
            parent = self._lock(db, principal, identifier, decision=False)
            self._eligible(db, parent)
            now = utc_now(self.sessions.clock, db)
            base = self._current(db, parent, now)
            pending = db.scalar(
                select(ExtensionRequest.id)
                .where(
                    ExtensionRequest.commitment_id == identifier,
                    ExtensionRequest.status == "REQUESTED",
                )
                .limit(1)
            )
            if pending is not None:
                raise FinancialError("CONFLICT")
            if body.requested_due_date <= base.due_date:
                raise AuthError("VALIDATION_ERROR")
            row = ExtensionRequest(
                commitment_id=identifier,
                requested_by_user_id=principal.user_id,
                requested_due_date=body.requested_due_date,
                reason=body.reason,
                requested_terms={"base_terms_version_id": str(base.id)},
                status=ExtensionStatus.REQUESTED,
                created_at=now,
            )
            db.add(row)
            db.flush()
            self._events(db, row, base, base.id, principal.user_id, now, request_id)
            return 201, self._response(db, row, parent)

        try:
            with self.sessions.sessions.begin() as db:
                return self.idempotency.execute(
                    db,
                    principal,
                    "extension-requests",
                    identifier,
                    key,
                    body.model_dump(mode="json"),
                    perform,
                    lambda db: self.authorization.commitment(db, principal, identifier),
                    endpoint=f"POST /api/v1/commitments/{identifier}/extension-requests",
                )
        except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def decide(self, principal, identifier, action, key, *, request_id=None):
        if action not in ("accept", "reject"):
            raise ValueError("Unknown extension action")

        def perform(db):
            parent = self._lock(db, principal, identifier, decision=True)
            row = db.get(ExtensionRequest, identifier)
            self._decision_actor(principal, row, parent)
            if row.status != ExtensionStatus.REQUESTED:
                raise FinancialError("INVALID_STATE")
            if action == "accept":
                self._eligible(db, parent)
            base = base_terms(db, row, parent)
            now = utc_now(self.sessions.clock, db)
            terms_id = base.id
            if action == "accept":
                current = self._current(db, parent, now)
                if current.id != base.id:
                    raise FinancialError("CONFLICT")
                number = (
                    db.scalar(
                        select(func.max(CommitmentTermsVersion.version_no)).where(
                            CommitmentTermsVersion.commitment_id == parent.id
                        )
                    )
                    + 1
                )
                terms = CommitmentTermsVersion(
                    commitment_id=parent.id,
                    version_no=number,
                    effective_at=now,
                    due_date=row.requested_due_date,
                    interest_type=base.interest_type,
                    interest_rate_bps=base.interest_rate_bps,
                    grace_period_days=base.grace_period_days,
                    schedule_definition=deepcopy(base.schedule_definition),
                    created_by_user_id=principal.user_id,
                    created_at=now,
                )
                db.add(terms)
                db.flush()
                terms_id = terms.id
            row.status = (
                ExtensionStatus.ACCEPTED if action == "accept" else ExtensionStatus.REJECTED
            )
            row.decided_by_user_id = principal.user_id
            row.decided_at = now
            db.flush()
            self._events(db, row, base, terms_id, principal.user_id, now, request_id)
            return 200, self._response(db, row, parent)

        def replay(db):
            access = self.authorization.extension_request(db, principal, identifier)
            self._decision_actor(
                principal,
                db.get(ExtensionRequest, identifier),
                db.get(Commitment, access.commitment_id),
            )

        try:
            with self.sessions.sessions.begin() as db:
                return self.idempotency.execute(
                    db,
                    principal,
                    action,
                    identifier,
                    key,
                    {},
                    perform,
                    replay,
                    endpoint=f"POST /api/v1/extension-requests/{identifier}/{action}",
                )
        except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def list(self, principal, identifier):
        try:
            with self.sessions.sessions.begin() as db:
                self.authorization.commitment(db, principal, identifier, lock=True)
                parent = db.get(Commitment, identifier)
                rows = db.scalars(
                    select(ExtensionRequest)
                    .where(ExtensionRequest.commitment_id == identifier)
                    .order_by(ExtensionRequest.created_at.desc(), ExtensionRequest.id.asc())
                )
                return [self._response(db, row, parent) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None
