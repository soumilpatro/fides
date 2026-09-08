"""`repayments` table model (Database Spec Sec. 4 - repayments).

NOTE on `idempotency_key_id`: the Database Spec defines this as a FK to
`idempotency_keys.id`. This ORM model declares that `ForeignKey(...)` so
it accurately reflects the FINAL schema (after all B1 migrations have
run), which is what the running application always sees. The DDL for
this FK constraint is NOT created in the same migration as this table's
`CREATE TABLE`, though: the approved B1 migration sequence creates
`repayments` in migration 006, before `idempotency_keys` exists
(migration 008), so migration 006 creates the column as plain UUID with
no FK, and migration 008 adds the FOREIGN KEY constraint via
`ALTER TABLE` once `idempotency_keys` exists. This split is a
migration-sequencing detail only — declaring `ForeignKey` here does not
change or reorder that DDL, since these hand-written migrations never
rely on `Base.metadata.create_all()` or Alembic autogenerate to produce
their DDL. See migrations 006 and 008 for the exact DDL history.

Deferred to the application/service layer (B7+), per approved B1
decision: `currency` must equal the parent commitment's currency. Not
expressible as a plain cross-table CHECK/FK constraint without a
trigger.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CHAR, CheckConstraint, Date, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import BIGINT, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import RepaymentStatus, repayment_status_enum


class Repayment(Base):
    __tablename__ = "repayments"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_repayments_amount_positive"),
        Index("ix_repayments_commitment_reported_at", "commitment_id", "reported_at"),
        Index("ix_repayments_commitment_status", "commitment_id", "status"),
        Index("ix_repayments_reporter_reported_at", "reported_by_user_id", "reported_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitments.id"), nullable=False
    )
    reported_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    reported_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[RepaymentStatus] = mapped_column(repayment_status_enum, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The FOREIGN KEY constraint itself is added to the database in
    # migration 008 (not 006) — see module docstring. Declaring it here
    # keeps the ORM model consistent with the final, fully-migrated schema.
    idempotency_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idempotency_keys.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
