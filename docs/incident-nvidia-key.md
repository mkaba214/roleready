# Incident: the NVIDIA API key leaked (owner: Andrew)

Use this when an NVIDIA key (`nvapi-...`) shows up anywhere it shouldn't: a commit, a PR, Slack, a screenshot, a log, a chat with an AI tool, a shared screen. Treat it as leaked even if you deleted it a minute later. Threat model row I3.

**Revoke first, investigate second.** Revoking is safe at any time: when the key stops working, the Access Assistant returns an error and manual invites keep working (threat model D1), so nothing else breaks.

## Who does what

| Step | Who | Needs |
| --- | --- | --- |
| Revoke the key at NVIDIA | Whoever created the key (their build.nvidia.com account) | Their NVIDIA sign-in |
| Add the new key to Secret Manager, disable the old version | Andrew | `roles/secretmanager.admin` |
| New Cloud Run revision | Mohamed | `roles/run.admin` |
| Check who read the secret | Andrew | `roles/logging.privateLogViewer` |

If the person for a step isn't around, the project Owner can do it (break-glass).

## Which key leaked?

- **The deployed key** lives in Secret Manager as `nvidia-api-key`. Cloud Run reads it as `NVIDIA_API_KEY` (`infra/deploy.sh`). Do every step below.
- **A teammate's local key** lives only in their `.env`. Do step 1, put the new key in their own `.env`, and skip steps 2 to 4. Keep local keys and the deployed key separate, so one leak never takes down both.

## Steps

1. **Revoke the leaked key.** The key's owner signs in at build.nvidia.com, opens the API Keys page, and deletes or revokes that key. Then they create a new one. NVIDIA shows a key only once, at creation, so they copy it straight into step 2 and don't paste it anywhere else.

2. **Add the new key as a new secret version** (Andrew). The input is hidden and never goes into shell history:

   ```bash
   read -r -s -p "New NVIDIA key: " K; echo
   printf '%s' "$K" | gcloud secrets versions add nvidia-api-key --data-file=- --project "$PROJECT_ID"
   unset K
   ```

3. **Start a new Cloud Run revision** (Mohamed), so every instance restarts on the new version. No rebuild needed:

   ```bash
   gcloud run services update roleready --region us-central1 --project "$PROJECT_ID" \
     --update-secrets NVIDIA_API_KEY=nvidia-api-key:latest
   ```

   Check: sign in as the owner and ask the Access Assistant to draft one invitation. It should succeed, and Cloud Run logs should show no `NVIDIA API returned HTTP 401`.

4. **Disable the old version** (Andrew), once step 3 works:

   ```bash
   gcloud secrets versions list nvidia-api-key --project "$PROJECT_ID"
   gcloud secrets versions disable OLD_VERSION_NUMBER --secret nvidia-api-key --project "$PROJECT_ID"
   ```

   Disable, don't destroy, so the evidence stays until the log check (step 5) and the write-up (step 7) are done.

5. **Check who read the secret** (Andrew). `scripts/iam.py apply` turns on Data Access logs for Secret Manager. In Logs Explorer, set the time range to start before the leak:

   ```
   protoPayload.serviceName="secretmanager.googleapis.com"
   protoPayload.methodName:"AccessSecretVersion"
   ```

   Every read should come from `roleready-run@...`. Any other principal is a second incident: remove its access through `iam.yaml` and tell Mohamed.

6. **Clean up where it leaked.**
   - **Git:** remove the key with a normal follow-up commit on a branch. Never force-push or rewrite `main` (CLAUDE.md rule 8). The key is still in history, which is why step 1 comes first: a revoked key in history is harmless.
   - **Slack, PR or issue comments:** delete the message or comment.
   - **AI chat tools:** you can't take it back. Revoking is the fix.

7. **Write it down.** Open a GitHub issue titled `Security incident: NVIDIA key` with the label `P1`: when it leaked, where, when it was revoked, what step 5 showed, and what changes so it doesn't happen again. Never put the key, or any part of it, in the issue.

## Prevention already in place

- Keys live in Secret Manager. Only `roleready-run` can read `nvidia-api-key` (`infra/iam/iam.yaml`), and every read is logged.
- `.env*` is git-ignored. CI runs gitleaks on every PR, and the optional pre-commit hook (`pre-commit install`) runs it before each commit.
- The app never logs the key or puts it in an error message (`test_nvidia_client_errors_never_leak_the_key`).
