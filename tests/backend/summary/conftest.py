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


def read(env, actor="A", **kwargs):
    return env.api.client.get("/api/v1/summary", headers=env.headers[actor], **kwargs)


def bucket(env, actor="A", currency="INR"):
    response = read(env, actor)
    assert response.status_code == 200, response.text
    return next(row for row in response.json()["currencies"] if row["currency"] == currency)


def unavailable(response):
    assert response.status_code == 503, response.text
    assert response.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "Service is temporarily unavailable.",
        }
    }
