# Threat model (STRIDE). Owner: Andrew (from Ashley, Nov 10). Reviewer: Mohamed.

Scope: sign-in, invite, approve, accept, act, revoke, expire, and the Access Assistant.
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
| I3 | Info disclosure | NVIDIA key leaks | Secret Manager, `.gitignore`, gitleaks in CI, key never in error messages; if it leaks anyway: [incident steps](incident-nvidia-key.md) | `test_nvidia_client_errors_never_leak_the_key` |
| D1 | Denial of service | NVIDIA rate limit (about 40 RPM) | Retries with backoff; assistant failure never blocks manual invites | `test_nvidia_client_retries_429_then_succeeds` |
| D2 | Denial of service | Huge prompt | 2,000-character cap before any model call | `test_long_and_empty_input_never_reach_the_model` |
| E1 | Elevation | Contributor gains `manage_access` | Invitations cannot grant owner or `manage_access`; grants cannot exceed role | `test_bad_invitations_rejected`, `test_grant_cannot_widen_role` |
| E2 | Elevation | Prompt injection makes the agent grant owner | Agent has no write tools; policy rejects the draft; owner must approve | `test_injection_cannot_produce_owner_access` |
| E3 | Elevation | Access continues after the window | Clock checked on every request; job only tidies status | `test_access_ends_on_the_second_even_if_job_never_runs` |
| E4 | Elevation | Reused or expired invite link | Single use (410), 72-hour link lifetime (410) | `test_reused_token_is_410`, `test_forged_and_expired_tokens` |

### Added Nov 5 (server-to-server integration and IAM as code)

The integration is off unless `INTEGRATION_API_KEY` is set, and the MVP doesn't use it (D2: Newly not adopted). The rows stay because the code path still exists.

| # | Threat | Example | Control | Test |
| --- | --- | --- | --- | --- |
| S4 | Spoofing | Someone calls the API pretending to be a trusted server integration | 32+ character key from Secret Manager, constant-time compare, off unless configured | `test_integration_rejects_bad_key_and_missing_user` |
| E5 | Elevation | Leaked integration key used to act as the owner | Owner actions blocked on the integration channel by default | `test_integration_cannot_act_as_owner_by_default` |
| I4 | Info disclosure | Browser JavaScript sends the integration key | Key header excluded from CORS; key lives only on the integrating server | `test_cors_only_for_listed_origins` |
| R2 | Repudiation | "That action came from the web app, not the integration" | Every integration call is tagged with the integration's name (`via`) in the audit log | `test_integration_freelancer_flow_is_tagged` |
| E6 | Elevation | A teammate's cloud role is widened in a hurry (Editor "just to fix it") | IAM only in `iam.yaml`; CI lint blocks basic roles, impersonation roles, project-wide act-as, and IAM-admin + deployer on one person | `tests/iam/test_iam_policy.py` |
| E7 | Elevation | A workload account reads a secret it does not need | Secret-level grants only to `roleready-run`; proven with IAM enforcement on Floci | `tests/iam/test_floci_enforcement.py` |
| E8 | Elevation | Teammate access outlives the project | Every person's grant carries `request.time < 2026-12-01` | `test_time_boxed_grant_stops_working_after_it_expires` |
| T4 | Tampering | Two admins edit IAM at once and one overwrites the other | Read-modify-write with the policy etag; conflict fails | `test_concurrent_edit_fails_instead_of_overwriting` |
| I5 | Info disclosure | Emulator sign-in left on in production | App refuses to start on Cloud Run with `FIREBASE_AUTH_EMULATOR_HOST` set | `test_wildcard_cors_and_emulator_on_cloud_run_refused` |

### Added Nov 17 (sign-in, invite tokens, revoke and the expiry job; owner Andrew since Nov 10)

