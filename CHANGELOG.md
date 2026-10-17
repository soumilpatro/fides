# Changelog

This file summarizes notable project changes; for complete technical history see Git commits and pull requests.

## Unreleased — Public repository preparation

- Added a public-facing project overview, setup instructions, security guidance, contribution guidance and publication checklist.
- Expanded local secret/build-artifact ignore patterns (does not remove files already tracked or from history).
- Configured existing frontend validation workflow to run on pull requests and pushes to `main`.
- No production financial functionality changed as part of this release-preparation documentation.

## Previous milestone

- PR #22: preserved mobile navigation and form drafts through session reconciliation; automated frontend validation reported 806 passing tests. Physical iPhone retesting remains a separate release gate.
