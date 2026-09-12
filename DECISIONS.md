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
