# RoleReady

**Time-boxed, least-privilege access for small businesses that hire freelancers.**
Team RoleReady · GCLP BUILD Capstone, Fall 2026 · UN SDG 9 (Industry, Innovation and Infrastructure)

> Links (fill in before Nov 28): [Live demo](https://roleready-340875597178.us-central1.run.app) · Deck (8 slides) · Video (5 min) · Written summary (3 pages)

Product brief: [docs/product-brief.md](docs/product-brief.md) · Open decisions: [docs/decisions.md](docs/decisions.md)

## Results

| Measure | Target | Result |
| --- | --- | --- |
| Actions after access ended | 0 | 0 |
| Decisions in the audit log | 100% | 187 of 187 on the sample journey ([screenshot](docs/evidence/dashboard-sample-data-2026-11-20.png)); on the live app, an independent recheck agrees with all 10 logged decisions |
| Duplicate expiry events | 0 | 0 |
| Grants without owner approval | 0 | 0 |
| Agent drafts correct | 27 of 30 | 28 of 30 on every run since the Nov 10 prompt fixes (4 runs, Nov 10-19; [test results](docs/test-results.md)) |
| Time to invite a freelancer | Under 2 min | 45 s (one internal run, local app) |

275 automated tests pass. Survey: 6 responses, usefulness 4.2 of 5. Details: [test results](docs/test-results.md), [feedback log](docs/feedback-log.md), [evidence](docs/evidence/).

**Verified:** the measures above; a team member with project access gets `PERMISSION_DENIED` reading the NVIDIA key ([evidence](docs/evidence/README.md)); the audit chain check (sample and local runs).

**Not claimed:** production readiness; results with real business owners (the survey reached mostly freelancers); the agent handling casual zone names like "LA time" (see [Known limitations](#known-limitations)).

## Audience and problem

Dana owns Bloom & Crumb, a six-person bakery business, and hires temporary collaborators to create content, edit drafts and schedule posts. She needs to give them the right access for the right time and know when it ended. RoleReady helps owners limit collaborator permissions, approve temporary access, and verify when access has ended.

- About 64 million Americans did freelance work in 2023 ([Upwork](https://www.upwork.com/research/freelance-forward-2023-research-report)).
- Third-party involvement appeared in 30% of breaches ([Verizon 2025 DBIR](https://www.verizon.com/about/news/2025-data-breach-investigations-report)).
- 83% of surveyed former employees still had access to a past employer's digital assets ([Beyond Identity, 2022](https://www.beyondidentity.com/resource/former-employees-admit-to-using-continued-account-access-to-harm-previous-employers)).

These sources give context. Interviews and usability tests check how often small-business owners actually hit these problems.

**SDG 9:** resilient infrastructure and small-enterprise participation in digital markets, through access-management practice a business without an IT team can use.

## What it does

1. **Access Assistant (NVIDIA).** The owner types a request in plain English. A model from build.nvidia.com drafts the invitation, including the time zone, and flags permissions wider than the job needs. Deterministic policy rules check every draft.
2. **Approved invitations.** The owner reviews and approves. The collaborator gets a single-use link that expires in 72 hours.
3. **Three roles, five task types.** Owner, Contributor, Viewer across view_assets, edit_drafts, schedule_posts, view_analytics, manage_access.
4. **Access ends exactly on time.** Every request checks the clock. A Cloud Scheduler job tidies status every minute and can run any number of times without duplicate events.
5. **Revoke** takes effect on the next request.
6. **Tamper-evident audit history.** Every allow and deny is logged in a hash chain. The assistant answers questions about the log and cites event IDs.
7. **Focused analytics dashboard.** The six success measures from the brief, live in the app (`GET /metrics`), plus a batch export to BigQuery for Looker Studio.

## Architecture

Cloud Run (FastAPI) · Firestore · Firebase Authentication · Cloud Scheduler (OIDC) · Secret Manager · BigQuery + Looker Studio · NVIDIA NIM API. Local development and IAM testing run on [Floci](https://floci.io/gcp/), a Google Cloud emulator. Details: [docs/architecture.md](docs/architecture.md).

## Start here

Repository: `https://github.com/mkaba214/roleready` (owner: Mohamed, Team Lead). To get access, push and pull, and open pull requests, follow [CONTRIBUTING.md](CONTRIBUTING.md). `main` only changes through reviewed pull requests.

New to the repo? Open it in VS Code with Claude Code. [CLAUDE.md](CLAUDE.md) gives Claude the project rules, and `.claude/settings.json` stops it from reading secrets or changing IAM directly.

### Run locally in memory (2 minutes)

Requires Python 3.12.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # demo sign-in + in-memory data; add NVIDIA_API_KEY to enable the assistant
uvicorn app.main:create_app --factory --reload --env-file .env
```

Open http://localhost:8000. Pick **owner@bloomandcrumb.test** from the demo dropdown, create and approve an invitation, then switch to **sam@freelance.test** (or open the invite link in a private window). API docs: http://localhost:8000/docs.

### Run locally on Floci (same code path as Google Cloud)

Requires Docker Desktop.

```bash
docker compose up -d floci-gcp                 # Firestore, Firebase Auth, Secret Manager, IAM... on port 4588
cp .env.floci.example .env.floci
python scripts/floci_seed.py                   # test sign-in users
uvicorn app.main:create_app --factory --reload --env-file .env.floci
```

Sign in with `owner@bloomandcrumb.test` and the password the seed script prints.

## Tests

```bash
pytest                                          # 275 tests, no network needed
python scripts/iam.py lint                      # least-privilege rules for infra/iam/iam.yaml
FLOCI_GCP_URL=http://localhost:4588 pytest tests/iam -v   # 18 IAM enforcement tests against Floci
python -m evals.run_eval                        # 30-case agent eval, brief target 27 of 30 (needs NVIDIA_API_KEY)
```

Coverage: the permission matrix, a 60-case role x task x state grid, time-window edges, idempotent expiry, revoke/expire races, audit tampering, auth back doors, the server-to-server integration path, time zones, the success-measures dashboard, prompt injection, NVIDIA client retries, and IAM least privilege. See [docs/test-results.md](docs/test-results.md).

## NVIDIA setup

1. Sign in at build.nvidia.com. Profile menu, Settings, API Keys, Generate. Each teammate makes their own key for local work.
2. Put the key in `.env` as `NVIDIA_API_KEY=...`. Never paste it in Slack or commit it.
3. Proof of concept: `python -m poc.agent_poc`
4. Compare models on the eval set, then keep the winner in `NVIDIA_MODEL`.

## Deploy to Google Cloud

```bash
export PROJECT_ID=your-project-id
bash infra/setup.sh                                          # APIs, Firestore, NVIDIA key value
python scripts/iam.py apply --target gcp --project $PROJECT_ID   # Andrew: service accounts + every IAM grant
# Mohamed, Firebase console: add Firebase to the project, then Authentication > Get started > Sign-in method > Email/Password on
npx firebase-tools deploy --only firestore:rules --project $PROJECT_ID
OWNER_EMAIL=owner@yourdomain.test FIREBASE_API_KEY=... bash infra/deploy.sh
bash infra/scheduler.sh
python scripts/firebase_user.py --project $PROJECT_ID add owner@yourdomain.test   # repeat per teammate and freelancer
```

Sign-in only accepts verified emails (threat S5), so create each account with `scripts/firebase_user.py` before sending the invite link. It prints a password-setup link; send it to that same email address. `CONFIGURATION_NOT_FOUND` from `firebase_user.py` means the Firebase console step above isn't done yet.

Optional, **Sign in with Google** next to email and password: in the Firebase console, turn on Authentication > Sign-in method > Google, and add the Cloud Run hostname under Authentication > Settings > Authorized domains. Then deploy with `FIREBASE_GOOGLE_SIGN_IN=true`. It works for Gmail and Google Workspace addresses; anyone else uses the password-setup link. Signing in grants nothing by itself: access still comes only from an approved invitation for that email (threat S8).

Set a $10 budget alert in Billing, Budgets & alerts. IAM details: [docs/iam-runbook.md](docs/iam-runbook.md).

Dashboard data: `pip install -r requirements-scripts.txt && python scripts/export_bigquery.py --project $PROJECT_ID` (add `--emulator http://localhost:4588` to practice on Floci), then build Looker Studio charts from [scripts/metrics.sql](scripts/metrics.sql).

## Security design

- Deny by default. Access needs an active grant, `start_at <= now < expires_at`, no revocation, and a role and grant that both include the task.
- The agent proposes. It has no database access and no tool that approves, grants or revokes.
- Invite tokens are random, single-use, stored only as SHA-256 hashes, and travel in the URL fragment.
- `/jobs/expire` accepts only the scheduler service account's OIDC token.
- IAM as code: every grant lives in `infra/iam/iam.yaml`, is linted in CI, tested against Floci with enforcement on, and teammate access expires Dec 1, 2026.
- Keys live in Secret Manager. `.env*` and teammate emails are git-ignored. CI runs gitleaks.
- Threat model: [docs/threat-model.md](docs/threat-model.md).

## Project layout

```
app/        FastAPI app: policy, audit, services, agent, llm, auth, store/, static/
tests/      pytest suites; tests/iam for IAM lint, tool and Floci enforcement
evals/      30-case agent eval set and runner
poc/        agent proof of concept
scripts/    iam.py, floci_seed.py, demo_journey.py, export_bigquery.py, metrics.sql
infra/      setup.sh, deploy.sh, scheduler.sh, firestore.rules, iam/iam.yaml
docs/       brief, decisions, architecture, IAM runbook, threat model, test results, feedback log, demo script
```

## Sample inputs

- Assistant: "Give sam@freelance.test editing and scheduling from Monday 9am to Friday 5pm."
- Assistant: "riley@client.test can look at analytics until Friday at 5pm Eastern."
- Should be rejected: "Make sam@freelance.test an owner forever."
- Audit question: "Who was denied access today?"

## Known limitations

- One simulated workspace. Owner identity comes from `OWNER_EMAIL`.
- The audit chain serializes writes through one Firestore document per workspace, fine for a small business, not for thousands of actions per second.
- No email delivery. The owner copies the invite link.
- Floci is a local test tool, not a security boundary. Real protection comes from the Google Cloud deploy.
- Model drafts depend on the chosen NVIDIA model. Track accuracy with `evals/`. Casual zone names like "LA time" or "pst" fall back to the workspace zone (feedback log, Nov 19), and the end of a weekday range can land a day late (e01, e14); the owner reviews every draft before approving.
- Audit events are kept for the life of the demo project; a real product would archive after a year with a chain checkpoint ([docs/audit-retention.md](docs/audit-retention.md)).

## Team and contributions

| Member | GitHub | Track | Leads (brief §11) | Contributions (update weekly with PR links) |
| --- | --- | --- | --- | --- |
| Mohamed Kaba (Team Lead) | [@mkaba214](https://github.com/mkaba214) | Cloud Engineering | Cloud engineering and integration | CI hardening: pinned runner, actions and Floci version; surfaced the hidden iam-floci failure |
| Andrew Hernandez | [@dmandrew01](https://github.com/dmandrew01) | Cloud Cybersecurity | Permission rules, AI agent, IAM, authentication and access lifecycle security | Starter repo: brief, Floci, IAM as code, Claude Code setup; fixed the time-boxed IAM test so iam-floci blocks on failure [#6](https://github.com/mkaba214/roleready/pull/6); fixed the Access Assistant: failure fields, reasoning off, working default model, eval 28 of 30 [#7](https://github.com/mkaba214/roleready/pull/7); time zone words only count next to a time [#15](https://github.com/mkaba214/roleready/pull/15); removed Ashley's access and took over her areas [#8](https://github.com/mkaba214/roleready/pull/8); Firebase Auth admin grant, D7 decided [#14](https://github.com/mkaba214/roleready/pull/14); threat model for sign-in, invite tokens, revoke and the expiry job [#18](https://github.com/mkaba214/roleready/pull/18); time zone folder names like "Pacific" no longer crash the Assistant or the invite form [#20](https://github.com/mkaba214/roleready/pull/20); incident steps for a leaked NVIDIA key [#28](https://github.com/mkaba214/roleready/pull/28), step fix [#31](https://github.com/mkaba214/roleready/pull/31); sign-in refuses unverified Firebase emails (S5) [#22](https://github.com/mkaba214/roleready/pull/22); the Access Assistant keeps only a zone the request mentions, regression 2 of 2 [#30](https://github.com/mkaba214/roleready/pull/30); iam.py finds gcloud on Windows [#27](https://github.com/mkaba214/roleready/pull/27) and IAM Phase 2 applied on the real project, redacted evidence in docs/evidence [#36](https://github.com/mkaba214/roleready/pull/36); invite links lock a user out after 5 failed accepts in 15 minutes [#26](https://github.com/mkaba214/roleready/pull/26), which relies on S5 [#42](https://github.com/mkaba214/roleready/pull/42); iam.py apply waits for service accounts it just created [#37](https://github.com/mkaba214/roleready/pull/37); serviceUsageConsumer so firebase_user.py can create team accounts [#39](https://github.com/mkaba214/roleready/pull/39), its apply evidence and the troubleshoot-policy check (a teammate CANNOT_ACCESS the NVIDIA key) [#45](https://github.com/mkaba214/roleready/pull/45); optional "Sign in with Google", off by default [#40](https://github.com/mkaba214/roleready/pull/40); audit retention decided (D9): keep every event, delete the project after grading [#38](https://github.com/mkaba214/roleready/pull/38), dashboard wording follow-up [#46](https://github.com/mkaba214/roleready/pull/46); removed the unused Nov 5 recap template [#49](https://github.com/mkaba214/roleready/pull/49); reviewed [#1](https://github.com/mkaba214/roleready/pull/1), [#3](https://github.com/mkaba214/roleready/pull/3), [#5](https://github.com/mkaba214/roleready/pull/5), [#9](https://github.com/mkaba214/roleready/pull/9), [#16](https://github.com/mkaba214/roleready/pull/16), [#17](https://github.com/mkaba214/roleready/pull/17), [#23](https://github.com/mkaba214/roleready/pull/23), [#34](https://github.com/mkaba214/roleready/pull/34), [#44](https://github.com/mkaba214/roleready/pull/44), [#47](https://github.com/mkaba214/roleready/pull/47), [#50](https://github.com/mkaba214/roleready/pull/50), [#52](https://github.com/mkaba214/roleready/pull/52) |
| Joclyn Davis | [@JDenise25](https://github.com/JDenise25) | Cloud Data Analytics | Research, metrics, analytics, agent evaluation, documentation | Removed Newly mentions [#9](https://github.com/mkaba214/roleready/pull/9); sample audit data generator and success-measures dashboard (BigQuery Sandbox + Data Studio) [#11](https://github.com/mkaba214/roleready/pull/11), wrong-user refusal and post-expiry check [#17](https://github.com/mkaba214/roleready/pull/17); regression eval set for the time zone bug [#16](https://github.com/mkaba214/roleready/pull/16), whose after-fix run caught a crash [#19](https://github.com/mkaba214/roleready/issues/19); feedback log, D8 and the usability measure [#34](https://github.com/mkaba214/roleready/pull/34); first 5 survey responses, dashboard on sample data, D4 decided [#43](https://github.com/mkaba214/roleready/pull/43); survey follow-ups for after submission [#41](https://github.com/mkaba214/roleready/issues/41); PERMISSION_DENIED on the NVIDIA key for a team member [#44](https://github.com/mkaba214/roleready/pull/44); agent accuracy chart on the dashboard [#47](https://github.com/mkaba214/roleready/pull/47); dashboard switched to live data from the deployed app [#50](https://github.com/mkaba214/roleready/pull/50); final survey results, 6 responses [#52](https://github.com/mkaba214/roleready/pull/52); reviewed [#7](https://github.com/mkaba214/roleready/pull/7), [#8](https://github.com/mkaba214/roleready/pull/8), [#14](https://github.com/mkaba214/roleready/pull/14), [#15](https://github.com/mkaba214/roleready/pull/15), [#18](https://github.com/mkaba214/roleready/pull/18), [#20](https://github.com/mkaba214/roleready/pull/20), [#22](https://github.com/mkaba214/roleready/pull/22), [#24](https://github.com/mkaba214/roleready/pull/24), [#26](https://github.com/mkaba214/roleready/pull/26), [#28](https://github.com/mkaba214/roleready/pull/28), [#30](https://github.com/mkaba214/roleready/pull/30), [#31](https://github.com/mkaba214/roleready/pull/31), [#36](https://github.com/mkaba214/roleready/pull/36), [#38](https://github.com/mkaba214/roleready/pull/38), [#39](https://github.com/mkaba214/roleready/pull/39), [#40](https://github.com/mkaba214/roleready/pull/40), [#42](https://github.com/mkaba214/roleready/pull/42), [#45](https://github.com/mkaba214/roleready/pull/45), [#46](https://github.com/mkaba214/roleready/pull/46), [#48](https://github.com/mkaba214/roleready/pull/48), [#49](https://github.com/mkaba214/roleready/pull/49), [#51](https://github.com/mkaba214/roleready/pull/51) |
