import pytest
from app.config import Settings
from app.db import session
from pydantic import ValidationError
from sqlalchemy import text


def test_explicit_engine_isolation_overrides_server_default(db_engine, monkeypatch):
    settings = Settings(_env_file=None, database_url=db_engine.url.render_as_string(False))
    monkeypatch.setattr(session, "get_settings", lambda: settings)
    engine = session._build_engine()
    try:
        assert engine.dialect._on_connect_isolation_level == "READ COMMITTED"
        with engine.connect() as db:
            assert db.scalar(text("SHOW transaction_isolation")) == "read committed"
    finally:
        engine.dispose()


@pytest.mark.parametrize("value", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_unsupported_application_isolation_rejected(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_isolation_level=value)
