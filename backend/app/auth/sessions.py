"""Current-hash session engine. Transaction-owning methods publish only after commit.

Future account orchestration may use ``_create_locked`` in its own transaction,
but must withhold its provisional response until the outer transaction commits.
All writers acquire User before AuthSession; multi-session locks use UUID order.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth_schemas import CredentialResponse, MeResponse
from app.auth.rate_limits import RateLimiter
from app.auth.safety import Clock, auth_operation, sensitive_io, utc_now
from app.auth.tokens import digest_matches, generate_token, token_digest
from app.config import Settings
from app.core.errors import AuthError
from app.core.logging import sanitize_request_id
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.enums import UserStatus
from app.models.user import User


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    session_id: UUID
    _digest: bytes = field(repr=False)


@dataclass(frozen=True)
class LogoutRecognition:
    """Restricted self-revocation input, deliberately not a Principal subclass."""

    session_id: UUID
    _digest: bytes = field(repr=False)


def _access_digest(authorization: str | None) -> bytes:
    if authorization is None or authorization == "":
        raise AuthError("AUTH_REQUIRED")
    if not isinstance(authorization, str):
        raise AuthError("INVALID_AUTH_TOKEN")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("INVALID_AUTH_TOKEN")
    try:
        return token_digest(parts[1], "access")
    except ValueError:
        raise AuthError("INVALID_AUTH_TOKEN") from None


def _active(user: User | None) -> None:
    if user is not None and user.status == UserStatus.DEACTIVATED:
        raise AuthError("ACCOUNT_DEACTIVATED")
    if user is None or user.status != UserStatus.ACTIVE:
        raise AuthError("ACCOUNT_UNAVAILABLE")


def _not_revoked(session: AuthSession) -> None:
    if session.revoked_at is not None:
        raise AuthError("SESSION_REVOKED")


class SessionService:
    def __init__(self, sessions: sessionmaker, settings: Settings, *, clock: Clock | None = None):
        self.sessions = sessions
        self.settings = settings
        self.clock = clock
        self.limiter = RateLimiter(sessions, settings, clock=clock)

    @staticmethod
    def _audit(db, session, action, request_id, **metadata):
        db.add(
            AuditLog(
                actor_user_id=session.user_id,
                action=action,
                object_type="Session",
                object_id=session.id,
                result="SUCCESS",
                metadata_={**metadata, "request_id": sanitize_request_id(request_id)},
            )
        )

    @staticmethod
    def user_response(user: User) -> MeResponse:
        return MeResponse(
            id=user.id,
            phone_e164=user.phone_e164,
            display_name=user.display_name,
            timezone=user.timezone,
            status="ACTIVE",
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    @staticmethod
    def _response(session, user, access, refresh):
        return CredentialResponse(
            access_token=access,
            refresh_token=refresh,
            token_type="Bearer",
            access_expires_at=session.access_expires_at,
            refresh_expires_at=session.refresh_expires_at,
            user=SessionService.user_response(user),
        )

    def _create_locked(self, db: Session, user: User, intent: str, request_id=None):
        """Provisional result only. Caller owns User lock and outer atomic commit."""
        if intent not in {"signup", "login"}:
            raise ValueError("Unknown authentication intent")
        _active(user)
        now = utc_now(self.clock, db)
        access, refresh = generate_token("access"), generate_token("refresh")
        session = AuthSession(
            user_id=user.id,
            access_token_hash=token_digest(access, "access"),
            refresh_token_hash=token_digest(refresh, "refresh"),
            created_at=now,
            access_expires_at=now + timedelta(seconds=self.settings.auth_access_token_ttl_seconds),
            refresh_expires_at=now
            + timedelta(seconds=self.settings.auth_refresh_session_ttl_seconds),
            rotation_count=0,
        )
        db.add(session)
        db.flush()
        self._audit(db, session, "AUTH_SESSION_CREATED", request_id, intent=intent)
        return self._response(session, user, access, refresh)

    @auth_operation
    def create(self, user_id: UUID, *, intent: str, request_id=None) -> CredentialResponse:
        try:
            with sensitive_io(), self.sessions.begin() as db:
                user = db.scalar(select(User).where(User.id == user_id).with_for_update())
                _active(user)
                response = self._create_locked(db, user, intent, request_id)
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def resolve(self, authorization: str | None) -> Principal:
        digest = _access_digest(authorization)
        try:
            with sensitive_io(), self.sessions() as db:
                row = db.execute(
                    select(AuthSession, User)
                    .join(User)
                    .where(AuthSession.access_token_hash == digest)
                ).first()
                if row is None:
                    raise AuthError("INVALID_AUTH_TOKEN")
                session, user = row
                _not_revoked(session)
                _active(user)
                if utc_now(self.clock, db) >= session.access_expires_at:
                    raise AuthError("AUTH_TOKEN_EXPIRED")
                return Principal(user.id, session.id, digest)
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    def revalidate_user_locked(self, db: Session, principal: Principal) -> User:
        """Lock User, then recheck current credential/status/expiry for an account operation.

        Every runtime session writer holds this User lock. Read the session without
        taking it out of UUID order before a possible revoke-all operation.
        Retention cannot remove an unexpired session. Callers own the transaction.
        """
        if not isinstance(principal, Principal):
            raise TypeError("Ordinary authenticated principal required")
        user = db.scalar(select(User).where(User.id == principal.user_id).with_for_update())
        session = db.scalar(select(AuthSession).where(AuthSession.id == principal.session_id))
        if (
            session is None
            or session.user_id != principal.user_id
            or not digest_matches(principal._digest, session.access_token_hash)
        ):
            raise AuthError("INVALID_AUTH_TOKEN")
        _not_revoked(session)
        _active(user)
        if utc_now(self.clock, db) >= session.access_expires_at:
            raise AuthError("AUTH_TOKEN_EXPIRED")
        return user

    @auth_operation
    def recognize_logout(self, authorization: str | None) -> LogoutRecognition:
        digest = _access_digest(authorization)
        try:
            with sensitive_io(), self.sessions() as db:
                session = db.scalar(
                    select(AuthSession).where(AuthSession.access_token_hash == digest)
                )
                if session is None:
                    raise AuthError("INVALID_AUTH_TOKEN")
                _not_revoked(session)
                return LogoutRecognition(session.id, digest)
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def refresh(self, credential: str, *, ip: str, request_id=None) -> CredentialResponse:
        # IP budget covers malformed/unknown credentials without membership lookup.
        self.limiter.refresh(ip=ip)
        try:
            digest = token_digest(credential, "refresh")
        except ValueError:
            raise AuthError("INVALID_REFRESH_TOKEN") from None
        try:
            with sensitive_io(), self.sessions() as db:
                candidate = db.execute(
                    select(AuthSession.id, AuthSession.user_id).where(
                        AuthSession.refresh_token_hash == digest
                    )
                ).first()
            if candidate is None:
                raise AuthError("INVALID_REFRESH_TOKEN")
            # Independent committed reservation; no lock/connection is held here.
            self.limiter.refresh(session_id=candidate.id)
            with sensitive_io(), self.sessions.begin() as db:
                user = db.scalar(select(User).where(User.id == candidate.user_id).with_for_update())
                session = db.scalar(
                    select(AuthSession).where(AuthSession.id == candidate.id).with_for_update()
                )
                if session is None or not digest_matches(digest, session.refresh_token_hash):
                    raise AuthError("INVALID_REFRESH_TOKEN")
                _not_revoked(session)
                _active(user)
                now = utc_now(self.clock, db)
                if now >= session.refresh_expires_at:
                    raise AuthError("REFRESH_TOKEN_EXPIRED")
                access, refresh = generate_token("access"), generate_token("refresh")
                session.access_token_hash = token_digest(access, "access")
                session.refresh_token_hash = token_digest(refresh, "refresh")
                session.access_expires_at = min(
                    now + timedelta(seconds=self.settings.auth_access_token_ttl_seconds),
                    session.refresh_expires_at,
                )
                session.rotation_count += 1
                session.last_rotated_at = now
                self._audit(
                    db,
                    session,
                    "AUTH_SESSION_REFRESHED",
                    request_id,
                    rotation_count=session.rotation_count,
                )
                response = self._response(session, user, access, refresh)
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def revoke_one(self, recognition: LogoutRecognition, *, request_id=None) -> None:
        if not isinstance(recognition, LogoutRecognition):
            raise TypeError("Logout recognition required")
        try:
            with sensitive_io(), self.sessions.begin() as db:
                user_id = db.scalar(
                    select(AuthSession.user_id).where(AuthSession.id == recognition.session_id)
                )
                if user_id is None:
                    raise AuthError("INVALID_AUTH_TOKEN")
                db.scalar(select(User).where(User.id == user_id).with_for_update())
                session = db.scalar(
                    select(AuthSession)
                    .where(AuthSession.id == recognition.session_id)
                    .with_for_update()
                )
                if session is None or not digest_matches(
                    recognition._digest, session.access_token_hash
                ):
                    raise AuthError("INVALID_AUTH_TOKEN")
                _not_revoked(session)
                session.revoked_at = utc_now(self.clock, db)
                session.revocation_reason = "LOGOUT"
                self._audit(db, session, "AUTH_SESSION_REVOKED", request_id, reason="LOGOUT")
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    def revoke_all_locked(self, db: Session, user: User, *, request_id=None) -> int:
        """For future atomic deactivation: caller must already hold this User lock.

        Does not alter User status or perform commitment eligibility checks.
        """
        with sensitive_io():
            rows = db.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                .order_by(AuthSession.id)
                .with_for_update()
            ).all()
            now = utc_now(self.clock, db)
            for session in rows:
                session.revoked_at = now
                session.revocation_reason = "ACCOUNT_DEACTIVATED"
                self._audit(
                    db, session, "AUTH_SESSION_REVOKED", request_id, reason="ACCOUNT_DEACTIVATED"
                )
            db.flush()
            return len(rows)

    @auth_operation
    def revoke_all(self, user_id: UUID, *, request_id=None) -> int:
        try:
            with sensitive_io(), self.sessions.begin() as db:
                user = db.scalar(select(User).where(User.id == user_id).with_for_update())
                if user is None:
                    raise AuthError("ACCOUNT_UNAVAILABLE")
                return self.revoke_all_locked(db, user, request_id=request_id)
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None
