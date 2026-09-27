"""B11 durable in-app records, recipient-owned reads, and first-read state.

Creation belongs to the originating writer's transaction and lock order.
Inbox operations lock the authenticated User before a notification, never a
financial parent. Historical meaning comes from validated source events.
"""

import base64
import binascii
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import get_args
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError

from app.api.ledger_schemas import LedgerResponse
from app.api.notification_schemas import (
    NotificationListResponse,
    NotificationResponse,
    NotificationType,
)
from app.auth.safety import auth_operation, utc_now
from app.core.errors import AuthError, ResourceUnavailable
from app.ledger import _project as project_ledger_events
from app.models.commitment import Commitment
from app.models.enums import NotificationStatus
from app.models.ledger_event import LedgerEvent
from app.models.notification_event import NotificationEvent

TYPES = frozenset(get_args(NotificationType))


def _require(condition):
    if not condition:
        raise ValueError("Invalid stored notification")


def _source(event):
    _require(event.event_type in TYPES)
    if event.event_type.startswith("COMMITMENT_"):
        return "Commitment", event.commitment_id
    if event.event_type.startswith("REPAYMENT_"):
        _require(event.repayment_id is not None)
        return "Repayment", event.repayment_id
    return "ExtensionRequest", UUID(event.event_payload["extension_request_id"])


def create_notification(db, event, parent):
    """Called once inside a newly successful domain action, never on replay.

    No commit, provider, eligibility override, backfill, or independent audit.
    Flush the source event to obtain its database-generated UUID.
    """
    try:
        participants = {parent.borrower_user_id, parent.lender_user_id}
        _require(len(participants) == 2 and event.actor_user_id in participants)
        _require(event.commitment_id == parent.id)
        object_type, object_id = _source(event)
        db.flush()
        db.add(
            NotificationEvent(
                user_id=next(iter(participants - {event.actor_user_id})),
                type=event.event_type,
                status=NotificationStatus.DELIVERED,
                object_type=object_type,
                object_id=object_id,
                payload={"source_ledger_event_id": str(event.id)},
                scheduled_at=None,
                sent_at=None,
                read_at=None,
                created_at=event.occurred_at,
            )
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        raise AuthError("SERVICE_UNAVAILABLE") from None


def encode_cursor(user_id, created_at, identifier):
    raw = json.dumps([1, str(user_id), created_at.isoformat(), str(identifier)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value, user_id):
    if value is None:
        return None
    try:
        if type(value) is not str or not 1 <= len(value) <= 512:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        parts = json.loads(raw)
        if (
            type(parts) is not list
            or len(parts) != 4
            or type(parts[0]) is not int
            or parts[0] != 1
            or any(type(x) is not str for x in parts[1:])
            or UUID(parts[1]) != user_id
        ):
            raise ValueError
        stamp = datetime.fromisoformat(parts[2])
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(UTC), UUID(parts[3])
    except (ValueError, TypeError, binascii.Error, UnicodeError, OverflowError):
        raise AuthError("VALIDATION_ERROR") from None


def project_notifications(db, rows, user_id):
    sources = {}
    for row in rows:
        _require(row.user_id == user_id and row.type in TYPES)
        _require(row.sent_at is None and row.scheduled_at is None)
        _require(
            (row.status == NotificationStatus.DELIVERED and row.read_at is None)
            or (
                row.status == NotificationStatus.READ
                and row.read_at is not None
                and row.read_at >= row.created_at
            )
        )
        _require(type(row.payload) is dict and set(row.payload) == {"source_ledger_event_id"})
        value = row.payload["source_ledger_event_id"]
        _require(type(value) is str)
        sources[row.id] = UUID(value)
    events = {
        e.id: e
        for e in db.scalars(select(LedgerEvent).where(LedgerEvent.id.in_(set(sources.values()))))
    }
    parents = {
        p.id: p
        for p in db.scalars(
            select(Commitment).where(Commitment.id.in_({e.commitment_id for e in events.values()}))
        )
    }
    grouped = defaultdict(dict)
    for event in events.values():
        grouped[event.commitment_id][event.id] = event
    projections = {}
    for parent_id, group in grouped.items():
        # B9/B10 already validate closed historical event details and references.
        # No AuthorizationService parent lock: notification ownership is distinct.
        validated = LedgerResponse(
            items=project_ledger_events(db, parents[parent_id], list(group.values())),
            next_cursor=None,
        )
        projections.update({item.id: item for item in validated.items})
    result = []
    for row in rows:
        event = events[sources[row.id]]
        parent = parents[event.commitment_id]
        _require(event.event_type == row.type)
        object_type, object_id = _source(event)
        _require((row.object_type, row.object_id) == (object_type, object_id))
        participants = {parent.borrower_user_id, parent.lender_user_id}
        _require(len(participants) == 2 and event.actor_user_id in participants)
        _require(participants - {event.actor_user_id} == {user_id})
        if object_type == "Commitment":
            _require(parent.created_by_user_id in participants)
            creator_action = row.type in ("COMMITMENT_PROPOSED", "COMMITMENT_CANCELLED")
            _require((event.actor_user_id == parent.created_by_user_id) == creator_action)
        result.append(
            NotificationResponse(
                id=row.id,
                type=row.type,
                actor=projections[event.id].actor,
                commitment_id=parent.id,
                repayment_id=object_id if object_type == "Repayment" else None,
                extension_request_id=object_id if object_type == "ExtensionRequest" else None,
                created_at=row.created_at,
                read_at=row.read_at,
            )
        )
    return result


class NotificationService:
    def __init__(self, sessions):
        self.sessions = sessions

    @auth_operation
    def list(self, principal, limit=50, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AuthError("VALIDATION_ERROR")
        try:
            with self.sessions.sessions.begin() as db:
                self.sessions.revalidate_user_locked(db, principal)
                position = decode_cursor(cursor, principal.user_id)
                query = select(NotificationEvent).where(
                    NotificationEvent.user_id == principal.user_id
                )
                if position:
                    query = query.where(
                        tuple_(NotificationEvent.created_at, NotificationEvent.id) < position
                    )
                rows = list(
                    db.scalars(
                        query.order_by(
                            NotificationEvent.created_at.desc(), NotificationEvent.id.desc()
                        ).limit(limit + 1)
                    )
                )
                items = project_notifications(db, rows, principal.user_id)
                return NotificationListResponse(
                    items=items[:limit],
                    next_cursor=(
                        encode_cursor(
                            principal.user_id, rows[limit - 1].created_at, rows[limit - 1].id
                        )
                        if len(rows) > limit
                        else None
                    ),
                )
        except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None

    @auth_operation
    def mark_read(self, principal, identifier):
        try:
            with self.sessions.sessions.begin() as db:
                self.sessions.revalidate_user_locked(db, principal)
                row = db.scalar(
                    select(NotificationEvent)
                    .where(
                        NotificationEvent.id == identifier,
                        NotificationEvent.user_id == principal.user_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise ResourceUnavailable()
                response = project_notifications(db, [row], principal.user_id)[0]
                if row.read_at is None:
                    row.read_at = utc_now(self.sessions.clock, db)
                    _require(row.read_at >= row.created_at)
                    row.status = NotificationStatus.READ
                    response.read_at = row.read_at
                return response
        except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError):
            raise AuthError("SERVICE_UNAVAILABLE") from None
