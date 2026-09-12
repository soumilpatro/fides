import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.models.audit_log import AuditLog
from app.models.auth_identity import AuthIdentity
from app.models.auth_otp_challenge import AuthOtpChallenge
from app.models.auth_session import AuthSession
from app.models.user import User
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .test_api import BASE, PHONE, error, request, signup, verify


def test_provider_calls_have_no_open_transaction_and_reservations_are_durable(api):
    observed = []

    async def inspect(operation, intent):
        assert api.factory.kw["bind"].pool.checkedout() == 0
        with api.factory() as db:
            row = db.scalar(select(AuthOtpChallenge).where(AuthOtpChallenge.phone_e164 == PHONE))
            observed.append(row.state)
            assert row.operation_id and row.operation_expires_at == api.clock.now + timedelta(
                seconds=30
            )
            assert row.verify_attempts == (1 if operation == "verify" else 0)

    api.provider.before_operation = inspect
    challenge = request(api).json()["challenge_id"]
    assert verify(api, challenge).status_code == 200
    assert observed == ["SENDING", "CHECKING"]


def test_concurrent_signup_same_challenge_has_one_winner(api):
    challenge = request(api).json()["challenge_id"]
    entered, release = threading.Event(), threading.Event()

    async def pause(operation, intent):
        if operation == "verify":
            entered.set()
            assert await asyncio.to_thread(release.wait, 10)

    api.provider.before_operation = pause
    with ThreadPoolExecutor(max_workers=1) as executor:
        winner = executor.submit(verify, api, challenge)
        try:
            assert entered.wait(5)
            error(verify(api, challenge, display_name="Losing profile"), "AUTH_CHALLENGE_BUSY", 409)
        finally:
            release.set()
        response = winner.result(timeout=10)
    assert response.status_code == 200 and response.json()["user"]["display_name"] == "Example"
    with api.factory() as db:
        users = db.scalars(select(User).where(User.phone_e164 == PHONE)).all()
        assert len(users) == 1
        assert (
            len(db.scalars(select(AuthSession).where(AuthSession.user_id == users[0].id)).all())
            == 1
        )
        assert (
            len(db.scalars(select(AuthIdentity).where(AuthIdentity.user_id == users[0].id)).all())
            == 1
        )


@pytest.mark.parametrize("operation", ["request", "verify"])
def test_expired_provider_lease_quarantines_late_results(api, operation):
    challenge = request(api).json()["challenge_id"] if operation == "verify" else None

    async def expire(kind, intent):
        if kind == operation:
            api.clock.now += timedelta(seconds=30)

    api.provider.before_operation = expire
    error(verify(api, challenge) if challenge else request(api), "OTP_CHALLENGE_UNAVAILABLE", 409)
    with api.factory() as db:
        row = db.scalar(select(AuthOtpChallenge).where(AuthOtpChallenge.phone_e164 == PHONE))
        assert row.state == "INDETERMINATE" and row.operation_id is None
        assert db.scalar(select(User).where(User.phone_e164 == PHONE)) is None


@pytest.mark.parametrize("operation", ["request", "verify"])
def test_stale_worker_cannot_overwrite_new_owner(api, operation):
    challenge = request(api).json()["challenge_id"] if operation == "verify" else None
    replacement = uuid4()

    async def change_owner(kind, intent):
        if kind == operation:
            with api.factory.begin() as db:
                row = db.scalar(
                    select(AuthOtpChallenge)
                    .where(AuthOtpChallenge.phone_e164 == PHONE)
                    .with_for_update()
                )
                row.operation_id = replacement

    api.provider.before_operation = change_owner
    error(verify(api, challenge) if challenge else request(api), "OTP_CHALLENGE_UNAVAILABLE", 409)
    with api.factory() as db:
        row = db.scalar(select(AuthOtpChallenge).where(AuthOtpChallenge.phone_e164 == PHONE))
        assert row.operation_id == replacement
        assert row.state == ("CHECKING" if operation == "verify" else "SENDING")
        assert db.scalar(select(User).where(User.phone_e164 == PHONE)) is None


