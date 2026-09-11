"""Durable PostgreSQL fixed windows, separate from protected-operation transactions."""

import hashlib
import hmac
import ipaddress
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.auth.safety import Clock, auth_operation, sensitive_io, utc_now
from app.config import Settings
from app.core.errors import AuthError
from app.core.validation import normalize_phone
from app.models.auth_rate_limit_bucket import AuthRateLimitBucket


def _address(value: str):
    # Scoped addresses have host-local semantics and are not accepted as public peers.
    if "%" in value:
        raise ValueError("Invalid client address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError("Invalid client address") from None
    return getattr(address, "ipv4_mapped", None) or address


def client_ip(peer: str, forwarded_for: str | None = None, *, trusted_proxies=()) -> str:
    """Explicit CIDR allowlist only. Walk XFF from the trusted right-hand edge.

    Invalid trusted-forwarder input fails closed; callers must not substitute an
    attacker-controlled header or a new random limiter key on failure.
    """
    address = _address(peer)
    networks = tuple(ipaddress.ip_network(value, strict=True) for value in trusted_proxies)
    if any(address in network for network in networks) and forwarded_for is not None:
        hops = forwarded_for.split(",")
        if not 1 <= len(hops) <= 32:
            raise ValueError("Invalid forwarded address chain")
        for hop in reversed(hops):
            if not any(address in network for network in networks):
                break
            address = _address(hop.strip())
    return str(address)


def subject_digest(secret: str, domain: str, value: str | UUID) -> bytes:
    if not secret.strip():
        raise ValueError("Authentication rate-limit secret is required")
    if domain == "phone":
        canonical = normalize_phone(value)
    elif domain == "ip":
        address = _address(str(value))
        canonical = (
            str(address)
            if address.version == 4
            else str(ipaddress.ip_network((address, 64), strict=False))
        )
    elif domain == "session":
        canonical = str(UUID(str(value)))
    else:
        raise ValueError("Unknown rate-limit subject domain")
    return hmac.digest(secret.encode(), f"fides:auth:v1:{domain}\0{canonical}".encode(), "sha256")


@dataclass(frozen=True)
class Policy:
    name: str
    subject: bytes = field(repr=False)
    seconds: int
    limit: int


class RateLimiter:
    def __init__(self, sessions: sessionmaker, settings: Settings, *, clock: Clock | None = None):
        self.sessions = sessions
        self.settings = settings
        self.clock = clock
        self._secret = settings.auth_rate_limit_hmac_secret.get_secret_value()
        if not self._secret.strip():
            raise ValueError("Authentication rate-limit secret is required")

    def subject(self, domain: str, value: str | UUID) -> bytes:
        return subject_digest(self._secret, domain, value)

    def policies(self, operation: str, *, phone=None, ip=None, session_id=None) -> list[Policy]:
        definitions = {
            "otp_request": [
                ("phone", "10m", 600),
                ("phone", "24h", 86400),
                ("ip", "10m", 600),
                ("ip", "24h", 86400),
            ],
            "otp_verify": [("phone", "10m", 600), ("ip", "1m", 60), ("ip", "1h", 3600)],
            "auth_refresh": [("session", "1m", 60), ("ip", "1m", 60)],
        }
        values = {"phone": phone, "ip": ip, "session": session_id}
        result = []
        for domain, suffix, seconds in definitions[operation]:
            if values[domain] is not None:
                name = f"{operation}_{domain}_{suffix}"
                result.append(
                    Policy(
                        name,
                        self.subject(domain, values[domain]),
                        seconds,
                        getattr(self.settings, f"{name}_limit"),
                    )
                )
        if not result:
            raise ValueError("At least one rate-limit subject is required")
        return result

    def otp_request(self, *, ip: str, phone: str) -> None:
        self.enforce(self.policies("otp_request", phone=phone, ip=ip), "OTP_RATE_LIMITED")

    def otp_verify(self, *, ip: str, phone: str | None = None) -> None:
        # Unknown challenges still consume IP allowance.
        self.enforce(self.policies("otp_verify", phone=phone, ip=ip), "OTP_RATE_LIMITED")

    def refresh(self, *, ip: str | None = None, session_id: UUID | None = None) -> None:
        self.enforce(
            self.policies("auth_refresh", ip=ip, session_id=session_id), "AUTH_RATE_LIMITED"
        )

    @auth_operation
    def enforce(self, policies: list[Policy], error_code: str) -> None:
        """Every applicable bucket counts, even when another bucket blocks.

        Counters saturate at their limit. The last allowance succeeds; following
        attempts are denied until the next UTC window. Commit denial counters
        before raising so downstream rollback cannot restore any allowance.
        Never invoke while holding locks needed by another limiter invocation.
        """
        ordered = sorted(policies, key=lambda p: (p.name, p.subject))
        if not ordered:
            raise ValueError("At least one rate-limit policy is required")
        if len({(p.name, p.subject) for p in ordered}) != len(ordered):
            raise ValueError("Duplicate rate-limit policy")
        blocked = 0
        try:
            with sensitive_io(), self.sessions.begin() as db:
                # Window-independent locks allow us to read fresh time AFTER
                # waiting. Sort actual keys, so hash collisions cannot invert order.
                locks = sorted(
                    {
                        int.from_bytes(
                            hashlib.sha256(p.name.encode() + b"\0" + p.subject).digest()[:8],
                            "big",
                            signed=True,
                        )
                        for p in ordered
                    }
                )
                for key in locks:
                    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
                now = utc_now(self.clock, db)
                for policy in ordered:
                    start = datetime.fromtimestamp(
                        math.floor(now.timestamp() / policy.seconds) * policy.seconds, UTC
                    )
                    end = start + timedelta(seconds=policy.seconds)
                    db.execute(
                        insert(AuthRateLimitBucket)
                        .values(
                            policy=policy.name,
                            subject_hash=policy.subject,
                            window_started_at=start,
                            request_count=0,
                            expires_at=end,
                        )
                        .on_conflict_do_nothing()
                    )
                    bucket = db.scalar(
                        select(AuthRateLimitBucket)
                        .where(
                            AuthRateLimitBucket.policy == policy.name,
                            AuthRateLimitBucket.subject_hash == policy.subject,
                            AuthRateLimitBucket.window_started_at == start,
                        )
                        .with_for_update()
                    )
                    if bucket.request_count >= policy.limit:
                        blocked = max(blocked, math.ceil((end - now).total_seconds()))
                    else:
                        bucket.request_count += 1
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None
        if blocked:
            raise AuthError(error_code, retry_after_seconds=blocked)
