import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.auth.sessions import LogoutRecognition, Principal, SessionService
from app.auth.tokens import generate_token, token_digest
from app.core.errors import AuthError
from app.models.audit_log import AuditLog
from app.models.auth_rate_limit_bucket import AuthRateLimitBucket
from app.models.auth_session import AuthSession
from app.models.enums import UserStatus
from app.models.user import User
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError


def issued(env):
    user_id = env.user()
    credentials = env.service.create(user_id, intent="login", request_id="request-1")
    return user_id, credentials


def bearer(credentials):
    return "Bearer " + credentials.access_token


def assert_error(code, function, *args, **kwargs):
    with pytest.raises(AuthError) as error:
        function(*args, **kwargs)
    assert error.value.code == code


def test_create_persists_only_hashes_with_atomic_audit(engine_env, caplog):
    env = engine_env
    caplog.set_level(logging.DEBUG)
    user_id, credentials = issued(env)
    assert credentials.access_token[4:] != credentials.refresh_token[4:]
    assert credentials.access_expires_at == env.clock.now + timedelta(minutes=15)
    assert credentials.refresh_expires_at == env.clock.now + timedelta(days=30)
    with env.factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == user_id))
        assert session.access_token_hash == token_digest(credentials.access_token, "access")
        assert session.refresh_token_hash == token_digest(credentials.refresh_token, "refresh")
        assert (
            session.rotation_count,
            session.last_rotated_at,
            session.revoked_at,
            session.revocation_reason,
        ) == (0, None, None, None)
        audit = db.scalar(select(AuditLog).where(AuditLog.object_id == session.id))
        assert audit.action == "AUTH_SESSION_CREATED" and audit.result == "SUCCESS"
        assert audit.metadata_ == {"intent": "login", "request_id": "request-1"}
        assert audit.actor_user_id == user_id
        assert credentials.access_token not in str(session.__dict__) + str(audit.metadata_)
    assert credentials.access_token not in caplog.text + repr(credentials)
    assert credentials.refresh_token not in caplog.text + repr(credentials)
    second = env.service.create(user_id, intent="signup")
    assert env.service.resolve(bearer(second)).session_id != session.id


@pytest.mark.parametrize(
    "header,code",
    [
        (None, "AUTH_REQUIRED"),
        ("", "AUTH_REQUIRED"),
        ("Basic xx", "INVALID_AUTH_TOKEN"),
        ("Bearer xx", "INVALID_AUTH_TOKEN"),
        ("Bearer  xx", "INVALID_AUTH_TOKEN"),
        ("Bearer\txx", "INVALID_AUTH_TOKEN"),
    ],
)
def test_bad_bearer(engine_env, header, code):
    assert_error(code, engine_env.service.resolve, header)
    assert_error(code, engine_env.service.recognize_logout, header)


def test_unknown_and_cross_type(engine_env):
    for kind in ["access", "refresh"]:
        header = "Bearer " + generate_token(kind)
        assert_error("INVALID_AUTH_TOKEN", engine_env.service.resolve, header)
        assert_error("INVALID_AUTH_TOKEN", engine_env.service.recognize_logout, header)


@pytest.mark.parametrize(
    "state,code",
    [
        (UserStatus.DEACTIVATED, "ACCOUNT_DEACTIVATED"),
        (UserStatus.ANONYMIZED, "ACCOUNT_UNAVAILABLE"),
    ],
)
def test_status_and_revocation_precede_expiry(engine_env, state, code):
    env = engine_env
    user_id, credentials = issued(env)
    recognition = env.service.recognize_logout(bearer(credentials))
    with env.factory.begin() as db:
        db.get(User, user_id).status = state
    env.clock.now += timedelta(days=31)
    assert_error(code, env.service.resolve, bearer(credentials))
    assert_error(code, env.service.refresh, credentials.refresh_token, ip="192.0.2.1")
    assert_error(code, env.service.create, user_id, intent="login")
    env.service.revoke_one(recognition)
    assert_error("SESSION_REVOKED", env.service.resolve, bearer(credentials))
    assert_error("SESSION_REVOKED", env.service.refresh, credentials.refresh_token, ip="192.0.2.1")


