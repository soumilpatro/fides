-- PREPARATION ONLY: not executed by this checkpoint. psql 16+, PostgreSQL 16+.
-- Use a dedicated staging database and an authorized provisioning administrator.
-- Required non-secret psql variables: FidesDatabase, FidesSchema, FidesPhase.
-- FidesPhase=bootstrap BEFORE Alembic; FidesPhase=grants AFTER head 014.
-- Bootstrap additionally requires FidesMigratorPassword, FidesApiPassword,
-- FidesRemindersPassword, FidesNotificationCleanupPassword via a protected input
-- mechanism (not shell command-line arguments/history). Existing passwords are
-- NEVER changed. All four variables are required even on a bootstrap rerun.
-- Run psql with -X, no client/server/proxy SQL tracing. This script disables
-- standard session statement/error/duration logging BEFORE sending passwords;
-- insufficient permission to do that aborts. DBA must additionally rule out
-- audit extensions/proxy capture. VERBOSITY terse avoids secret-bearing CONTEXT.
-- No grants to future tables, no data deletion, no ownership transfer/reassignment.
-- Operator order: bootstrap -> Alembic as fides_migrator -> grants -> standalone
-- verify-staging-roles.sql -> credential smoke checks before enabling services.
\set ON_ERROR_STOP on
\set ECHO none
\set ECHO_HIDDEN off
\set VERBOSITY terse
\if :{?FidesDatabase}
\else
  \echo 'Missing FidesDatabase'
  DO $missing$ BEGIN RAISE EXCEPTION 'Required psql variable missing'; END $missing$;
\endif
\if :{?FidesSchema}
\else
  \echo 'Missing FidesSchema'
  DO $missing$ BEGIN RAISE EXCEPTION 'Required psql variable missing'; END $missing$;
\endif
\if :{?FidesPhase}
\else
  \echo 'Missing FidesPhase (bootstrap or grants)'
  DO $missing$ BEGIN RAISE EXCEPTION 'Required psql variable missing'; END $missing$;
\endif

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SELECT set_config('fides.database', :'FidesDatabase', true) AS db_context,
       set_config('fides.schema', :'FidesSchema', true) AS schema_context,
       set_config('fides.phase', :'FidesPhase', true) AS phase_context
\gset

DO $preflight$
DECLARE
    db_name text := current_setting('fides.database');
    schema_name text := current_setting('fides.schema');
    phase text := current_setting('fides.phase');
    role_names text[] := ARRAY['fides_migrator', 'fides_api',
        'fides_reminders', 'fides_notification_cleanup'];
