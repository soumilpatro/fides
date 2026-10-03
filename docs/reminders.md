# In-app reminders and notification preferences

Migration `013` (parent `012`) adds `notification_preferences`, nullable
`notification_events.dedupe_key VARCHAR(160)`, named dedupe uniqueness, a reminder
key CHECK, and the `(created_at, id)` retention index. Existing workflow rows keep
null keys; no backfill or notification-type enum conversion occurs. The existing
commitment PK supports the keyset scan; no speculative commitment index was added.

Upgrade refuses pre-existing reminder type rows for explicit review. Downgrade
refuses stored preferences or keyed/reminder notifications. Operators must archive
and explicitly remove that new data before downgrade; the migration never silently
destroys it. The supported normal deployment operation is `alembic upgrade head`.

`GET /api/v1/notification-preferences` returns the authenticated user's settings or
true/true defaults without inserting. `POST` fully replaces both required strict
boolean fields using PostgreSQL upsert/RETURNING. Query parameters and extra fields
are rejected. Existing session eligibility, B14 body limits, no-store, security
headers, and safe error handling apply. Preferences never affect mandatory workflow
notifications or financial records.

From `backend/`, with the existing environment configured and migrated:

```text
python -m app.jobs.reminders
python -m app.jobs.notification_cleanup
```

Each command runs once and exits. B15 must arrange approximately hourly reminder
invocation and separate daily cleanup, process exit monitoring, and least privilege.
There is no web-worker background loop, broker, new provider, or dependency.
Exit 0 means completion/no-op; startup, database, or corrupt-candidate partial
failure yields a non-zero reminder exit. Logs contain bounded categories/counts,
never exception details, recipient identifiers, SQL binds, or private payloads.

The reminder pass captures a finite UUID scan frontier and reads at most 100
commitments per page. Financial inputs, current effective terms, installments,
users, and preferences are loaded together in one statement snapshot. It uses
`validate_terms` and the existing exact `accounting` helper. Each INSERT SELECT
rechecks the validated state, current effective terms at execution time, recipient
preferences/activity, and the applicable borrower-local day. Changed state skips
insertion until a later invocation. No explicit financial or advisory locks are
taken; PostgreSQL's normal foreign-key and unique-key enforcement still applies.

Only ACTIVE/PARTIALLY_REPAID commitments with positive verified outstanding qualify.
Pending/disputed repayments do not reduce that outstanding. No-deadline, fully
repaid, closed, and other ineligible commitments are suppressed. Contractual
`due_timezone` uses ZoneInfo; profile timezone changes do not change the contract.

Upcoming is borrower-only on due date minus three calendar days. Due-today is
borrower-only on the due date. Neither backfills after its applicable day. Overdue
uses `E = due_date + grace_period_days + 1 calendar day`. For borrower-local date
`T >= E`, the one applicable occurrence is
`S = E + 7 * floor((T - E).days / 7)`. Borrower and lender preferences gate their
own delivery independently. Downtime recovery emits only S, never historical floods.
Current-version installments provide schedule dates only; there is no installment
outstanding calculation, payment allocation, or status mutation.

Logical identity is exactly:

```text
r1|recipient_uuid|type|commitment_uuid|installment_uuid_or_-|YYYY-MM-DD
```

Canonical UUIDs and date text fit within 160 characters. TermsVersion is provenance,
not dedupe identity. Only conflict on `uq_notification_events_dedupe_key` is a no-op;
other database errors propagate. Reminder transactions are independent and never
write financial, ledger, or audit state. Existing mandatory workflow atomicity is
preserved.

UPCOMING_DUE/DUE_TODAY/OVERDUE project `actor: null`, the commitment ID, and null
repayment/extension IDs. Human workflow notifications retain non-null actors.
Payload contains only terms_version_id, installment_id or null, and scheduled_local_date.
Historical projection validates ownership/static provenance without reevaluating
current outstanding, terms eligibility, or commitment lifecycle. Later payments
and extensions therefore do not make delivered reminders unreadable. Cursor order,
pagination, mark-read, and read timestamps preserve existing inbox behavior.

Cleanup deletes only NotificationEvent rows with `created_at < now - 90 days`,
including read/unread rows; exact boundary rows remain. Transactions select up to
1,000 IDs ordered by created_at/id using SKIP LOCKED and delete only those IDs,
with at most 100 batches per invocation. Preferences and all financial/history
tables remain untouched. Cursor anchors do not require a surviving row; reading
an expired notification returns the existing generic unavailable response.

Production cleanup should use a separately privileged maintenance DATABASE_URL
in its own process. No production credentials or role redesign is supplied here;
B15 must verify that the runtime role does not acquire broad delete privileges.

Frontend coordination is a separate release prerequisite before enabling reminders:
accept the three new types, allow null actor only for them, use system reminder
copy without actor.display_name, and navigate to the commitment. Backend work does
not modify frontend or generate client-side eligibility.
