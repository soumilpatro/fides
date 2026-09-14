"""Closed B6-D0 inputs and projections; internal schedule JSON is never public."""

import re
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, StrictInt, StrictStr, model_validator

from app.api.auth_schemas import AuthSchema, UtcDatetime
from app.api.connection_schemas import ParticipantResponse
from app.models.enums import InstallmentStatus


def date_only(value):
    if type(value) is date:
        return value
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("Expected YYYY-MM-DD")
    return date.fromisoformat(value)


DateOnly = Annotated[date, BeforeValidator(date_only)]
ScheduleMode = Literal["none", "single", "installments"]


class TermsRequest(AuthSchema):
    due_date: DateOnly | None = None
    interest_type: Literal["NONE", "SIMPLE_FIXED"]
    interest_rate_bps: Annotated[StrictInt, Field(ge=1, le=10000)] | None = None
    grace_period_days: Annotated[StrictInt, Field(ge=0, le=365)] = 0
    installment_dates: Annotated[list[DateOnly], Field(min_length=2, max_length=60)] | None = None

    @model_validator(mode="after")
    def combinations(self):
        if (self.interest_type == "NONE") != (self.interest_rate_bps is None):
            raise ValueError("Interest rate must match interest type")
        if self.due_date is not None and self.installment_dates is not None:
            raise ValueError("Choose a due date or installments")
        if self.installment_dates is not None and any(
            a >= b for a, b in zip(self.installment_dates, self.installment_dates[1:], strict=False)
        ):
            raise ValueError("Installment dates must strictly increase")
        return self

    @property
    def schedule_mode(self) -> ScheduleMode:
        return "installments" if self.installment_dates else "single" if self.due_date else "none"


class TermsVersionResponse(AuthSchema):
    id: UUID
    version_no: StrictInt
    effective_at: UtcDatetime
    due_date: DateOnly | None
    interest_type: Literal["NONE", "SIMPLE_FIXED"]
    interest_rate_bps: StrictInt | None
    grace_period_days: StrictInt
    schedule_mode: ScheduleMode
    due_timezone: StrictStr | None = Field(
        description="Null for legacy B5 terms without a snapshot."
    )
    installment_dates: list[DateOnly] | None
    created_by: ParticipantResponse
    created_at: UtcDatetime


class TermsResponse(AuthSchema):
    commitment_id: UUID
    currency: Literal["INR", "USD", "GBP"]
    current_terms_version_id: UUID
    versions: list[TermsVersionResponse]


class InstallmentResponse(AuthSchema):
    id: UUID
    terms_version_id: UUID
    sequence_no: StrictInt
    due_date: DateOnly
    principal_amount_minor: StrictInt
    interest_amount_minor: StrictInt
    total_due_minor: StrictInt
    currency: Literal["INR", "USD", "GBP"]
    status: InstallmentStatus
    created_at: UtcDatetime
    updated_at: UtcDatetime
