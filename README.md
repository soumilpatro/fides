# Fides — Give Trust a Financial Memory

Fides is a cross-platform **shared financial commitment record** for people who already know and trust each other. Participants can agree on independent commitments and preserve an auditable history of repayment decisions, extensions, and closure.

**Fides does not lend, transfer, or hold money. It is not a credit bureau or an official credit-score service.**

> **Status:** Founder-built MVP with internal functional testing. Not a production-hardened financial service; independent usability, security, accessibility, and scale testing are ongoing or planned. Do not enter real financial details into an instance you do not trust.

## How it works

1. Users authenticate and accept a connection.
2. One participant proposes a commitment, including amount and optional terms; the counterparty accepts or rejects it.
3. Repayments are reported against **one specific commitment**.
4. The counterparty verifies or disputes each repayment. **Only verified repayments reduce verified outstanding.**
5. Participants can propose and decide extensions or mutually close a commitment; waived outstanding amounts are recorded **separately** from verified repayments.
6. Summaries, notifications, and historical records preserve the shared context.

Each connection can hold multiple **independent** commitments. Coordinated multi-lender funding, Trust Profiles, Trust Circles, AI insights, integrated transfers, and partner APIs are future concepts—not implemented MVP claims.

## Technology

| Layer | Stack |
| --- | --- |
| Web | Next.js, React, TypeScript |
| iPhone/mobile | React Native, Expo |
| Shared API | Python, FastAPI |
| Persistence | PostgreSQL, Alembic migrations |
| Local DB | Docker Compose with a dedicated development and test database |
| Deployment arrangement | Web: Vercel; backend/database: Railway; mobile: Expo-based client |

Both frontends share backend-authoritative financial logic. Monetary amounts are handled as integer minor units. See [security guidance](SECURITY.md) and the [deployment runbook](docs/b15-deployment.md) for caveats and environment requirements.

## Repository map

- `backend/` — API, identity/session controls, financial domain logic, migrations, background tasks
- `frontend/web/` — Next.js web client
- `frontend/mobile/` — React Native/Expo client
- `frontend/shared/` — typed API client, pure domain helpers, design tokens
- `tests/backend/` and `frontend/tests/` — automated checks
- `database/`, `infra/` — local database initialization and operational scripts
- `docs/`, `DECISIONS.md` — architecture decisions and operational guidance
- `FIDES_*SPECIFICATION*.docx` — historical specifications; code and current docs are the source of truth for implemented behavior

## Local development

Prerequisites: **Node.js 24+**, **Python 3.11+**, npm, and Docker (for the local PostgreSQL example). See the more detailed [frontend guide](frontend/README.md).

```bash
git clone https://github.com/soumilpatro/fides.git
cd fides
docker compose up -d db
```

Prepare backend configuration:

```bash
cd backend
cp .env.example .env
python -m venv .venv
# Activate .venv using your shell's command
python -m pip install -r requirements-dev.txt
```

**Before using login:** configure a permitted OTP provider and a generated `AUTH_RATE_LIMIT_HMAC_SECRET` in your local untracked `.env`. The example intentionally defaults to disabled authentication. Fake OTP is strictly for isolated local testing; never use it in staging/production. Apply the Alembic migrations required by your local database before authentication (see `docs/b15-deployment.md` for migration safety guidance). From `backend/`:

```bash
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

Run clients in another terminal from `frontend/`:

```bash
npm ci
npm run web
# Or, separately:
npm run mobile
```

Copy `frontend/web/.env.example` to `frontend/web/.env.local`. For mobile, copy `frontend/mobile/.env.example` to `frontend/mobile/.env` and set `EXPO_PUBLIC_API_BASE_URL` to an API host actually reachable from your physical device; `localhost` on a phone refers to that phone.

**Environment safety:** `EXPO_PUBLIC_*` and `NEXT_PUBLIC_*` values are distributed to clients and must never contain secrets. Local `docker-compose.yml` credentials are development-only; do not expose the container port to an untrusted network.

## Validation

From `frontend/`:

```bash
npm ci
npm run lint
npm run typecheck
npm run test:auth
npm run test:connections
npm run test:commitments
npm run test:repayments
npm run test:dashboard
npm run test:extensions
npm run test:notifications
npm run test:profile
npm run test:notification-preferences
npm run test:mutual-closure
npm run test:due-summaries
npm run build:web
npm run config --workspace=@fides/mobile
```

Backend tests require an **isolated** `TEST_DATABASE_URL` with migrations/test prerequisites satisfied:

```bash
cd backend
python -m pytest ../tests/backend
python -m ruff check app ../tests/backend
```

These commands are documented entry points, not a promise that they were rerun during documentation updates.

## Contributing, security, and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and contribution expectations and [SECURITY.md](SECURITY.md) to report vulnerabilities privately.

**Publicly viewable; all rights reserved.** Fides is not open-source licensed. Public visibility permits viewing and linking, not general reuse or redistribution. Read [RIGHTS.md](RIGHTS.md). The team must confirm contribution/asset ownership before publishing.

## Public-release caution

Before switching repository visibility, review **all Git history** (not just today's files) for credentials, phone numbers, personal records, private test data, internal URLs, and third-party material. Remove or rewrite sensitive historical objects and rotate affected secrets **before** publishing. See [the release checklist](docs/public-release-checklist.md).
