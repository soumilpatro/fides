import pytest
from app.core.errors import FinancialError
from app.term_calculations import allocate_installments, fixed_interest


@pytest.mark.parametrize(
    "principal,rate,expected",
    [
        (10000, 500, 500),
        (1, 4999, 0),
        (1, 5000, 1),
        (1, 5001, 1),
        (1000000000000, 10000, 1000000000000),
        (12345, None, 0),
        (9999, 1, 1),
    ],
)
def test_fixed_interest(principal, rate, expected):
    assert fixed_interest(principal, rate) == expected
    assert fixed_interest(principal, rate) == expected


@pytest.mark.parametrize(
    "principal,rate,count",
    [
        (10000, None, 2),
        (10000, 500, 3),
        (101, 1250, 4),
        (60, 1, 60),
        (1000000000000, 10000, 60),
        (2, None, 2),
        (100, 5000, 3),
    ],
)
def test_reconciliation_and_final_remainder(principal, rate, count):
    interest = fixed_interest(principal, rate)
    rows = allocate_installments(principal, interest, count)
    assert len(rows) == count
    assert sum(p for p, i in rows) == principal
    assert sum(i for p, i in rows) == interest
    assert sum(p + i for p, i in rows) == principal + interest
    assert all(p >= 0 and i >= 0 and p + i > 0 for p, i in rows)
    assert rows[:-1] == [(principal // count, interest // count)] * (count - 1)
    assert rows[-1] == (
        principal - (principal // count) * (count - 1),
        interest - (interest // count) * (count - 1),
    )


@pytest.mark.parametrize("principal,interest,count", [(1, 0, 2), (1, 1, 2), (59, 59, 60)])
def test_zero_total_rejected(principal, interest, count):
    with pytest.raises(FinancialError) as error:
        allocate_installments(principal, interest, count)
    assert error.value.code == "INVALID_AMOUNT"
