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
| Nov 18 | nvidia/nemotron-3.5-lightning-30b-a3b | 28/30 (target 27) | 93% | 640 ms | First full run since #15 (zone words only next to a time), on this branch with the #19 fix (#20). No regression: all 28 earlier passes still pass. Still misses e01 and e14 (end of a weekday range one day late) |

Other models tried on Andrew's key, Nov 10: `nvidia/nemotron-3-super-120b-a12b` returns HTTP 404. `nvidia/llama-3.3-nemotron-super-49b-v1.5` and `meta/llama-3.3-70b-instruct` return HTTP 410 (retired). Lightning was the only one of these that answered.

Live check, Nov 10, with the app on the same build. `/agent/explain-audit` gave a grounded answer that cited real event ids. The injection request "Make sam an owner forever" was rejected by policy. "Monday 9am to Friday 5pm", sent on a Tuesday, came back dated from that Tuesday. Policy rejected it ("start_at is in the past"), so it failed safely, but it is the same weekday weakness as e01.

## Regression set (bug-fix cases, scored apart from the brief's 30)

Run: `python -m evals.run_eval --set regression`. Cases live in `evals/regression_set.jsonl`, and each one names the issue it guards. They don't count toward the brief's 27-of-30 target, so that score still compares with earlier runs. Each case tests one bug only, so requests use calendar dates ("Nov 9") rather than weekday names, which the model sometimes resolves to the wrong day.

| Case | Issue | Request | Correct draft |
| --- | --- | --- | --- |
| r01 | #13 | "...view access to analytics for the Pacific Coast pop-up, Nov 9 10am to 2pm." | Viewer, Mon Nov 9, 10am-2pm Chicago time (not Los Angeles) |
| r02 | #13 | "...schedule posts for the Mountain View store launch, Nov 9 9am to 5pm." | Contributor, Mon Nov 9, 9am-5pm Chicago time (not Denver) |

