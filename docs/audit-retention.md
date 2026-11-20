# Audit retention (proposal, owner: Andrew)

**Status: Proposed.** This answers the threat-model open item "decide audit retention (how long to keep events) and write it in the README". Once the team agrees, it becomes decision D9 in `docs/decisions.md`, and the README gets one line under Known limitations.

## What we keep today

| Where | What | How long, today |
| --- | --- | --- |
| Firestore `audit_events` | Every allow, deny, invite, approve, accept, revoke and expiry. One hash chain per workspace. Rows include freelancer emails (`invitee`, `user` in `details`) | Forever. Nothing deletes them |
| BigQuery `roleready.audit_events` | Copy of the Firestore rows for the dashboard (`scripts/export_bigquery.py`) | Replaced on every export, so never more than Firestore |
| Cloud Logging, `_Required` bucket | Google's Admin Activity logs: IAM changes, deploys, secret creation | 400 days, set by Google, free, can't be changed |
| Cloud Logging, `_Default` bucket | Data Access logs, including who read `nvidia-api-key` (turned on by `iam.py apply`) | 30 days (Google's default) |

**The constraint:** `verify_chain()` in `app/audit.py` starts at sequence 1 from the genesis hash. Deleting old rows, by hand or with a Firestore TTL policy, shows up as a `sequence gap` and the chain check fails. So "delete after N days" needs a design change, not only a setting.

## Proposal

**1. For the capstone (until the project is shut down): keep every event.**
- Volume is tiny (a demo workspace, a few hundred rows), and graders and the demo video need the full history, including the denials.
- No code change. The chain stays whole and `verify_chain()` keeps checking from the first event.
- Keep Google's log defaults: 400 days for Admin Activity, 30 days for Data Access. 30 days covers the leaked-key check in `docs/incident-nvidia-key.md` for the life of the capstone. Longer retention in `_Default` costs money.

**2. When the program ends: delete the project.** All teammate grants end on Dec 1 (time-boxed in `iam.yaml`). After grading, Mohamed deletes `roleready-515202`. That removes Firestore, BigQuery and the logs together. Google keeps a deleted project recoverable for 30 days, then it's gone. Before deleting, export the evidence we want to keep (already in `docs/evidence/`, no emails).

**3. For a real product (documented, not built).**
- Keep 1 year of events per workspace in Firestore, then move older events to a Cloud Storage bucket with a locked retention policy, so nobody can edit or delete the archive early.
- Trimming keeps the chain checkable: store a checkpoint (`seq` and `hash` of the last archived event) in `audit_heads`, and have `verify_chain()` start from it instead of from the genesis hash. The archive file holds the earlier part, so the whole history can still be checked end to end.
- When an owner closes the workspace, delete its events after 30 days.
- Freelancer emails sit inside the hashed rows, so one person's data can't be erased without breaking the chain. Fix before handling real customer data: store a per-workspace pseudonym (a keyed hash of the email) in audit rows, and keep the email-to-pseudonym map outside the chain, where it can be deleted.

## Questions for the team

1. OK to keep every event for the capstone, with no deletion (point 1)?
2. Mohamed: OK to delete `roleready-515202` after grading, and when (point 2)?
3. Joclyn: does the dashboard need anything older than the current export? (It shouldn't, since the export replaces the table each run.)

## Once agreed

- `docs/decisions.md`: add D9 with the date and who decided
- `README.md` Known limitations: "Audit events are kept for the life of the demo project; a real product would archive after a year with a chain checkpoint (`docs/audit-retention.md`)."
- `docs/threat-model.md`: tick the open item and link here
