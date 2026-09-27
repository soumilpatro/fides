from types import SimpleNamespace
from uuid import UUID

import pytest
from app.models.notification_event import NotificationEvent
from sqlalchemy import delete, select

from extensions.conftest import (  # noqa: F401
    api,
    b6,
    b7,
    b8,
    b10,
    clock,
    ctx,
    engine_env,
    peers,
    settings,
)

TYPES = [
    "COMMITMENT_PROPOSED",
    "COMMITMENT_CONFIRMED",
    "COMMITMENT_REJECTED",
    "COMMITMENT_CANCELLED",
    "REPAYMENT_REPORTED",
    "REPAYMENT_VERIFIED",
    "REPAYMENT_DISPUTED",
    "EXTENSION_REQUESTED",
    "EXTENSION_ACCEPTED",
    "EXTENSION_REJECTED",
]


@pytest.fixture
def inbox(b10):  # noqa: F811
    # Treat fixture setup as pre-enablement history; no backfill should occur.
    with b10.api.factory.begin() as db:
        db.execute(
            delete(NotificationEvent).where(NotificationEvent.user_id.in_(b10.users.values()))
        )

    def listing(actor="B", params=None):
        return b10.api.client.get(
            "/api/v1/notifications", headers=b10.headers[actor], params=params
        )

    def read(identifier, actor="B", **kwargs):
        return b10.api.client.post(
            f"/api/v1/notifications/{identifier}/read",
            headers=b10.headers[actor],
            **({"json": {}} if not kwargs else kwargs),
        )

    return SimpleNamespace(**vars(b10), inbox=listing, mark=read)


def notifications(env):
    with env.api.factory() as db:
        return {
            row.id: dict(row._mapping)
            for row in db.execute(
                select(NotificationEvent.__table__).where(
                    NotificationEvent.user_id.in_(env.users.values())
                )
            )
        }


def prepare(env, kind, actor="A", role="BORROWER"):
    """Return a replayable real HTTP domain action after its prerequisites."""
    other = "B" if actor == "A" else "A"
    if kind == "COMMITMENT_PROPOSED":
        return lambda key=None: env.request(
            "POST",
            actor=actor,
            key=key,
            json={**env.body, "actor_role": role, "description": "private-commitment-description"},
        )
    if kind.startswith("COMMITMENT_"):
        creator = actor if kind == "COMMITMENT_CANCELLED" else other
        result = env.request(
            "POST",
            actor=creator,
            json={**env.body, "actor_role": role, "description": "private-commitment-description"},
        )
        assert result.status_code == 201, result.text
        action = {
            "COMMITMENT_CONFIRMED": "confirm",
            "COMMITMENT_REJECTED": "reject",
            "COMMITMENT_CANCELLED": "cancel",
        }[kind]
        return lambda key=None: env.request(
            "POST", f"/{result.json()['id']}/{action}", actor=actor, key=key
        )
    if kind == "REPAYMENT_REPORTED":
        return lambda key=None: env.report(
            actor=actor, parent=env.identifier, key=key, note="private-report-note"
        )
    if kind.startswith("REPAYMENT_"):
        report = env.report(actor=other, parent=env.identifier, note="private-report-note")
        assert report.status_code == 201, report.text
        return lambda key=None: env.financial.decide(
            "verify" if kind == "REPAYMENT_VERIFIED" else "dispute",
            actor=actor,
            identifier=report.json()["id"],
            key=key,
            body={"decision_note": "private-verification-note"},
        )
    if kind == "EXTENSION_REQUESTED":
        return lambda key=None: env.create(actor=actor, key=key, reason="private-extension-reason")
    request = env.create(actor=other, reason="private-extension-reason")
    assert request.status_code == 201, request.text
    return lambda key=None: env.decide(
        request.json()["id"],
        "accept" if kind == "EXTENSION_ACCEPTED" else "reject",
        actor=actor,
        key=key,
    )


def make(env, kind="COMMITMENT_PROPOSED", actor="A"):
    run = prepare(env, kind, actor)
    before = notifications(env)
    response = run()
    assert response.status_code in (200, 201), response.text
    added = notifications(env).keys() - before.keys()
    assert len(added) == 1
    return next(iter(added))


def notification_row(db, identifier):
    return db.get(NotificationEvent, UUID(str(identifier)))
