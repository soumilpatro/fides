# FIDES Database Roles — Least-Privilege Requirements

**Status:** Documentation / runbook only. This document describes the
roles and grants FIDES production/staging PostgreSQL databases must
have. It contains **no SQL to run** and is **not** executed by any
Alembic migration. Role provisioning is a separate, deliberately
un-automated concern from ordinary application schema migrations
(approved B1 decision).

## Why this is separate from Alembic migrations

Alembic migrations in `backend/migrations/versions/` are owned by the
application and run automatically as part of deploys. Database roles and
their grants are an infrastructure/security concern that should be
provisioned and reviewed by whoever manages the database environment
(which may be a different process, person, or tool than "run migrations
on deploy"), and should not be silently alterable by an application-level
migration. This separation is deliberate, not an oversight — see AI
Development & Backend Build Specification B14 (Security hardening) for
where role provisioning tooling itself, if any, should be built.

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
  `extension_requests`, `idempotency_keys`, `notification_events`).
- Must have `SELECT`, `INSERT` **only** — explicitly **no `UPDATE` or
  `DELETE`** — on the two append-only tables:
  - `ledger_events`
  - `audit_logs`

  This directly implements Database & Data Model Specification v1.0
  Sec. 5 ("Ledger and audit rows are append-only; normal application
  role must not UPDATE/DELETE them") and Sec. 14 ("Financial history
  and ledger events are not hard-deleted").
- Must **not** have superuser, `CREATEDB`, `CREATEROLE`, or
  `BYPASSRLS` privileges.
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

## Local development note

The Docker Compose setup in `docker-compose.yml` (B1) uses a single,
broadly-privileged `fides` role for local development convenience only,
across both `fides_dev` and `fides_test`. This is acceptable for a
local, disposable development database and is explicitly **not** the
production role model described above.
