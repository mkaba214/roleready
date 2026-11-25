# Test results

Run: `pytest` (all suites) · `python -m evals.run_eval --model <id>` (agent quality, needs a key)

## Automated suites (Nov 5 baseline: 203 passing, 19 Floci tests skipped without Floci)

**Nov 23:** `pytest` 275 passed, 18 skipped (the Floci IAM enforcement tests, which run in the `iam-floci` CI job). `python scripts/iam.py lint` clean.

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
| Nov 19 | nvidia/nemotron-3.5-lightning-30b-a3b | 28/30 (target 27) | 93% | 601 ms | With the #29 fix (a zone the request never mentions is dropped). No regression, including e08, e15, e22, e25 and e30, which name a zone. Same e01 and e14 misses |

Charted on the dashboard from [`docs/evidence/eval_runs.csv`](evidence/eval_runs.csv) ([screenshot](evidence/dashboard-agent-accuracy-2026-11-22.png)). Add a row there too after each run.

Other models tried on Andrew's key, Nov 10: `nvidia/nemotron-3-super-120b-a12b` returns HTTP 404. `nvidia/llama-3.3-nemotron-super-49b-v1.5` and `meta/llama-3.3-70b-instruct` return HTTP 410 (retired). Lightning was the only one of these that answered.

Live check, Nov 10, with the app on the same build. `/agent/explain-audit` gave a grounded answer that cited real event ids. The injection request "Make sam an owner forever" was rejected by policy. "Monday 9am to Friday 5pm", sent on a Tuesday, came back dated from that Tuesday. Policy rejected it ("start_at is in the past"), so it failed safely, but it is the same weekday weakness as e01.

## Regression set (bug-fix cases, scored apart from the brief's 30)

Run: `python -m evals.run_eval --set regression`. Cases live in `evals/regression_set.jsonl`, and each one names the issue it guards (r03-r05 track a known gap instead; see below). They don't count toward the brief's 27-of-30 target, so that score still compares with earlier runs. Each case tests one bug only, so requests use calendar dates ("Nov 9") rather than weekday names, which the model sometimes resolves to the wrong day.

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
| Nov 19, 2026 | With the #29 fix (this branch) | nvidia/nemotron-3.5-lightning-30b-a3b | 2/2 | PASS | PASS | The app drops a zone the request never mentions. r01 then ran 15 more times: the model answered `Pacific` 14 times (handled by #20) and `America/Los_Angeles` once (handled by #29); the draft was 10am-2pm Chicago time every time |

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

