# Test results

Run: `pytest` (all suites) · `python -m evals.run_eval --model <id>` (agent quality, needs a key)

## Automated suites (Nov 5 baseline: 203 passing, 19 Floci tests skipped without Floci)

Added Nov 5: `tests/test_brief_updates.py` (time zones, success-measures dashboard, Newly integration, CORS), `tests/iam/test_iam_policy.py` (least-privilege lint), `tests/iam/test_iam_tool.py` (plan/apply logic), `tests/iam/test_floci_enforcement.py` (19 enforcement checks, run with `FLOCI_GCP_URL` set). The eval set grew to 30 cases.

| Suite | File | What it proves | Cases |
| --- | --- | --- | --- |
| Permission matrix + time window | `tests/test_policy.py` | Each role does only its tasks; access starts and ends on the second | 15 + 8 + rules |
| Full grid | `tests/test_grid.py` | 3 roles x 5 tasks x 4 states, every decision logged | 60 |
| Expiry and revoke | `tests/test_expiry.py` | 10 job runs = 1 event per grant; revoke/expire race has one winner | 8 |
| Audit integrity | `tests/test_audit.py` | Edits, re-hashed edits and deletions are detected | 6 |
| API and back doors | `tests/test_api.py` | Full journey; 401/403/410 cases; scheduler OIDC; demo auth blocked on Cloud Run | 18+ |
| Agent safety | `tests/test_agent.py` | Injection, bad roles, messy JSON, retries, key never leaks | 30+ |
| Eval runner | `tests/test_evals.py` | Scoring logic is correct | 3 |

## Agent eval (fill in after each run)

| Date | Model | Passed | Accuracy | Median latency | Notes |
| --- | --- | --- | --- | --- | --- |
| | | /30 (target 27) | | | |

## Live reliability checks (Week 3)

| Check | Target | Result | Date |
| --- | --- | --- | --- |
| `scripts/demo_journey.py` against Cloud Run | completes, chain ok | | |
| Scheduler job runs, no duplicate expiry events (`scripts/metrics.sql` #3) | 0 rows | | |
| Allowed actions after end (`scripts/metrics.sql` #1) | 0 | | |
| Expiry job lag (`scripts/metrics.sql` #4) | under 90 s | | |
