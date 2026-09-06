"""FIDES backend application package.

B0 scope only: application factory, configuration, health/readiness
endpoints, structured logging, and error-handling foundations.

No domain logic (users, connections, commitments, repayments, ledger,
etc.) is implemented at this stage. See:
- FIDES_AI_DEVELOPMENT_BACKEND_BUILD_SPECIFICATION_v1.0 (build order B0-B15)
- FIDES_TECH_SPECIFICATION_v1.1_APP_WEB_BACKEND (architecture)
"""
