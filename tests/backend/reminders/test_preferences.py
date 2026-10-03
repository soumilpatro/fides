from concurrent.futures import ThreadPoolExecutor

import pytest
from app.api.notification_preference_schemas import NotificationPreferences
from app.models.auth_session import AuthSession
from app.models.notification_preference import NotificationPreference
from app.models.user import User
from app.notification_preferences import PreferenceService
from sqlalchemy import event, func, select

PATH = "/api/v1/notification-preferences"
DEFAULT = {"due_reminders_enabled": True, "overdue_reminders_enabled": True}


def request(env, method="GET", actor="A", **kwargs):
    return env.api.client.request(method, PATH, headers=env.headers[actor], **kwargs)


def test_default_read_side_effect_free(env):
    assert request(env).json() == DEFAULT
    with env.api.factory() as db:
        assert db.get(NotificationPreference, env.users["A"]) is None


def test_replacement_repeat_and_owner_isolation(env):
    for body in ({**DEFAULT, "due_reminders_enabled": False}, DEFAULT, DEFAULT):
        assert request(env, "POST", json=body).json() == body
        assert request(env).json() == body
    assert request(env, actor="B").json() == DEFAULT
    with env.api.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(NotificationPreference)
                .where(NotificationPreference.user_id == env.users["A"])
            )
            == 1
        )


@pytest.mark.parametrize("field", list(DEFAULT))
@pytest.mark.parametrize("value", [None, "true", "false", 1, 0, [], {}])
def test_strict_booleans(env, field, value):
    result = request(env, "POST", json={**DEFAULT, field: value})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"due_reminders_enabled": True},
        {"overdue_reminders_enabled": True},
        {**DEFAULT, "user_id": "someone"},
    ],
)
def test_closed_complete_object(env, body):
    assert request(env, "POST", json=body).status_code == 422


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_query_and_auth(env, method):
    kwargs = {"json": DEFAULT} if method == "POST" else {}
    assert request(env, method, params={"user_id": env.users["B"]}, **kwargs).status_code == 422
    assert env.api.client.request(method, PATH, **kwargs).status_code == 401


@pytest.mark.parametrize(
    "method,kwargs,status,code",
    [
        ("GET", {}, 200, None),
        ("POST", {"json": DEFAULT}, 200, None),
        ("POST", {"content": "{"}, 400, "MALFORMED_REQUEST"),
        ("POST", {"content": b"x" * 1048577}, 413, "REQUEST_TOO_LARGE"),
    ],
)
def test_b14_contract(env, method, kwargs, status, code):
    result = request(env, method, **kwargs)
    assert result.status_code == status
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Content-Type-Options"] == "nosniff"
    assert result.headers["Referrer-Policy"] == "no-referrer"
    assert result.headers["X-Request-ID"]
    if code:
        assert result.json()["error"]["code"] == code


@pytest.mark.parametrize("kind", ["deactivated", "revoked", "expired"])
def test_current_auth_revalidated(env, kind):
    with env.api.factory.begin() as db:
        if kind == "deactivated":
            db.get(User, env.users["A"]).status = "DEACTIVATED"
        else:
            row = db.scalar(select(AuthSession).where(AuthSession.user_id == env.users["A"]))
            if kind == "revoked":
                row.revoked_at = env.api.clock.now
                row.revocation_reason = "LOGOUT"
            else:
                env.api.clock.now = row.access_expires_at
    expected = 403 if kind == "deactivated" else 401
    assert request(env).status_code == expected
    assert request(env, "POST", json=DEFAULT).status_code == expected


def test_concurrent_upsert(env):
    principal = env.api.service.resolve(env.headers["A"]["Authorization"])
    service = PreferenceService(env.api.service)
    bodies = [
        NotificationPreferences(**{**DEFAULT, "due_reminders_enabled": value})
        for value in [True, False, True, False]
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda body: service.write(principal, body), bodies))
    assert all(result in bodies for result in results)
    with env.api.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(NotificationPreference)
                .where(NotificationPreference.user_id == principal.user_id)
            )
            == 1
        )


def test_rollback_safe_error(env):
    engine = env.api.factory.kw["bind"]

    def fail(connection):
        raise RuntimeError("private database diagnostic")

    event.listen(engine, "commit", fail)
    try:
        result = request(env, "POST", json=DEFAULT)
    finally:
        event.remove(engine, "commit", fail)
    assert result.status_code == 500
    assert "private database diagnostic" not in result.text
    with env.api.factory() as db:
        assert db.get(NotificationPreference, env.users["A"]) is None


def test_openapi(env):
    spec = env.api.app.openapi()
    assert set(spec["paths"][PATH]) == {"get", "post"}
    for method in ("get", "post"):
        assert spec["paths"][PATH][method]["security"]
    schema = spec["components"]["schemas"]["NotificationPreferences"]
    assert set(schema["properties"]) == set(DEFAULT)
    assert set(schema["required"]) == set(DEFAULT)
    assert schema["additionalProperties"] is False


def test_exact_body_ceiling_and_malformed_host(env):
    import json

    content = json.dumps(DEFAULT).encode()
    content += b" " * (1048576 - len(content))
    result = env.api.client.post(
        PATH,
        content=content,
        headers={**env.headers["A"], "Host": "[malformed", "Content-Type": "application/json"},
    )
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json() == DEFAULT


def test_oversized_declared_length_never_executes_service(env):
    from app.api.notification_preferences import get_preference_service

    calls = []

    def forbidden_service():
        calls.append(True)
        raise RuntimeError("service must not run")

    env.api.app.dependency_overrides[get_preference_service] = forbidden_service
    result = env.api.client.post(
        PATH, content=b"{}", headers={**env.headers["A"], "Content-Length": "1048577"}
    )
    assert result.status_code == 413
    assert not calls


def test_post_updates_timestamp_preserves_creation(env):
    from datetime import timedelta

    assert request(env, "POST", json=DEFAULT).status_code == 200
    with env.api.factory() as db:
        row = db.get(NotificationPreference, env.users["A"])
        created, updated = row.created_at, row.updated_at
    env.api.clock.now += timedelta(seconds=1)
    assert request(env, "POST", json=DEFAULT).status_code == 200
    with env.api.factory() as db:
        row = db.get(NotificationPreference, env.users["A"])
        assert row.created_at == created
        assert row.updated_at > updated
