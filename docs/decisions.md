# Decisions log

The Nov 4 brief asks the team to confirm five things (section 12). Each row shows the recommendation built into this codebase. Record the team's call, the date and who decided. Change the code only after a decision lands here.

| # | Decision (brief §12) | Recommendation in the code | Status | Decided by / date |
| --- | --- | --- | --- | --- |
| D1 | MVP scope: roles, permissions, task types, journey | 3 roles, 5 task types, matrix in `app/policy.py`, time zone on every invitation | Proposed | |
| D2 | Newly integration | Not adopted. Newly was used only for the Nov 6 hackathon prototype; the BUILD handbook requires only Google Cloud and NVIDIA. `docs/newly-integration.md` is no longer part of the MVP | Decided | Team, Nov 9 |
| D3 | Architecture and deployment | Cloud Run + Firestore + Firebase Auth + Cloud Scheduler + Secret Manager. Local development and IAM testing on Floci (floci-gcp). Real Google Cloud for the demo and the final submission | Proposed | |
| D4 | Analytics | Live success measures in the app (`GET /metrics`), plus a batch export to BigQuery for a Data Studio (formerly Looker Studio) report (`scripts/export_bigquery.py`, `scripts/metrics.sql`). Until Nov 22 the report ran on sample data in a separate BigQuery Sandbox project ([screenshot](evidence/dashboard-sample-data-2026-11-20.png)). Switched Nov 22: `scripts/export_bigquery.py` exports the live app's records to `roleready-515202`, and the report reads that data ([screenshot](evidence/dashboard-live-2026-11-22.png); steps and views in `scripts/dashboard_views.sql`). Rerun the export and refresh the report for newer numbers. Screenshots in `docs/evidence/` are the lasting record: Sandbox tables expire in January, and the team project is deleted after grading | Decided | Team, Nov 20; switched Nov 22 |
| D5 | Responsibilities and milestones | Leads as listed in the brief §11. Each lead owns the matching Claude Code prompt in the setup guide | Proposed | |
| D6 | Team repository host | `github.com/mkaba214/roleready`, owned by Mohamed (@mkaba214) as Team Lead; Andrew (@dmandrew01) and Joclyn (@JDenise25) are collaborators (Ashley left on Nov 10, see D7). Public, so branch protection works on GitHub Free. `main` takes changes only through reviewed pull requests with green CI | Decided | Team, Nov 5 |
| D7 | Ashley leaves the team | Ashley (@Aphillipstech) resigned on Nov 10. Her grants come out of `infra/iam/iam.yaml`. Her areas (Firebase Auth, invite tokens, revoke, expiry job, threat model) move to Andrew, her named backup in the BUILD plan. Mohamed replaces her as second code owner on security paths. Of her Google Cloud roles, only `roles/firebaseauth.admin` is reassigned: Andrew takes it (issue #10), Joclyn's analytics work doesn't need it (least privilege). Her other roles are not reassigned | Decided | Team, weekend meeting (issue #10) |
| D8 | User testing | Outside people don't use the app hands-on. Instead, the user survey gets a section with three screenshot tasks from the owner's journey (invite a freelancer, see what they did, remove their access), each rated for ease (1-5), plus a usefulness rating. The usability measure in the brief §8 is updated to match | Decided | Team, Nov 15 |
| D9 | Audit retention | Keep every audit event for the capstone: no deletion, because deleting rows breaks `verify_chain()`. Google's log defaults stay (400 days Admin Activity, 30 days Data Access). Mohamed deletes `roleready-515202` after grading, around Dec 31, which removes Firestore, BigQuery and the logs together. A real product would archive events older than a year to locked Cloud Storage with a chain checkpoint ([audit-retention.md](audit-retention.md)) | Decided | Team, Nov 20 (PR #38) |

## Decisions already made in the code (change with care)

| Decision | Why |
| --- | --- |
| Expiry is checked on every request, not only by the job | Access ends on the second even if the scheduler is late |
| The agent proposes and never grants | A model reply cannot create access; the owner approves |
| Audit log is hash-chained | Tampering is detectable (`GET /audit/verify`) |
| IAM is managed as code in `infra/iam/iam.yaml` | Every grant is reviewed in a pull request and tested |
| Teammate IAM grants expire on Dec 1, 2026 | Same principle as the product: access ends when the work ends |
