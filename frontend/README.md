# Fides frontend — F0

Two presentation clients, one authoritative FastAPI backend. This batch contains
only the app shells, separate platform primitives, and a foundation preview.
The preview makes **no backend requests** and uses no stored session or product data.

## Structure

```text
frontend/
  package.json, package-lock.json, eslint.config.mjs
  shared/
    tokens/       approved colors, spacing, radii, typography
    api/          CurrentUser DTO, errors, request primitive
    domain/       display-only money formatting and status vocabulary
  web/
    app/          Next.js root layout, preview page, global CSS
    components/   independent DOM ui/ and shell/
    features/auth/session/  controlled auth context and storage interface
    api/          environment-bound client factory
  mobile/
    index.ts, app.json
    app/          Expo root and foundation screen
    navigation/   single-screen root (no product routes)
    components/   independent React Native ui/ and shell/
    features/auth/session/  controlled auth context and storage interface
    api/          environment-bound client factory
```

## Install and run

Use Node 24 LTS and npm 11 or newer. From `frontend/`:

```sh
npm ci
npm run web
npm run mobile
```

Web: http://localhost:3000. Mobile: Expo Metro, then open with a compatible
SDK 57 Expo Go/development client on Android or iOS. Press `a` for a configured
Android emulator; iOS Simulator requires macOS. No app icon has been selected.
For Expo's browser-based **mobile component preview** (not the Fides web app):

```sh
npm run start --workspace=@fides/mobile -- --web --localhost --port 8081
```

For CLI options, target a workspace directly (one level of npm argument forwarding):

```sh
npm run dev --workspace=@fides/web -- --hostname 127.0.0.1
```

## Environment

No environment variables or running backend are required for the preview.
When a later approved feature constructs an API client, copy the corresponding
`.env.example` into `web/.env.local` or `mobile/.env` and set:

- Web: `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1`
- Mobile: `EXPO_PUBLIC_API_BASE_URL=http://<development-host>:8000/api/v1`

A physical device cannot reach the computer through `localhost`; use a reachable
host address. Production API transport must use HTTPS. These variables are public
configuration, never secrets. Backend CORS/same-origin deployment configuration is
not implemented or selected here; no backend configuration is changed for F0.

API factories accept an optional access-token source. Requests are relative to
the configured `/api/v1` base, serialize JSON, normalize backend error envelopes,
and accept an optional caller-supplied idempotency key and abort signal. They never
retry, refresh, log payloads, follow redirects, or persist financial facts.
Generic TypeScript response types describe wire contracts; they are not runtime
JSON validation. No product endpoints are invented or called. CurrentUser matches
checked-in B2 MeResponse, not the superseded register/login sketches in the old spec.

## Sharing and authority

Only tokens, DTOs, error/request primitives, and pure display helpers are shared.
DOM and React Native components, navigation, accessibility, auth contexts and
session-store interfaces remain platform-specific. No state-management framework,
UI library, API generator, test framework, or monorepo build system is added.

Money display accepts safe integer minor units with an explicit currency, rejects
unsafe values, and formats without aggregating or deriving balances. A reported or
disputed repayment never means verified. Connections never imply financial access.
The server owns authorization, calculations, independent commitments, lifecycle,
repayment allocation and verified outstanding. No B12 response shape is assumed.

## Dependencies

- Next.js, React, React DOM: web application runtime.
- Expo, React Native: mobile application runtime; versions follow the official
  Expo TypeScript template and SDK bundled dependency manifest.
- expo-font and the Manrope/Inter font asset packages: bundled approved typography,
  also served locally by Next.js (no runtime Google Fonts requests).
- expo-status-bar, react-native-safe-area-context: platform status bar and safe areas.
- react-native-web and matching react-dom in mobile: Expo browser rendering for
  foundation checks on hosts without a native emulator; no shared UI abstraction.
- TypeScript and React/Node type packages: strict static checks.
- ESLint and eslint-config-next: web/shared lint checks.
- npm workspaces and one lockfile: standard package linking without custom tooling.

## Design source and unresolved items

The five supplied colors and the subsequently supplied layout/type scale are
approved inputs for this batch. Spacing: 4, 8, 12, 16, 24, 32, 40, 48, 64.
Chosen category radii: 8 / 12 / 16 / 20 / 999. Type sizes: 32 title, 20 section,
16 body, 14 supporting, 12 metadata, 11 micro; amounts 40 / 24 / 18. Controls 48.
Borders define surfaces; shadows are intentionally omitted. Surface currently
aliases Canvas, avoiding an invented surface color. Responsive widths are layout
constraints, not additional design-system color or spacing tokens.

Still unresolved:

- semantic status colors (verified/pending/disputed/overdue/closed), muted text and
  additional surface values: **not invented**; StatusChip is neutral and examples
  do not imply financial status styling;
- final dark palette: **not invented**; named tokens make later theming possible;
- TD-012 web/mobile credential persistence: interfaces only, no adapter,
  localStorage, SecureStore, cookie policy, session recovery or token refresh;
- final branding/logo/app icon: **not selected**; text-only FIDES wordmark;
- native-device visual validation requires a compatible device/emulator;
- CORS/deployment routing must be approved with the first network feature.

AuthProvider is a controlled state seam (loading/anonymous/authenticated), defaulting
to anonymous. There is no login, registration, logout request, route guard or
credential persistence. F1 and all product screens are intentionally absent.

## Validation

```sh
npm run lint
npm run typecheck
npm run build:web
npm run config --workspace=@fides/mobile
cd mobile
npx expo install --check
npx expo export --platform android --output-dir dist/android
npx expo export --platform ios --output-dir dist/ios
```

Browser checks cover rendering, input/button/reset behavior, disabled controls,
keyboard focus and narrow-screen layout. Expo web preview is supplemental and
must not be presented as Android/iOS device validation. No existing frontend test
setup was present, so no Jest/Vitest/Storybook framework was introduced. Backend
isolation is checked via Git; the full backend test suite is not run for F0.
