# Threat model (STRIDE). Owner: Ashley. Reviewer: Andrew.

Scope: invite, approve, accept, act, revoke, expire, and the Access Assistant.
Each row names the test that proves the control. Add rows as you find new threats.

| # | Threat | Example | Control | Test |
| --- | --- | --- | --- | --- |
| S1 | Spoofing | Caller pretends to be the owner | Firebase ID token verified server-side; demo header ignored in firebase mode | `test_firebase_mode_rejects_missing_and_bad_tokens` |
| S2 | Spoofing | Someone else uses Sam's invite link | Accept requires the signed-in email to match the invitee | `test_wrong_person_cannot_use_token` |
| S3 | Spoofing | Anyone calls the expiry job | OIDC token, audience and service-account email checked; fails closed if unset | `test_expiry_endpoint_needs_scheduler_identity` |
| T1 | Tampering | Edit an audit row to hide a denial | Hash chain; `/audit/verify` names the broken event | `test_edited_row_breaks_chain_at_that_event` |
| T2 | Tampering | Recompute the edited row's hash | Next row's `prev_hash` no longer matches | `test_rehashed_edit_still_breaks_next_link` |
| T3 | Tampering | Browser writes Firestore directly | Firestore rules deny all client access | `infra/firestore.rules` |
| R1 | Repudiation | "I never tried to open analytics" | Every allow and deny is logged with actor and reason | `test_grid` (asserts the audit row) |
| I1 | Info disclosure | Freelancer reads the audit log or grant list | Owner-only routes, enforced in the service layer | `test_freelancer_cannot_use_owner_routes` |
| I2 | Info disclosure | Invite token leaks from logs or the DB | Token in URL fragment (not sent to servers); only SHA-256 stored | `Invitation.public()` excludes `token_hash` |
| I3 | Info disclosure | NVIDIA key leaks | Secret Manager, `.gitignore`, gitleaks in CI, key never in error messages | `test_nvidia_client_errors_never_leak_the_key` |
| D1 | Denial of service | NVIDIA rate limit (about 40 RPM) | Retries with backoff; assistant failure never blocks manual invites | `test_nvidia_client_retries_429_then_succeeds` |
| D2 | Denial of service | Huge prompt | 2,000-character cap before any model call | `test_long_and_empty_input_never_reach_the_model` |
| E1 | Elevation | Contributor gains `manage_access` | Invitations cannot grant owner or `manage_access`; grants cannot exceed role | `test_bad_invitations_rejected`, `test_grant_cannot_widen_role` |
| E2 | Elevation | Prompt injection makes the agent grant owner | Agent has no write tools; policy rejects the draft; owner must approve | `test_injection_cannot_produce_owner_access` |
| E3 | Elevation | Access continues after the window | Clock checked on every request; job only tidies status | `test_access_ends_on_the_second_even_if_job_never_runs` |
| E4 | Elevation | Reused or expired invite link | Single use (410), 72-hour link lifetime (410) | `test_reused_token_is_410`, `test_forged_and_expired_tokens` |

### Added Nov 5 (Newly integration and IAM as code)

| # | Threat | Example | Control | Test |
| --- | --- | --- | --- | --- |
| S4 | Spoofing | Someone calls the API pretending to be the Newly Backend | 32+ character key from Secret Manager, constant-time compare, off unless configured | `test_integration_rejects_bad_key_and_missing_user` |
| E5 | Elevation | Leaked integration key used to act as the owner | Owner actions blocked on the integration channel by default | `test_integration_cannot_act_as_owner_by_default` |
| I4 | Info disclosure | Browser JavaScript sends the integration key | Key header excluded from CORS; key lives only on the Newly Backend | `test_cors_only_for_listed_origins` |
| R2 | Repudiation | "That action came from the web app, not Newly" | Every integration call is tagged `via: newly` in the audit log | `test_integration_freelancer_flow_is_tagged` |
| E6 | Elevation | A teammate's cloud role is widened in a hurry (Editor "just to fix it") | IAM only in `iam.yaml`; CI lint blocks basic roles, impersonation roles, project-wide act-as, and IAM-admin + deployer on one person | `tests/iam/test_iam_policy.py` |
| E7 | Elevation | A workload account reads a secret it does not need | Secret-level grants only to `roleready-run`; proven with IAM enforcement on Floci | `tests/iam/test_floci_enforcement.py` |
| E8 | Elevation | Teammate access outlives the project | Every person's grant carries `request.time < 2026-12-01` | `test_time_boxed_grant_stops_working_after_it_expires` |
| T4 | Tampering | Two admins edit IAM at once and one overwrites the other | Read-modify-write with the policy etag; conflict fails | `test_concurrent_edit_fails_instead_of_overwriting` |
| I5 | Info disclosure | Emulator sign-in left on in production | App refuses to start on Cloud Run with `FIREBASE_AUTH_EMULATOR_HOST` set | `test_wildcard_cors_and_emulator_on_cloud_run_refused` |

## Open items

- [ ] Rate-limit failed accept attempts per IP (Cloud Armor or an in-app counter).
- [ ] Decide audit retention (how long to keep events) and write it in the README.
- [ ] Consent text for the 5 user-testing sessions.
- [ ] Incident steps if the NVIDIA key leaks: revoke at build.nvidia.com, add a new Secret Manager version, redeploy.
