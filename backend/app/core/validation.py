"""Reusable phone/profile normalization; never include input values in errors."""

import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from pydantic_core import PydanticCustomError


def normalize_phone(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Phone must be a string.")
    phone = value.strip()
    if not re.fullmatch(r"\+[1-9][0-9]{1,14}", phone):
        raise PydanticCustomError("invalid_phone", "Enter a valid international phone number.")
    try:
        number = phonenumbers.parse(phone, None)
    except phonenumbers.NumberParseException:
        raise PydanticCustomError(
            "invalid_phone", "Enter a valid international phone number."
        ) from None
    if not phonenumbers.is_valid_number(number):
        raise PydanticCustomError("invalid_phone", "Enter a valid international phone number.")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_display_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Display name must be a string.")
    value = unicodedata.normalize("NFC", value)
    # Check before trimming: control characters must not disappear into whitespace.
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("Display name must not contain control characters.")
    value = value.strip()
    if not 1 <= len(value) <= 100:
        raise ValueError("Display name must contain 1–100 Unicode code points.")
    return value


def normalize_timezone(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Timezone must be a string.")
    value = value.strip()
    if not 1 <= len(value) <= 64:
        raise ValueError("Timezone must contain 1–64 characters.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Timezone must be a valid IANA identifier.") from None
    return value
