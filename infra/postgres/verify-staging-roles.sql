-- PREPARATION ONLY: not executed by this checkpoint. psql 16+, PostgreSQL 16+.
-- Required variables: FidesDatabase and FidesSchema, identical to provisioning.
-- Execute AFTER Alembic head 014 and grants. No password variables needed.
-- Standalone: one READ ONLY transaction, catalog/permission queries and a read of
-- alembic_version only. No destructive permission probes and no financial reads.
-- Provisioning includes this before its COMMIT using the internal transaction flag.
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
\if :{?FidesVerificationInTransaction}
\else
  BEGIN READ ONLY;
\endif
SET LOCAL search_path = pg_catalog, pg_temp;
SELECT set_config('fides.database', :'FidesDatabase', true) AS db_context,
       set_config('fides.schema', :'FidesSchema', true) AS schema_context
\gset

DO $verify$
DECLARE
    db_name text := current_setting('fides.database');
    schema_name text := current_setting('fides.schema');
    role_names text[] := ARRAY['fides_migrator','fides_api','fides_reminders',
        'fides_notification_cleanup'];
    runtime_names text[] := ARRAY['fides_api','fides_reminders','fides_notification_cleanup'];
    table_names text[] := ARRAY['users','auth_identities','connections','commitments',
        'commitment_terms_versions','commitment_installments','repayments',
        'repayment_verifications','ledger_events','audit_logs','idempotency_keys',
        'notification_events','extension_requests','auth_sessions','auth_otp_challenges',
        'auth_rate_limit_buckets','notification_preferences','mutual_closure_requests',
        'alembic_version'];
    mutable_tables text[] := ARRAY['users','connections','commitments','repayments',
        'idempotency_keys','notification_events','extension_requests','auth_sessions',
        'auth_otp_challenges','auth_rate_limit_buckets','notification_preferences',
        'mutual_closure_requests'];
    reminder_tables text[] := ARRAY['commitments','commitment_terms_versions'];
    enum_names text[] := ARRAY['user_status','connection_status','commitment_type',
        'commitment_status','interest_type','repayment_status','verification_decision',
        'extension_status','installment_status','notification_status','mutual_closure_status'];
    reminder_enums text[] := ARRAY['user_status','commitment_type','commitment_status',
        'interest_type','repayment_status','installment_status','notification_status'];
    role_name text; item record; privilege text; column_item record;
    expected boolean; actual boolean; version_count int; version_value text;
