# Decisions

Placeholder. Architecture and product decisions will be recorded here when they are made.

## B2-D0 — Approved MVP authentication architecture

- Date: 2026-09-09
- Status: APPROVED founder/technical decision; recorded before B2 implementation.
- Scope: B2 — Identity & Authentication for the shared mobile/web FastAPI backend.
- Authority: This explicit founder decision takes priority when resolving the specification conflicts identified below. It records approved architecture; it does not authorize unreviewed API schemas, database schemas, or security-policy details.
- Implementation state: This entry records decisions only. Authentication implementation, migrations, and dependency changes are not part of B2-D0.

### Specification context

This decision applies alongside these checked-in specifications:

- `FIDES_MASTER_PRODUCT_MVP_SPECIFICATION_v2.0_UNIFIED.docx`
- `FIDES_TECH_SPECIFICATION_v1.1_APP_WEB_BACKEND.docx`
- `FIDES_DATABASE_DATA_MODEL_SPECIFICATION_v1.0.docx`
- `FIDES_API_SPECIFICATION_v1.0.docx`
- `FIDES_AI_DEVELOPMENT_BACKEND_BUILD_SPECIFICATION_v1.0.docx`

### 1. Authentication API surface

For B2, the dedicated API Specification authentication surface is authoritative:

| Method | Endpoint |
| --- | --- |
| POST | `/api/v1/auth/otp/request` |
| POST | `/api/v1/auth/otp/verify` |
| POST | `/api/v1/auth/refresh` |
| POST | `/api/v1/auth/logout` |
| GET | `/api/v1/me` |
| PATCH | `/api/v1/me` |
| POST | `/api/v1/me/deactivate` |

The Tech Specification entries `POST /api/v1/auth/register` and `POST /api/v1/auth/login` are superseded for MVP authentication. Do not implement register/login aliases unless a later explicit decision requires them.

### 2. Primary identifier and login method

- The primary Fides MVP identity is a phone number.
- Normalize and store phone numbers in E.164 format.
- Authenticate through SMS OTP.
- Use the existing B1 `User.phone_e164` and `AuthIdentity` structures.

### 3. OTP provider

The production OTP delivery/verification provider is **Twilio Verify v2**.

- Put Twilio behind a Fides provider interface/adapter.
- Fides domain/account logic must not depend directly on Twilio-specific behavior.
- Automated tests must use a deterministic fake OTP provider; real OTP delivery must never be required.
- Never log OTP codes.
- Fides must not persist raw OTP codes.

### 4. Signup versus login

`POST /api/v1/auth/otp/request` must explicitly identify the authentication intent as `signup` or `login`.

- **Signup:** An unknown verified phone may create a Fides account after successful OTP verification. Signup must provide `display_name` and `timezone`, the fields required to create a valid User.
- **Login:** Existing accounts only. Login must not silently create an account for an unknown phone.

Exact request/response schemas must be defined in the B2 implementation contract before coding.

### 5. Session architecture

Fides owns its account session lifecycle.

- Use cryptographically random opaque access tokens and cryptographically random opaque refresh tokens.
- Store only token hashes server-side.
- There is no JWT requirement for MVP.
- Initial access-token lifetime: **15 minutes**.
- Initial refresh-session lifetime: **30 days**.
- Refresh credentials rotate on successful refresh; the previous refresh credential becomes invalid.

### 6. Authentication session persistence

During B2, add an additive PostgreSQL `auth_sessions` persistence model and a new migration after B1 migration `011`.

The model must support at minimum:

- Session ownership by user.
- Secure token-hash storage.
- Access-token expiry.
- Refresh-token expiry.
- Refresh rotation/revocation.
- Session creation time.
- Revocation state/time.
- Multiple simultaneous sessions for the same user.

The exact database schema must be reviewed before implementation. This decision does not define or approve that schema.

### 7. Authentication transport

Protected FastAPI endpoints use `Authorization: Bearer <access_token>`.

The shared backend contract must not depend on a particular client-side storage technology. Mobile/web credential storage remains a separate client concern. **TD-012 remains OPEN.**

### 8. Multiple-device session policy

- Each successful login may create an independent session.
- Multiple active sessions per user are allowed.
- Normal logout revokes the current session.
- Account deactivation revokes all sessions belonging to that user.

### 9. Profile update policy

`PATCH /api/v1/me` may modify only `display_name` and `timezone`.

The following are not part of B2:

- Phone-number change.
- Identity linking.
- Direct status modification through profile updates.
- Account anonymization.
- Editing internal identifiers.

### 10. Account deactivation policy

For B2 MVP, deactivation is not deletion or anonymization.

- Preserve required financial history.
- Set the User status to `DEACTIVATED` and record `deactivated_at`.
- Revoke all active authentication sessions belonging to the user.
- A deactivated account cannot log in or refresh.
- Keep the phone identity reserved.
- Do not provide self-service reactivation in B2.
- Block deactivation while the user has unresolved/non-terminal financial commitments.

This resolves B2 deactivation behavior only. The broader **TD-008 account deletion/anonymization decision remains OPEN** beyond this approved behavior.

### 11. Security requirements

B2 implementation must include:

- OTP request rate limiting.
- OTP verification attempt limiting.
- Expired OTP rejection.
- Replayed OTP rejection.
- Safe duplicate-account race handling.
- Token/session expiry enforcement.
- Refresh rotation.
- Session revocation.
- Secret/token/OTP redaction from logs.
- Safe provider error handling.
- Server-side current-user resolution.
- No client-supplied user ID as authentication authority.
- Generic responses where required to avoid account enumeration.
- Automated tests for invalid, expired, replayed, and unauthorized authentication paths.

Exact rate-limit thresholds and detailed stable error-code contracts must be proposed and reviewed before implementation; they must not be invented silently.

### 12. Decision status and remaining review

| Decision | Status | Approved resolution or boundary |
| --- | --- | --- |
| TD-001 Authentication provider/identifier strategy | RESOLVED FOR MVP | Phone E.164 + SMS OTP + Twilio Verify v2 adapter. |
| Authentication endpoint conflict | RESOLVED | Dedicated API Specification OTP/refresh/logout surface supersedes Tech Spec register/login entries for MVP; no aliases without a later decision. |
| Backend session architecture | RESOLVED FOR MVP | Opaque access and refresh credentials with server-side hashed session persistence. |
| B2 deactivation behavior | RESOLVED FOR MVP | Apply section 10, including the unresolved/non-terminal commitment restriction and revocation of all sessions. |
| TD-008 Account deletion/anonymization | REMAINS OPEN | Beyond the approved B2 deactivation behavior. |
| TD-012 Mobile authentication/session storage | REMAINS OPEN | Client storage is separate from the shared backend contract. |

Before implementation, define the exact authentication request/response schemas in the B2 implementation contract, review the exact `auth_sessions` database schema, and propose/review rate-limit thresholds and detailed stable error-code contracts. Unspecified details remain unspecified; this entry must not be treated as permission to invent them silently.

## B2-D2 — Final approved Identity & Authentication implementation contract

- Recorded: 2026-09-10.
- Status: **APPROVED FOR B2 IMPLEMENTATION**.
- Authority: Explicit founder approval incorporating and finalizing the B2-D1, B2-D1R, and B2-D1R2 technical reviews, including the final decision to use separate Twilio Verify Services for signup and login.
- Scope: Shared Fides FastAPI backend identity/authentication for the MVP. The five specifications named in B2-D0 remain authoritative outside the detailed decisions recorded here.
- Precedence: Where detailed earlier assumptions or B2-D0 wording conflict with this entry, this newer explicit B2-D2 decision governs B2 implementation while preserving B2-D0's architectural intent. B2-D0 remains preserved above as historical decision content.
- Superseded details: signup profile collection at OTP request; phone-only live-challenge uniqueness; cross-intent challenge conflicts; a single shared Twilio Verify Service; mandatory rejection of expired access credentials for logout; and mandatory module/file counts. This entry supplies the final API, schema, limits, errors, and lifecycle choices previously awaiting review.
- This B2-D2 recording task is documentation only. It does not itself implement authentication, add migrations/dependencies, or authorize future product scope.

### 1. API surface and common contract

The only B2 authentication/account endpoints are:

