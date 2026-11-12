# Architecture

The policy engine decides access. The agent only proposes.

```
 Owner (Dana) ───────► ┌──────────── Cloud Run: FastAPI service ────────────┐ ──chat calls──► NVIDIA NIM API
                       │  Access Assistant (agent): drafts, explains audit  │                (build.nvidia.com)
 Freelancer ─────────► │  Policy engine: deny by default, checks the clock  │ ──verify token─► Firebase Auth
                       │  Audit writer: append-only, hash-chained           │ ──read, write──► Firestore ──nightly──► BigQuery + Looker Studio
 Cloud Scheduler ────► │  POST /jobs/expire: idempotent, fixed event IDs    │
 (every minute, OIDC)  │  Keys from Secret Manager                          │
                       └────────────────────────────────────────────────────┘
```

## Where each technology does real work

| Technology | Role | Code |
| --- | --- | --- |
| Cloud Run | Hosts API + web UI, scales to zero | `Dockerfile`, `infra/deploy.sh` |
| Firestore | Invitations, grants, audit events, audit chain heads | `app/store/firestore.py` |
| Firebase Authentication | Sign-in; server verifies ID tokens | `app/auth.py` |
| Cloud Scheduler | Calls `/jobs/expire` every minute with an OIDC token | `infra/scheduler.sh`, `app/auth.py` |
| Secret Manager | NVIDIA API key, mounted as an env var | `infra/setup.sh`, `infra/deploy.sh` |
| BigQuery + Looker Studio | Success-measure dashboard | `scripts/export_bigquery.py`, `scripts/metrics.sql` |
| NVIDIA NIM (build.nvidia.com) | Access Assistant: draft invitations, explain the audit log | `app/llm.py`, `app/agent.py` |

## Request flow

1. Owner types a request. `POST /agent/draft-invitation` sends it to the NVIDIA model.
2. The reply is parsed and checked by `policy.validate_invitation`. Bad roles, `manage_access`, missing end dates and past dates are rejected. Least-privilege warnings are attached.
3. Owner reviews the form and clicks Create (`POST /invitations`), then Approve. Approve returns a one-time link with the token in the URL fragment. Only a SHA-256 hash of the token is stored.
4. The freelancer signs in and accepts. One Firestore transaction flips the invitation to accepted, creates the grant and writes the audit event.
5. Every task request (`POST /actions/{task}`) runs `policy.evaluate` with the current time. Allowed and denied decisions are both logged.
6. At `expires_at`, the next request is denied on the clock. Within a minute, the scheduler's expiry job flips the grant to expired and writes one `grant.expired` event (fixed ID `{grant_id}:expired`). Running the job again writes nothing.
7. Revoke uses the same transaction pattern (`{grant_id}:revoked`). Revoke and expiry can race. Exactly one wins.

## Data model (Firestore)

| Collection | Key fields |
| --- | --- |
| invitations | workspace_id, invitee_email, role, task_types, start_at, expires_at, status (draft, approved, accepted, cancelled), source (manual, assistant), token_hash, token_expires_at, grant_id |
| grants | workspace_id, user_email, role, task_types, start_at, expires_at, status (active, expired, revoked), revoked_at, revoked_by, expired_at |
| audit_events | seq, ts, actor, action, target, decision, reason, details, prev_hash, hash |
| audit_heads | one doc per workspace: last seq and hash (serializes chain appends) |

## Endpoints

| Endpoint | Caller |
| --- | --- |
| `GET /health`, `GET /config` | Anyone |
| `GET /me` | Signed-in user |
| `POST /invitations`, `GET /invitations`, `POST /invitations/{id}/approve`, `POST /invitations/{id}/cancel` | Owner |
| `POST /invitations/accept` | Invitee with token, signed in as the invited email |
| `GET /grants`, `POST /grants/{id}/revoke` | Owner |
| `POST /actions/{task_type}` | Signed-in user. 200 allow, 403 deny. Both logged. |
| `GET /audit`, `GET /audit/verify` | Owner |
| `GET /metrics` | Owner. The brief's six success measures, live (focused dashboard) |
| `POST /agent/draft-invitation`, `POST /agent/explain-audit` | Owner |
| `POST /jobs/expire` | Cloud Scheduler service account only (OIDC) |
| `POST /dev/run-expiry` | Owner, demo mode only |

Any endpoint can also be called by a trusted server integration (the Newly Backend) with `X-RoleReady-Integration-Key` and `X-Acting-User`. The same rules apply to the acting user, audit events record `via: newly`, and owner actions over the integration are off unless `INTEGRATION_ALLOW_OWNER=true`.

## Local cloud (Floci)

`docker compose up -d floci-gcp` runs floci-gcp on port 4588 with IAM enforcement on. With `.env.floci`, the app uses the real Firestore and Firebase Admin libraries against the emulator (`FIRESTORE_EMULATOR_HOST`, `FIREBASE_AUTH_EMULATOR_HOST`). `scripts/iam.py --target floci` applies `infra/iam/iam.yaml` there, and `tests/iam` proves who can and cannot read each secret. The app refuses to start on Cloud Run if an emulator variable is set.

## Permission matrix

| Task | Owner | Contributor | Viewer |
| --- | --- | --- | --- |
| view_assets | allow | allow | allow |
| edit_drafts | allow | allow | deny |
| schedule_posts | allow | allow | deny |
| view_analytics | allow | deny | allow |
| manage_access | allow | deny | deny |

A grant can be narrower than its role (for example, a contributor with only `edit_drafts`). It can never be wider.
