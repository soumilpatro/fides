"""Account reads/mutations serialized with session issuance and financial eligibility."""

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth_schemas import DeactivationResponse, ProfileUpdateRequest
from app.auth.safety import auth_operation, utc_now
from app.auth.sessions import Principal, SessionService
from app.core.errors import AuthError
from app.core.logging import sanitize_request_id
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.enums import CommitmentStatus, UserStatus

TERMINAL_COMMITMENTS = (
    CommitmentStatus.CLOSED,
    CommitmentStatus.REJECTED,
    CommitmentStatus.CANCELLED,
)


class AccountService:
    def __init__(self, sessions: SessionService):
        self.sessions = sessions

    @staticmethod
    def _audit(db, user, action, request_id, **metadata):
        db.add(
            AuditLog(
                actor_user_id=user.id,
                object_id=user.id,
                object_type="User",
                action=action,
                result="SUCCESS",
                metadata_={**metadata, "request_id": sanitize_request_id(request_id)},
            )
        )

    @auth_operation
    def get(self, principal: Principal):
        try:
            with self.sessions.sessions.begin() as db:
                user = self.sessions.revalidate_user_locked(db, principal)
                response = self.sessions.user_response(user)
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def update(self, principal: Principal, body: ProfileUpdateRequest, *, request_id=None):
        try:
            with self.sessions.sessions.begin() as db:
                user = self.sessions.revalidate_user_locked(db, principal)
                changed = sorted(
                    name
                    for name in body.model_fields_set
                    if getattr(user, name) != getattr(body, name)
                )
                if changed:
                    for name in changed:
                        setattr(user, name, getattr(body, name))
                    now = utc_now(self.sessions.clock, db)
                    user.updated_at = max(now, user.updated_at + timedelta(microseconds=1))
                    self._audit(db, user, "PROFILE_UPDATED", request_id, changed_fields=changed)
                response = self.sessions.user_response(user)
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def deactivate(self, principal: Principal, *, request_id=None):
        try:
            with self.sessions.sessions.begin() as db:
                user = self.sessions.revalidate_user_locked(db, principal)
                # D2: future financial writers must lock affected Users in UUID
                # order and check ACTIVE before making a blocking state authoritative.
                # The post-lock READ COMMITTED query sees earlier committed writers.
                blocking = db.scalar(
                    select(Commitment.id)
                    .where(
                        or_(
                            Commitment.lender_user_id == user.id,
                            Commitment.borrower_user_id == user.id,
                        ),
                        Commitment.status.not_in(TERMINAL_COMMITMENTS),
                    )
                    .limit(1)
                )
                if blocking is not None:
                    raise AuthError("ACCOUNT_HAS_UNRESOLVED_COMMITMENTS")
                self.sessions.revalidate_user_locked(db, principal)
                now = utc_now(self.sessions.clock, db)
                user.status = UserStatus.DEACTIVATED
                user.deactivated_at = now
                user.updated_at = max(now, user.updated_at + timedelta(microseconds=1))
                revoked = self.sessions.revoke_all_locked(db, user, request_id=request_id)
                self._audit(
                    db, user, "ACCOUNT_DEACTIVATED", request_id, revoked_session_count=revoked
                )
                response = DeactivationResponse(status="DEACTIVATED", deactivated_at=now)
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None
