import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.enums import CommitmentStatus, UserStatus
from app.models.user import User
from auth_api.test_api import error
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .test_account import ME, call


@pytest.mark.parametrize(
    "action", ["PROFILE_UPDATED", "ACCOUNT_DEACTIVATED", "AUTH_SESSION_REVOKED"]
)
def test_audit_failure_rolls_back_account_and_all_sessions(account, action):
    api = account.api
    api.service.create(account.user_id, intent="login")

    def reject(mapper, connection, target):
        if target.action == action:
            raise SQLAlchemyError("private audit diagnostics")

    event.listen(AuditLog, "before_insert", reject)
    try:
        response = (
            call(account, "PATCH", json={"display_name": "Changed"})
            if action == "PROFILE_UPDATED"
            else call(account, "POST", ME + "/deactivate")
        )
    finally:
        event.remove(AuditLog, "before_insert", reject)
    error(response, "SERVICE_UNAVAILABLE", 503)
    assert call(account).json() == account.credentials["user"]
    with api.factory() as db:
        assert db.get(User, account.user_id).deactivated_at is None
        sessions = db.scalars(
            select(AuthSession).where(AuthSession.user_id == account.user_id)
        ).all()
        assert len(sessions) == 2 and all(row.revoked_at is None for row in sessions)
        assert (
            len(db.scalars(select(AuditLog).where(AuditLog.actor_user_id == account.user_id)).all())
            == 4
        )


@pytest.mark.parametrize("operation", ["patch", "deactivate"])
def test_commit_failure_returns_no_success_and_rolls_back(account, monkeypatch, operation):
    api = account.api
    engine = api.factory.kw["bind"]
    real_commit = engine.dialect.do_commit

    def reject(connection):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT display_name, status FROM users WHERE id = %s", (account.user_id,)
            )
            name, status = cursor.fetchone()
            if name == "Changed" or status == "DEACTIVATED":
                raise engine.dialect.dbapi.OperationalError("private commit diagnostics")
        real_commit(connection)

    with monkeypatch.context() as patch:
        patch.setattr(engine.dialect, "do_commit", reject)
        response = (
            call(account, "PATCH", json={"display_name": "Changed"})
            if operation == "patch"
            else call(account, "POST", ME + "/deactivate")
        )
    error(response, "SERVICE_UNAVAILABLE", 503)
    assert call(account).json() == account.credentials["user"]


def test_concurrent_partial_profile_updates_do_not_lose_fields(account):
    api = account.api
    api.clock.now += timedelta(seconds=1)
    barrier, pids = threading.Barrier(2, timeout=10), set()

    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            pids.add(connection.connection.driver_connection.info.backend_pid)
            barrier.wait()

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda body: call(account, "PATCH", json=body),
                    [{"display_name": "Winner"}, {"timezone": "Asia/Kolkata"}],
                )
            )
    finally:
        event.remove(engine, "before_cursor_execute", before_lock)
    assert len(pids) == 2 and all(r.status_code == 200 for r in results)
    result = call(account).json()
    assert result["display_name"] == "Winner" and result["timezone"] == "Asia/Kolkata"
    with api.factory() as db:
        assert (
            len(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.actor_user_id == account.user_id,
                        AuditLog.action == "PROFILE_UPDATED",
                    )
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize(
    "change,expected",
    [
        ("expiry", "AUTH_TOKEN_EXPIRED"),
        ("rotation", "INVALID_AUTH_TOKEN"),
        ("revocation", "SESSION_REVOKED"),
    ],
)
def test_mutation_rechecks_credential_after_waiting_for_user_lock(account, change, expected):
    from app.auth.tokens import generate_token, token_digest

    api = account.api
    attempting = threading.Event()
    main_thread = threading.get_ident()

    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if (
            threading.get_ident() != main_thread
            and "FROM users" in statement
            and "FOR UPDATE" in statement
        ):
            attempting.set()

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_lock)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with api.factory.begin() as db:
                db.scalar(select(User).where(User.id == account.user_id).with_for_update())
                future = executor.submit(call, account, "PATCH", json={"display_name": "Forbidden"})
                assert attempting.wait(5)
                session = db.scalar(
                    select(AuthSession).where(AuthSession.user_id == account.user_id)
                )
                if change == "expiry":
                    api.clock.now += timedelta(minutes=15)
                elif change == "rotation":
                    session.access_token_hash = token_digest(generate_token("access"), "access")
                else:
                    session.revoked_at, session.revocation_reason = api.clock.now, "LOGOUT"
            error(future.result(timeout=10), expected, 401)
    finally:
        event.remove(engine, "before_cursor_execute", before_lock)
    with api.factory() as db:
        assert db.get(User, account.user_id).display_name == "Example"