BEGIN
    IF phase NOT IN ('bootstrap', 'grants') OR db_name = '' OR schema_name = ''
       OR octet_length(schema_name) > 63 OR schema_name ~ '^pg_'
       OR schema_name = 'information_schema' OR current_database() <> db_name THEN
        RAISE EXCEPTION 'Invalid phase/database/schema or wrong connected database';
    END IF;
    IF current_user = ANY(role_names) THEN
        RAISE EXCEPTION 'Use a separate authorized provisioning administrator';
    END IF;
    IF current_setting('server_version_num')::int < 160000 THEN
        RAISE EXCEPTION 'This preparation targets PostgreSQL 16 or later';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_available_extension_versions
                   WHERE name = 'pgcrypto' AND trusted) THEN
        RAISE EXCEPTION 'Trusted pgcrypto must be available; review provider prerequisites';
    END IF;
    -- Refuse unknown existing role attributes rather than silently resetting them.
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = ANY(role_names)
               AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls
                    OR rolreplication OR rolinherit OR NOT rolcanlogin
                    OR rolvaliduntil IS NOT NULL)) THEN
        RAISE EXCEPTION 'Existing role attributes require explicit administrator review';
    END IF;
    -- Cross-membership within the four names is revoked below. Unknown authority
    -- is refused, not removed from unrelated administrator/application roles.
    IF EXISTS (
        SELECT FROM pg_auth_members m JOIN pg_roles member ON member.oid = m.member
        JOIN pg_roles authority ON authority.oid = m.roleid
        WHERE member.rolname = ANY(role_names) AND authority.rolname <> ALL(role_names)
    ) OR EXISTS (
        SELECT FROM pg_auth_members m JOIN pg_roles authority ON authority.oid = m.roleid
        JOIN pg_roles member ON member.oid = m.member
        WHERE authority.rolname = ANY(role_names) AND member.rolname <> ALL(role_names)
          AND member.rolname <> current_user
    ) THEN
        RAISE EXCEPTION 'Unknown membership touching a Fides role requires review';
    END IF;
    -- Ownership bypasses ACLs. Detect ALL shared/local owned objects, not just tables.
    IF EXISTS (SELECT FROM pg_shdepend d JOIN pg_roles r ON r.oid = d.refobjid
               WHERE d.refclassid = 'pg_authid'::regclass AND d.deptype = 'o'
                 AND r.rolname IN ('fides_api', 'fides_reminders',
                                  'fides_notification_cleanup')) THEN
        RAISE EXCEPTION 'A runtime role owns objects; no automatic reassignment is safe';
    END IF;
    IF phase = 'grants' AND
       (SELECT count(*) FROM pg_roles WHERE rolname = ANY(role_names)) <> 4 THEN
        RAISE EXCEPTION 'Run bootstrap before grants';
    END IF;
    IF EXISTS (SELECT FROM pg_default_acl a JOIN pg_roles r ON r.oid=a.defaclrole
               WHERE r.rolname='fides_migrator') THEN
        RAISE EXCEPTION 'Custom migrator default ACLs require review before creating objects';
    END IF;
    IF EXISTS (SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname=schema_name AND NOT EXISTS (
            SELECT FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
            WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid
              AND d.deptype='e' AND e.extname='pgcrypto')) THEN
        RAISE EXCEPTION 'Unexpected application routine requires review before migration/grants';
    END IF;
    IF phase = 'bootstrap' AND EXISTS (
        SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = schema_name AND c.relkind IN ('r','p','v','m','S','f')
          AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                          AND d.objid = c.oid AND d.deptype = 'e')
    ) THEN
        RAISE EXCEPTION 'Bootstrap requires an empty application schema; use grants after migrations';
    END IF;
END
$preflight$;

SELECT current_setting('fides.phase') = 'bootstrap' AS bootstrap
\gset
\if :bootstrap
  \if :{?FidesMigratorPassword}
  \else
    \echo 'Missing FidesMigratorPassword'
    DO $missing$ BEGIN RAISE EXCEPTION 'Required psql variable missing'; END $missing$;
  \endif
  \if :{?FidesApiPassword}
  \else
    \echo 'Missing FidesApiPassword'
    DO $missing$ BEGIN RAISE EXCEPTION 'Required psql variable missing'; END $missing$;
  \endif
  \if :{?FidesRemindersPassword}
  \else
    \echo 'Missing FidesRemindersPassword'
    DO $missing$ BEGIN RAISE EXCEPTION 'Required psql variable missing'; END $missing$;
  \endif
  \if :{?FidesNotificationCleanupPassword}
  \else
    \echo 'Missing FidesNotificationCleanupPassword'
    DO $missing$ BEGIN RAISE EXCEPTION 'Required psql variable missing'; END $missing$;
  \endif
  SET LOCAL log_statement = 'none';
  SET LOCAL log_min_error_statement = 'panic';
  SET LOCAL log_min_duration_statement = -1;
  SET LOCAL log_min_duration_sample = -1;
  SET LOCAL log_transaction_sample_rate = 0;
  SET LOCAL password_encryption = 'scram-sha-256';
  SELECT set_config('fides.password_migrator', :'FidesMigratorPassword', true) AS pm,
         set_config('fides.password_api', :'FidesApiPassword', true) AS pa,
         set_config('fides.password_reminders', :'FidesRemindersPassword', true) AS pr,
         set_config('fides.password_cleanup', :'FidesNotificationCleanupPassword', true) AS pc
  \gset
  DO $new_roles$
  DECLARE item record; password_value text;
  BEGIN
      FOR item IN SELECT * FROM (VALUES
          ('fides_migrator', 'migrator'), ('fides_api', 'api'),
          ('fides_reminders', 'reminders'), ('fides_notification_cleanup', 'cleanup')
      ) AS mapping(role_name, setting_suffix) LOOP
          password_value := current_setting('fides.password_' || item.setting_suffix);
          IF btrim(password_value) = '' THEN
              RAISE EXCEPTION 'Required password variable is empty';
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = item.role_name) THEN
              EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                  'NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD %L',
                  item.role_name, password_value);
          END IF;
          -- No ALTER ROLE PASSWORD: reruns never reset existing passwords.
          PERFORM set_config('fides.password_' || item.setting_suffix, '', true);
      END LOOP;
  END
  $new_roles$;
  \unset pm
  \unset pa
  \unset pr
  \unset pc
  \unset FidesMigratorPassword
  \unset FidesApiPassword
  \unset FidesRemindersPassword
  \unset FidesNotificationCleanupPassword
