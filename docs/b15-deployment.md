# B15 staging deployment and release runbook

Status: B15-D0 APPROVED, documentation only. Baseline:
`e8babb3629acaa593f7a950a55ffda646d713e3c`.
No cloud resources, secrets, grants, deployment hooks, or application changes are
created by this checkpoint. Completion of a checklist below requires evidence
from later execution, not merely this document.

## Frozen architecture and runtime

| Component | Host / arrangement |
| --- | --- |
| Web | Vercel, Next.js workspace `frontend/web` (`@fides/web`) |
| API | Railway, backend root `backend/`, FastAPI `app.main:app` |
| PostgreSQL | Railway, isolated staging and production databases/credentials |
| Reminders | Separate Railway scheduled service, hourly |
| Notification cleanup | Separate Railway scheduled service, daily |
| Mobile | Expo, direct HTTPS requests to deployed Railway API |
| Source / releases | GitHub, exact approved commit/artifact promotion |

Web uses its existing same-origin `/api/v1` relay. Mobile calls the API directly.
No client receives database or provider credentials.

Backend installation, from `backend/`:

```sh
python -m pip install -r requirements.txt
```

Frozen Railway start command, with shell expansion of the assigned PORT:

```sh
python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --no-proxy-headers --no-access-log
```

PORT is not automatically wired from Settings into Uvicorn. Verify the hosting
start-command shell and injected port during R2. Preserve both flags. Source
requires Python 3.11+ features; select and verify an explicit compatible runtime.
The frontend declares Node >=24; platform runtime support must be verified.
There is currently no Railway/Vercel deployment configuration or migration hook.

## Environment matrix

Settings names/defaults are sourced from `backend/app/config.py`. Backend Settings
load environment variables and optional process-relative `.env`; deployment
secrets belong in restricted environment configuration, never tracked files.

| Variable | Staging | Production | Classification |
| --- | --- | --- | --- |
| APP_ENV | `staging` | `production` | Public configuration, explicitly required |
| DATABASE_URL | Process-specific staging role | Process-specific production role | Secret, required for DB access |
| OTP_PROVIDER | `twilio` | `twilio` | Public configuration, required |
| TWILIO_API_KEY_SID | Staging API Key SID | Separate production credential | Restricted credential identifier, required |
| TWILIO_API_KEY_SECRET | Staging secret | Separate production secret | Secret, required |
| TWILIO_VERIFY_SIGNUP_SERVICE_SID | Staging signup service | Separate production signup service | Public provider identifier, required |
| TWILIO_VERIFY_LOGIN_SERVICE_SID | Distinct staging login service | Distinct production login service | Public provider identifier, required |
| AUTH_RATE_LIMIT_HMAC_SECRET | Staging secret | Separate production secret | Secret, required |
| PORT | Hosting-assigned port | Hosting-assigned port | Public process configuration, explicitly used by launch command |

The API Key SID must be SK + 32 hex digits; service SIDs must be VA + 32 hex
digits and distinct for signup/login. Secrets must be nonblank; deployment must
provide secure values. No Twilio master Account Auth Token or JWT signing secret
is required. Fake/disabled OTP is rejected in staging/production. Both scheduled
commands load Settings and therefore currently require the provider/HMAC fields
above despite not calling Twilio. Do not mislabel their environment to bypass
validation; limiting this settings coupling requires separate approval.

Keep approved defaults below; B15-D0 does not change auth or rate limits. These
optional settings are public configuration except the test database URL:

| Variable | Current default |
| --- | --- |
| APP_NAME | `fides-backend` |
| LOG_LEVEL | `INFO` |
| DATABASE_ISOLATION_LEVEL | `READ COMMITTED` (only allowed value) |
| TEST_DATABASE_URL | Empty; secret if configured, local/CI test-only |
| AUTH_ACCESS_TOKEN_TTL_SECONDS | 900 |
| AUTH_REFRESH_SESSION_TTL_SECONDS | 2592000 |
| OTP_CODE_LENGTH | 6, fixed |
| OTP_CHALLENGE_TTL_SECONDS | 600 |
| OTP_PROVIDER_OPERATION_LEASE_SECONDS | 30 |
| OTP_RESEND_COOLDOWN_SECONDS | 60 |
| OTP_REQUEST_PHONE_10M_LIMIT | 3 |
| OTP_REQUEST_PHONE_24H_LIMIT | 10 |
| OTP_REQUEST_IP_10M_LIMIT | 20 |
| OTP_REQUEST_IP_24H_LIMIT | 100 |
| OTP_VERIFY_CHALLENGE_LIMIT | 5 |
| OTP_VERIFY_PHONE_10M_LIMIT | 10 |
| OTP_VERIFY_IP_1M_LIMIT | 30 |
| OTP_VERIFY_IP_1H_LIMIT | 200 |
| AUTH_REFRESH_SESSION_1M_LIMIT | 10 |
| AUTH_REFRESH_IP_1M_LIMIT | 60 |
| AUTH_TRUSTED_PROXY_CIDRS | Empty; JSON array of strict CIDRs if approved |
| OTP_PROVIDER_CONNECT_TIMEOUT_SECONDS | 2 |
| OTP_PROVIDER_READ_TIMEOUT_SECONDS | 5 |
| OTP_PROVIDER_WRITE_TIMEOUT_SECONDS | 5 |
| OTP_PROVIDER_POOL_TIMEOUT_SECONDS | 1 |
| OTP_PROVIDER_OPERATION_BUDGET_SECONDS | 10 |
| AUTH_OTP_CLEANUP_RETENTION_SECONDS | 86400 |
| AUTH_RATE_LIMIT_CLEANUP_RETENTION_SECONDS | 86400 |
| AUTH_SESSION_CLEANUP_RETENTION_SECONDS | 2592000 |