**Fix (#29, Nov 19).** The app now keeps the model's zone only when the request mentions it: its IANA name ("America/Denver"), its city followed by "time" ("London time"), or an abbreviation ("PST", "ET"). Any other zone is a guess, so the draft uses the workspace zone and keeps the clock times the owner typed. A zone word next to a time ("5pm Pacific") still wins, as in #15. With the fix, r01 is 10am-2pm Chicago time whether the model answers `Pacific`, `America/Los_Angeles` or `America/Chicago`.


**Known gap: casual zone names (r03-r05, added Nov 24).** The #30 review (Nov 19) found that the #29 rule also drops a zone the request *does* name in everyday words ("LA time", "UK time", lowercase "pst"), so the draft falls back to Chicago. The 30-case set can't see this, because its zone requests all say "Pacific time", "Eastern" and so on. These three cases measure the gap. They are labeled `#30 (known gap)` because they track an open problem, not a fixed bug, and they are expected to fail until it is fixed.

| Case | Issue | Request | Correct draft |
| --- | --- | --- | --- |
| r03 | #30 (known gap) | "...edit drafts on Nov 9 from 10am to 2pm LA time." | Contributor, Mon Nov 9, 10am-2pm Los Angeles time |
| r04 | #30 (known gap) | "...schedule posts on Nov 9 from 9am to 5pm UK time." | Contributor, Mon Nov 9, 9am-5pm London time |
| r05 | #30 (known gap) | "...see analytics on Nov 9 from 8am to noon pst." | Viewer, Mon Nov 9, 8am-noon Los Angeles time |

| Date | Code | Model | Passed | r01 | r02 | r03 | r04 | r05 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Nov 24, 2026 | main (after #30) | nvidia/nemotron-3.5-lightning-30b-a3b | 2/5 | PASS | PASS | FAIL | FAIL | FAIL |

| Case | Expected | Draft | Off by |
| --- | --- | --- | --- |
| r03 | 10am-2pm Los Angeles (18:00-22:00 UTC) | 10am-2pm Chicago (`10:00-06:00`) | 2 h early |
| r04 | 9am-5pm London (09:00-17:00 UTC) | 9am-5pm Chicago (`09:00-06:00`) | 6 h late |
| r05 | 8am-noon Los Angeles (16:00-20:00 UTC) | 8am-noon Chicago (`08:00-06:00`) | 2 h early |

Email, role, tasks and clock times are right in all three; only the zone is wrong, so each failure is this gap alone. r01 and r02 still pass. The scored draft can't show which zone the model first answered, because the app replaces it before scoring. Checked directly, the app's zone rule (`_request_mentions_zone` in `app/agent.py`, no model call) rejects Los Angeles and London for these three requests, so the drafts would fall back to Chicago even if the model named the right zone. Fix ideas from the #30 review, for after submission: match 3-letter abbreviations case-insensitively, and add a short alias list (LA, NYC, UK, Hawaii, Arizona). The owner still sees the zone before approving.

## Live reliability checks (Week 3)

| Check | Target | Result | Date |
| --- | --- | --- | --- |
| `scripts/demo_journey.py` against Cloud Run | completes, chain ok | Not run. The same journey was done by hand on the live app (below); Verify chain: intact, 67 events | Nov 23 |
| Scheduler job runs, no duplicate expiry events (`scripts/metrics.sql` #3) | 0 rows | Runs every minute; 1 grant expired, exactly 1 `grant.expired` event | Nov 23 |
| Allowed actions after end (`scripts/metrics.sql` #1) | 0 | 0, across 4 ended grants (1 expired, 3 revoked) | Nov 23 |
| Expiry job lag (`scripts/metrics.sql` #4) | under 90 s | 2.8 s | Nov 23 |

Counted from the live audit log (Firestore `audit_events`, read-only) and the Cloud Run request log, not by running `metrics.sql`. Joclyn's `export_bigquery.py` run on Nov 23 brought these events into the dashboard, and the safety checks there agree: 0 actions after end, 0 duplicate expiry events ([screenshot](evidence/dashboard-live-2026-11-23.png)).

### Nov 23 live run (Mohamed as owner, Andrew and Joclyn as invitees)

Cloud Run revision `roleready-00004-gvz`. Times are UTC; ET is UTC-5.

**Expiry.** Andrew, contributor, `edit_drafts` only, window 23:40-23:45 (America/New_York).

| Step | Time | Result |
| --- | --- | --- |
| Invite created, then approved | 23:39:55, 23:39:59 | 4 s between them |
| Andrew accepts | 23:40:41 | 42 s after approval |
| `edit_drafts` inside the window | 23:41:00 | Allowed |
| Window ends | 23:45:00 | |
| Scheduler writes `grant.expired` | 23:45:02.8 | 2.8 s after the end, one event |
| `edit_drafts` after the end | 23:48:21 | Blocked: `expired` |

**Revoke.**

| Step | Time | Result |
| --- | --- | --- |
| Owner revokes Andrew's grant (ending Nov 28) | 23:40:27.8 | |
| Andrew clicks `edit_drafts` | 23:40:31.8 | Blocked: `revoked`, 4 s later |
| Owner revokes Andrew's original grant (ending Nov 24) | 23:20:17 | |
| Andrew clicks `edit_drafts` | 23:21:52 | Blocked: `revoked` |

Joclyn's original grant (ending Dec 20) was also revoked, at 23:20:11. She got a new one at 00:01 on Nov 24 (window from 00:06), and her clicks at 00:02 and 00:05 were blocked as `not_started`, then allowed at 00:08. Both active grants now end Nov 28 around 00:01-00:04 UTC (Nov 27, about 7 PM ET).

**Refusals seen in the same session:** 3 `wrong_user` (an invite opened while signed in under a different email), 1 `token_reused`, 2 Access Assistant drafts rejected by validation. Each was logged with its reason.

**Invite time.** Create to approve took 2-4 s every time, and approve to accept took 22-46 s. The audit log doesn't record how long the owner spends filling in the form, so the usability measure still comes from the timed local run (45 s).

**Audit chain.** Verify chain at 00:49 UTC on Nov 24: "Chain intact: 67 events verified" ([screenshot](evidence/live-audit-verify-2026-11-23.png)).