\endif

DO $infrastructure$
DECLARE
    db_name text := current_setting('fides.database');
    schema_name text := current_setting('fides.schema');
    role_name text; other_role text;
    role_names text[] := ARRAY['fides_migrator', 'fides_api',
        'fides_reminders', 'fides_notification_cleanup'];
BEGIN
    FOREACH role_name IN ARRAY role_names LOOP
        FOREACH other_role IN ARRAY role_names LOOP
            IF role_name <> other_role AND EXISTS (
                SELECT FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.roleid
                JOIN pg_roles b ON b.oid=m.member
                WHERE a.rolname=role_name AND b.rolname=other_role
            ) THEN
                EXECUTE format('REVOKE %I FROM %I', role_name, other_role);
            END IF;
        END LOOP;
    END LOOP;
    IF NOT EXISTS (SELECT FROM pg_namespace WHERE nspname = schema_name) THEN
        IF current_setting('fides.phase') <> 'bootstrap' THEN
            RAISE EXCEPTION 'Expected schema missing';
        END IF;
        EXECUTE format('CREATE SCHEMA %I AUTHORIZATION fides_migrator', schema_name);
    END IF;
    -- Dedicated staging only: do not apply these PUBLIC changes to a shared DB.
    EXECUTE format('REVOKE ALL PRIVILEGES ON DATABASE %I FROM PUBLIC', db_name);
    EXECUTE format('REVOKE ALL PRIVILEGES ON SCHEMA %I FROM PUBLIC', schema_name);
    IF schema_name <> 'public' AND EXISTS (SELECT FROM pg_namespace WHERE nspname='public') THEN
        REVOKE CREATE ON SCHEMA public FROM PUBLIC, fides_api, fides_reminders,
            fides_notification_cleanup;
    END IF;
    FOREACH role_name IN ARRAY role_names LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON DATABASE %I FROM %I', db_name, role_name);
        EXECUTE format('REVOKE ALL PRIVILEGES ON SCHEMA %I FROM %I', schema_name, role_name);
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', db_name, role_name);
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', schema_name, role_name);
        -- Deliberate per-database setting; migrations are unqualified. Avoid $user
        -- or a different schema silently receiving Alembic/application objects.
        EXECUTE format('ALTER ROLE %I IN DATABASE %I SET search_path = %I, pg_catalog',
                       role_name, db_name, schema_name);
    END LOOP;
    -- Database CREATE permits trusted pgcrypto installation, not CREATEDB.
    EXECUTE format('GRANT CREATE ON DATABASE %I TO fides_migrator', db_name);
    EXECUTE format('GRANT CREATE ON SCHEMA %I TO fides_migrator', schema_name);
    -- No default grants: newly created tables remain unavailable until reviewed.
    -- Refuse existing default ACL customizations in the verification phase below.
END
$infrastructure$;

\if :bootstrap
  DO $bootstrap_boundary$
  DECLARE role_name text;
  BEGIN
      FOREACH role_name IN ARRAY ARRAY['fides_api','fides_reminders',
          'fides_notification_cleanup'] LOOP
          -- PUBLIC CONNECT/TEMPORARY on another DB is not a role-specific grant.
          -- Membership/SET ROLE and runtime ownership are guarded above.
          -- Inspect every DB, even if connections are currently disabled; never
          -- modify unrelated ACLs or assume provider/template names are trusted.
          IF EXISTS (SELECT FROM pg_database d JOIN pg_roles r ON r.rolname=role_name
              WHERE d.datname<>current_database() AND (
                  d.datdba=r.oid
                  OR EXISTS (SELECT FROM aclexplode(coalesce(d.datacl,
                      acldefault('d',d.datdba))) a WHERE a.grantee=r.oid)
                  OR has_database_privilege(role_name,d.oid,'CREATE')))
             OR EXISTS (SELECT FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%'
              AND n.nspname<>'information_schema' AND has_schema_privilege(role_name,n.oid,'CREATE'))
             OR has_database_privilege(role_name,current_database(),'CREATE,TEMPORARY') THEN
              RAISE EXCEPTION 'Unsafe runtime DB/schema boundary; cluster administrator review needed: %',role_name;
          END IF;
      END LOOP;
  END
  $bootstrap_boundary$;
  -- Service connections remain disabled operationally until migrations/grants/
  -- verification finish. They have no application-table permissions at this point.
  \echo 'Bootstrap prepared; run existing Alembic migrations as fides_migrator next.'
