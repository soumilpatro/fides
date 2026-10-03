"""One bounded pass of system reminders; no financial writes or explicit locks.

Each page reads all financial inputs in one PostgreSQL statement snapshot.
INSERT SELECT rechecks those inputs at its own READ COMMITTED snapshot. Changed
inputs suppress insertion until the next pass. Unique keys handle overlap/retry.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Date, String, cast, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by, insert
from sqlalchemy.orm import aliased

from app.financial_calculations import accounting
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.enums import CommitmentStatus, NotificationStatus, RepaymentStatus, UserStatus
from app.models.notification_event import NotificationEvent
from app.models.notification_preference import NotificationPreference
from app.models.repayment import Repayment
from app.models.user import User
from app.terms import validate_terms

REMINDER_TYPES = frozenset({"UPCOMING_DUE", "DUE_TODAY", "OVERDUE"})
ELIGIBLE = (CommitmentStatus.ACTIVE, CommitmentStatus.PARTIALLY_REPAID)
logger = logging.getLogger(__name__)


def dedupe_key(recipient, kind, commitment, installment, scheduled_date):
    if kind not in REMINDER_TYPES or type(scheduled_date) is not date:
        raise ValueError("Invalid reminder identity")
    return "|".join(
        (
            "r1",
            str(UUID(str(recipient))),
            kind,
            str(UUID(str(commitment))),
            str(UUID(str(installment))) if installment else "-",
            scheduled_date.isoformat(),
        )
    )


def occurrences(due, grace, today):
    """Calendar occurrences only; no fixed delivery time or historical flood."""
    if today == due - timedelta(days=3):
        return [("UPCOMING_DUE", today)]
    if today == due:
        return [("DUE_TODAY", today)]
    first = due + timedelta(days=grace + 1)
    if today >= first:
        return [("OVERDUE", first + timedelta(days=7 * ((today - first).days // 7)))]
    return []


def snapshot_query(ids, now):
    """Bounded result size, no per-parent or per-user query round trips."""
    c, t, r, i = Commitment, CommitmentTermsVersion, Repayment, CommitmentInstallment
    borrower, lender = aliased(User), aliased(User)
    bp, lp = aliased(NotificationPreference), aliased(NotificationPreference)
    grouped = (
        select(
            r.commitment_id.label("cid"),
            r.status.label("status"),
            func.sum(r.amount_minor).label("amount"),
            func.bool_or(
                or_(
                    r.currency != c.currency,
                    (r.reported_by_user_id != c.borrower_user_id)
                    & (r.reported_by_user_id != c.lender_user_id),
                )
            ).label("invalid"),
        )
        .join(c, c.id == r.commitment_id)
        .where(r.commitment_id.in_(ids))
        .group_by(r.commitment_id, r.status)
        .subquery()
    )
    totals = (
        select(
            grouped.c.cid,
            func.jsonb_object_agg(cast(grouped.c.status, String), grouped.c.amount).label("sums"),
            func.bool_or(grouped.c.invalid).label("invalid"),
        )
        .group_by(grouped.c.cid)
        .subquery()
    )
    bounded_installments = (
        select(
            i.id,
            i.commitment_id,
            i.terms_version_id,
            i.due_date,
            i.sequence_no,
            func.row_number()
            .over(
                partition_by=i.terms_version_id,
                order_by=i.sequence_no,
            )
            .label("position"),
        )
        .where(i.commitment_id.in_(ids))
        .subquery()
    )
    si = bounded_installments.c
    installments = (
        select(
            si.terms_version_id.label("tid"),
            func.jsonb_agg(
                aggregate_order_by(
                    func.jsonb_build_object(
                        "id",
                        si.id,
                        "commitment_id",
                        si.commitment_id,
                        "date",
                        si.due_date,
                        "sequence",
                        si.sequence_no,
                    ),
                    si.sequence_no,
                )
            ).label("schedule"),
        )
        # 61 rows are sufficient to detect a corrupt schedule exceeding the
        # approved maximum of 60 without materializing unbounded JSON in Python.
        .where(si.position <= 61)
        .group_by(si.terms_version_id)
        .subquery()
    )
    current = (
        select(CommitmentTermsVersion.id)
        .where(
            CommitmentTermsVersion.commitment_id == c.id,
            CommitmentTermsVersion.effective_at <= now,
        )
        .order_by(CommitmentTermsVersion.version_no.desc())
        .limit(1)
        .correlate(c)
        .scalar_subquery()
    )
    return (
        select(
            c,
            t,
            cast(func.row_to_json(c.__table__.table_valued()), JSONB).label("parent_state"),
            cast(func.row_to_json(t.__table__.table_valued()), JSONB).label("terms_state"),
            func.coalesce(totals.c.sums, cast(literal("{}"), JSONB)).label("sums"),
            func.coalesce(totals.c.invalid, false()).label("invalid"),
            func.coalesce(installments.c.schedule, cast(literal("[]"), JSONB)).label("schedule"),
            (borrower.status == UserStatus.ACTIVE).label("borrower_active"),
            (lender.status == UserStatus.ACTIVE).label("lender_active"),
            func.coalesce(bp.due_reminders_enabled, True).label("borrower_due"),
            func.coalesce(bp.overdue_reminders_enabled, True).label("borrower_overdue"),
            func.coalesce(lp.overdue_reminders_enabled, True).label("lender_overdue"),
        )
        .outerjoin(t, t.id == current)
        .outerjoin(totals, totals.c.cid == c.id)
        .outerjoin(installments, installments.c.tid == t.id)
        .join(borrower, borrower.id == c.borrower_user_id)
        .join(lender, lender.id == c.lender_user_id)
        .outerjoin(bp, bp.user_id == borrower.id)
        .outerjoin(lp, lp.user_id == lender.id)
        .where(c.id.in_(ids), c.status.in_(ELIGIBLE))
    )


def candidates(row, now):
    c, t = row.Commitment, row.CommitmentTermsVersion
    if t is None:
        raise ValueError("Missing current reminder terms")
    logical, timezone = validate_terms(t, c)
    if c.borrower_user_id == c.lender_user_id:
        raise ValueError("Invalid reminder participants")
    sums = {RepaymentStatus(k): v for k, v in row.sums.items()}
    if accounting(c, t, sums, row.invalid).verified_outstanding <= 0:
        return []
    if logical.schedule_mode == "none":
        return []
    today = now.astimezone(ZoneInfo(timezone)).date()
    if logical.schedule_mode == "installments":
        dates = logical.installment_dates
        if len(row.schedule) != len(dates) or any(
            item["date"] != due.isoformat()
            or item["sequence"] != seq
            or item["commitment_id"] != str(c.id)
            for seq, (item, due) in enumerate(zip(row.schedule, dates, strict=True), 1)
        ):
            raise ValueError("Invalid reminder schedule")
        schedule = [(UUID(item["id"]), date.fromisoformat(item["date"])) for item in row.schedule]
    else:
        if row.schedule:
            raise ValueError("Unexpected reminder installments")
        schedule = [(None, logical.due_date)]
    result = []
    for installment, due in schedule:
        for kind, stamp in occurrences(due, logical.grace_period_days, today):
            roles = ("borrower", "lender") if kind == "OVERDUE" else ("borrower",)
            for role in roles:
                enabled = getattr(row, f"{role}_overdue" if kind == "OVERDUE" else "borrower_due")
                if enabled and getattr(row, f"{role}_active"):
                    result.append((getattr(c, f"{role}_user_id"), kind, installment, stamp, role))
    return result


def insert_candidate(db, query, row, candidate, now, *, live_clock=False):
    """Only this named uniqueness conflict is a no-op. Other errors propagate."""
    recipient, kind, installment, stamp, role = candidate
    state = query.subquery()
    unchanged = [state.c.id == row.Commitment.id]
    # Recheck all validated financial inputs, including current terms and schedule.
    for name in ("parent_state", "terms_state", "sums", "invalid", "schedule"):
        unchanged.append(state.c[name] == getattr(row, name))
    unchanged.extend(
        [
            state.c[f"{role}_active"],
            state.c[f"{role}_overdue" if kind == "OVERDUE" else "borrower_due"],
        ]
    )
    if live_clock:
        timezone = row.CommitmentTermsVersion.schedule_definition["due_timezone"]
        unchanged.append(
            cast(func.timezone(timezone, func.statement_timestamp()), Date)
            == now.astimezone(ZoneInfo(timezone)).date()
        )
    values = dict(
        id=uuid4(),
        user_id=recipient,
        type=kind,
        status=NotificationStatus.DELIVERED,
        object_type="Commitment",
        object_id=row.Commitment.id,
        payload={
            "terms_version_id": str(row.CommitmentTermsVersion.id),
            "installment_id": str(installment) if installment else None,
            "scheduled_local_date": stamp.isoformat(),
        },
        dedupe_key=dedupe_key(recipient, kind, row.Commitment.id, installment, stamp),
        created_at=now,
    )
    table = NotificationEvent.__table__
    statement = (
        insert(table)
        .from_select(
            list(values),
            select(*(literal(value, type_=table.c[name].type) for name, value in values.items()))
            .select_from(state)
            .where(*unchanged),
        )
        .on_conflict_do_nothing(constraint="uq_notification_events_dedupe_key")
        .returning(table.c.id)
    )
    return db.execute(statement).scalar_one_or_none() is not None


class ReminderService:
    def __init__(self, sessions):
        self.sessions = sessions

    def run(self, *, now=None, page_size=100):
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Invalid reminder pass bounds")
        fixed_clock = now is not None
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Reminder clock must be timezone aware")
        created, failures, after = 0, 0, None
        # Capture a finite scan frontier. New inserts cannot extend this pass
        # indefinitely; paging bounds memory without starving higher UUIDs.
        with self.sessions.begin() as db:
            ceiling = db.scalar(
                select(Commitment.id)
                .where(Commitment.status.in_(ELIGIBLE))
                .order_by(Commitment.id.desc())
                .limit(1)
            )
        while ceiling is not None:
            if not fixed_clock:
                now = datetime.now(UTC)
            with self.sessions.begin() as db:
                query = select(Commitment.id).where(
                    Commitment.status.in_(ELIGIBLE),
                    Commitment.id <= ceiling,
                )
                if after is not None:
                    query = query.where(Commitment.id > after)
                ids = list(db.scalars(query.order_by(Commitment.id).limit(page_size)))
            if not ids:
                break
            with self.sessions.begin() as db:
                query = snapshot_query(ids, now)
                rows = list(db.execute(query))
                final_query = snapshot_query(
                    ids, now if fixed_clock else func.statement_timestamp()
                )
                page_created = 0
                for row in rows:
                    try:
                        planned = candidates(row, now)
                    except (ValueError, TypeError, KeyError, OverflowError):
                        failures += 1
                        logger.warning(
                            "reminder_candidate_invalid",
                            extra={"fields": {"reason": "stored_state"}},
                        )
                        continue
                    for candidate in planned:
                        page_created += insert_candidate(
                            db, final_query, row, candidate, now, live_clock=not fixed_clock
                        )
            created += page_created
            after = ids[-1]
            if len(ids) < page_size:
                break
        if failures:
            logger.warning(
                "reminder_pass_partial", extra={"fields": {"failed_candidates": failures}}
            )
        return {"created": created, "failed_candidates": failures}
