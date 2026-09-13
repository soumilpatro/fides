from uuid import uuid4

import pytest
from app.main import create_app

from .test_lifecycle import create

BASE = "/api/v1/connections"
ROUTES = [
    ("POST", ""),
    ("GET", ""),
    ("GET", "/{id}"),
    ("POST", "/{id}/accept"),
    ("POST", "/{id}/reject"),
    ("POST", "/{id}/block"),
    ("DELETE", "/{id}"),
]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"phone": None},
        {"phone": 123},
        {"phone": "+14155552673", "requester_user_id": str(uuid4())},
        {"phone": "4155552673"},
        {"phone": "+1 4155552673"},
        {"phone": "+123"},
        {"phone": ""},
        {"phone": True},
        [],
    ],
)
def test_closed_phone_schema(peers, body):
    response = peers.call("POST", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["Cache-Control"] == "no-store"


def test_phone_normalization(peers):
    response = peers.call("POST", json={"phone": "  " + peers.phones["B"] + "  "})
    assert response.status_code == 201
    assert response.json()["recipient"]["id"] == str(peers.users["B"])


@pytest.mark.parametrize("method,path", ROUTES)
def test_bearer_required(peers, method, path):
    response = peers.api.client.request(
        method,
        BASE + path.replace("{id}", str(uuid4())),
        json={"phone": peers.phones["B"]} if path == "" and method == "POST" else {},
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("method,path", ROUTES)
def test_expired_access_rejected(peers, method, path):
    from datetime import timedelta

    peers.api.clock.now += timedelta(minutes=15)
    response = peers.call(
        method,
        path.replace("{id}", str(uuid4())),
        json={"phone": peers.phones["B"]} if path == "" and method == "POST" else {},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_EXPIRED"


@pytest.mark.parametrize("action", ["accept", "reject", "block", "remove"])
@pytest.mark.parametrize("content,expected", [("{", 400), ('{"status":"ACCEPTED"}', 422)])
def test_action_overposting_and_json(peers, action, content, expected):
    row = create(peers)
    response = peers.call(
        "DELETE" if action == "remove" else "POST",
        "/" + row["id"] + ("" if action == "remove" else "/" + action),
        content=content,
    )
    assert response.status_code == expected


def test_malformed_and_request_correlation(peers):
    response = peers.api.client.post(
        BASE, content="{", headers={**peers.headers["A"], "X-Request-ID": "bad value!"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    assert response.headers["X-Request-ID"] != "bad value!"
    assert response.headers["Cache-Control"] == "no-store"
    row = create(peers)
    response = peers.call("GET", "/" + row["id"])
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]


def test_safe_unexpected_failure(peers, monkeypatch):
    from app.connections import ConnectionService

    def fail(*args):
        raise RuntimeError("private phone token detail")

    monkeypatch.setattr(ConnectionService, "list", fail)
    response = peers.call("GET")
    assert response.status_code == 500
    assert "private" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_openapi():
    schema = create_app().openapi()
    actual = {
        (method.upper(), path[len(BASE) :])
        for path, item in schema["paths"].items()
        if path.startswith(BASE)
        for method in item
    }
    assert actual == set(ROUTES)
    models = schema["components"]["schemas"]
    assert models["ConnectionRequest"]["additionalProperties"] is False
    assert models["ConnectionRequest"]["required"] == ["phone"]
    assert set(models["ConnectionRequest"]["properties"]) == {"phone"}
    assert models["ConnectionRequest"]["properties"]["phone"]["type"] == "string"
    assert set(models["ConnectionResponse"]["properties"]) == {
        "id",
        "status",
        "requester",
        "recipient",
        "created_at",
        "updated_at",
    }
    assert set(models["ParticipantResponse"]["properties"]) == {"id", "display_name"}
    for method, path in ROUTES:
        operation = schema["paths"][BASE + path][method.lower()]
        assert operation["security"] == [{"HTTPBearer": []}]
        success = "201" if method == "POST" and path == "" else "200"
        assert success in operation["responses"]
        for status in ("400", "401", "403", "404", "409", "422", "500", "503"):
            assert operation["responses"][status]["content"]["application/json"]["schema"][
                "$ref"
            ].endswith("AuthErrorEnvelope")


def test_openapi_action_bodies_and_headers():
    schema = create_app().openapi()
    for method, path in ROUTES:
        operation = schema["paths"][BASE + path][method.lower()]
        for response in operation["responses"].values():
            assert response["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
        if method == "DELETE" or path.endswith(("/accept", "/reject", "/block")):
            body = operation["requestBody"]
            assert body["required"] is False
            assert body["content"]["application/json"]["schema"]["additionalProperties"] is False
