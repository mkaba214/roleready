Put IAM evidence here: policy exports, audit output, denial screenshots.
Never store keys, tokens or personal emails in this folder.

## IAM Phase 2 on `roleready-515202` (Nov 19)

Applied by Andrew with `python scripts/iam.py apply --target gcp --project roleready-515202`, after Mohamed's OK on #25.

- `project-iam-policy.json`: `gcloud projects get-iam-policy roleready-515202 --format=json` right after apply. Teammate emails are replaced with `user:<name>@REDACTED` (from the git-ignored `infra/iam/team.local.yaml`), and the project number with `PROJECT_NUMBER`.
- `nvidia-api-key-iam-policy.json`: `gcloud secrets get-iam-policy nvidia-api-key`. Only `roleready-run` can read the key; no person has `secretAccessor`.

Re-plan after apply shows 1 change: the `roleready-integration-key` accessor binding, skipped because that secret isn't created yet (D2). One finding stays on purpose: Google's default `roles/editor` on the Compute Engine default service account, used by the first source deploy. Issue #35 removes it once we're live.

Still to capture: Joclyn's `PERMISSION_DENIED` on `gcloud secrets versions access latest --secret=nvidia-api-key` (screenshot) and the `troubleshoot-policy` check (see `docs/iam-runbook.md` Phase 2 step 3).