| # | Threat | Example | Control | Test |
| --- | --- | --- | --- | --- |
| S5 | Spoofing | Mallory creates a Firebase email/password account for sam@freelance.test (or the owner's email) before the real person does, using the public web API key | **Mitigated.** `app/auth.py` refuses Firebase tokens unless `email_verified` is true. Accounts are made already verified (`scripts/floci_seed.py` locally, `scripts/firebase_user.py` on the real project) before the invite link goes out; `firebase_user.py` refuses to bless an existing unverified account without `--replace` | `test_firebase_sign_in_with_unverified_email_is_refused`, `test_firebase_sign_in_with_verified_email_works` |
| S6 | Spoofing | Someone calls the demo-only expiry route in production | `/dev/run-expiry` exists only in demo mode; demo mode refuses to start on Cloud Run unless `ALLOW_DEMO_AUTH_ON_CLOUD_RUN=true` (hackathon fallback only) | `test_dev_expiry_route_only_in_demo` |
| S7 | Spoofing | Someone guesses an invite link | 256-bit random token (`secrets.token_urlsafe(32)`), looked up by SHA-256 hash; unknown tokens get 404 and an `invalid_token` audit row; after 5 failed tries in 15 minutes the signed-in user gets 429 with `Retry-After` (even for a good link), and one `too_many_attempts` audit row is written. The limit is per account, so it relies on S5: with Google sign-in off (the default), accounts are made by an admin, so nobody can rotate through fresh accounts to dodge it. With `FIREBASE_GOOGLE_SIGN_IN=true`, anyone with Google accounts can sign in (S8) and rotate through them, but that doesn't help: each guess is still one try at a 256-bit token | `test_forged_and_expired_tokens`, `test_five_failures_lock_out_that_user_only`, `test_lockout_is_audited_once` |
| D3 | Denial of service | A stranger tries Sam's link first to use it up | A refused accept (`wrong_user`) leaves the invitation approved, so Sam can still accept | `test_wrong_person_cannot_use_token` |
| E9 | Elevation | A freelancer approves an invitation (their own or a friend's) | Approve is owner-only; the link token is created only at approval, and a refused try leaves the draft unchanged | `test_freelancer_cannot_approve_or_revoke` |
| E10 | Elevation | A freelancer revokes someone's access, or a revoked grant comes back | Revoke is owner-only; grants move only from active to revoked or expired, and no route reverses that | `test_freelancer_cannot_approve_or_revoke`, `test_double_revoke_conflicts_and_logs_once` |
| E11 | Elevation | A revoked freelancer keeps working with a still-valid Firebase session (ID tokens last up to an hour) | Every request re-reads the grant, so revoke applies on the next request whatever the session | `test_revoke_takes_effect_on_next_request` |
| E12 | Elevation | An invite link outlives the access it grants | Link lifetime is the shorter of 72 hours and the grant's end; accept checks the link's expiry | `test_invite_link_ends_with_the_access_it_grants`, `test_forged_and_expired_tokens` |
| T5 | Tampering | Revoke and the expiry job race, leaving the grant active or with two end events | Conditional move out of active with a fixed event id; exactly one wins and a revoke stays a revoke | `test_racing_revoke_and_expire_threads`, `test_revoke_then_expire_keeps_revoked` |
| R3 | Repudiation | The expiry job runs twice (Scheduler retry), so metrics count one expiry twice | Job is idempotent; each grant gets exactly one `grant.expired` event (`<grant id>:expired`) | `test_ten_runs_write_one_expired_event_per_grant`, `test_fixed_event_id_is_written_once` |
| D4 | Denial of service | Cloud Scheduler is down, so the expiry job never runs | Not a security failure: access ends on the second from the clock check (E3); the job only tidies status | `test_access_ends_on_the_second_even_if_job_never_runs` |

### Added Nov 20 (Sign in with Google; owner Andrew)

| # | Threat | Example | Control | Test |
| --- | --- | --- | --- | --- |
| S8 | Spoofing | Someone with any Google account clicks "Sign in with Google" to get in, or to claim sam@freelance.test before Sam does | Same server check as every sign-in: Firebase verifies the ID token and `email_verified` must be `true` (no exception for Google). Google proves the person owns the address, so S5 still holds. Signing in grants nothing: access comes only from an owner-approved invitation for that email, so a stranger's Google account is denied by default. The button shows only when `FIREBASE_GOOGLE_SIGN_IN=true` and never on the emulator; Firebase only opens the popup from its Authorized domains list | `test_google_sign_in_with_verified_email_works`, `test_google_sign_in_gets_no_special_pass_on_verification`, `test_google_button_is_off_until_turned_on` |
| S9 | Spoofing | The owner's Google account is phished, so the attacker signs in as the owner | Same risk as a stolen password, but Google adds 2-Step Verification and suspicious-sign-in checks the app doesn't have. Owners should turn on 2-Step Verification. Every owner action is in the audit chain, and revoke still works | none (outside the app) |

## Open items

- [x] S5: Firebase ID tokens whose `email_verified` isn't true are refused (#21). Seeded and admin-created accounts are marked verified; freelancers get a password-setup link from `scripts/firebase_user.py`, not self sign-up
- [x] Rate-limit failed accept attempts: in-app, per signed-in user rather than per IP (accept requires sign-in, and a client can put any address in `X-Forwarded-For`). A stranger's failures count against the stranger, never against Sam, so D3 still holds. The count is in memory per Cloud Run instance (max 3), which is fine for defense in depth on 256-bit tokens. Settings: `ACCEPT_MAX_FAILURES` (5), `ACCEPT_LOCKOUT_MINUTES` (15).
- [ ] Decide audit retention (how long to keep events) and write it in the README.
- [x] Consent text for the 5 user-testing sessions: not needed. Outside people don't use the app hands-on (D8); survey respondents see only screenshots.
- [x] Incident steps if the NVIDIA key leaks: [docs/incident-nvidia-key.md](incident-nvidia-key.md) (revoke first, new secret version, new revision, disable the old version, check the Secret Manager read logs).
