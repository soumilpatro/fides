from datetime import date, timedelta

import pytest
from app.api.commitment_schemas import CommitmentRequest
from app.api.term_schemas import TermsRequest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"interest_type": "none"},
        {"interest_type": None},
        {"interest_type": True},
        {"interest_type": "FIXED"},
        {"interest_type": "CUSTOM"},
        {"interest_type": "NONE", "interest_rate_bps": 1},
        {"interest_type": "SIMPLE_FIXED"},
        *[
            {"interest_type": "SIMPLE_FIXED", "interest_rate_bps": x}
            for x in [None, 0, -1, 10001, True, 1.0, "1"]
        ],
        *[
            {"interest_type": "NONE", "grace_period_days": x}
            for x in [None, True, "0", 0.0, -1, 366]
        ],
        *[
            {"interest_type": "NONE", "due_date": x}
            for x in [
                False,
                123,
                "2026-1-01",
                "20260201",
                "2026-02-30",
                "2026-01-01T00:00:00Z",
                " 2026-01-01",
            ]
        ],
        *[
            {"interest_type": "NONE", "installment_dates": x}
            for x in [
                [],
                ["2026-01-01"],
                ["2026-01-01"] * 2,
                ["2026-01-02", "2026-01-01"],
                ["2026-01-01", "bad"],
                "2026-01-01",
                False,
            ]
        ],
        {
            "interest_type": "NONE",
            "due_date": "2026-01-01",
            "installment_dates": ["2026-01-01", "2026-02-01"],
        },
        *[
            {"interest_type": "NONE", x: 1}
            for x in [
                "currency",
                "principal",
                "installment_amounts",
                "due_timezone",
                "schedule_definition",
                "version_no",
            ]
        ],
    ],
)
def test_strict_invalid_terms(values):
    with pytest.raises(ValidationError):
        TermsRequest.model_validate(values)


@pytest.mark.parametrize("rate", [1, 10000])
def test_interest_bounds(rate):
    assert (
        TermsRequest(interest_type="SIMPLE_FIXED", interest_rate_bps=rate).interest_rate_bps == rate
    )


@pytest.mark.parametrize("grace", [0, 365])
def test_grace_bounds(grace):
    assert TermsRequest(interest_type="NONE", grace_period_days=grace).grace_period_days == grace


@pytest.mark.parametrize("count", [2, 60, 61])
def test_installment_count(count):
    days = [(date(2024, 2, 28) + timedelta(days=i)).isoformat() for i in range(count)]
    if count == 61:
        with pytest.raises(ValidationError):
            TermsRequest(interest_type="NONE", installment_dates=days)
    else:
        assert (
            len(TermsRequest(interest_type="NONE", installment_dates=days).installment_dates)
            == count
        )


def test_defaults_and_nulls():
    a = TermsRequest(interest_type="NONE")
    b = TermsRequest(
        interest_type="NONE",
        due_date=None,
        interest_rate_bps=None,
        installment_dates=None,
        grace_period_days=0,
    )
    assert a.model_dump() == b.model_dump()
    assert a.schedule_mode == "none"
    body = dict(
        connection_id="00000000-0000-0000-0000-000000000001",
        actor_role="LENDER",
        type="IOU",
        principal_amount_minor=1,
        currency="INR",
    )
    assert CommitmentRequest(**body).terms is None
    with pytest.raises(ValidationError):
        CommitmentRequest(**body, terms=None)
