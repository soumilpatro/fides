from types import SimpleNamespace
from uuid import UUID

import pytest
from app.models.ledger_event import LedgerEvent
from sqlalchemy import select

from verification.conftest import (  # noqa: F401
    api,
    b6,
    b7,
    b8,
    clock,
    ctx,
    engine_env,
    peers,
    settings,
)


@pytest.fixture
def timeline(b8):  # noqa: F811
    def read(actor="A", identifier=None, **kwargs):
        return b8.api.client.get(
            f"/api/v1/commitments/{identifier or b8.identifier}/ledger",
            headers=b8.headers[actor],
            **kwargs,
        )

    return SimpleNamespace(**vars(b8), timeline=read)


def event(db, env, name):
    return db.scalar(
        select(LedgerEvent).where(
            LedgerEvent.commitment_id == UUID(env.identifier),
            LedgerEvent.event_type == name,
        )
    )
