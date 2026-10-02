"""Whole-report counterparty decisions. No reopening, allocation or closure.

Writers lock idempotency scope -> sorted Users -> Commitment -> Repayment.
History is appended, never updated. DISPUTE deliberately performs no obligation
calculation: it releases a pending reservation even after obligation reduction.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.verification_schemas import VerificationResponse
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation, utc_now
from app.commitments import CommitmentService
from app.core.errors import AuthError, FinancialError, VerificationError
from app.core.logging import sanitize_request_id
from app.core.reliability import transaction
from app.idempotency import Idempotency
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.enums import CommitmentStatus, RepaymentStatus, UserStatus, VerificationDecision
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from app.models.user import User
from app.notifications import create_notification
from app.repayments import RepaymentService, repayment_accounting


def validate_history(db, row, parent):
    """Validate the stored projection before deciding or exposing its history."""
    participants = {parent.borrower_user_id, parent.lender_user_id}
    if (
        row.commitment_id != parent.id
        or row.reported_by_user_id not in participants
        or row.currency != parent.currency
        or row.amount_minor <= 0
    ):
        raise ValueError("Inconsistent repayment association")
    rows = list(
        db.scalars(
            select(RepaymentVerification)
            .where(RepaymentVerification.repayment_id == row.id)
            .order_by(RepaymentVerification.decided_at.asc(), RepaymentVerification.id.asc())
        )
    )
    other = next(u for u in participants if u != row.reported_by_user_id)
    if any(h.decided_by_user_id != other for h in rows):
        raise ValueError("Inconsistent historical decision actor")
    if row.status == RepaymentStatus.PENDING_VERIFICATION:
        if rows:
            raise ValueError("Pending repayment has decision history")
    elif row.status in (RepaymentStatus.VERIFIED, RepaymentStatus.DISPUTED):
        if len(rows) != 1 or rows[0].decision.value != row.status.value:
            raise ValueError("Repayment projection contradicts history")
    # CANCELLED projection/history semantics belong to a later workflow.
    return rows


class VerificationService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.authorization = AuthorizationService(sessions)
        self.idempotency = Idempotency(sessions)

    @staticmethod
    def _decision_actor(principal, row, parent):
        if row.reported_by_user_id not in (parent.borrower_user_id, parent.lender_user_id):
            raise ValueError("Invalid original reporter")
        if row.reported_by_user_id == principal.user_id:
            raise FinancialError("FORBIDDEN")

    @staticmethod
    def _events(db, row, history, parent, now, request_id, terms_id, remaining):
        name = "REPAYMENT_" + history.decision.value
        payload = {"verification_id": str(history.id), "status": row.status.value}
        if history.decision == VerificationDecision.VERIFIED:
            payload.update(verified_outstanding=remaining, commitment_status=parent.status.value)
        event = LedgerEvent(
            commitment_id=parent.id,
            repayment_id=row.id,
            actor_user_id=history.decided_by_user_id,
            event_type=name,
            amount_minor=row.amount_minor,
            currency=row.currency,
            terms_version_id=terms_id,
            event_payload=payload,
            occurred_at=now,
            created_at=now,
        )
        db.add(event)
        db.add(
            AuditLog(
                actor_user_id=history.decided_by_user_id,
                object_type="Repayment",
                object_id=row.id,
                action=name,
                result="SUCCESS",
                created_at=now,
                metadata_={"request_id": sanitize_request_id(request_id)},
            )
        )
        create_notification(db, event, db.get(Commitment, event.commitment_id))

    @auth_operation
    def decide(self, principal, identifier, action, body, key, *, request_id=None):
        if action not in ("verify", "dispute"):
            raise ValueError("Unknown decision action")

        def perform(db):
            snapshot = db.execute(
                select(Commitment.borrower_user_id, Commitment.lender_user_id, Commitment.id)
                .join(Repayment, Repayment.commitment_id == Commitment.id)
                .where(
                    Repayment.id == identifier, CommitmentService._participants(principal.user_id)
                )
            ).first()
            for user_id in sorted(set(snapshot[:2] if snapshot else ()) | {principal.user_id}):
                db.execute(select(User.id).where(User.id == user_id).with_for_update()).first()
            self.sessions.revalidate_user_locked(db, principal)
            access = self.authorization.repayment(db, principal, identifier, lock=True)
            parent = db.get(Commitment, access.commitment_id)
            row = db.get(Repayment, identifier)
            if tuple(snapshot or ()) != (parent.borrower_user_id, parent.lender_user_id, parent.id):
                raise FinancialError("CONFLICT")
            self._decision_actor(principal, row, parent)
            validate_history(db, row, parent)
            if row.status == RepaymentStatus.VERIFIED:
                raise VerificationError("ALREADY_VERIFIED")
            if row.status != RepaymentStatus.PENDING_VERIFICATION or parent.status not in (
                CommitmentStatus.ACTIVE,
                CommitmentStatus.PARTIALLY_REPAID,
            ):
                raise FinancialError("INVALID_STATE")
            if any(db.get(User, u).status != UserStatus.ACTIVE for u in snapshot[:2]):
                raise ValueError("Inconsistent financial account eligibility")
            now = utc_now(self.sessions.clock, db)
            terms_id = remaining = None
            if action == "verify":
                # Existing verified credit must also have authoritative decision history.
                for credit in db.scalars(
                    select(Repayment).where(
                        Repayment.commitment_id == parent.id,
                        Repayment.status == RepaymentStatus.VERIFIED,
                    )
                ):
                    validate_history(db, credit, parent)
                terms_id, accounting = repayment_accounting(db, parent, now)
                remaining = accounting.verified_outstanding - row.amount_minor
                if remaining < 0:
                    raise VerificationError("OVER_REPAYMENT")
            decision = (
                VerificationDecision.VERIFIED
                if action == "verify"
                else VerificationDecision.DISPUTED
            )
            history = RepaymentVerification(
                repayment_id=row.id,
                decided_by_user_id=principal.user_id,
                decision=decision,
                decision_note=body.decision_note,
                decided_at=now,
            )
            db.add(history)
            db.flush()
            row.status = RepaymentStatus(decision.value)
            if action == "verify":
                state = (
                    CommitmentStatus.FULLY_REPAID
                    if remaining == 0
                    else CommitmentStatus.PARTIALLY_REPAID
                )
                if parent.status != state:
                    parent.status = state
                    parent.updated_at = max(now, parent.updated_at + timedelta(microseconds=1))
            db.flush()
            self._events(db, row, history, parent, now, request_id, terms_id, remaining)
            return 200, RepaymentService._response(db, row, parent)

        def replay_authorize(db):
            access = self.authorization.repayment(db, principal, identifier)
            self._decision_actor(
                principal, db.get(Repayment, identifier), db.get(Commitment, access.commitment_id)
            )

        try:
            with transaction(self.sessions.sessions, "verification") as db:
                result = self.idempotency.execute(
                    db,
                    principal,
                    action,
                    identifier,
                    key,
                    body.model_dump(mode="json"),
                    perform,
                    replay_authorize,
                    endpoint=f"POST /api/v1/repayments/{identifier}/{action}",
                )
            return result
        except (SQLAlchemyError, ValueError, TypeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def history(self, principal, identifier):
        try:
            with transaction(self.sessions.sessions, "verification") as db:
                access = self.authorization.repayment(db, principal, identifier, lock=True)
                rows = validate_history(
                    db, db.get(Repayment, identifier), db.get(Commitment, access.commitment_id)
                )
                return [
                    VerificationResponse(
                        id=h.id,
                        repayment_id=h.repayment_id,
                        decided_by={
                            "id": h.decided_by_user_id,
                            "display_name": db.get(User, h.decided_by_user_id).display_name,
                        },
                        decision=h.decision,
                        decision_note=h.decision_note,
                        decided_at=h.decided_at,
                    )
                    for h in rows
                ]
        except (SQLAlchemyError, ValueError, TypeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None