@pytest.mark.parametrize("action", ["AUTH_OTP_VERIFIED", "ACCOUNT_CREATED", "AUTH_SESSION_CREATED"])
def test_audit_failure_rolls_back_whole_signup(api, action):
    challenge = request(api).json()["challenge_id"]

    def fail(mapper, connection, target):
        if target.action == action:
            raise SQLAlchemyError("sensitive provider details must not escape")

    event.listen(AuditLog, "before_insert", fail)
    try:
        response = verify(api, challenge)
    finally:
        event.remove(AuditLog, "before_insert", fail)
    error(response, "SERVICE_UNAVAILABLE", 503)
    assert "access_token" not in response.text
    with api.factory() as db:
        assert db.scalar(select(User).where(User.phone_e164 == PHONE)) is None
        assert db.scalar(select(AuthIdentity).where(AuthIdentity.provider_subject == PHONE)) is None
        assert db.get(AuthOtpChallenge, UUID(challenge)).state == "INDETERMINATE"
    api.clock.now += timedelta(seconds=30)
    error(verify(api, challenge), "OTP_CHALLENGE_UNAVAILABLE", 409)


def test_lease_expiring_during_session_creation_rolls_back_and_quarantines(api, monkeypatch):
    challenge = request(api).json()["challenge_id"]
    create = api.challenges.session_service._create_locked

    def delayed_creation(*args, **kwargs):
        response = create(*args, **kwargs)
        api.clock.now += timedelta(seconds=30)
        return response

    monkeypatch.setattr(api.challenges.session_service, "_create_locked", delayed_creation)
    response = verify(api, challenge)
    error(response, "OTP_CHALLENGE_UNAVAILABLE", 409)
    assert "access_token" not in response.text
    with api.factory() as db:
        assert db.scalar(select(User).where(User.phone_e164 == PHONE)) is None
        assert db.scalar(select(AuthIdentity).where(AuthIdentity.provider_subject == PHONE)) is None
        assert db.get(AuthOtpChallenge, UUID(challenge)).state == "INDETERMINATE"


def test_commit_failure_after_proof_returns_no_credentials_or_orphans(api, monkeypatch):
    challenge = request(api).json()["challenge_id"]
    engine = api.factory.kw["bind"]
    real_commit = engine.dialect.do_commit
    failures = []

    def reject_account_commit(connection):
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM users WHERE phone_e164 = %s", (PHONE,))
            if cursor.fetchone()[0]:
                failures.append(True)
                raise engine.dialect.dbapi.OperationalError("simulated commit failure")
        real_commit(connection)

    with monkeypatch.context() as patch:
        patch.setattr(engine.dialect, "do_commit", reject_account_commit)
        response = verify(api, challenge)
    error(response, "SERVICE_UNAVAILABLE", 503)
    assert failures == [True] and "access_token" not in response.text
    with api.factory() as db:
        assert db.scalar(select(User).where(User.phone_e164 == PHONE)) is None
        assert db.scalar(select(AuthIdentity).where(AuthIdentity.provider_subject == PHONE)) is None


def test_account_created_during_provider_call_is_not_adopted_as_signup(api):
    challenge = request(api).json()["challenge_id"]

    async def competing_signup(operation, intent):
        if operation == "verify":
            with api.factory.begin() as db:
                user = User(
                    id=uuid4(), phone_e164=PHONE, display_name="Other winner", timezone="UTC"
                )
                db.add(user)
                db.flush()
                db.add(
                    AuthIdentity(
                        user_id=user.id,
                        provider="phone",
                        provider_subject=PHONE,
                        verified_at=api.clock.now,
                    )
                )

    api.provider.before_operation = competing_signup
    error(verify(api, challenge), "AUTH_FLOW_NOT_ALLOWED", 409)
    with api.factory() as db:
        user = db.scalar(select(User).where(User.phone_e164 == PHONE))
        assert user.display_name == "Other winner"
        assert not db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()


