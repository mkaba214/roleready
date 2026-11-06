# Newly integration (brief §7 and decision D2)

**Recommendation:** Newly builds RoleReady's mobile front end. RoleReady's API on Cloud Run stays the system of record and enforces every rule. The Newly Backend calls RoleReady server to server.

## Why this shape

From Newly's docs ([integrations](https://docs.newly.app/backend/integrations.md), [secrets](https://docs.newly.app/backend/production-and-secrets.md)):

- Newly builds native iOS and Android apps (React Native and Expo) and comes with its own Newly Backend.
- Calls to outside services go from the Newly Backend, not from the app.
- Secrets live on the Newly Backend. "Never put a secret inside your app."
- Supabase, Firebase and other backends are not supported inside Newly, so the app cannot use RoleReady's Firebase sign-in directly.

```
Newly app (phone) ──► Newly Backend ──HTTPS + integration key──► RoleReady API (Cloud Run)
  user signs in          holds the key as a secret                 checks the key, applies the
  with Newly             sets X-Acting-User from the               same policy to the acting user,
                         signed-in Newly user                      tags audit events via=newly
```

## Security rules (owner: Andrew)

1. One random key, at least 32 characters, stored in Google Secret Manager as `roleready-integration-key` and in Newly's backend secrets. Nowhere else.
2. The Newly Backend sets `X-Acting-User` from its own signed-in user. Never from a value the app user types.
3. Owner actions over Newly are **off** (`INTEGRATION_ALLOW_OWNER=false`). The Newly app serves freelancers and viewers: accept an invite, see access, do tasks. Turn owner actions on only if the team decides it (record it in `docs/decisions.md`), because a leaked key would then control the workspace.
4. Every call through Newly is tagged `via: newly` in the audit log, so the owner can tell channels apart.
5. Rotate the key after the hackathon: add a new Secret Manager version, update Newly's secret, redeploy.
6. The key header is not allowed through CORS, so no browser can send it.

## Turn it on

```bash
# 1. Make a key and store it (Andrew)
python -c "import secrets; print(secrets.token_urlsafe(32))" | \
  gcloud secrets create roleready-integration-key --replication-policy=automatic --data-file=-
# 2. Grant only the Cloud Run service account access: add it in infra/iam/iam.yaml, then
python scripts/iam.py plan --target gcp && python scripts/iam.py apply --target gcp
# 3. Redeploy: infra/deploy.sh mounts the secret as INTEGRATION_API_KEY when it exists
bash infra/deploy.sh
# 4. In Newly, add the same value as a backend secret (Newly docs: Production and secrets)
```

## API the Newly app needs

All calls carry `X-RoleReady-Integration-Key: <key>` and `X-Acting-User: <signed-in email>`. Full schema: `https://<your-run-url>/docs`.

| Screen | Call | Notes |
| --- | --- | --- |
| Accept invitation | `POST /invitations/accept` `{"token": "..."}` | 410 if the link was used or expired; 403 if the email does not match |
| My access | `GET /me` | `grants[]` with `state`: pending, active, expired, revoked; times in UTC plus the invitation's `timezone` |
| Do a task | `POST /actions/{task_type}` | 200 allowed, 403 denied with `reason` |
| Owner screens (only if D2 allows) | `POST /invitations`, `POST /invitations/{id}/approve`, `GET /grants`, `POST /grants/{id}/revoke`, `GET /audit`, `GET /metrics`, `POST /agent/draft-invitation` | 403 `owner_blocked_on_channel` while `INTEGRATION_ALLOW_OWNER=false` |

## Prompt for the Newly agent (Nov 6 hackathon)

```text
Build a mobile app called RoleReady for freelancers who get temporary access to a small business workspace.
Screens:
1. Sign in (Newly sign-in).
2. "Accept invitation": paste or open an invite token, call our backend, show success or the error message.
3. "My access": list each grant with role, tasks, start and end in the grant's time zone, and a status chip (pending, active, expired, revoked).
4. "Do a task": five buttons (view_assets, edit_drafts, schedule_posts, view_analytics, manage_access). Each tap shows Allowed or Denied with the reason.
Backend: add server code that calls our REST API at ROLE_READY_BASE_URL (non-secret, put it in app config).
Every request sends header X-RoleReady-Integration-Key from the backend secret ROLE_READY_INTEGRATION_KEY,
and header X-Acting-User set to the signed-in user's email from Newly sign-in. Never put the key in the app.
Endpoints: POST /invitations/accept {token}; GET /me; POST /actions/{task_type} (200 allowed, 403 denied).
Style: clean, friendly, large tap targets. Green for allowed, red for denied, gray for pending.
```

## Hackathon fallback

If the Newly Backend cannot reach Cloud Run in time, have Newly render the same screens with sample data, and demo the live access lifecycle in RoleReady's web UI. Say so plainly in the submission.
