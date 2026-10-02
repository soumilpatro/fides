# Fides frontend — F1

Separate Next.js and Expo clients implement phone OTP authentication against the
existing B2 contract. No product/financial screens are implemented. Backend B12
remains server-only; B13 is a separate branch and is not used here.

## Structure

```text
shared/
  api/             typed auth DTOs, errors, request client
  auth/            pure serialized session coordinator and flow helpers
  tokens/          approved brand/layout/type and semantic status tokens
web/
  app/             welcome, signup, login, guarded app destinations
  app/api/v1/      allowlisted transparent auth transport relay
  app/dev/         development-only F0 foundation preview
  features/auth/   DOM auth flow, context, guard, memory SessionStore
mobile/
  features/auth/   React Native auth flow, context, SecureStore SessionStore
  navigation/      welcome/auth and four-destination shell
  app/             font bootstrap and preserved development F0 preview
 tests/            Node auth tests; isolated auth-only visual fixture
```

Only tokens, API types/errors and pure logic are shared. UI, navigation,
accessibility and credential storage remain separate for each platform.

## Run against the local backend

Use Node 24 LTS and the existing npm workspace lockfile. From `frontend/`:

```sh
npm ci
npm run web
npm run mobile
```

Use the repository's existing, initialized local development PostgreSQL database
and backend environment. From `backend/`, with the repository virtual environment:

```sh
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

For local authentication the backend must already have an enabled, correctly
configured OTP provider and HMAC secret (see `backend/.env.example`). Existing
local fake-provider codes are signup `123456`, login `654321`; never enable the
fake provider in staging/production. F1 does not apply migrations or change backend
configuration. An empty database cannot serve authentication.

Web configuration (`web/.env.local`, based on `web/.env.example`):

- `NEXT_PUBLIC_API_BASE_URL=/api/v1`
- `FIDES_BACKEND_API_URL=http://localhost:8000/api/v1`

Next's relay forwards only GET `/me` and POST `auth/otp/request`, `auth/otp/verify`,
`auth/refresh`, `auth/logout`. It forwards bearer/JSON and safe response headers,
uses no cookies or server credential storage, disables caching, refuses redirects,
and never logs bodies. This avoids requiring backend CORS changes. It does not
forward client-supplied proxy IP headers; deployment proxy/trust policy is a
separate decision. All browser clients behind it share the backend-visible proxy IP
budget. Production transport must use HTTPS.

Mobile configuration (`mobile/.env`, based on its `.env.example`):

- `EXPO_PUBLIC_API_BASE_URL=http://<development-host>:8000/api/v1`

Physical devices cannot reach the computer via `localhost`; use a reachable local
host with backend binding/firewall configured for development. No credentials go
in public frontend configuration. Use SDK 57-compatible Expo Go/development client.
iOS Simulator requires macOS; browser Expo preview is supplemental:

```sh
npm run start --workspace=@fides/mobile -- --web --localhost --port 8081
```

The browser Expo preview requires an API with approved CORS routing; native Expo
requests do not have this browser restriction. No backend CORS patch is included.

## Authentication and sessions

Request: `{ intent: "signup" | "login", phone }` → server challenge UUID, expiry,
resend delay. Backend validation/normalization is authoritative. Signup collects
six-digit code temporarily in memory, then display name and a reviewable runtime-
derived IANA timezone. No invented timezone fallback. Final verify sends exactly
`{ challenge_id, code, display_name, timezone }`. Login sends only
`{ challenge_id, code }`. No password/email/social authentication.

The unchanged credential response is projected to the five existing credential
fields. GET `/me` must succeed before protected UI appears; cached response user is
not authoritative. Loading, anonymous and authenticated states are explicit.
Backend expiry, resend delay, safe errors and numeric `Retry-After` are respected.
No automatic OTP retries. Auth transport has a 15-second client deadline to avoid
indefinite verification/restoration/logout spinners; it does not change provider
leases, OTP validity, rate limits or backend cooldowns.

