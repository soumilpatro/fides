# Fides frontend — F3

Separate Next.js and Expo clients implement phone OTP authentication against the
existing B2 contract and the merged Connections and Commitments APIs. F3 starts
from current main at 29326f9, including merged B13 and F2. Backend B12 remains server-only.

## Structure

```text
shared/
  api/             typed auth/connection/commitment DTOs, errors, request client
  auth/            pure serialized session coordinator and flow helpers
  commitments/     pure money/date/form/role and mutation-intent helpers
  tokens/          approved brand/layout/type and semantic status tokens
web/
  app/             welcome, signup, login, guarded app destinations
  app/api/v1/      allowlisted transparent auth/Connections/Commitments relay
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

Next's allowlisted relay forwards Connections routes as well as GET `/me` and POST `auth/otp/request`, `auth/otp/verify`,
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
Notifications. Home/Overview contains independent commitment records, with contextual creation
there and on accepted Connections. It is not a fifth tab/sidebar destination.
Activity, Notifications and Profile remain placeholders.

**Final Record Loop production asset missing.** Shared concept is approved, but
independent Brand components use a text-only FIDES wordmark as the asset insertion
point. No logo is redrawn. The F0 preview remains `/dev/foundation` on web (404 in
production) and a development-only entry on mobile.

F4+, dashboard/B12 UI, upcoming/overdue/activity calculations, settlement, financial
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

## F2 Connections

The existing API client provides create/list/detail/accept/reject/block/remove operations.
The relay retains the seven approved Connections routes and F1 authentication;
F3 adds only its eight approved commitment lifecycle/read-only terms routes.
Create sends only `{ phone }`; server responses retain only connection ID/status,
participant IDs/display names and timestamps. Phone numbers are entered only in the
new-request form and never displayed in connection lists/details.

Web routes are `/app/connections`, `/app/connections/new`, and
`/app/connections/[id]`. Mobile uses local list/new/detail navigation inside the
Connections tab. Other shell tabs remain placeholders. Roles come from authoritative
GET /me participant IDs. Incoming pending requests allow accept/decline/block;
outgoing pending requests allow cancel/block; accepted connections allow remove/block.
Blocked is terminal. Removed is neutral and reconnect opens an empty phone form.
Accept, decline, cancel, remove and block require confirmation; no action deletes financial history.

There are no optimistic status changes or automatic mutation retries. In-flight guards
prevent duplicate submissions. Mutation failures reconcile with safe reads; if those
reads fail, actions remain disabled until refresh. Transient refresh errors preserve
previous server data. The existing AuthSession owns refresh rotation and invalid-session
handling. Connection requests have a 15-second transport deadline and no idempotency keys.

Run `npm run test:connections` alongside the F1 checks above. For localhost-only
visual review, `npm run preview:connections` serves ephemeral auth/connection fixture
data on port 8766; it is not imported by the apps. Fixture login is +12025550101 with
code 654321. Point the existing relay/Expo API base to that fixture only for review.
`npm run test:connections:live` validates the existing local fake-provider backend,
creates three disposable development accounts, and logs out their sessions. All 14
live lifecycle/privacy/IDOR checks passed; no backend test suite or backend source
changes are needed for F2.

No dependencies were added. Expo's compatibility check requests expo ~57.0.26,
while the unchanged repository pins 57.0.25. This existing recommendation is an approved non-blocking follow-up; no dependency versions changed.
The authoritative Record Loop asset and physical-device secure-storage validation
remain known separate items. The F2 milestone excluded F3; the completed F3 scope is documented below.
Repayment workflows, contact discovery, unblock,
notifications, trust scores, dashboard/summary UI and B14 are excluded.

## F3 Commitments

Web routes: /app/overview (list), /app/commitments (list alias),
/app/commitments/new and /app/commitments/[id]. Accepted Connection detail links
preselect the connection; Home/Overview starts with an accepted-person picker.
Mobile implements separate React Native list/new/detail screens inside Home and
uses the same contextual Connection entry. The five web destinations and four
mobile tabs remain unchanged. Only DTOs, API/errors, parsers, role helpers and
synchronous mutation-intent state are shared; no shared cross-platform UI.

F3 uses POST/GET /commitments, GET /commitments/{id}, POST /commitments/{id}/confirm,
/reject, /cancel, GET /commitments/{id}/terms and /installments. The existing relay
forwards one validated Idempotency-Key only on those commitment POSTs. No generic
financial proxy or repayment/ledger/extension/notification/summary calls are added.
API responses are projected to their approved fields; participant phones are absent.

Creation sends connection_id, the current actor's BORROWER/LENDER role, IOU/PEER_LOAN,
integer principal_amount_minor, explicit INR/USD/GBP, trimmed description or null,
and explicit initial terms. Decimal amount/percent inputs use string/BigInt parsing;
no floating-point conversion, currency aggregation or FX. Date-only inputs are
calendar-validated without timezone arithmetic. Terms always include mutually
exclusive due_date/installment_dates, NONE/null or SIMPLE_FIXED/1–10000 bps,
and integer grace 0–365. Schedules support none, single, or 2–60 increasing dates.
The review identifies both roles, amount/currency and terms before submission.
Money moves outside Fides. The backend owns eligibility, timezone, versions,
interest rounding and installment allocation. Detail displays current server terms,
legacy null timezone copy and server installment amounts/status; no client totals,
balances or overdue calculations. Responses with inconsistent terms/schedule
references are withheld for refresh.

Pending creators may cancel; the non-creator may confirm/reject, independently of
borrower/lender role. Each requires confirmation. Other statuses are read-only.
Existing commitment reads never depend on current Connection visibility/status;
confirm failures from a changed connection remain server-authoritative. No optimistic
status updates or automatic mutation retries. Ambiguous responses retain exact key
and payload, reconcile by GET, then permit explicit same-operation retry only.
Opposite lifecycle actions remain disabled while an ambiguous action is unresolved.
IDEMPOTENCY_CONFLICT freezes that intent rather than silently changing its key.
Definite failures permit a fresh attempt; success clears the intent. In-memory
intents survive feature remounts inside AuthProvider, are actor/resource/action
scoped, and disappear when the application process/provider restarts. Web sessions
remain memory-only; mobile credentials remain in the existing SecureStore abstraction.
No tokens, OTPs, phone values or idempotency payloads are logged.

Validation commands from frontend/: npm run test:auth, npm run test:connections,
npm run test:commitments, npm run test:commitments:live, npm run lint,
npm run typecheck, npm run build:web, npm run config --workspace=@fides/mobile.
From frontend/mobile/: npx expo install --check and
npx expo export --platform ios --output-dir dist/ios.
The live runner targets localhost's existing fake-provider backend only, provisions
three disposable development accounts and logs out all sessions. It verifies
creation, roles, lifecycle, explicit terms, server schedules, independent currencies,
IDOR/privacy, replay/conflict, lost-response recovery and reads after blocking.
It does not run the backend suite or alter backend code/configuration/migrations.

For UI review only, npm run preview:commitments starts ephemeral localhost fixtures
at 127.0.0.1:8767. Point the relay/Expo API base to that URL's /api/v1 temporarily
using process environment variables. Login +12025550101 (Riya) or +12025550104 (Sam),
code 654321. Local fixture controls /__fixture/reset and /__fixture/mode allow
empty/mixed, slow, error, network, ambiguous, invalid and conflict scenarios.
This clearly isolated test data is never imported by application code and refuses
production mode; it supplements separate live-backend validation.

No dependencies/versions changed. The existing Expo 57.0.25 vs ~57.0.26
recommendation remains an approved non-blocking follow-up. The authoritative
Record Loop asset is still absent (text FIDES fallback); physical-device secure
storage validation remains separate from the phone-size Expo browser review.
F4+, B14, repayments, verification, disputes, extensions, ledger, notifications,
summary/dashboard/balances, settlement, financial aggregation and profile work
remain excluded.

F3 completion validation: 135 commitment tests, 25 auth regressions and 68
Connections regressions passed, with 33 live local-backend checks. Lint, all
workspace typechecks, production web build, Expo config and iOS export passed.
Web (desktop and narrow) and phone-size Expo browser reviews covered lists,
creation/context/pickers, all schedule controls, review/roles, pending actions,
read-only terminal records, terms/schedules, loading and safe recovery errors.
One focused review fixed opposite-action availability during an unresolved write,
inconsistent installment snapshots and navigation after feature unmount. The
visual fixture was also corrected to canonicalize nested JSON property order.


## F4 — repayments and verification

F4 starts from merged F3 at origin/main 025dc25ac99e8faa03644c6fef3817e1a3d31cb9,
in the isolated Fides-F4 worktree on feat/f4-repayments-verification.
The existing bearer API client now binds reportRepayment, listRepayments,
getRepayment, verifyRepayment, disputeRepayment and getVerificationHistory.
The web relay admits only the six exact F4 method/path combinations alongside
F1–F3. Idempotency-Key is required and forwarded only on approved financial POSTs;
GETs do not forward it. Cookies and arbitrary proxy headers remain excluded.
No auth storage or backend contract changes are introduced.

Web commitment detail contains a Repayments section. Report form lives at
/app/commitments/[id]/repayments/new; repayment detail and history at
/app/repayments/[id]. Both remain under Overview with the five existing sidebar
entries. Mobile extends the feature-local Commitment destinations with report
and repayment-detail views; its four tabs are unchanged. Web and React Native
rendered UI remain separate. Shared additions contain DTOs, API operations and
pure form/role/history/error helpers only.

Either current direct participant may report while the authoritative parent is
ACTIVE or PARTIALLY_REPAID. The form locks currency to the parent, reuses F3
string/BigInt decimal parsing, validates date-only YYYY-MM-DD and trims optional
notes to null (maximum 500 Unicode characters). The backend checks future dates
in the reporter's stored timezone. No payment method/reference/evidence is sent.
The review distinguishes reporting from verification and states that money
moves outside Fides. Independent list records retain backend order.

Only the other direct participant may verify/dispute a pending report while the
parent remains eligible. Confirmations send a JSON object containing only
optional decision_note (null when blank). PENDING_VERIFICATION, VERIFIED,
DISPUTED and read-only CANCELLED have explicit textual labels with approved
semantic tokens. Verification history is read-only and requires coherent parent,
reporter, currency, decision actor and status references before enabling actions.
CANCELLED introduces no workflow. Reporting never optimistically changes either
status; decisions refresh detail, history, list and parent. FULLY_REPAID remains
distinct from CLOSED. No obligation/outstanding/reservation/FX/interest/allocation
calculation exists in application frontend code.

Existing in-memory MutationIntents retain actor/resource/action-scoped key and
canonical normalized payload after uncertain outcomes. Controllers reconcile GETs,
then permit an explicit same-action/key/payload retry only. Opposite decision
controls remain disabled until the original outcome resolves. A key conflict
freezes the original intent. Definitive validation failures allow a new logical
attempt. Writes are never automatically retried after auth recovery; safe reads
may recover the session once. Failed reconciliation disables mutation eligibility
and withholds stale history; malformed successful write responses retain intent.
Memory intents survive feature remounts inside the current AuthProvider, not
process restart. Existing web memory-only and mobile secure credentials remain.

Validation from frontend/: npm run test:auth, npm run test:connections,
npm run test:commitments, npm run test:repayments, npm run test:repayments:live,
npm run lint, npm run typecheck, npm run build:web,
npm run config --workspace=@fides/mobile. From frontend/mobile/:
npx expo install --check; npx expo export --platform ios --output-dir dist/ios.
The live runner uses only localhost current-main backend from Fides-F4/backend
and the existing fake provider; three disposable users are logged out finally.
It covers partial/multiple/final reports, reverse roles, interest, disputes,
terminal decisions, capacity errors, blocked connection independence, IDOR,
original-response replay, conflicts and a lost real acknowledgement.
A verification OVER_REPAYMENT after a later obligation reduction is exercised
through controller tests and UI fixture, without introducing a terms-amendment
route solely to create that scenario.

npm run preview:repayments provides a localhost-only ephemeral fixture at 8768
for UI review. Point process-only relay/Expo base URL to its /api/v1. Login
+12025550101 (Riya) or +12025550104 (Sam), code 654321. Controls
/__fixture/reset and /__fixture/mode accept mixed/empty, slow, error, network,
ambiguous, invalid, over and conflict. Fixture financial arithmetic is local
server test setup only, never imported by application code. It supplements
separate live-backend validation and refuses NODE_ENV=production.

Zero dependencies added or versions changed. The existing Expo 57.0.25 vs
~57.0.26 recommendation remains a non-blocking follow-up; no Expo upgrade in F4.
The final Record Loop asset and physical-device secure-storage review remain
known separate items. No F5+, extensions, notifications, dashboard/B12 UI,
ledger/activity, settlement, waiver, closure, payments, installment allocation
or backend/B14 work is included.

F4 completion validation: 157 focused tests, 25 auth, 68 Connections and 135
Commitments regressions passed with zero failures/skips. Live validation passed
68 checks on current-main's migration 012 backend. Lint, all workspace typechecks,
production web build, Expo config and iOS export passed. Expo install --check
exits 1 solely for the unchanged 57.0.25 patch recommendation described above.
Desktop web and phone-size Expo review covered empty/mixed lists, all four
repayment statuses, report/review/pending success, both reporter directions,
verify/dispute confirmations and notes, history, uncertain report reconciliation
and explicit same-key retry, OVER_REPAYMENT/INVALID_STATE, and server-returned
FULLY_REPAID with the report action removed. The single focused review hardened
successful-response action/status validation so malformed receipts retain intent,
and verified failed-refresh action gating and stale-history withholding. Native
calendar keyboard input and date input/change capture were also validated.
