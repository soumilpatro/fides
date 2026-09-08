"""SQLAlchemy declarative base and naming convention (B1 scope).

The naming convention ensures Alembic autogenerate produces stable,
predictable constraint/index names that match across environments,
rather than Postgres' default auto-generated names (which vary and are
not diff-stable). This directly supports the many named constraints and
indexes required by the Database & Data Model Specification v1.0
(Sec. 5-6).

This module defines structure only. It is imported by every model module
in `app.models`, but contains no query logic itself.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Naming convention recommended by SQLAlchemy's own documentation for
# Alembic compatibility.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all FIDES ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
