# FIDES Database Roles — Least-Privilege Requirements

**Status:** Documentation / runbook only. This document describes the
roles and grants FIDES production/staging PostgreSQL databases must
have. It contains **no SQL to run** and is **not** executed by any
Alembic migration. Role provisioning is a separate, deliberately
un-automated concern from ordinary application schema migrations
(approved B1 decision).

## Why this is separate from Alembic migrations

Alembic migrations in `backend/migrations/versions/` are owned by the
application. No automatic deployment hook currently exists, and application
startup does not run migrations. B15-D0 requires a separate, explicitly invoked
migration step using a migration credential; a future hook must be implemented
and verified before claiming automatic deployment execution. Database roles and
their grants are an infrastructure/security concern that should be
provisioned and reviewed by whoever manages the database environment
(which may be a different process, person, or tool than "run migrations
on deploy"), and should not be silently alterable by an application-level
migration. This separation is deliberate, not an oversight — see AI
Development & Backend Build Specification B14 (Security hardening) for
where role provisioning tooling itself, if any, should be built. B15 now owns
deployment provisioning and verification; see [the B15 runbook](b15-deployment.md).

## Required roles

### 1. Migration role
- Used only to run Alembic migrations (DDL: `CREATE TABLE`, `CREATE
  TYPE`, `CREATE INDEX`, `ALTER TABLE`, etc.).
- Should be a distinct credential from the application's runtime
  database role.
- Not used by the running FastAPI application at request time.

### 2. Application runtime role
- Used by the FastAPI backend for all normal request-time database
  access (via `DATABASE_URL` in `.env`).
- Must **not** have DDL privileges (no `CREATE`, `ALTER`, `DROP` on any
  object).
- Must have `SELECT`, `INSERT`, `UPDATE` on ordinary domain tables
  (`users`, `connections`, `commitments`, `commitment_terms_versions`,
  `commitment_installments`, `repayments`, `repayment_verifications`,
  `extension_requests`, `idempotency_keys`, `notification_events`,
  `notification_preferences`).
- Must have `SELECT`, `INSERT` **only** — explicitly **no `UPDATE` or
  `DELETE` or `TRUNCATE`** — on the two append-only tables:
  - `ledger_events`
  - `audit_logs`

  This directly implements Database & Data Model Specification v1.0
  Sec. 5 ("Ledger and audit rows are append-only; normal application
  role must not UPDATE/DELETE them") and Sec. 14 ("Financial history
  and ledger events are not hard-deleted").
- Must **not** have superuser, `CREATEDB`, `CREATEROLE`, or
  `BYPASSRLS` privileges.
- Must not own application objects or inherit an owner/migration role that
  bypasses these restrictions. Verify effective grants, schema CREATE denial,
  required schema/type usage, and actual application access under this credential.
- Must **not** be usable to connect to any database other than the one
  it is scoped to (the application runtime role for `fides_dev` should
  not also have access to `fides_test`, and vice versa, keeping the two
  databases genuinely isolated per the approved B1 test-database
  decision).

### 3. No client-side database credentials
- Per Tech Spec Sec. 22 and Database Spec Sec. 14: "No client receives
  database credentials." Mobile and web clients only ever talk to the
  FastAPI backend over HTTPS/REST; they never receive a database
  connection string, role, or credential of any kind.

## What this document deliberately does NOT include

- Actual `CREATE ROLE` / `GRANT` / `REVOKE` SQL statements.
- Any provisioning script, Terraform/IaC config, or Alembic migration
  that creates or alters roles.
- Secrets, passwords, or connection strings of any kind.

These are intentionally left for a dedicated security/infrastructure
task (see AI Development & Backend Build Specification B14: Security
hardening, and B15: Integration & release), where the actual mechanism
(manual DBA setup, an infra-as-code tool, or a separate provisioning
script outside the application's own migration chain) can be decided
deliberately rather than folded into ordinary schema migrations.

## B2 authentication runtime and maintenance permissions

Runtime auth requires SELECT/INSERT/UPDATE on `auth_sessions`,
`auth_otp_challenges`, and `auth_rate_limit_buckets`, plus SELECT/INSERT on
`auth_identities`. It does not need DELETE on these tables. Existing User and
append-only AuditLog permissions remain unchanged.

`app.auth.maintenance.cleanup_auth` is an explicitly invoked internal function.
Supply a session factory using separately authorized maintenance credentials;
it is not called by HTTP routes or application startup and has no scheduler.
The maintenance role needs SELECT/DELETE only on the three auth operational
tables above. Do not grant it DELETE on Users, AuthIdentity, AuditLog or any
financial/history table. Provisioning these grants remains separate from
migrations; this document does not execute them.

The function uses configured retention defaults: OTP challenges at expiry +
24 hours, buckets at window expiry + 24 hours, and sessions at refresh expiry +
30 days. Equality with the cutoff is eligible. Cleanup returns per-table counts
after commit; an error rolls back the batch. No account or financial state is
changed, and deleted credentials/challenges subsequently resolve as unknown.

Deactivation and all runtime session writers coordinate through the User row
lock. Future financial writers introducing blocking commitments must lock the
affected Users in stable UUID order and recheck ACTIVE eligibility before their
write, as required by B2-D2. Direct writes bypassing that protocol are not safe.

## Mutual closure runtime permissions

Migration 014 adds `mutual_closure_requests` and its dedicated status enum.
The application runtime role requires SELECT, INSERT and UPDATE on the new
table, with no DELETE or DDL privileges. Closure rows and their original waiver
snapshots remain durable. Existing SELECT/INSERT-only ledger and audit grants,
notification permissions, idempotency permissions, and commitment update
permissions remain unchanged. Grant provisioning stays separate from Alembic;
this document performs no role or credential operations.

## B15 scheduled-service roles

Staging and production use distinct migration, API, reminder, and notification
cleanup credentials. Each process receives only its own `DATABASE_URL`; role
provisioning remains separate from migrations. Migration head `014` follows `013`,
and migration `001` requires `pgcrypto` availability/creation permissions.

The reminder role reads commitments, current terms/installments, repayments,
users, preferences, and notification state and inserts notification events.
It has no financial UPDATE/DELETE, ledger/audit writes, DDL, or ownership rights.

The notification cleanup role is limited to reading/deleting notification events
and the minimum row-locking privilege needed by SELECT FOR UPDATE SKIP LOCKED
(verify a column-level UPDATE grant rather than granting broad UPDATE). It must
not delete preferences, users, auth identities, financial records, ledger, or audit.
This is distinct from the separately documented auth-maintenance role/function;
there is no executable auth-cleanup job command in this repository.

Every non-migration service role must lack superuser, CREATEDB, CREATEROLE,
BYPASSRLS, DDL, and inherited object ownership. Prove ledger/audit UPDATE, DELETE,
and TRUNCATE denial under actual deployed service credentials. No grants are
executed by this document.

## Local development privileges

The Docker Compose setup in `docker-compose.yml` (B1) uses a single,
broadly-privileged `fides` role for local development convenience only,
across both `fides_dev` and `fides_test`. This is acceptable for a
local, disposable development database and is explicitly **not** the
production role model described above.
