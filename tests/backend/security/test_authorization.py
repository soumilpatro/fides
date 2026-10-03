from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.api.auth import get_auth_service
from app.api.dependencies import require_principal
from app.auth.sessions import Principal
from app.main import create_app
from authorization.conftest import clock, engine_env, graph, settings  # noqa: F401
from fastapi import Depends
from fastapi.testclient import TestClient

from .test_responses import HOSTS


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize(
    "kind",
    ["connection", "commitment", "repayment", "verification", "ledger_event", "extension_request"],
)
def test_host_does_not_change_real_auth_or_participant_lookup(graph, host, kind):  # noqa: F811
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: SimpleNamespace(
        session_service=graph.service
    )

    @app.get("/api/v1/commitments/{resource_id}/security-test")
    def protected(resource_id: UUID, principal: Principal = Depends(require_principal)):
        with graph.factory.begin() as db:
            return getattr(graph.authorization, kind)(db, principal, resource_id)

    identifier = graph.connection_ab if kind == "connection" else graph.groups[0][kind]
    outsider = "C" if kind == "connection" else "B"

    def headers(actor):
        return {"Host": host, "Authorization": "Bearer " + graph.credentials[actor].access_token}

    with TestClient(app) as client:
        path = f"/api/v1/commitments/{identifier}/security-test"
        assert client.get(path, headers=headers("A")).status_code == 200
        unrelated = client.get(path, headers=headers(outsider))
        missing = client.get(
            f"/api/v1/commitments/{uuid4()}/security-test", headers=headers(outsider)
        )
        assert unrelated.status_code == missing.status_code == 404
        assert (
            unrelated.json()
            == missing.json()
            == {"error": {"code": "NOT_FOUND", "message": "Unavailable resource."}}
        )
        assert unrelated.headers["cache-control"] == "no-store"
        assert client.get(path, headers={"Host": host}).status_code == 401
