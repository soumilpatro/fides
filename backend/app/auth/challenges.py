"""Durable OTP reservations, provider leases, and post-proof account transactions."""

import logging
import math
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.auth_schemas import OtpRequestResponse, SignupOtpVerifyRequest
from app.auth.providers import Outcome, ProviderResult
from app.auth.safety import sensitive_io, utc_now
from app.auth.sessions import SessionService
from app.core.errors import AuthError
from app.core.logging import sanitize_request_id
from app.models.audit_log import AuditLog
from app.models.auth_identity import AuthIdentity
from app.models.auth_otp_challenge import AuthOtpChallenge
from app.models.enums import UserStatus
from app.models.user import User

LIVE = {"SENDING", "PENDING", "CHECKING", "LOCKED", "INDETERMINATE"}
logger = logging.getLogger("fides.auth.challenges")


@dataclass(frozen=True)
class Reservation:
    id: UUID
    operation_id: UUID
    phone: str = field(repr=False)
    intent: str
    provider_key: str
    provider_reference: str | None = field(repr=False)


class ChallengeService:
    def __init__(self, sessions, settings, provider, *, clock=None):
        self.sessions = sessions
        self.settings = settings
        self.provider = provider
        self.clock = clock
        self.session_service = SessionService(sessions, settings, clock=clock)
        self.limiter = self.session_service.limiter

    def _lock_phone(self, db, phone):
        # Shared across both intents, requests, checks and post-proof signup.
        key = int.from_bytes(self.limiter.subject("phone", phone)[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    @staticmethod
    def _transition(challenge, state):
        challenge.state = state
        challenge.operation_id = challenge.operation_expires_at = None

    def _state_error(self, challenge, now):
        if challenge.state == "CONSUMED":
            return AuthError("OTP_REPLAYED")
        if now >= challenge.expires_at:
            self._transition(challenge, "EXPIRED")
            return AuthError("OTP_EXPIRED")
        if challenge.state in {"SENDING", "CHECKING"}:
            if now >= challenge.operation_expires_at:
                self._transition(challenge, "INDETERMINATE")
                return AuthError("OTP_CHALLENGE_UNAVAILABLE")
            return AuthError("AUTH_CHALLENGE_BUSY")
        if challenge.state == "LOCKED":
            return AuthError(
                "OTP_RATE_LIMITED", retry_after_seconds=self._remaining(challenge, now)
            )
        if challenge.state in {"INDETERMINATE", "FAILED"}:
            return AuthError("OTP_CHALLENGE_UNAVAILABLE")
        if challenge.state == "EXPIRED":
            return AuthError("OTP_EXPIRED")
        return None

    @staticmethod
    def _remaining(challenge, now):
        return max(0, math.ceil((challenge.expires_at - now).total_seconds()))

    def _reserve(self, challenge, now, state):
        challenge.state = state
        challenge.operation_id = uuid4()
        challenge.operation_expires_at = now + timedelta(
            seconds=self.settings.otp_provider_operation_lease_seconds
        )
        return Reservation(
            challenge.id,
            challenge.operation_id,
            challenge.phone_e164,
            challenge.intent,
            challenge.provider_key,
            challenge.provider_reference,
        )

    @staticmethod
    def _unwrap(result):
        if isinstance(result, AuthError):
            logger.info("OTP operation rejected: %s", result.code)
            raise result
        return result

    async def request(self, body, *, ip, request_id=None):
        reservation = self._unwrap(await run_in_threadpool(self._request_reservation, body, ip))
        # No checked-out SQL connection survives _request_reservation's return.
        try:
            result = await self.provider.request_verification(reservation.phone, reservation.intent)
        except Exception:
            result = ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
        return self._unwrap(await run_in_threadpool(self._finish_request, reservation, result))

    def _request_reservation(self, body, ip):
        budget_retry = 0
        try:
            self.limiter.otp_request(phone=body.phone, ip=ip)
        except AuthError as error:
            if error.status_code != 429:
                raise
            budget_retry = int(error.headers["Retry-After"])
        try:
            with sensitive_io(), self.sessions.begin() as db:
                self._lock_phone(db, body.phone)
                now = utc_now(self.clock, db)
                challenge = db.scalar(
                    select(AuthOtpChallenge)
                    .where(
                        AuthOtpChallenge.phone_e164 == body.phone,
                        AuthOtpChallenge.intent == body.intent,
                        AuthOtpChallenge.state.in_(LIVE),
                    )
                    .with_for_update()
                )
                if challenge:
                    error = self._state_error(challenge, now)
                    if challenge.state == "EXPIRED":
                        db.flush()  # release this intent's partial-unique reservation
                        challenge = None
                    elif error and error.status_code == 429:
                        budget_retry = max(budget_retry, int(error.headers["Retry-After"]))
                    elif error and not budget_retry:
                        return error
                last = db.scalar(
                    select(func.max(AuthOtpChallenge.last_requested_at)).where(
                        AuthOtpChallenge.phone_e164 == body.phone
                    )
                )
                if last:
                    remaining = math.ceil(
                        (
                            last
                            + timedelta(seconds=self.settings.otp_resend_cooldown_seconds)
                            - now
                        ).total_seconds()
                    )
                    budget_retry = max(budget_retry, remaining)
                if budget_retry > 0:
                    return AuthError("OTP_RATE_LIMITED", retry_after_seconds=budget_retry)
                if challenge is None:
                    prefix = "fake" if self.settings.otp_provider == "fake" else "twilio_verify_v2"
                    challenge = AuthOtpChallenge(
                        id=uuid4(),
                        phone_e164=body.phone,
                        intent=body.intent,
                        provider_key=f"{prefix}_{body.intent}",
                        created_at=now,
                        expires_at=now + timedelta(seconds=self.settings.otp_challenge_ttl_seconds),
                        verify_attempts=0,
                    )
                    db.add(challenge)
                challenge.last_requested_at = now
                reservation = self._reserve(challenge, now, "SENDING")
            return reservation
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    def _owned(self, db, reservation, state):
        self._lock_phone(db, reservation.phone)
        challenge = db.scalar(
            select(AuthOtpChallenge).where(AuthOtpChallenge.id == reservation.id).with_for_update()
        )
        if (
            challenge is None
            or challenge.state != state
            or challenge.operation_id != reservation.operation_id
        ):
            return None, AuthError("OTP_CHALLENGE_UNAVAILABLE")
        now = utc_now(self.clock, db)
        if now >= challenge.expires_at:
            self._transition(challenge, "EXPIRED")
            return None, AuthError("OTP_EXPIRED")
        if now >= challenge.operation_expires_at:
            self._transition(challenge, "INDETERMINATE")
            return None, AuthError("OTP_CHALLENGE_UNAVAILABLE")
        return challenge, None

    def _quarantine(self, reservation):
        """Fail closed after a rolled-back finalization, without touching a new owner."""
        try:
            with sensitive_io(), self.sessions.begin() as db:
                self._lock_phone(db, reservation.phone)
                challenge = db.scalar(
                    select(AuthOtpChallenge)
                    .where(AuthOtpChallenge.id == reservation.id)
                    .with_for_update()
                )
                if (
                    challenge is not None
                    and challenge.operation_id == reservation.operation_id
                    and challenge.state in {"SENDING", "CHECKING"}
                ):
                    now = utc_now(self.clock, db)
                    self._transition(
                        challenge, "EXPIRED" if now >= challenge.expires_at else "INDETERMINATE"
                    )
        except SQLAlchemyError:
            # The durable reservation still prevents reuse until its lease expires.
            logger.error("OTP finalization quarantine unavailable")

    def _provider_error(self, challenge, result, now, *, checking):
        allowed = {
            Outcome.RATE_LIMITED,
            Outcome.TRANSIENT_FAILURE,
            Outcome.CONFIGURATION_FAILURE,
            *(
                (Outcome.INVALID_CODE, Outcome.EXPIRED, Outcome.CHALLENGE_UNAVAILABLE)
                if checking
                else (Outcome.DELIVERY_UNAVAILABLE,)
            ),
        }
        if result.uncertain or result.outcome not in allowed:
            self._transition(challenge, "INDETERMINATE")
            return AuthError("AUTH_PROVIDER_UNAVAILABLE")
        if result.outcome == Outcome.EXPIRED:
            self._transition(challenge, "EXPIRED")
            return AuthError("OTP_EXPIRED")
        if result.outcome == Outcome.CHALLENGE_UNAVAILABLE:
            self._transition(challenge, "INDETERMINATE")
            return AuthError("OTP_CHALLENGE_UNAVAILABLE")
        exhausted = (
            checking and challenge.verify_attempts >= self.settings.otp_verify_challenge_limit
        )
        limited = result.outcome == Outcome.RATE_LIMITED
        self._transition(
            challenge,
            "LOCKED"
            if checking and (exhausted or limited)
            else ("PENDING" if challenge.provider_reference else "FAILED"),
        )
        if limited:
            return AuthError(
                "OTP_RATE_LIMITED",
                retry_after_seconds=max(
                    result.retry_after_seconds or 0,
                    self._remaining(challenge, now)
                    if checking
                    else self.settings.otp_resend_cooldown_seconds,
                ),
            )
        if result.outcome == Outcome.INVALID_CODE and checking:
            return AuthError("OTP_INVALID")
        if result.outcome == Outcome.DELIVERY_UNAVAILABLE and not checking:
            return AuthError("OTP_DELIVERY_UNAVAILABLE")
        return AuthError("AUTH_PROVIDER_UNAVAILABLE")

    def _finish_request(self, reservation, result):
        try:
            with sensitive_io(), self.sessions.begin() as db:
                challenge, error = self._owned(db, reservation, "SENDING")
                if error:
                    return error
                deadline = min(challenge.expires_at, challenge.operation_expires_at)
                now = utc_now(self.clock, db)
                if (
                    result.outcome == Outcome.REQUESTED
                    and result.provider_key != reservation.provider_key
                ):
                    self._transition(challenge, "INDETERMINATE")
                    return AuthError("OTP_CHALLENGE_UNAVAILABLE")
                if (
                    result.outcome != Outcome.REQUESTED
                    or result.uncertain
                    or result.provider_key != reservation.provider_key
                ):
                    return self._provider_error(challenge, result, now, checking=False)
                challenge.provider_reference = result.provider_reference
                self._transition(challenge, "PENDING")
                response = OtpRequestResponse(
                    challenge_id=challenge.id,
                    expires_at=challenge.expires_at,
                    message="Verification requested.",
                    resend_after_seconds=max(
                        0,
                        math.ceil(
                            (
                                challenge.last_requested_at
                                + timedelta(seconds=self.settings.otp_resend_cooldown_seconds)
                                - now
                            ).total_seconds()
                        ),
                    ),
                )
                db.flush()
                if utc_now(self.clock, db) >= deadline:
                    raise AuthError("OTP_CHALLENGE_UNAVAILABLE")
            return response
        except AuthError:
            self._quarantine(reservation)
            raise
        except SQLAlchemyError:
            self._quarantine(reservation)
            raise AuthError("SERVICE_UNAVAILABLE") from None

    async def verify(self, body, *, request_id=None):
        # IP limit is an HTTP dependency, so even invalid signup profiles count.
        reservation = self._unwrap(await run_in_threadpool(self._verify_reservation, body))
        try:
            result = await self.provider.verify_stored(
                reservation.provider_key, reservation.provider_reference, body.code
            )
        except Exception:
            result = ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
        return self._unwrap(
            await run_in_threadpool(self._finish_verify, reservation, result, body, request_id)
        )

    def _verify_reservation(self, body):
        try:
            with sensitive_io(), self.sessions() as db:
                snapshot = db.execute(
                    select(AuthOtpChallenge.phone_e164, AuthOtpChallenge.intent).where(
                        AuthOtpChallenge.id == body.challenge_id
                    )
                ).first()
            if snapshot is None:
                return AuthError("OTP_INVALID_CHALLENGE")
            phone = snapshot.phone_e164
            if (snapshot.intent == "signup") != isinstance(body, SignupOtpVerifyRequest):
                return AuthError("VALIDATION_ERROR")
            # This reservation commits independently of all challenge mutations.
            budget_error = None
            try:
                self.limiter.enforce(
                    self.limiter.policies("otp_verify", phone=phone), "OTP_RATE_LIMITED"
                )
            except AuthError as error:
                if error.status_code != 429:
                    raise
                budget_error = error
            with sensitive_io(), self.sessions.begin() as db:
                self._lock_phone(db, phone)
                challenge = db.scalar(
                    select(AuthOtpChallenge)
                    .where(AuthOtpChallenge.id == body.challenge_id)
                    .with_for_update()
                )
                if challenge is None:
                    return AuthError("OTP_INVALID_CHALLENGE")
                now = utc_now(self.clock, db)
                error = self._state_error(challenge, now)
                if budget_error:
                    if error and error.status_code == 429:
                        return AuthError(
                            "OTP_RATE_LIMITED",
                            retry_after_seconds=max(
                                int(budget_error.headers["Retry-After"]),
                                int(error.headers["Retry-After"]),
                            ),
                        )
                    return budget_error
                if error:
                    return error
                if (challenge.intent == "signup") != isinstance(body, SignupOtpVerifyRequest):
                    return AuthError("VALIDATION_ERROR")
                if challenge.verify_attempts >= self.settings.otp_verify_challenge_limit:
                    self._transition(challenge, "LOCKED")
                    return AuthError(
                        "OTP_RATE_LIMITED", retry_after_seconds=self._remaining(challenge, now)
                    )
                challenge.verify_attempts += 1
                reservation = self._reserve(challenge, now, "CHECKING")
            return reservation
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @staticmethod
    def _audit(db, action, object_id, actor, request_id, *, result="SUCCESS", intent=None):
        metadata = {"request_id": sanitize_request_id(request_id)}
        if intent:
            metadata["intent"] = intent
        db.add(
            AuditLog(
                actor_user_id=actor,
                action=action,
                object_type="User" if action == "ACCOUNT_CREATED" else "Challenge",
                object_id=object_id,
                result=result,
                metadata_=metadata,
            )
        )

    def _account(self, db, challenge, body, now):
        # Called only for explicit, matching provider approval, under phone lock.
        user = db.scalar(
            select(User).where(User.phone_e164 == challenge.phone_e164).with_for_update()
        )
        identity = db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == "phone",
                AuthIdentity.provider_subject == challenge.phone_e164,
            )
        )
        if (user is None) != (identity is None) or (
            user is not None and (identity.user_id != user.id or identity.verified_at is None)
        ):
            logger.error("Inconsistent phone identity persistence after verified proof")
            return user, AuthError("SERVICE_UNAVAILABLE"), False
        if user is not None:
            if user.status == UserStatus.DEACTIVATED:
                return user, AuthError("ACCOUNT_DEACTIVATED"), False
            if user.status != UserStatus.ACTIVE:
                return user, AuthError("ACCOUNT_UNAVAILABLE"), False
            if challenge.intent == "signup":
                return user, AuthError("AUTH_FLOW_NOT_ALLOWED"), False
            return user, None, False
        if challenge.intent == "login":
            return None, AuthError("AUTH_FLOW_NOT_ALLOWED"), False
        user = User(
            id=uuid4(),
            phone_e164=challenge.phone_e164,
            status=UserStatus.ACTIVE,
            display_name=body.display_name,
            timezone=body.timezone,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider="phone",
                provider_subject=challenge.phone_e164,
                verified_at=now,
                created_at=now,
            )
        )
        return user, None, True

    def _finish_verify(self, reservation, result, body, request_id):
        try:
            with sensitive_io(), self.sessions.begin() as db:
                challenge, error = self._owned(db, reservation, "CHECKING")
                if error:
                    return error
                deadline = min(challenge.expires_at, challenge.operation_expires_at)
                now = utc_now(self.clock, db)
                if result.outcome != Outcome.APPROVED or result.uncertain:
                    return self._provider_error(challenge, result, now, checking=True)
                if (
                    result.provider_reference != reservation.provider_reference
                    or result.provider_key != reservation.provider_key
                ):
                    self._transition(challenge, "INDETERMINATE")
                    return AuthError("OTP_CHALLENGE_UNAVAILABLE")
                user, denial, created = self._account(db, challenge, body, now)
                # Account row locking can wait: sample time again before proof consumption.
                now = utc_now(self.clock, db)
                if now >= challenge.expires_at or now >= challenge.operation_expires_at:
                    # Roll back any provisional new account as well.
                    raise AuthError("OTP_CHALLENGE_UNAVAILABLE")
                self._transition(challenge, "CONSUMED")
                challenge.consumed_at = now
                actor = user.id if user else None
                self._audit(
                    db,
                    "AUTH_OTP_VERIFIED",
                    challenge.id,
                    actor,
                    request_id,
                    intent=challenge.intent,
                )
                if denial:
                    self._audit(
                        db,
                        "AUTH_ACCOUNT_ACCESS_DENIED",
                        challenge.id,
                        actor,
                        request_id,
                        result="DENIED",
                        intent=challenge.intent,
                    )
                    response = denial
                else:
                    if created:
                        self._audit(db, "ACCOUNT_CREATED", user.id, user.id, request_id)
                    response = self.session_service._create_locked(
                        db, user, challenge.intent, request_id
                    )
                db.flush()
                if utc_now(self.clock, db) >= deadline:
                    raise AuthError("OTP_CHALLENGE_UNAVAILABLE")
            return response
        except AuthError:
            self._quarantine(reservation)
            raise
        except SQLAlchemyError:
            self._quarantine(reservation)
            raise AuthError("SERVICE_UNAVAILABLE") from None
