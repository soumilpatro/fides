from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.notification_event import NotificationEvent
from sqlalchemy import delete, select

from connections.conftest import api, clock, engine_env, peers, settings  # noqa: F401


@pytest.fixture
def ctx(peers):  # noqa: F811
    connection = peers.call("POST", json={"phone": peers.phones["B"]}).json()["id"]
    assert peers.call("POST", "/" + connection + "/accept", actor="B").status_code == 200
    body = {
        "connection_id": connection,
        "actor_role": "BORROWER",
        "type": "IOU",
        "principal_amount_minor": 10000,
        "currency": "INR",
        "description": None,
    }

    def call(method, suffix="", actor="A", key=None, **kwargs):
        headers = {**peers.headers[actor], "Idempotency-Key": key or uuid4().hex}
        return peers.api.client.request(
            method, "/api/v1/commitments" + suffix, headers=headers, **kwargs
        )

    try:
        yield SimpleNamespace(**vars(peers), connection=connection, body=body, request=call)
    finally:
        with peers.api.factory.begin() as db:
            ids = list(
                db.scalars(
                    select(Commitment.id).where(
                        Commitment.created_by_user_id.in_(peers.users.values())
                    )
                )
            )
            db.execute(
                delete(NotificationEvent).where(NotificationEvent.user_id.in_(peers.users.values()))
            )
            db.execute(delete(LedgerEvent).where(LedgerEvent.commitment_id.in_(ids)))
            db.execute(delete(AuditLog).where(AuditLog.object_id.in_(ids)))
            db.execute(
                delete(CommitmentTermsVersion).where(CommitmentTermsVersion.commitment_id.in_(ids))
            )
            db.execute(delete(Commitment).where(Commitment.id.in_(ids)))
            db.execute(
                delete(IdempotencyKey).where(IdempotencyKey.user_id.in_(peers.users.values()))
            )
