"""Enum types for the FIDES database schema (B1 scope).

Defines the 10 enum types from the Database & Data Model Specification
v1.0, Sec. 4, as Python `enum.Enum` classes plus matching PostgreSQL
native ENUM type handles for use on model columns.

The native Postgres ENUM types themselves are created explicitly in
Alembic migration 001 (001_extensions_enums). Model columns reference
them with `create_type=False` so SQLAlchemy does not attempt to
(re)create the type when Alembic already owns that responsibility.
"""

import enum

from sqlalchemy.dialects.postgresql import ENUM as PGEnum


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"
    ANONYMIZED = "ANONYMIZED"


class ConnectionStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    REMOVED = "REMOVED"


class CommitmentType(str, enum.Enum):
    IOU = "IOU"
    PEER_LOAN = "PEER_LOAN"


class CommitmentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    PARTIALLY_REPAID = "PARTIALLY_REPAID"
    FULLY_REPAID = "FULLY_REPAID"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"
    DEFAULTED = "DEFAULTED"


class InterestType(str, enum.Enum):
    NONE = "NONE"
    SIMPLE_FIXED = "SIMPLE_FIXED"


class RepaymentStatus(str, enum.Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class VerificationDecision(str, enum.Enum):
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class ExtensionStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class InstallmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class NotificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    READ = "READ"


def _pg_enum(python_enum: type[enum.Enum], name: str) -> PGEnum:
    """Build a PostgreSQL native ENUM column type bound to a Python enum.

    `create_type=False` because the actual `CREATE TYPE ... AS ENUM` DDL
    is owned by Alembic migration 001, not by SQLAlchemy's own
    create-on-first-use behavior.
    """
    return PGEnum(python_enum, name=name, create_type=False)


user_status_enum = _pg_enum(UserStatus, "user_status")
connection_status_enum = _pg_enum(ConnectionStatus, "connection_status")
commitment_type_enum = _pg_enum(CommitmentType, "commitment_type")
commitment_status_enum = _pg_enum(CommitmentStatus, "commitment_status")
interest_type_enum = _pg_enum(InterestType, "interest_type")
repayment_status_enum = _pg_enum(RepaymentStatus, "repayment_status")
verification_decision_enum = _pg_enum(VerificationDecision, "verification_decision")
extension_status_enum = _pg_enum(ExtensionStatus, "extension_status")
installment_status_enum = _pg_enum(InstallmentStatus, "installment_status")
notification_status_enum = _pg_enum(NotificationStatus, "notification_status")
