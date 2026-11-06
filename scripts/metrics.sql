-- Success-measure queries for Looker Studio (Joclyn). Replace PROJECT with your project id.

-- 1. Actions allowed after expiry or revoke. Target: 0.
WITH ended AS (
  SELECT target AS grant_id, MIN(ts) AS ended_at
  FROM `PROJECT.roleready.audit_events`
  WHERE action IN ('grant.expired', 'grant.revoked')
  GROUP BY target
)
SELECT COUNT(*) AS allowed_after_end
FROM `PROJECT.roleready.audit_events` e
JOIN ended ON e.target = ended.grant_id  -- an action event's target is the grant it used
WHERE STARTS_WITH(e.action, 'action.') AND e.decision = 'allow' AND e.ts >= ended.ended_at;

-- 2. Every decision logged: allow and deny counts by reason.
SELECT decision, reason, COUNT(*) AS events
FROM `PROJECT.roleready.audit_events`
WHERE STARTS_WITH(action, 'action.')
GROUP BY decision, reason
ORDER BY events DESC;

-- 3. Duplicate expiry events per grant. Target: 0 rows.
SELECT target AS grant_id, COUNT(*) AS expired_events
FROM `PROJECT.roleready.audit_events`
WHERE action = 'grant.expired'
GROUP BY target
HAVING COUNT(*) > 1;

-- 4. Expiry job lag: seconds between the scheduled end and the expired event (status tidy-up only;
--    access already ended at expires_at because every request checks the clock).
SELECT
  target AS grant_id,
  TIMESTAMP_DIFF(ts, TIMESTAMP(JSON_VALUE(details, '$.expires_at')), SECOND) AS lag_seconds
FROM `PROJECT.roleready.audit_events`
WHERE action = 'grant.expired'
ORDER BY lag_seconds DESC;

-- 5. Access Assistant use and rejection rate.
SELECT action, reason, COUNT(*) AS calls
FROM `PROJECT.roleready.audit_events`
WHERE STARTS_WITH(action, 'assistant.')
GROUP BY action, reason;

-- 6. Invitations by source (assistant vs manual).
SELECT JSON_VALUE(details, '$.source') AS source, COUNT(*) AS invitations
FROM `PROJECT.roleready.audit_events`
WHERE action = 'invitation.created'
GROUP BY source;