def test_request_never_queries_account_membership(api):
    def inspect(connection, cursor, statement, parameters, context, executemany):
        assert "FROM users" not in statement and "FROM auth_identities" not in statement

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", inspect)
    try:
        assert request(api, "login").status_code == 202
    finally:
        event.remove(engine, "before_cursor_execute", inspect)


def test_concurrent_request_reservations_use_separate_pg_connections(api):
    key = int.from_bytes(api.limiter.subject("phone", PHONE)[:8], "big", signed=True)
    gate = threading.Barrier(2, timeout=10)
    mutex = threading.Lock()
    pids = []

    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock" in statement and parameters.get("key") == key:
            with mutex:
                wait = len(pids) < 2
                if wait:
                    pids.append(connection.connection.driver_connection.info.backend_pid)
            if wait:
                gate.wait()

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: request(api), range(2)))
    finally:
        event.remove(engine, "before_cursor_execute", before_lock)
    assert len(set(pids)) == 2
    assert sorted(response.status_code for response in results) in [[202, 409], [202, 429]]
    with api.factory() as db:
        assert (
            len(
                db.scalars(
                    select(AuthOtpChallenge).where(AuthOtpChallenge.phone_e164 == PHONE)
                ).all()
            )
            == 1
        )


def test_concurrent_http_signup_uses_two_pg_connections_and_one_profile(api):
    challenge = request(api).json()["challenge_id"]
    key = int.from_bytes(api.limiter.subject("phone", PHONE)[:8], "big", signed=True)
    gate, mutex = threading.Barrier(2, timeout=10), threading.Lock()
    pids, provider_calls = [], []

    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock" in statement and parameters.get("key") == key:
            with mutex:
                wait = len(pids) < 2
                if wait:
                    pids.append(connection.connection.driver_connection.info.backend_pid)
            if wait:
                gate.wait()

    async def count(operation, intent):
        provider_calls.append(operation)

    api.provider.before_operation = count
    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda name: verify(api, challenge, display_name=name), ["First", "Second"]
                )
            )
    finally:
        event.remove(engine, "before_cursor_execute", before_lock)
    assert len(set(pids)) == 2 and provider_calls == ["verify"]
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json() for r in results if r.status_code == 200)
    loser = next(r for r in results if r.status_code != 200)
    assert loser.json()["error"]["code"] in {"AUTH_CHALLENGE_BUSY", "OTP_REPLAYED"}
    with api.factory() as db:
        users = db.scalars(select(User).where(User.phone_e164 == PHONE)).all()
        assert len(users) == 1 and users[0].display_name == winner["user"]["display_name"]
        assert (
            len(db.scalars(select(AuthIdentity).where(AuthIdentity.user_id == users[0].id)).all())
            == 1
        )
        assert (
            len(db.scalars(select(AuthSession).where(AuthSession.user_id == users[0].id)).all())
            == 1
        )
        assert (
            len(db.scalars(select(AuditLog).where(AuditLog.actor_user_id == users[0].id)).all())
            == 3
        )
        assert db.get(AuthOtpChallenge, UUID(challenge)).verify_attempts == 1


