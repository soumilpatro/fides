"""Smoke tests for the B0 gate condition: "Service starts cleanly."

These verify the application factory boots, the health/readiness
endpoints respond correctly, no secrets are exposed, and a request
correlation ID is attached to responses.
"""

from fastapi.testclient import TestClient


def test_app_starts_and_health_endpoint_responds(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "fides-backend"


def test_readiness_endpoint_responds(client: TestClient) -> None:
    response = client.get("/readiness")

    assert response.status_code == 200
    body = response.json()
    # B1 extends readiness to verify DB connectivity (as B0's own code
    # comment anticipated). This assertion was updated from B0's exact
    # {"status": "ready"} equality check to accommodate that — flagged
    # explicitly in the B1 implementation report rather than left as a
    # silent test change.
    assert body["status"] in {"ready", "not_ready"}
    assert "database" in body


def test_health_response_contains_no_secret_like_fields(client: TestClient) -> None:
    response = client.get("/health")
    body = response.json()

    forbidden_keys = {"password", "secret", "token", "key", "database_url"}
    assert forbidden_keys.isdisjoint(set(k.lower() for k in body.keys()))


def test_request_correlation_id_is_present_on_response(client: TestClient) -> None:
    response = client.get("/health")

    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_request_correlation_id_is_propagated_when_supplied(
    client: TestClient,
) -> None:
    response = client.get("/health", headers={"X-Request-ID": "test-correlation-id"})

    assert response.headers["X-Request-ID"] == "test-correlation-id"


def test_unknown_route_returns_stable_error_envelope(client: TestClient) -> None:
    response = client.get("/this-route-does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert "code" in body["error"]
    assert "message" in body["error"]
