from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.enums import CommitmentType, ConnectionStatus
from auth_api.conftest import api, clock, engine_env, settings  # noqa: F401
from auth_api.test_api import signup
from sqlalchemy import delete


@pytest.fixture
def account(api):  # noqa: F811
    credentials, _ = signup(api)
    user_id = UUID(credentials["user"]["id"])
    other_id = api.user()
    connections, commitments = [], []

    def commitment(status, *, borrower=False, db=None):
        new_connection = not connections
        connection_id, commitment_id = (uuid4() if new_connection else connections[0]), uuid4()
        if new_connection:
            connections.append(connection_id)
        commitments.append(commitment_id)

        def insert(session):
            if new_connection:
                session.add(
                    Connection(
                        id=connection_id,
                        requester_user_id=user_id,
                        recipient_user_id=other_id,
                        status=ConnectionStatus.ACCEPTED,
                    )
                )
                session.flush()
            session.add(
                Commitment(
                    id=commitment_id,
                    connection_id=connection_id,
                    lender_user_id=other_id if borrower else user_id,
                    borrower_user_id=user_id if borrower else other_id,
                    type=CommitmentType.IOU,
                    status=status,
                    principal_amount_minor=10000,
                    currency="INR",
                    created_by_user_id=user_id,
                )
            )
            session.flush()

        if db is not None:
            insert(db)
        else:
            with api.factory.begin() as session:
                insert(session)
        return commitment_id

    try:
        yield SimpleNamespace(
            api=api,
            credentials=credentials,
            user_id=user_id,
            other_id=other_id,
            commitment=commitment,
            headers={"Authorization": "Bearer " + credentials["access_token"]},
        )
    finally:
        with api.factory.begin() as db:
            db.execute(delete(Commitment).where(Commitment.id.in_(commitments)))
            db.execute(delete(Connection).where(Connection.id.in_(connections)))
