-- Dashboard views and the decision recheck for the Data Studio report (Joclyn).
-- Replace PROJECT with your project id. All of it reads `PROJECT.roleready.audit_events`,
-- which scripts/export_bigquery.py fills (one row per audit event; `details` is JSON text).
-- Screenshots: docs/evidence/dashboard-agent-accuracy-2026-11-22.png (sample data),
-- docs/evidence/dashboard-live-2026-11-22.png (live data, after the switch on Nov 22).
--
-- Switching the report from the Sandbox (sample data) to roleready-515202 (D4):
--   1. Run scripts/export_bigquery.py --project roleready-515202 after real activity on the live app.
--   2. Run the four CREATE VIEW statements below in roleready-515202.
--   3. In Data Studio, edit each data source's connection to point at roleready-515202:
--      the four views and "Success measures (query)" (scripts/metrics.sql).
--      eval_runs can stay in the Sandbox; it comes from evals, not the app.
--   4. Refresh data, rerun the decision recheck (expect 0 disagreements), and
--      replace the "Sample data" note at the top of the report.
--   5. Take a new screenshot for docs/evidence/.
-- To refresh later: rerun step 1, then Refresh data in Data Studio. Rerun the views only
-- after this file changes.


-- ===== Dashboard views =====

-- Task attempts with readable labels. Used by the "Why attempts were blocked" chart.
CREATE OR REPLACE VIEW `PROJECT.roleready.dashboard_events` AS
SELECT id, seq, ts, workspace_id, actor, action, target, decision, reason,
  CASE decision WHEN 'allow' THEN 'Allowed' WHEN 'deny' THEN 'Blocked' END AS outcome,
  CASE reason
    WHEN 'ok' THEN 'Allowed'
    WHEN 'expired' THEN 'Access had expired'
    WHEN 'revoked' THEN 'Access was revoked'
    WHEN 'not_started' THEN 'Access not started yet'
    WHEN 'role_forbids_task' THEN "Role doesn't allow this task"
    WHEN 'no_grant' THEN 'Never given access'
    WHEN 'task_not_granted' THEN 'Task not in their grant'
    WHEN 'unknown_task' THEN 'Not a RoleReady task'
    WHEN 'inactive' THEN 'Access not active'
    ELSE reason END AS reason_label,
  CASE
    WHEN reason IN ('expired', 'revoked') THEN 'Access ended'
    WHEN reason IN ('not_started', 'no_grant', 'role_forbids_task', 'task_not_granted', 'unknown_task', 'inactive') THEN 'Outside granted access'
    WHEN reason = 'ok' THEN 'Allowed' END AS block_group,
  CASE action
    WHEN 'action.view_assets' THEN 'View assets'
    WHEN 'action.edit_drafts' THEN 'Edit drafts'
    WHEN 'action.view_analytics' THEN 'View analytics'
    WHEN 'action.schedule_posts' THEN 'Schedule posts'
    WHEN 'action.manage_access' THEN 'Manage access'
    ELSE action END AS task_label,
  IF(decision = 'deny', 1, 0) AS is_blocked
FROM `PROJECT.roleready.audit_events`
WHERE STARTS_WITH(action, 'action.');

-- Blocked attempts by reason. Used by the "Why attempts were blocked" chart.
CREATE OR REPLACE VIEW `PROJECT.roleready.dashboard_blocked_reasons` AS
SELECT reason_label, block_group, COUNT(*) AS blocked_attempts
FROM `PROJECT.roleready.dashboard_events`
WHERE outcome = 'Blocked'
GROUP BY reason_label, block_group;

-- Invited -> approved -> accepted -> ended. Used by the "Did every grant end?" chart.
-- Counts events, so a cancelled invitation shows as invited but not approved.
CREATE OR REPLACE VIEW `PROJECT.roleready.dashboard_lifecycle` AS
SELECT 1 AS step, '1. Invited' AS stage, COUNTIF(action = 'invitation.created') AS grants FROM `PROJECT.roleready.audit_events`
UNION ALL SELECT 2, '2. Approved by owner', COUNTIF(action = 'invitation.approved') FROM `PROJECT.roleready.audit_events`
UNION ALL SELECT 3, '3. Accepted by freelancer', COUNTIF(action = 'invitation.accepted') FROM `PROJECT.roleready.audit_events`
UNION ALL SELECT 4, '4. Access ended (expired or revoked)', COUNTIF(action IN ('grant.expired', 'grant.revoked')) FROM `PROJECT.roleready.audit_events`;

