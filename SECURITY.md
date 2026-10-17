# Security Policy

Fides records sensitive information about peer financial commitments. **Do not post suspected vulnerabilities, private account information, access tokens, provider credentials, or production data in a public issue.**

## Reporting

Until a dedicated private security contact is configured, use GitHub's **private vulnerability reporting** feature on this repository if enabled. If it is not enabled, contact the repository owner through an existing private channel. Do not disclose a reproducible security issue publicly before the maintainer has an opportunity to respond.

## Supported deployments

This repository describes an MVP, not a certified or production-hardened banking system. The maintainer currently prioritizes the `main` branch; no formal security-support SLA or guaranteed remediation timeline is offered.

## Security boundaries

- No money transfer or custody; Fides records external commitments.
- Backend owns financial state and participant authorization.
- A repayment report is distinct from a counterparty-verified repayment.
- Never put API secrets, Twilio keys, HMAC secrets, real database URLs, user records, or personal phone numbers in Git or screenshots.
- Client-prefixed environment variables are **public** and not secret storage.
- Local fake OTP and Docker credentials must not be used on public deployments.
- Do not treat a successful test suite as a penetration test.

For deployment configuration and security gates, see [docs/b15-deployment.md](docs/b15-deployment.md).
