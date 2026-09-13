"""Bounded B5 proposals and lifecycle. Services own atomic transaction boundaries.

Lock order: idempotency scope -> affected Users sorted by UUID -> Connection
(creation/confirmation only) -> Commitment. B3 re-locks an already held actor.
Determine participants without locking, then verify them again after locks.
Reject/cancel and financial reads never depend on Connection status.
"""

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.commitment_schemas import CommitmentResponse
from app.api.connection_schemas import ParticipantResponse
from app.auth.authorization import AuthorizationService
from app.auth.safety import auth_operation, utc_now
from app.core.errors import AuthError, FinancialError, ResourceUnavailable
from app.core.logging import sanitize_request_id
from app.idempotency import Idempotency
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.connection import Connection
from app.models.enums import CommitmentStatus as State
from app.models.enums import CommitmentType, ConnectionStatus, UserStatus
from app.models.ledger_event import LedgerEvent
from app.models.user import User


class CommitmentService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.authorization = AuthorizationService(sessions)
        self.idempotency = Idempotency(sessions)

    @staticmethod
    def _participants(actor):
        return or_(Commitment.borrower_user_id == actor, Commitment.lender_user_id == actor)

    def _lock_users(self, db, principal, identifiers):
        for identifier in sorted(set(identifiers) | {principal.user_id}):
            db.execute(select(User.id).where(User.id == identifier).with_for_update()).first()
        self.sessions.revalidate_user_locked(db, principal)

    @staticmethod
    def _response(db, row):
        people = {
            u.id: ParticipantResponse(id=u.id, display_name=u.display_name)
            for u in db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_((row.borrower_user_id, row.lender_user_id, row.created_by_user_id))
                )
            )
        }
        return CommitmentResponse(
            id=row.id,
            connection_id=row.connection_id,
            type=CommitmentType(row.type).value,
            status=row.status,
            principal_amount_minor=row.principal_amount_minor,
            currency=row.currency,
            description=row.description,
            borrower=people[row.borrower_user_id],
            lender=people[row.lender_user_id],
            creator=people[row.created_by_user_id],
            created_at=row.created_at,
            updated_at=row.updated_at,
            confirmed_at=row.confirmed_at,
            activated_at=row.activated_at,
        ).model_dump(mode="json")

    @staticmethod
    def _events(db, row, actor, name, now, request_id, terms_id=None):
        # State events are not monetary postings. In particular, PROPOSED is
        # unverified; no authoritative balance/repayment calculation exists here.
        db.add(
            LedgerEvent(
                commitment_id=row.id,
                actor_user_id=actor,
                event_type=name,
                terms_version_id=terms_id,
                amount_minor=None,
                currency=None,
                occurred_at=now,
                event_payload={"status": row.status.value},
            )
        )
        db.add(
            AuditLog(
                actor_user_id=actor,
                object_type="Commitment",
                object_id=row.id,
                action=name,
                result="SUCCESS",
                metadata_={"request_id": sanitize_request_id(request_id)},
            )
        )

    @auth_operation
    def create(self, principal, body, key, *, request_id=None):
        def perform(db):
            pair = db.execute(
                select(Connection.requester_user_id, Connection.recipient_user_id).where(
                    Connection.id == body.connection_id,
                    or_(
                        Connection.requester_user_id == principal.user_id,
                        Connection.recipient_user_id == principal.user_id,
                    ),
                )
            ).first()
            self._lock_users(db, principal, pair or ())
            self.authorization.connection(db, principal, body.connection_id, lock=True)
            connection = db.get(Connection, body.connection_id)
            actual = {connection.requester_user_id, connection.recipient_user_id}
            if actual != set(pair or ()):
                raise FinancialError("CONFLICT")
            if connection.status != ConnectionStatus.ACCEPTED:
                raise FinancialError("INVALID_STATE")
            active = set(
                db.scalars(
                    select(User.id).where(User.id.in_(actual), User.status == UserStatus.ACTIVE)
                )
            )
            if active != actual:
                raise ResourceUnavailable()
            other = next(identifier for identifier in actual if identifier != principal.user_id)
            now = utc_now(self.sessions.clock, db)
            row = Commitment(
                connection_id=connection.id,
                borrower_user_id=principal.user_id if body.actor_role == "BORROWER" else other,
                lender_user_id=principal.user_id if body.actor_role == "LENDER" else other,
                created_by_user_id=principal.user_id,
                type=body.type,
                status=State.PENDING_CONFIRMATION,
                principal_amount_minor=body.principal_amount_minor,
                currency=body.currency,
                description=body.description,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
            terms = CommitmentTermsVersion(
                commitment_id=row.id,
                version_no=1,
                effective_at=now,
                interest_type="NONE",
                interest_rate_bps=None,
                due_date=None,
                schedule_definition=None,
                grace_period_days=0,
                created_by_user_id=principal.user_id,
                created_at=now,
            )
            db.add(terms)
            db.flush()
            self._events(
                db, row, principal.user_id, "COMMITMENT_PROPOSED", now, request_id, terms.id
            )
            return 201, self._response(db, row)

        return self._execute(principal, "create", None, key, body.model_dump(mode="json"), perform)

    @auth_operation
    def mutate(self, principal, identifier, action, key, *, request_id=None):
        if action not in ("confirm", "reject", "cancel"):
            raise ValueError("Unknown commitment action")

        def perform(db):
            snapshot = db.execute(
                select(
                    Commitment.borrower_user_id, Commitment.lender_user_id, Commitment.connection_id
                ).where(Commitment.id == identifier, self._participants(principal.user_id))
            ).first()
            self._lock_users(db, principal, snapshot[:2] if snapshot else ())
            if snapshot and action == "confirm":
                db.execute(
                    select(Connection.id)
                    .where(Connection.id == snapshot.connection_id)
                    .with_for_update()
                ).first()
            self.authorization.commitment(db, principal, identifier, lock=True)
            row = db.get(Commitment, identifier)
            if (row.borrower_user_id, row.lender_user_id, row.connection_id) != tuple(snapshot):
                raise FinancialError("CONFLICT")
            creator = row.created_by_user_id == principal.user_id
            if creator != (action == "cancel"):
                raise FinancialError("FORBIDDEN")
            if row.status != State.PENDING_CONFIRMATION:
                raise FinancialError("INVALID_STATE")
            if action == "confirm":
                if db.get(Connection, row.connection_id).status != ConnectionStatus.ACCEPTED:
                    raise FinancialError("INVALID_STATE")
            now = utc_now(self.sessions.clock, db)
            row.updated_at = max(now, row.updated_at + timedelta(microseconds=1))
            row.status = {
                "confirm": State.ACTIVE,
                "reject": State.REJECTED,
                "cancel": State.CANCELLED,
            }[action]
            if action == "confirm":
                row.confirmed_at = now
                row.activated_at = now
            event = {
                "confirm": "COMMITMENT_CONFIRMED",
                "reject": "COMMITMENT_REJECTED",
                "cancel": "COMMITMENT_CANCELLED",
            }[action]
            self._events(db, row, principal.user_id, event, now, request_id)
            return 200, self._response(db, row)

        return self._execute(principal, action, identifier, key, {}, perform)

    def _execute(self, principal, action, identifier, key, payload, perform):
        try:
            with self.sessions.sessions.begin() as db:

                def replay_authorize(db):
                    if identifier is not None:
                        self.authorization.commitment(db, principal, identifier)

                result = self.idempotency.execute(
                    db, principal, action, identifier, key, payload, perform, replay_authorize
                )
            return result
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def detail(self, principal, identifier):
        try:
            with self.sessions.sessions.begin() as db:
                self.authorization.commitment(db, principal, identifier, lock=True)
                result = self._response(db, db.get(Commitment, identifier))
            return result
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def list(self, principal):
        try:
            with self.sessions.sessions.begin() as db:
                self.sessions.revalidate_user_locked(db, principal)
                rows = db.scalars(
                    select(Commitment)
                    .where(self._participants(principal.user_id))
                    .order_by(Commitment.updated_at.desc(), Commitment.id.asc())
                )
                result = [self._response(db, row) for row in rows]
            return result
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None
