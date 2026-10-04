# Fides

Product and technical requirements are in the checked-in Fides specification
documents, with approved implementation contracts recorded in `DECISIONS.md`.

## B15 deployment and release planning

The approved staging architecture and release gates are in
[the B15 deployment runbook](docs/b15-deployment.md), under decision B15-D0.
Web runs on Vercel; the API, PostgreSQL, and separate reminder/notification-cleanup
scheduled services run on Railway; Expo mobile consumes the deployed API.
This is a documentation checkpoint, not evidence of deployed infrastructure.

Migrations run separately from application startup using a distinct migration
credential. The current repository head is `014`. `/health` is process liveness;
staging release verification must inspect the `/readiness` JSON body because a
database failure currently still returns HTTP 200. See the runbook for exact
commands, environment separation, restricted-staging proxy policy, database roles,
security gates, and data-preserving rollback requirements.

## Backend runtime (B2 authentication)

With backend requirements already installed and configuration supplied through
the environment or `backend/.env` (see `backend/.env.example`), run from `backend`:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

Keep `--no-proxy-headers` in local and deployed launch commands. Authentication
rate limiting needs the original socket peer; Fides alone resolves
`X-Forwarded-For` using `AUTH_TRUSTED_PROXY_CIDRS` (a JSON CIDR list, empty by
default). Uvicorn must not rewrite the peer first, including for loopback peers.
Only configure trusted CIDRs for proxies you control, with forwarding headers
sanitized by those proxies. Never trust arbitrary client forwarding headers.

Keep `--no-access-log`: Uvicorn's default access log includes raw client addresses
and request URLs. Fides uses its structured application logs and sanitized
request IDs; proxy/platform access logging must likewise avoid raw IPs,
credential-bearing URLs, Authorization values and request/response bodies.
Authentication remains disabled by default until an explicit provider and its
required settings are supplied. Fake OTP is for explicitly configured local/test
use only; staging/production require the approved Twilio settings.
