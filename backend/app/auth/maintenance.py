"""Explicitly invoked auth retention; caller supplies a maintenance-privileged factory."""

from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.auth.safety import auth_operation, utc_now
from app.core.errors import AuthError
from app.models.auth_otp_challenge import AuthOtpChallenge
from app.models.auth_rate_limit_bucket import AuthRateLimitBucket
from app.models.auth_session import AuthSession


@auth_operation
def cleanup_auth(maintenance_sessions, settings, *, clock=None) -> dict[str, int]:
    """Delete only auth operational rows at/after each approved retention deadline.

    Not wired to HTTP, runtime startup, or a scheduler. The supplied factory must
    use separately authorized maintenance credentials; never grant runtime DELETE.
    Counts are returned only after the single cleanup transaction commits.
    """
    try:
        with maintenance_sessions.begin() as db:
            now = utc_now(clock, db)
            counts = {}
            for model, expiry, retention in (
                (
                    AuthOtpChallenge,
                    AuthOtpChallenge.expires_at,
                    settings.auth_otp_cleanup_retention_seconds,
                ),
                (
                    AuthRateLimitBucket,
                    AuthRateLimitBucket.expires_at,
                    settings.auth_rate_limit_cleanup_retention_seconds,
                ),
                (
                    AuthSession,
                    AuthSession.refresh_expires_at,
                    settings.auth_session_cleanup_retention_seconds,
                ),
            ):
                counts[model.__tablename__] = db.execute(
                    delete(model).where(expiry <= now - timedelta(seconds=retention))
                ).rowcount
        return counts
    except SQLAlchemyError:
        raise AuthError("SERVICE_UNAVAILABLE") from None
