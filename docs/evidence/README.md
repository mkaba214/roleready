Put IAM evidence here: policy exports, audit output, denial screenshots.
Never store keys, tokens or personal emails in this folder.

## IAM Phase 2 on `roleready-515202` (Nov 19)

Applied by Andrew with `python scripts/iam.py apply --target gcp --project roleready-515202`, after Mohamed's OK on #25.

- `project-iam-policy.json`: `gcloud projects get-iam-policy roleready-515202 --format=json` right after apply. Teammate emails are replaced with `user:<name>@REDACTED` (from the git-ignored `infra/iam/team.local.yaml`), and the project number with `PROJECT_NUMBER`.
- `nvidia-api-key-iam-policy.json`: `gcloud secrets get-iam-policy nvidia-api-key`. Only `roleready-run` can read the key; no person has `secretAccessor`.

Re-plan after apply shows 1 change: the `roleready-integration-key` accessor binding, skipped because that secret isn't created yet (D2). One finding stays on purpose: Google's default `roles/editor` on the Compute Engine default service account, used by the first source deploy. Issue #35 removes it once we're live.

- `permission-denied-nvidia-key.png` (Nov 20): Joclyn, signed in with her own account, runs `gcloud secrets versions access latest --secret=nvidia-api-key --project=roleready-515202` and gets `PERMISSION_DENIED` (`secretmanager.versions.access`, `IAM_PERMISSION_DENIED`). A team member with project access still can't read the key. Her email is blacked out.

- `troubleshoot-nvidia-api-key.json` (Nov 20): Policy Troubleshooter for Joclyn and `secretmanager.versions.access` on `nvidia-api-key`: `CANNOT_ACCESS`. Neither the secret's policy nor the project's grants it, and no deny policy is involved. Trimmed to the verdicts, emails and the project number redacted. This was the last Phase 2 step 3 item.

## `serviceUsageConsumer` for Andrew, PR #39 (Nov 20)

- `iam-apply-2026-11-20.txt`: plan, apply, re-plan. One grant added, time-boxed to Dec 1. The re-plan shows the same two known leftovers as Nov 19 (integration-key binding, Editor on the default SA). The new grant took about 12 minutes to start working (`USER_PROJECT_DENIED` until then).

## Dashboard

- `dashboard-sample-data-2026-11-20.png` (Nov 20): the Data Studio report on sample data from a scripted run of the local app (D4). 187 task attempts (61 allowed, 126 blocked), all 6 grants ended (4 expired, 2 revoked), and the decision recheck found 0 disagreements.
- `dashboard-agent-accuracy-2026-11-22.png` (Nov 22): the same report with the agent accuracy chart added: 21, 28, 28 and 28 of 30 drafts correct across the four runs, against the target of 27. The chart reads `eval_runs.csv`, uploaded to the Sandbox as table `eval_runs`.
- `eval_runs.csv`: one row per eval run, copied by hand from `docs/test-results.md` (`evals/results/` is git-ignored). The chart shows only the `brief_30` rows; the `regression` rows are scored out of 2 and stay off the dashboard. `test-results.md` lists three Nov 17 regression runs, all 0/2; the CSV keeps one row for them.
- `dashboard-live-2026-11-22.png` (Nov 22): the report on live data after the switch (D4). Joclyn ran `export_bigquery.py --project roleready-515202` with her own login (23 audit events: Mohamed's Nov 20 deploy test, plus her accept and five task clicks on Nov 22) and created the views in `roleready-515202`. 10 task attempts: 6 allowed, 4 blocked (3 role doesn't allow, 1 not started yet). 3 invites created and approved, 2 accepted, 3 wrong-user accepts blocked. All three safety checks 0. No grant has ended yet, because both run to December. The decision recheck in `scripts/dashboard_views.sql` agrees with the app on all 10 attempts. The agent accuracy chart still reads `eval_runs` in the Sandbox.