def test_financial_writer_first_blocks_deactivation_after_lock_wait(account):
    api = account.api
    attempting = threading.Event()
    main_thread = threading.get_ident()

    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if (
            threading.get_ident() != main_thread
            and "FROM users" in statement
            and "FOR UPDATE" in statement
        ):
            attempting.set()

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_lock)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with api.factory.begin() as db:
                users = db.scalars(
                    select(User)
                    .where(User.id.in_([account.user_id, account.other_id]))
                    .order_by(User.id)
                    .with_for_update()
                ).all()
                assert all(user.status == UserStatus.ACTIVE for user in users)
                future = executor.submit(call, account, "POST", ME + "/deactivate")
                assert attempting.wait(5)
                account.commitment(CommitmentStatus.DRAFT, db=db)
            error(future.result(timeout=10), "ACCOUNT_HAS_UNRESOLVED_COMMITMENTS", 409)
    finally:
        event.remove(engine, "before_cursor_execute", before_lock)


def test_deactivation_first_rejects_correctly_locked_financial_writer(account):
    api = account.api
    deactivating, writer_attempting, release = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    writer_thread = []

    def before_query(connection, cursor, statement, parameters, context, executemany):
        if "FROM commitments" in statement:
            deactivating.set()
            assert release.wait(10)
        if (
            writer_thread
            and threading.get_ident() == writer_thread[0]
            and "FOR UPDATE" in statement
        ):
            writer_attempting.set()

    def writer():
        writer_thread.append(threading.get_ident())
        with api.factory.begin() as db:
            users = db.scalars(
                select(User)
                .where(User.id.in_([account.user_id, account.other_id]))
                .order_by(User.id)
                .with_for_update()
            ).all()
            if any(user.status != UserStatus.ACTIVE for user in users):
                return "ineligible"
            account.commitment(CommitmentStatus.DRAFT, db=db)
            return "created"

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_query)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(call, account, "POST", ME + "/deactivate")
            try:
                assert deactivating.wait(5)
                second = executor.submit(writer)
                assert writer_attempting.wait(5)
            finally:
                release.set()
            assert first.result(timeout=10).status_code == 200
            assert second.result(timeout=10) == "ineligible"
    finally:
        event.remove(engine, "before_cursor_execute", before_query)
    with api.factory() as db:
        assert (
            db.scalar(select(Commitment.id).where(Commitment.created_by_user_id == account.user_id))
            is None
        )


@pytest.mark.parametrize(
    "operation,expected", [("create", "ACCOUNT_DEACTIVATED"), ("refresh", "SESSION_REVOKED")]
)
def test_deactivation_first_prevents_waiting_session_issuance(account, operation, expected):
    from app.core.errors import AuthError

    api = account.api
    deactivating, issuing, release = threading.Event(), threading.Event(), threading.Event()
    issue_thread = []

    def before_query(connection, cursor, statement, parameters, context, executemany):
        if "FROM commitments" in statement:
            deactivating.set()
            assert release.wait(10)
        if (
            issue_thread
            and threading.get_ident() == issue_thread[0]
            and "FROM users" in statement
            and "FOR UPDATE" in statement
        ):
            issuing.set()

    def issue():
        issue_thread.append(threading.get_ident())
        try:
            if operation == "create":
                return api.service.create(account.user_id, intent="login")
            return api.service.refresh(account.credentials["refresh_token"], ip="192.0.2.1")
        except AuthError as error:
            return error.code

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_query)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(call, account, "POST", ME + "/deactivate")
            try:
                assert deactivating.wait(5)
                second = executor.submit(issue)
                assert issuing.wait(5)
            finally:
                release.set()
            assert first.result(timeout=10).status_code == 200
            assert second.result(timeout=10) == expected
    finally:
        event.remove(engine, "before_cursor_execute", before_query)
    with api.factory() as db:
        assert not db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == account.user_id, AuthSession.revoked_at.is_(None)
            )
        ).all()


def test_session_issuance_first_is_included_in_deactivation(account):
    api = account.api
    inserting, deactivating, release = threading.Event(), threading.Event(), threading.Event()

    def before_insert(mapper, connection, target):
        if target.user_id == account.user_id:
            inserting.set()
            assert release.wait(10)

    def before_query(connection, cursor, statement, parameters, context, executemany):
        if inserting.is_set() and "FROM users" in statement and "FOR UPDATE" in statement:
            deactivating.set()

    engine = api.factory.kw["bind"]
    event.listen(AuthSession, "before_insert", before_insert)
    event.listen(engine, "before_cursor_execute", before_query)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(api.service.create, account.user_id, intent="login")
            try:
                assert inserting.wait(5)
                second = executor.submit(call, account, "POST", ME + "/deactivate")
                assert deactivating.wait(5)
            finally:
                release.set()
            first.result(timeout=10)
            assert second.result(timeout=10).status_code == 200
    finally:
        event.remove(AuthSession, "before_insert", before_insert)
        event.remove(engine, "before_cursor_execute", before_query)
    with api.factory() as db:
        sessions = db.scalars(
            select(AuthSession).where(AuthSession.user_id == account.user_id)
        ).all()
        assert len(sessions) == 2 and all(session.revoked_at for session in sessions)