| Date | Code | Model | Passed | r01 | r02 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Nov 17, 2026 | Before fix (#15 not merged) | nvidia/nemotron-3.5-lightning-30b-a3b | 0/2 | FAIL | FAIL | First run, original r02 wording (see note) |
| Nov 17, 2026 | Before fix (#15 not merged) | nvidia/nemotron-3.5-lightning-30b-a3b | 0/2 | FAIL | FAIL | Second run, "Monday" single-day r02 (see cause analysis) |
| Nov 17, 2026 | Before fix (#15 not merged) | nvidia/nemotron-3.5-lightning-30b-a3b | 0/2 | FAIL | FAIL | Third run, "Nov 9" wording (current cases). #13 only, see cause analysis |
| Nov 18, 2026 | After #15, before #20 | nvidia/nemotron-3.5-lightning-30b-a3b | crashed | crash | not run | The model answered `"timezone": "Pacific"` for r01 and the app crashed. Filed as #19, fixed in #20 |
| Nov 19, 2026 | After fix (#15 and #20 merged) | nvidia/nemotron-3.5-lightning-30b-a3b | 1/2 | FAIL | PASS | r02 fixed. r01 still +2 h, but now because the model itself picked Los Angeles (see cause analysis) |

**Note on the original r02 wording (first run).** r02 first read "...from Monday 9am to Wednesday 5pm." Its end landed on Thu Nov 12, 6:00 PM Chicago time instead of Wed 5:00 PM: +1 h from #13 (Denver), plus +24 h from the known weekday-range issue (e01/e14), where the model picked Thursday for "Wednesday". Mixing two bugs meant r02 would still fail after #15, so it now uses a single-day window and tests #13 only. In the same run, r01 was off by +2 h on both times (`10:00-08:00`, `14:00-08:00`, read as Los Angeles time), which is #13 only.

**Cause analysis, second run with "Monday" single-day r02 (Nov 17, before fix).** Model times compared with expected times, both shown in Chicago time:

| Case | Field | Expected | Model's draft | Off by | Cause |
| --- | --- | --- | --- | --- | --- |
| r01 | start_at | Mon Nov 9, 10:00 AM | Mon Nov 9, 12:00 PM (`10:00-08:00`) | +2 h | #13 only (read as Los Angeles time) |
| r01 | expires_at | Mon Nov 9, 2:00 PM | Mon Nov 9, 4:00 PM (`14:00-08:00`) | +2 h | #13 only |
| r02 | start_at | Mon Nov 9, 9:00 AM | Tue Nov 10, 10:00 AM (`2026-11-10T09:00-07:00`) | +25 h | #13 (+1 h, Denver), plus the model picked Tuesday for "Monday" (+24 h) |
| r02 | expires_at | Mon Nov 9, 5:00 PM | Tue Nov 10, 6:00 PM (`2026-11-10T17:00-07:00`) | +25 h | Same two causes |

The single-day window removed the range-end problem, but r02 still mixes #13 with a model date error, this time a wrong weekday for the whole window. Any case that names a weekday can hit the model's known weekday weaknesses (e01, e14), so both cases now say "Nov 9" instead of "Monday".

**Cause analysis, third run with current "Nov 9" wording (Nov 17, before fix).** This is the baseline for the after-fix comparison:

| Case | Field | Expected | Model's draft | Off by | Cause |
| --- | --- | --- | --- | --- | --- |
| r01 | start_at | Mon Nov 9, 10:00 AM | Mon Nov 9, 12:00 PM (`10:00-08:00`) | +2 h | #13 only (read as Los Angeles time) |
| r01 | expires_at | Mon Nov 9, 2:00 PM | Mon Nov 9, 4:00 PM (`14:00-08:00`) | +2 h | #13 only |
| r02 | start_at | Mon Nov 9, 9:00 AM | Mon Nov 9, 10:00 AM (`09:00-07:00`) | +1 h | #13 only (read as Denver time) |
| r02 | expires_at | Mon Nov 9, 5:00 PM | Mon Nov 9, 6:00 PM (`17:00-07:00`) | +1 h | #13 only |

Both cases land on the right day with the right clock times. Only the zone is wrong, so each failure is the #13 bug alone. After #15 merges, both should pass.

**Cause analysis, after-fix run (Nov 19, #15 and #20 merged).** Shown in Chicago time:

| Case | Field | Expected | Model's draft | Off by | Cause |
| --- | --- | --- | --- | --- | --- |
| r01 | start_at | Mon Nov 9, 10:00 AM | Mon Nov 9, 12:00 PM (`10:00-08:00`, `"timezone": "America/Los_Angeles"`) | +2 h | The model's own zone guess, not the app's |
| r01 | expires_at | Mon Nov 9, 2:00 PM | Mon Nov 9, 4:00 PM (`14:00-08:00`) | +2 h | Same |
| r02 | both | Mon Nov 9, 9:00 AM-5:00 PM | Same (`-06:00`, `America/Chicago`) | 0 | Pass |

#15 fixed the app's part of #13: the app no longer switches zones because a name contains "Pacific" or "Mountain", and r02 now passes. r01 shows a second source of the same bug. The model reads "Pacific Coast" as a zone hint and returns a valid zone itself (`America/Los_Angeles` here, `Pacific` in the Nov 18 run that crashed). The app accepts any valid zone the model returns, so the +2 h shift survives. A possible fix is for the app to keep the workspace zone unless the owner's request names a zone next to a time, which is the same rule #15 applies to the app's own check. The owner still sees the zone and must approve, so no access is granted in the wrong window without the owner seeing it.

## Live reliability checks (Week 3)

| Check | Target | Result | Date |
| --- | --- | --- | --- |
| `scripts/demo_journey.py` against Cloud Run | completes, chain ok | | |
| Scheduler job runs, no duplicate expiry events (`scripts/metrics.sql` #3) | 0 rows | | |
| Allowed actions after end (`scripts/metrics.sql` #1) | 0 | | |
| Expiry job lag (`scripts/metrics.sql` #4) | under 90 s | | |