| Frontend variable | Staging / production value | Classification |
| --- | --- | --- |
| NEXT_PUBLIC_API_BASE_URL | `/api/v1`, existing AuthProvider resolves against web origin | Public web build configuration |
| FIDES_BACKEND_API_URL | Absolute environment-specific HTTPS API URL ending `/api/v1` | Server-only routing configuration; not a secret |
| EXPO_PUBLIC_API_BASE_URL | Absolute environment-specific HTTPS API URL ending `/api/v1` | Public mobile bundle configuration |
| NODE_ENV | Standard Next.js production mode on deployed web | Public framework configuration |

Do not put secrets in NEXT_PUBLIC_/EXPO_PUBLIC_ values. Staging/production must
have separate DBs, service credentials, HMAC secrets, provider credentials and
Verify services, and destination URLs. Public bundle URL changes require a new
build/export; no EAS environment/release profiles currently exist. No CORS origin
environment setting or MIGRATION_DATABASE_URL setting exists. Each separate
migration/service process uses its own DATABASE_URL.

## Database release boundary

Existing migration mechanism is Alembic. Head is `014`, parent `013`; migration
`001` requires pgcrypto. Use `postgresql+psycopg://` for the installed driver;
verify provider connectivity/TLS and extension privileges rather than assuming a
supplied connection URL already meets these requirements.

From `backend/`, using the migration role's DATABASE_URL in process environment:

```sh
python -m alembic heads
python -m alembic upgrade head
python -m alembic current
```

Alembic reads os.environ DATABASE_URL directly, not the application `.env` loader.
Run one explicit migration step separately from app startup; do not run it from
every API worker. Verify revision 014, tables, constraints and service-role grants
before accepting the release. Grants are separate from schema migrations.

Use separate migration/API/reminder/notification-cleanup roles as detailed in
[database-roles.md](database-roles.md). Runtime service roles have no DDL, object
ownership or inherited migration rights, and no superuser/CREATEDB/CREATEROLE/
BYPASSRLS. The API needs notification_preferences SELECT/INSERT/UPDATE in addition
to existing domain/auth grants. Ledger_events and audit_logs remain SELECT/INSERT
only: prove UPDATE/DELETE/TRUNCATE denial. Reminder and cleanup credentials must
not acquire financial mutation privileges. Verify minimum cleanup row-locking
privileges for SELECT FOR UPDATE SKIP LOCKED under the actual credential.

The API pool permits up to 15 connections per process (5 + 10 overflow); budget
API replicas/workers, jobs and migration connections against the database limit.

## Scheduled services

From `backend/`, with migrated DB and each job's own credential/configuration:

```sh
python -m app.jobs.reminders
python -m app.jobs.notification_cleanup
```

Reminders run hourly and notification cleanup daily. UTC scheduling is acceptable;
exact scheduler times are configured/recorded during R3. Use one configured schedule
per job/environment; no HTTP-worker loop. Existing dedupe uniqueness and state
rechecks protect reminders during overlap; cleanup uses bounded SKIP LOCKED
transactions. Monitor nonzero exits and missing successful runs. Reminder dates
remain contractual borrower-local dates using IANA timezones. Cleanup removes
only notifications strictly older than 90 days, including read/unread rows.

Verify deployed frontend reminder/null-actor compatibility before enabling
delivery. There is no executable auth-cleanup command: cleanup_auth is an internal
function requiring separate maintenance authorization. Any wrapper/schedule for
it requires a subsequent bounded decision, not an invented command in this runbook.

## Staging readiness and proxy decisions

Use `/health` for process liveness. `/readiness` runs SELECT 1 but DB failure returns
HTTP 200 with `{"status":"not_ready","database":"unreachable"}`. Never use it
as an HTTP-status-only rollout gate. Staging release verification must require
HTTP success AND JSON `status == "ready"` AND `database == "reachable"`; timeout,
transport failure, invalid JSON or any other values fail the release. Separately
verify migration head and role privileges: SELECT 1 proves neither. No readiness
code change is approved here. Invalid settings fail startup, but startup alone
does not prove database/schema/provider readiness.

Retain --no-proxy-headers. Do not broadly trust forwarding headers, configure
wildcard CIDRs, or enable Uvicorn peer rewriting. Existing Fides peer/CIDR policy
remains authoritative. The same-origin Vercel relay is approved and unchanged.
It does not forward browser client IPs; shared backend-observed web proxy IP
budgets are accepted for RESTRICTED STAGING ONLY. Do not increase rate limits to
mask this. Proper proxy identity/client-IP design is REQUIRED BEFORE PROD; Railway
CIDRs alone cannot recover an IP absent from the relay request.

