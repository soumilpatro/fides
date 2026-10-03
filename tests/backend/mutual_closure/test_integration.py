from datetime import timedelta
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.notification_event import NotificationEvent
from app.reminders import REMINDER_TYPES, ReminderService
from sqlalchemy import select

from .conftest import error, requested


def dated(mc):
    with mc.api.factory.begin() as db:
        term = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(mc.identifier)
            )
        )
        term.due_date = mc.api.clock.now.date() + timedelta(days=3)
        term.schedule_definition = {
            "schedule_mode": "single",
            "due_timezone": "UTC",
            "installment_dates": None,
        }


def closed(mc):
    identifier = requested(mc)
    assert mc.decide(identifier).status_code == 200
    return identifier


@pytest.mark.parametrize(
    "actor,field", [("A", "borrowed_outstanding_minor"), ("B", "lent_outstanding_minor")]
)
def test_summary_exclusion_and_history(mc, actor, field):
    before = mc.api.client.get("/api/v1/summary", headers=mc.headers[actor]).json()
    assert before["currencies"][0][field] == 10000
    identifier = closed(mc)
    after = mc.api.client.get("/api/v1/summary", headers=mc.headers[actor])
    assert after.status_code == 200, after.text
    assert all(
        c["borrowed_outstanding_minor"]
        == c["lent_outstanding_minor"]
        == c["net_position_minor"]
        == 0
        for c in after.json()["currencies"]
    )
    assert mc.closure_read(actor=actor, identifier=identifier).status_code == 200
    assert mc.read(actor=actor).status_code == 200
    assert mc.timeline().status_code == 200
    assert (
        mc.api.client.get(
            f"/api/v1/commitments/{mc.identifier}/terms", headers=mc.headers[actor]
        ).status_code
        == 200
    )


def test_closed_financial_guards_and_extension_resolution(mc):
    dated(mc)
    extension = mc.extension()
    assert extension.status_code == 201, extension.text
    eid = extension.json()["id"]
    repayment = mc.report().json()["id"]
    assert mc.verify(repayment, "dispute").status_code == 200
    closed(mc)
    for result in (
        mc.report(),
        mc.verify(repayment),
        mc.verify(repayment, "dispute"),
        mc.extension(),
        mc.extension(eid),
        mc.create(),
    ):
        error(result, "INVALID_STATE")
    assert mc.extension(eid, "reject").status_code == 200
    assert mc.timeline().status_code == 200
    with mc.api.factory() as db:
        assert db.get(Commitment, UUID(mc.identifier)).status == "CLOSED"


def test_reminders_suppressed_and_historical_system_actor_compatible(mc):
    dated(mc)
    service = ReminderService(mc.api.factory)
    before = service.run(now=mc.api.clock.now)
    assert before["created"] == 1
    closed(mc)
    assert service.run(now=mc.api.clock.now + timedelta(days=4))["created"] == 0
    with mc.api.factory() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(NotificationEvent).where(
                            NotificationEvent.object_id == UUID(mc.identifier),
                            NotificationEvent.type.in_(REMINDER_TYPES),
                        )
                    )
                )
            )
            == 1
        )
    response = mc.api.client.get("/api/v1/notifications", headers=mc.headers["A"])
    assert response.status_code == 200, response.text
    reminder = next(i for i in response.json()["items"] if i["type"] == "UPCOMING_DUE")
    assert reminder["actor"] is None


@pytest.mark.parametrize("actor", ["A", "B"])
def test_deactivation_after_closure(mc, actor):
    closed(mc)
    response = mc.api.client.post("/api/v1/me/deactivate", json={}, headers=mc.headers[actor])
    assert response.status_code == 200, response.text
