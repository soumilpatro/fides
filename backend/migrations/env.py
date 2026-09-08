"""Alembic environment configuration (B1 scope).

Reads the database connection string from the DATABASE_URL environment
variable (never from alembic.ini), and wires up `Base.metadata` from
`app.models` so `alembic revision --autogenerate` can diff against the
current ORM model definitions.

Which database migrations run against (development vs. test) is
controlled entirely by which DATABASE_URL is set in the environment when
Alembic is invoked — this file does not hardcode either.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure app package is importable when Alembic is invoked from backend/.
import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Alembic requires it to know which database to migrate."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL only)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection (the normal path)."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
