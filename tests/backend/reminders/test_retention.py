from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.ledger_event import LedgerEvent
from app.models.notification_event import NotificationEvent
from app.models.notification_preference import NotificationPreference
from app.models.repayment import Repayment
from app.notification_maintenance import cleanup_notifications
from sqlalchemy import func, select


def test_boundary_and_financial_preservation(env):
    env.preference()
    env.job.run(now=env.api.clock.now)
    now = env.api.clock.now + timedelta(days=90)
    original = env.rows()[0]
    with env.api.factory.begin() as db:
        for days, status in ((91, "DELIVERED"), (91, "READ"), (89, "DELIVERED")):
            created = now - timedelta(days=days)
            db.add(
                NotificationEvent(
                    user_id=env.users["A"],
                    type="COMMITMENT_PROPOSED",
                    status=status,
                    payload={},
                    created_at=created,
                    read_at=created if status == "READ" else None,
                )
            )
        tables = [
            Commitment,
            CommitmentTermsVersion,
            Repayment,
            LedgerEvent,
            AuditLog,
            NotificationPreference,
        ]
        before = [db.scalar(select(func.count()).select_from(model)) for model in tables]
    assert cleanup_notifications(env.api.factory, now=now) == 2
    with env.api.factory() as db:
        assert db.get(NotificationEvent, original.id) is not None
        assert [db.scalar(select(func.count()).select_from(model)) for model in tables] == before


def test_bounded_batches(env):
    with env.api.factory.begin() as db:
        for _ in range(5):
            db.add(
                NotificationEvent(
                    user_id=env.users["A"],
                    type="COMMITMENT_PROPOSED",
                    status="DELIVERED",
                    payload={},
                    created_at=env.api.clock.now - timedelta(days=91),
                )
            )
    assert (
        cleanup_notifications(env.api.factory, now=env.api.clock.now, batch_size=2, max_batches=2)
        == 4
    )
    assert cleanup_notifications(env.api.factory, now=env.api.clock.now) == 1


def test_cleanup_overlap(env):
    with env.api.factory.begin() as db:
        for _ in range(12):
            db.add(
                NotificationEvent(
                    user_id=env.users["A"],
                    type="COMMITMENT_PROPOSED",
                    status="DELIVERED",
                    payload={},
                    created_at=env.api.clock.now - timedelta(days=91),
                )
            )
    with ThreadPoolExecutor(2) as pool:
        counts = list(
            pool.map(
                lambda _: cleanup_notifications(
                    env.api.factory, now=env.api.clock.now, batch_size=2
                ),
                range(2),
            )
        )
    assert sum(counts) == 12


def test_locked_notification_skipped(env):
    env.job.run(now=env.api.clock.now)
    row = env.rows()[0]
    with env.api.factory.begin() as db:
        db.get(NotificationEvent, row.id).created_at -= timedelta(days=91)
    with env.api.factory.begin() as writer:
        writer.scalar(
            select(NotificationEvent).where(NotificationEvent.id == row.id).with_for_update()
        )
        with ThreadPoolExecutor(1) as pool:
            assert (
                pool.submit(cleanup_notifications, env.api.factory, now=env.api.clock.now).result(
                    timeout=20
                )
                == 0
            )
    assert cleanup_notifications(env.api.factory, now=env.api.clock.now) == 1


def test_expired_cursor_safe(env):
    env.job.run(now=env.api.clock.now)
    original = env.rows()[0]
    env.api.clock.now += timedelta(seconds=1)
    assert env.create(actor="B").status_code == 201
    page = env.inbox("A", {"limit": 1}).json()
    with env.api.factory.begin() as db:
        db.get(NotificationEvent, original.id).created_at -= timedelta(days=91)
    assert cleanup_notifications(env.api.factory, now=env.api.clock.now) == 1
    response = env.inbox("A", {"cursor": page["next_cursor"]})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert env.mark(original.id, "A").status_code == 404


@pytest.mark.parametrize(
    "kwargs", [{"batch_size": 0}, {"batch_size": 1001}, {"max_batches": 0}, {"max_batches": 101}]
)
def test_invalid_bounds(env, kwargs):
    with pytest.raises(ValueError):
        cleanup_notifications(env.api.factory, **kwargs)