Native credentials use **expo-secure-store ~57.0.4**, one whole JSON credential
record with `WHEN_UNLOCKED_THIS_DEVICE_ONLY`, behind SessionStore. The native config
plugin excludes its records from Android backup and does not request Face ID.
No AsyncStorage,
plain files or persisted user/OTP state. Native-device keychain behavior still
requires device verification. Expo web preview uses memory, not native SecureStore.
Web also uses memory only: full reload returns to anonymous, including direct
protected URLs. No localStorage/sessionStorage/IndexedDB/cookie session. Persistent
web login awaits an approved secure-cookie/server-session architecture.

Session operations are serialized; concurrent refreshes share one flight. Rotation
replaces both tokens in one storage write and never reuses the previous refresh
credential after success. Access expiry triggers refresh in the active session;
mobile authenticated resume reconciles `/me` without resetting anonymous OTP flows.
Invalid/expired/revoked credentials clear locally. Transient failure hides protected
UI and offers explicit recovery/clear actions, without indefinite retries. Logout
uses bearer access authentication and clears local state even when the network or
credential is unusable. Storage deletion failure is surfaced for retry.

## Design and navigation

The approved F0 five brand colors, spacing 4/8/12/16/24/32/40/48/64, radii
8/12/16/20/999, Manrope/Inter typography hierarchy and 48px controls are retained.
VERIFIED, PENDING, DISPUTED, OVERDUE and CLOSED now use the supplied exact semantic
text/background/border colors; StatusChip requires explicit text and accepts an
optional semantic style. These do not derive server/financial state. No final dark
palette or additional missing semantic tokens are invented.

Web shell: Overview, Connections, Activity, Notifications, Profile / Settings.
Mobile: permanent Home, Connections, Activity, Profile tabs, global bell entry for
Notifications. Create commitment is a contextual disabled future-release action,
not a fifth tab. Destinations contain placeholders only, without financial data.

**Final Record Loop production asset missing.** Shared concept is approved, but
independent Brand components use a text-only FIDES wordmark as the asset insertion
point. No logo is redrawn. The F0 preview remains `/dev/foundation` on web (404 in
production) and a development-only entry on mobile.

F2+, dashboard/B12 UI, upcoming/overdue/activity calculations, settlement, financial
workflows, profile editing/deactivation, push, dark mode and frontend analytics are
excluded.

## Validation and isolated visual fixture

```sh
npm run lint
npm run typecheck
npm run test:auth
npm run build:web
npm run config --workspace=@fides/mobile
cd mobile
npx expo install --check
npx expo export --platform ios --output-dir dist/ios
```

Tests use Node's built-in runner and the existing TypeScript compiler; no new test
framework. They cover exact payloads/bearer boundaries, authoritative bootstrap,
rotation/single flight, invalid credentials, transient recovery, storage failure,
logout races and safe errors.

When a real backend cannot authenticate, `npm run preview:auth` starts a clearly
isolated localhost-only fixture on port 8765. It is never imported by application
code and refuses production mode. Point the web relay and/or Expo public API base
to `http://127.0.0.1:8765/api/v1` **only for visual validation**. Signup code is
`123456`; login code `654321`. All state is ephemeral auth-only test data, never
financial data. Use the live backend instead once it is available.

Current checks: all three workspace typechecks, web/mobile/shared lint, production web
build, Expo config/boot and iOS Hermes export pass; 25 Node auth tests pass. Manual
web and phone-size Expo browser reviews cover welcome, signup phone/OTP/profile,
login phone/OTP, safe auth errors and authenticated shell. Native-device secure
storage validation remains separate from the Expo browser review.

Live local validation also passes against the existing backend and `fides_dev`,
after applying existing Alembic migrations through 012. Process-only local settings
enable the existing fake OTP provider; no backend files or migration sources change.
Browser signup/login, authoritative `/me` and logout pass. The shared frontend
session coordinator also passes live refresh rotation, revoked/invalid credentials,
and expired access/refresh handling using temporary local token lifetimes. Shared
signup/login cooldowns remain enforced. The fake provider keeps challenge state in
memory and resets its reference sequence on restart; against retained database
history, a reused reference can safely fail with 503. Keep a single backend process
for a live validation sequence. No backend suite is rerun for this frontend-only batch.
