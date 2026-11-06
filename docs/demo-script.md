# Hackathon demo script (2 minutes)

Setup: two browser windows side by side. Left: owner. Right: freelancer (private window).

1. **Problem (15 s).** "Dana hires a freelancer for launch week. Today she shares a password, and last month's contractor still has it."
2. **Assistant drafts (20 s).** Owner types: "Give sam@freelance.test editing for the launch, starting now for 3 minutes." Click Draft. Point at the NVIDIA tag and the least-privilege warning.
3. **Approve (10 s).** Create, Approve, copy the one-time link. "The assistant can't grant anything. Only Dana can."
4. **Accept and work (20 s).** Right window: open the link, sign in as Sam, accept. Click `edit_drafts` (allowed), `view_analytics` (denied, role_forbids_task), `manage_access` (denied).
5. **Expiry live (30 s).** Wait for the clock. Click `edit_drafts` again: denied, expired. "Access ended on the second, not when a job got around to it."
6. **Audit (20 s).** Owner: Verify chain (intact). Ask the assistant "Who was denied today?" It answers with event IDs. "Every decision, allowed or denied, is in a tamper-evident log."
7. **Close (5 s).** "RoleReady: the right access, for the right time, with proof."

Backup: if the live deploy fails, run locally and play the recorded 2-minute video.