| Method | Endpoint | Success | Authentication |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/otp/request` | 202 | None; phone/intent from validated body |
| POST | `/api/v1/auth/otp/verify` | 200 | OTP proof for the stored challenge |
| POST | `/api/v1/auth/refresh` | 200 | Refresh credential in JSON body; access bearer not required |
| POST | `/api/v1/auth/logout` | 200 | Recognized current access credential; logout-only expiry exception |
| GET | `/api/v1/me` | 200 | Valid, unexpired access bearer |
| PATCH | `/api/v1/me` | 200 | Valid, unexpired access bearer |
| POST | `/api/v1/me/deactivate` | 200 | Valid, unexpired access bearer |

Do not implement `/auth/register` or `/auth/login`, including `/api/v1` aliases. Protected endpoints use `Authorization: Bearer <access_token>`; credentials are never accepted in query parameters. An incoming bearer on an OTP endpoint does not establish its target account.

Requests/responses use JSON. Request objects reject unknown fields and do not coerce numbers/booleans into strings. Fields are required and non-null unless explicitly stated otherwise. Timestamps are RFC 3339 UTC strings ending in `Z`; UUIDs use standard hyphenated strings. Malformed JSON returns `400 MALFORMED_REQUEST`; well-formed schema-invalid JSON returns `422 VALIDATION_ERROR`. Financial `Idempotency-Key` headers are not required by these auth endpoints.

Every B2 response, including errors, carries `Cache-Control: no-store` and a sanitized `X-Request-ID`. Protected 401 responses carry `WWW-Authenticate: Bearer`; rate-limit responses carry integer-seconds `Retry-After`. Preserve these headers through exception handling. Never expose provider/SQL exceptions or stack traces.

`MeResponse` contains exactly these required fields:

| Field | JSON type | Meaning |
| --- | --- | --- |
| `id` | string | User UUID |
| `phone_e164` | string or null | Own phone; nullable to respect B1, although B2-created users have a phone |
| `display_name` | string | Validated display name |
| `timezone` | string | Validated IANA timezone identifier |
| `status` | string | `ACTIVE` for successful authenticated account responses |
| `created_at` | string | UTC timestamp |
| `updated_at` | string | UTC timestamp |

`CredentialResponse` contains exactly these required, non-null fields: `access_token` (string), `refresh_token` (string), `token_type` (literal `Bearer`), `access_expires_at` (UTC timestamp string), `refresh_expires_at` (UTC timestamp string), and `user` (`MeResponse`). No provider references, auth-identity IDs, session internals, credential hashes, or audit metadata are returned.

### 2. OTP request contract

Signup request:

```json
{
  "intent": "signup",
  "phone": "+919876543210"
}
```

Login request:

```json
{
  "intent": "login",
  "phone": "+919876543210"
}
```

Both fields are required strings; intent is exactly `signup` or `login`. Do not collect or persist `display_name` or `timezone` here; those fields are forbidden, including null values.

On provider acceptance, return **202 Accepted** with exactly: `challenge_id` (UUID string), `expires_at` (UTC timestamp string), `resend_after_seconds` (non-negative integer remaining cooldown), and `message` (literal `Verification requested.`). All fields are required and non-null. Acceptance does not guarantee SMS delivery.

Request OTP for a valid, rate-eligible phone without branching on local account membership. Do not disclose whether it is existing, unknown, or deactivated before phone proof. The same policy applies to signup and login; an unknown login or existing-account signup can receive an SMS and be denied only after proof.

### 3. OTP verify contract and account creation

Signup verification:

```json
{
  "challenge_id": "<uuid>",
  "code": "123456",
  "display_name": "Example User",
  "timezone": "Asia/Kolkata"
}
```

Login verification:

```json
{
  "challenge_id": "<uuid>",
  "code": "123456"
}
```

The stored challenge determines intent. Signup requires non-null `display_name` and `timezone`; login forbids both. `phone`, `intent`, user IDs, and other fields are forbidden. `challenge_id` is a UUID; `code` is a string of exactly six decimal digits (`[0-9]{6}`), preserving leading zeros. OpenAPI describes both closed request shapes; server-side validation additionally checks the supplied shape against stored intent.

Load the challenge, require the correct shape, and normalize/validate signup profile fields **before** provider verification. Invalid profile input must not call the provider, consume a provider-check attempt, or persist profile values; IP abuse limits still apply. No signup profile PII is persisted before successful phone proof. Profile values from unsuccessful attempts do not become bound to the challenge.

Signup sequence: OTP request -> provider challenge -> validated signup verification input -> reserved provider-check operation -> explicit provider Approved result -> atomic User + AuthIdentity + AuthSession creation + selected challenge consumption + required audit -> commit -> credential response. No account rows are created merely by requesting OTP.

New User values: normalized phone, `ACTIVE`, normalized profile values from the successful verification request, `created_at = updated_at = event time`, and null `deactivated_at`. AuthIdentity uses `provider = phone`, the normalized phone as `provider_subject`, and the successful verification time as `verified_at`.

Login requires an existing ACTIVE User and matching `phone` AuthIdentity referencing that User. It never silently creates an account or repairs conflicting/missing identity records. Inconsistent identity persistence fails closed with a safe service error and operational alert. Each new successful login may create an independent session.

After proof, unknown login and existing ACTIVE-account signup return `409 AUTH_FLOW_NOT_ALLOWED`; deactivated accounts return `403 ACCOUNT_DEACTIVATED`; anonymized/unavailable accounts return `403 ACCOUNT_UNAVAILABLE`. These denials consume the selected verified challenge, audit the denial, and issue no credentials. Phone identity remains reserved after deactivation.

Account eligibility is rechecked against current state at verification time. Signup may complete and an independently issued login challenge may subsequently succeed if still valid and the account is now eligible. Do not automatically consume the other intent's challenge.

Use database uniqueness and transaction-safe coordination for concurrent signup. User, identity, session, challenge consumption, and successful account audit writes commit together; failures leave no orphan account records. A signup uniqueness conflict must not be recovered by issuing credentials for the existing account. With competing valid profile submissions, only the successful operation owner's request supplies the new profile.

Provider approval and PostgreSQL commit are not a distributed atomic transaction. If persistence fails after provider approval, fail closed; never infer approval from a subsequent 404. Return credentials only after commit. If commit succeeds but the HTTP response is lost, replay cannot reproduce plaintext credentials; the client begins a new authentication flow (login after completed signup).

### 4. Phone identity

Accept string input beginning with `+`; strip outer whitespace, require `^\+[1-9][0-9]{1,14}$`, validate against phone metadata, and format as canonical E.164. Do not guess a country, accept national-format numbers/extensions/separators, or coerce numeric JSON input. Backend normalization is authoritative.

Use the same canonical phone in `User.phone_e164`, `AuthIdentity.provider_subject`, challenge storage, and rate-limit subject derivation. `AuthIdentity.provider = "phone"`; Twilio is infrastructure, not the identity namespace. No India-only registration rule is inferred from INR-first financial support. Phone changes and identity linking are outside B2.

### 5. Twilio Verify architecture and configuration

Use Twilio Verify v2 behind a provider-neutral Fides adapter, with **two distinct Verify Services**:

| Intent | Service configuration | Persisted provider routing key |
| --- | --- | --- |
| signup | `TWILIO_VERIFY_SIGNUP_SERVICE_SID` | `twilio_verify_v2_signup` |
| login | `TWILIO_VERIFY_LOGIN_SERVICE_SID` | `twilio_verify_v2_login` |

Both services use environment/secret-manager supplied `TWILIO_API_KEY_SID` and `TWILIO_API_KEY_SECRET`. Authenticate with the API Key SID/Secret; do not require or design around the master Twilio Account Auth Token. Keep Service SIDs separate from API credentials. Validate required configuration and distinct signup/login Service SIDs; never silently fall back to one shared service or a fake provider in production.

Persist the returned Twilio Verification SID (`VE...`) as the opaque `provider_reference`. Resolve the adapter/service from the stored routing key for subsequent checks. Verification Check sends that stored SID plus submitted code (`VerificationSid` and `Code` in the direct REST request), without requiring the phone again. The domain layer does not parse SIDs, construct Twilio URLs, or interpret Twilio error numbers.

The provider-neutral interface supports request verification by phone and verify code by opaque reference. Normalize outcomes into Requested, Approved, InvalidCode, Expired, RateLimited, ChallengeUnavailable, DeliveryUnavailable, TransientFailure, and ConfigurationFailure. Only explicit Approved for the matching challenge can authorize account/session creation.

Never infer approval from HTTP 404: it can represent expiry, prior approval, maximum attempts, deletion, or another unavailable state. Use known local consumed/expired/locked state where available; otherwise report an unavailable challenge. A reused or unavailable provider reference must not be treated as new proof. Do not automatically retry provider POSTs after uncertain outcomes.

Provider settings: SMS, six-digit codes, ten-minute validity. Retained timeout defaults: connection 2 seconds; read/write 5 seconds; connection-pool 1 second; overall operation budget 10 seconds. Configure these centrally and validate them. Transient/configuration provider failures expose the same safe `AUTH_PROVIDER_UNAVAILABLE` message while operational classification differs.

Automated tests inject a deterministic fake provider and clock, including separate intent/service routing, reference reuse, expiry, failures, leases, and concurrency. No automated test calls live Twilio or requires SMS delivery. Raw OTP values are never persisted or logged; never log Twilio API secrets or Authorization values.

### 6. Challenge uniqueness and intent independence

Permit at most one live/quarantined challenge per **`(phone_e164, intent)`**, for states `SENDING`, `PENDING`, `CHECKING`, `LOCKED`, `INDETERMINATE`. One phone may simultaneously have one signup and one login reservation.

Same phone + same intent reuses/resends the existing eligible challenge. Different intents are independent. The opposite intent must not block, mutate, consume, cancel, or invalidate the other challenge, or reset shared budgets. Shared limits/cooldown may still throttle either intent.

`AUTH_CHALLENGE_CONFLICT` is removed from B2 endpoints, taxonomy, OpenAPI, and tests. `AUTH_CHALLENGE_BUSY` applies only to an active operation on the requested challenge, not merely an operation on the other intent. Successful verification consumes only the selected Fides challenge. Separate Twilio Services ensure the provider proof is not shared across intents.

### 7. Shared abuse controls

All phone/IP request and verification budgets remain shared across signup/login. Phone/IP rate-limit subjects and the phone advisory-lock key must not include intent. Switching intent cannot reset or bypass a budget or cooldown.

| Policy | Approved configurable default |
| --- | --- |
| OTP requests per phone | 3 per 10 minutes; 10 per 24-hour UTC window |
| OTP requests per IP | 20 per 10 minutes; 100 per 24-hour UTC window |
| Phone-wide resend cooldown | 60 seconds |
| Provider verification checks per challenge | Maximum 5 over the challenge lifetime |
| Verification requests per phone | 10 per 10 minutes |
| Verification requests per IP | 30 per minute; 200 per hour |
| Refresh requests per session | 10 per minute |
| Refresh requests per IP | 60 per minute |

Use PostgreSQL-backed shared fixed-window buckets, atomic updates, and deterministic lock order. Keep reviewed defaults in central validated configuration, not scattered hardcoded constants. Changing configured limits/windows requires review. Fixed-window boundary behavior must be explicit and tested. No Redis for B2.

Use domain-separated HMAC-SHA-256 for phone/IP subjects, with an environment-managed secret; do not store raw values or unsalted hashes in buckets. Determine IP from the connection peer or explicitly trusted proxy configuration, not arbitrary forwarded headers. Retain individual IPv4 and IPv6 /64 grouping.

Cooldown uses the latest phone request reservation across **both** intents. Request reservations count even if the provider later fails ambiguously. Reserve provider-check attempts durably before calling the provider; failed checks must not regain allowance on rollback. The fifth check may succeed; an unsuccessful exhausted challenge becomes LOCKED. Provider failures consume attempted-operation allowance. IP controls cover invalid/unknown challenge or credential attempts without depending on account membership.

Return 429 with `Retry-After` for the longest currently blocking window/cooldown. Provider limits can be stricter. If shared enforcement storage fails, fail closed with `503 SERVICE_UNAVAILABLE`.

### 8. Challenge lifecycle and concurrency

Challenge validity is **10 minutes**; provider-operation lease is **30 seconds**. States are `SENDING`, `PENDING`, `CHECKING`, `CONSUMED`, `EXPIRED`, `LOCKED`, `FAILED`, `INDETERMINATE`.

Use the same normalized-phone PostgreSQL advisory lock for request/resend coordination across both intents. Under that lock, coordinate shared phone limits/cooldown and creation/reuse of the requested phone+intent reservation. The lock stays phone-wide even though uniqueness is phone+intent.

Persist an operation UUID/lease when reserving SENDING or CHECKING, then commit before the provider call. Do not hold database transactions or checked-out connections open across Twilio network calls. Complete only for the matching state, operation UUID, unexpired lease, and eligible challenge. Expired operation leases become INDETERMINATE; late or ambiguous results fail closed and cannot issue credentials.

Resends preserve original expiry and verification attempts and obey shared cooldown/budgets. LOCKED/INDETERMINATE reserve only their own intent until expiry. Explicitly transition expired reservations before replacement; do not use time-dependent predicates in partial indexes. A consumed challenge/provider reference cannot issue another session or change profile values. Challenge cleanup/expiry must not invalidate the other intent's valid challenge.

### 9. Authentication persistence

Additive migration **012**, with parent **011**, adds exactly `auth_sessions`, `auth_otp_challenges`, and `auth_rate_limit_buckets`. Do not modify migrations 001–011 or any B1 financial table. Reuse B1 User, AuthIdentity, AuditLog, Commitment, Base, and session infrastructure.

In the tables below, "none" means no default. Timestamps are timezone-aware PostgreSQL TIMESTAMPTZ. Services own state/transaction behavior; ORM models must mirror migration types, defaults, constraints, and indexes without delete cascades.

#### auth_sessions

| Column | PostgreSQL type | Nullable | Default |
| --- | --- | --- | --- |
| id | UUID | no | gen_random_uuid() |
| user_id | UUID | no | none |
| access_token_hash | BYTEA | no | none |
| refresh_token_hash | BYTEA | no | none |
| access_expires_at | TIMESTAMPTZ | no | none |
| refresh_expires_at | TIMESTAMPTZ | no | none |
| created_at | TIMESTAMPTZ | no | now() |
| last_rotated_at | TIMESTAMPTZ | yes | NULL |
| rotation_count | INTEGER | no | 0 |
| revoked_at | TIMESTAMPTZ | yes | NULL |
| revocation_reason | VARCHAR(32) | yes | NULL |

Constraints: UUID primary key; `user_id REFERENCES users(id) ON DELETE RESTRICT`; both hashes exactly 32 bytes with independent unique constraints; `created_at < access_expires_at <= refresh_expires_at`; non-negative rotation count; zero rotations require null last_rotated_at, positive rotations require a timestamp at/after creation; revocation timestamp/reason both null or both populated; revocation cannot precede creation. Reasons are only `LOGOUT` and `ACCOUNT_DEACTIVATED`. **No uniqueness on user_id**; multiple sessions are allowed.

Indexes/constraint names: `pk_auth_sessions`; `uq_auth_sessions_access_token_hash`; `uq_auth_sessions_refresh_token_hash`; `ix_auth_sessions_user_revoked` on `(user_id, revoked_at)`; `ix_auth_sessions_refresh_expires_at` on `refresh_expires_at`. The unique constraints supply indexed credential lookup; do not duplicate them with ordinary hash indexes.

#### auth_otp_challenges

| Column | PostgreSQL type | Nullable | Default |
| --- | --- | --- | --- |
| id | UUID | no | gen_random_uuid() |
| phone_e164 | VARCHAR(20) | no | none |
| intent | VARCHAR(6) | no | none |
| provider_key | VARCHAR(30) | no | none |
| provider_reference | VARCHAR(255) | yes | NULL |
| state | VARCHAR(20) | no | SENDING |
| verify_attempts | INTEGER | no | 0 |
| created_at | TIMESTAMPTZ | no | now() |
| expires_at | TIMESTAMPTZ | no | none |
| last_requested_at | TIMESTAMPTZ | no | none |
| operation_id | UUID | yes | NULL |
| operation_expires_at | TIMESTAMPTZ | yes | NULL |
| consumed_at | TIMESTAMPTZ | yes | NULL |

There are **no display_name, timezone, or OTP-code columns**. Intent is signup/login; states are the section 8 set; attempts are non-negative; expiry follows creation. Operation UUID/deadline are both populated only for SENDING/CHECKING. PENDING/CHECKING/CONSUMED require a provider reference. CONSUMED requires consumed_at; other states require it null.

Retain UUID primary key, unique `(provider_key, provider_reference)` for non-null references, phone history index `(phone_e164, created_at DESC)`, and expiry index `(expires_at)`. Live-reservation index:

```sql
CREATE UNIQUE INDEX uq_auth_otp_challenges_live_phone_intent
ON auth_otp_challenges (phone_e164, intent)
WHERE state IN ('SENDING', 'PENDING', 'CHECKING', 'LOCKED', 'INDETERMINATE');
```

This is the approved future migration contract, not an instruction to execute SQL during the B2-D2 documentation task. No phone-only live-reservation index remains.

#### auth_rate_limit_buckets

| Column | PostgreSQL type | Nullable | Default |
| --- | --- | --- | --- |
| policy | VARCHAR(40) | no | none |
| subject_hash | BYTEA | no | none |
| window_started_at | TIMESTAMPTZ | no | none |
| request_count | INTEGER | no | 0 |
| expires_at | TIMESTAMPTZ | no | none |

Composite primary key `(policy, subject_hash, window_started_at)`; subject_hash exactly 32 bytes; non-negative count; expiry follows window start; index expires_at.

Corresponding SQLAlchemy models are AuthSession, AuthOtpChallenge, and AuthRateLimitBucket registered on the existing Base. Use UUID(as_uuid=True), bytes/LargeBinary for BYTEA, timezone-aware timestamps, and optional mapped types for nullable fields. Model metadata must match migration 012; do not let autogeneration remove unrelated B1 indexes or alter historical constraints.

### 10. Token and session contract

Generate access/refresh randomness independently using `secrets.token_bytes(32)` (256 bits each). Use canonical unpadded base64url: access `fda_<43-character encoded value>`, refresh `fdr_<43-character encoded value>`, each 47 ASCII characters total. Validate type prefix and canonical representation before lookup.

Persist only 32-byte `SHA-256(full ASCII credential including prefix)`. Never persist plaintext credentials in session rows, audit, cached responses, or idempotency records. Independent access/refresh hash uniqueness is required; composite pair uniqueness is insufficient. Cross-column uniqueness is unnecessary because types and lookup paths are separate.

Access lifetime is 15 minutes. Refresh-session deadline is fixed at 30 days from creation and does not slide. Rotated access expiry is `min(rotation_time + 15 minutes, refresh_expires_at)`.

Ordinary authentication: parse bearer -> validate access format -> hash/current-session lookup -> reject unknown -> reject revoked -> require ACTIVE User -> require current time strictly before access_expires_at -> resolve principal from stored User/session. Never use a client-supplied user ID as authentication authority. Use an injected UTC clock; mutation decisions use freshly sampled database time rather than stale transaction-start time.

Refresh request is exactly `{"refresh_token":"<refresh credential>"}`: required non-null string length 1–512; schema violations return 422, malformed/wrong-type credential representations return 401 INVALID_REFRESH_TOKEN. No access bearer is required or used. Return 200 CredentialResponse after commit.

Refresh transaction: enforce limits, locate candidate session, lock User then AuthSession, recheck presented digest is still current, recheck ACTIVE status/revocation/deadline, replace **both** digests, update access expiry, preserve refresh deadline, increment rotation_count, set last_rotated_at, append audit, commit, then issue response. Exactly one concurrent refresh wins; a loser returns INVALID_REFRESH_TOKEN without revoking or overwriting the winner. Previous access and refresh credentials become invalid immediately.

No JWT, refresh grace period, or refresh-token family history in B2. Multiple independent sessions per user remain supported.

### 11. Logout

POST `/api/v1/auth/logout` accepts absent body or exactly `{}`; reject JSON null/extra fields. Identify its session using the presented access credential's **currently stored hash**. A recognized non-revoked credential may revoke its own session even if access_expires_at has passed. This expiry exception applies only to logout, never GET/PATCH /me, deactivation, financial routes, or any ordinary protected endpoint.

Missing bearer: 401 AUTH_REQUIRED. Unknown/malformed credential: 401 INVALID_AUTH_TOKEN. Already revoked: 401 SESSION_REVOKED. A rotated-away access token is unknown because its stored hash was replaced. Do not return AUTH_TOKEN_EXPIRED merely because a recognized logout credential expired.

Logout sets revoked_at/reason LOGOUT and required audit for only that session, then returns `200 {"logged_out":true}`. It issues no credentials, extends no expiry, and reactivates nothing. Use a distinct logout-only recognition path; it must not produce a reusable ordinary authenticated-user capability. Recheck the credential under transaction locks so a concurrent rotation cannot authorize logout through a superseded digest.

### 12. /me profile contract

GET `/api/v1/me` has no body/query parameters and returns 200 MeResponse after ordinary unexpired-access validation.

PATCH `/api/v1/me` permits only display_name/timezone, each optional but at least one required; supplied fields must be non-null strings. Phone, status, identity/session internals, and internal IDs are not editable. Apply these same profile validators to signup verification:

- Display name: Unicode NFC; trim outer whitespace; 1–100 Unicode code points; reject control characters and blank/null values; preserve internal spaces and case.
- Timezone: trim outer whitespace; 1–64 characters; resolve through IANA-backed zoneinfo; UTC and valid aliases are accepted; preserve the valid supplied identifier; reject blank/null/unknown values and do not infer timezone from phone country.

Validate all fields before writes; lock/revalidate the ACTIVE user and unexpired session. Actual normalized changes advance updated_at and append PROFILE_UPDATED with changed field names. A normalized no-op returns 200 without changing updated_at or emitting PROFILE_UPDATED. Return MeResponse. B1 has no automatic updated_at update; the service sets it explicitly.

### 13. Deactivation

POST `/api/v1/me/deactivate` accepts absent body or exactly `{}` and requires ordinary unexpired access. Approved terminal CommitmentStatus set: **CLOSED, REJECTED, CANCELLED**. All other current statuses block: DRAFT, PENDING_CONFIRMATION, CONFIRMED, ACTIVE, PARTIALLY_REPAID, FULLY_REPAID, DISPUTED, DEFAULTED. Future/unrecognized statuses block by default.

A commitment blocks if the user is either lender or borrower and status is outside the terminal set. FULLY_REPAID still awaits closure; DEFAULTED is not resolution. Do not invent balance-based exceptions.

In one transaction: lock User; revalidate session and ACTIVE status; verify no blocking commitments; set DEACTIVATED and deactivated_at/updated_at; revoke every non-revoked session with ACCOUNT_DEACTIVATED; append required audit; commit. Return `200 {"status":"DEACTIVATED","deactivated_at":"<UTC timestamp>"}` after commit, despite revocation of the requesting credential.

Preserve phone reservation, AuthIdentity, all financial/history/audit data, and original deactivation timestamp on repeats. Repeating through the revoked credential returns SESSION_REVOKED without another deactivation event. A deactivated account cannot login or refresh. No self-service reactivation in B2. TD-008 remains open beyond this behavior.

All session-issuing operations lock/recheck User so deactivation cannot be followed by issuance based on stale ACTIVE state. Future financial writers that introduce blocking commitments must coordinate through affected User locks in stable UUID order and check account eligibility; this is a later financial-service integration requirement, not permission to implement financial workflows in B2.

### 14. Stable auth errors and response headers

Error JSON is exactly `{"error":{"code":"<stable code>","message":"<safe fixed message>"}}`. Use the approved mappings below; never substitute raw exception/provider text.

| HTTP | Code | Fixed public message |
| --- | --- | --- |
| 400 | MALFORMED_REQUEST | Malformed request. |
| 401 | AUTH_REQUIRED | Authentication is required. |
| 401 | INVALID_AUTH_TOKEN | Invalid access token. |
| 401 | AUTH_TOKEN_EXPIRED | Access token has expired. |
| 401 | INVALID_REFRESH_TOKEN | Invalid refresh token. |
| 401 | REFRESH_TOKEN_EXPIRED | Refresh token has expired. |
| 401 | SESSION_REVOKED | Session has been revoked. |
| 422 | INVALID_PHONE | Enter a valid international phone number. |
| 400 | OTP_INVALID_CHALLENGE | Invalid verification challenge. |
| 400 | OTP_INVALID | Invalid verification code. |
| 400 | OTP_EXPIRED | Verification has expired. Request a new code. |
| 409 | OTP_REPLAYED | Verification has already been used. |
| 409 | OTP_CHALLENGE_UNAVAILABLE | Verification cannot be completed. Request a new code after its expiry. |
| 409 | AUTH_CHALLENGE_BUSY | Verification is already being processed. |
| 429 | OTP_RATE_LIMITED | Too many verification attempts. Try again later. |
| 429 | AUTH_RATE_LIMITED | Too many authentication requests. Try again later. |
| 400 | OTP_DELIVERY_UNAVAILABLE | SMS verification is unavailable for this number. |
| 503 | AUTH_PROVIDER_UNAVAILABLE | Authentication is temporarily unavailable. |
| 409 | AUTH_FLOW_NOT_ALLOWED | This authentication flow cannot be completed. |
| 403 | ACCOUNT_DEACTIVATED | This account is deactivated. |
| 403 | ACCOUNT_UNAVAILABLE | This account is unavailable. |
| 409 | ACCOUNT_HAS_UNRESOLVED_COMMITMENTS | Resolve outstanding commitments before deactivating your account. |
| 422 | VALIDATION_ERROR | Request validation failed. |
| 503 | SERVICE_UNAVAILABLE | Service is temporarily unavailable. |
| 500 | INTERNAL_ERROR | An unexpected error occurred. |

**AUTH_CHALLENGE_CONFLICT is explicitly removed.** Do not retain unused public codes for hypothetical future behavior or replace the removed cross-intent denial with another conflict/busy code.

For structurally valid ordinary credentials, precedence is unknown/current-hash mismatch, revoked session, non-ACTIVE user, then expiry. Logout omits expiry rejection. Retained consumed challenges report replay before expiry. After cleanup, absent rows are unknown, not identifiable as expired/revoked.

Protected 401: `WWW-Authenticate: Bearer`. Rate limits: `Retry-After`. Every B2 response: `Cache-Control: no-store` and sanitized `X-Request-ID`. Preserve these in exception handling instead of flattening auth errors into HTTP_ERROR.

### 15. Enumeration policy

Before successful phone verification, do not reveal account membership/status. Unknown login and existing ACTIVE-account signup use the same post-proof AUTH_FLOW_NOT_ALLOWED result. ACCOUNT_DEACTIVATED/ACCOUNT_UNAVAILABLE may be disclosed only after verified ownership or possession of an otherwise recognized credential. Provider interaction/error differences must not depend on local membership; operational reasons do not enter public messages.

### 16. Audit and logging

Use existing AuditLog (including required object_id). Successful events use result SUCCESS:

| Action | Object | Actor | Metadata allowlist |
| --- | --- | --- | --- |
| AUTH_OTP_VERIFIED | Challenge UUID | Resolved user where appropriate, otherwise null | intent, sanitized request ID |
| ACCOUNT_CREATED | User UUID | New user | sanitized request ID |
| AUTH_SESSION_CREATED | Session UUID | User | intent, sanitized request ID |
| AUTH_SESSION_REFRESHED | Session UUID | User | rotation count, sanitized request ID |
| AUTH_SESSION_REVOKED | Session UUID | User | reason, sanitized request ID |
| PROFILE_UPDATED | User UUID | User | changed field names, sanitized request ID |
| ACCOUNT_DEACTIVATED | User UUID | User | revoked-session count, sanitized request ID |

Post-proof account/intent denial uses AUTH_ACCOUNT_ACCESS_DENIED against the challenge UUID with result DENIED; do not invent a User merely to supply an audit object. State mutation and required audit records commit atomically; audit failure rolls back the mutation.

Operationally log safe categories for invalid/expired/replayed/exhausted/busy challenges, schema/intent mismatch, rate limits, token/session failures, provider timeout/configuration/unavailable/ambiguous outcomes, identity inconsistency, and database failures. Include appropriate safe correlation/actor/object identifiers without sensitive values.

Never log/audit: raw OTP; raw access/refresh credentials; credential hashes; Authorization headers; full phones; raw IPs; Twilio API secrets; unfiltered Twilio requests/responses; signup profile values; credential-bearing bodies; sensitive SQL bind parameters. Prevent leakage through application exceptions, HTTP client logs, SQL logs, and stack traces, not only explicit route logging. Use keyed pseudonymous tags when phone correlation is required; do not log phone suffixes by default.

Accept an incoming request ID only if at most 64 characters drawn from letters, digits, `.`, `_`, `-`; otherwise generate a new ID. Expired-token logout emits the normal session-revocation audit event and never grants unrelated authentication success.

### 17. Retention

Approved cleanup defaults: OTP challenges are deleted 24 hours after expiry; rate-limit buckets 24 hours after their window expires; auth sessions 30 days after refresh_expires_at. Use separately authorized maintenance privileges. Audit logs and financial history are never deleted through B2 auth cleanup. Ordinary runtime least-privilege grants and maintenance permissions must be documented separately from application migrations.

### 18. Dependencies

Approved minimal runtime additions: **httpx**, **phonenumberslite**, **tzdata**. Move the existing development-only HTTPX declaration to runtime as appropriate, avoiding inconsistent duplicate pins. Use standard-library secrets, SHA-256, HMAC, base64url, UUID, Unicode normalization, and zoneinfo/time utilities where applicable. Version pins must be reviewed during implementation.

Do not require the Twilio Python SDK, a JWT library, password hashing, or a Redis client. Do not install dependencies as part of the B2-D2 documentation task.

### 19. File/module policy

Require clear responsibilities, not a mandatory file count. Preserve meaningful boundaries between API, request/response schemas, auth/account orchestration, security/token primitives, provider integration, persistence, and tests. Use the smallest maintainable module set preserving testability/security separation. Do not create trivial pass-through repository/service/maintenance modules solely because earlier planning suggested them.

Integrate with the existing application factory, configuration, error handling, logging, model registration, database sessions, and test fixtures. Keep route handlers thin; services own account/session transactions. Retain ordinary authentication separately from logout-only recognition. Module consolidation must not mix unrelated security responsibilities.

### 20. Required automated test families and gates

| Family | Required coverage |
| --- | --- |
| Signup/login | Valid flows; unknown login creates no account; existing-account signup denial; deactivated/unavailable accounts; current eligibility after proof |
| Input/privacy | Exact request/verify shapes; stored-intent validation; six-digit string/leading zeros; profile validation before provider calls; no pre-proof profile persistence or logging |
| OTP failures | Incorrect, malformed, expired, replayed, exhausted, unavailable proof; no credentials from ambiguous 404 |
| Provider integration | VE SID plus code; API Key SID/Secret; separate signup/login Service SID and routing keys; no master Auth Token requirement; failure normalization; no uncertain automatic POST retry |
| Cross-intent challenges | Same-phone signup/login coexistence and provider independence; same-intent uniqueness/reuse; other-intent state isolation; signup then already-issued login; no AUTH_CHALLENGE_CONFLICT |
| Shared abuse controls | Cross-intent request/verification budgets and phone-wide cooldown; configurable defaults; fixed-window boundaries; HMAC privacy; trusted proxy/IP handling; Retry-After; failure closed |
| Challenge concurrency | Phone-wide advisory locking; one reservation per phone+intent; attempts/expiry not reset; operation ownership, leases, late results, consumed-reference replay prevention |
| Account atomicity | Duplicate/concurrent signup including differing verify-time profiles; one winner; no orphan User/AuthIdentity/AuthSession; audit failure rollback; attempted checks remain counted |
| Tokens/sessions | Independent generation, representation, hashing, no plaintext persistence; access expiry boundaries; revoked/non-ACTIVE/unknown credentials; multiple-device sessions |
| Refresh | Fixed deadline; both credentials rotate; old access/refresh invalidation; one concurrent winner; loser cannot revoke/overwrite winner; lost-response replay cannot recover plaintext |
| Logout | Current/expired recognized credential revokes only itself; unknown/malformed/revoked/rotated-away rejected; no renewal; expiry exception cannot authorize ordinary routes |
| GET/PATCH /me | Safe response fields; authorization; allowed fields only; blank/null/control/timezone rules; normalized no-op versus updated_at/audit change |
| Deactivation | Every current status and future-status default; lender/borrower roles; unrelated commitments; all-session revocation; phone/history preservation; repeat timestamp/event stability; races with session/profile/logout operations and simulated correctly serialized financial writers |
| Audit/logging | Approved events, real object UUIDs, atomic records, safe operational categories, no OTP/token/hash/profile/Twilio-secret/SQL-bind leakage |
| Cleanup | Retention boundaries; eligible auth rows only; no audit/financial deletion; absent-row error behavior |
| Contracts/migrations/regression | Exact seven-endpoint OpenAPI; no register/login aliases; clean migration install; 011 -> 012 with B1 data preserved; constraints/indexes/model agreement including no challenge profile columns and no phone-only uniqueness; full B0/B1 regression |

No automated test may depend on live Twilio SMS. Use deterministic fake providers/clocks and separate database connections for concurrency. Test DB must be distinct from development; schema setup must not depend on test order. Required CI database suites must not pass through wholesale skipping; include contract tests. Run destructive migration round-trips only against the isolated test database during an authorized implementation/test task, never as part of this documentation task.

### 21. Remaining open decisions

**For B2 backend implementation, no architecture decision remains unresolved.** Separate signup/login Verify Services resolve the final provider-isolation issue.

- **TD-008 remains OPEN:** account deletion/anonymization beyond approved B2 deactivation.
- **TD-012 remains OPEN:** mobile/client credential storage implementation.

These intentionally deferred items do not block B2 backend implementation. Real credentials, service provisioning, trusted deployment proxy configuration, and reviewed dependency pins are implementation/deployment inputs, not unresolved B2 architecture decisions.

### 22. Implementation authorization status

**B2 Identity & Authentication architecture: APPROVED FOR IMPLEMENTATION.** Proceed only through bounded B2.x tasks with tests/review gates. Suitable boundaries are contract/config validation; additive persistence; token primitives; shared limits; provider integration; challenge coordination; account creation/login; refresh; logout-only recognition; /me; deactivation; and operational/regression verification. Each state-changing task includes its audit/logging safeguards rather than deferring them to the end.

This decision does not authorize future product scope, financial workflow implementation, or unrelated architecture changes. The B2-D2 task records this contract in DECISIONS.md only; it does not implement B2, modify specification/backend files, create migrations, install dependencies, stage, commit, or push.

## B4-D0 — Approved MVP Connection Lifecycle Contract

- Date: 2026-09-12
- Status: APPROVED founder/product decision; recorded before B4 implementation.
- Scope: B4 — Connections.
- Authority: This explicit founder decision resolves the B4 contract gaps left unspecified by the checked-in Master Product, Tech, Database, API, and AI Build specifications.
- Relationship remains distinct from financial commitment. Connection lifecycle changes must never delete, mutate, or determine authorization for existing financial history.

### 1. Public B4 API surface

Exactly:

POST   /api/v1/connections
GET    /api/v1/connections
GET    /api/v1/connections/{id}
POST   /api/v1/connections/{id}/accept
POST   /api/v1/connections/{id}/reject
POST   /api/v1/connections/{id}/block
DELETE /api/v1/connections/{id}

Do not add search/discovery, unblock, restore, or other connection endpoints in B4.

### 2. Create request

POST /api/v1/connections request body is exactly:

{
  "phone": "+919876543210"
}

Rules:

- phone is a required non-null string
- reject unknown fields
- normalize/validate using the same strict E.164 rules as B2
- authenticated current user is always requester
- client cannot supply requester/current-user ID
- recipient is resolved from an existing ACTIVE Fides account by canonical phone
- unknown, unavailable, or deactivated recipient returns generic:
  404 NOT_FOUND
  "Unavailable resource."
- self-connection returns:
  422 VALIDATION_ERROR
- no public user/contact discovery is introduced

### 3. Connection response

ConnectionResponse contains exactly:

- id
- status
- requester:
  - id
  - display_name
- recipient:
  - id
  - display_name
- created_at
- updated_at

Do not return either participant's phone number through the connection response.

Do not expose:
- AuthIdentity data
- session data
- credential/token data
- financial history
- unrelated profile fields

### 4. Create success and initial state

A successful new request returns:

- HTTP 201
- ConnectionResponse
- status = PENDING
- requester = authenticated actor
- recipient = resolved target user
- server-generated UUID/timestamps

Creation + audit must be atomic.

### 5. List

GET /api/v1/connections:

- returns only relationships where current user is requester or recipient
- response is an array of ConnectionResponse
- order by updated_at descending
- no pagination/filter/query contract in B4 MVP
- unrelated relationships must never be returned

### 6. Detail

GET /api/v1/connections/{id}:

- requester or recipient may read
- unrelated authenticated user receives 404 NOT_FOUND
- missing and unauthorized resources share the same unavailable-resource behavior
- return ConnectionResponse only

### 7. Accept

POST /api/v1/connections/{id}/accept:

Allowed only when:
- actor is recipient
- current status is PENDING

Transition:

PENDING -> ACCEPTED

Results:
- success: 200 ConnectionResponse
- requester attempting accept: 403 FORBIDDEN
- unrelated actor/resource: 404 NOT_FOUND
- wrong current state: 409 INVALID_STATE

Mutation + audit commit atomically.

Accepting creates no commitment or financial record.

### 8. Reject

POST /api/v1/connections/{id}/reject:

Allowed only when:
- actor is recipient
- current status is PENDING

Because the approved connection enum has no REJECTED state:

PENDING -> REMOVED

The persisted relationship row is preserved.

Results:
- success: 200 ConnectionResponse
- requester attempting reject: 403 FORBIDDEN
- unrelated actor/resource: 404 NOT_FOUND
- wrong state: 409 INVALID_STATE

Record semantic audit action:

CONNECTION_REJECTED

Do not hard-delete the connection.

### 9. Block

POST /api/v1/connections/{id}/block:

Either participant may block when status is:

- PENDING
- ACCEPTED

Transition:

PENDING  -> BLOCKED
ACCEPTED -> BLOCKED

BLOCKED is terminal for B4 MVP.

There is no unblock endpoint.

Repeated block or block from REMOVED/BLOCKED returns:

409 INVALID_STATE

Unrelated actor/resource returns:

404 NOT_FOUND

Do not expose which participant initiated a previous block through public error behavior.

Blocking:
- preserves connection row
- preserves commitments
- preserves repayments
- preserves ledger/audit history
- does not alter financial balances
- does not remove lender/borrower authorization to existing commitments

Record:

CONNECTION_BLOCKED

### 10. Remove / DELETE

DELETE /api/v1/connections/{id}

DELETE is a soft relationship-state transition, never a row deletion.

Allowed:

Requester may cancel own PENDING request:

PENDING -> REMOVED

Either participant may remove:

ACCEPTED -> REMOVED

Not allowed:

BLOCKED -> anything
REMOVED -> anything

Those return:

409 INVALID_STATE

Unrelated actor/resource:

404 NOT_FOUND

Successful DELETE returns:

200 ConnectionResponse

Record:

CONNECTION_REMOVED

For recipient rejection of PENDING, use the dedicated reject endpoint and semantic CONNECTION_REJECTED audit.

### 11. Reconnection

REMOVED relationships may later reconnect.

Because the current schema uniquely identifies the pair across statuses, a new POST for a previously REMOVED pair:

- reuses the existing Connection row
- updates requester_user_id to the new authenticated requester
- updates recipient_user_id to the newly resolved recipient
- sets status = PENDING
- advances updated_at
- preserves original created_at
- does not delete historical audit records

This is treated as a new request semantically and records:

CONNECTION_REQUESTED

Do not create a separate RECONNECTED state or audit action.

### 12. Duplicate-pair behavior

The user pair is symmetric for uniqueness purposes.

For an existing pair:

PENDING:
- new POST in either direction -> 409 CONFLICT

ACCEPTED:
- new POST in either direction -> 409 CONFLICT

BLOCKED:
- new POST in either direction -> 409 CONFLICT
- response must not disclose which user blocked

REMOVED:
- allowed to create a new request by reusing the existing row as defined above

The service must prevent duplicate authoritative pair rows during:

- simultaneous A -> B and B -> A requests
- simultaneous A -> B requests
- normal retries/races

Use canonical/symmetric pair coordination.

If the existing schema cannot enforce this safely without migration, implementation must stop and report before creating any migration.

### 13. Idempotency

B4 does not require Idempotency-Key.

The existing API requirement for mandatory idempotency applies to financial mutations.

Connection duplicate protection is provided by pair uniqueness, locking, and lifecycle checks.

Do not silently introduce a new B4 idempotency API contract.

### 14. Audits

Use exactly these semantic connection audit actions:

- CONNECTION_REQUESTED
- CONNECTION_ACCEPTED
- CONNECTION_REJECTED
- CONNECTION_BLOCKED
- CONNECTION_REMOVED

A request after REMOVED records CONNECTION_REQUESTED again.

State mutation and audit commit atomically.

Audit failure rolls back the connection mutation.

Do not store unnecessary phone/profile PII, tokens, credential hashes, or Authorization data in audit metadata.

### 15. Stable error mapping

Use the existing stable error vocabulary:

- unrelated/missing protected connection:
  404 NOT_FOUND

- authenticated participant lacks the required actor role for the requested action:
  403 FORBIDDEN

- invalid lifecycle transition/repeated terminal action:
  409 INVALID_STATE

- duplicate/colliding active pair creation:
  409 CONFLICT

- self-connection or request schema violation:
  422 VALIDATION_ERROR

- malformed JSON:
  400 MALFORMED_REQUEST

- unexpected internal/database failure:
  safe generic 500/SERVICE_UNAVAILABLE according to existing backend conventions

Do not invent a new connection-specific public error code.

### 16. Financial separation invariant

Connection lifecycle must never:

- create a Commitment
- alter a Commitment
- delete a Commitment
- delete Repayment or Verification history
- delete LedgerEvent/AuditLog records
- grant access to unrelated financial records
- revoke lender/borrower access to an existing commitment

Financial authorization continues to derive from direct commitment participation under B3, not current connection status.

### 17. B4 implementation boundary

B4 implements only:

- connection create
- list
- detail
- accept
- reject
- block
- remove
- reconnection from REMOVED
- required connection audits
- authorization/concurrency/API tests

B4 does not implement:

- commitments
- terms/installments
- repayments
- verification
- ledger APIs
- extensions
- notifications
- trust graph
- user/contact discovery
- unblock workflow
- payments

## B5-D0 — Approved MVP Currency Contract

- Date: 2026-09-13
- Status: APPROVED founder/product decision before B5 implementation.
- Scope: B5+ financial records, calculations, repayments, summaries and clients.
- Intent: Allow Fides to serve users in India, the US and the UK at MVP launch without introducing foreign-exchange conversion or mixed-currency financial logic.

### 1. Supported MVP currencies

The only currencies enabled for new MVP commitments are:

- INR — Indian Rupee
- USD — United States Dollar
- GBP — Pound Sterling

Currency values use uppercase ISO 4217 codes.

Do not accept arbitrary ISO currencies merely because the database field is currency-agnostic.

Additional currencies require a later explicit product decision and tests.

### 2. One currency per commitment

Every Commitment has exactly one explicit currency.

A single commitment must never contain amounts in more than one currency.

Examples:

Valid:
- INR 10,000 commitment
- USD 250 commitment
- GBP 80 commitment

Invalid:
- principal in USD with installment amounts in GBP
- repayment in INR against USD commitment
- combining USD and GBP into one commitment

### 3. Money representation

Persist money using integer minor units.

For the three MVP currencies:

- INR: 100 paise = 1 INR
- USD: 100 cents = 1 USD
- GBP: 100 pence = 1 GBP

Do not use floating-point values for authoritative money.

Examples:

- INR 1,250.50 -> 125050 minor units
- USD 250.00 -> 25000 minor units
- GBP 80.75 -> 8075 minor units

The backend remains authoritative for monetary calculations.

### 4. Repayment currency

Every repayment must use exactly the same currency as its parent Commitment.

If:

Commitment.currency = USD

then:

Repayment.currency must = USD

Any mismatch must return the approved CURRENCY_MISMATCH behavior.

No repayment may convert between currencies.

### 5. Terms and installments

All monetary fields associated with a Commitment inherit that Commitment's currency.

This includes, where applicable:

- principal
- installment amounts
- repayment amounts
- interest-derived monetary amounts
- outstanding amounts
- ledger monetary events

Terms/installments may not introduce a second currency.

### 6. No FX conversion

The MVP performs no:

- foreign-exchange conversion
- exchange-rate lookup
- historical FX calculation
- real-time FX calculation
- settlement across currencies
- currency conversion during repayment

Fides records each financial obligation in its original currency.

There is no authoritative exchange-rate service in MVP.

### 7. No cross-currency netting

Commitments in different currencies remain financially independent.

Example:

User owes:
- INR 10,000
- USD 200

Fides must NOT calculate:

"Total owed = INR X"

or:

"Total owed = USD Y"

No FX-derived combined balance is authoritative.

### 8. Summary behavior

Where totals contain multiple currencies, results must remain separated by currency.

Conceptually:

borrowed:
- INR: 1000000 minor
- USD: 20000 minor
- GBP: 5000 minor

Do not add unlike currencies together.

Exact B12 API response schemas will be finalized when Summary APIs are implemented.

B5 must not invent the B12 response contract early.

### 9. Net position

Net position is calculated independently per currency.

For example:

INR:
- lent INR 20,000
- borrowed INR 5,000
- net INR +15,000

USD:
- lent USD 100
- borrowed USD 300
- net USD -200

Do not combine INR and USD net positions.

### 10. Client display

Mobile and web may display the appropriate human-facing symbols:

- INR -> ₹
- USD -> $
- GBP -> £

The ISO currency code remains authoritative in API/database records.

Clients must not infer financial meaning from the symbol alone.

### 11. International use

Currency support does not alter account identity.

Users may create any supported-currency Commitment regardless of their phone-number country or configured timezone.

Do not infer:

- Indian phone -> INR only
- US phone -> USD only
- UK phone -> GBP only

The commitment creator selects an allowed currency under the approved B5 contract.

### 12. No automatic default based on location

Backend financial behavior must not depend on:

- IP geolocation
- phone country
- device locale
- App Store region

A client may later suggest a convenient default for UX, but the selected and confirmed currency is explicit and server-validated.

### 13. Immutability of commitment currency

Once a Commitment is created, its currency must not be changed in place.

Changing currency would represent a different financial obligation.

Do not implement a PATCH-style currency mutation.

If a currency was entered incorrectly, resolution must occur through the approved cancellation/replacement/audit flow defined by commitment lifecycle rules rather than rewriting financial history.

### 14. Future compatibility

The storage architecture remains currency-agnostic.

Future currencies may be added through explicit product/technical decisions.

Future FX support, if ever added, must be a separate derived/conversion layer and must not rewrite original commitment/repayment currency records.

Potential future currencies such as EUR, AED, SGD, CAD, AUD, JPY, etc. are NOT enabled merely by this decision.

### 15. B5 implementation boundary

B5 should:

- allow exactly INR/USD/GBP
- persist explicit currency
- validate supported currency
- preserve currency on commitment
- reject unsupported currency
- prepare downstream financial records to inherit the commitment currency

B5 should NOT:

- implement FX
- implement currency conversion
- aggregate different currencies
- implement B12 summary schemas
- add location-based currency assumptions

## B5-D1 — Commitment Creation & Lifecycle Contract

Date: 2026-09-13
Status: APPROVED founder/product decision
Scope: B5 Commitments only

### 1. Public B5 API surface

Exactly:

POST /api/v1/commitments
GET /api/v1/commitments
GET /api/v1/commitments/{id}
POST /api/v1/commitments/{id}/confirm
POST /api/v1/commitments/{id}/reject
POST /api/v1/commitments/{id}/cancel

Deferred from B5:
- POST /api/v1/commitments/{id}/activate
- GET /api/v1/commitments/{id}/terms
- GET /api/v1/commitments/{id}/installments
- GET /api/v1/commitments/{id}/ledger

No commitment PATCH or DELETE route in B5.

### 2. Create request

POST /api/v1/commitments

Body exactly:

{
  "connection_id": "uuid",
  "actor_role": "BORROWER" | "LENDER",
  "type": "IOU" | "PEER_LOAN",
  "principal_amount_minor": integer,
  "currency": "INR" | "USD" | "GBP",
  "description": string | null
}

Closed schema. No extra fields.

The authenticated creator is always one financial participant.

The other participant is derived from the supplied Connection.

Do NOT accept:
- arbitrary borrower user id
- arbitrary lender user id
- phone number
- separate counterparty user id

### 3. Direction

actor_role is relative to the authenticated creator.

If actor_role = BORROWER:
- current user = borrower
- other Connection participant = lender

If actor_role = LENDER:
- current user = lender
- other Connection participant = borrower

Either participant may propose:
- “I borrowed”
- “I lent”

Creator must always be one of the stored borrower/lender participants.

### 4. Commitment types

Enabled immediately in B5:

- IOU
- PEER_LOAN

No additional type is enabled.

B5 does not attach different lifecycle behavior to these types yet unless already required by approved specifications.

### 5. Connection eligibility for creation

A new Commitment proposal requires:

- existing Connection
- authenticated creator is a participant in that Connection
- Connection.status = ACCEPTED
- both affected accounts currently eligible/active

Creation through:

- PENDING
- BLOCKED
- REMOVED

is not allowed.

Missing/unrelated Connection:
404 NOT_FOUND
message: "Unavailable resource."

Known participant using non-ACCEPTED Connection:
409 INVALID_STATE

New proposal creation must coordinate with current account eligibility using the established affected-user locking rules.

### 6. Existing commitment access after Connection changes

Once a Commitment exists:

- lender/borrower participation is the source of financial authorization
- blocking/removing the Connection does NOT revoke financial read access
- no Commitment history is deleted
- no Commitment is re-parented
- no Commitment is merged

For an existing PENDING_CONFIRMATION Commitment after the Connection becomes BLOCKED or REMOVED:

- proposer may cancel
- required counterparty may reject
- confirmation is NOT allowed unless the Connection is currently ACCEPTED

This restriction applies only to activating a still-pending proposal.

### 7. Principal amount

Public field:

principal_amount_minor

Rules:

- required
- true JSON integer only
- booleans rejected
- floats rejected
- numeric strings rejected
- > 0
- maximum:
  1,000,000,000,000 minor units

Invalid principal amount returns:

422 INVALID_AMOUNT

No floating-point authoritative money.

### 8. Currency

B5-D0 remains authoritative.

Exactly:

- INR
- USD
- GBP

Uppercase only.

Do not silently normalize:
- inr
- usd
- gbp

Unsupported or malformed currency returns:

422 VALIDATION_ERROR

Currency is immutable after Commitment creation.

No FX.

### 9. Description

Field:

description

Rules:

- optional
- nullable
- string when supplied
- trim surrounding whitespace
- maximum 500 characters
- empty or whitespace-only becomes null

Description is immutable in bounded B5 because no edit/PATCH workflow is approved.

### 10. Initial TermsVersion

Creation must satisfy the existing atomic initial-terms requirement.

B5 creates:

- Commitment
- initial TermsVersion
- ledger event
- audit event
- successful idempotency result

in one transaction.

The bounded B5 initial TermsVersion represents:

- principal-only obligation
- no interest
- no due date
- no installment schedule

B5 creates NO installments.

B6 will add/finalize:
- due-date behavior
- interest
- schedules
- installments
- deterministic term calculations
- term version changes

B5 must not invent B6 financial behavior.

### 11. Initial status

No public DRAFT workflow in MVP B5.

Creation persists directly as:

PENDING_CONFIRMATION

created_at and updated_at are set.

confirmed_at = null
activated_at = null
closed_at = null

### 12. Confirmation

Only the required counterparty may confirm.

The creator may NOT confirm their own proposal.

Valid source state:

PENDING_CONFIRMATION

Connection must currently be ACCEPTED at confirmation time.

Confirmation logically performs:

PENDING_CONFIRMATION
→ CONFIRMED
→ ACTIVE

inside one atomic transaction.

Final persisted state returned:

ACTIVE

Set:

confirmed_at
activated_at

in the same transaction.

CONFIRMED remains a valid persisted enum/state for future compatibility, but no externally callable separate activation step exists in bounded B5.

No separate COMMITMENT_ACTIVATED event is emitted in B5.

### 13. Rejection

Only the required counterparty may reject.

Valid source state:

PENDING_CONFIRMATION

Transition:

PENDING_CONFIRMATION → REJECTED

REJECTED is terminal for B5.

Reject remains allowed even if the Connection later becomes BLOCKED or REMOVED.

No reason field in B5.

### 14. Cancellation

Only the original proposer/creator may cancel.

Valid source state:

PENDING_CONFIRMATION

Transition:

PENDING_CONFIRMATION → CANCELLED

CANCELLED is terminal for B5.

Cancel remains allowed even if the Connection later becomes BLOCKED or REMOVED.

Confirmed/ACTIVE Commitments may NOT be cancelled through B5.

No cancellation reason field in B5.

No hard deletion.

### 15. Terminal lifecycle behavior

For bounded B5:

REJECTED = terminal
CANCELLED = terminal

ACTIVE cannot return to PENDING_CONFIRMATION.

No reopening endpoint exists.

Later repayment states belong to B7/B8+.

### 16. Read authorization

GET /api/v1/commitments
GET /api/v1/commitments/{id}

are authorized only by direct borrower/lender participation.

A Connection alone never grants financial-history access.

Missing or unrelated Commitment:

404 NOT_FOUND
message: "Unavailable resource."

Both lender and borrower may read their Commitment regardless of later Connection removal/blocking.

### 17. List behavior

GET /api/v1/commitments

Returns only Commitments where authenticated actor is:

- lender OR
- borrower

Includes all lifecycle states.

Ordering:

updated_at DESC
then id as deterministic tie-breaker

No pagination in bounded B5.
No filtering in bounded B5.

### 18. Commitment response schema

Expose exactly:

- id
- connection_id
- type
- status
- principal_amount_minor
- currency
- description
- borrower:
  - id
  - display_name
- lender:
  - id
  - display_name
- creator:
  - id
  - display_name
- created_at
- updated_at
- confirmed_at
- activated_at

Do NOT expose:

- phone numbers
- auth identities
- session/token data
- trust data
- unrelated profile fields
- unrelated financial history

### 19. Lifecycle actor errors

Error precedence for protected Commitment actions:

1. missing/unrelated resource:
   404 NOT_FOUND

2. authenticated participant but wrong lifecycle actor:
   403 FORBIDDEN

3. correct actor but invalid current state:
   409 INVALID_STATE

Creator attempting to confirm/reject own proposal:
403 FORBIDDEN

Counterparty attempting proposer-only cancellation:
403 FORBIDDEN

### 20. Idempotency requirement

Required on every B5 mutation:

- create
- confirm
- reject
- cancel

Header:

Idempotency-Key

Allowed format:

1–128 characters

Allowed characters:

A-Z
a-z
0-9
.
_
:
-

Missing or malformed Idempotency-Key:

400 MALFORMED_REQUEST

Same authenticated actor + same operation/resource + same normalized request + same key:

return original completed logical HTTP status/body

Same scope/key with different normalized request:

409 IDEMPOTENCY_CONFLICT

In-flight duplicate where no completed result is available:

409 CONFLICT

Completed successful financial mutation results are retained for 30 days.

Do not cache:

- schema validation failures
- authentication failures
- authorization failures

Replay must re-establish authenticated actor identity and must never expose another user's stored response.

### 21. Request hashing

Hash the validated/normalized logical request together with:

- authenticated actor identity
- operation identity
- resource identity where applicable

Normalization occurs after schema validation.

Do not hash secrets or Authorization headers into persisted metadata.

### 22. Concurrency

Lifecycle mutations must use authoritative database state inside the transaction.

Required race behavior:

- double confirm
- confirm vs reject
- confirm vs cancel
- reject vs cancel
- concurrent same-key request

Exactly one valid lifecycle outcome may commit.

Loser must re-read authoritative state after locking.

No duplicate:

- Commitment
- TermsVersion
- ledger event
- audit entry
- successful idempotency result

Use documented locking order compatible with B2 user coordination, B3 financial authorization and B4 connection mutation behavior.

### 23. Event catalog

Exact semantic event/action names:

COMMITMENT_PROPOSED
COMMITMENT_CONFIRMED
COMMITMENT_REJECTED
COMMITMENT_CANCELLED

Use the corresponding semantic name for:

- ledger event
- audit action

COMMITMENT_PROPOSED must NOT imply verified or active debt.

COMMITMENT_CONFIRMED represents confirmation + activation in bounded B5.

No COMMITMENT_ACTIVATED event in B5.

### 24. Atomicity

Every successful B5 mutation must atomically commit all required effects.

Create:

- Commitment
- initial TermsVersion
- COMMITMENT_PROPOSED ledger event
- COMMITMENT_PROPOSED audit log
- completed idempotency result

Confirm:

- Commitment lifecycle/timestamps
- COMMITMENT_CONFIRMED ledger event
- COMMITMENT_CONFIRMED audit log
- completed idempotency result

Reject:

- Commitment lifecycle
- COMMITMENT_REJECTED ledger event
- COMMITMENT_REJECTED audit log
- completed idempotency result

Cancel:

- Commitment lifecycle
- COMMITMENT_CANCELLED ledger event
- COMMITMENT_CANCELLED audit log
- completed idempotency result

Failure in any required component rolls back the entire mutation.

### 25. Pending proposal expiry

No automatic proposal expiry in MVP.

No abandonment scheduler.

A pending proposal remains PENDING_CONFIRMATION until:

- counterparty confirms
- counterparty rejects
- proposer cancels

### 26. B5 error contract

Use existing standard envelope.

Required mappings:

401 AUTH_REQUIRED
403 FORBIDDEN
404 NOT_FOUND
409 INVALID_STATE
409 CONFLICT
409 IDEMPOTENCY_CONFLICT
422 INVALID_AMOUNT
422 VALIDATION_ERROR
400 MALFORMED_REQUEST

CURRENCY_MISMATCH remains defined for downstream same-Commitment currency mismatches, especially repayments, but is not normally produced by initial Commitment creation.

Safe generic internal failures remain existing 500/SERVICE_UNAVAILABLE behavior.

### 27. Scope exclusions

B5 must NOT implement:

- repayment reporting
- repayment verification
- user-defined interest
- interest calculations
- due-date calculations
- installment generation
- extension workflow
- notifications
- summary APIs
- FX
- currency conversion
- payment movement
- trust score/profile
- trust graph
- AI assistant

### 28. Schema/migration policy

Current audit found no mandatory migration.

B5 should use the existing schema where safe.

If implementation discovers behavior that cannot be safely satisfied without schema change:

STOP
report the exact limitation
do NOT create a migration without explicit approval.

## B6-D0 — Terms, Interest & Installment Contract

Date: 2026-09-13
Status: APPROVED founder/product decision
Scope: B6 Terms & Installments

### 1. Terms entry point

Extend the existing:

POST /api/v1/commitments

with one optional closed `terms` object.

Existing B5 fields remain unchanged.

Optional terms object:

{
  "due_date": "YYYY-MM-DD" | null,
  "interest_type": "NONE" | "SIMPLE_FIXED",
  "interest_rate_bps": integer | null,
  "grace_period_days": integer,
  "installment_dates": ["YYYY-MM-DD", ...] | null
}

If `terms` is omitted, preserve B5 behavior:

- no interest
- no due date
- no installments
- grace period 0

Existing B5-created commitments must not be silently modified.

### 2. No B6 terms-edit endpoint

B6 introduces no independent:

- POST terms
- PATCH terms
- PUT terms

Initial terms are part of Commitment creation.

Once created, the initial TermsVersion is immutable.

Before confirmation, correcting incorrect terms requires:

cancel proposal -> create corrected proposal

ACTIVE term amendments are not implemented in B6.

Negotiated due-date changes belong to B10 Extensions and must create a new TermsVersion rather than overwrite history.

### 3. Interest modes

Allowed publicly in B6:

- NONE
- SIMPLE_FIXED

SIMPLE_FIXED means:

A flat fixed percentage of the original Commitment principal for the entire obligation.

It is NOT:

- annualized
- daily accruing
- monthly accruing
- declining-balance interest
- compound interest
- penalty interest
- interest-on-interest

### 4. Interest rate representation

Field:

interest_rate_bps

Meaning:

100 basis points = 1.00%

Examples:

500 = 5.00%
1250 = 12.50%

Rules:

If interest_type = NONE:
- interest_rate_bps must be null

If interest_type = SIMPLE_FIXED:
- interest_rate_bps required
- true integer only
- minimum 1
- maximum 10000

Maximum public fixed interest = 100.00%.

### 5. Interest calculation

All calculations use integer arithmetic.

Let:

P = principal_amount_minor
R = interest_rate_bps

For NONE:

interest_minor = 0

For SIMPLE_FIXED:

interest_minor = round_half_up(P * R / 10000)

Implement deterministically using integer arithmetic:

interest_minor = (P * R + 5000) // 10000

Do not use floating-point authoritative money.

Total obligation:

total_obligation_minor =
principal_amount_minor + interest_minor

### 6. Schedule modes

Exactly three B6 arrangements exist.

A. No deadline

due_date = null
installment_dates = null

No installment rows.

B. Single due date

due_date = YYYY-MM-DD
installment_dates = null

No installment rows.

C. Installment schedule

due_date = null
installment_dates = [date1, date2, ...]

Installment rows are generated.

Do not allow both due_date and installment_dates simultaneously.

### 7. Installment schedule validation

For installment schedules:

- minimum 2 installments
- maximum 60 installments
- dates explicitly supplied by client
- dates strictly increasing
- duplicate dates prohibited
- no automatic weekly/monthly frequency generator in B6
- no custom installment amounts in B6

B6 generates amounts server-side.

### 8. Equal-principal allocation

Let:

P = principal
N = installment count

q = P // N

For installments 1 through N-1:

principal_amount_minor = q

Final installment:

principal_amount_minor =
P - q * (N - 1)

Remainder goes to final installment.

Require every installment total_due_minor > 0.

### 9. Interest allocation across installments

If total interest I > 0:

iq = I // N

For installments 1 through N-1:

interest_amount_minor = iq

Final installment:

interest_amount_minor =
I - iq * (N - 1)

For each installment:

total_due_minor =
principal_amount_minor + interest_amount_minor

Required reconciliation:

sum(installment principal) = Commitment principal

sum(installment interest) = authoritative total interest

sum(installment total) = authoritative total obligation

No minor units may be lost.

### 10. Currency

Terms/installments inherit Commitment currency.

Exactly the B5-D0 approved currencies remain:

- INR
- USD
- GBP

No second currency in terms or installments.

No FX.

### 11. Contractual timezone

The contractual due-date timezone is:

the borrower's configured timezone at Commitment creation.

Snapshot this value into the TermsVersion schedule metadata.

Later profile timezone changes must NOT change an existing contractual deadline.

One TermsVersion has one contractual timezone.

All installment deadlines in that version use the same timezone.

### 12. End-of-day semantics

A due date remains valid through the end of that local calendar date.

Server boundary semantics:

the obligation becomes past-due at the start of the following calendar day in the contractual timezone.

Do not implement the deadline as a fabricated 23:59:59.999999 timestamp.

Timezone/DST handling must use proper calendar/timezone semantics.

### 13. Past/today/future dates

Allow:

- past due dates
- today's date
- future due dates

This supports recording existing IOUs/loans that may already be overdue.

B6 does NOT automatically implement OVERDUE or DEFAULTED lifecycle behavior.

Those classifications belong to later approved logic.

### 14. Grace period

Field:

grace_period_days

Rules:

- true integer
- default 0
- minimum 0
- maximum 365

Meaning:

Grace period does NOT:

- alter the contractual due date
- alter interest
- rewrite terms

It only delays the point at which later overdue logic considers the obligation/installment overdue.

Example:

due_date = 2026-10-10
grace_period_days = 3

Contractual due date remains 2026-10-10.

Overdue eligibility begins after the end of 2026-10-13 in the contractual timezone.

B6 stores/defines this rule.
Later notifications/summaries consume it.

### 15. TermsVersion authority

TermsVersion rows are immutable.

Authoritative current terms are:

the highest version_no with effective_at <= evaluation time.

B6 itself creates only version 1 at Commitment creation.

No future-effective TermsVersion creation in bounded B6.

No current_terms_id column is required.

B10 may later create version 2+ after approved extension behavior.

### 16. B6 read API

Exactly:

GET /api/v1/commitments/{id}/terms

GET /api/v1/commitments/{id}/installments

No additional public B6 write route.

### 17. Terms response

GET /api/v1/commitments/{id}/terms returns a closed object containing:

- commitment_id
- currency
- current_terms_version_id
- versions

Versions ordered:

version_no ASC

Each version exposes:

- id
- version_no
- effective_at
- due_date
- interest_type
- interest_rate_bps
- grace_period_days
- schedule_mode
- due_timezone
- installment_dates
- created_by:
  - id
  - display_name
- created_at

Do NOT expose raw internal schedule_definition JSON.

### 18. Installment response

GET /api/v1/commitments/{id}/installments

Returns installments for the current TermsVersion only.

Order:

sequence_no ASC

Each installment exposes:

- id
- terms_version_id
- sequence_no
- due_date
- principal_amount_minor
- interest_amount_minor
- total_due_minor
- currency
- status
- created_at
- updated_at

No phone/auth/session/trust/unrelated profile data.

### 19. Authorization

Authorize B6 reads through the parent Commitment.

Only direct borrower/lender participants may read terms/installments.

Connection membership alone grants no access.

Later Connection BLOCKED/REMOVED state does not revoke financial read access.

Missing/unrelated Commitment:

404 NOT_FOUND
"Unavailable resource."

### 20. Creation atomicity

When terms are supplied during Commitment creation, the existing B5 mutation atomically creates:

- Commitment
- initial TermsVersion
- installments if schedule exists
- COMMITMENT_PROPOSED ledger event
- COMMITMENT_PROPOSED audit event
- completed idempotency result

The ledger proposal event references the TermsVersion.

Failure in any required effect rolls back the entire Commitment creation.

### 21. Idempotency

No separate B6 idempotency endpoint exists.

The existing B5 POST /commitments idempotency policy remains authoritative.

The validated/normalized terms object becomes part of the create request hash.

Same key + same normalized complete request:
replay original logical result

Same scoped key + changed terms:
IDEMPOTENCY_CONFLICT

### 22. B10 boundary

B6 does NOT implement:

- extensions
- renegotiation
- replacement of active schedules
- arbitrary term amendments
- version 2+ writes after activation

These belong to B10 or later approved workflows.

### 23. Explicit B6 exclusions

Do NOT implement:

- repayments
- repayment verification
- FX
- currency conversion
- payment movement
- automatic frequency schedule generation
- custom installment amounts
- compound interest
- declining-balance interest
- annualized/time-accruing interest
- penalty interest
- extension workflow
- overdue/default state transitions
- notifications
- summaries
- trust features
- AI

### 24. Migration rule

The B6 audit did not establish a mandatory migration for this bounded contract.

Use existing schema where safe.

If implementation cannot safely satisfy this approved contract without schema change:

STOP
report exact limitation
do NOT create a migration without approval.

## FUTURE-FIN-D0 — Mutual Settlement / Waiver Requirement

Date: 2026-09-13
Status: APPROVED founder/product requirement; exact implementation contract DEFERRED to B7–B9 design
Scope: Future MVP repayment/outstanding/closure behavior

### 1. Product requirement

Fides MVP must support mutually agreed closure of an active financial Commitment even when verified outstanding is greater than zero.

This represents a voluntary agreement between borrower and lender to settle/forgive/waive the unpaid remainder.

### 2. Mutual consent mandatory

Neither party may unilaterally erase or waive the remaining obligation through this feature.

One financial participant proposes the settlement.

The other financial participant must explicitly approve it.

Until both sides agree, authoritative outstanding remains unchanged.

### 3. Never fake repayment

A waived/forgiven amount must NEVER be represented as:

- a repayment
- a verified repayment
- money transferred
- money received

Fides must preserve the distinction between:

repaid amount

and:

waived/settled amount

### 4. Financial history preservation

Mutual settlement must NOT rewrite:

- original principal
- original terms
- verified repayments
- repayment verification history
- previous ledger events

History remains append-only/auditable.

### 5. Required settlement record

The eventual implementation must persist or otherwise authoritatively record at minimum:

- Commitment
- proposer
- approving counterparty
- verified outstanding immediately before settlement
- amount waived/settled
- timestamps
- resulting closure
- ledger/audit history

Exact schema/API representation is intentionally NOT approved yet.

### 6. Closure result

After both parties approve a valid mutual settlement:

- remaining approved unpaid obligation is considered waived/settled by agreement
- Commitment may transition to CLOSED
- no fake repayment is generated
- historical outstanding/repaid/waived values remain distinguishable

### 7. Fully repaid versus mutually settled

Fides must preserve the semantic distinction between:

A. fully repaid commitment

and

B. commitment closed with some amount waived/forgiven

Future Trust Profile / behavioral analytics must be capable of distinguishing these outcomes.

Do not treat mutually settled as identical to fully repaid.

### 8. Relationship to previous zero-outstanding rule

Existing specifications currently state that normal settlement/closure occurs only when authoritative verified obligation reaches zero.

FUTURE-FIN-D0 introduces an explicit approved exception:

A Commitment may also close with non-zero verified outstanding ONLY through the future mutually approved settlement/waiver workflow.

Normal automatic/full-repayment closure still requires zero outstanding.

### 9. Lifecycle direction

Conceptually the future flow may include:

ACTIVE / PARTIALLY_REPAID
-> settlement proposed
-> counterparty approval
-> CLOSED

The exact persisted state model, including whether a dedicated SETTLEMENT_PENDING state is needed, is NOT approved yet.

Do not add states or migrations now.

### 10. Implementation timing

Do NOT implement this in B6.

Before B7/B8/B9 closure/outstanding implementation is finalized:

- audit current schema
- define exact API
- define settlement proposal/approval roles
- define idempotency
- define concurrency behavior
- define ledger/audit events
- define cancellation/rejection of settlement request
- define effect on outstanding calculation
- determine whether schema migration is necessary

No implementation agent may silently invent these rules.


## B7-D0 — Repayment Reporting Contract

Date: 2026-09-15
Status: APPROVED founder/product decision
Scope: B7 Repayment Reporting

### 1. Public B7 routes

Implement exactly:

POST /api/v1/commitments/{id}/repayments
GET  /api/v1/commitments/{id}/repayments
GET  /api/v1/repayments/{id}

No B8 verify/dispute routes are implemented in B7.

### 2. Reporter permissions

Either direct financial participant may report a repayment:

- borrower may report “I paid”
- lender may report “I received”

The other participant becomes the required future B8 verifier.

Unrelated users:
404 NOT_FOUND

Connection membership alone grants no repayment access.

### 3. Eligible commitment states

Repayment reporting is allowed only when Commitment status is:

- ACTIVE
- PARTIALLY_REPAID

Reject reporting in every other state, including:

- PENDING_CONFIRMATION
- REJECTED
- CANCELLED
- FULLY_REPAID
- CLOSED
- DISPUTED
- DEFAULTED

with:

409 INVALID_STATE

B7 does not itself create PARTIALLY_REPAID or FULLY_REPAID transitions.

### 4. Connection-state independence

Once an active Commitment exists, repayment reporting does not depend on the current Connection state.

BLOCKED or REMOVED connection does not revoke financial reporting access for existing commitments.

Current authenticated account eligibility still applies.

### 5. Repayment create request

Closed schema:

{
  "amount_minor": integer,
  "currency": "INR" | "USD" | "GBP",
  "payment_date": "YYYY-MM-DD",
  "note": string | null
}

No client-supplied:

- commitment_id in body
- reporter ID
- repayment status
- verification state
- balance/outstanding
- installment ID
- terms version ID
- verifier ID

### 6. Amount validation

amount_minor:

- required
- true JSON integer
- booleans rejected
- floats rejected
- numeric strings rejected
- must be > 0
- must not exceed transactionally computed reportable_remaining

Invalid type/range:
422 INVALID_AMOUNT

Over-capacity:
409 OVER_REPAYMENT

### 7. Currency

currency is required explicitly.

Allowed:
- INR
- USD
- GBP

Must exactly equal parent Commitment currency.

No lowercase normalization.

Mismatch:
422 CURRENCY_MISMATCH

No FX.

### 8. Payment date

payment_date is required DATE semantics.

Allow:
- past dates
- today

Reject:
- future dates

“Today” is evaluated using the reporting user’s configured timezone at submission time.

Persist the exact supplied calendar date.

Do not timezone-convert the stored payment_date.

Malformed date:
422 VALIDATION_ERROR

### 9. Note

note:

- optional
- nullable
- string only
- trim surrounding whitespace
- blank -> null
- max 500 characters

No structured payment method/reference/evidence fields in bounded B7.

Do not overload note as a hidden structured storage format.

TD-005 / cash evidence remains deferred.

### 10. Initial repayment status

Every successfully reported repayment starts as:

PENDING_VERIFICATION

Always.

B7 never auto-verifies a repayment.

### 11. Reported != verified

PENDING_VERIFICATION repayments:

- remain auditable
- do not reduce verified outstanding
- do not change Commitment repayment status
- do not imply money has been verified

DISPUTED and CANCELLED repayments likewise do not count as verified repayment.

### 12. Authoritative obligation

At transaction evaluation time:

P = original Commitment principal

T = highest TermsVersion with:
effective_at <= evaluation time

For NONE:

I = 0

For SIMPLE_FIXED:

I = (P * interest_rate_bps + 5000) // 10000

Authoritative obligation:

O = P + I

Use current effective B6 terms.

Do not add installment totals to O because installments represent allocation of the same obligation.

Grace period does not change O.

### 13. Verified outstanding

V =
sum(amount_minor)
for repayment rows of the Commitment
whose current status is VERIFIED

verified_outstanding = O - V

Pending, disputed, and cancelled repayments do not reduce verified_outstanding.

If persisted data produces impossible corruption such as V > O:
fail safely rather than silently clamp.

### 14. Prepayment

Allow repayment reporting against the full remaining obligation even if scheduled installment dates are in the future.

No installment-maturity cap.

No early-payment interest rebate.

No interest recalculation for early payment in MVP.

### 15. No installment allocation in B7

Repayments are commitment-level records only.

B7 does NOT:

- allocate repayment to installments
- add repayment-to-installment foreign keys
- update installment statuses
- implement payment waterfalls
- auto-match reported amounts to installments

Do not create a migration for installment allocation.

### 16. Pending reporting-capacity reservation

Pending repayment reports reserve reporting capacity without reducing verified outstanding.

Define:

O = authoritative total obligation

V =
sum VERIFIED repayments

Q =
sum PENDING_VERIFICATION repayments

reportable_remaining =
O - V - Q

Accept a new report only when:

0 < amount_minor <= reportable_remaining

This means pending reports may collectively equal, but never exceed, current verified outstanding.

A pending report does NOT become verified merely because it reserves capacity.

### 17. Pending full-balance report behavior

If a PENDING_VERIFICATION report reserves all remaining capacity:

new repayment reports are rejected with OVER_REPAYMENT until capacity is released by a later approved workflow.

B7 does not invent:

- pending expiry
- repayment cancellation
- automatic verification
- automatic capacity release

Those belong to later approved behavior.

### 18. Commitment lifecycle on report

Reporting a repayment does NOT change Commitment status.

B7 does not transition to:

- PARTIALLY_REPAID
- FULLY_REPAID
- CLOSED

Those transitions depend on later verification/outstanding behavior.

### 19. FUTURE-FIN-D0 boundary

Do NOT implement mutual settlement/waiver in B7.

No:
- settlement table
- settlement state
- settlement endpoint
- waived amount field
- fake repayment for waived value

Future waived amount must remain distinct from repaid amount.

Do not introduce an invariant that CLOSED always means fully repaid.

### 20. Repayment response

Exact closed response fields:

- id
- commitment_id
- reported_by:
  - id
  - display_name
- amount_minor
- currency
- payment_date
- reported_at
- status
- note
- created_at

Do not expose:

- phone
- auth/session data
- idempotency internals
- verification internals
- raw outstanding
- unrelated profile information

### 21. Repayment list

GET /api/v1/commitments/{id}/repayments

Return all repayment statuses visible to the direct participants.

Order:

reported_at DESC
then id ASC

No filtering in B7.
No pagination in B7.
No repayments -> [].

### 22. Individual repayment read

GET /api/v1/repayments/{id}

Only direct participants of the parent Commitment may access it.

Missing/unrelated:
404 NOT_FOUND
"Unavailable resource."

Access survives Connection BLOCKED/REMOVED state.

### 23. Ledger event

Successful report appends:

REPAYMENT_REPORTED

Ledger event includes at minimum:

- commitment_id
- repayment_id
- reporter actor
- amount
- currency
- current terms_version reference
- occurrence time
- repayment status / explicit unverified semantics

The event must never imply verification.

### 24. Audit action

Use exact action name:

REPAYMENT_REPORTED

Audit records:

- repayment object
- actor
- result
- timestamp
- sanitized request correlation metadata

Do not store note/free-text evidence in audit/log metadata.

### 25. Atomicity

Successful POST repayment commits atomically:

- Repayment
- REPAYMENT_REPORTED ledger event
- REPAYMENT_REPORTED audit event
- completed idempotency result

Failure in any required step rolls back all effects.

No orphan repayment/event/audit/idempotency result.

### 26. Idempotency

POST repayment requires Idempotency-Key.

Reuse the approved B5 financial-write contract:

Format:
1–128 chars

Allowed chars:
A-Z
a-z
0-9
.
_
:
-

Missing/malformed:
400 MALFORMED_REQUEST

Same actor + operation/resource + normalized request + key:
return original completed status/body

Same scope/key + changed normalized request:
409 IDEMPOTENCY_CONFLICT

Concurrent in-flight same-key request:
409 CONFLICT

Successful results retained for 30 days.

Do not cache schema/auth/authz failures.

Replay must reauthenticate and reauthorize the protected parent resource.

Replay returns the original completed logical response and does not re-run current capacity/state checks.

### 27. Repayment idempotency FK policy

For bounded B7:

leave repayments.idempotency_key_id NULL / unused.

Reason:
the current idempotency row may be expired/reused under existing retention behavior, so a durable FK could later misrepresent original causality.

The idempotency result itself remains authoritative for replay.

Do not create a migration or retention redesign in B7.

### 28. Actor/error precedence

After authentication and schema validation:

1. missing/unrelated resource
   -> 404 NOT_FOUND

2. participant lacking approved action permission
   -> 403 FORBIDDEN

3. wrong Commitment state
   -> 409 INVALID_STATE

4. currency mismatch
   -> 422 CURRENCY_MISMATCH

5. invalid financial amount
   -> 422 INVALID_AMOUNT where applicable

6. amount exceeds reportable capacity
   -> 409 OVER_REPAYMENT

Preserve existing safe generic internal errors.

### 29. Public errors

At minimum:

401 AUTH_REQUIRED
403 FORBIDDEN
404 NOT_FOUND
409 INVALID_STATE
409 OVER_REPAYMENT
409 CONFLICT
409 IDEMPOTENCY_CONFLICT
422 CURRENCY_MISMATCH
422 INVALID_AMOUNT
422 VALIDATION_ERROR
400 MALFORMED_REQUEST

### 30. Concurrency and locking

Preserve existing lock ordering.

For mutation:

1. validate/normalize request and key
2. acquire scoped idempotency advisory lock
3. acquire affected User locks in UUID order
4. revalidate account/session eligibility
5. authorize and lock parent Commitment
6. re-read current Commitment state
7. read authoritative current TermsVersion
8. compute VERIFIED aggregate
9. compute PENDING_VERIFICATION aggregate
10. validate currency and reportable_remaining
11. insert repayment
12. append ledger
13. append audit
14. persist completed idempotency result
15. commit

Do not perform external network calls inside the transaction.

Different-key concurrent repayment reports must serialize through the Commitment lock so their aggregate pending capacity cannot exceed the approved obligation.

### 31. Account/state races

After waiting for locks:

current database state wins.

Tests must cover:

- reporter account deactivation
- counterparty/account eligibility where required by current financial invariants
- Commitment state change
- same-key concurrent requests
- different-key competing reports

Do not rely on stale pre-lock state.

### 32. No migration rule

The bounded B7 contract requires no migration.

If implementation discovers that the approved contract cannot safely be satisfied without a schema change:

STOP.
Report the exact blocker.
Do not create a migration without approval.

### 33. Explicit B7 exclusions

Do NOT implement:

- repayment verification
- repayment dispute decisions
- verification history APIs
- repayment cancellation endpoint
- automatic pending expiry
- settlement/waiver
- extension workflow
- notification delivery
- summary endpoints
- installment allocation
- structured method/reference/evidence
- payment movement
- FX
- overdue/default transitions
- trust features
- AI


## B8-D0 — Repayment Verification & Dispute Contract

Date: 2026-09-19
Status: APPROVED founder/product decision
Scope: B8 Repayment Verification / Dispute / Verification History

### 1. Public B8 routes

Implement exactly:

POST /api/v1/repayments/{id}/verify
POST /api/v1/repayments/{id}/dispute
GET  /api/v1/repayments/{id}/verification-history

No generic decision endpoint.
No individual verification-detail endpoint.

### 2. Verifier authorization

Only the direct participant who did NOT report the repayment may verify or dispute it.

Therefore:

- borrower reports payment -> lender decides
- lender reports receipt -> borrower decides

The original reporter can never verify or dispute their own report.

Missing/unrelated protected resource:
404 NOT_FOUND
"Unavailable resource."

A direct participant who is not the required decision actor:
403 FORBIDDEN

Connection BLOCKED/REMOVED does not revoke financial access to an existing commitment.

### 3. Account eligibility

For a normal B8 decision, both commitment participants must remain ACTIVE.

The acting verifier must also satisfy current authentication/session eligibility.

If persisted data violates these financial-account invariants:
fail safely rather than inventing recovery behavior.

### 4. Whole-report decisions only

No partial verification.

A repayment decision applies to the entire reported amount.

Allowed transitions:

PENDING_VERIFICATION -> VERIFIED
PENDING_VERIFICATION -> DISPUTED

No partially verified amount is stored or derived.

### 5. One successful decision per repayment

Only PENDING_VERIFICATION may be decided.

Bounded B8 allows exactly one successful decision for the original report.

Do NOT allow:

- DISPUTED -> VERIFIED
- VERIFIED -> DISPUTED
- reopen
- reconsideration
- reversal
- decision on CANCELLED repayment

A later correction must use a new auditable report/workflow rather than rewriting the original decision.

### 6. Verification history

Every successful verify/dispute appends exactly one RepaymentVerification row.

B8 history product contract allows one successful decision row per repayment.

Exact history response element:

{
  "id": "uuid",
  "repayment_id": "uuid",
  "decided_by": {
    "id": "uuid",
    "display_name": "string"
  },
  "decision": "VERIFIED" | "DISPUTED",
  "decision_note": "string|null",
  "decided_at": "UTC RFC3339 timestamp"
}

Both direct participants may read history.

Missing/unrelated repayment:
404 NOT_FOUND

No history:
[]

Ordering:
decided_at ASC
then id ASC

No pagination.
No filtering.
No history update/delete routes.

Do not expose:
- phone
- auth/session data
- idempotency internals
- unrelated profiles
- unrelated financial records

Current display_name is a current profile projection, not a historical name snapshot.

### 7. Decision note

Both verify and dispute use the same closed request body:

{
  "decision_note": "Optional note"
}

Allow:
{}

Allow:
{
  "decision_note": null
}

Rules:
- optional
- nullable
- strict string or null
- trim surrounding whitespace
- blank -> null
- maximum 500 characters after trimming

No:
- structured reason codes
- evidence uploads
- payment method/reference
- client decision timestamp
- client actor
- client repayment/commitment IDs
- client decision/status
- client balance/outstanding
- client terms-version reference

Schemas are closed.

### 8. Eligible parent Commitment states

Verify/dispute allowed only when the parent Commitment status is:

- ACTIVE
- PARTIALLY_REPAID

Every other Commitment state:
409 INVALID_STATE

### 9. Verification-time authoritative obligation

VERIFY uses the current effective B6 TermsVersion at verification time.

Under the locked parent Commitment:

P = original principal

T =
highest TermsVersion version_no
where effective_at <= verification evaluation time

For NONE:
I = 0

For SIMPLE_FIXED:
I = (P * interest_rate_bps + 5000) // 10000

O = P + I

V =
sum amount_minor
for currently VERIFIED repayments of this Commitment

verified_outstanding =
O - V

The candidate PENDING_VERIFICATION repayment is not included in V until successful verification.

B7 report-time terms_version provenance does NOT freeze verification-time entitlement.

### 10. Verification amount rule

Before VERIFY succeeds:

repayment.amount_minor <= current verified_outstanding

must hold.

If candidate amount exceeds current verified outstanding:
409 OVER_REPAYMENT

B7 pending reservation does not remove this verification-time recheck.

Grace period does not change O or verification amount.

### 11. Pending-capacity effects

Let candidate repayment amount = a.

On VERIFY:

V -> V + a
Q -> Q - a

Verified outstanding decreases by a.

On DISPUTE:

V unchanged
Q -> Q - a

Verified outstanding remains unchanged.
Reporting capacity increases by a.

No separate persisted "capacity release" row is required.

These effects are derived from repayment.status.

### 12. Corruption / amended-terms behavior

For VERIFY:

- if V > O -> fail safely
- if candidate amount > O - V -> 409 OVER_REPAYMENT
- if repayment/status/history persistence is inconsistent -> fail safely

For DISPUTE:

Do NOT require V + Q <= O.

Do NOT reuse B7 reporting_capacity() as a dispute precondition.

DISPUTE may release the repayment's pending reservation even if later approved/future terms changes or inconsistent pending reservations mean V + Q > O.

Reason:
DISPUTE does not create verified credit and must not trap an invalid pending reservation.

However, corrupted repayment/status/history association still fails safely.

### 13. Commitment lifecycle on successful VERIFY

After successful verification, derive resulting verified outstanding.

If parent before = ACTIVE
and resulting verified outstanding > 0:
-> PARTIALLY_REPAID

If parent before = PARTIALLY_REPAID
and resulting verified outstanding > 0:
-> PARTIALLY_REPAID

If parent before = ACTIVE or PARTIALLY_REPAID
and resulting verified outstanding = 0:
-> FULLY_REPAID

Single full repayment may transition:

ACTIVE -> FULLY_REPAID

Do not force an intermediate PARTIALLY_REPAID state.

Update Commitment.updated_at when status changes.

DISPUTE does not change Commitment status.

Do not infer Commitment DISPUTED from a disputed repayment.

### 14. FULLY_REPAID is distinct from CLOSED

B8 stops at:

FULLY_REPAID

Do NOT automatically transition to CLOSED.

Leave closed_at unchanged in B8.

Do not establish:

CLOSED == fully repaid

Future mutual settlement may close an obligation with waived amount, and repaid versus waived accounting must remain distinct.

### 15. No installment allocation

B8 remains Commitment-level only.

Do NOT:
- allocate verified repayment to installments
- mutate installment statuses
- implement waterfall logic
- cap verification by installment maturity
- infer paid installments

### 16. Mutation response

Both:

POST /verify
POST /dispute

return:

200

with the exact existing B7 RepaymentResponse:

- id
- commitment_id
- reported_by:
  - id
  - display_name
- amount_minor
- currency
- payment_date
- reported_at
- status
- note
- created_at

Do not embed:
- updated Commitment
- verified outstanding
- verification-history record
- idempotency internals
- auth/session data

Clients may refetch the authoritative Commitment and verification history.

### 17. Idempotency

VERIFY and DISPUTE are idempotent financial writes.

Require Idempotency-Key.

Reuse approved B5/B7 contract:

Key:
1–128 chars

Allowed:
A-Z
a-z
0-9
.
_
:
-

Missing/malformed:
400 MALFORMED_REQUEST

Scope:
actor + exact operation/endpoint + repayment resource + key

Same scope + same normalized request:
return original completed status/body

Same scope/key + changed request:
409 IDEMPOTENCY_CONFLICT

Concurrent same-scope in-flight:
409 CONFLICT

Successful results retained 30 days.

Do not cache failed schema/auth/authz/state/financial requests.

Replay:
- reauthenticate
- reauthorize protected repayment/action
- return original completed response
- do NOT rerun pending-state or financial eligibility checks

VERIFY and DISPUTE may reuse the same textual key because operation scopes differ.

No new verification-idempotency FK.

Do not use Repayment.idempotency_key_id for B8.

Any idempotency helper adaptation must preserve existing B5/B7 endpoint strings, hashes and replay behavior exactly.

### 18. Locking / concurrency

Preserve global lock ordering.

Mutation order:

1. validate/normalize body and key
2. acquire scoped idempotency advisory lock
3. discover participant IDs without treating snapshot as authoritative
4. lock affected Users in UUID order
5. revalidate current account/session eligibility
6. authorize and lock parent Commitment
7. lock Repayment
8. reread parent association, reporter, actor role and states
9. validate repayment/history consistency
10. for VERIFY, select current TermsVersion and calculate authoritative outstanding
11. append RepaymentVerification row
12. update Repayment status
13. update Commitment status if VERIFY requires it
14. append ledger event
15. append audit event
16. persist completed idempotency result
17. commit

Parent Commitment must be locked before Repayment.

B7 reporting and B8 decisions share the same parent Commitment lock discipline.

Expected races:

verify vs dispute:
one succeeds; loser rereads and rejects

verify vs verify:
one financial effect

dispute vs dispute:
one effect

report vs verify/dispute:
serialized through parent Commitment lock

future terms amendment vs B8:
serialized through parent Commitment lock

account deactivation:
User locks coordinate; current database eligibility wins

Connection block/remove:
does not revoke financial access and must not introduce Connection-lock dependency

### 19. Ledger events

Approve exact event names:

REPAYMENT_VERIFIED
REPAYMENT_DISPUTED

REPAYMENT_VERIFIED includes:

- commitment_id
- repayment_id
- verifier actor
- amount
- currency
- verification-history ID
- resulting repayment status
- verification-time terms_version_id
- resulting verified outstanding
- resulting Commitment status
- occurrence timestamp

REPAYMENT_DISPUTED includes:

- commitment_id
- repayment_id
- deciding actor
- reported amount
- currency
- verification-history ID
- resulting repayment status
- occurrence timestamp

Do NOT attach a fresh verification-time TermsVersion to DISPUTE because no monetary verification calculation is applied.

Do not store decision-note/evidence text in ledger payload.

Neither event means Fides moved money.

### 20. Audit events

Use exact action names:

REPAYMENT_VERIFIED
REPAYMENT_DISPUTED

Object:

object_type = Repayment
object_id = repayment UUID

Include:
- actor
- SUCCESS result
- server timestamp
- sanitized request correlation metadata

Exclude decision_note/evidence/free text from audit metadata.

### 21. Atomicity

A successful B8 mutation atomically commits all required effects:

- RepaymentVerification row
- Repayment status
- Commitment status update if applicable
- ledger event
- audit event
- completed idempotency result

Failure at any required step rolls back all effects.

No orphan or partially applied verification/dispute state.

### 22. Error contract

After authentication/schema validation and protected-resource lookup:

Missing repayment / unrelated user:
404 NOT_FOUND

Reporter attempts counterparty-only action:
403 FORBIDDEN

Invalid parent Commitment state:
409 INVALID_STATE

DISPUTED repayment receives another decision:
409 INVALID_STATE

CANCELLED repayment receives a decision:
409 INVALID_STATE

Already VERIFIED repayment receives a new decision:
409 ALREADY_VERIFIED

VERIFY candidate amount exceeds current eligible verified outstanding:
409 OVER_REPAYMENT

Invalid decision_note/schema:
422 VALIDATION_ERROR

Missing/malformed Idempotency-Key or malformed JSON:
400 MALFORMED_REQUEST

Same key, changed normalized request:
409 IDEMPOTENCY_CONFLICT

Same-scope operation in flight:
409 CONFLICT

Corrupt authoritative financial/history state:
existing safe generic 500/503 behavior

Preserve B7 reporting-specific OVER_REPAYMENT wording.

B8 gets verification-specific OVER_REPAYMENT wording.

Error precedence:

1. unavailable resource
2. wrong action role
3. repayment / parent current state
4. financial verification validation

Do not leak state or amounts to unrelated users.

### 23. No migration / dependency rule

Bounded B8 requires no migration.

Do NOT add:

- uniqueness constraint
- verification.updated_at
- current_verification_id
- version column
- verification idempotency FK
- verification terms_version_id
- new dependency

Single successful decision is enforced transactionally through:
- parent lock
- repayment lock
- PENDING_VERIFICATION state guard
- atomic history/status update

If implementation discovers that this approved contract cannot safely be satisfied without a migration or dependency change:

STOP.
Report the exact blocker.
Do not invent or apply the migration/dependency change.

### 24. History immutability

Verification history is append-only in application behavior.

No B8 update/delete route or service behavior may modify/delete an existing successful RepaymentVerification record.

Database-level immutability hardening may be handled later and is not a B8 migration requirement.

### 25. FUTURE-FIN-D0 compatibility

B8 must preserve:

- verified repayment != waived amount
- disputed repayment != waived amount
- CLOSED does not imply fully repaid
- no fake VERIFIED repayment representing waiver
- disputed report/history may remain present if a future mutual settlement closes remaining obligation
- no settlement endpoints/states/tables/fields in B8

### 26. Explicit B8 exclusions

Do NOT implement:

- partial verification
- reopen/reconsideration
- reversal
- repayment cancellation
- dispute-resolution workflow after DISPUTED
- structured evidence
- evidence upload
- payment method/reference
- installment allocation
- automatic CLOSED
- mutual settlement/waiver
- extension workflow
- notification workflow
- summary/dashboard calculations
- overdue/default transitions
- payment movement
- FX
- Trust Score / Trust Graph
- AI


## B9-D0 — Ledger / Audit / Commitment Timeline Contract

Date: 2026-09-20
Status: APPROVED founder/product decision
Scope: B9 Ledger / Audit / Commitment Timeline

### 1. Financial authority

Domain tables remain authoritative for current financial state.

LedgerEvent is:
- immutable historical evidence
- an auditable commitment timeline
- a reconciliation aid

LedgerEvent is NOT:
- the authoritative outstanding calculator
- a replacement for Commitment / TermsVersion / Repayment / verification state
- a general event-sourcing reconstruction engine for current state

Do not calculate current outstanding by summing ledger amounts.

### 2. Canonical public route

Implement exactly:

GET /api/v1/commitments/{id}/ledger

Do NOT add:
/api/v1/commitments/{id}/history

No alias.

This explicitly resolves the existing Tech/API route conflict in favor of /ledger.

### 3. B9 public scope

B9 exposes Commitment-scoped ledger history only.

Do NOT implement:
- global user activity
- dashboard recent-activity endpoint
- individual ledger-event endpoint
- public AuditLog endpoint
- operator/admin audit endpoint

### 4. Public representation

Do NOT expose raw LedgerEvent ORM/storage rows.

Public API returns a safe projected timeline with closed, event-specific schemas.

Do NOT expose:
- raw event_payload
- created_at
- audit metadata
- request IDs
- object_type/result
- storage-only fields
- arbitrary JSON keys
- idempotency internals

### 5. Supported B9 event types

Expose exactly these current event types:

COMMITMENT_PROPOSED
COMMITMENT_CONFIRMED
COMMITMENT_REJECTED
COMMITMENT_CANCELLED
REPAYMENT_REPORTED
REPAYMENT_VERIFIED
REPAYMENT_DISPUTED

Do not rename historical events.

Do NOT synthesize:
COMMITMENT_CREATED
COMMITMENT_ACTIVATED
or any other artificial historical event.

### 6. Future event visibility

Future approved:
- terms changes
- extension events
- settlement events

may join the same timeline only after their own event contracts are approved.

Initial B6 TermsVersion remains represented through COMMITMENT_PROPOSED terms_version_id.

Do not create a synthetic initial-terms event in B9.

### 7. Response envelope

Use exactly:

{
  "items": [],
  "next_cursor": null
}

Each item has common fields:

{
  "id": "<event UUID>",
  "commitment_id": "<Commitment UUID>",
  "event_type": "<approved event code>",
  "actor": {
    "id": "<User UUID>",
    "display_name": "<current display name>"
  },
  "occurred_at": "<UTC RFC3339>",
  "details": {}
}

actor may be null only for a future explicitly approved system event.

All current seven event writers are expected to have participant actors.

### 8. Actor projection

Project actor as current:

{
  "id": "...",
  "display_name": "..."
}

Do NOT create historical display-name snapshots.

If the user later changes display_name, historical events display the current name.

### 9. Closed event-specific details

Use a discriminated union keyed by event_type.

COMMITMENT_PROPOSED details:
- status
- terms_version_id

COMMITMENT_CONFIRMED details:
- status = ACTIVE

COMMITMENT_REJECTED details:
- status = REJECTED

COMMITMENT_CANCELLED details:
- status = CANCELLED

REPAYMENT_REPORTED details:
- repayment_id
- terms_version_id
- amount_minor
- currency
- status = PENDING_VERIFICATION

REPAYMENT_VERIFIED details:
- repayment_id
- verification_id
- terms_version_id
- amount_minor
- currency
- status = VERIFIED
- resulting_verified_outstanding_minor
- resulting_commitment_status

REPAYMENT_DISPUTED details:
- repayment_id
- verification_id
- amount_minor
- currency
- status = DISPUTED

Amounts remain integer minor units.

Currencies remain:
INR
USD
GBP

### 10. Historical-result semantics

Historical event output uses values captured at event time.

For example:
REPAYMENT_VERIFIED resulting_verified_outstanding_minor and resulting_commitment_status are historical resulting values.

Do NOT recompute old event output from today's current TermsVersion or current Commitment state.

### 11. Reference integrity

Before exposing projected references, validate:

- event.commitment_id matches requested Commitment
- referenced Repayment belongs to the same Commitment
- referenced TermsVersion belongs to the same Commitment
- verification_id resolves to the projected Repayment where used
- actor reference is valid
- no payload reference points to an unrelated resource

Do not trust arbitrary IDs from JSON payload.

Malformed/cross-parent known event data must fail safely.

### 12. Authorization

Both direct Commitment participants may read the Commitment ledger.

Missing Commitment:
404 NOT_FOUND
"Unavailable resource."

Unrelated user:
same 404 NOT_FOUND response.

Connected-but-unrelated user:
not authorized.

Connection BLOCKED/REMOVED:
does not revoke existing financial-history access.

CLOSED Commitment:
history remains readable to currently eligible authenticated participants.

Account deactivation:
- records remain preserved
- deactivated user does not receive an authentication exception
- eligible counterparty retains access

### 13. Timeline ordering

Order by:

occurred_at ASC
then id ASC

This is deterministic event-time ordering.

Do NOT claim:
- strict causal ordering
- commit ordering
- UUID chronological semantics

UUID is only the deterministic tie-break.

### 14. Pagination

Use keyset pagination.

Request:

GET /api/v1/commitments/{id}/ledger?limit=50&cursor=<opaque-cursor>

Rules:
- default limit = 50
- maximum limit = 100
- positive integer only
- no offset pagination
- no filters in bounded B9
- cursor is opaque
- cursor contains validated version / Commitment / ordering-position state
- cursor never grants authorization
- every page request independently authenticates and authorizes the path Commitment

Response:

{
  "items": [...],
  "next_cursor": "<opaque string|null>"
}

Empty authorized timeline:

{
  "items": [],
  "next_cursor": null
}

Invalid limit or cursor:
422 VALIDATION_ERROR

### 15. Pagination consistency

B9 provides live keyset pagination.

It does NOT guarantee a frozen point-in-time snapshot across multiple page requests.

Do not add:
- snapshot IDs
- timeline sessions
- cross-page database snapshot guarantees

If new earlier-timestamp data becomes visible between requests, client refresh may be required.

### 16. Unsupported / malformed event behavior

Known event type with malformed stored payload:
503 SERVICE_UNAVAILABLE

Unsupported historical event_type:
503 SERVICE_UNAVAILABLE

Do NOT:
- silently omit
- return raw event
- expose arbitrary payload
- invent generic fallback

For MVP, readers for a new event type must be deployed before that event writer is enabled.

### 17. Payload evolution

Do NOT add:
- schema_version column
- event enum migration
- payload version column

For MVP use:
- stable semantic event names
- validated closed event-specific projection schemas
- explicit future decisions for incompatible changes

Never change the historical meaning of an existing event code.

### 18. Ledger semantic/privacy rules

Do not expose or newly store through B9:
- decision_note
- evidence
- free-form financial notes
- phone numbers
- display-name snapshots
- raw request bodies
- auth credentials
- tokens
- idempotency keys
- secrets

REPAYMENT_DISPUTED amount represents the disputed reported amount.

It is NOT:
- verified repayment credit
- waived amount

No current event means Fides moved or held money.

### 19. LedgerEvent versus AuditLog

LedgerEvent:
- domain/financial meaning
- Commitment history
- user-visible only through safe timeline projection

AuditLog:
- separate internal action/security/administrative trail
- actor
- object
- result
- sanitized correlation metadata

Do not merge these concepts.

### 20. Audit public exposure

AuditLog remains internal.

Do NOT implement:
- public AuditLog route
- admin/operator audit route
- audit timeline mixed into Commitment ledger

Tests should verify that no B9 public audit resource exists.

### 21. Failed-action auditing

Do NOT introduce universal durable financial-failure AuditLog rows in B9.

Preserve existing behavior:
- current B5–B8 successful financial mutations audit SUCCESS
- already-approved B2 denial auditing remains unchanged
- existing sanitized operational logging remains unchanged

Any broader failed-financial-attempt auditing policy is deferred.

### 22. Audit privacy

Do NOT copy into AuditLog metadata:
- decision_note
- evidence
- raw request body
- auth token
- credential hash
- Authorization header
- idempotency key
- raw IP

Sanitized request_id remains permitted.

Do not add in B9:
- endpoint/path/method metadata
- user-agent
- raw IP

### 23. Application append-only behavior

B9 must preserve:
- no ledger update service
- no ledger delete service
- no audit update service
- no audit delete service
- no public mutation endpoint for either resource

B9 must never rewrite historical LedgerEvent or AuditLog rows.

### 24. Production DB-role immutability boundary

Production/staging runtime roles must ultimately be restricted to:

SELECT
INSERT

on ledger/audit tables.

B9 does NOT provision or alter runtime DB grants.

DB role provisioning/verification remains in later security/infrastructure hardening, targeted for B14.

Do not add triggers or grant migrations in B9.

### 25. Existing persistence model is canonical

Retain current LedgerEvent model:
- string event_type
- commitment_id
- actor_user_id
- amount_minor
- currency
- repayment_id
- terms_version_id
- JSONB event_payload
- occurred_at
- created_at

Retain current AuditLog model:
- actor_user_id
- string action
- object_type
- object_id
- result
- JSONB metadata
- created_at

Do not introduce older Tech-spec sketches:
- database event enum
- generic source_id
- entity_* rename
- before/after snapshots
- dedicated request_id column

No schema reconciliation migration.

### 26. Index policy

Do NOT add a new index in bounded B9.

Specifically do not add:

(commitment_id, occurred_at, id)

at this time.

Existing indexes are accepted for MVP Commitment-scoped history.

If measured performance later requires an index:
obtain separate migration approval.

### 27. Idempotency / replay

B9 is read-only and adds no idempotency behavior.

Existing B5–B8 retained idempotent replay must continue to create zero duplicate ledger/audit rows.

Do NOT add heuristic timeline deduplication.

After idempotency result expiry, genuinely newly executed allowed business actions remain separate events according to current domain rules.

### 28. Atomicity

Existing writers continue to atomically commit:

domain mutation
+ LedgerEvent
+ AuditLog
+ completed idempotency result where applicable

Failed or rolled-back financial mutations must never expose a partial successful ledger event.

B9 timeline reads only committed rows.

### 29. Terms provenance

Preserve:

COMMITMENT_PROPOSED
-> initial TermsVersion reference

REPAYMENT_REPORTED
-> report-time TermsVersion reference

REPAYMENT_VERIFIED
-> verification-time TermsVersion reference

REPAYMENT_DISPUTED
-> no fresh verification-time TermsVersion reference

Do not replace one historical provenance reference with another.

Do not duplicate full TermsVersion snapshots into LedgerEvent JSON in B9.

The existing authorized TermsVersion API remains the detailed terms-history resource.

### 30. FUTURE-FIN-D0 compatibility

Preserve:

waived amount != verified repayment
CLOSED != fully repaid
DISPUTED != verified

Future settlement history must remain capable of distinguishing:
- pre-settlement verified outstanding
- waived amount
- resulting closure

B9 does NOT define or implement settlement persistence/API.

Never represent waiver using REPAYMENT_VERIFIED.

### 31. Future extension compatibility

B9 does not define:
- extension event names
- extension payloads
- extension FK
- extension API

These remain B10 decisions.

Existing LedgerEvent JSONB/reference structure must not be altered in a way that prevents future approved extension events.

### 32. HTTP behavior

GET /api/v1/commitments/{id}/ledger uses:

- Bearer authentication
- Cache-Control: no-store
- sanitized X-Request-ID
- existing safe exception handling

No Idempotency-Key required.

Missing/unrelated Commitment remains:
404 NOT_FOUND

No participant-role 403 for collection access.

### 33. No migration / dependency rule

Bounded B9 requires:
- no migration
- no new index
- no new dependency
- no event enum
- no sequence number
- no payload-version column
- no display-name snapshot field
- no generic source FK

If safe implementation unexpectedly requires any of those:
STOP.
Report the exact blocker.
Do not invent or apply it.

### 34. Explicit B9 exclusions

Do NOT implement:
- B10 extension workflow
- actual terms amendments
- settlement/waiver
- global user activity
- dashboard recent activity endpoint
- summaries
- notifications
- overdue/default
- Trust Score
- Trust Graph
- AI
- payment movement/custody
- FX
- public audit endpoint
- admin audit UI/API
- financial-history deletion
- anonymization policy
- retention-period policy
- new legal/privacy policy
- DB-role provisioning
- schema migration
- dependency change


## B10-D0 — Due-Date Extension Contract

Date: 2026-09-20
Status: APPROVED founder/product decision
Scope: B10 Due-Date Extension Workflow

### 1. Scope

B10 supports only due-date extension for Commitments whose current effective TermsVersion uses a single due date.

Allowed change:

existing single due date
-> strictly later single due date

B10 is NOT a general terms-amendment engine.

Do NOT implement:
- no-deadline -> deadline conversion
- installment schedule changes
- adding/removing installments
- grace-period changes
- interest-type changes
- interest-rate changes
- principal changes
- currency changes
- lender/borrower changes
- settlement/waiver
- overdue/default behavior

### 2. Canonical API routes

Implement exactly:

POST /api/v1/commitments/{id}/extension-requests
GET  /api/v1/commitments/{id}/extension-requests

POST /api/v1/extension-requests/{id}/accept
POST /api/v1/extension-requests/{id}/reject

No aliases.

These routes explicitly override conflicting older Tech-spec route spellings.

Do NOT add:
- /extensions
- /approve
- individual extension GET
- generic decision endpoint
- cancellation endpoint

### 3. Requester / decision authorization

Either direct Commitment participant may create an extension request.

Borrower may request.
Lender may request.

The requester may NOT accept or reject their own request.

Only the other direct participant may decide.

Requester self-decision:
403 FORBIDDEN

Missing/unrelated Commitment or ExtensionRequest:
404 NOT_FOUND
"Unavailable resource."

Connection BLOCKED/REMOVED does not revoke existing financial access.

### 4. Account eligibility

For request creation and acceptance:

- both Commitment participants must be ACTIVE
- acting user must satisfy current authentication/session eligibility

For rejection:

- acting deciding counterparty must satisfy current authentication/session eligibility
- request must remain part of an existing direct financial relationship

Do not invent a deactivated-user authentication exception.

### 5. Eligible Commitment states

Request creation and acceptance are allowed only when parent Commitment status is:

ACTIVE
PARTIALLY_REPAID

Do NOT allow creation/acceptance when parent is:

PENDING_CONFIRMATION
FULLY_REPAID
CLOSED
REJECTED
CANCELLED

Invalid parent state:
409 INVALID_STATE

The current due date does NOT need to have been reached.

Requests may be made:
- before current due date
- after current due date

No overdue/default engine is introduced.

### 6. Date rule

requested_due_date must be strictly later than the base/current contractual due date.

Equal date:
invalid

Earlier date:
invalid

Later date:
valid

There is NO separate rule requiring requested_due_date to be after today's date.

Compare contractual calendar dates directly.

Do not reinterpret the old due date using the requester's current profile timezone.

### 7. Single-date schedule only

The current effective TermsVersion must represent a single-date schedule.

Do NOT allow B10 on:
- no-deadline schedules
- installment schedules

Unsupported current schedule mode:
409 INVALID_STATE

Do not create, update, delete, renumber, or allocate Installment rows.

### 8. One pending request per Commitment

At most one ExtensionRequest with status REQUESTED may exist for one Commitment at a time.

Competing request creation:
409 CONFLICT

Enforce transactionally using the parent Commitment lock.

Do NOT add a DB uniqueness constraint.

After a request becomes:
ACCEPTED
or
REJECTED

a new request may later be created if the Commitment remains eligible.

### 9. Extension lifecycle

Bounded B10 allows only:

REQUESTED -> ACCEPTED
REQUESTED -> REJECTED

Do NOT implement:
- cancellation route
- expiration
- automatic expiry
- reopen
- reconsideration
- reversal

The existing CANCELLED enum remains unused by bounded B10.

Do not invent behavior for CANCELLED.

### 10. Pending request after parent becomes ineligible

If a REQUESTED extension exists and parent Commitment becomes ineligible before decision:

ACCEPT:
409 INVALID_STATE

REJECT:
remains allowed if the deciding counterparty is currently eligible.

Reason:
rejection does not amend authoritative financial terms and may cleanly resolve the stale workflow.

### 11. Create request body

Exact closed body:

{
  "requested_due_date": "YYYY-MM-DD",
  "reason": "Optional explanation"
}

Rules:

requested_due_date:
- required
- non-null
- strict YYYY-MM-DD calendar date

reason:
- optional
- nullable
- strict string or null
- trim surrounding whitespace
- blank -> null
- maximum 500 characters after trimming

Reject unknown fields.

Do NOT accept client-supplied:
- requester ID
- actor ID
- status
- base terms ID
- current/previous due date
- decision actor
- timestamps
- interest fields
- grace
- schedule fields
- principal
- currency

### 12. Accept / reject bodies

Accept body:

{}

Reject body:

{}

Require a JSON object under existing mutation request conventions.

Reject unknown fields.

No decision note.

No client timestamp.

No client actor/status/resource fields.

### 13. Base TermsVersion capture

At request creation, server stores immutable request context in ExtensionRequest.requested_terms:

{
  "base_terms_version_id": "<uuid>"
}

This is server-generated only.

Do not accept base_terms_version_id from the client.

The historical previous due date is derived from this immutable base TermsVersion.

Do NOT add a dedicated database column.

### 14. Stale-base protection

At acceptance time:

stored base_terms_version_id

must equal:

current effective TermsVersion ID

under the locked parent Commitment.

If not:
409 CONFLICT

Do NOT silently rebase a stale extension request to newer terms.

### 15. TermsVersion creation

Successful ACCEPT must create exactly one new immutable TermsVersion.

Proposal:
creates no TermsVersion.

Rejection:
creates no TermsVersion.

New TermsVersion:

version_no =
max existing version_no for this Commitment + 1

effective_at =
server acceptance time

created_by_user_id =
accepting counterparty

Copy unchanged fields from base TermsVersion, including:
- interest_type
- interest_rate_bps
- grace_period_days
- schedule metadata
- contractual due timezone
- all other unchanged approved TermsVersion fields

Change only:
due_date = requested_due_date

Old TermsVersions remain immutable.

### 16. Immediate effectiveness

Accepted extension becomes effective immediately at server acceptance time.

Do NOT support:
- future-dated extension activation
- scheduled activation

Current terms remain selected as:

highest version_no
where effective_at <= evaluation time

### 17. Repayment interaction

Pending repayment reports do NOT block extension request creation or acceptance.

Because bounded B10 changes only due date:

O unchanged
V unchanged
Q unchanged
verified outstanding unchanged
reporting capacity unchanged

Existing VERIFIED repayments remain unchanged.

Existing PENDING_VERIFICATION repayments remain unchanged.

Existing DISPUTED repayments remain unchanged.

Repayment verification after extension acceptance uses the newly current effective TermsVersion.

Do not rewrite or recalculate historical repayment/verification records.

### 18. No obligation reduction

B10 must never reduce:
- original principal
- approved interest
- total obligation
- verified outstanding through term amendment

B10 is not:
- waiver
- settlement
- forgiveness
- debt correction

### 19. ExtensionResponse

Exact response:

{
  "id": "<uuid>",
  "commitment_id": "<uuid>",
  "requested_by": {
    "id": "<uuid>",
    "display_name": "<current display name>"
  },
  "status": "REQUESTED|ACCEPTED|REJECTED|CANCELLED",
  "base_terms_version_id": "<uuid>",
  "previous_due_date": "YYYY-MM-DD",
  "requested_due_date": "YYYY-MM-DD",
  "reason": "<string|null>",
  "decided_by": {
    "id": "<uuid>",
    "display_name": "<current display name>"
  } | null,
  "decided_at": "<UTC RFC3339|null>",
  "created_at": "<UTC RFC3339>"
}

Use previous_due_date, not current_due_date.

previous_due_date means the historical due date captured through the immutable base TermsVersion.

Names are current profile projections.

Do not embed:
- updated Commitment
- full TermsVersion
- repayment state
- ledger event
- audit data
- idempotency internals

### 20. Create success

POST /api/v1/commitments/{id}/extension-requests

returns:

201 ExtensionResponse

Initial status:
REQUESTED

decided_by:
null

decided_at:
null

### 21. Accept / reject success

POST /api/v1/extension-requests/{id}/accept

returns:

200 ExtensionResponse
status = ACCEPTED

POST /api/v1/extension-requests/{id}/reject

returns:

200 ExtensionResponse
status = REJECTED

### 22. Extension list

GET /api/v1/commitments/{id}/extension-requests

Both direct participants may read.

Order:

created_at DESC
then id ASC

No pagination in bounded B10.

Empty list:

[]

No filters.

No individual extension GET endpoint.

### 23. Reason visibility

ExtensionRequest.reason is visible only to authorized direct participants through ExtensionResponse/list.

Do NOT copy reason into:
- LedgerEvent payload
- AuditLog metadata
- operational logs

### 24. Idempotency

All B10 POST mutations require Idempotency-Key:

- create
- accept
- reject

Reuse existing approved B5/B7/B8 policy.

Key:
1–128 characters

Allowed:
[A-Za-z0-9._:-]

Missing/malformed:
400 MALFORMED_REQUEST

Scope:
authenticated actor
+ exact endpoint/operation
+ Commitment or ExtensionRequest resource
+ key

Same scope + same normalized request:
return original completed response

Same key/scope + changed normalized request:
409 IDEMPOTENCY_CONFLICT

Concurrent same-scope in-flight:
409 CONFLICT

Successful results retained for 30 days.

Failed requests are not cached.

Replay:
- reauthenticate
- reauthorize same protected resource/action
- return original completed response
- do NOT repeat domain mutation
- do NOT append duplicate TermsVersion
- do NOT append duplicate ledger/audit rows

Same textual key may be reused across distinct endpoint scopes.

No ExtensionRequest idempotency FK.

No migration.

### 25. Lock ordering

Use:

1. validate/normalize request and idempotency key
2. acquire scoped idempotency advisory lock
3. discover participant IDs non-authoritatively
4. lock affected Users in UUID order
5. revalidate account/session eligibility
6. authorize and lock parent Commitment
7. for decisions, lock ExtensionRequest
8. reread parent association/requester/state/base terms/current terms
9. enforce one-pending / stale-base / date / state rules
10. apply request or decision
11. on acceptance append TermsVersion
12. append LedgerEvent
13. append AuditLog
14. persist completed idempotency result
15. commit once

Never acquire child ExtensionRequest before parent Commitment.

### 26. Concurrency

Expected outcomes:

proposal vs proposal:
one succeeds
one returns 409 CONFLICT

accept vs reject:
one succeeds
loser rereads terminal request state and rejects

accept vs accept:
one effect only

proposal vs repayment report:
serialized through parent Commitment

accept vs repayment verification:
serialized through parent Commitment

accept vs future extension decision:
serialized through parent Commitment

account deactivation vs mutation:
coordinated through ordered User locks

Connection block/remove:
no financial-access revocation
no Connection-lock dependency

### 27. Atomicity

Successful create atomically commits:
- ExtensionRequest
- EXTENSION_REQUESTED ledger
- EXTENSION_REQUESTED audit
- completed idempotency result

Successful accept atomically commits:
- ExtensionRequest status = ACCEPTED
- decided_by_user_id
- decided_at
- exactly one new TermsVersion
- EXTENSION_ACCEPTED ledger
- EXTENSION_ACCEPTED audit
- completed idempotency result

Successful reject atomically commits:
- ExtensionRequest status = REJECTED
- decided_by_user_id
- decided_at
- EXTENSION_REJECTED ledger
- EXTENSION_REJECTED audit
- completed idempotency result

Any required-step failure rolls back all effects.

### 28. Ledger event names

Approve exactly:

EXTENSION_REQUESTED
EXTENSION_ACCEPTED
EXTENSION_REJECTED

Exactly one LedgerEvent per successful extension action.

Do NOT create an extra generic terms-change event.

### 29. EXTENSION_REQUESTED ledger

Actor:
requester

Ledger commitment reference:
parent Commitment

Ledger terms_version_id:
captured base TermsVersion

amount_minor:
null

currency:
null

Closed event details:

extension_request_id
base_terms_version_id
requested_by_user_id
previous_due_date
requested_due_date
status = REQUESTED

Do not include reason.

No money-movement implication.

### 30. EXTENSION_ACCEPTED ledger

Actor:
accepting counterparty

Ledger commitment reference:
parent Commitment

Ledger terms_version_id:
new resulting TermsVersion

amount_minor:
null

currency:
null

Closed event details:

extension_request_id
base_terms_version_id
terms_version_id
requested_by_user_id
previous_due_date
requested_due_date
status = ACCEPTED

Do not include reason.

No money-movement implication.

### 31. EXTENSION_REJECTED ledger

Actor:
rejecting counterparty

Ledger commitment reference:
parent Commitment

Ledger terms_version_id:
captured base TermsVersion

amount_minor:
null

currency:
null

Closed event details:

extension_request_id
base_terms_version_id
requested_by_user_id
previous_due_date
requested_due_date
status = REJECTED

Do not include reason.

### 32. Audit events

Use exact actions:

EXTENSION_REQUESTED
EXTENSION_ACCEPTED
EXTENSION_REJECTED

Object:

object_type = ExtensionRequest
object_id = ExtensionRequest UUID

Actors:

REQUESTED:
requester

ACCEPTED:
accepting counterparty

REJECTED:
rejecting counterparty

result:
SUCCESS

metadata:
sanitized request_id only

Do NOT include:
- reason
- request body
- dates as free-text metadata
- auth token
- Authorization header
- credential hash
- idempotency key
- raw IP
- user-agent

Do not introduce new durable failed-financial-attempt audit policy.

### 33. B9 timeline integration

B10 must update the B9 timeline reader/projector before enabling extension event writers.

Add supported event types:

EXTENSION_REQUESTED
EXTENSION_ACCEPTED
EXTENSION_REJECTED

Preserve B9:
- occurred_at ASC, id ASC
- existing keyset pagination
- authorization
- privacy rules
- malformed/unsupported event fail-safe behavior

Do not change existing seven B9 event projections.

### 34. B9 extension timeline projections

EXTENSION_REQUESTED details:

extension_request_id
base_terms_version_id
requested_by_user_id
previous_due_date
requested_due_date
status = REQUESTED

EXTENSION_ACCEPTED details:

extension_request_id
base_terms_version_id
terms_version_id
requested_by_user_id
previous_due_date
requested_due_date
status = ACCEPTED

EXTENSION_REJECTED details:

extension_request_id
base_terms_version_id
requested_by_user_id
previous_due_date
requested_due_date
status = REJECTED

Do not expose ExtensionRequest.reason in B9 timeline.

Actor:
- request event -> requester
- accepted/rejected -> deciding counterparty

Use current display-name projection.

### 35. Error contract

Missing Commitment:
404 NOT_FOUND

Missing ExtensionRequest:
404 NOT_FOUND

Unrelated user:
same 404 NOT_FOUND

Requester attempts accept/reject:
403 FORBIDDEN

Parent state invalid for request creation/acceptance:
409 INVALID_STATE

Request already ACCEPTED/REJECTED/CANCELLED:
409 INVALID_STATE

Equal/earlier requested date:
422 VALIDATION_ERROR

Unsupported parent schedule mode:
409 INVALID_STATE

Existing REQUESTED extension:
409 CONFLICT

Stale base TermsVersion:
409 CONFLICT

Invalid date/reason/schema:
422 VALIDATION_ERROR

Missing/malformed Idempotency-Key or malformed JSON:
400 MALFORMED_REQUEST

Same idempotency key + changed request:
409 IDEMPOTENCY_CONFLICT

Same-scope in-flight:
409 CONFLICT

Corrupt stored parent/base/request/reference state:
503 SERVICE_UNAVAILABLE

Error precedence after authentication/schema validation:

1. unavailable resource
2. wrong action role
3. parent/request state
4. stale-base/date/invariant validation

No IDOR leakage.

### 36. No migration / index / dependency

Bounded B10 requires:
- no migration
- no index
- no dependency
- no new enum
- no uniqueness constraint
- no ExtensionRequest idempotency FK
- no TermsVersion source-extension FK
- no resulting-version FK
- no installment schema change

One-pending invariant is enforced transactionally under parent Commitment lock.

If implementation unexpectedly requires persistence/index/dependency changes:
STOP.
Report exact blocker.
Do not invent or apply the change.

### 37. FUTURE-FIN-D0 compatibility

B10 must never:
- waive principal
- reduce interest
- modify original principal
- change verified repayment history
- create fake repayment
- create fake waiver
- represent settlement
- set Commitment CLOSED
- imply extension equals forgiveness

Future mutual settlement remains separate.

### 38. Explicit exclusions

Do NOT implement:
- extension cancellation
- expiration
- automatic expiry
- reopen/reconsideration
- reversal
- no-deadline -> deadline conversion
- installment schedule amendments
- installment row mutation
- grace amendment
- interest amendment
- principal amendment
- currency amendment
- party reassignment
- settlement/waiver
- notifications
- summaries/dashboard
- overdue/default
- Trust Score
- Trust Graph
- AI
- payment movement/custody
- FX

## B11-D0 — In-App Event Notifications Contract

Date: 2026-09-21
Status: APPROVED founder/product decision
Scope: B11 bounded in-app event notifications

### 1. Scope

This B11 implementation covers event-driven in-app notifications generated from existing B5–B10 domain actions.

Includes:
- notification creation
- notification inbox/list
- read/unread state
- authorization/privacy
- pagination
- integration with existing domain writers

Does NOT yet implement:
- mobile push
- email
- SMS
- scheduled due-date reminders
- overdue reminders
- notification preferences
- mark-all-read
- deletion/dismissal
- marketing notifications

Reminders remain part of MVP and are deferred to a separate reminder contract.

### 2. Channel

Bounded B11 is IN-APP ONLY.

No provider-specific delivery.
No Expo push-token handling.
No email/SMS provider integration.
No worker/broker.
No new dependency.

Future push may consume the same durable notification records.

### 3. Canonical notification types

Approve exactly:

COMMITMENT_PROPOSED
COMMITMENT_CONFIRMED
COMMITMENT_REJECTED
COMMITMENT_CANCELLED

REPAYMENT_REPORTED
REPAYMENT_VERIFIED
REPAYMENT_DISPUTED

EXTENSION_REQUESTED
EXTENSION_ACCEPTED
EXTENSION_REJECTED

Do not add notification types for:
- terms creation
- installment creation
- ledger reads
- connection state changes
- account/security events
- settlement
- Trust Score/Trust Graph
- AI
- payment movement

### 4. Recipient rule

For every approved event, exactly one notification goes to the other direct participant relative to the action actor.

Never notify the actor about their own action.

Examples:

COMMITMENT_PROPOSED
actor = creator
recipient = other participant

REPAYMENT_REPORTED
actor = reporter
recipient = other participant

EXTENSION_ACCEPTED
actor = accepter
recipient = requester

No self-notifications.

No client-supplied recipient.

### 5. Inactive recipients

If the source domain action is itself valid, create the durable notification record for the intended existing recipient even if that recipient is currently deactivated.

Do not:
- reactivate them
- create a notification-specific login exception
- weaken domain mutation eligibility
- fail an otherwise-valid B10 rejection because requester later deactivated

A deactivated user still cannot authenticate/read notifications under B2.

Historical notification records remain stored.

### 6. Integrated writers

Integrate notification creation into:
- Commitment writers
- Repayment reporting
- Repayment verification/dispute
- Extension request/decision

B6 TermsVersion calculations/writers do not independently generate notifications.

B9 ledger reads do not generate notifications.

### 7. Creation timing

Create NotificationEvent only when the underlying domain action has passed validation and is proceeding successfully.

No notification for:
- failed action
- rejected HTTP request
- rolled-back transaction
- race loser
- completed idempotent replay

### 8. Atomic durable record rule

For bounded in-app notifications, where the originating financial/domain writer already commits transactionally:

domain mutation
+ ledger
+ audit
+ NotificationEvent
+ completed idempotency result

must commit in the same database transaction.

If durable NotificationEvent persistence fails before commit:
the entire transaction rolls back.

Clarification:
durable NotificationEvent persistence is part of the application transaction, not an external delivery attempt.

After commit, any later provider/delivery/read failure must never reverse or mutate financial state.

### 9. No historical backfill

Do not create notifications for historical B5–B10 actions when B11 is deployed.

Only successful domain actions occurring after B11 writers are enabled generate notifications.

No backfill job.

### 10. NotificationEvent storage

Use existing notification_events table.

For bounded B11:

user_id =
recipient UUID

type =
exact approved notification type

object_type =
Commitment
or
Repayment
or
ExtensionRequest

object_id =
corresponding source object UUID

payload exactly:

{
  "source_ledger_event_id": "<uuid>"
}

Do not store in payload:
- notes
- descriptions
- extension reason
- verification note
- repayment note
- phone
- actor display name
- title/body
- amount
- currency
- auth information
- raw ledger payload

### 11. Source provenance

Every bounded notification must reference the LedgerEvent generated by the same successful domain action through:

payload.source_ledger_event_id

Projection must validate:
- ledger event exists
- ledger event type matches notification type
- source object matches notification object
- source belongs to correct Commitment
- actor is valid participant
- recipient is the correct counterparty
- notification represents the original historical action

Do not infer historical notification meaning solely from the source object's current status.

### 12. Notification lifecycle

On durable in-app creation:

status = DELIVERED
read_at = null
sent_at = null
scheduled_at = null

For bounded B11, DELIVERED means:
durably available in the Fides in-app inbox.

It does NOT mean:
- delivered to a device
- externally delivered
- viewed by the human

On first successful mark-read:

status = READ
read_at = server timestamp

PENDING, SENT, FAILED remain unused in bounded in-app B11.

### 13. Read/unread semantics

Unread:
read_at == null

Read:
read_at != null

Mark-read is one-way.

Do not implement:
- mark unread
- mark all read
- dismiss
- delete

GET never marks a notification read.

### 14. Repeated mark-read

Calling mark-read on an already-read notification:

returns 200
returns the existing NotificationResponse
preserves the original first read_at

Do not generate a new timestamp.

The route is naturally idempotent and does not require Idempotency-Key.

### 15. Canonical API

Implement exactly:

GET  /api/v1/notifications
POST /api/v1/notifications/{id}/read

Do NOT add:
- GET /notifications/{id}
- POST /notifications/read
- POST /notifications/read-all
- PATCH /notifications/{id}
- DELETE /notifications/{id}
- mark-unread

Do not implement notification-preference routes in bounded B11.

### 16. GET /notifications

Bearer authenticated.

Query parameters:

limit
cursor

limit:
default = 50
min = 1
max = 100

Ordering:

created_at DESC
id DESC

Cursor:
- opaque
- versioned
- recipient-bound
- contains last ordering tuple
- keyset pagination
- no offset pagination

Live pagination.

No frozen snapshot guarantee.

No filters.
No unread-count field.
No Idempotency-Key.

### 17. List response

Exact response envelope:

{
  "items": [],
  "next_cursor": null
}

### 18. NotificationResponse

Exact public fields:

id
type

actor {
  id
  display_name
}

commitment_id

repayment_id | null

extension_request_id | null

created_at

read_at | null

Do not expose:
- status
- payload
- object_type
- object_id
- source_ledger_event_id
- sent_at
- scheduled_at
- amount_minor
- currency
- previous_due_date
- requested_due_date
- note
- reason
- description
- title
- body
- raw metadata

Do not add redundant is_read.

### 19. Actor projection

actor uses the current User display name.

Do not snapshot actor display names into NotificationEvent payload.

Missing/corrupt actor/source relationships fail safely.

### 20. Content rendering

Backend does not persist rendered title/body strings for these ten event-driven types.

Frontend renders notification copy from:
- type
- validated structured references
- current actor projection

This preserves localization and avoids stale rendered names or duplicated private text.

### 21. Source IDs

All ten notification types expose:
commitment_id

Repayment notification types also expose:
repayment_id

Extension notification types also expose:
extension_request_id

Non-applicable IDs are null.

### 22. Authorization

Only the recipient may list/read/mark a NotificationEvent:

NotificationEvent.user_id == authenticated principal.user_id

Being:
- actor
- lender
- borrower
- another Commitment participant

does not grant ownership access to another user's NotificationEvent.

Missing notification and other-recipient notification both return:

404 NOT_FOUND
"Unavailable resource."

No IDOR leakage.

### 23. Connection state

BLOCKED/REMOVED does not alter financial-participant semantics.

Notification creation derives from whether the underlying domain action succeeded.

Notification read authorization derives only from recipient ownership.

No Connection lock dependency.

### 24. Privacy

Never expose or store notification copies of:
- phone
- auth/session data
- repayment note
- verification note
- extension reason
- Commitment description
- raw ledger JSON
- audit metadata
- idempotency key

No global/public notification API.
No admin/public notification feed.

### 25. Read mutation effects

Mark-read:
- mutates NotificationEvent only
- does not change financial state
- does not create LedgerEvent
- does not create AuditLog
- does not require financial parent locking

### 26. Notification creation auditing

Do not create a second AuditLog merely for NotificationEvent insertion.

The originating domain action remains the authoritative ledger/audit action.

NotificationEvent is a derived workflow record.

### 27. Locking

Domain-generated notification creation follows the existing lock order of the originating writer.

Do not introduce a global notification lock.

For mark-read:

authenticated User eligibility
-> recipient-owned NotificationEvent
-> row lock/update

Do not acquire NotificationEvent and then acquire financial Commitment/User locks.

Concurrent mark-read calls preserve the first read_at.

### 28. Domain idempotency

Notification creation inherits originating domain-action idempotency.

Completed replay must not create another NotificationEvent.

No separate notification dedupe key or unique constraint.

### 29. Notification API idempotency

GET list:
no Idempotency-Key

POST mark-read:
no Idempotency-Key

Mark-read is naturally idempotent.

### 30. Pagination concurrency

List and mark-read may race normally.

No cross-request frozen-snapshot guarantee.

New notifications inserted between pages follow live keyset-pagination semantics.

No global notification lock.

### 31. Retention

Bounded B11 implements:
- no hard delete
- no soft delete
- no archive state
- no retention job
- no automatic expiration

Notification rows remain stored pending a future explicit retention/anonymization policy.

After creation, only read-state fields may mutate.

Do not rewrite:
- type
- recipient
- source object
- payload/provenance
- created_at

### 32. Unknown/corrupt records

If stored NotificationEvent contains:
- unknown type
- malformed payload
- missing ledger event
- cross-parent reference
- inconsistent source object
- invalid actor/recipient
- impossible lifecycle

fail safely with:

503 SERVICE_UNAVAILABLE

Do not silently omit corrupt records.

Do not expose raw JSON.

### 33. Error contract

Missing notification:
404 NOT_FOUND

Other-recipient notification:
same 404 NOT_FOUND

Already read:
200 success
preserve original read_at

Invalid UUID:
422 VALIDATION_ERROR

Invalid cursor:
422 VALIDATION_ERROR

Invalid limit:
422 VALIDATION_ERROR

Unknown body field:
422 VALIDATION_ERROR

Malformed JSON:
400 MALFORMED_REQUEST

Missing/invalid/expired/revoked auth:
existing B2 behavior

Corrupt persisted notification/source:
503 SERVICE_UNAVAILABLE

No new notification-specific public error codes.

### 34. Mark-read body

Require exact closed JSON object:

{}

No actor.
No timestamp.
No status.
No notification ID inside body.
No unknown fields.

### 35. No migration

Bounded B11 requires:
- no migration
- no new enum
- no new FK
- no dedupe field
- no device table
- no preferences table

Existing read_at provides read persistence.

Existing recipient index is sufficient for correctness.

Do not add a new list index without measured evidence.

If implementation unexpectedly requires schema/index changes:
STOP and report exact blocker.

### 36. No dependency/infrastructure

Do not add:
- Redis
- Celery
- broker
- notification provider SDK
- scheduler
- Expo push integration
- email provider
- SMS provider

Bounded event-driven in-app notifications use PostgreSQL and current application transactions only.

### 37. Reminder follow-up

Upcoming due reminders and overdue notifications remain part of MVP.

They are explicitly deferred from bounded B11 to a separate reminder contract.

That contract must define at minimum:
- cadence
- recipients
- contractual timezone
- grace behavior
- extension interaction
- partial repayment interaction
- terminal-state stop rules
- missed-run handling
- retries
- deduplication
- scheduler deployment

Do not implement scheduled reminders in bounded B11.

### 38. Preferences follow-up

Notification preferences remain an MVP/spec requirement but are deferred from bounded B11 because no approved persistence contract exists.

Do not fake preference persistence inside:
- NotificationEvent payload
- User JSON
- authentication/device tables

### 39. Push follow-up

Do not select or implement a push provider in bounded B11.

Before push implementation, separately approve:
- provider
- device-token registration
- token ownership
- revocation
- multi-device behavior
- retries
- provider receipts
- invalid-token handling
- consent

Keep durable in-app notification records transport-independent.

### 40. Explicit exclusions

Do NOT implement:
- email delivery
- general SMS
- push
- device tokens
- notification preferences
- scheduled reminders
- reminder scheduler
- mark-all-read
- mark-unread
- deletion/dismissal
- marketing notifications
- Trust Score alerts
- Trust Graph alerts
- community funding alerts
- default escalation
- collections
- settlement notifications
- AI-generated notification copy
- cross-currency aggregation


## B12-D0 — Server-Derived Financial Summary Contract

Date: 2026-09-29
Status: APPROVED founder/product decision
Scope: B12 bounded server-derived financial summary queries

### 1. Canonical endpoint

GET /api/v1/summary

### 2. Authentication / authority

- authenticated-user only
- server-derived
- backend remains authoritative
- no client-supplied user_id
- aggregate only commitments where authenticated user is lender or borrower

### 3. Read-only behavior

- no request body
- no Idempotency-Key requirement
- no LedgerEvent
- no AuditLog
- no NotificationEvent
- no state mutation
- no persistent summary/balance table
- no materialized view
- no persistent cache

### 4. Explicitly deferred from bounded B12

- GET /api/v1/summary/borrowed
- GET /api/v1/summary/lent
- GET /api/v1/summary/upcoming
- GET /api/v1/summary/overdue
- upcoming items/counts/totals
- overdue items/counts/totals
- next-due fields
- recent activity/global activity feed
- generic needs_attention
- pending-action aggregates
- frontend integration/F1

These remain separate future/MVP requirements where already specified;
they are not silently removed.

### 5. Currency contract

Supported currencies:
- INR
- USD
- GBP

Summary returns exactly three currency buckets in deterministic order:
INR, USD, GBP

Include zero-exposure currencies.

No:
- FX
- currency conversion
- base/preferred currency
- cross-currency aggregation
- cross-currency netting

Commitment currency remains immutable and authoritative.

### 6. Obligation / outstanding

For one commitment at one evaluation time:

P = original principal
I = approved interest from current effective TermsVersion
O = P + I
V = sum of current VERIFIED repayments

verified_outstanding = O - V

IMPORTANT:
- do NOT clamp with max(O - V, 0)
- if V > O, fail safely as authoritative-data inconsistency

SIMPLE_FIXED:
I = (P * interest_rate_bps + 5000) // 10000

NONE:
I = 0

Pending, disputed, and cancelled repayments do not reduce verified outstanding.

### 7. Borrowed / lent totals

borrowed_outstanding_minor(currency)
=
sum of verified outstanding for included commitments
where authenticated user is borrower

lent_outstanding_minor(currency)
=
sum of verified outstanding for included commitments
where authenticated user is lender

These represent CURRENT VERIFIED OUTSTANDING,
not original principal, lifetime volume, or reporting capacity.

### 8. Net position

Per currency:

net_position_minor
=
lent_outstanding_minor
-
borrowed_outstanding_minor

Net position is display-only derived data.

It must not:
- merge commitments
- settle obligations
- offset repayments operationally
- change repayment eligibility
- mutate financial state

### 9. Commitment-state treatment

ACTIVE
- include current verified outstanding

PARTIALLY_REPAID
- include current verified outstanding

FULLY_REPAID
- validate verified outstanding == 0
- contributes zero
- inconsistent non-zero or negative result => safe failure

PENDING_CONFIRMATION
- exclude

REJECTED
- exclude

CANCELLED
- exclude

CLOSED
- unsupported in bounded B12 until approved mutual-settlement/waiver accounting defines its effect
- encountering an authorized CLOSED commitment => safe SERVICE_UNAVAILABLE

Other legacy/unsupported stored states such as:
- DRAFT
- CONFIRMED
- DISPUTED
- DEFAULTED

must not be silently interpreted or omitted.
Encountering them in authorized financial input => safe SERVICE_UNAVAILABLE.

### 10. TermsVersion

Current effective terms =
highest version_no
where effective_at <= evaluation_time

Do not select newest-created blindly.

Historical terms do not independently contribute to totals.

B10 accepted extension terms become authoritative immediately.
Pending/rejected extensions do not alter effective terms.

### 11. No-deadline commitments

- still contribute to borrowed/lent/net financial totals
- no due/upcoming/overdue classification in bounded B12

### 12. Installment commitments

- whole-commitment verified outstanding contributes exactly once
- do not add installment amounts on top of total obligation
- do not infer installment repayment allocation
- do not infer next unpaid installment
- do not infer installment overdue status

### 13. Upcoming / overdue

Do not expose either in bounded B12.

Existing B6 timezone/grace/date rules remain authoritative where already approved.

Do not implement:
- default transitions
- penalties
- collections
- delinquency scoring
- trust impact
- installment overdue allocation

### 14. Recent activity

- B9 remains commitment-scoped
- no new user-level/global activity route in B12
- do not expose AuditLog
- do not treat B11 notifications as equivalent financial activity

### 15. Exact response shape

```json
{
  "currencies": [
    {
      "currency": "INR",
      "borrowed_outstanding_minor": 0,
      "lent_outstanding_minor": 0,
      "net_position_minor": 0
    },
    {
      "currency": "USD",
      "borrowed_outstanding_minor": 0,
      "lent_outstanding_minor": 0,
      "net_position_minor": 0
    },
    {
      "currency": "GBP",
      "borrowed_outstanding_minor": 0,
      "lent_outstanding_minor": 0,
      "net_position_minor": 0
    }
  ]
}
```


Closed schema:
- root contains only currencies
- currencies required/non-null
- exactly three entries
- fixed INR/USD/GBP order
- each entry has exactly:
  currency
  borrowed_outstanding_minor
  lent_outstanding_minor
  net_position_minor
- no null monetary values
- no floating-point money
- borrowed/lent non-negative
- net signed
- no additional properties

### 16. Aggregate numeric representation

Use JSON integers.

All returned monetary aggregates must fit JavaScript safe integer range:

-(2^53 - 1) <= value <= (2^53 - 1)

Borrowed/lent remain non-negative.
Net may be signed.

If aggregate exceeds safe-integer range:
- return safe 503 SERVICE_UNAVAILABLE
- do not round
- do not truncate
- do not emit imprecise JSON numbers

### 17. Query contract

GET /api/v1/summary

- no body
- no pagination
- no supported query parameters
- unknown query parameter => 422 VALIDATION_ERROR
- no Idempotency-Key requirement

### 18. Success / headers

200 on success.

Preserve existing API conventions including:
- Cache-Control: no-store
- sanitized X-Request-ID
- existing Bearer / WWW-Authenticate behavior

### 19. Authorization / privacy

- only authenticated actor's financial participation
- connection membership alone grants no access
- blocked/removed connection does not erase existing financial participation
- do not exclude financial records merely because counterparty is deactivated
- actor deactivation follows existing B2 auth/session behavior

Response must not expose:
- counterparty identity
- phone
- notes
- descriptions
- individual commitment IDs
- repayment details
- extension reasons
- ledger payloads
- audit data
- notification data

### 20. Consistency

One response must be internally coherent.

Approved technical approach:
- authenticate/revalidate actor
- retain existing actor User lock
- capture one evaluation time
- load authorized financial inputs consistently
- batch current TermsVersions
- batch repayment aggregates
- calculate/validate summary
- do not lock every commitment solely for summary reads

Do not call helpers outside their documented lock preconditions.

Concurrency tests must prove behavior against current compliant writers.

### 21. Calculation implementation rule

Reuse/refactor authoritative financial calculation logic as necessary.

Do not duplicate independent formulas for:
- fixed interest
- obligation
- verified repayment accounting
- outstanding
- currency validation

LedgerEvent is not the financial calculation authority.

### 22. Corruption handling

Do not silently skip corrupt authorized records.

Return safe 503 SERVICE_UNAVAILABLE for:
- missing current terms
- unsupported currency
- repayment currency mismatch
- invalid reporter/association
- V > O
- invalid principal
- inconsistent FULLY_REPAID state
- unsupported commitment state
- aggregate overflow
- other authoritative-data corruption covered by existing safe error conventions

No partial summary.

### 23. Error contract

Use existing mappings:

- missing auth -> 401 AUTH_REQUIRED
- invalid token -> 401 INVALID_AUTH_TOKEN
- expired token -> 401 AUTH_TOKEN_EXPIRED
- revoked session -> 401 SESSION_REVOKED
- inactive/unavailable actor -> existing B2 mapping
- unsupported query parameter -> 422 VALIDATION_ERROR
- corrupt authoritative financial data -> 503 SERVICE_UNAVAILABLE
- database unavailable -> 503 SERVICE_UNAVAILABLE
- unexpected uncaught exception -> existing 500 INTERNAL_ERROR

No new B12-specific public error codes.

### 24. Persistence / infrastructure

Bounded B12 requires:
- no migration
- no new index
- no summary table
- no materialized view
- no persistent cache
- no new dependency

Do not add speculative performance infrastructure without evidence.

### 25. Explicit exclusions

Do NOT include:
- settlement/waiver implementation
- installment repayment allocation
- default transitions
- penalties
- collections
- trust/risk scoring
- FX
- cross-currency aggregation
- reminders
- notification preferences
- push
- frontend DTOs
- F1 work

## B13-D0 — Reliability, Concurrency & Idempotency Hardening Contract

- Date: 2026-10-01
- Status: APPROVED founder/technical decision; recorded before B13 implementation.
- Scope: B13 — reliability hardening for the existing backend through B12.
- Authority: This decision preserves approved B2–B12 behavior and governs B13 reliability work. It does not authorize product/API behavior changes.
- Implementation state: This entry records decisions only. B13 implementation, tests, migrations, and dependency changes are not part of B13-D0.

### 1. B13 purpose

B13 is hardening only. It must not change product behavior.

Use a tests-first process to prove existing reliability architecture under failure and race conditions before changing production code. If a focused test demonstrates an in-scope defect, make the smallest safe fix and rerun affected regressions. Do not broadly refactor services for consistency.

### 2. Financial idempotency contract

Exactly the existing ten financial mutation endpoints continue to require `Idempotency-Key`. Their actor + operation/resource + key scope, normalized request hash, endpoint scopes, and historical hashes remain unchanged.

- Same key and same normalized request replays the original logical result.
- Same key with a changed request returns the existing `IDEMPOTENCY_CONFLICT` error.
- A concurrent in-flight duplicate returns the existing `CONFLICT` error.
- Current authorization is rechecked before replay.
- Successful results are retained for 30 days.
- A failed financial transaction does not consume a new key.
- The advisory lock is acquired before User or resource locks.
- Idempotency completion commits atomically with domain effects.

Do not add idempotency requirements to authentication, account, connection, or notification-read actions.

### 3. Lock ordering

Preserve this canonical financial lock order:

Idempotency advisory lock
→ affected User rows in deterministic UUID order
→ Connection where required
→ Commitment
→ child resource

Existing patterns remain authoritative:

| Operation | Lock order |
| --- | --- |
| Commitment create | I → U* → C → inserts |
| Commitment confirm | I → U* → C → P |
| Commitment reject/cancel | I → U* → P |
| Repayment report | I → U* → P |
| Verify/dispute | I → U* → P → R |
| Extension create | I → U* → P |
| Extension decision | I → U* → P → E |
| B12 summary | U → financial reads |

Do not introduce child-first locking or lock every Commitment unnecessarily.

### 4. Transaction atomicity

Where applicable, one logical financial operation commits together:

- domain mutation;
- TermsVersion and installments;
- LedgerEvent;
- AuditLog;
- NotificationEvent; and
- completed IdempotencyKey result.

Helpers may flush but must not independently commit. OTP/provider operations remain intentional exceptions to single-database-transaction semantics.

### 5. Post-lock revalidation

Re-read and revalidate authoritative state after required locks, including where relevant:

- actor/session and participant association;
- connection and commitment state;
- repayment state and current effective TermsVersion;
- verified outstanding and pending reporting capacity;
- extension base version and request state; and
- active participant state.

Pre-lock discovery reads may identify lock targets but are not authoritative financial snapshots.

### 6. Application transaction isolation

Fides application transactions rely on PostgreSQL `READ COMMITTED` unless a later approved decision specifies otherwise for a particular workflow.

B13 must verify or explicitly configure application transaction isolation as `READ COMMITTED`, add automated verification of effective application isolation, and fail safely if application configuration explicitly selects an unsupported isolation level.

Do not globally move to `REPEATABLE READ` or `SERIALIZABLE`. Do not introduce per-operation isolation overrides without demonstrated need.

### 7. Database retry policy

Do not add a generic automatic database retry loop. Do not retry a statement inside an aborted transaction.

Deadlock, serialization, and timeout failures roll back and surface through existing safe behavior. Client recovery for financial operations uses the same `Idempotency-Key` and identical payload.

Do not automatically retry PostgreSQL:

- `40P01` deadlock;
- `40001` serialization failure;
- `55P03` lock timeout; or
- `57014` statement timeout/cancellation.

Whole-transaction automatic retry is deferred pending a separate policy for retry count, timing/backoff, transaction recreation, and observability.

### 8. Lost commit acknowledgement

B13 must test a transaction that commits successfully but whose acknowledgement is lost to the caller/application. Retrying the same request with the same key and payload must return the persisted original logical result and leave exactly one complete effect set.

There must be no duplicate Commitment, TermsVersion, Repayment, RepaymentVerification, ExtensionRequest, LedgerEvent, AuditLog, NotificationEvent, or idempotency result.

### 9. Expired idempotency results

Add tests for expired-result replacement, failure while replacing an expired result, and concurrent reuse at the expiry boundary.

Preserve these rules:

- only an expired result may be replaced;
- replacement remains serialized under the existing advisory lock;
- failed replacement rolls back new domain work and replacement;
- a later valid retry remains possible; and
- no durable in-progress reservation is added without a new approved decision.

### 10. Commitment race tests

Add targeted tests including reject versus reject and representative cross-route operations with reversed participant roles.

Verify only valid serialized outcomes, no duplicate terminal effects or ledger/audit/notification effects, and no invalid lifecycle state.

### 11. Extension race tests

Add tests for accept versus a new extension request and accept versus repayment report.

Preserve at most one `REQUESTED` extension per Commitment, B10 stale-base handling, unique TermsVersion version allocation, and correct reporting capacity. Do not add a database uniqueness constraint solely for this purpose.

### 12. Summary race tests

Add tests for summary versus repayment report and summary versus actual account deactivation.

Preserve the actor User lock and fixed evaluation time. The result must be internally coherent or return the existing authorization/account-state denial; it must never contain mixed-state totals.

### 13. Credential race tests

Add financial-request race tests against logout and refresh/session rotation.

The operation winning the existing coordination determines the valid outcome:

- revocation or rotation first means the subsequent protected financial action is denied under existing authentication rules;
- financial mutation first may complete atomically; and
- an already valid committed transaction is not retroactively rolled back.

### 14. Connection race tests

Add representative tests for connection block/remove versus commitment confirmation.

Preserve current connection eligibility rules. Blocked/removed relationships do not erase historical financial participation, and participant-based financial authorization remains unchanged.

### 15. PostgreSQL failure-class tests

Add targeted tests for `40P01`, `40001`, `55P03`, `57014`, connection loss before commit, and connection loss during/after commit where the outcome is uncertain.

Verify rollback when commit did not occur, safe public errors, retained request correlation, no partial financial effects, and same-key recovery where appropriate.

### 16. Structured reliability diagnostics

Add sanitized structured internal reliability logging. Allowed fields are:

- event/category;
- operation category;
- failure phase;
- safe database category;
- allowlisted SQLSTATE;
- request ID; and
- commit outcome when knowable: `committed`, `rolled_back`, `uncertain`, or `unknown`.

Example categories include deadlock, serialization failure, lock timeout, statement timeout, integrity error, connection failure, commit uncertain, idempotency conflict, and state conflict.

Never log SQL text, bind values, raw exception text that may expose data, Idempotency-Key values, request bodies, phone numbers, auth tokens, OTPs, notes/reasons, financial descriptions, or other prohibited sensitive fields. If commit outcome is uncertain, log `uncertain`; never report it as rolled back.

### 17. Public errors

Do not add B13 public reliability error codes. Preserve existing `CONFLICT`, `IDEMPOTENCY_CONFLICT`, `SERVICE_UNAVAILABLE`, and safe generic internal-error behavior. PostgreSQL-specific details remain internal.

### 18. Failure injection and rollback

Add or strengthen failure-injection tests for failure after successful flushes but before commit, idempotency-result persistence, expired-result update, ledger insertion, audit insertion, notification insertion, TermsVersion creation, verification-history creation, financial state update, and commit stage.

Assert complete logical rollback whenever commit did not occur.

### 19. Complete side-effect assertions

Where practical, new race and failure tests must verify the complete effect set: primary domain state, terms/history, repayment/verification rows, LedgerEvent, AuditLog, NotificationEvent, and IdempotencyKey result.

### 20. Schema and infrastructure

B13 requires no migration, new index, model/table, uniqueness constraint, or dependency by default.

If a new B13 test demonstrates a defect that genuinely requires a schema change, stop and report the exact issue before creating any migration.

### 21. Bounded fix policy

Use this sequence:

1. Add a focused test.
2. Demonstrate the current result.
3. If behavior is already correct, keep production code unchanged.
4. If a defect exists, make the smallest in-scope fix.
5. Rerun affected regressions.

Do not broadly refactor services for consistency.

### 22. Explicit exclusions

Do not include new endpoints, F1/frontend work, settlement/waiver, overdue/default product behavior, reminders, notification preferences, push delivery, installment allocation, closure redesign, contact discovery, authentication redesign, retention redesign, generic automatic retries, new timeout values, speculative indexes, dependency upgrades, broad logging redesign, or B14 security-hardening work.

### 23. Validation expectation

B13 implementation must eventually run focused B13 reliability tests, affected B2–B12 regressions, the full backend suite, Ruff, formatter check, `pip check`, and `git diff --check`. No wholesale skips.

## B14-D0 — APPROVED — Security Hardening Contract

B14 is a bounded security-hardening pass. Its objective is to inspect, verify, test, and fix demonstrated security defects while preserving the current approved product, API, and financial behavior.

### Audit scope

The read-only audit and any later approved implementation may cover:

- authorization and IDOR boundaries across accounts, connections, commitments, repayments, verification/dispute, ledger/history, extensions, notifications, profiles, summaries, and UUID-addressable resources;
- OTP authentication, session and token issuance/revocation, deactivated-account behavior, revalidation, authentication failures, and sensitive-value handling;
- FastAPI/Pydantic validation, malformed identifiers, oversized strings and pages, malformed money/currency/date/timezone input, and request-size protection, with an approximately 1 MiB production request ceiling unless the architecture requires a smaller approved limit;
- production CORS, browser-facing behavior, and security headers appropriate to the bearer-token architecture;
- secrets and configuration, logging and error handling, proxy/deployment assumptions, health/readiness exposure, database least privilege, and declared dependency risk; and
- security testing for IDOR, unauthorized participant access, auth/session misuse, malformed or oversized requests, production configuration failures, CORS, secret/log leakage, privacy-safe unavailable/not-found behavior, financial invariants, and B13 reliability behavior.

### Explicit exclusions

B14 must not redesign authentication, add OAuth/social login, MFA, passwords, new product features, frontend functionality, Mutual Closure, reminders, notification preferences, Upcoming/Overdue behavior, or infrastructure without demonstrated need. It must not change financial semantics, money calculations, commitment lifecycle, repayment verification, extension rules, or B13 concurrency, idempotency, isolation, and reliability behavior. It must not introduce migrations, dependencies, indexes, or other schema changes unless a later audited defect absolutely requires one and approval is obtained first.

### Stop conditions

If a demonstrated defect requires an API contract change, migration or other schema change, new dependency, authentication-architecture change, financial-behavior change, or substantial infrastructure change, stop and request approval before implementation. Do not fix hypothetical or speculative issues.

### Production security gate

The production gate is fail-closed configuration, safe authentication and session handling, privacy-preserving authorization and errors, no sensitive secret or financial-data leakage, appropriate CORS and security headers, safe proxy and health assumptions, least-privilege runtime expectations, and focused regression evidence. Existing approved behavior remains authoritative unless a demonstrated security defect is fixed through the bounded process.

Only demonstrated defects may be fixed. Every fix requires a focused test, demonstration of the prior result, the smallest in-scope change, and affected regression tests. Preserve B13 transaction, isolation, lock-ordering, idempotency, and diagnostic behavior.

### B14 execution order

1. Approved docs checkpoint.
2. Read-only security audit.
3. Review audit findings.
4. Approve a bounded implementation plan.
5. Implement demonstrated fixes.
6. Run focused security tests.
7. Run full backend regression.
8. Perform the final security gate.

No implementation occurs before step 4.

## B14-D1 — APPROVED — Security implementation scope

### A. Request body size limit

Maximum HTTP request body:

1 MiB = 1,048,576 bytes

Rules:

- exactly 1,048,576 bytes is allowed;
- any body larger than 1,048,576 bytes is rejected;
- rejection status: HTTP 413 Payload Too Large;
- public error code: `REQUEST_TOO_LARGE`;
- use the existing standard public error envelope;
- do not expose parser, framework, or body-size internals;
- preserve correlation/request ID behavior;
- preserve safe cache/security headers;
- reject clearly oversized declared `Content-Length` before service/provider execution;
- `Content-Length` is not trusted as the only enforcement mechanism;
- missing, misleading, or streamed/chunked bodies must be counted by actual bytes;
- stop reading once the ceiling is exceeded;
- valid requests must remain readable downstream;
- no dependency is added;
- no OTP/rate-limit semantics are changed.

### B. Malformed Host / raw path correction

Security-sensitive path classification must use the authoritative ASGI request path rather than reconstructed `request.url.path` where malformed Host could influence URL reconstruction.

Requirements:

- use `request.scope["path"]` or an equivalent authoritative raw request path;
- preserve routing behavior;
- preserve authorization;
- preserve public error taxonomy;
- preserve cache policy;
- no FastAPI/Starlette upgrade in B14;
- no proxy redesign;
- no dependency change.

### C. API security headers

Add bounded API response headers:

- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`.

