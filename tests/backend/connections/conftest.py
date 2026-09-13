from types import SimpleNamespace

import pytest
from app.models.connection import Connection
from app.models.user import User
from auth_api.conftest import api, clock, engine_env, settings  # noqa: F401
from sqlalchemy import delete, or_


@pytest.fixture
def peers(api):  # noqa: F811
    users = {name: api.user() for name in "ABC"}
    phones = dict(zip("ABC", ("+14155552672", "+14155552673", "+14155552674"), strict=True))
    with api.factory.begin() as db:
        for name, identifier in users.items():
            db.get(User, identifier).phone_e164 = phones[name]
    credentials = {
        name: api.service.create(identifier, intent="login") for name, identifier in users.items()
    }
    headers = {
        name: {"Authorization": "Bearer " + token.access_token}
        for name, token in credentials.items()
    }

    def call(method, suffix="", actor="A", **kwargs):
        return api.client.request(
            method, "/api/v1/connections" + suffix, headers=headers[actor], **kwargs
        )

    try:
        yield SimpleNamespace(api=api, users=users, phones=phones, headers=headers, call=call)
    finally:
        with api.factory.begin() as db:
            db.execute(
                delete(Connection).where(
                    or_(
                        Connection.requester_user_id.in_(users.values()),
                        Connection.recipient_user_id.in_(users.values()),
                    )
                )
            )