def test_strict_expiry_and_logout_only_capability(engine_env):
    env = engine_env
    _, credentials = issued(env)
    principal = env.service.resolve(bearer(credentials))
    assert type(principal) is Principal
    env.clock.now = credentials.access_expires_at - timedelta(microseconds=1)
    assert env.service.resolve(bearer(credentials)) == principal
    env.clock.now = credentials.access_expires_at
    assert_error("AUTH_TOKEN_EXPIRED", env.service.resolve, bearer(credentials))
    recognition = env.service.recognize_logout(bearer(credentials))
    assert type(recognition) is LogoutRecognition and not isinstance(recognition, Principal)
    assert_error("INVALID_AUTH_TOKEN", env.service.resolve, recognition)
    with pytest.raises(TypeError):
        env.service.revoke_one(principal)
    env.service.revoke_one(recognition)
    assert_error("SESSION_REVOKED", env.service.recognize_logout, bearer(credentials))
    assert_error("SESSION_REVOKED", env.service.revoke_one, recognition)


def test_refresh_rotation_fixed_deadline_and_cap(engine_env):
    env = engine_env
    _, original = issued(env)
    recognition = env.service.recognize_logout(bearer(original))
    env.clock.now += timedelta(minutes=5)
    rotated = env.service.refresh(original.refresh_token, ip="192.0.2.1", request_id="refresh-1")
    assert rotated.refresh_expires_at == original.refresh_expires_at
    assert rotated.access_expires_at == env.clock.now + timedelta(minutes=15)
    assert rotated.access_token != original.access_token
    assert rotated.refresh_token != original.refresh_token
    assert_error("INVALID_AUTH_TOKEN", env.service.resolve, bearer(original))
    assert_error("INVALID_AUTH_TOKEN", env.service.recognize_logout, bearer(original))
    assert_error("INVALID_AUTH_TOKEN", env.service.revoke_one, recognition)
    assert_error(
        "INVALID_REFRESH_TOKEN", env.service.refresh, original.refresh_token, ip="192.0.2.1"
    )
    env.clock.now = original.refresh_expires_at - timedelta(seconds=1)
    final = env.service.refresh(rotated.refresh_token, ip="192.0.2.1")
    assert final.access_expires_at == final.refresh_expires_at == original.refresh_expires_at
    with env.factory() as db:
        session = db.get(AuthSession, recognition.session_id)
        assert session.rotation_count == 2 and session.last_rotated_at == env.clock.now
        logs = db.scalars(select(AuditLog).where(AuditLog.object_id == session.id)).all()
        assert len(logs) == 3
        assert {log.metadata_.get("rotation_count") for log in logs} == {None, 1, 2}
    env.clock.now = final.refresh_expires_at
    assert_error("REFRESH_TOKEN_EXPIRED", env.service.refresh, final.refresh_token, ip="192.0.2.1")


@pytest.mark.parametrize("credential", ["bad", "fda_" + "A" * 43, "fdr_" + "A" * 43])
def test_invalid_refresh_counts_ip(engine_env, credential):
    env = engine_env
    assert_error("INVALID_REFRESH_TOKEN", env.service.refresh, credential, ip="192.0.2.1")
    with env.factory() as db:
        count = db.scalar(
            select(AuthRateLimitBucket.request_count).where(
                AuthRateLimitBucket.subject_hash == env.limiter.subject("ip", "192.0.2.1")
            )
        )
        assert count == 1


def test_revocation_one_all_idempotence(engine_env):
    env = engine_env
    user_id, first = issued(env)
    second = env.service.create(user_id, intent="login")
    other_user, other = issued(env)
    first_id = env.service.resolve(bearer(first)).session_id
    second_id = env.service.resolve(bearer(second)).session_id
    env.clock.now += timedelta(minutes=1)
    env.service.revoke_one(env.service.recognize_logout(bearer(first)))
    assert env.service.resolve(bearer(second)).user_id == user_id
    assert env.service.revoke_all(user_id) == 1
    assert env.service.revoke_all(user_id) == 0
    assert env.service.resolve(bearer(other)).user_id == other_user
    with env.factory() as db:
        for identifier, reason, credentials in [
            (first_id, "LOGOUT", first),
            (second_id, "ACCOUNT_DEACTIVATED", second),
        ]:
            session = db.get(AuthSession, identifier)
            assert session.revocation_reason == reason and session.revoked_at == env.clock.now
            assert session.access_expires_at == credentials.access_expires_at
            assert session.refresh_expires_at == credentials.refresh_expires_at
            assert session.rotation_count == 0
            assert session.access_token_hash == token_digest(credentials.access_token, "access")
            assert session.refresh_token_hash == token_digest(credentials.refresh_token, "refresh")
        logs = db.scalars(
            select(AuditLog).where(
                AuditLog.actor_user_id == user_id, AuditLog.action == "AUTH_SESSION_REVOKED"
            )
        ).all()
        assert len(logs) == 2
        assert {log.metadata_["reason"] for log in logs} == {"LOGOUT", "ACCOUNT_DEACTIVATED"}