Requirements:

- apply to normal API success responses;
- apply to handled API error responses;
- apply to 413 responses;
- preserve existing `Cache-Control`;
- preserve `WWW-Authenticate`;
- preserve request/correlation IDs;
- preserve `Retry-After` where already present.

Do not add in this backend task:

- frontend CSP;
- frontend frame policy;
- local/dev HSTS;
- CSRF infrastructure;
- unrelated security headers.

HSTS/CSP/frame policy remain deployment/web-host concerns.

### D. Implementation limits

B14-D1 does not approve:

- migrations;
- dependency upgrades;
- auth redesign;
- API redesign beyond the approved 413 / `REQUEST_TOO_LARGE` contract;
- financial behavior changes;
- B13 transaction/lock/idempotency changes;
- frontend changes;
- new product features;
- Mutual Closure;
- reminders;
- Notification Preferences;
- Upcoming/Overdue endpoints.

If implementation later requires any of those, stop and request approval.

### E. Required validation

Implementation must include focused regression coverage for:

- body-size boundary;
- streamed/misleading `Content-Length` bypass attempts;
- provider/service not invoked for oversized bodies;
- 413 error envelope;
- malformed Host path invariance;
- no-store preservation;
- security headers on success/error paths;
- authz unchanged;
- B13 behavior unchanged;
- financial invariants unchanged.

