"""Pure validation of durable closure facts shared by reads and timeline projection.

Historical facts never depend on current repayment totals or account eligibility.
"""

from app.models.enums import CommitmentStatus, MutualClosureStatus


def validate_closure(row, parent):
    parties = {parent.borrower_user_id, parent.lender_user_id}
    if (
        len(parties) != 2
        or row.commitment_id != parent.id
        or {row.requested_by_user_id, row.counterparty_user_id} != parties
        or row.requested_by_user_id == row.counterparty_user_id
        or row.currency != parent.currency
        or row.currency not in ("INR", "USD", "GBP")
        or type(row.outstanding_snapshot_minor) is not int
        or row.outstanding_snapshot_minor <= 0
        or type(row.waived_amount_minor) is not int
        or row.waived_amount_minor != row.outstanding_snapshot_minor
        or (row.note is not None and (type(row.note) is not str or len(row.note) > 500))
        or row.updated_at < row.created_at
    ):
        raise ValueError("Invalid stored closure facts")
    if row.status == MutualClosureStatus.REQUESTED:
        if row.decided_by_user_id is not None or row.decided_at is not None:
            raise ValueError("Unexpected closure decision")
    elif row.status in (
        MutualClosureStatus.ACCEPTED,
        MutualClosureStatus.REJECTED,
        MutualClosureStatus.CANCELLED,
    ):
        expected = (
            row.requested_by_user_id
            if row.status == MutualClosureStatus.CANCELLED
            else row.counterparty_user_id
        )
        if (
            row.decided_by_user_id != expected
            or row.decided_at is None
            or row.decided_at < row.created_at
            or row.updated_at != row.decided_at
        ):
            raise ValueError("Invalid closure decision")
        if row.status == MutualClosureStatus.ACCEPTED and (
            parent.status != CommitmentStatus.CLOSED or parent.closed_at != row.decided_at
        ):
            raise ValueError("Closure decision contradicts parent")
    else:
        raise ValueError("Unknown closure state")
