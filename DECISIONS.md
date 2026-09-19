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
