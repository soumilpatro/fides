"""B4-D0 relationship lifecycle; no financial writes or financial permissions.

Create/reconnect locks both Users in UUID order before inspecting both pair
orientations. Every B4 pair creator follows this protocol, including absent-row
races. Mutations lock the actor User through B3, then the Connection. No path
acquires another User lock after a Connection lock. Transactions are owned here.
"""

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.connection_schemas import ConnectionResponse, ParticipantResponse
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation, utc_now
from app.core.errors import AuthError, ConnectionError, ResourceUnavailable
from app.core.logging import sanitize_request_id
from app.models.audit_log import AuditLog
from app.models.connection import Connection
from app.models.enums import ConnectionStatus as State
from app.models.enums import UserStatus
from app.models.user import User


class ConnectionService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.authorization = AuthorizationService(sessions)

    @staticmethod
    def _audit(db, actor, row, action, request_id):
        db.add(
            AuditLog(
                actor_user_id=actor,
                object_type="Connection",
                object_id=row.id,
                action=action,
                result="SUCCESS",
                metadata_={"request_id": sanitize_request_id(request_id)},
            )
        )

    @staticmethod
    def _response(db, row):
        # Explicit projections: neither user phones nor auth/financial objects.
        people = {
            u.id: ParticipantResponse(id=u.id, display_name=u.display_name)
            for u in db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_((row.requester_user_id, row.recipient_user_id))
                )
            )
        }
        return ConnectionResponse(
            id=row.id,
            status=row.status,
            requester=people[row.requester_user_id],
            recipient=people[row.recipient_user_id],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @auth_operation
    def create(self, principal, body, *, request_id=None):
        try:
            with self.sessions.sessions.begin() as db:
                recipient = db.scalar(
                    select(User.id).where(
                        User.phone_e164 == body.phone, User.status == UserStatus.ACTIVE
                    )
                )
                # Revalidate even unsuccessful requests against current credentials.
                identifiers = sorted({principal.user_id, recipient} - {None})
                for identifier in identifiers:
                    db.execute(
                        select(User.id).where(User.id == identifier).with_for_update()
                    ).first()
                self.sessions.revalidate_user_locked(db, principal)
                target = db.scalar(
                    select(User.id).where(
                        User.id == recipient,
                        User.phone_e164 == body.phone,
                        User.status == UserStatus.ACTIVE,
                    )
                )
                if target is None:
                    raise ResourceUnavailable()
                if target == principal.user_id:
                    raise AuthError("VALIDATION_ERROR")
                rows = list(
                    db.scalars(
                        select(Connection)
                        .where(
                            or_(
                                (Connection.requester_user_id == principal.user_id)
                                & (Connection.recipient_user_id == target),
                                (Connection.requester_user_id == target)
                                & (Connection.recipient_user_id == principal.user_id),
                            )
                        )
                        .with_for_update()
                    )
                )
                # Fail closed on any pre-existing inconsistent pair data.
                if len(rows) > 1 or (rows and rows[0].status != State.REMOVED):
                    raise ConnectionError("CONFLICT")
                now = utc_now(self.sessions.clock, db)
                if rows:
                    row = rows[0]
                    row.requester_user_id = principal.user_id
                    row.recipient_user_id = target
                    row.status = State.PENDING
                    row.updated_at = max(now, row.updated_at + timedelta(microseconds=1))
                else:
                    row = Connection(
                        requester_user_id=principal.user_id,
                        recipient_user_id=target,
                        status=State.PENDING,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(row)
                db.flush()
                self._audit(db, principal.user_id, row, "CONNECTION_REQUESTED", request_id)
                response = self._response(db, row)
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def list(self, principal):
        try:
            with self.sessions.sessions.begin() as db:
                self.sessions.revalidate_user_locked(db, principal)
                rows = db.scalars(
                    select(Connection)
                    .where(
                        or_(
                            Connection.requester_user_id == principal.user_id,
                            Connection.recipient_user_id == principal.user_id,
                        )
                    )
                    .order_by(Connection.updated_at.desc())
                )
                response = [self._response(db, row) for row in rows]
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def detail(self, principal, identifier):
        try:
            with self.sessions.sessions.begin() as db:
                self.authorization.connection(db, principal, identifier, lock=True)
                response = self._response(db, db.get(Connection, identifier))
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def mutate(self, principal, identifier, action, *, request_id=None):
        try:
            with self.sessions.sessions.begin() as db:
                self.authorization.connection(db, principal, identifier, lock=True)
                row = db.get(Connection, identifier)
                if action in ("accept", "reject"):
                    if row.recipient_user_id != principal.user_id:
                        raise ConnectionError("FORBIDDEN")
                    if row.status != State.PENDING:
                        raise ConnectionError("INVALID_STATE")
                    status = State.ACCEPTED if action == "accept" else State.REMOVED
                elif action == "block":
                    if row.status not in (State.PENDING, State.ACCEPTED):
                        raise ConnectionError("INVALID_STATE")
                    status = State.BLOCKED
                elif action == "remove":
                    if row.status not in (State.PENDING, State.ACCEPTED):
                        raise ConnectionError("INVALID_STATE")
                    if row.status == State.PENDING and row.requester_user_id != principal.user_id:
                        raise ConnectionError("FORBIDDEN")
                    status = State.REMOVED
                else:
                    raise ValueError("Unknown connection action")
                row.status = status
                row.updated_at = max(
                    utc_now(self.sessions.clock, db), row.updated_at + timedelta(microseconds=1)
                )
                actions = {
                    "accept": "CONNECTION_ACCEPTED",
                    "reject": "CONNECTION_REJECTED",
                    "block": "CONNECTION_BLOCKED",
                    "remove": "CONNECTION_REMOVED",
                }
                self._audit(db, principal.user_id, row, actions[action], request_id)
                response = self._response(db, row)
            return response
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None
