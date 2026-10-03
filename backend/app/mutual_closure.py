"""Mutual full waiver under idempotency -> sorted Users -> parent -> child locks."""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.closure_schemas import ClosureResponse
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation, utc_now
from app.closure_provenance import validate_closure
from app.commitments import CommitmentService
from app.core.errors import AuthError, FinancialError, ResourceUnavailable
from app.core.logging import sanitize_request_id
from app.core.reliability import transaction
from app.idempotency import Idempotency
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.enums import CommitmentStatus, MutualClosureStatus, RepaymentStatus, UserStatus
from app.models.ledger_event import LedgerEvent
from app.models.mutual_closure_request import MutualClosureRequest
from app.models.repayment import Repayment
from app.models.user import User
from app.notifications import create_notification
from app.repayments import repayment_accounting
from app.verification import validate_history

ELIGIBLE = (CommitmentStatus.ACTIVE, CommitmentStatus.PARTIALLY_REPAID)
SAFE_FAILURES = (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError)


class MutualClosureService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.authorization = AuthorizationService(sessions)
        self.idempotency = Idempotency(sessions)

    def _child(self, db, principal, identifier, *, lock=False):
        parent_id = db.scalar(
            select(MutualClosureRequest.commitment_id)
            .join(Commitment, MutualClosureRequest.commitment_id == Commitment.id)
            .where(
                MutualClosureRequest.id == identifier,
                CommitmentService._participants(principal.user_id),
            )
        )
        if parent_id is None:
            self.sessions.revalidate_user_locked(db, principal)
            raise ResourceUnavailable()
        self.authorization.commitment(db, principal, parent_id, lock=lock)
        query = select(MutualClosureRequest).where(
            MutualClosureRequest.id == identifier, MutualClosureRequest.commitment_id == parent_id
        )
        if lock:
            query = query.with_for_update()
        row = db.scalar(query.execution_options(populate_existing=True))
        if row is None:
            raise ResourceUnavailable()
        return db.get(Commitment, parent_id), row

    def _lock(self, db, principal, identifier, *, decision):
        query = select(Commitment.borrower_user_id, Commitment.lender_user_id, Commitment.id)
        if decision:
            query = query.join(
                MutualClosureRequest, MutualClosureRequest.commitment_id == Commitment.id
            )
        snapshot = db.execute(
            query.where(
                (MutualClosureRequest.id if decision else Commitment.id) == identifier,
                CommitmentService._participants(principal.user_id),
            )
        ).first()
        for user_id in sorted(set(snapshot[:2] if snapshot else ()) | {principal.user_id}):
            db.execute(select(User.id).where(User.id == user_id).with_for_update()).first()
        self.sessions.revalidate_user_locked(db, principal)
        if decision:
            parent, row = self._child(db, principal, identifier, lock=True)
        else:
            self.authorization.commitment(db, principal, identifier, lock=True)
            parent, row = db.get(Commitment, identifier), None
        if tuple(snapshot or ()) != (parent.borrower_user_id, parent.lender_user_id, parent.id):
            raise FinancialError("CONFLICT")
        return parent, row

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
    def _actor(principal, row, action):
        expected = row.requested_by_user_id if action == "cancel" else row.counterparty_user_id
        if principal.user_id != expected:
            raise FinancialError("FORBIDDEN")

    @staticmethod
    def _response(db, row, parent):
        validate_closure(row, parent)
        people = {
            u.id: {"id": u.id, "display_name": u.display_name}
            for u in db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_({row.requested_by_user_id, row.counterparty_user_id})
                )
            )
        }
        return ClosureResponse(
            id=row.id,
            commitment_id=row.commitment_id,
            requested_by=people[row.requested_by_user_id],
            counterparty=people[row.counterparty_user_id],
            status=row.status,
            currency=row.currency,
            outstanding_snapshot_minor=row.outstanding_snapshot_minor,
            waived_amount_minor=row.waived_amount_minor,
            note=row.note,
            decided_by=people[row.decided_by_user_id] if row.decided_by_user_id else None,
            decided_at=row.decided_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        ).model_dump(mode="json")

    @staticmethod
    def _events(db, row, parent, actor, now, request_id):
        name = "MUTUAL_CLOSURE_" + row.status.value
        event = LedgerEvent(
            commitment_id=parent.id,
            event_type=name,
            actor_user_id=actor,
            amount_minor=None,
            currency=None,
            repayment_id=None,
            terms_version_id=None,
            event_payload={"closure_request_id": str(row.id), "status": row.status.value},
            occurred_at=now,
            created_at=now,
        )
        db.add(event)
        db.add(
            AuditLog(
                actor_user_id=actor,
                object_type="MutualClosureRequest",
                object_id=row.id,
                action=name,
                result="SUCCESS",
                created_at=now,
                metadata_={"request_id": sanitize_request_id(request_id)},
            )
        )
        if row.status != MutualClosureStatus.CANCELLED:
            create_notification(db, event, parent)

    @auth_operation
    def create(self, principal, identifier, body, key, *, request_id=None):
        def perform(db):
            parent, _ = self._lock(db, principal, identifier, decision=False)
            self._eligible(db, parent)
            now = utc_now(self.sessions.clock, db)
            _, capacity = repayment_accounting(db, parent, now)
            if capacity.verified_outstanding <= 0:
                raise FinancialError("INVALID_STATE")
            if (
                db.scalar(
                    select(MutualClosureRequest.id)
                    .where(
                        MutualClosureRequest.commitment_id == parent.id,
                        MutualClosureRequest.status == MutualClosureStatus.REQUESTED,
                    )
                    .limit(1)
                )
                is not None
            ):
                raise FinancialError("CONFLICT")
            row = MutualClosureRequest(
                commitment_id=parent.id,
                requested_by_user_id=principal.user_id,
                counterparty_user_id=next(
                    u
                    for u in (parent.borrower_user_id, parent.lender_user_id)
                    if u != principal.user_id
                ),
                status=MutualClosureStatus.REQUESTED,
                currency=parent.currency,
                outstanding_snapshot_minor=capacity.verified_outstanding,
                waived_amount_minor=capacity.verified_outstanding,
                note=body.note,
                decided_by_user_id=None,
                decided_at=None,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
            self._events(db, row, parent, principal.user_id, now, request_id)
            return 201, self._response(db, row, parent)

        try:
            with transaction(self.sessions.sessions, "commitments") as db:
                return self.idempotency.execute(
                    db,
                    principal,
                    "closure-requests",
                    identifier,
                    key,
                    body.model_dump(mode="json"),
                    perform,
                    lambda db: self.authorization.commitment(db, principal, identifier),
                    endpoint=f"POST /api/v1/commitments/{identifier}/closure-requests",
                )
        except SAFE_FAILURES:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def decide(self, principal, identifier, action, key, *, request_id=None):
        if action not in ("accept", "reject", "cancel"):
            raise ValueError("Unknown closure action")

        def perform(db):
            parent, row = self._lock(db, principal, identifier, decision=True)
            validate_closure(row, parent)
            self._actor(principal, row, action)
            if row.status != MutualClosureStatus.REQUESTED:
                raise FinancialError("INVALID_STATE")
            now = utc_now(self.sessions.clock, db)
            if action == "accept":
                self._eligible(db, parent)
                reports = list(
                    db.scalars(select(Repayment).where(Repayment.commitment_id == parent.id))
                )
                for report in reports:
                    validate_history(db, report, parent)
                _, capacity = repayment_accounting(db, parent, now)
                if capacity.verified_outstanding <= 0:
                    raise FinancialError("INVALID_STATE")
                if (
                    any(r.status == RepaymentStatus.PENDING_VERIFICATION for r in reports)
                    or capacity.verified_outstanding != row.outstanding_snapshot_minor
                ):
                    raise FinancialError("CONFLICT")
                parent.status = CommitmentStatus.CLOSED
                parent.closed_at = now
                parent.updated_at = now
            row.status = {
                "accept": MutualClosureStatus.ACCEPTED,
                "reject": MutualClosureStatus.REJECTED,
                "cancel": MutualClosureStatus.CANCELLED,
            }[action]
            row.decided_by_user_id = principal.user_id
            row.decided_at = now
            row.updated_at = now
            db.flush()
            self._events(db, row, parent, principal.user_id, now, request_id)
            return 200, self._response(db, row, parent)

        def replay(db):
            parent, row = self._child(db, principal, identifier)
            validate_closure(row, parent)
            self._actor(principal, row, action)

        try:
            with transaction(self.sessions.sessions, "commitments") as db:
                return self.idempotency.execute(
                    db,
                    principal,
                    action,
                    identifier,
                    key,
                    {},
                    perform,
                    replay,
                    endpoint=f"POST /api/v1/closure-requests/{identifier}/{action}",
                )
        except SAFE_FAILURES:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def list(self, principal, identifier):
        try:
            with transaction(self.sessions.sessions, "commitments") as db:
                self.authorization.commitment(db, principal, identifier, lock=True)
                parent = db.get(Commitment, identifier)
                rows = db.scalars(
                    select(MutualClosureRequest)
                    .where(MutualClosureRequest.commitment_id == identifier)
                    .order_by(MutualClosureRequest.created_at.desc(), MutualClosureRequest.id.asc())
                )
                return [self._response(db, row, parent) for row in rows]
        except SAFE_FAILURES:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def detail(self, principal, identifier):
        try:
            with transaction(self.sessions.sessions, "commitments") as db:
                parent, row = self._child(db, principal, identifier, lock=True)
                return self._response(db, row, parent)
        except SAFE_FAILURES:
            raise AuthError("SERVICE_UNAVAILABLE") from None
