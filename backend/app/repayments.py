"""B7 reporting, without verification or installment allocation.

Lock order: idempotency scope, affected Users in UUID order, parent Commitment.
All future writers affecting terms or repayment capacity must share that parent
lock. Pending capacity is distinct from verified outstanding; neither is stored.
"""

from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.repayment_schemas import RepaymentResponse
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation, utc_now
from app.commitments import CommitmentService
from app.core.errors import AuthError, FinancialError, ResourceUnavailable
from app.core.logging import sanitize_request_id
from app.core.reliability import transaction
from app.core.validation import normalize_timezone
from app.financial_calculations import accounting
from app.idempotency import Idempotency
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.enums import CommitmentStatus, RepaymentStatus, UserStatus
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.user import User
from app.notifications import create_notification
from app.terms import project_terms


def repayment_accounting(db, commitment, now):
    """Caller holds parent lock; PostgreSQL SUM stays exact for BIGINT amounts."""
    terms = db.scalar(
        select(CommitmentTermsVersion)
        .where(
            CommitmentTermsVersion.commitment_id == commitment.id,
            CommitmentTermsVersion.effective_at <= now,
        )
        .order_by(CommitmentTermsVersion.version_no.desc())
        .limit(1)
    )
    if terms is None:
        raise ValueError("No current effective terms")
    project_terms(db, terms, commitment)
    sums = dict(
        db.execute(
            select(Repayment.status, func.sum(Repayment.amount_minor))
            .where(Repayment.commitment_id == commitment.id)
            .group_by(Repayment.status)
        ).all()
    )
    # Currency and participant integrity are service invariants, not cross-table CHECKs.
    invalid = db.scalar(
        select(Repayment.id)
        .where(
            Repayment.commitment_id == commitment.id,
            (Repayment.currency != commitment.currency)
            | Repayment.reported_by_user_id.not_in(
                (commitment.borrower_user_id, commitment.lender_user_id)
            ),
        )
        .limit(1)
    )
    return terms.id, accounting(commitment, terms, sums, invalid is not None)


def reporting_capacity(db, commitment, now):
    """B7 additionally rejects inconsistent pending reservations; B8 VERIFY does not."""
    terms_id, capacity = repayment_accounting(db, commitment, now)
    if capacity.reportable_remaining < 0:
        raise ValueError("Inconsistent persisted repayment capacity")
    return terms_id, capacity


class RepaymentService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.authorization = AuthorizationService(sessions)
        self.idempotency = Idempotency(sessions)

    @staticmethod
    def _response(db, row, parent):
        if row.reported_by_user_id not in (parent.borrower_user_id, parent.lender_user_id):
            raise ValueError("Invalid persisted reporter")
        if row.currency != parent.currency:
            raise ValueError("Invalid persisted currency")
        user = db.execute(
            select(User.id, User.display_name).where(User.id == row.reported_by_user_id)
        ).one()
        return RepaymentResponse(
            id=row.id,
            commitment_id=row.commitment_id,
            reported_by={"id": user.id, "display_name": user.display_name},
            amount_minor=row.amount_minor,
            currency=row.currency,
            payment_date=row.payment_date,
            reported_at=row.reported_at,
            status=row.status,
            note=row.note,
            created_at=row.created_at,
        ).model_dump(mode="json")

    @staticmethod
    def _events(db, row, terms_id, now, request_id):
        event = LedgerEvent(
            commitment_id=row.commitment_id,
            repayment_id=row.id,
            actor_user_id=row.reported_by_user_id,
            event_type="REPAYMENT_REPORTED",
            amount_minor=row.amount_minor,
            currency=row.currency,
            terms_version_id=terms_id,
            occurred_at=now,
            created_at=now,
            event_payload={"status": "PENDING_VERIFICATION"},
        )
        db.add(event)
        db.add(
            AuditLog(
                actor_user_id=row.reported_by_user_id,
                object_type="Repayment",
                object_id=row.id,
                action="REPAYMENT_REPORTED",
                result="SUCCESS",
                created_at=now,
                metadata_={"request_id": sanitize_request_id(request_id)},
            )
        )
        create_notification(db, event, db.get(Commitment, event.commitment_id))

    @auth_operation
    def create(self, principal, identifier, body, key, *, request_id=None):
        def perform(db):
            pair = db.execute(
                select(Commitment.borrower_user_id, Commitment.lender_user_id).where(
                    Commitment.id == identifier, CommitmentService._participants(principal.user_id)
                )
            ).first()
            for user_id in sorted(set(pair or ()) | {principal.user_id}):
                db.execute(select(User.id).where(User.id == user_id).with_for_update()).first()
            self.sessions.revalidate_user_locked(db, principal)
            self.authorization.commitment(db, principal, identifier, lock=True)
            parent = db.get(Commitment, identifier)
            if (parent.borrower_user_id, parent.lender_user_id) != tuple(pair):
                raise FinancialError("CONFLICT")
            if parent.status not in (CommitmentStatus.ACTIVE, CommitmentStatus.PARTIALLY_REPAID):
                raise FinancialError("INVALID_STATE")
            # Active financial obligations prevent B2 deactivation. Reject corrupt
            # or concurrently changed eligibility under the same ordered User locks.
            if any(db.get(User, u).status != UserStatus.ACTIVE for u in pair):
                raise ResourceUnavailable()
            if body.currency != parent.currency:
                raise FinancialError("CURRENCY_MISMATCH")
            now = utc_now(self.sessions.clock, db)
            timezone = normalize_timezone(db.get(User, principal.user_id).timezone)
            if body.payment_date > now.astimezone(ZoneInfo(timezone)).date():
                raise AuthError("VALIDATION_ERROR")
            terms_id, capacity = reporting_capacity(db, parent, now)
            if body.amount_minor > capacity.reportable_remaining:
                raise FinancialError("OVER_REPAYMENT")
            row = Repayment(
                commitment_id=identifier,
                reported_by_user_id=principal.user_id,
                amount_minor=body.amount_minor,
                currency=body.currency,
                payment_date=body.payment_date,
                note=body.note,
                status=RepaymentStatus.PENDING_VERIFICATION,
                idempotency_key_id=None,
                reported_at=now,
                created_at=now,
            )
            db.add(row)
            db.flush()
            self._events(db, row, terms_id, now, request_id)
            return 201, self._response(db, row, parent)

        try:
            with transaction(self.sessions.sessions, "repayments") as db:
                result = self.idempotency.execute(
                    db,
                    principal,
                    "repayments",
                    identifier,
                    key,
                    body.model_dump(mode="json"),
                    perform,
                    lambda db: self.authorization.commitment(db, principal, identifier),
                )
            return result
        except (SQLAlchemyError, ValueError, TypeError, ValidationError):
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def read(self, principal, identifier, *, detail=False):
        try:
            with transaction(self.sessions.sessions, "repayments") as db:
                if detail:
                    access = self.authorization.repayment(db, principal, identifier, lock=True)
                    parent = db.get(Commitment, access.commitment_id)
                    return self._response(db, db.get(Repayment, identifier), parent)
                self.authorization.commitment(db, principal, identifier, lock=True)
                parent = db.get(Commitment, identifier)
                rows = db.scalars(
                    select(Repayment)
                    .where(Repayment.commitment_id == identifier)
                    .order_by(Repayment.reported_at.desc(), Repayment.id.asc())
                )
                return [self._response(db, row, parent) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, ValidationError):
            raise AuthError("SERVICE_UNAVAILABLE") from None