Then run the appropriate full backend regression before B14 completion.

### B14 implementation evidence

The request admission middleware runs before correlation middleware, route dependencies, JSON parsing, and services. It rejects clearly oversized declared Content-Length without reading the body; otherwise it counts actual received bytes, stops at the first over-limit chunk, and retains no over-limit chunk. Its bounded buffer admits exactly 1,048,576 bytes and replays admitted bodies downstream. This also covers handlers that do not read bodies. HTTP 413 returns the standard envelope with `REQUEST_TOO_LARGE` and the fixed message `Request too large.`; correlation IDs use the existing sanitizer. OpenAPI documents 413 globally; existing endpoint request schemas and the closed B2 auth error catalog are unchanged.

Cache and validation classification now use `request.scope["path"]`. API successes and handled errors carry `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. Early 413s use the same policies, no-store, and sanitized request IDs. Existing WWW-Authenticate and Retry-After values remain intact. A focused regression caught duplicate differently cased headers on 413; response construction now uses case-insensitive MutableHeaders to prevent duplication.

The initial focused regressions demonstrated oversized OTP acceptance, malformed-Host cache-policy bypass, and a real Uvicorn ASGI request-cycle log containing a synthetic exception sentinel after the safe application 500 response. The logging correction is limited to the existing `uvicorn.error` ASGI-exception record: it removes exception/stack text while retaining the generic ERROR event. It does not change B13 diagnostics, transaction behavior, or other logger records. Verification uses Uvicorn's installed h11 RequestResponseCycle with an in-memory transport, not merely TestClient logging and not a deployed reverse proxy.

Focused validation passed: 120 tests, including 66 new B14 cases and existing error regressions. Coverage includes byte boundaries, missing/misleading declared length, whitespace-padded oversized Content-Length, streamed rejection and stopped reads, downstream replay, no dispatch for oversized requests, malformed-Host auth and financial validation, safe error/header behavior, and 18 PostgreSQL-backed checks using the actual B2 principal resolver and B3 participant service. The earlier broader affected-regression run had 565 passes and four duplicate-header failures; all four were corrected and passed in the focused rerun. The first full run was interrupted to add the final declared-length whitespace correction before running the complete final suite.

Final complete backend regression passed: 2,633 tests, zero failures, zero skips. This includes B2-B13 authentication, authorization, financial, notification, summary, extension, and reliability regressions. The one warning is the existing Starlette TestClient use of a deprecated AnyIO BlockingPortal alias; no dependency is changed to address it. Financial service code and B13 transaction/isolation/locking/idempotency code remain unchanged.

Application and new B14 test Ruff checks pass. All 12 changed/new Python files pass formatter checks; pip check and git diff --check pass. Repository-wide Ruff retains seven pre-existing B12 summary-test I001 import-order findings. Only the existing summary OpenAPI assertion changes outside the main B14 file areas, adding the approved 413 status; its pre-existing import block is untouched.

### Deployment verification and deferred B15 gates

Cross-origin preflight remains restrictive: untrusted browser origins receive no Access-Control-Allow-Origin or credential permission. No CORS middleware or cookie/CSRF architecture is introduced. The existing trusted-peer forwarding-header policy and documented --no-proxy-headers / --no-access-log launch requirements remain authoritative.

The existing local fides_test database was reachable at the configured port and migration 012 before tests. Read-only role inspection confirmed its documented broad local-development privileges; this is not evidence of production least privilege. Separate production migration/runtime credentials, runtime DDL denial, and ledger/audit UPDATE/DELETE denial must be verified under externally provisioned production-style credentials as a B15/deployment gate. No roles, grants, credentials, or migration files are introduced here. Production TLS/HSTS, web-host CSP/frame policy, and proxy/platform log privacy remain deployment concerns.

## B11-R Technical Contract T0 — APPROVED

### A. Architecture

Use a DB-backed scheduler job invoked approximately hourly. Do not use Redis, Celery, Kafka, RabbitMQ, a separate broker, or an infinite scheduler loop inside FastAPI web workers. The conceptual job entry point may be `python -m app.jobs.reminders`; deployment scheduling belongs to B15.

### B. Reminder types

Add `UPCOMING_DUE`, `DUE_TODAY`, and `OVERDUE` as NotificationEvent types only. They are not commitment states, ledger event types, or financial mutations.

### C. Recipients and timing

- `UPCOMING_DUE`: borrower only, three borrower-local calendar days before the authoritative contractual due date.
- `DUE_TODAY`: borrower only, on the borrower-local due date.
- `OVERDUE`: borrower and lender, only after authoritative overdue eligibility; first on the first eligible reminder date, then every seven local calendar days while still overdue.

Overdue eligibility uses the approved Overdue D0 rule: overdue starts at the borrower-local start of `due_date + grace_period_days + 1 calendar day`. With grace zero, eligibility begins one day after the due date; with grace greater than zero, grace expires first. Recurrence follows the approved seven-day cadence.

### D. Current authoritative terms

Every scheduler run derives from the current authoritative TermsVersion/current due schedule. Accepted extensions immediately replace old future reminder timing. Historical superseded terms must not generate new reminders, and long-lived future reminders must not be precomputed from stale terms.

### E. Verified outstanding

Reminder eligibility requires authoritative verified outstanding greater than zero. Pending or disputed repayments do not reduce verified outstanding. A verified repayment may suppress a reminder when outstanding becomes zero before execution.

### F. Eligible commitment states

Reminder-eligible states are `ACTIVE` and `PARTIALLY_REPAID`. Suppress reminders for `PENDING_CONFIRMATION`, `REJECTED`, `CANCELLED`, `FULLY_REPAID`, and `CLOSED`. There is no automatic `DEFAULTED` transition and no reminder scheduling for no-deadline commitments.

### G. Installment safety

Installment schedule dates may independently drive reminder timing while commitment-level verified outstanding remains positive. Fides MVP has no authoritative repayment-to-installment allocation model, so reminders must not claim that a particular installment is financially unpaid, state a specific installment outstanding amount, or say “₹X overdue installment.” Safe language is schedule/date based, such as “A scheduled payment is due.” An `installment_id` may identify the schedule occurrence only.

### H. Logical reminder identity and dedupe

Each occurrence has deterministic logical identity from `recipient_user_id + reminder_type + commitment_id + installment_id or null + scheduled_local_date`. At most one NotificationEvent may exist for each occurrence. Database uniqueness, not process-local locking alone, must enforce this. The preferred minimal implementation is a nullable `dedupe_key`/`logical_key` on `notification_events` with a unique constraint or index for scheduled reminders; existing mandatory workflow notifications may leave it null. Do not dedupe by querying JSON payload text. Inspect and document the exact migration shape before implementation.

### I. Execution and downtime recovery

Evaluate preferences and authoritative financial state at execution time. If a scheduler runs later on the same logical day, create the still-relevant reminder. Do not create stale historical Upcoming/Due reminders after their applicable day. For overdue recurrence, emit only a currently applicable cadence occurrence; never flood historical reminders after downtime.

### J. Concurrency

Multiple scheduler instances may race. Correctness must rely on the database uniqueness rule; duplicate insertion attempts resolve as already-created/no-op behavior. Do not create duplicate visible reminders. No financial locks are required merely to create reminder notifications.

### K. Transaction and failure semantics

Reminder creation uses short independent transactions. Reminder failure must never roll back a commitment, repayment, or verification; alter terms; create ledger side effects; or change financial state. Notifications remain workflow aids only.

### L. Actor and payload

Scheduled reminders are system-generated; do not fabricate a human actor. Use the current schema’s safe system/null actor representation as appropriate. Payloads remain minimal and authorized and contain no phone numbers, private notes, evidence, tokens, secrets, or internal audit metadata.

### M. Read state

Use existing inbox semantics: `read_at` null means unread and non-null means read. Mark-read is owner-only and repeated mark-read is safe. There is no mark-unread, delete, dismiss, or read-all operation.

### N. Retention

Ordinary in-app notifications, including reminders, use 90-day retention from `created_at`; read/unread status does not extend retention. Cleanup must never touch commitments, terms, repayments, ledger, audit, or financial state. Future reminder candidates derive from current state and are not lost merely because old notification rows expire.

### O. Core invariant

The scheduler derives eligibility from current authoritative server state at execution time, creates at most one notification for each logical reminder occurrence, and can fail, retry, overlap, or run late without changing financial state or producing duplicates.

## Notification Preferences T0 — APPROVED

### A. Endpoints

`GET /api/v1/notification-preferences` and `POST /api/v1/notification-preferences`. There is no PATCH endpoint in MVP.

### B. Response

The exact object is:

```json
{
  "due_reminders_enabled": true,
  "overdue_reminders_enabled": true
}
```

Only these two fields exist in MVP. There is no email, SMS, push, quiet hours, digest, per-commitment preference, global all-notifications-off, or mandatory-workflow control.

### C. Defaults

Defaults are `due_reminders_enabled = true` and `overdue_reminders_enabled = true`. GET with no stored row returns these defaults, remains side-effect free, and does not create a row.

### D. Persistence

Add dedicated `notification_preferences` persistence. Recommended fields are `user_id`, the two booleans, `created_at`, and `updated_at`. `user_id` is the users PK/FK; one row maximum exists per user; booleans are non-null and default true; no JSON settings blob is used. Inspect exact migration details before implementation.

### E. GET semantics

The authenticated current user only, with no query parameters. An existing row returns stored values; no row returns defaults. No user ID appears in the path or body.

### F. POST semantics

The body must contain both required fields:

```json
{
  "due_reminders_enabled": true,
  "overdue_reminders_enabled": true
}
```

This is complete replacement of the two-field object and returns the stored authoritative object. There is no partial update.

### G. Upsert

POST is a server-authoritative upsert: insert when absent and update when present. Repeated identical POST is safe. No Idempotency-Key is required because full-object replacement is naturally idempotent.

### H. Validation

Accept strict booleans only. Reject null, strings such as `"true"`, integers such as `1`, and extra fields. Use the existing closed-schema backend validation style.

### I. Authorization

Only the authenticated user may read or write their own preferences. There is no target user_id, actor field, admin override endpoint, or cross-user access. Normal active-account/session rules apply.

### J. Mandatory workflow notifications

Preferences control reminders only. They never suppress mandatory workflow notifications, including commitment proposal/confirmation/rejection, repayment verification request/verified/disputed, extension requested/accepted/rejected, and mutual closure requested/accepted/rejected once implemented.

### K. B11-R mapping

`due_reminders_enabled` controls `UPCOMING_DUE` and `DUE_TODAY`. `overdue_reminders_enabled` controls `OVERDUE`. Nothing else is controlled.

### L. Evaluation timing

Read preferences at reminder execution time. If disabled before candidate generation, skip creation. If later re-enabled, do not backfill stale historical reminders; resume only currently relevant/future behavior.

### M. Concurrency

Concurrent POSTs are safe. Database uniqueness on `user_id` prevents duplicate rows; last committed write wins. No financial/advisory locks are required.

### N. Transaction and financial isolation

Preference writes affect preferences only. They must not alter commitments, repayments, already-delivered notifications, or financial state, and must not create ledger events. No financial audit event is required.

### O. History and retention

There is no immutable preference version history in MVP; `updated_at` is sufficient operational state. Preference rows are account configuration, not ordinary NotificationEvent records, so 90-day notification retention does not apply.

### P. Account deactivation

No special preference deletion behavior is required. Deactivated users follow normal account/session eligibility and stop receiving new ordinary reminder delivery. Broader account-erasure policy is separate.

### Q. Migration

Use one additive Alembic migration for `notification_preferences` during implementation; no destructive migration and no rewriting of existing NotificationEvent rows. B11-R dedupe and preference schemas may be implemented in one later batch if reviewed together, but remain logically distinct concerns.

### R. API errors

Use existing common API error behavior for unauthenticated, validation, and safe server/database errors. Do not invent preference-specific public error codes unless a demonstrated need appears.

### S. Core invariant

Notification Preferences control only optional reminder delivery. They never suppress mandatory workflow notifications and never affect financial state.

## B11-R and Notification Preferences implementation order

1. Approved docs checkpoint.
2. Read the current merged notification schema/model/API/tests.
3. Inspect the exact migration head and current notification implementation.
4. Produce a bounded implementation plan.
5. Implement additive preference persistence and API.
6. Implement reminder dedupe persistence.
7. Implement scheduler/job.
8. Implement retention cleanup if included in the approved batch.
9. Focused tests.
10. Full backend regression.
11. Final review.
12. Promote/merge only after review.

No implementation begins before this docs checkpoint is committed.

## B11-R and Notification Preferences stop conditions

Stop before proceeding if implementation requires a destructive migration; a change to financial semantics or commitment/repayment state machines; repayment-to-installment allocation logic; new broker/queue infrastructure; Redis, Celery, Kafka, or RabbitMQ; a new notification channel/provider; push, email, or SMS; auth redesign; a new dependency unless strictly required and approved; API behavior outside these contracts; frontend implementation; or automatic `DEFAULTED` behavior.

## Notification Reminder Response Compatibility D0 — APPROVED

### A. New notification types

Add support for `UPCOMING_DUE`, `DUE_TODAY`, and `OVERDUE`. Existing notification types remain unchanged.

### B. System reminder actor

Scheduled reminders are system-generated. For the three reminder types only, `actor = null`. Do not fabricate a fake user, “Fides”, “System”, or a synthetic human actor.

### C. Existing workflow actors

All existing human/workflow notification types preserve their current non-null actor projection exactly as today. Do not weaken existing workflow response guarantees.

### D. Resource IDs

For reminder notifications, `commitment_id` is the affected commitment, while `repayment_id` and `extension_request_id` are null. Any other unrelated resource IDs remain null unless genuinely applicable.

### E. Response compatibility

Keep all other existing notification response fields and semantics unchanged. Do not redesign pagination, read state, ordering, cursor behavior, status semantics, or ownership rules.

### F. Reminder payload

Reminder storage/projection may use minimal server-controlled metadata such as `terms_version_id`, `installment_id` or null, and `scheduled_local_date`. Do not include phone numbers, free-form private notes, repayment evidence, authentication tokens, secrets, fabricated installment outstanding amounts, or repayment-to-installment allocation claims.

### G. Historical readability

Reminder creation eligibility is evaluated using current authoritative state. Once a reminder `NotificationEvent` is created, later repayments, extensions, term changes, and commitment progression must not make that historical reminder unreadable. Historical projection must remain stable and safe.

### H. Frontend coordination

Frontend implementation is separate. The frontend track must later accept `UPCOMING_DUE`, `DUE_TODAY`, and `OVERDUE`; allow actor null for these types only; avoid dereferencing `actor.display_name` for system reminders; preserve existing human notification rendering; navigate reminder notifications to the commitment; and not generate reminder eligibility client-side. Do not modify frontend in this checkpoint or backend implementation task.

### I. Overdue cadence clarification

For overdue reminders, `E = due_date + grace_period_days + 1` calendar day. For current borrower-local date `T`, `S = E + 7 × floor((T - E).days / 7)` is the one currently applicable overdue cadence occurrence. Do not enumerate every missed historical overdue reminder; create at most the currently applicable occurrence. Overlapping scheduler runs rely on database dedupe. Upcoming/due reminders never backfill after their applicable local date.

### J. Core invariant

System reminder notifications are distinguishable from human workflow notifications without fabricating an actor, while preserving all existing workflow response behavior and keeping historical reminder rows safely readable.

## B11-R / Notification Preferences implementation record

The approved T0 and Response Compatibility D0 contracts are implemented with additive revision `013` (parent `012`). This adds the preference table, nullable `VARCHAR(160)` dedupe key, named unique/CHECK constraints, and notification retention index. No commitment scan index was added without demonstrated need. Existing workflow rows are not rewritten. Upgrade refuses pre-existing reminder rows; downgrade refuses populated preferences or keyed/reminder rows until an operator explicitly archives/removes that new data.

The current-user GET/POST preference API uses strict complete booleans, side-effect-free true/true defaults, current-session revalidation, and PostgreSQL upsert/RETURNING. Mandatory workflow notification creation does not consult preferences.

The one-shot command is `python -m app.jobs.reminders` from `backend/`. A finite UUID frontier and pages of up to 100 commitments bound memory. Financial inputs, current effective terms, recipient activity, preferences, and schedules are batched into a single statement snapshot. The existing `validate_terms` and exact `accounting` helpers are reused. Final INSERT SELECT rechecks the validated state and execution-time current terms/local day, with no explicit financial/advisory locks. PostgreSQL uniqueness and normal FK enforcement handle overlap. Corrupt candidates fail closed with bounded diagnostics and a non-zero partial-failure job exit.

Reminder identity is `r1|recipient_uuid|type|commitment_uuid|installment_uuid_or_-|YYYY-MM-DD`. Only conflicts on `uq_notification_events_dedupe_key` are no-ops. Overdue uses `E = due_date + grace_period_days + 1 calendar day` and `S = E + 7 * floor((T - E).days / 7)` for borrower-local `T >= E`; only S is emitted. No stale Upcoming/Due backfill occurs. Contractual due timezone is preserved. Current-version installments provide dates/identity only, with no payment allocation or financial unpaid claim.

System reminder projection has null actor and commitment-only targeting; existing workflow actors remain non-null. Historical reminder readability depends on ownership/static provenance, not later repayment, terms, or commitment eligibility. Existing inbox ordering, cursor/read behavior, and workflow atomicity are preserved.

The separate one-shot command `python -m app.jobs.notification_cleanup` removes only NotificationEvent rows strictly older than 90 days, read/unread equally, in short SKIP LOCKED transactions of up to 1,000 rows and at most 100 batches per invocation. Preferences, financial objects, ledger, and audit are unaffected. Production cleanup should use a separately privileged maintenance credential; B15 owns scheduling, monitoring, and production least-privilege validation.

Operational details and frontend coordination are documented in `docs/reminders.md`. Frontend reminder type/null-actor support is a separate track and must precede enabling reminder delivery. No frontend, auth redesign, financial semantics, B13 lock/idempotency behavior, broker, channel/provider, or dependency changes are included.

Validation on the existing local `fides_test` PostgreSQL database: 129 focused reminder/preference tests passed, including 16 concurrency, 7 migration, and 9 retention tests; the existing notification HTTP/OpenAPI contract suite passed all 36 tests. The final full backend regression passed 2,762 tests with zero failures or skips, covering mandatory workflows, B2-B14 regressions, and financial invariants. Alembic repository/test-database head is `013`; migration tests verify `012 -> 013`, preserved workflow data, metadata/constraints, pre-existing reminder refusal, and downgrade data-loss guards. Both one-shot job commands exited 0 on an empty test inbox, with zero created/deleted rows.

Ruff and formatter checks passed for all 31 changed/new Python files; `pip check` and `git diff --check` passed. No separate type checker is configured. Repository-wide Ruff retains seven pre-existing I001 import-order findings in unchanged B12 summary tests; they are outside this change. The existing Starlette/AnyIO BlockingPortal deprecation warning is non-blocking. B15 scheduling/least privilege and separate frontend reminder compatibility remain release coordination items.

## Mutual Closure D0 — APPROVED

Mutual Closure is not repayment. It represents both parties explicitly agreeing to close an outstanding commitment with the remaining verified outstanding amount waived. `FULLY_REPAID` means verified repayments reduced outstanding to zero; `CLOSED` means the parties mutually agreed to waive the remaining verified outstanding. User-facing wording is “Closed by mutual agreement”; CLOSED must never be presented as fully repaid.

A closure request may be created only for `ACTIVE` or `PARTIALLY_REPAID` commitments. It is not allowed for `PENDING_CONFIRMATION`, `REJECTED`, `CANCELLED`, `FULLY_REPAID`, `CLOSED`, or `DEFAULTED`. No automatic relationship to Connection state is required.

Either borrower or lender may propose. The other party must accept; there is no unilateral forgiveness and the requester cannot accept their own request. The requester may cancel while `REQUESTED`; the counterparty may accept or reject. At most one `REQUESTED` request exists per commitment, while historical `ACCEPTED`, `REJECTED`, and `CANCELLED` requests remain auditable.

Each request targets the full current authoritative verified outstanding amount. There is no custom partial waiver or user-entered waiver amount. The server derives `outstanding_snapshot_minor` and `waived_amount_minor`; at creation the waived amount equals authoritative verified outstanding, in the commitment currency. Pending repayment verification blocks final acceptance. Disputed repayments remain historical and do not reduce authoritative verified outstanding.

Acceptance must lock and revalidate the authoritative commitment state, recompute verified outstanding, verify no pending verification blocks closure, verify eligibility, and compare the recomputed value with the stored snapshot. If it differs, acceptance returns a conflict and does not silently adjust the waiver. Successful acceptance atomically marks the request `ACCEPTED`, transitions the commitment to `CLOSED`, sets `closed_at`, records the authoritative waived amount, appends a closure ledger event, and preserves repayment/dispute history. CLOSED is terminal for new repayment reporting, verification, extension, closure, and other live financial mutations. Frontend presentation must show verified repayments and waived amount separately; no repayment or verification row represents the waiver. CLOSED commitments are excluded from active outstanding summaries while history remains available.

## Mutual Closure Technical Contract T0 — APPROVED

Routes:

- `POST /api/v1/commitments/{id}/closure-requests`
- `GET /api/v1/commitments/{id}/closure-requests`
- `GET /api/v1/closure-requests/{id}`
- `POST /api/v1/closure-requests/{id}/accept`
- `POST /api/v1/closure-requests/{id}/reject`
- `POST /api/v1/closure-requests/{id}/cancel`

There is no PATCH route. Add the dedicated `mutual_closure_requests` table with UUID/timestamp conventions and fields `id`, `commitment_id`, `requested_by_user_id`, `counterparty_user_id`, `status`, `currency`, `outstanding_snapshot_minor`, `waived_amount_minor`, `note`, `decided_by_user_id`, `decided_at`, `created_at`, and `updated_at`. Statuses are `REQUESTED`, `ACCEPTED`, `REJECTED`, and `CANCELLED`; database enforcement should ensure one REQUESTED row per commitment. Exact migration details must be inspected against the current migration head before implementation.

Create is participant-only and either participant may request when the commitment is eligible, verified outstanding is positive, and no REQUESTED request exists. The server determines counterparty, currency, snapshot, and waiver. The optional note is at most 500 characters; no client financial amount is accepted. Use existing idempotency conventions where applicable.

List is participant-only and returns historical requests in stable order. Detail is participant-only with generic unavailable/IDOR-safe behavior. Accept is counterparty-only and must lock/revalidate users/resources using current Fides lock order, require REQUESTED and eligible state, reject pending verification, recompute outstanding, and compare the snapshot. A mismatch returns conflict, leaves the request REQUESTED, and requires a fresh proposal after cancellation or rejection as appropriate. Success sets the decision fields, closes the commitment, and appends `MUTUAL_CLOSURE_ACCEPTED` atomically.

Reject is counterparty-only and transitions REQUESTED to REJECTED without financial-state changes, appending `MUTUAL_CLOSURE_REJECTED`. Cancel is requester-only and transitions REQUESTED to CANCELLED without financial-state changes, appending `MUTUAL_CLOSURE_CANCELLED`. Creation appends `MUTUAL_CLOSURE_REQUESTED`. Do not emit `REPAYMENT_REPORTED` or `REPAYMENT_VERIFIED` for closure.

Ledger payloads contain only minimal authoritative closure references/state required for historical projection; private notes and unnecessary sensitive/free-form data are excluded. Protect simultaneous creates, accept/reject/cancel, repayment or verification races, extension races, replayed mutations, stale snapshots, and double close using existing B13 lock ordering and idempotency conventions. Replays return the original authoritative result and conflicting keys preserve `IDEMPOTENCY_CONFLICT` semantics.

Only commitment participants may access closure requests. Create is either participant; accept/reject are counterparty-only; cancel is requester-only. Authoritative outstanding remains obligation minus VERIFIED repayments. Closure is a separate waiver and does not alter accounting helper semantics or represent repayment. Accepted closure sets `Commitment.status = CLOSED` and `closed_at` at acceptance time; CLOSED is terminal for new financial actions while history remains readable.

Use an additive, non-destructive migration after inspecting the post-B11-R migration head. Do not rewrite historical commitment or repayment data. Required validation includes eligibility and role rules, one pending request, note and amount derivation, verified/pending/disputed semantics, IDOR, idempotency, snapshot conflict, repayment/verification/extension races, double and competing transitions, CLOSED-state blocking, ledger events, history, summaries, and no fake repayment. Acceptance must close only when both parties explicitly agree to waive exactly the same server-authoritative verified outstanding amount revalidated atomically.

Implementation flow is: docs checkpoint; read-only audit; inspect migration head, B13 locks/idempotency, accounting and verification; bounded plan; additive persistence/API/service; ledger projection; CLOSED integration; concurrency/idempotency tests; focused and full regression; review; then merge only after approval. Stop if implementation requires changing accounting, representing waiver as repayment, changing B13 lock order, destructive migration, a new dependency or broker, automatic DEFAULTED behavior, unilateral forgiveness, partial custom waiver, frontend work, unrelated API redesign, or custody/payment movement.

### Mutual closure implementation evidence — 2026-10-03

Migration `014` follows `013`, adding the dedicated closure table/status enum,
non-cascading foreign keys, full-waiver/decision checks, one REQUESTED request
per commitment, and the history-order index. Downgrade refuses closure rows,
ledger/audit/notification provenance or closure endpoint idempotency records.
The six approved routes use strict normalized notes, existing authentication,
parent participant authorization and endpoint-scoped 30-day idempotency.

Acceptance reuses `repayment_accounting` and `validate_history` under idempotency
→ sorted Users → Commitment → ClosureRequest locks. Pending verification or an
exact snapshot mismatch produces CONFLICT without changing the proposal.
Successful acceptance closes the parent and commits closure, ledger, audit,
mandatory workflow notification and replay response atomically. Reject/cancel
preserve stale-request resolution; cancellation has no notification. Ledger
storage contains references/status only and historical REQUESTED projection
survives decisions. Notes stay confined to participant closure responses.

CLOSED is excluded from summary outstanding; existing financial mutation
guards, extension rejection, reminder eligibility, accounting formulas, B13
behavior, frontend and dependencies are preserved. B14 direct-path admission,
malformed JSON, correlation and no-store conventions cover closure routes.
Focused coverage includes 22 PostgreSQL concurrency tests and 27 migration/model
tests. One focused self-review added a fail-closed check tying an ACCEPTED
request to the parent's CLOSED state and matching closure timestamp. Runtime
permissions are documented separately; no role provisioning is executed.

Final validation: 262 focused closure tests passed, including 22 real PostgreSQL
race tests and 27 migration/model tests. The required relevant regression groups
passed 1,729 tests; the final full backend run passed 3,024 tests with zero
failures and zero skips. Ruff and formatter checks passed on all 36 changed/new
Python files; pip check and git diff --check passed. Repository and isolated
fides_test Alembic heads are 014. The existing commitment OpenAPI route assertion
was extended for the approved nested closure routes. An interrupted run's
identified fixture records were cleaned only from fides_test before the final
run. The existing Starlette deprecation warning and six import-order findings
in untouched B12 tests remain non-blocking; one previously affected B12 file
was necessarily updated for CLOSED exclusion and now passes changed-file checks.
