"""Bounded, actor-serialized occurrence reads; no financial state or formula writes.

The ordered stream includes no-deadline/error sentinels so candidate admission
cannot hide missing terms or malformed schedules. Sentinels are internal only.
At most 500 candidates are loaded; a scalar existence probe establishes whether
the last consumed key has a successor without loading another financial row.
"""

import base64
import binascii
import json
import re
from datetime import date, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, literal, or_, select, true, tuple_
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import SQLAlchemyError

from app.api.summary_schemas import OccurrenceItem, OccurrenceResponse
from app.auth.safety import auth_operation, utc_now
from app.core.errors import AuthError, FinancialError
from app.core.reliability import transaction
from app.financial_calculations import accounting
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.enums import CommitmentStatus
from app.models.repayment import Repayment
from app.models.user import User
from app.term_calculations import allocate_installments, fixed_interest
from app.terms import validate_terms

ELIGIBLE = (CommitmentStatus.ACTIVE, CommitmentStatus.PARTIALLY_REPAID)
CANDIDATE_CAP = 500
KINDS = {"UPCOMING", "OVERDUE"}
EMPTY_OCCURRENCE = UUID(int=0)


def encode_cursor(user_id, kind, row):
    data = [
        1,
        str(user_id),
        kind,
        row.due.isoformat(),
        str(row.cid),
        str(row.iid) if row.iid is not None else None,
    ]
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def decode_cursor(value, user_id, kind):
    if value is None:
        return None
    try:
        if (
            type(value) is not str
            or not 1 <= len(value) <= 512
            or not re.fullmatch(r"[A-Za-z0-9_-]+", value)
        ):
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
            raise ValueError
        parts = json.loads(raw)
        if type(parts) is not list or len(parts) != 6 or type(parts[0]) is not int or parts[0] != 1:
            raise ValueError
        if (
            any(type(parts[i]) is not str for i in (1, 2, 3, 4))
            or parts[2] != kind
            or kind not in KINDS
        ):
            raise ValueError
        owner, parent = UUID(parts[1]), UUID(parts[4])
        if str(owner) != parts[1] or owner != user_id or str(parent) != parts[4]:
            raise ValueError
        due = date.fromisoformat(parts[3])
        if due.isoformat() != parts[3]:
            raise ValueError
        child = EMPTY_OCCURRENCE
        if parts[5] is not None:
            if type(parts[5]) is not str:
                raise ValueError
            child = UUID(parts[5])
            if str(child) != parts[5]:
                raise ValueError
        return due, parent, child
    except (ValueError, TypeError, binascii.Error, UnicodeError, OverflowError):
        raise AuthError("VALIDATION_ERROR") from None


def candidate_stream(user_id, now):
    c, t, i = Commitment, CommitmentTermsVersion, CommitmentInstallment
    current = (
        select(t.id)
        .where(t.commitment_id == c.id, t.effective_at <= now)
        .order_by(t.version_no.desc())
        .limit(1)
        .correlate(c)
        .scalar_subquery()
    )
    parents = (
        select(
            c.id.label("cid"),
            t.id.label("tid"),
            t.due_date.label("single_due"),
            t.schedule_definition["schedule_mode"].astext.label("mode"),
        )
        .outerjoin(t, t.id == current)
        .where(
            or_(c.borrower_user_id == user_id, c.lender_user_id == user_id), c.status.in_(ELIGIBLE)
        )
        .cte("occurrence_parents")
    )
    children = (
        select(i.id.label("iid"), i.due_date.label("installment_due"))
        .where(i.terms_version_id == parents.c.tid, parents.c.mode == "installments")
        .order_by(i.sequence_no, i.id)
        .limit(61)
        .lateral()
    )
    return (
        select(
            parents.c.cid,
            func.coalesce(
                children.c.installment_due, parents.c.single_due, literal(date.min)
            ).label("due"),
            children.c.iid,
            func.coalesce(
                children.c.iid, literal(EMPTY_OCCURRENCE, type_=PGUUID(as_uuid=True))
            ).label("oid"),
        )
        .select_from(parents.outerjoin(children, true()))
        .subquery("occurrence_candidates")
    )