BEGIN
    IF db_name='' OR schema_name='' OR current_database()<>db_name
       OR schema_name ~ '^pg_' OR schema_name='information_schema'
       OR current_setting('server_version_num')::int < 160000 THEN
        RAISE EXCEPTION 'Invalid database/schema or unsupported PostgreSQL version';
    END IF;
    IF (SELECT count(*) FROM pg_roles WHERE rolname=ANY(role_names))<>4 THEN
        RAISE EXCEPTION 'All four distinct service/migration roles must exist';
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname=ANY(role_names)
        AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolreplication
             OR rolinherit OR NOT rolcanlogin OR rolvaliduntil IS NOT NULL)) THEN
        RAISE EXCEPTION 'Role attributes differ from approved non-inheriting login roles';
    END IF;
    -- NOINHERIT alone does not prevent SET ROLE; reject every outgoing membership.
    IF EXISTS (SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
               WHERE r.rolname=ANY(role_names)) THEN
        RAISE EXCEPTION 'A Fides role has membership/SET ROLE authority';
    END IF;
    IF EXISTS (SELECT FROM pg_shdepend d JOIN pg_roles r ON r.oid=d.refobjid
        WHERE d.refclassid='pg_authid'::regclass AND d.deptype='o'
          AND r.rolname=ANY(runtime_names)) THEN
        RAISE EXCEPTION 'Runtime role owns an object and can bypass privilege denial';
    END IF;
    IF EXISTS (SELECT FROM pg_parameter_acl p,
        LATERAL aclexplode(p.paracl) a JOIN pg_roles r ON r.oid=a.grantee
        WHERE r.rolname=ANY(runtime_names)) THEN
        RAISE EXCEPTION 'Unexpected runtime server-parameter authority requires review';
    END IF;
    IF EXISTS (SELECT FROM pg_database d,
        LATERAL aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a
        WHERE d.datname=db_name AND a.grantee=0)
       OR EXISTS (SELECT FROM pg_namespace n,
        LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a
        WHERE n.nspname=schema_name AND a.grantee=0) THEN
        RAISE EXCEPTION 'Target database/schema retains unexpected PUBLIC privileges';
    END IF;
    FOREACH role_name IN ARRAY role_names LOOP
        IF NOT has_database_privilege(role_name,db_name,'CONNECT')
           OR NOT has_schema_privilege(role_name,schema_name,'USAGE')
           OR has_database_privilege(role_name,db_name,'CREATE')<>(role_name='fides_migrator')
           OR has_schema_privilege(role_name,schema_name,'CREATE')<>(role_name='fides_migrator')
           OR has_database_privilege(role_name,db_name,'TEMPORARY') THEN
            RAISE EXCEPTION 'Database/schema permissions differ for %',role_name;
        END IF;
        IF NOT EXISTS (SELECT FROM pg_db_role_setting s JOIN pg_roles r ON r.oid=s.setrole
            JOIN pg_database d ON d.oid=s.setdatabase
            WHERE r.rolname=role_name AND d.datname=db_name
              AND format('search_path=%I, pg_catalog',schema_name)=ANY(s.setconfig)) THEN
            RAISE EXCEPTION 'Per-database search_path differs for %',role_name;
        END IF;
    END LOOP;
    FOREACH role_name IN ARRAY runtime_names LOOP
        IF EXISTS (SELECT FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%'
            AND n.nspname<>'information_schema' AND has_schema_privilege(role_name,n.oid,'CREATE')) THEN
            RAISE EXCEPTION 'Runtime role can create in another schema: %',role_name;
        END IF;
        -- No DENY ACL exists: PUBLIC CONNECT on OTHER databases cannot be undone
        -- by revoking from this role. Stop for DBA review; never alter other DBs here.
        IF EXISTS (SELECT FROM pg_database d WHERE d.datallowconn
            AND d.datname<>db_name AND has_database_privilege(role_name,d.oid,'CONNECT')) THEN
            RAISE EXCEPTION 'Cross-database CONNECT requires cluster administrator review: %',role_name;
        END IF;
        IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
              AND n.nspname<>schema_name AND c.relkind IN ('r','p','v','m','f')
              AND (has_table_privilege(role_name,c.oid,
                      'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                   OR has_any_column_privilege(role_name,c.oid,'SELECT,INSERT,UPDATE,REFERENCES'))) THEN
            RAISE EXCEPTION 'Unexpected table/column authority outside app schema: %',role_name;
        END IF;
        IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
              AND c.relkind='S' AND has_sequence_privilege(role_name,c.oid,'USAGE,SELECT,UPDATE')) THEN
            RAISE EXCEPTION 'No current runtime sequence privilege is required: %',role_name;
        END IF;
    END LOOP;
    IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=schema_name AND c.relkind='r' AND c.relname=ANY(table_names))
       <>cardinality(table_names) THEN
        RAISE EXCEPTION 'Expected 18 application tables plus alembic_version are not present';
    END IF;
    IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=schema_name AND c.relkind IN ('r','p','v','m','S','f')
          AND c.relname<>ALL(table_names)) THEN
        RAISE EXCEPTION 'Unexpected relation/sequence: grants must be reviewed explicitly';
    END IF;
    IF EXISTS (SELECT FROM pg_default_acl a JOIN pg_roles r ON r.oid=a.defaclrole
        WHERE r.rolname='fides_migrator') THEN
        RAISE EXCEPTION 'Custom migrator default ACLs require explicit review; no future broad grants';
    END IF;
    EXECUTE format('SELECT count(*), min(version_num) FROM %I.alembic_version',schema_name)
        INTO version_count,version_value;
    IF version_count<>1 OR version_value IS DISTINCT FROM '014' THEN
        RAISE EXCEPTION 'Database must have exactly Alembic head 014';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_extension WHERE extname='pgcrypto') THEN
        RAISE EXCEPTION 'pgcrypto is not installed';
    END IF;
    IF NOT has_function_privilege('fides_api','pg_catalog.gen_random_uuid()','EXECUTE') THEN
        RAISE EXCEPTION 'API lacks builtin UUID default execution privilege';
    END IF;
    FOR item IN SELECT c.oid,c.relname,c.relowner FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=schema_name AND c.relname=ANY(table_names) LOOP
        IF item.relowner<>(SELECT oid FROM pg_roles WHERE rolname='fides_migrator') THEN
            RAISE EXCEPTION 'Migration role must own table %',item.relname;
        END IF;
        FOREACH role_name IN ARRAY runtime_names LOOP
            FOREACH privilege IN ARRAY ARRAY['SELECT','INSERT','UPDATE','DELETE',
                'TRUNCATE','REFERENCES','TRIGGER'] LOOP
                expected := CASE role_name
                    WHEN 'fides_api' THEN item.relname<>'alembic_version' AND
                        (privilege IN ('SELECT','INSERT') OR
                         (privilege='UPDATE' AND item.relname=ANY(mutable_tables)))
                    WHEN 'fides_reminders' THEN
                        (privilege='SELECT' AND item.relname=ANY(reminder_tables)) OR
                        (privilege='INSERT' AND item.relname='notification_events')
                    ELSE privilege='DELETE' AND item.relname='notification_events'
                END;
                actual := has_table_privilege(role_name,item.oid,privilege);
                IF actual<>expected OR has_table_privilege(role_name,item.oid,
                    privilege || ' WITH GRANT OPTION') THEN
                    RAISE EXCEPTION 'Unexpected table/grant-option privilege: % % %',
                        role_name,item.relname,privilege;
                END IF;
            END LOOP;
            -- has_table_privilege misses column ACLs: enumerate every real column.
            FOR column_item IN SELECT attnum,attname FROM pg_attribute
                WHERE attrelid=item.oid AND attnum>0 AND NOT attisdropped LOOP
                FOREACH privilege IN ARRAY ARRAY['SELECT','INSERT','UPDATE','REFERENCES'] LOOP
                    expected := CASE role_name
                        WHEN 'fides_api' THEN item.relname<>'alembic_version' AND
                            (privilege IN ('SELECT','INSERT') OR
                             (privilege='UPDATE' AND item.relname=ANY(mutable_tables)))
                        WHEN 'fides_reminders' THEN
                            (privilege='SELECT' AND (item.relname=ANY(reminder_tables)
                              OR (item.relname='users' AND column_item.attname IN ('id','status'))
                              OR (item.relname='commitment_installments' AND column_item.attname IN
                                  ('id','commitment_id','terms_version_id','due_date','sequence_no'))
                              OR (item.relname='repayments' AND column_item.attname IN
                                  ('commitment_id','status','amount_minor','currency','reported_by_user_id'))
                              OR (item.relname='notification_preferences' AND column_item.attname IN
                                  ('user_id','due_reminders_enabled','overdue_reminders_enabled'))
                              OR (item.relname='notification_events' AND column_item.attname='id'))) OR
                            (privilege='INSERT' AND item.relname='notification_events')
                        ELSE item.relname='notification_events' AND
                            ((privilege='SELECT' AND column_item.attname IN ('id','created_at'))
                             OR (privilege='UPDATE' AND column_item.attname='id'))
                    END;
                    IF has_column_privilege(role_name,item.oid,column_item.attnum,privilege)<>expected
                       OR has_column_privilege(role_name,item.oid,column_item.attnum,
                           privilege || ' WITH GRANT OPTION') THEN
                        RAISE EXCEPTION 'Unexpected column/grant-option privilege: % %.% %',
                            role_name,item.relname,column_item.attname,privilege;
                    END IF;
                END LOOP;
            END LOOP;
        END LOOP;
    END LOOP;
    IF (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
        WHERE n.nspname=schema_name AND t.typtype='e' AND t.typname=ANY(enum_names))<>11
       OR EXISTS (SELECT FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                  WHERE n.nspname=schema_name AND t.typtype='e' AND t.typname<>ALL(enum_names)) THEN
        RAISE EXCEPTION 'Expected migration-014 enum inventory differs';
    END IF;
    FOR item IN SELECT t.oid,t.typname,t.typowner FROM pg_type t
        JOIN pg_namespace n ON n.oid=t.typnamespace
        WHERE n.nspname=schema_name AND t.typtype='e' LOOP
        IF item.typowner<>(SELECT oid FROM pg_roles WHERE rolname='fides_migrator') THEN
            RAISE EXCEPTION 'Migration role must own enum %',item.typname;
        END IF;
        FOREACH role_name IN ARRAY runtime_names LOOP
            expected := role_name='fides_api' OR
                        (role_name='fides_reminders' AND item.typname=ANY(reminder_enums));
            IF has_type_privilege(role_name,item.oid,'USAGE')<>expected
               OR has_type_privilege(role_name,item.oid,'USAGE WITH GRANT OPTION') THEN
                RAISE EXCEPTION 'Unexpected type privilege: % %',role_name,item.typname;
            END IF;
        END LOOP;
    END LOOP;
    FOR item IN SELECT p.oid,p.proname,p.pronargs FROM pg_proc p
        JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=schema_name LOOP
        IF NOT EXISTS (SELECT FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
            WHERE d.classid='pg_proc'::regclass AND d.objid=item.oid AND d.deptype='e'
              AND e.extname='pgcrypto') THEN
            RAISE EXCEPTION 'Unexpected application routine requires review';
        END IF;
        FOREACH role_name IN ARRAY runtime_names LOOP
            expected := role_name='fides_api' AND item.proname='gen_random_uuid' AND item.pronargs=0;
            IF has_function_privilege(role_name,item.oid,'EXECUTE')<>expected
               OR has_function_privilege(role_name,item.oid,'EXECUTE WITH GRANT OPTION') THEN
                RAISE EXCEPTION 'Unexpected schema function privilege: %',role_name;
            END IF;
        END LOOP;
    END LOOP;
END
$verify$;
\echo 'PASS: head 014, role attributes, ownership, effective table/column/type grants and denials.'
\if :{?FidesVerificationInTransaction}
\else
  ROLLBACK;
\endif
