# Public repository release gate

**Status: NOT CLEARED.** This document is a checklist, not certification that Fides is safe to publish.

## Before changing visibility

- [ ] Review every reachable commit, tag, deleted file, and PR branch for secrets, tokens, credentials, real phone numbers, OTPs, database exports, personal data, internal documents and privileged hostnames.
- [ ] Run an independently configured full-history secret scanner (for example Gitleaks or TruffleHog) on a full clone, and manually investigate findings. Scanning only the working tree is inadequate.
- [ ] Audit `DECISIONS.md` and all five root `FIDES_*SPECIFICATION*.docx` documents for confidential internal information, third-party content and personal data. Decide whether they should be included in a public repository at all; removal from current `main` alone does not erase history.
- [ ] Review old test fixtures, git patches, commit messages, issues and pull requests for real user information or pasted secrets.
- [ ] Rotate any secrets found in history or previously shared. Invalidate old Twilio API credentials, HMAC signing keys, database passwords and deployment tokens as applicable.
- [ ] If sensitive material exists in Git history, coordinate a deliberate history rewrite using tools such as `git filter-repo`; verify the resulting repository and external references. **Do not rewrite shared history casually.** Even after rewriting, assume already-cloned secrets are compromised.
- [ ] Verify no tracked `.env`, exported data, key stores, certificates, or binary credentials. `.gitignore` does not untrack existing files.
- [ ] Verify no live configuration depends on the development-only credentials in `docker-compose.yml`.
- [ ] Confirm all logos, image assets and specification documents can legally be published.
- [x] Record maintainer's licensing preference: publicly viewable, **all rights reserved** (see `RIGHTS.md`).
- [ ] Confirm copyright ownership and written permission from teammates/third-party asset rights holders before public release.
- [ ] Enable GitHub secret scanning / push protection where available, Dependabot alerts, private vulnerability reporting and reasonable branch rules.
- [ ] Run frontend checks and backend tests with an isolated test database; do not run tests against a real production or staging dataset.
- [ ] Inspect PR #22's mobile navigation fix on physical iPhones (background/resume, drafts, open modal, logout and account switch). Automated tests are not a substitute.
- [ ] Check documentation instructions against a fresh clone without secrets; ensure no production hostname or internal credential is required to run the demonstration safely.
- [ ] Double-check public deployment behavior, CORS, error payloads, admin-only routes, rate limits and logging for disclosures.
- [ ] Approve a final publication review of the actual repository contents **and its history** before changing GitHub visibility.

## After making it public

- [ ] Review the public GitHub landing page and README as an anonymous visitor.
- [ ] Confirm link targets, repository topics, description, branch protection and CI are appropriate.
- [ ] Monitor security alerts and replace any inadvertently disclosed credential immediately.

**The GitHub connector used for these documentation changes cannot switch repository visibility.** Complete the visibility change in GitHub Settings → General → Danger Zone → Change repository visibility only after this gate is cleared.
