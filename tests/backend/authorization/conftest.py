from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.auth.authorization import AuthorizationService
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.extension_request import ExtensionRequest
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from auth_engine.conftest import clock, engine_env, settings  # noqa: F401
from sqlalchemy import delete


@pytest.fixture
def graph(engine_env):  # noqa: F811
    env = engine_env
    users = {name: env.user() for name in "ABC"}
    credentials = {
        name: env.service.create(identifier, intent="login") for name, identifier in users.items()
    }
    principals = {
        name: env.service.resolve("Bearer " + value.access_token)
        for name, value in credentials.items()
    }
    connection_ab, connection_ac = uuid4(), uuid4()
    groups = []
    with env.factory.begin() as db:
        for identifier, other in ((connection_ab, "B"), (connection_ac, "C")):
            db.add(
                Connection(
                    id=identifier,
                    requester_user_id=users["A"],
                    recipient_user_id=users[other],
                    status="ACCEPTED",
                )
            )
        db.flush()
        for lender, borrower, connection_id in (
            ("A", "C", connection_ac),
            ("C", "A", connection_ac),
            ("A", "B", connection_ab),
        ):
            ids = {
                name: uuid4()
                for name in (
                    "commitment",
                    "repayment",
                    "verification",
                    "ledger_event",
                    "extension_request",
                )
            }
            groups.append(ids)
            db.add(
                Commitment(
                    id=ids["commitment"],
                    connection_id=connection_id,
                    lender_user_id=users[lender],
                    borrower_user_id=users[borrower],
                    type="IOU",
                    status="ACTIVE",
                    principal_amount_minor=918273,
                    currency="INR",
                    description="Private commitment detail",
                    created_by_user_id=users[lender],
                )
            )
            db.flush()
            # Deliberately inconsistent attribution: reporter/actor/requester is B.
            # B3 must never turn these fields into financial membership authority.
            db.add(
                Repayment(
                    id=ids["repayment"],
                    commitment_id=ids["commitment"],
                    reported_by_user_id=users["B"],
                    amount_minor=12345,
                    currency="INR",
                    payment_date=env.clock.now.date(),
                    reported_at=env.clock.now,
                    status="PENDING_VERIFICATION",
                    note="Private repayment detail",
                )
            )
            db.flush()
            db.add(
                RepaymentVerification(
                    id=ids["verification"],
                    repayment_id=ids["repayment"],
                    decided_by_user_id=users["B"],
                    decision="VERIFIED",
                    decision_note="Private verification detail",
                    decided_at=env.clock.now,
                )
            )
            db.add(
                LedgerEvent(
                    id=ids["ledger_event"],
                    commitment_id=ids["commitment"],
                    actor_user_id=users["B"],
                    event_type="TEST_EVENT",
                    amount_minor=12345,
                    currency="INR",
                    repayment_id=ids["repayment"],
                    event_payload={"private": "Private ledger detail"},
                    occurred_at=env.clock.now,
                )
            )
            db.add(
                ExtensionRequest(
                    id=ids["extension_request"],
                    commitment_id=ids["commitment"],
                    requested_by_user_id=users["B"],
                    requested_due_date=env.clock.now.date(),
                    reason="Private extension detail",
                    status="REQUESTED",
                )
            )
    try:
        yield SimpleNamespace(
            **vars(env),
            users=users,
            credentials=credentials,
            principals=principals,
            connection_ab=connection_ab,
            connection_ac=connection_ac,
            groups=groups,
            authorization=AuthorizationService(env.service),
        )
    finally:
        with env.factory.begin() as db:
            for model, name in (
                (LedgerEvent, "ledger_event"),
                (RepaymentVerification, "verification"),
                (ExtensionRequest, "extension_request"),
                (Repayment, "repayment"),
                (Commitment, "commitment"),
            ):
                db.execute(delete(model).where(model.id.in_([group[name] for group in groups])))
            db.execute(delete(Connection).where(Connection.id.in_([connection_ab, connection_ac])))
