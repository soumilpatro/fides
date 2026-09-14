from datetime import timedelta
from uuid import UUID

import pytest
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from sqlalchemy import select

from .conftest import create


def version(b6, identifier, number, effective):
    with b6.api.factory.begin() as db:
        original = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(identifier),
                CommitmentTermsVersion.version_no == 1,
            )
        )
        row = CommitmentTermsVersion(
            commitment_id=original.commitment_id,
            version_no=number,
            effective_at=effective,
            interest_type=original.interest_type,
            interest_rate_bps=original.interest_rate_bps,
            due_date=original.due_date,
            grace_period_days=original.grace_period_days,
            schedule_definition=original.schedule_definition,
            created_by_user_id=original.created_by_user_id,
        )
        db.add(row)
        db.flush()
        if original.schedule_definition and original.schedule_definition["installment_dates"]:
            originals = list(
                db.scalars(
                    select(CommitmentInstallment)
                    .where(CommitmentInstallment.terms_version_id == original.id)
                    .order_by(CommitmentInstallment.sequence_no)
                )
            )
            for r in originals:
                db.add(
                    CommitmentInstallment(
                        commitment_id=r.commitment_id,
                        terms_version_id=row.id,
                        sequence_no=(number - 1) * len(originals) + r.sequence_no,
                        due_date=r.due_date,
                        principal_amount_minor=r.principal_amount_minor,
                        interest_amount_minor=r.interest_amount_minor,
                        total_due_minor=r.total_due_minor,
                        status="PENDING",
                    )
                )
        return str(row.id)


@pytest.mark.parametrize("schedule", [False, True])
def test_current_version_and_history(b6, schedule):
    identifier = create(b6, b6.terms if schedule else None)
    initial = b6.request("GET", f"/{identifier}/terms").json()["versions"][0]
    now = b6.api.clock.now
    v3 = version(b6, identifier, 3, now + timedelta(days=1))
    v2 = version(b6, identifier, 2, now - timedelta(seconds=1))
    body = b6.request("GET", f"/{identifier}/terms").json()
    assert body["current_terms_version_id"] == v2
    assert [v["version_no"] for v in body["versions"]] == [1, 2, 3]
    assert body["versions"][0] == initial
    rows = b6.request("GET", f"/{identifier}/installments").json()
    assert len(rows) == (3 if schedule else 0)
    assert all(r["terms_version_id"] == v2 for r in rows)
    assert all(r["terms_version_id"] != v3 for r in rows)


@pytest.mark.parametrize(
    "corruption",
    [
        "no_effective",
        "metadata",
        "mode",
        "timezone",
        "missing_installment",
        "amount",
        "wrong_parent",
        "creator",
    ],
)
def test_inconsistent_data_safe_failure(b6, corruption):
    identifier = create(b6, b6.terms)
    with b6.api.factory.begin() as db:
        row = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(identifier)
            )
        )
        installment = db.scalar(
            select(CommitmentInstallment)
            .where(CommitmentInstallment.terms_version_id == row.id)
            .order_by(CommitmentInstallment.sequence_no)
        )
        if corruption == "no_effective":
            row.effective_at = b6.api.clock.now + timedelta(days=1)
        elif corruption == "metadata":
            row.schedule_definition = {**row.schedule_definition, "private": "secret"}
        elif corruption == "mode":
            row.schedule_definition = {**row.schedule_definition, "schedule_mode": "single"}
        elif corruption == "timezone":
            row.schedule_definition = {**row.schedule_definition, "due_timezone": "bad/zone"}
        elif corruption == "missing_installment":
            db.delete(installment)  # Corrupt test fixture only; no application deletion.
        elif corruption == "amount":
            installment.total_due_minor += 1
        elif corruption == "creator":
            row.created_by_user_id = b6.users["C"]
        elif corruption == "wrong_parent":
            # Use an unrelated commitment without a conflicting installment sequence.
            other = create(b6)
            installment.commitment_id = UUID(other)
    response = b6.request("GET", f"/{identifier}/installments")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_effective_boundary(b6, offset):
    identifier = create(b6)
    initial = b6.request("GET", f"/{identifier}/terms").json()["current_terms_version_id"]
    candidate = version(b6, identifier, 2, b6.api.clock.now + timedelta(microseconds=offset))
    response = b6.request("GET", f"/{identifier}/terms")
    assert response.json()["current_terms_version_id"] == (candidate if offset <= 0 else initial)
