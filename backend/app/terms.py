"""B6 initial terms persistence and participant-only historical reads.

Creation runs inside the B5 transaction after affected User/Connection locks.
Reads lock the parent through B3 so future version writers can serialize there.
Legacy B5 metadata stays null: a missing historical timezone is never guessed.
"""

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.term_schemas import (
    InstallmentResponse,
    TermsRequest,
    TermsResponse,
    TermsVersionResponse,
)
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation, utc_now
from app.core.errors import AuthError, FinancialError
from app.core.validation import normalize_timezone
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.enums import InterestType
from app.models.user import User
from app.term_calculations import allocate_installments, fixed_interest


def create_terms(db, commitment, supplied, now):
    terms = supplied or TermsRequest(interest_type="NONE")
    metadata = None
    if supplied is not None:
        timezone = db.scalar(select(User.timezone).where(User.id == commitment.borrower_user_id))
        try:
            timezone = normalize_timezone(timezone)
        except (ValueError, TypeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None
        metadata = {
            "schedule_mode": terms.schedule_mode,
            "due_timezone": timezone,
            "installment_dates": terms.model_dump(mode="json")["installment_dates"],
        }
    dates = terms.installment_dates or []
    amounts = (
        allocate_installments(
            commitment.principal_amount_minor,
            fixed_interest(commitment.principal_amount_minor, terms.interest_rate_bps),
            len(dates),
        )
        if dates
        else []
    )
    row = CommitmentTermsVersion(
        commitment_id=commitment.id,
        version_no=1,
        effective_at=now,
        due_date=terms.due_date,
        interest_type=terms.interest_type,
        interest_rate_bps=terms.interest_rate_bps,
        grace_period_days=terms.grace_period_days,
        schedule_definition=metadata,
        created_by_user_id=commitment.created_by_user_id,
        created_at=now,
    )
    db.add(row)
    db.flush()
    for sequence, (due_date, (principal, interest)) in enumerate(
        zip(dates, amounts, strict=True), 1
    ):
        db.add(
            CommitmentInstallment(
                commitment_id=commitment.id,
                terms_version_id=row.id,
                sequence_no=sequence,
                due_date=due_date,
                principal_amount_minor=principal,
                interest_amount_minor=interest,
                total_due_minor=principal + interest,
                status="PENDING",
                created_at=now,
                updated_at=now,
            )
        )
    db.flush()
    return row


def validate_terms(row, commitment):
    """Validate stored terms without I/O; callers provide a consistent financial snapshot."""
    if row.commitment_id != commitment.id:
        raise ValueError("Terms belong to another commitment")
    if row.created_by_user_id not in (commitment.borrower_user_id, commitment.lender_user_id):
        raise ValueError("Terms creator is not a participant")
    metadata = row.schedule_definition
    timezone = None
    dates = None
    if metadata is None:
        if (
            row.interest_type != InterestType.NONE
            or row.interest_rate_bps is not None
            or row.due_date is not None
            or row.grace_period_days != 0
        ):
            raise ValueError("Invalid legacy terms")
    else:
        if not isinstance(metadata, dict) or set(metadata) != {
            "schedule_mode",
            "due_timezone",
            "installment_dates",
        }:
            raise ValueError("Invalid schedule metadata")
        timezone = normalize_timezone(metadata["due_timezone"])
        dates = metadata["installment_dates"]
    logical = TermsRequest(
        due_date=row.due_date,
        interest_type=InterestType(row.interest_type).value,
        interest_rate_bps=row.interest_rate_bps,
        grace_period_days=row.grace_period_days,
        installment_dates=dates,
    )
    if row.version_no < 1 or (metadata and metadata["schedule_mode"] != logical.schedule_mode):
        raise ValueError("Invalid version or schedule mode")
    return logical, timezone


def project_terms(db, row, commitment):
    logical, timezone = validate_terms(row, commitment)
    creator = db.execute(
        select(User.id, User.display_name).where(User.id == row.created_by_user_id)
    ).one()
    return TermsVersionResponse(
        id=row.id,
        version_no=row.version_no,
        effective_at=row.effective_at,
        due_date=logical.due_date,
        interest_type=logical.interest_type,
        interest_rate_bps=logical.interest_rate_bps,
        grace_period_days=logical.grace_period_days,
        schedule_mode=logical.schedule_mode,
        due_timezone=timezone,
        installment_dates=logical.installment_dates,
        created_by={"id": creator.id, "display_name": creator.display_name},
        created_at=row.created_at,
    )


class TermsService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.authorization = AuthorizationService(sessions)

    @auth_operation
    def read(self, principal, identifier, *, installments=False):
        try:
            with self.sessions.sessions.begin() as db:
                self.authorization.commitment(db, principal, identifier, lock=True)
                commitment = db.get(Commitment, identifier)
                rows = list(
                    db.scalars(
                        select(CommitmentTermsVersion)
                        .where(CommitmentTermsVersion.commitment_id == identifier)
                        .order_by(CommitmentTermsVersion.version_no)
                    )
                )
                now = utc_now(self.sessions.clock, db)
                eligible = [row for row in rows if row.effective_at <= now]
                if not eligible:
                    raise ValueError("No authoritative terms")
                current = eligible[-1]
                if not installments:
                    return TermsResponse(
                        commitment_id=identifier,
                        currency=commitment.currency,
                        current_terms_version_id=current.id,
                        versions=[project_terms(db, row, commitment) for row in rows],
                    )
                projection = project_terms(db, current, commitment)
                # Query by version alone too, to detect inconsistent cross-parent FKs.
                installments_rows = list(
                    db.scalars(
                        select(CommitmentInstallment)
                        .where(CommitmentInstallment.terms_version_id == current.id)
                        .order_by(CommitmentInstallment.sequence_no)
                    )
                )
                dates = projection.installment_dates or []
                if len(installments_rows) != len(dates):
                    raise ValueError("Incomplete schedule")
                amounts = (
                    allocate_installments(
                        commitment.principal_amount_minor,
                        fixed_interest(
                            commitment.principal_amount_minor, current.interest_rate_bps
                        ),
                        len(dates),
                    )
                    if dates
                    else []
                )
                result = []
                for row, due, (p, i) in zip(installments_rows, dates, amounts, strict=True):
                    if (
                        row.commitment_id != identifier
                        or row.sequence_no < 1
                        or row.due_date != due
                        or row.principal_amount_minor != p
                        or row.interest_amount_minor != i
                        or row.total_due_minor != p + i
                    ):
                        raise ValueError("Inconsistent installment")
                    result.append(
                        InstallmentResponse(
                            id=row.id,
                            terms_version_id=row.terms_version_id,
                            sequence_no=row.sequence_no,
                            due_date=row.due_date,
                            principal_amount_minor=p,
                            interest_amount_minor=i,
                            total_due_minor=p + i,
                            currency=commitment.currency,
                            status=row.status,
                            created_at=row.created_at,
                            updated_at=row.updated_at,
                        )
                    )
                return result
        except (SQLAlchemyError, ValidationError, ValueError, TypeError, FinancialError):
            raise AuthError("SERVICE_UNAVAILABLE") from None
