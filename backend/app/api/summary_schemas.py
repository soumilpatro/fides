"""Closed B12-D0 response, with exact currency order and safe JSON integers."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from app.api.auth_schemas import AuthSchema, Timezone
from app.api.connection_schemas import ParticipantResponse
from app.api.term_schemas import DateOnly

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


class OccurrenceItem(AuthSchema):
    commitment_id: UUID
    counterparty: ParticipantResponse
    role: Literal["BORROWER", "LENDER"]
    currency: Literal["INR", "USD", "GBP"]
    verified_outstanding_minor: Annotated[StrictInt, Field(ge=1, le=MAX_SAFE_INTEGER)]
    due_date: DateOnly
    due_timezone: Timezone
    schedule_mode: Literal["single", "installments"]
    installment_id: UUID | None


class OccurrenceResponse(AuthSchema):
    items: list[OccurrenceItem]
    next_cursor: str | None