def load_inputs(db, ids, user_id, now):
    """Constant batched round trips, with at most 61 children/current version."""
    parents = {p.id: p for p in db.scalars(select(Commitment).where(Commitment.id.in_(ids)))}
    terms = {
        t.commitment_id: t
        for t in db.scalars(
            select(CommitmentTermsVersion)
            .where(
                CommitmentTermsVersion.commitment_id.in_(ids),
                CommitmentTermsVersion.effective_at <= now,
            )
            .distinct(CommitmentTermsVersion.commitment_id)
            .order_by(
                CommitmentTermsVersion.commitment_id, CommitmentTermsVersion.version_no.desc()
            )
        )
    }
    sums, invalid = {}, set()
    r, c = Repayment, Commitment
    for cid, status, amount, bad in db.execute(
        select(
            r.commitment_id,
            r.status,
            func.sum(r.amount_minor),
            func.bool_or(
                or_(
                    r.currency != c.currency,
                    (r.reported_by_user_id != c.borrower_user_id)
                    & (r.reported_by_user_id != c.lender_user_id),
                )
            ),
        )
        .join(c, c.id == r.commitment_id)
        .where(r.commitment_id.in_(ids))
        .group_by(r.commitment_id, r.status)
    ):
        sums.setdefault(cid, {})[status] = amount
        if bad:
            invalid.add(cid)
    ranked = (
        select(
            CommitmentInstallment,
            func.row_number()
            .over(
                partition_by=CommitmentInstallment.terms_version_id,
                order_by=(CommitmentInstallment.sequence_no, CommitmentInstallment.id),
            )
            .label("position"),
        )
        .where(CommitmentInstallment.terms_version_id.in_([t.id for t in terms.values()]))
        .subquery()
    )
    schedules = {}
    for row in db.execute(
        select(ranked)
        .where(ranked.c.position <= 61)
        .order_by(ranked.c.terms_version_id, ranked.c.position)
    ).mappings():
        schedules.setdefault(row["terms_version_id"], []).append(row)
    people_ids = {u for p in parents.values() for u in (p.borrower_user_id, p.lender_user_id)}
    people = {
        u.id: {"id": u.id, "display_name": u.display_name}
        for u in db.execute(select(User.id, User.display_name).where(User.id.in_(people_ids)))
    }
    result = {}
    for cid in ids:
        p, t = parents.get(cid), terms.get(cid)
        if p is None or t is None or p.status not in ELIGIBLE:
            raise ValueError("Missing authoritative state")
        if (
            p.borrower_user_id == p.lender_user_id
            or user_id not in (p.borrower_user_id, p.lender_user_id)
            or any(u not in people for u in (p.borrower_user_id, p.lender_user_id))
        ):
            raise ValueError("Invalid participants")
        logical, timezone = validate_terms(t, p)
        children = schedules.get(t.id, [])
        dates = logical.installment_dates or []
        if len(children) != len(dates):
            raise ValueError("Incomplete current schedule")
        amounts = (
            allocate_installments(
                p.principal_amount_minor,
                fixed_interest(p.principal_amount_minor, t.interest_rate_bps),
                len(dates),
            )
            if dates
            else []
        )
        for seq, (row, due, (principal, interest)) in enumerate(
            zip(children, dates, amounts, strict=True), 1
        ):
            if (
                row["commitment_id"] != cid
                or row["terms_version_id"] != t.id
                or row["sequence_no"] != seq
                or row["due_date"] != due
                or row["principal_amount_minor"] != principal
                or row["interest_amount_minor"] != interest
                or row["total_due_minor"] != principal + interest
            ):
                raise ValueError("Invalid current installment")
        capacity = accounting(p, t, sums.get(cid, {}), cid in invalid)
        counterparty = p.lender_user_id if p.borrower_user_id == user_id else p.borrower_user_id
        result[cid] = (
            p,
            logical,
            timezone,
            capacity.verified_outstanding,
            people[counterparty],
            {row["id"]: row["due_date"] for row in children},
        )
    return result


class OccurrenceService:
    def __init__(self, sessions):
        self.sessions = sessions

    @auth_operation
    def list(self, principal, kind, limit=50, cursor=None):
        if kind not in KINDS or type(limit) is not int or not 1 <= limit <= 100:
            raise AuthError("VALIDATION_ERROR")
        position = decode_cursor(cursor, principal.user_id, kind)
        try:
            with transaction(self.sessions.sessions, "summary") as db:
                self.sessions.revalidate_user_locked(db, principal)
                now = utc_now(self.sessions.clock, db)
                stream = candidate_stream(principal.user_id, now)
                key = tuple_(stream.c.due, stream.c.cid, stream.c.oid)
                query = select(stream)
                if position:
                    query = query.where(key > position)
                rows = list(
                    db.execute(
                        query.order_by(stream.c.due, stream.c.cid, stream.c.oid).limit(
                            CANDIDATE_CAP
                        )
                    )
                )
                if not rows:
                    return OccurrenceResponse(items=[], next_cursor=None)
                inputs = load_inputs(db, {r.cid for r in rows}, principal.user_id, now)
                projected = []
                for row in rows:
                    p, logical, timezone, amount, person, dates = inputs[row.cid]
                    if logical.schedule_mode == "none":
                        projected.append(None)
                        continue
                    if (
                        logical.schedule_mode == "single"
                        and (row.iid is not None or row.due != logical.due_date)
                    ) or (
                        logical.schedule_mode == "installments" and dates.get(row.iid) != row.due
                    ):
                        raise ValueError("Invalid occurrence")
                    today = now.astimezone(ZoneInfo(timezone)).date()
                    matches = (
                        (today <= row.due <= today + timedelta(days=7))
                        if kind == "UPCOMING"
                        else today >= row.due + timedelta(days=logical.grace_period_days + 1)
                    )
                    projected.append(
                        OccurrenceItem(
                            commitment_id=p.id,
                            counterparty=person,
                            role="BORROWER"
                            if p.borrower_user_id == principal.user_id
                            else "LENDER",
                            currency=p.currency,
                            verified_outstanding_minor=amount,
                            due_date=row.due,
                            due_timezone=timezone,
                            schedule_mode=logical.schedule_mode,
                            installment_id=row.iid,
                        )
                        if matches and amount > 0
                        else None
                    )
                items, consumed = [], 0
                for index, item in enumerate(projected):
                    consumed = index + 1
                    if item is not None:
                        items.append(item)
                    if len(items) == limit:
                        break
                last = rows[consumed - 1]
                more = consumed < len(rows)
                if not more:
                    more = db.scalar(
                        select(select(stream).where(key > (last.due, last.cid, last.oid)).exists())
                    )
                return OccurrenceResponse(
                    items=items,
                    next_cursor=encode_cursor(principal.user_id, kind, last) if more else None,
                )
        except (
            SQLAlchemyError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
            FinancialError,
        ):
            raise AuthError("SERVICE_UNAVAILABLE") from None
