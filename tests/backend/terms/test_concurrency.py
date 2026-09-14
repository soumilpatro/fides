from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from sqlalchemy import select

from commitments.test_concurrency import (
    test_concurrent_creates as run_creates,
)
from commitments.test_concurrency import (
    test_create_races_actual_b2_deactivation as run_deactivation,
)
from commitments.test_concurrency import (
    test_create_rechecks_after_lock_wait as run_recheck,
)
from commitments.test_concurrency import (
    test_inflight_duplicate_returns_conflict as run_inflight,
)


def with_terms(b6):
    b6.body["terms"] = b6.terms
    return b6


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_creates_with_terms(b6, same_key):
    run_creates(with_terms(b6), same_key)
    with b6.api.factory() as db:
        commitments = list(
            db.scalars(select(Commitment.id).where(Commitment.connection_id == UUID(b6.connection)))
        )
        for identifier in commitments:
            rows = list(
                db.scalars(
                    select(CommitmentInstallment).where(
                        CommitmentInstallment.commitment_id == identifier
                    )
                )
            )
            assert len(rows) == 3
            assert sum(r.total_due_minor for r in rows) == 10500


def test_inflight_with_terms(b6):
    run_inflight(with_terms(b6))


@pytest.mark.parametrize("kind", ["account", "connection"])
def test_locked_state_recheck_with_terms(b6, kind):
    run_recheck(with_terms(b6), kind)


def test_real_deactivation_with_terms(b6):
    run_deactivation(with_terms(b6))
