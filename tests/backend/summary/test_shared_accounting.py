from types import SimpleNamespace

import pytest

from app.financial_calculations import accounting
from app.models.enums import RepaymentStatus


@pytest.mark.parametrize(
    "principal,rate,verified,pending,expected",
    [
        (10000, None, 0, 0, (10000, 10000, 0, 10000)),
        (10000, None, 1000, 9000, (10000, 9000, 9000, 0)),
        (10000, None, 1000, 10000, (10000, 9000, 10000, -1000)),
        (10000, 500, 10500, 1, (10500, 0, 1, -1)),
        (5000, 1, 0, 0, (5001, 5001, 0, 5001)),
    ],
)
def test_shared_capacity_preserves_writer_semantics(principal, rate, verified, pending, expected):
    result = accounting(
        SimpleNamespace(principal_amount_minor=principal, currency="INR"),
        SimpleNamespace(interest_rate_bps=rate),
        {
            RepaymentStatus.VERIFIED: verified,
            RepaymentStatus.PENDING_VERIFICATION: pending,
            RepaymentStatus.DISPUTED: 999999,
            RepaymentStatus.CANCELLED: 999999,
        },
    )
    assert (
        result.obligation,
        result.verified_outstanding,
        result.pending,
        result.reportable_remaining,
    ) == expected


@pytest.mark.parametrize("principal", [0, -1, 1_000_000_000_001, True, 1.0])
def test_invalid_principal_never_calculated(principal):
    with pytest.raises(ValueError):
        accounting(
            SimpleNamespace(principal_amount_minor=principal, currency="INR"),
            SimpleNamespace(interest_rate_bps=None),
            {},
        )


@pytest.mark.parametrize("currency", ["EUR", "inr", "", None])
def test_invalid_currency_never_calculated(currency):
    with pytest.raises(ValueError):
        accounting(
            SimpleNamespace(principal_amount_minor=100, currency=currency),
            SimpleNamespace(interest_rate_bps=None),
            {},
        )


@pytest.mark.parametrize("invalid,verified", [(False, 101), (True, 0)])
def test_no_clamp_or_invalid_association(invalid, verified):
    with pytest.raises(ValueError):
        accounting(
            SimpleNamespace(principal_amount_minor=100, currency="INR"),
            SimpleNamespace(interest_rate_bps=None),
            {RepaymentStatus.VERIFIED: verified},
            invalid,
        )
