"""Provider-neutral outcomes and a deterministic, explicitly selected local fake."""

import hmac
import re
import threading
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol

from app.auth.safety import Clock, utc_now
from app.config import Settings

Intent = Literal["signup", "login"]


class Outcome(StrEnum):
    REQUESTED = "Requested"
    APPROVED = "Approved"
    INVALID_CODE = "InvalidCode"
    EXPIRED = "Expired"
    RATE_LIMITED = "RateLimited"
    CHALLENGE_UNAVAILABLE = "ChallengeUnavailable"
    DELIVERY_UNAVAILABLE = "DeliveryUnavailable"
    TRANSIENT_FAILURE = "TransientFailure"
    CONFIGURATION_FAILURE = "ConfigurationFailure"


@dataclass(frozen=True)
class ProviderResult:
    outcome: Outcome
    provider_reference: str | None = field(default=None, repr=False)
    provider_key: str | None = None
    retry_after_seconds: int | None = None
    uncertain: bool = False

    def __post_init__(self):
        if not isinstance(self.outcome, Outcome) or type(self.uncertain) is not bool:
            raise ValueError("Invalid provider outcome")
        if self.outcome in {Outcome.APPROVED, Outcome.REQUESTED}:
            if (
                self.uncertain
                or not isinstance(self.provider_reference, str)
                or not self.provider_reference
                or not isinstance(self.provider_key, str)
                or not self.provider_key
            ):
                raise ValueError("Provider success requires a certain, identified challenge")
        if self.retry_after_seconds is not None and (
            type(self.retry_after_seconds) is not int or self.retry_after_seconds < 0
        ):
            raise ValueError("Invalid provider retry interval")


class OtpProvider(Protocol):
    async def aclose(self) -> None:
        """Release provider resources at application-lifespan shutdown."""
        ...

    async def request_verification(self, phone_e164: str, intent: Intent) -> ProviderResult: ...
    async def verify_code(
        self, provider_reference: str, code: str, intent: Intent
    ) -> ProviderResult: ...
    async def verify_stored(
        self, provider_key: str, provider_reference: str, code: str
    ) -> ProviderResult: ...


def valid_code(code: object) -> bool:
    return isinstance(code, str) and re.fullmatch(r"[0-9]{6}", code, flags=re.ASCII) is not None


@dataclass(repr=False)
class _FakeChallenge:
    intent: Intent
    expires_at: datetime
    attempts: int = 0
    consumed: bool = False


class FakeOtpProvider:
    """In-memory test proof only. Never selected by a production fallback.

    ``before_operation`` can park operations at test barriers without holding a
    state lock. Scripted outcomes can model a provider whose result is uncertain.
    Resends reuse the original reference/deadline/attempts until expiry/consumption.
    """

    TEST_CODES = {"signup": "123456", "login": "654321"}

    async def aclose(self) -> None:
        """The fake owns no network resources."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        ttl_seconds=600,
        attempt_limit=5,
        before_operation: Callable[[str, Intent], Awaitable[None]] | None = None,
    ):
        self.clock = clock
        self.ttl_seconds = ttl_seconds
        self.attempt_limit = attempt_limit
        self.before_operation = before_operation
        self._lock = threading.Lock()
        self._sequence = 0
        self._active = {}
        self._challenges = {}
        self._scripts = defaultdict(deque)

    def script(self, operation: str, intent: Intent, *results: ProviderResult) -> None:
        if operation not in {"request", "verify"} or intent not in self.TEST_CODES:
            raise ValueError("Invalid fake provider script route")
        # Success always comes from the normal single-use state machine. Scripts
        # inject failures, not fabricated proof for missing/expired/consumed rows.
        if any(result.outcome in {Outcome.REQUESTED, Outcome.APPROVED} for result in results):
            raise ValueError("Fake provider success must use the challenge state machine")
        with self._lock:
            self._scripts[(operation, intent)].extend(results)

    async def _before(self, operation, intent):
        if self.before_operation:
            await self.before_operation(operation, intent)

    async def request_verification(self, phone_e164: str, intent: Intent) -> ProviderResult:
        if intent not in self.TEST_CODES:
            return ProviderResult(Outcome.CONFIGURATION_FAILURE)
        await self._before("request", intent)
        with self._lock:
            scripted = self._scripts[("request", intent)]
            if scripted:
                return scripted.popleft()
            now = utc_now(self.clock)
            reference = self._active.get((phone_e164, intent))
            challenge = self._challenges.get(reference)
            if challenge and not challenge.consumed and now < challenge.expires_at:
                if challenge.attempts >= self.attempt_limit:
                    return ProviderResult(Outcome.RATE_LIMITED)
            else:
                self._sequence += 1
                reference = f"fake-{intent}-{self._sequence}"
                self._challenges[reference] = _FakeChallenge(
                    intent, now + timedelta(seconds=self.ttl_seconds)
                )
                self._active[(phone_e164, intent)] = reference
            return ProviderResult(Outcome.REQUESTED, reference, f"fake_{intent}")

    async def verify_code(
        self, provider_reference: str, code: str, intent: Intent
    ) -> ProviderResult:
        if intent not in self.TEST_CODES:
            return ProviderResult(Outcome.CONFIGURATION_FAILURE)
        if not valid_code(code):
            return ProviderResult(Outcome.INVALID_CODE)
        await self._before("verify", intent)
        with self._lock:
            challenge = self._challenges.get(provider_reference)
            if not challenge or challenge.intent != intent or challenge.consumed:
                return ProviderResult(Outcome.CHALLENGE_UNAVAILABLE)
            if utc_now(self.clock) >= challenge.expires_at:
                return ProviderResult(Outcome.EXPIRED)
            if challenge.attempts >= self.attempt_limit:
                return ProviderResult(Outcome.RATE_LIMITED)
            challenge.attempts += 1
            scripted = self._scripts[("verify", intent)]
            if scripted:
                return scripted.popleft()
            if not hmac.compare_digest(code, self.TEST_CODES[intent]):
                return ProviderResult(Outcome.INVALID_CODE)
            challenge.consumed = True
            return ProviderResult(Outcome.APPROVED, provider_reference, f"fake_{intent}")

    async def verify_stored(
        self, provider_key: str, provider_reference: str, code: str
    ) -> ProviderResult:
        routes = {"fake_signup": "signup", "fake_login": "login"}
        if provider_key not in routes:
            return ProviderResult(Outcome.CONFIGURATION_FAILURE)
        return await self.verify_code(provider_reference, code, routes[provider_key])


def build_provider(
    settings: Settings, *, clock: Clock | None = None, transport=None
) -> OtpProvider:
    if settings.otp_provider == "fake" and settings.app_env not in {"production", "staging"}:
        return FakeOtpProvider(
            clock=clock,
            ttl_seconds=settings.otp_challenge_ttl_seconds,
            attempt_limit=settings.otp_verify_challenge_limit,
        )
    if settings.otp_provider == "twilio":
        from app.auth.twilio import TwilioVerifyProvider

        return TwilioVerifyProvider(settings, transport=transport)
    raise ValueError("No enabled authentication provider")