@pytest.mark.parametrize("operation", ["create", "refresh", "revoke_one", "revoke_all"])
def test_audit_failure_rolls_back_mutation_and_retains_refresh_budget(engine_env, operation):
    env = engine_env
    user_id, credentials = issued(env)
    recognition = env.service.recognize_logout(bearer(credentials))

    def fail_audit(mapper, connection, target):
        raise SQLAlchemyError("sensitive SQL diagnostics must not escape")

    event.listen(AuditLog, "before_insert", fail_audit)
    try:
        actions = {
            "create": lambda: env.service.create(user_id, intent="login"),
            "refresh": lambda: env.service.refresh(credentials.refresh_token, ip="192.0.2.1"),
            "revoke_one": lambda: env.service.revoke_one(recognition),
            "revoke_all": lambda: env.service.revoke_all(user_id),
        }
        assert_error("SERVICE_UNAVAILABLE", actions[operation])
    finally:
        event.remove(AuditLog, "before_insert", fail_audit)
    with env.factory() as db:
        rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user_id)).all()
        assert len(rows) == 1
        assert rows[0].rotation_count == 0 and rows[0].revoked_at is None
        assert rows[0].access_token_hash == token_digest(credentials.access_token, "access")
        if operation == "refresh":
            buckets = db.scalars(
                select(AuthRateLimitBucket).where(
                    AuthRateLimitBucket.subject_hash.in_(
                        [
                            env.limiter.subject("ip", "192.0.2.1"),
                            env.limiter.subject("session", recognition.session_id),
                        ]
                    )
                )
            ).all()
            assert len(buckets) == 2 and all(bucket.request_count == 1 for bucket in buckets)


def test_concurrent_refresh_two_connections_one_winner(engine_env):
    env = engine_env
    user_id, credentials = issued(env)
    gate = threading.Barrier(2, timeout=10)
    pids = set()
    services = [SessionService(env.factory, env.settings, clock=env.clock) for _ in range(2)]

    # Capture the ACTUAL connections attempting the User lock. Hold both there
    # until each has found/reserved the original credential, then release them.
    def before_query(connection, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            pids.add(connection.connection.driver_connection.info.backend_pid)
            gate.wait()

    def run(service):
        try:
            return service.refresh(credentials.refresh_token, ip="192.0.2.1")
        except AuthError as error:
            return error.code

    engine = env.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_query)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, services))
    finally:
        event.remove(engine, "before_cursor_execute", before_query)
    assert len(pids) == 2
    assert sum(result == "INVALID_REFRESH_TOKEN" for result in results) == 1
    winner = next(result for result in results if not isinstance(result, str))
    assert env.service.resolve(bearer(winner)).user_id == user_id
    with env.factory() as db:
        rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user_id)).all()
        assert len(rows) == 1 and rows[0].rotation_count == 1 and rows[0].revoked_at is None


def test_sql_debug_logs_do_not_expose_binds_or_result_hashes(engine_env, caplog):
    env = engine_env
    caplog.set_level(logging.DEBUG, logger="sqlalchemy.engine")
    _, credentials = issued(env)
    env.service.resolve(bearer(credentials))
    env.service.refresh(credentials.refresh_token, ip="192.0.2.198")
    for secret in [
        credentials.access_token,
        credentials.refresh_token,
        "192.0.2.198",
        repr(token_digest(credentials.access_token, "access")),
        token_digest(credentials.access_token, "access").hex(),
    ]:
        assert secret not in caplog.text


@pytest.mark.parametrize("operation", ["create", "refresh"])
def test_issuance_rechecks_user_after_waiting_for_lock(engine_env, operation):
    env = engine_env
    user_id, credentials = issued(env)
    attempting_lock = threading.Event()
    main_thread = threading.get_ident()

    def before_query(connection, cursor, statement, parameters, context, executemany):
        if (
            threading.get_ident() != main_thread
            and "FROM users" in statement
            and "FOR UPDATE" in statement
        ):
            attempting_lock.set()

    def issue():
        try:
            if operation == "create":
                return env.service.create(user_id, intent="login")
            return env.service.refresh(credentials.refresh_token, ip="192.0.2.1")
        except AuthError as error:
            return error.code

    engine = env.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_query)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with env.factory.begin() as db:
                user = db.scalar(select(User).where(User.id == user_id).with_for_update())
                future = executor.submit(issue)
                assert attempting_lock.wait(5)
                user.status = UserStatus.DEACTIVATED
            assert future.result(timeout=5) == "ACCOUNT_DEACTIVATED"
    finally:
        event.remove(engine, "before_cursor_execute", before_query)
    with env.factory() as db:
        sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user_id)).all()
        assert len(sessions) == 1 and sessions[0].rotation_count == 0


