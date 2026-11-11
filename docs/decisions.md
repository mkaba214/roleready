# Decisions log

The Nov 4 brief asks the team to confirm five things (section 12). Each row shows the recommendation built into this codebase. Record the team's call, the date and who decided. Change the code only after a decision lands here.

| # | Decision (brief §12) | Recommendation in the code | Status | Decided by / date |
| --- | --- | --- | --- | --- |
| D1 | MVP scope: roles, permissions, task types, journey | 3 roles, 5 task types, matrix in `app/policy.py`, time zone on every invitation | Proposed | |
| D2 | Newly integration | Not adopted. Newly was used only for the Nov 6 hackathon prototype; the BUILD handbook requires only Google Cloud and NVIDIA. `docs/newly-integration.md` is no longer part of the MVP | Decided | Team, Nov 9 |
| D3 | Architecture and deployment | Cloud Run + Firestore + Firebase Auth + Cloud Scheduler + Secret Manager. Local development and IAM testing on Floci (floci-gcp). Real Google Cloud for the demo and the final submission | Proposed | |
| D4 | Analytics | Live success measures in the app (`GET /metrics`), plus a nightly batch export to BigQuery for Looker Studio (`scripts/export_bigquery.py`) | Proposed | |
| D5 | Responsibilities and milestones | Leads as listed in the brief §11. Each lead owns the matching Claude Code prompt in the setup guide | Proposed | |
| D6 | Team repository host | `github.com/mkaba214/roleready`, owned by Mohamed (@mkaba214) as Team Lead; Andrew (@dmandrew01), Ashley (@Aphillipstech) and Joclyn (@JDenise25) are collaborators. Public, so branch protection works on GitHub Free. `main` takes changes only through reviewed pull requests with green CI | Decided | Team, Nov 5 |

## Decisions already made in the code (change with care)

| Decision | Why |
| --- | --- |
| Expiry is checked on every request, not only by the job | Access ends on the second even if the scheduler is late |
| The agent proposes and never grants | A model reply cannot create access; the owner approves |
| Audit log is hash-chained | Tampering is detectable (`GET /audit/verify`) |
| IAM is managed as code in `infra/iam/iam.yaml` | Every grant is reviewed in a pull request and tested |
| Teammate IAM grants expire on Dec 1, 2026 | Same principle as the product: access ends when the work ends |
