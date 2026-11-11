# RoleReady: instructions for Claude Code

RoleReady gives a small business owner time-boxed, least-privilege access control for freelancers, with an NVIDIA-powered Access Assistant and a tamper-evident audit log. GCLP BUILD capstone, team of four, final PR due Nov 28, 2026 11:59 PM ET. Product brief: `docs/product-brief.md`. Open decisions: `docs/decisions.md`.

## Commands

- Install: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt`
- Tests: `pytest` (must pass before any change is called done)
- IAM rules: `python scripts/iam.py lint`
- Run locally, in memory: `cp .env.example .env && uvicorn app.main:create_app --factory --reload --env-file .env`
- Run locally on Floci (Firestore + Firebase Auth + IAM emulated): `docker compose up -d floci-gcp && python scripts/floci_seed.py && uvicorn app.main:create_app --factory --reload --env-file .env.floci`
- IAM enforcement tests: `FLOCI_GCP_URL=http://localhost:4588 pytest tests/iam -v`
- Full journey smoke test: `python scripts/demo_journey.py --base-url http://localhost:8000`

## Map

- `app/policy.py` pure permission rules (deny by default, clock passed in). `app/services.py` business logic and audit. `app/main.py` routes. `app/agent.py` + `app/llm.py` NVIDIA Access Assistant. `app/auth.py` Firebase, demo and server-to-server integration sign-in. `app/store/` memory and Firestore.
- `infra/iam/iam.yaml` every IAM grant. `scripts/iam.py` lint, plan, apply, audit. `infra/*.sh` setup, deploy, scheduler.
- `evals/` 30-case agent eval (brief target 27 of 30). `docs/` runbooks and templates.

## Rules (security first)

1. Never read, print or edit `.env`, `.env.floci` or `infra/iam/team.local.yaml`, and never put keys, tokens or teammate emails in code, docs, commits or chat.
2. Write or update a test first for any change to permissions, expiry, revoke, audit, auth or the agent. Keep `policy.py` pure: no I/O, no `datetime.now()`.
3. The Access Assistant proposes and never grants. Do not give it store access or write tools. Every model output goes through `policy.validate_invitation`.
4. IAM changes happen only in `infra/iam/iam.yaml`, then `scripts/iam.py plan` and `apply`. Never run `gcloud ... set-iam-policy` or `add-iam-policy-binding` yourself; print the command for a human instead. Never grant basic roles (owner, editor, viewer) or create service-account keys.
5. Store times in UTC with an IANA time zone for display. Every invitation carries `timezone`.
6. Before deploying or touching a real Google Cloud project, stop and ask. Local work uses memory or Floci.
7. Keep changes small, on a branch named `<name>/<topic>`, with a clear commit message. Run `pytest` and `python scripts/iam.py lint` before each commit.
8. Repository: `github.com/mkaba214/roleready` (owner: Mohamed). Never commit to or push `main`; push the branch and open a pull request (`gh pr create --fill --base main`). Never force-push, and never commit Floci `data/`. Workflow: `CONTRIBUTING.md`.

## Team owners

Mohamed (@mkaba214): cloud engineering, deploy, CI. Andrew (@dmandrew01): permission rules, Access Assistant, IAM. Ashley (@Aphillipstech): Firebase Auth, invite tokens, revoke, expiry job, threat model. Joclyn (@JDenise25): research, metrics, BigQuery + Looker Studio, evals, written docs. Reviewers per path: `.github/CODEOWNERS`.
