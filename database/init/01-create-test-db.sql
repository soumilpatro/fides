-- FIDES local Postgres initialization (B1)
--
-- The official postgres image only creates the database named by
-- POSTGRES_DB (fides_dev) on first init. This script creates the second,
-- fully isolated test database (fides_test) so automated tests never run
-- against development data, per the approved B1 test-database decision.
--
-- Runs once, only on first container initialization (empty data volume).
--
-- The pgcrypto extension itself is created by Alembic migration 001
-- (001_extensions_enums), run separately against each database, so schema
-- provisioning stays entirely within the migration chain rather than being
-- split across this init script and Alembic.

CREATE DATABASE fides_test OWNER fides;
