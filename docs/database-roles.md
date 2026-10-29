# FIDES Database Roles — Least-Privilege Requirements

**Status:** Documentation / runbook only. This document describes the
roles and grants FIDES production/staging PostgreSQL databases must
have. The B15-R1 preparation scripts are in `infra/postgres/` and have **not been
executed** by this checkpoint. Provisioning remains an explicit administrator
operation, separate from Alembic migrations (approved B1 decision); no deployment
hook automatically executes these scripts.

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
  (`users`, `connections`, `commitments`, `repayments`,
  `extension_requests`, `idempotency_keys`, `notification_events`,
  `notification_preferences`).
- Must have SELECT/INSERT only on `commitment_terms_versions`,
  `commitment_installments`, and `repayment_verifications`; the B15-R1 scripts
  deliberately omit UPDATE on these three tables. Authorization locks their
  mutable parent/repayment, not those immutable child/history rows.
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
- Must use a dedicated application database with each service `DATABASE_URL`
  pinned to its intended database. No explicit cross-database grants, ownership,
  or role membership may give a runtime role authority over another database.
  PostgreSQL cannot deny CONNECT per-role while PUBLIC grants it; technical
  connectivity alone is not proof of application-data access. Keep development,
  test, staging and production data separate, with no Fides schema/data in other
  databases on the staging/production cluster. Provider network/auth controls
  and actual database inventory must be verified before production acceptance.

### 3. No client-side database credentials
- Per Tech Spec Sec. 22 and Database Spec Sec. 14: "No client receives
  database credentials." Mobile and web clients only ever talk to the
  FastAPI backend over HTTPS/REST; they never receive a database
  connection string, role, or credential of any kind.

## Provisioning boundary

This document contains no real secrets, passwords, or connection strings.
`infra/postgres/provision-staging-roles.sql` and `verify-staging-roles.sql` implement
the reviewed staging ACL preparation outside the Alembic chain. They do not create
cloud resources, change application behavior, or run during application startup.

Actual execution, credentials, provider administrator capabilities, and deployed
privilege evidence remain a separately authorized B15 infrastructure step.

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

## B15-R1 script operation and caveats

Required client/server: psql 16+ and PostgreSQL 16+. Use a fresh psql session with
`-X` and an authorized provisioning administrator, not a service login. The
administrator must be allowed to create roles, manage target DB/schema/object
ACLs, and set the logging controls below. No Railway connection or SQL execution
occurred during this preparation.

Required non-secret psql variables are `FidesDatabase`, `FidesSchema`, and
`FidesPhase` (`bootstrap` or `grants`). Connect to exactly FidesDatabase; the scripts
never connect to a database on the operator's behalf. FidesSchema can be parameterized:
per-database role search_path is set deliberately so existing unqualified Alembic
and ORM statements resolve to that schema. Dedicated staging only: PUBLIC ACL
changes must not be applied to a shared application/database schema.

Execution order, after separate authorization:

1. `provision-staging-roles.sql` with FidesPhase=bootstrap on an empty app schema.
2. Existing Alembic upgrade through 014, connecting as `fides_migrator`.
3. The same provisioning script with FidesPhase=grants; it includes verification
   before COMMIT and rolls back privilege changes on any assertion failure.
4. Standalone `verify-staging-roles.sql` with FidesDatabase/FidesSchema in a read-only
   transaction, then separately approved real-credential connection/smoke checks.
5. Enable API/jobs only after verification. Bootstrap is not runtime readiness.

Bootstrap requires all four nonblank psql password variables:
`FidesMigratorPassword`, `FidesApiPassword`, `FidesRemindersPassword`, and
`FidesNotificationCleanupPassword`. Supply through protected input or private psql
prompts, never shell `-v Password=...` arguments/history. No passwords are supplied
or generated here. Passwords are used only for newly created roles; existing role
passwords are never changed. Unknown attributes/ownership/membership fail for
explicit review. Only per-database search_path is deliberately ALTERed; cross-role
memberships among the four approved names are explicitly revoked, without blindly
dropping roles or reassigning owned data. New credentials use SCRAM-SHA-256.

Before password interpolation the script disables psql echo/hidden query echo,
uses terse errors and transaction-local standard SQL/error/duration sampling logs.
It aborts if the administrator cannot set these controls. Provider audit extensions,
proxy/query capture, client tracing/history and other external logging must also be
reviewed: session settings cannot guarantee their secrecy. Do not run it until
those channels are confirmed safe. The grant phase needs no password variables.

Migration `001` requires pgcrypto. PostgreSQL documents it as trusted, installable
by a non-superuser with database CREATE; the migrator receives CONNECT/CREATE on
the target DB and USAGE/CREATE on the schema, not CREATEDB or superuser. Verify the
provider exposes trusted pgcrypto before execution; availability is checked by
catalog, not by silently attempting an extension workaround. Migration-owned tables
and enums must belong to the migrator. Extension objects may be bootstrap-superuser
owned: the provisioner needs authority to revoke their EXECUTE ACLs if installed
in the app schema. Runtime access to application-schema pgcrypto routines is limited
to the API's UUID default; the migrator can also execute that UUID function for
schema maintenance. pg_catalog builtins remain unchanged.

