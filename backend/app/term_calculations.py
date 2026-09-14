"""B6-D0 flat interest and equal-principal allocation, in integer minor units."""

from app.core.errors import FinancialError


def fixed_interest(principal: int, rate_bps: int | None) -> int:
    return 0 if rate_bps is None else (principal * rate_bps + 5000) // 10000


def allocate_installments(principal: int, interest: int, count: int) -> list[tuple[int, int]]:
    q, iq = principal // count, interest // count
    amounts = [(q, iq)] * (count - 1)
    amounts.append((principal - q * (count - 1), interest - iq * (count - 1)))
    if any(p < 0 or i < 0 or p + i <= 0 for p, i in amounts):
        raise FinancialError("INVALID_AMOUNT")
    return amounts
