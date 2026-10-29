# Reminder worker incident: 29 October 2026

## Evidence and correction

Railway `fides-staging` / `production` repeatedly logged `reminder_job_failed`.
PostgreSQL logs at the corresponding hourly executions reported
`permission denied for table notification_events` (including 10:03 UTC on 29 October).
No live database queries, grants or data changes were executed during investigation.

A local PostgreSQL regression reproduces SQLSTATE 42501 using the checked-in
reminder-role permissions: INSERT on notification_events and SELECT(id) only.
PostgreSQL also requires SELECT(dedupe_key) for the named ON CONFLICT arbiter,
even with DO NOTHING (see the [PostgreSQL INSERT privilege rules](https://www.postgresql.org/docs/current/sql-insert.html)). Granting that one column permits the same worker/query to
insert a reminder and retry with zero duplicate insertions. Payload SELECT and
UPDATE remain denied. This confirms a provisioning defect matching the live error;
verify the live role and grants before applying the repair (live ACLs were not read).

Provisioning and the read-only verification script now agree on SELECT(id,
dedupe_key). There are no migrations, query/accounting changes, new dependencies,
password changes, or broad table SELECT grants. Existing financial and audit/ledger
permissions remain unchanged.

The worker now emits a closed exception category, known SQLSTATE where available,
failure phase (configuration/session_factory/reminder_pass), and the last 16
application traceback locations (relative file, function, line). It never emits
exception messages/chains, SQL, bind parameters, source lines or local variables.
Unknown categories/states are not reflected. Nonzero exits remain failures,
including partial corrupt-candidate passes. A successful no-op remains exit 0.

## Deployment synchronization

Read-only Railway inspection found all three backend services connected to
`soumilpatro/fides`, branch `main`, root `/backend`, with source commit
`2e1803d9bdb2f0d2fa01d0a5397ca1e7540093de`. The reminder deployment history records
hourly `redeploy` executions of that same commit. API and cleanup latest successful
deployments are from 4 October. No staged changes were present.

GitHub main at investigation was `f53a1f0ff331e62b74791b24143f11de96a2e626`.
`git diff 2e1803d..f53a1f0 -- backend infra` is empty. The commit gap is not a
backend-behavior explanation for this incident. The normal backend services should
track approved main releases together; cron executions do not establish source
synchronization. The exposed Railway configuration does not report an automatic
GitHub deployment toggle or trigger subscription. Its enabled/disabled state and
why pushes did not advance the source remain unconfirmed. Inspect Service Settings
source triggers, GitHub integration permissions, watch paths and deployment history
before changing settings. Do not infer disabled autodeploy solely from the old SHA.

Railway distinguishes [Deploy Latest Commit](https://docs.railway.com/deployments/github-autodeploys#disable-automatic-deployments)
from re-running the existing deployment. Re-running the old artifact will not add
these diagnostics. No settings or deployments were changed by this investigation.

## Authorized rollout procedure (not executed)

1. Review/merge the PR only after approval. Record the exact approved main SHA.
2. Using an authorized database administration session, confirm the target database,
   schema, actual reminder login role, migration head 014, and existing privileges.
   In particular inspect SELECT on notification_events.id/dedupe_key and INSERT.
   Do not print credentials or notification contents. Stop if the inventory differs
   from the dedicated Fides database/role design.
3. On the approved Fides database only, if the role is `fides_reminders` and schema
   is `public`, the minimal repair is:

   ```sql
   BEGIN;
   GRANT SELECT (dedupe_key) ON TABLE public.notification_events TO fides_reminders;
   COMMIT;
   ```

   This is an operator action requiring authorization, not an application startup
   migration. Prefer this narrow repair over rerunning the full provisioning script
   on a live database. Run the repository's read-only role verification with its
   documented database/schema parameters afterward. Preserve every other denial.
4. Authorize a build of the approved commit for the reminder service using its
   existing command `python -m app.jobs.reminders`. Confirm the resulting deployment
   SHA; do not assume a redeploy of the old artifact selects new source. Keep hourly
   `0 * * * *` and restart policy NEVER. API/cleanup need no behavioral release for
   this permission repair; synchronize them only through the normal approved release.
5. Check exit 0 and `reminder_job_complete` with failed_candidates=0 on the next run.
   Verify existing eligible notifications through authorized read-only inspection;
   do not create live financial fixtures. A second pass for the same occurrences
   must add no duplicates. Zero created is valid when nothing is eligible.
6. Observe at least two scheduled executions, no new permission failures/crash
   alerts, and unchanged API/cleanup health. Local passing tests alone do not prove
   Railway recovery. If it still fails, collect only failure_phase,
   exception_category, known sqlstate and application_traceback from the new worker,
   plus deployment SHA and migration/privilege verification outcomes. Do not share
   raw PostgreSQL statements, connection strings or financial rows.
7. Rollback application artifacts through the approved process if necessary. No
   financial/data rollback is required. Do not revoke SELECT(dedupe_key) as a routine
   rollback: the previous worker needs it too. Any ACL rollback is a separate
   approved operational decision and would reintroduce the demonstrated failure.
