from types import SimpleNamespace

import pytest
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from sqlalchemy import delete, select

from commitments.conftest import api, clock, ctx, engine_env, peers, settings  # noqa: F401


@pytest.fixture
def b6(ctx):  # noqa: F811
    terms = {
        "interest_type": "SIMPLE_FIXED",
        "interest_rate_bps": 500,
        "installment_dates": ["2026-10-10", "2026-11-10", "2026-12-10"],
    }
    try:
        yield SimpleNamespace(**vars(ctx), terms=terms)
    finally:
        with ctx.api.factory.begin() as db:
            ids = select(Commitment.id).where(Commitment.connection_id == ctx.connection)
            db.execute(
                delete(CommitmentInstallment).where(CommitmentInstallment.commitment_id.in_(ids))
            )


def create(b6, terms=None, **values):
    body = {**b6.body, **values}
    if terms is not None:
        body["terms"] = terms
    response = b6.request("POST", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]
