import pytest
from app.connections import ConnectionService
from app.core.errors import ResourceUnavailable
from app.models.commitment import Commitment
from app.models.extension_request import ExtensionRequest
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from authorization.conftest import clock, engine_env, graph, settings  # noqa: F401
from sqlalchemy import select


@pytest.mark.parametrize("action", ["block", "remove"])
def test_financial_history_and_authorization_survive(graph, action):  # noqa: F811
    service = ConnectionService(graph.service)
    models = (
        Commitment,
        Repayment,
        RepaymentVerification,
        LedgerEvent,
        ExtensionRequest,
    )

    def snapshot():
        with graph.factory() as db:
            return {
                model.__name__: list(db.execute(select(model.__table__).order_by(model.id)))
                for model in models
            }

    before = snapshot()
    service.mutate(graph.principals["A"], graph.connection_ac, action)
    assert snapshot() == before
    for name, identifier in graph.groups[0].items():
        method = {"verification": "verification"}.get(name, name)
        for actor in ("A", "C"):
            with graph.factory.begin() as db:
                assert getattr(graph.authorization, method)(db, graph.principals[actor], identifier)
        with graph.factory.begin() as db, pytest.raises(ResourceUnavailable):
            getattr(graph.authorization, method)(db, graph.principals["B"], identifier)
