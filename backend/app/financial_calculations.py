"""Shared exact accounting over validated, consistently loaded financial inputs.

No database I/O or locking here. Writers retain their parent lock; B12 holds the
actor User lock shared by all current financial writers and batch-loads inputs.
"""

from dataclasses import dataclass

from pydantic import TypeAdapter

from app.api.commitment_schemas import CommitmentRequest
from app.models.enums import RepaymentStatus
from app.term_calculations import fixed_interest

_currency = TypeAdapter(CommitmentRequest.model_fields["currency"].annotation)


@dataclass(frozen=True)
class Capacity:
    obligation: int
    verified_outstanding: int
    pending: int
    reportable_remaining: int


def accounting(commitment, terms, sums, invalid_association=False):
    """Terms validation is shared separately; never clamp invalid outstanding."""
    _currency.validate_python(commitment.currency)
    principal = commitment.principal_amount_minor
    if type(principal) is not int or not 0 < principal <= 1_000_000_000_000:
        raise ValueError("Invalid persisted principal")
    obligation = principal + fixed_interest(principal, terms.interest_rate_bps)
    verified = int(sums.get(RepaymentStatus.VERIFIED, 0))
    pending = int(sums.get(RepaymentStatus.PENDING_VERIFICATION, 0))
    if invalid_association or verified > obligation or verified < 0 or pending < 0:
        raise ValueError("Inconsistent persisted repayment capacity")
    return Capacity(obligation, obligation - verified, pending, obligation - verified - pending)