def test_concurrent_http_refresh_has_one_winner_on_separate_pg_connections(api):
    original, _ = signup(api)
    gate, pids = threading.Barrier(2, timeout=10), set()

    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            pids.add(connection.connection.driver_connection.info.backend_pid)
            gate.wait()

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: api.client.post(
                        BASE + "/refresh", json={"refresh_token": original["refresh_token"]}
                    ),
                    range(2),
                )
            )
    finally:
        event.remove(engine, "before_cursor_execute", before_lock)
    assert len(pids) == 2 and sorted(r.status_code for r in results) == [200, 401]
    error(next(r for r in results if r.status_code == 401), "INVALID_REFRESH_TOKEN", 401)
    winner = next(r.json() for r in results if r.status_code == 200)
    assert api.service.resolve("Bearer " + winner["access_token"])
    with api.factory() as db:
        user_id = UUID(original["user"]["id"])
        sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user_id)).all()
        assert len(sessions) == 1 and sessions[0].rotation_count == 1
        logs = db.scalars(
            select(AuditLog).where(
                AuditLog.actor_user_id == user_id, AuditLog.action == "AUTH_SESSION_REFRESHED"
            )
        ).all()
        assert len(logs) == 1


@pytest.mark.parametrize("operation", ["logout", "refresh", "denial"])
def test_route_audit_failure_rolls_back_session_or_denial(api, operation):
    credentials, _ = signup(api)
    if operation == "denial":
        api.clock.now += timedelta(seconds=60)
        challenge = request(api).json()["challenge_id"]
    action = {
        "logout": "AUTH_SESSION_REVOKED",
        "refresh": "AUTH_SESSION_REFRESHED",
        "denial": "AUTH_ACCOUNT_ACCESS_DENIED",
    }[operation]

    def fail(mapper, connection, target):
        if target.action == action:
            raise SQLAlchemyError("Private audit diagnostics")

    event.listen(AuditLog, "before_insert", fail)
    try:
        if operation == "denial":
            response = verify(api, challenge)
        elif operation == "refresh":
            response = api.client.post(
                BASE + "/refresh", json={"refresh_token": credentials["refresh_token"]}
            )
        else:
            response = api.client.post(
                BASE + "/logout", headers={"Authorization": "Bearer " + credentials["access_token"]}
            )
    finally:
        event.remove(AuditLog, "before_insert", fail)
    error(response, "SERVICE_UNAVAILABLE", 503)
    assert api.service.resolve("Bearer " + credentials["access_token"])
    with api.factory() as db:
        user_id = UUID(credentials["user"]["id"])
        assert len(db.scalars(select(AuditLog).where(AuditLog.actor_user_id == user_id)).all()) == 3
        if operation == "denial":
            assert db.get(AuthOtpChallenge, UUID(challenge)).state == "INDETERMINATE"


def test_expired_lease_quarantines_until_ttl_and_late_sender_cannot_change_replacement(api):
    entered, release = threading.Event(), threading.Event()
    calls = []

    async def pause_first(operation, intent):
        calls.append(operation)
        if len(calls) == 1:
            entered.set()
            assert await asyncio.to_thread(release.wait, 10)

    api.provider.before_operation = pause_first
    with ThreadPoolExecutor(max_workers=1) as executor:
        stale = executor.submit(request, api)
        try:
            assert entered.wait(5)
            with api.factory() as db:
                old_id = db.scalar(
                    select(AuthOtpChallenge.id).where(AuthOtpChallenge.phone_e164 == PHONE)
                )
            api.clock.now += timedelta(seconds=30)
            error(request(api), "OTP_CHALLENGE_UNAVAILABLE", 409)
            assert len(calls) == 1
            api.clock.now += timedelta(seconds=570)
            replacement = request(api)
            assert replacement.status_code == 202
            new_id = UUID(replacement.json()["challenge_id"])
            assert new_id != old_id
            with api.factory() as db:
                reference = db.get(AuthOtpChallenge, new_id).provider_reference
        finally:
            release.set()
        error(stale.result(timeout=10), "OTP_CHALLENGE_UNAVAILABLE", 409)
    with api.factory() as db:
        assert db.get(AuthOtpChallenge, old_id).state == "EXPIRED"
        new = db.get(AuthOtpChallenge, new_id)
        assert new.state == "PENDING" and new.provider_reference == reference
        assert new.verify_attempts == 0 and new.operation_id is None
