"""Closed B12-D0 response, with exact currency order and safe JSON integers."""

from typing import Annotated, Literal

from pydantic import Field, StrictInt, model_validator

from app.api.auth_schemas import AuthSchema

MAX_SAFE_INTEGER = 2**53 - 1
UnsignedMoney = Annotated[StrictInt, Field(ge=0, le=MAX_SAFE_INTEGER)]
SignedMoney = Annotated[StrictInt, Field(ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)]


class CurrencySummary(AuthSchema):
    borrowed_outstanding_minor: UnsignedMoney
    lent_outstanding_minor: UnsignedMoney
    net_position_minor: SignedMoney

    @model_validator(mode="after")
    def net_matches(self):
        if self.net_position_minor != self.lent_outstanding_minor - self.borrowed_outstanding_minor:
            raise ValueError("Inconsistent net position")
        return self


class INRSummary(CurrencySummary):
    currency: Literal["INR"]


class USDSummary(CurrencySummary):
    currency: Literal["USD"]


class GBPSummary(CurrencySummary):
    currency: Literal["GBP"]


class SummaryResponse(AuthSchema):
    currencies: tuple[INRSummary, USDSummary, GBPSummary]
