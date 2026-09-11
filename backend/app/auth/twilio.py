"""Direct Twilio Verify v2 REST, isolated services and fail-closed result mapping.

Wire contract: https://www.twilio.com/docs/verify/api/verification-check
Provider POSTs have no automatic retries. Cancellation/transport uncertainty
must be quarantined by the later challenge-operation lease coordinator.
"""

import asyncio
import logging
import re

import httpx

from app.auth.providers import Intent, Outcome, ProviderResult, valid_code
from app.auth.safety import sensitive_io
from app.config import Settings

logger = logging.getLogger("fides.auth.provider")


class TwilioVerifyProvider:
    ROUTES = {"twilio_verify_v2_signup": "signup", "twilio_verify_v2_login": "login"}

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        if settings.otp_provider != "twilio":
            raise ValueError("Twilio provider must be explicitly configured")
        self._services = {
            "signup": settings.twilio_verify_signup_service_sid,
            "login": settings.twilio_verify_login_service_sid,
        }
        self._budget = settings.otp_provider_operation_budget_seconds
        self._client = httpx.AsyncClient(
            base_url="https://verify.twilio.com/v2/Services/",
            auth=httpx.BasicAuth(
                settings.twilio_api_key_sid, settings.twilio_api_key_secret.get_secret_value()
            ),
            timeout=httpx.Timeout(
                connect=settings.otp_provider_connect_timeout_seconds,
                read=settings.otp_provider_read_timeout_seconds,
                write=settings.otp_provider_write_timeout_seconds,
                pool=settings.otp_provider_pool_timeout_seconds,
            ),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        )

    async def aclose(self):
        with sensitive_io():
            await self._client.aclose()

    async def request_verification(self, phone_e164: str, intent: Intent) -> ProviderResult:
        return await self._operation(intent, "Verifications", {"To": phone_e164, "Channel": "sms"})

    async def verify_code(
        self, provider_reference: str, code: str, intent: Intent
    ) -> ProviderResult:
        if not isinstance(provider_reference, str) or not re.fullmatch(
            r"VE[0-9a-fA-F]{32}", provider_reference
        ):
            return ProviderResult(Outcome.CHALLENGE_UNAVAILABLE)
        if not valid_code(code):
            return ProviderResult(Outcome.INVALID_CODE)
        return await self._operation(
            intent, "VerificationCheck", {"VerificationSid": provider_reference, "Code": code}
        )

    async def verify_stored(
        self, provider_key: str, provider_reference: str, code: str
    ) -> ProviderResult:
        intent = self.ROUTES.get(provider_key)
        if intent is None:
            return ProviderResult(Outcome.CONFIGURATION_FAILURE)
        return await self.verify_code(provider_reference, code, intent)

    async def _operation(self, intent, resource, data):
        if intent not in self._services:
            return ProviderResult(Outcome.CONFIGURATION_FAILURE)
        try:
            with sensitive_io():
                async with asyncio.timeout(self._budget):
                    response = await self._client.post(
                        f"{self._services[intent]}/{resource}", data=data
                    )
                result = self._normalize(response, intent, resource, data.get("VerificationSid"))
        except (httpx.RequestError, TimeoutError):
            # Includes timeouts after the provider may have approved/sent a code.
            result = ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
        if result.outcome not in {Outcome.REQUESTED, Outcome.APPROVED}:
            logger.info("OTP provider outcome: %s", result.outcome.value)
        return result

    def _normalize(self, response, intent, resource, reference):
        checking = resource == "VerificationCheck"
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        code = body.get("code")
        if type(code) is not int:
            code = None
        status = response.status_code
        if status == 404:
            return ProviderResult(
                Outcome.CHALLENGE_UNAVAILABLE if checking else Outcome.CONFIGURATION_FAILURE
            )
        if status in {401, 403}:
            return ProviderResult(Outcome.CONFIGURATION_FAILURE)
        # A failing upstream can attach a stale/misleading application code.
        # HTTP server failure remains uncertain regardless of that body.
        if status >= 500:
            return ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
        if status == 429 or (status >= 400 and code in {60202, 60203}):
            raw_retry = response.headers.get("Retry-After", "")
            retry = int(raw_retry) if re.fullmatch(r"[0-9]{1,9}", raw_retry) else None
            return ProviderResult(Outcome.RATE_LIMITED, retry_after_seconds=retry)
        if status >= 400:
            # 60205 is a known unsupported SMS destination. Do not expose the
            # provider's free-form message or infer InvalidCode from all 400s.
            if not checking and code == 60205:
                return ProviderResult(Outcome.DELIVERY_UNAVAILABLE)
            return ProviderResult(Outcome.CONFIGURATION_FAILURE)
        if status not in {200, 201}:
            return ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
        sid = body.get("sid")
        if not isinstance(sid, str) or not re.fullmatch(r"VE[0-9a-fA-F]{32}", sid):
            return ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
        if body.get("service_sid") != self._services[intent] or (checking and sid != reference):
            return ProviderResult(
                Outcome.CHALLENGE_UNAVAILABLE if checking else Outcome.TRANSIENT_FAILURE,
                uncertain=True,
            )
        state = body.get("status")
        if not isinstance(state, str):
            return ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
        route = f"twilio_verify_v2_{intent}"
        if checking:
            outcome = {
                "approved": Outcome.APPROVED,
                "pending": Outcome.INVALID_CODE,
                "expired": Outcome.EXPIRED,
                "max_attempts_reached": Outcome.RATE_LIMITED,
                "canceled": Outcome.CHALLENGE_UNAVAILABLE,
                "deleted": Outcome.CHALLENGE_UNAVAILABLE,
                "failed": Outcome.CHALLENGE_UNAVAILABLE,
            }.get(state)
            if outcome is None:
                return ProviderResult(Outcome.CHALLENGE_UNAVAILABLE, uncertain=True)
            return ProviderResult(outcome, sid, route)
        if state == "pending":
            return ProviderResult(Outcome.REQUESTED, sid, route)
        if state == "max_attempts_reached":
            return ProviderResult(Outcome.RATE_LIMITED)
        if state == "failed":
            return ProviderResult(Outcome.DELIVERY_UNAVAILABLE)
        return ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