-- Headline numbers. Used by the scorecards at the top of the report.
-- invite_misuse_blocked counts every refused invite accept (wrong user, reused or expired
-- token, too many attempts).
CREATE OR REPLACE VIEW `PROJECT.roleready.dashboard_kpis` AS
SELECT
  COUNTIF(STARTS_WITH(action, 'action.')) AS task_attempts,
  COUNTIF(STARTS_WITH(action, 'action.') AND decision = 'allow') AS task_attempts_allowed,
  COUNTIF(STARTS_WITH(action, 'action.') AND decision = 'deny') AS task_attempts_blocked,
  SAFE_DIVIDE(COUNTIF(STARTS_WITH(action, 'action.') AND decision = 'deny'), COUNTIF(STARTS_WITH(action, 'action.'))) AS blocked_rate,
  COUNTIF(action = 'invitation.created') AS invites_created,
  COUNTIF(action = 'invitation.approved') AS invites_owner_approved,
  COUNTIF(action = 'invitation.accepted') AS invites_accepted,
  COUNTIF(action IN ('grant.expired', 'grant.revoked')) AS grants_ended,
  COUNTIF(action = 'grant.expired') AS grants_expired,
  COUNTIF(action = 'grant.revoked') AS grants_revoked,
  COUNTIF(action = 'invitation.accept' AND decision = 'deny') AS invite_misuse_blocked
FROM `PROJECT.roleready.audit_events`;


-- ===== Decision recheck (saved in BigQuery as "RoleReady decision recheck") =====
-- Rebuilds each grant from the invitation records and checks every task attempt
-- independently of the app's own decision. Expect 0 rows where decision and expected disagree.
-- Limit: the role-permission table lives in app code, so "allow unless role forbids" can't
-- re-derive the role rule; tests cover that.

WITH ev AS (SELECT * FROM `PROJECT.roleready.audit_events`),
inv AS (
  SELECT target AS invitation_id,
    JSON_VALUE(details, '$.role') AS role,
    JSON_VALUE_ARRAY(details, '$.tasks') AS tasks,
    TIMESTAMP(JSON_VALUE(details, '$.start_at')) AS start_at,
    TIMESTAMP(JSON_VALUE(details, '$.expires_at')) AS expires_at
  FROM ev WHERE action = 'invitation.created'),
acc AS (
  SELECT target AS invitation_id, JSON_VALUE(details, '$.grant_id') AS grant_id, actor AS grant_user
  FROM ev WHERE action = 'invitation.accepted'),
rev AS (
  SELECT target AS grant_id, MIN(ts) AS revoked_at
  FROM ev WHERE action = 'grant.revoked' GROUP BY 1),
g AS (
  SELECT a.grant_id, a.grant_user, i.role, i.tasks, i.start_at, i.expires_at, r.revoked_at
  FROM acc a JOIN inv i USING (invitation_id) LEFT JOIN rev r USING (grant_id)),
att AS (
  SELECT e.ts, e.actor, SUBSTR(e.action, 8) AS task, e.decision, e.reason, g.*
  FROM ev e LEFT JOIN g ON g.grant_id = e.target
  WHERE STARTS_WITH(e.action, 'action.')),
chk AS (
  SELECT *, CASE
    WHEN grant_id IS NULL THEN 'deny'
    WHEN actor != grant_user THEN 'deny'
    WHEN revoked_at IS NOT NULL AND ts >= revoked_at THEN 'deny'
    WHEN ts < start_at THEN 'deny'
    WHEN ts >= expires_at THEN 'deny'
    WHEN task NOT IN UNNEST(tasks) THEN 'deny'
    ELSE 'allow unless role forbids' END AS expected
  FROM att)
SELECT decision, reason, expected, COUNT(*) AS n, MIN(role) AS a_role, MAX(role) AS b_role
FROM chk GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