\else
  DO $current_grants$
  DECLARE
      schema_name text := current_setting('fides.schema');
      item record; role_name text; cols text;
      expected_tables text[] := ARRAY['users','auth_identities','connections',
          'commitments','commitment_terms_versions','commitment_installments',
          'repayments','repayment_verifications','ledger_events','audit_logs',
          'idempotency_keys','notification_events','extension_requests','auth_sessions',
          'auth_otp_challenges','auth_rate_limit_buckets','notification_preferences',
          'mutual_closure_requests','alembic_version'];
  BEGIN
      IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname=schema_name AND c.relkind='r'
            AND c.relname=ANY(expected_tables)) <> cardinality(expected_tables) THEN
          RAISE EXCEPTION 'Expected migration-014 tables missing';
      END IF;
      IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                 WHERE n.nspname=schema_name AND c.relkind IN ('r','p','v','m','S','f')
                   AND c.relname <> ALL(expected_tables)) THEN
          RAISE EXCEPTION 'Unexpected relation/sequence: explicit privilege review required';
      END IF;
      IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                 JOIN pg_roles r ON r.oid=c.relowner
                 WHERE n.nspname=schema_name AND c.relname=ANY(expected_tables)
                   AND r.rolname <> 'fides_migrator') THEN
          RAISE EXCEPTION 'Migrations must create/own objects as fides_migrator';
      END IF;
      -- Explicitly clear table AND column ACLs; verification also checks effective
      -- column permissions independently (including the cleanup locking exception).
      FOR item IN SELECT c.oid,c.relname FROM pg_class c
          JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname=schema_name AND c.relname=ANY(expected_tables) LOOP
          EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM PUBLIC, '
              'fides_api, fides_reminders, fides_notification_cleanup', schema_name,item.relname);
          SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO cols
          FROM pg_attribute WHERE attrelid=item.oid AND attnum>0 AND NOT attisdropped;
          EXECUTE format('REVOKE SELECT (%s), INSERT (%s), UPDATE (%s), REFERENCES (%s) '
              'ON TABLE %I.%I FROM PUBLIC, fides_api, fides_reminders, '
              'fides_notification_cleanup', cols,cols,cols,cols,schema_name,item.relname);
      END LOOP;
      -- Minimum table operations actually used by current API writers/readers.
      FOR item IN SELECT * FROM (VALUES
          ('users','SELECT, INSERT, UPDATE'), ('auth_identities','SELECT, INSERT'),
          ('connections','SELECT, INSERT, UPDATE'), ('commitments','SELECT, INSERT, UPDATE'),
          ('commitment_terms_versions','SELECT, INSERT'),
          ('commitment_installments','SELECT, INSERT'), ('repayments','SELECT, INSERT, UPDATE'),
          ('repayment_verifications','SELECT, INSERT'), ('ledger_events','SELECT, INSERT'),
          ('audit_logs','SELECT, INSERT'), ('idempotency_keys','SELECT, INSERT, UPDATE'),
          ('notification_events','SELECT, INSERT, UPDATE'),
          ('extension_requests','SELECT, INSERT, UPDATE'), ('auth_sessions','SELECT, INSERT, UPDATE'),
          ('auth_otp_challenges','SELECT, INSERT, UPDATE'),
          ('auth_rate_limit_buckets','SELECT, INSERT, UPDATE'),
          ('notification_preferences','SELECT, INSERT, UPDATE'),
          ('mutual_closure_requests','SELECT, INSERT, UPDATE')
      ) matrix(table_name,privileges) LOOP
          EXECUTE format('GRANT %s ON TABLE %I.%I TO fides_api',
                         item.privileges,schema_name,item.table_name);
      END LOOP;
      FOREACH role_name IN ARRAY ARRAY['commitments','commitment_terms_versions'] LOOP
          EXECUTE format('GRANT SELECT ON TABLE %I.%I TO fides_reminders',schema_name,role_name);
      END LOOP;
      -- Only parent/current-terms row_to_json requires every column. Joins,
      -- aggregates, schedule and RETURNING use these explicit columns; no phone
      -- or credential/profile columns are exposed to the reminder credential.
      EXECUTE format('GRANT SELECT (id, status) ON TABLE %I.users TO fides_reminders',schema_name);
      EXECUTE format('GRANT SELECT (id, commitment_id, terms_version_id, due_date, sequence_no) '
          'ON TABLE %I.commitment_installments TO fides_reminders',schema_name);
      EXECUTE format('GRANT SELECT (commitment_id, status, amount_minor, currency, reported_by_user_id) '
          'ON TABLE %I.repayments TO fides_reminders',schema_name);
      EXECUTE format('GRANT SELECT (user_id, due_reminders_enabled, overdue_reminders_enabled) '
          'ON TABLE %I.notification_preferences TO fides_reminders',schema_name);
      -- ON CONFLICT needs SELECT on the arbiter key even for DO NOTHING.
      EXECUTE format('GRANT SELECT (id, dedupe_key) ON TABLE %I.notification_events TO fides_reminders',schema_name);
      EXECUTE format('GRANT INSERT ON TABLE %I.notification_events TO fides_reminders',schema_name);
      -- PostgreSQL 16 ddl-priv.html: FOR UPDATE requires UPDATE on at least one
      -- column. Cleanup reads id/created_at and deletes by id (ORM primary-key
      -- synchronization also needs only id if it emits RETURNING).
      EXECUTE format('GRANT SELECT (id, created_at), UPDATE (id), DELETE '
          'ON TABLE %I.notification_events TO fides_notification_cleanup',schema_name);
      -- Explicit append-only revocation, even though the reset above already denies it.
      FOREACH role_name IN ARRAY ARRAY['ledger_events','audit_logs'] LOOP
          EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON TABLE %I.%I '
              'FROM PUBLIC, fides_api, fides_reminders, fides_notification_cleanup',schema_name,role_name);
      END LOOP;
      -- 001 defines ten enums; 014 defines mutual_closure_status. UUID keys and
      -- user_id/composite keys create NO sequences through 014: grant none.
      FOR item IN SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
          WHERE n.nspname=schema_name AND t.typtype='e' LOOP
          EXECUTE format('REVOKE ALL PRIVILEGES ON TYPE %I.%I FROM PUBLIC, '
              'fides_api, fides_reminders, fides_notification_cleanup',schema_name,item.typname);
          EXECUTE format('GRANT USAGE ON TYPE %I.%I TO fides_api',schema_name,item.typname);
          IF item.typname IN ('user_status','commitment_type','commitment_status',
              'interest_type','installment_status','repayment_status','notification_status') THEN
              EXECUTE format('GRANT USAGE ON TYPE %I.%I TO fides_reminders',schema_name,item.typname);
          END IF;
      END LOOP;
      -- No application-defined routines exist through 014. pgcrypto may install
      -- routines in this schema; remove PUBLIC/runtime EXECUTE and allow only the
      -- UUID default, if present here. pg_catalog builtins remain unchanged.
      FOR item IN SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname=schema_name LOOP
          IF NOT EXISTS (SELECT FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
              WHERE d.classid='pg_proc'::regclass AND d.objid=item.oid AND d.deptype='e'
                AND e.extname='pgcrypto') THEN
              RAISE EXCEPTION 'Unexpected application routine: explicit review required';
          END IF;
          EXECUTE format('REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC, '
              'fides_api, fides_reminders, fides_notification_cleanup',item.oid::regprocedure);
      END LOOP;
      IF to_regprocedure(format('%I.gen_random_uuid()',schema_name)) IS NOT NULL THEN
          EXECUTE format('GRANT EXECUTE ON FUNCTION %I.gen_random_uuid() '
              'TO fides_api, fides_migrator',schema_name);
      END IF;
  END
  $current_grants$;
  -- Use the same safe catalog assertions before committing. The included verifier
  -- recognizes this transaction; standalone verification uses BEGIN READ ONLY.
  \set FidesVerificationInTransaction true
  \ir verify-staging-roles.sql
  \unset FidesVerificationInTransaction
\endif
COMMIT;
\echo 'Provisioning phase committed; no application data was changed.'
