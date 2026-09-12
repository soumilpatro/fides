# Fides

Placeholder project README. Product and technical requirements will be captured in `PRODUCT_SPEC.md` and `TECH_SPEC.md`.

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