def test_refresh_rate_limit_precedes_rotation(engine_env):
    env = engine_env
    env.settings.auth_refresh_session_1m_limit = 1
    _, credentials = issued(env)
    rotated = env.service.refresh(credentials.refresh_token, ip="192.0.2.1")
    assert_error("AUTH_RATE_LIMITED", env.service.refresh, rotated.refresh_token, ip="192.0.2.2")
    assert env.service.resolve(bearer(rotated))


def test_database_clock_default_is_fresh(engine_env):
    env = engine_env
    service = SessionService(env.factory, env.settings)
    with env.factory() as db:
        before = db.scalar(text("SELECT clock_timestamp()"))
    credentials = service.create(env.user(), intent="login")
    with env.factory() as db:
        after = db.scalar(text("SELECT clock_timestamp()"))
    created = credentials.refresh_expires_at - timedelta(days=30)
    assert before <= created <= after
    assert service.resolve(bearer(credentials))


def test_revocation_helper_participates_in_outer_rollback(engine_env):
    env = engine_env
    user_id, credentials = issued(env)
    with env.factory() as db:
        user = db.scalar(select(User).where(User.id == user_id).with_for_update())
        assert env.service.revoke_all_locked(db, user) == 1
        db.rollback()
    assert env.service.resolve(bearer(credentials)).user_id == user_id
    with env.factory() as db:
        assert not db.scalars(
            select(AuditLog).where(
                AuditLog.actor_user_id == user_id, AuditLog.action == "AUTH_SESSION_REVOKED"
            )
        ).all()


@pytest.mark.parametrize("operation", ["create", "refresh"])
def test_commit_failure_withholds_generated_credentials(engine_env, monkeypatch, operation, caplog):
    env = engine_env
    user_id, original = issued(env)
    engine = env.factory.kw["bind"]
    generated = []
    failed_commits = []
    real_commit = engine.dialect.do_commit

    def generate(kind):
        value = generate_token(kind)
        generated.append((kind, value))
        return value

    def commit(dbapi_connection):
        # The limiter must commit normally. Fail at the DBAPI commit boundary
        # only after the session mutation AND audit were flushed to PostgreSQL.
        with dbapi_connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM auth_sessions WHERE user_id = %s "
                "AND (rotation_count > 0 OR access_token_hash = %s)",
                (user_id, token_digest(generated[0][1], "access"))
                if generated
                else (user_id, bytes(32)),
            )
            changed = cursor.fetchone()[0]
        if changed:
            failed_commits.append(changed)
            raise engine.dialect.dbapi.OperationalError("simulated commit rejection")
        real_commit(dbapi_connection)

    caplog.set_level(logging.DEBUG)
    with monkeypatch.context() as patch:
        patch.setattr("app.auth.sessions.generate_token", generate)
        patch.setattr(engine.dialect, "do_commit", commit)
        if operation == "create":
            assert_error("SERVICE_UNAVAILABLE", env.service.create, user_id, intent="login")
        else:
            assert_error(
                "SERVICE_UNAVAILABLE", env.service.refresh, original.refresh_token, ip="192.0.2.1"
            )
    assert failed_commits == [1] and [kind for kind, _ in generated] == ["access", "refresh"]
    assert env.service.resolve(bearer(original)).user_id == user_id
    for kind, value in generated:
        assert value not in caplog.text
        if kind == "access":
            assert_error("INVALID_AUTH_TOKEN", env.service.resolve, "Bearer " + value)
        else:
            assert_error("INVALID_REFRESH_TOKEN", env.service.refresh, value, ip="192.0.2.1")
    with env.factory() as db:
        rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user_id)).all()
        assert len(rows) == 1 and rows[0].rotation_count == 0
        assert rows[0].refresh_token_hash == token_digest(original.refresh_token, "refresh")
        logs = db.scalars(select(AuditLog).where(AuditLog.actor_user_id == user_id)).all()
        assert len(logs) == 1 and logs[0].action == "AUTH_SESSION_CREATED"