API operation matrix: SELECT/INSERT/UPDATE on users, connections, commitments,
repayments, extension_requests, idempotency_keys, notification_events,
notification_preferences, mutual_closure_requests and the three auth operational
tables. SELECT/INSERT only on auth_identities, terms versions, installments,
verification history, ledger_events and audit_logs. No API DELETE/TRUNCATE,
REFERENCES/TRIGGER, or access to alembic_version. No service owns objects or has
membership/SET ROLE authority. No future blanket grants or grant options.

The reminder role has table SELECT only on commitments and terms versions (both
are projected as full row JSON). Other SELECT grants are column-scoped: users
(id, status); installments (id, commitment_id, terms_version_id, due_date,
sequence_no); repayments (commitment_id, status, amount_minor, currency,
reported_by_user_id); preferences (user_id, due_reminders_enabled,
overdue_reminders_enabled); notifications (id for RETURNING, dedupe_key for ON CONFLICT). It has INSERT only
on notifications, and cannot read users' phones/profile fields or auth data. Cleanup
has SELECT(id, created_at), DELETE, and UPDATE(id) only on notification_events.
PostgreSQL's FOR UPDATE rule requires UPDATE on at least one column; this is why
cleanup receives UPDATE(id). This also permits actual id updates: it is not a
special lock-only privilege. It does not grant table-wide UPDATE or financial
mutation. Restrict the credential to the existing one-shot cleanup job.

All current keys use UUID, user_id, or composite keys: migrations 001-014 create
no sequences, so no sequence privileges are needed/granted. API receives USAGE on
the eleven enums; reminders on the seven types used by its input/output tables;
cleanup needs none for its id/created_at query. Table SELECT/INSERT only does not
require REFERENCES for existing FK checks. UUID generation uses existing functions.

No ALTER DEFAULT PRIVILEGES is installed. Existing custom migrator default ACLs
are refused. Every schema change must explicitly refresh the inventory/grants and
verification; unexpected tables/views/sequences/enums/routines fail closed. The
verification checks effective table AND column privileges, grant-option denial,
attributes, membership, ownership, search_path, enums and exactly Alembic head 014.
It reads catalogs and alembic_version, not financial rows; it performs no destructive
UPDATE/DELETE/TRUNCATE probes. These assertions are prepared, not executed evidence.

PostgreSQL has no per-role DENY overriding PUBLIC CONNECT. The scripts require
runtime CONNECT to the target Fides database and revoke PUBLIC CONNECT/TEMPORARY
only on that dedicated target; they never alter unrelated database ACLs. Managed
provider maintenance/template databases such as `postgres`, `template0` and
`template1` may remain technically connectable when provider settings and PUBLIC
privileges permit it. PUBLIC-derived CONNECT/TEMPORARY alone is not a failure.

Bootstrap and verification inspect `pg_database.datdba` and expanded database ACLs
(`aclexplode`, using `acldefault` when `datacl` is NULL). They fail on runtime
ownership or any role-specific database privilege on another database, including
CONNECT, CREATE, TEMPORARY and grant options, regardless of grantor. Grants from
provider users to Fides runtime roles therefore fail too. Effective CREATE on
another database is also refused, including CREATE derived from PUBLIC. All
databases are checked, even those currently disallowing connections; no database
name is treated as a trusted exception. Existing membership checks reject
inherited/provider-role and SET ROLE authority rather than relying on NOINHERIT.
Target database/schema CREATE denials and ledger/audit protections are unchanged.
Unexpected CREATE on another schema is still refused without changing that schema.

These catalog checks cannot establish what schemas/data or PUBLIC object grants
exist inside other databases. Fides isolation requires a dedicated application
database, no Fides schema/data elsewhere, no explicit cross-database grants,
service `DATABASE_URL` pinning, and provider network/auth controls. Before execution,
review the actual provider/database inventory and administrator authority. Before
production acceptance, verify that inventory and each relevant database's schema,
data and effective application privileges, including PUBLIC grants; document any
maintenance/template connectivity. A passing script is not proof of network
isolation or of inaccessible data in another database.

Semantics references:

- [PostgreSQL 16 privileges](https://www.postgresql.org/docs/16/ddl-priv.html)
- [PostgreSQL 16 pgcrypto](https://www.postgresql.org/docs/16/pgcrypto.html)
- [PostgreSQL 16 psql variables](https://www.postgresql.org/docs/16/app-psql.html)
- [PostgreSQL 16 REVOKE semantics](https://www.postgresql.org/docs/16/sql-revoke.html)
- [PostgreSQL 16 database catalog](https://www.postgresql.org/docs/16/catalog-pg-database.html)
- [PostgreSQL 16 ACL inspection](https://www.postgresql.org/docs/16/functions-info.html)

## Local development privileges (unchanged)

The Docker Compose setup in `docker-compose.yml` (B1) uses a single,
broadly-privileged `fides` role for local development convenience only,
across both `fides_dev` and `fides_test`. This is acceptable for a
local, disposable development database and is explicitly **not** the
production role model described above.
