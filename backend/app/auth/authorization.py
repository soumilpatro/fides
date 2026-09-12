"""Authoritative participant lookup, without financial lifecycle/action permissions.

Use the Principal from api.dependencies.require_principal. Call before staging
writes in the caller-owned transaction. Financial mutation callers first acquire
all affected User locks in UUID order (B2-D2), then use lock=True here; resource
locks remain held until their transaction ends. Recheck on each new transaction:
an Access result is a snapshot, never a reusable authentication capability.

Authorize a verification-history collection with repayment(), and a commitment
ledger collection with commitment(); later reads must filter by those exact IDs.
No helper loads financial values or history, or commits/rolls back caller work.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import case, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.safety import auth_operation
from app.auth.sessions import Principal, SessionService
from app.core.errors import AuthError, ResourceUnavailable
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.extension_request import ExtensionRequest
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification


@dataclass(frozen=True)
class Access:
    resource_id: UUID
    role: Literal["participant", "lender", "borrower"]
    commitment_id: UUID | None = None
    repayment_id: UUID | None = None


class AuthorizationService:
    def __init__(self, sessions: SessionService):
        self.sessions = sessions

    @auth_operation
    def _lookup(self, db: Session, principal: Principal, resource_id: UUID, kind, *, lock: bool):
        if (
            type(principal) is not Principal
            or type(principal.user_id) is not UUID
            or type(principal.session_id) is not UUID
            or type(principal._digest) is not bytes
            or len(principal._digest) != 32
        ):
            raise AuthError("INVALID_AUTH_TOKEN")
        if type(resource_id) is not UUID:
            raise AuthError("VALIDATION_ERROR")
        if db.new or db.dirty or db.deleted:
            raise ValueError("Authorize before staging mutations")
        try:
            with db.no_autoflush:
                # Do not let clean but stale ORM objects override the B2 recheck.
                db.expire_all()
                self.sessions.revalidate_user_locked(db, principal)
                actor = principal.user_id
                if kind is Connection:
                    query = select(Connection.id).where(
                        Connection.id == resource_id,
                        or_(
                            Connection.requester_user_id == actor,
                            Connection.recipient_user_id == actor,
                        ),
                    )
                    if lock:
                        query = query.with_for_update(of=Connection)
                    row = db.execute(query).first()
                    if row is None:
                        raise ResourceUnavailable()
                    return Access(row.id, "participant")

                role = case((Commitment.lender_user_id == actor, "lender"), else_="borrower")
                query = select(Commitment.id.label("commitment_id"), role.label("role"))
                if kind is RepaymentVerification:
                    query = (
                        query.add_columns(Repayment.id.label("repayment_id"))
                        .select_from(RepaymentVerification)
                        .join(Repayment, RepaymentVerification.repayment_id == Repayment.id)
                        .join(Commitment, Repayment.commitment_id == Commitment.id)
                    )
                elif kind is not Commitment:
                    query = query.select_from(kind).join(
                        Commitment, kind.commitment_id == Commitment.id
                    )
                query = query.where(
                    kind.id == resource_id,
                    or_(Commitment.lender_user_id == actor, Commitment.borrower_user_id == actor),
                )
                row = db.execute(query).first()
                if row is None:
                    raise ResourceUnavailable()
                if lock:
                    # Explicit order; a joined FOR UPDATE does not define parent-
                    # before-child acquisition. Never UPDATE-lock append-only ledger.
                    original = row
                    db.execute(
                        select(Commitment.id)
                        .where(Commitment.id == original.commitment_id)
                        .with_for_update()
                    ).first()
                    if kind in (Repayment, RepaymentVerification, ExtensionRequest):
                        child = ExtensionRequest if kind is ExtensionRequest else Repayment
                        child_id = (
                            original.repayment_id if kind is RepaymentVerification else resource_id
                        )
                        db.execute(
                            select(child.id).where(child.id == child_id).with_for_update()
                        ).first()
                    row = db.execute(query).first()
                    if (
                        row is None
                        or row.commitment_id != original.commitment_id
                        or (
                            kind is RepaymentVerification
                            and row.repayment_id != original.repayment_id
                        )
                    ):
                        raise ResourceUnavailable()
                repayment_id = (
                    resource_id
                    if kind is Repayment
                    else row.repayment_id
                    if kind is RepaymentVerification
                    else None
                )
                return Access(resource_id, row.role, row.commitment_id, repayment_id)
        except SQLAlchemyError:
            raise AuthError("SERVICE_UNAVAILABLE") from None

    def connection(self, db, principal, resource_id, *, lock=False) -> Access:
        return self._lookup(db, principal, resource_id, Connection, lock=lock)

    def commitment(self, db, principal, resource_id, *, lock=False) -> Access:
        """Also authorizes the ledger collection for this exact commitment."""
        return self._lookup(db, principal, resource_id, Commitment, lock=lock)

    def repayment(self, db, principal, resource_id, *, lock=False) -> Access:
        """Also authorizes verification history for this exact repayment."""
        return self._lookup(db, principal, resource_id, Repayment, lock=lock)

    def verification(self, db, principal, resource_id, *, lock=False) -> Access:
        return self._lookup(db, principal, resource_id, RepaymentVerification, lock=lock)

    def ledger_event(self, db, principal, resource_id, *, lock=False) -> Access:
        return self._lookup(db, principal, resource_id, LedgerEvent, lock=lock)

    def extension_request(self, db, principal, resource_id, *, lock=False) -> Access:
        return self._lookup(db, principal, resource_id, ExtensionRequest, lock=lock)
