# Contributing to Fides

Thanks for your interest. Fides is an early-stage financial recordkeeping MVP with strict accounting and privacy requirements.

## Before contributing

- Open an issue to discuss nontrivial feature changes and API/schema changes before implementation.
- Never include production credentials, real user/repayment records, private phone numbers, or sensitive debugging logs.
- Treat financial state and authorization as **server-authoritative**; never reduce outstanding for unverified repayments.
- Preserve the independence of commitments, separate waiver accounting, and participant-authorization rules.
- Coordinate any schema change with Alembic migrations, tests, and existing API contracts.
- Future concepts (coordinated funding, Trust Profiles, AI insights, payments) are not implemented features and should not be added without an approved specification.

## Development workflow

1. Create a branch for your change.
2. Follow [README.md](README.md) for local development.
3. Add or revise regression tests for behavior changes, including negative permission and state-transition cases.
4. Run the relevant frontend/backend checks.
5. Open a focused pull request describing the change, tests, risk and manual validation required.

**Security reports must be private:** see [SECURITY.md](SECURITY.md).

## Licensing

No open-source license has yet been selected. Do not assume that repository visibility constitutes permission to reuse code; coordinate licensing and contribution rights with the repository owner before substantial external contributions.
