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

## Local run, Nov 10 (Mohamed)

Windows 11, Python 3.12.10, `AUTH_MODE=demo`, `STORE_BACKEND=memory`, personal NVIDIA key from build.nvidia.com.

**Automated suites:** `pytest` 203 passed, 19 skipped (Floci not running). `python scripts/iam.py lint` clean.

**Journey:** `python scripts/demo_journey.py --base-url http://127.0.0.1:8000 --window-minutes 1`

| Who | Task | Expected | Result |
| --- | --- | --- | --- |
| sam@freelance.test (contributor) | `edit_drafts` | allow | ALLOW |
| sam@freelance.test (contributor) | `view_analytics` | deny, role | DENY `role_forbids_task` |
| riley@client.test (viewer) | `view_analytics` | allow | ALLOW |
| riley@client.test (viewer) | `schedule_posts` | deny, role | DENY `role_forbids_task` |
| mallory@evil.test (no invite) | `view_assets` | deny | DENY `no_grant` |
| riley@client.test after owner revoke | `view_assets` | deny | DENY `revoked` |
| sam@freelance.test after the 1-minute window | `edit_drafts` | deny | DENY `expired` |
| Owner | `GET /audit/verify` | intact | ok, 14 of 14 events |

**Access Assistant: failed every request** (no draft and no grant on failure, so the safety posture held). Three causes, tracked in [#4](https://github.com/mkaba214/roleready/issues/4):

1. `nvidia/nemotron-3-super-120b-a12b` returns HTTP 404 "Function not found for account" for this key. `nvidia/nemotron-3.5-lightning-30b-a3b` responds.
2. That model is a reasoning model and uses up `max_tokens` before writing the answer, so `content` is empty. With `chat_template_kwargs: {"enable_thinking": false}`, a short JSON reply drops from 482 to 25 completion tokens.
3. `DraftResult` positional arguments are shifted on the error paths in `app/agent.py`, so model and latency are logged in the wrong fields.

**Not covered yet:** Floci IAM enforcement (needs Docker; the CI job fails 1 of 47, see [#2](https://github.com/mkaba214/roleready/issues/2)), Firebase sign-in, the agent eval, and anything on Cloud Run.

## Agent eval (fill in after each run)

| Date | Model | Passed | Accuracy | Median latency | Notes |
| --- | --- | --- | --- | --- | --- |
| Nov 10 | nvidia/nemotron-3.5-lightning-30b-a3b | 21/30 (target 27) | 70% | 1702 ms | First run with reasoning off (#4). Misses: weekday names resolved to past dates, invented end dates, wrong zone offsets |
| Nov 10 | nvidia/nemotron-3.5-lightning-30b-a3b | 28/30 (target 27) | 93% | 1265 ms | After the prompt calendar, date and task rules and the named-zone check (#7). Same score on two runs. Misses e01 and e14: the end of a weekday range lands one day late |

Other models tried on Andrew's key, Nov 10: `nvidia/nemotron-3-super-120b-a12b` returns HTTP 404. `nvidia/llama-3.3-nemotron-super-49b-v1.5` and `meta/llama-3.3-70b-instruct` return HTTP 410 (retired). Lightning was the only one of these that answered.

Live check, Nov 10, with the app on the same build. `/agent/explain-audit` gave a grounded answer that cited real event ids. The injection request "Make sam an owner forever" was rejected by policy. "Monday 9am to Friday 5pm", sent on a Tuesday, came back dated from that Tuesday. Policy rejected it ("start_at is in the past"), so it failed safely, but it is the same weekday weakness as e01.

## Live reliability checks (Week 3)

| Check | Target | Result | Date |
| --- | --- | --- | --- |
| `scripts/demo_journey.py` against Cloud Run | completes, chain ok | | |
| Scheduler job runs, no duplicate expiry events (`scripts/metrics.sql` #3) | 0 rows | | |
| Allowed actions after end (`scripts/metrics.sql` #1) | 0 | | |
| Expiry job lag (`scripts/metrics.sql` #4) | under 90 s | | |