## Security and operational release gates

| Gate | Staging acceptance | Additional production requirement |
| --- | --- | --- |
| HTTPS | Verify API/web HTTPS ingress and appropriate redirect behavior | Verify production domain/TLS/HSTS policy; no local/dev HSTS |
| CORS | Same-origin relay; native mobile direct API; no permissive backend CORS | Approve any additional browser origin explicitly; no invented CORS variable |
| Request size | Verify existing 1,048,576-byte backend limit through public paths, streamed and misleading lengths; verify web ingress buffering/limits | Retain approved boundary, safe 413 and no service dispatch for oversized bodies |
| Headers | Verify backend nosniff/no-referrer, no-store, WWW-Authenticate, Retry-After and correlation | Web host must cover relay success/error paths; current relay drops backend security headers; approve CSP/frame policy |
| Secrets | Restricted environment storage, separate staging credentials, no tracked secrets/public bundles | Rotation/access/incident procedure, production isolation |
| DB least privilege | Effective grants, no DDL/ownership, append-only mutation denial proved | Repeat under production credentials; no broad local role |
| Migration separation | Explicit migration role/process before acceptance | One reviewed release step; no API migration credential |
| Logging/privacy | Structured application logs, sanitized IDs, --no-access-log; inspect platform logs for sensitive leakage | Restrict access/retention; no tokens/OTP/PII/body/credential-bearing URLs or raw IP leakage |
| Backup/restore | Confirm backup capability and rehearse isolated recovery before production planning | Approve RPO/RTO/retention, enable backups and prove restore; no assumption of platform defaults |
| Monitoring/alerts | Verify liveness/body-aware readiness and failed/missed job detection | Owned alerts for availability, error rates, DB capacity/storage, backups and job freshness |
| Rollback | Record artifact compatibility, migration revision and operator procedure | Rehearsed data-preserving recovery and release ownership |

Existing settings/header/log safeguards are not proof of actual platform
configuration. Full release integration/regression, OpenAPI verification and
dependency-security review remain required; this docs task does not run them.

## Rollback policy

Prefer rollback to a known compatible application artifact without changing DB
history. Use forward migration repair when necessary. Do not automate destructive
downgrades, manual stamping, or database replacement that loses financial history.
Migration 013 refuses downgrade with preferences or keyed/reminder notifications.
Migration 014 refuses downgrade when closure data/provenance would be lost. Read
their current guards before any recovery; retention/archival is not authorization
to delete financial history. Restore decisions require an approved recovery plan,
data-loss assessment and preserved ledger/audit history. Roll back incompatible
jobs/web/mobile alongside the API as required by the recorded compatibility matrix.

## Ordered execution and stop gates

1. **B15-D0:** this documentation checkpoint only; commit/push branch, no PR/merge.
2. **B15-R1:** authorize Railway access/resources/budget/ownership; create isolated
   staging PostgreSQL, verify pgcrypto/TLS/driver, provision roles, migrate to 014,
   prove privileges and record backup capability. No app startup migration.
3. **B15-R2:** configure/deploy approved backend artifact and required staging
   secrets, explicit PORT command, bounded proxy trust, liveness and body-aware
   readiness checks. Verify schema/roles/provider, headers and log privacy.
4. **B15-R3:** configure the two separate scheduled services with restricted roles,
   hourly/daily UTC schedules, frontend compatibility, overlap and failure alerts.
5. **B15-V1:** configure Vercel workspace-aware Next.js deployment. Candidate root
   frontend/web, install `cd .. && npm ci`, build `cd .. && npm run build:web`, with
   outside-root workspace access. Verify platform settings, Node support, relay
   URLs, web headers and absence of dev preview; do not static-export the relay.
6. **B15-M1:** supply mobile HTTPS staging URL, validate Expo configuration and
   real-device session/secure-storage behavior. Decide packaging identities/profiles
   separately; do not publish an app as part of staging configuration.
7. **B15-E2E:** verify controlled real-OTP accounts, auth/IDOR, existing financial
   lifecycle, idempotency/races, ledger, closure, extensions, reminders/preferences
   and derived views; run release regression/OpenAPI/dependency checks. Exercise
   DB/provider failures, request limits, spoofed forwarding and job alerts. Existing
   local fake-provider scripts are not automatically staging runners.
8. **B15-PROD:** close proxy identity and all production gates; use isolated
   production resources/secrets, separate migrations and exact validated artifacts,
   restore/rollback evidence and post-deployment verification before acceptance.

Before R1, confirm infrastructure authorization, access, resource plan/budget and
ownership, and review role-provisioning and migration/backup prerequisites. These
are execution inputs, not claims that resources already exist. Stop for separate
approval if work requires behavior/API/auth/proxy/readiness redesign, new
migrations/models/indexes/dependencies, changed financial semantics, or new product
features. This contract authorizes no such implementation.
