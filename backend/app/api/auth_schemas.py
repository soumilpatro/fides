"""B2-D2 wire schemas only; stored-intent checks belong to later orchestration."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.validation import normalize_display_name, normalize_phone, normalize_timezone

Phone = Annotated[StrictStr, AfterValidator(normalize_phone)]
DisplayName = Annotated[StrictStr, AfterValidator(normalize_display_name)]
Timezone = Annotated[StrictStr, AfterValidator(normalize_timezone)]
OtpCode = Annotated[StrictStr, StringConstraints(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")]


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_utc)]


class AuthSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class OtpRequest(AuthSchema):
    intent: Literal["signup", "login"]
    phone: Phone = Field(repr=False)


class OtpRequestResponse(AuthSchema):
    challenge_id: UUID
    expires_at: UtcDatetime
    resend_after_seconds: Annotated[int, Field(strict=True, ge=0)]
    message: Literal["Verification requested."]


class LoginOtpVerifyRequest(AuthSchema):
    challenge_id: UUID
    code: OtpCode = Field(repr=False)


class SignupOtpVerifyRequest(LoginOtpVerifyRequest):
    display_name: DisplayName = Field(repr=False)
    timezone: Timezone = Field(repr=False)


OtpVerifyRequest = SignupOtpVerifyRequest | LoginOtpVerifyRequest


class RefreshRequest(AuthSchema):
    refresh_token: Annotated[StrictStr, StringConstraints(min_length=1, max_length=512)] = Field(
        repr=False
    )


class MeResponse(AuthSchema):
    id: UUID
    phone_e164: StrictStr | None = Field(repr=False)
    display_name: StrictStr = Field(repr=False)
    timezone: StrictStr
    status: Literal["ACTIVE"]
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CredentialResponse(AuthSchema):
    access_token: StrictStr = Field(repr=False)
    refresh_token: StrictStr = Field(repr=False)
    token_type: Literal["Bearer"]
    access_expires_at: UtcDatetime
    refresh_expires_at: UtcDatetime
    user: MeResponse


class ProfileUpdateRequest(AuthSchema):
    model_config = ConfigDict(json_schema_extra={"minProperties": 1})
    # None is an internal omission sentinel, never an accepted supplied value.
    # Keeping the annotation non-null also keeps JSON Schema non-nullable.
    display_name: DisplayName = Field(default=None, repr=False)
    timezone: Timezone = Field(default=None, repr=False)

    @model_validator(mode="after")
    def require_change_fields(self) -> "ProfileUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required.")
        return self


class EmptyAuthRequest(AuthSchema):
    """Optional body for logout/deactivate: if supplied, it must be an empty object."""


class DeactivationResponse(AuthSchema):
    status: Literal["DEACTIVATED"]
    deactivated_at: UtcDatetime


class LogoutResponse(AuthSchema):
    logged_out: Literal[True]

    @field_validator("logged_out", mode="before")
    @classmethod
    def require_boolean_true(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("Successful logout must report boolean true.")
        return True
