"""SQLAlchemy ORM models (B1 scope).

Structural mapping only — one module per table from the Database & Data
Model Specification v1.0, Sec. 4. No query methods, repositories, or
business logic live on these classes. Importing this package registers
all models on `Base.metadata`, which Alembic's `env.py` uses for
autogenerate support.
"""

from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.auth_identity import AuthIdentity
from app.models.auth_otp_challenge import AuthOtpChallenge
from app.models.auth_rate_limit_bucket import AuthRateLimitBucket
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.connection import Connection
from app.models.extension_request import ExtensionRequest
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.notification_event import NotificationEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "AuthIdentity",
    "AuthOtpChallenge",
    "AuthRateLimitBucket",
    "AuthSession",
    "Connection",
    "Commitment",
    "CommitmentTermsVersion",
    "CommitmentInstallment",
    "Repayment",
    "RepaymentVerification",
    "ExtensionRequest",
    "LedgerEvent",
    "AuditLog",
    "IdempotencyKey",
    "NotificationEvent",
]
