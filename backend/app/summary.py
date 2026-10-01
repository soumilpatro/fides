"""B12 read-only, actor-serialized, batched financial summary.

All current financial writers lock both affected Users before financial rows.
Hold the actor lock through every read and projection; no parent locks or writes.
Future writers must preserve this protocol. A fixed evaluation time selects terms.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.summary_schemas import SummaryResponse
from app.auth.safety import auth_operation, utc_now
from app.core.errors import AuthError
from app.financial_calculations import accounting
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.enums import CommitmentStatus
from app.models.repayment import Repayment
from app.terms import validate_terms

INCLUDED = {
    CommitmentStatus.ACTIVE,
    CommitmentStatus.PARTIALLY_REPAID,
    CommitmentStatus.FULLY_REPAID,
}
EXCLUDED = {
    CommitmentStatus.PENDING_CONFIRMATION,
    CommitmentStatus.REJECTED,
    CommitmentStatus.CANCELLED,
}


class SummaryService:
    def __init__(self, sessions):
        self.sessions = sessions

    @auth_operation
    def read(self, principal):
        try:
            with self.sessions.sessions.begin() as db:
                self.sessions.revalidate_user_locked(db, principal)
                now = utc_now(self.sessions.clock, db)
                participation = or_(
                    Commitment.borrower_user_id == principal.user_id,
                    Commitment.lender_user_id == principal.user_id,
                )
                rows = list(db.scalars(select(Commitment).where(participation)))
                if any(row.status not in INCLUDED | EXCLUDED for row in rows):
                    raise ValueError("Unsupported financial state")
                rows = [row for row in rows if row.status in INCLUDED]
                # A scoped subquery avoids one bind parameter per commitment, including
                # accounts with enough obligations to exceed PostgreSQL's bind limit.
                ids = select(Commitment.id).where(participation, Commitment.status.in_(INCLUDED))
                terms = {}
                sums = {}
                invalid = set()
                if rows:
                    # PostgreSQL DISTINCT ON chooses the highest effective version per parent.
                    terms = {
                        row.commitment_id: row
                        for row in db.scalars(
                            select(CommitmentTermsVersion)
                            .where(
                                CommitmentTermsVersion.commitment_id.in_(ids),
                                CommitmentTermsVersion.effective_at <= now,
                            )
                            .distinct(CommitmentTermsVersion.commitment_id)
                            .order_by(
                                CommitmentTermsVersion.commitment_id,
                                CommitmentTermsVersion.version_no.desc(),
                            )
                        )
                    }
                    for identifier, status, amount in db.execute(
                        select(
                            Repayment.commitment_id,
                            Repayment.status,
                            func.sum(Repayment.amount_minor),
                        )
                        .where(Repayment.commitment_id.in_(ids))
                        .group_by(Repayment.commitment_id, Repayment.status)
                    ):
                        sums.setdefault(identifier, {})[status] = amount
                    invalid = set(
                        db.scalars(
                            select(Repayment.commitment_id)
                            .join(Commitment)
                            .where(
                                Repayment.commitment_id.in_(ids),
                                or_(
                                    Repayment.currency != Commitment.currency,
                                    (Repayment.reported_by_user_id != Commitment.borrower_user_id)
                                    & (Repayment.reported_by_user_id != Commitment.lender_user_id),
                                ),
                            )
                            .distinct()
                        )
                    )
                buckets = {
                    currency: {
                        "currency": currency,
                        "borrowed_outstanding_minor": 0,
                        "lent_outstanding_minor": 0,
                        "net_position_minor": 0,
                    }
                    for currency in ("INR", "USD", "GBP")
                }
                for row in rows:
                    term = terms.get(row.id)
                    if term is None:
                        raise ValueError("Missing current terms")
                    validate_terms(term, row)
                    amount = accounting(
                        row, term, sums.get(row.id, {}), row.id in invalid
                    ).verified_outstanding
                    if row.borrower_user_id == row.lender_user_id:
                        raise ValueError("Invalid participants")
                    if row.status == CommitmentStatus.FULLY_REPAID and amount != 0:
                        raise ValueError("Inconsistent fully repaid state")
                    bucket = buckets[row.currency]
                    side = "borrowed" if row.borrower_user_id == principal.user_id else "lent"
                    bucket[f"{side}_outstanding_minor"] += amount
                for bucket in buckets.values():
                    bucket["net_position_minor"] = (
                        bucket["lent_outstanding_minor"] - bucket["borrowed_outstanding_minor"]
                    )
                return SummaryResponse(currencies=tuple(buckets.values()))
        except (SQLAlchemyError, ValueError, TypeError, KeyError, OverflowError):
            raise AuthError("SERVICE_UNAVAILABLE") from None
