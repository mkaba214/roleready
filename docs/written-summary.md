# RoleReady: Written Summary

**Team:** Mohamed Kaba (team lead), Andrew Hernandez, Joclyn Davis · **SDG 9:** Industry, Innovation and Infrastructure

**Links:** [Live app](https://roleready-340875597178.us-central1.run.app) · [Repo](https://github.com/mkaba214/roleready) · [Deck](https://docs.google.com/presentation/d/1aTvrEI9q--rpzbtyc7soXvABASi0OtrS2Ib_diI0BXg/edit?usp=sharing) · [Video](https://docs.google.com/videos/d/10sclNvXOZUiKbHtelFMTCv8KvYpHXO-EXhyPRNLGIIg/play?usp=sharing) · [Dashboard](https://datastudio.google.com/reporting/6d62f470-2ef5-423b-9047-6fb74e6b0a22)

## 1. Problem and objectives

Small business owners give short-term freelancers access to their accounts with no simple way to limit what the freelancer can touch or to end that access on time. Access outlives the job.

Our persona is Dana, who owns Bloom & Crumb, a six-person bakery brand. She hires a freelance social media manager for launch week. Today she shares one login, and last month's contractor still has the password.

RoleReady supports SDG 9, Targets 9.1 (reliable infrastructure with equitable access) and 9.3 (small enterprises' integration into value chains). Time-limited, least-privilege access with an audit trail is standard at large companies. RoleReady gives the same protection to a business with no IT team.

**Objectives.** We set six measurable targets before building. Section 6 reports the result for each.

- 0 actions allowed after access expires or is revoked
- 100% of access decisions, allowed and denied, written to the audit log
- 0 duplicate expiry events when the expiry job runs repeatedly
- 0 agent actions taken without the owner's approval
- 27 of 30 (90%) agent drafts with the correct role, tasks and dates
- Under 2 minutes for an owner to invite a freelancer

## 2. Research and evidence

Published data shows the problem is common: 64 million Americans freelanced in 2023, about 38% of the U.S. workforce ([Upwork, Dec 2023](https://investors.upwork.com/news-releases/news-release-details/upwork-study-finds-64-million-americans-freelanced-2023-adding)); third-party involvement in breaches doubled to 30% ([Verizon 2025 DBIR](https://verizon.com/about/news/2025-data-breach-investigations-report)); and 83% of surveyed former employees said they still had access to a past employer's accounts ([Beyond Identity, Feb 2022](https://www.beyondidentity.com/resource/former-employees-admit-to-using-continued-account-access-to-harm-previous-employers); n = 1,121, self-reported).

**Our survey.** We shared an access-management survey on Nov 10 through LinkedIn and program Slack. It closed on Nov 23 with 6 non-team-member responses. Two of six said access sometimes stays active after a project ends, and three reported difficulties getting or managing access. One shares usernames and passwords.

**What is still an assumption.** Six responses are early signals. Most respondents were freelancers, with none answering as only a business owner, RoleReady's target. We have not yet measured how often owners forget to remove access.

## 3. Solution

RoleReady lets an owner give a freelancer only the tasks the job needs, for a fixed window, and proves the access ended on time.

The owner creates an invitation with a role, task types, and start and end times, or asks the Access Assistant to draft one in plain English. Nothing is granted until the owner approves. The freelancer accepts with a single-use link and can do only what their role (contributor or viewer) and the five task types allow. Access ends automatically at the end time, or right away if the owner revokes it, and every decision goes into a tamper-evident audit log.

**The Access Assistant** is our NVIDIA-powered agent. It drafts invitations, explains the audit log and flags drafts wider than the job needs. The agent proposes, the owner decides, and the policy engine enforces.

**Out of scope:** real social media connections, payments, single sign-on, live email delivery and more than one workspace.

## 4. Implementation

RoleReady is built on Google Cloud and uses the NVIDIA API for its agent. A FastAPI app on Cloud Run stores invitations, grants and the hash-chained audit log in Firestore, whose security rules block all direct browser access. Firebase Authentication handles sign-in and accepts only verified emails. Cloud Scheduler runs the expiry job every minute with a signed identity, and Secret Manager holds the NVIDIA key; only the app's service account has a read grant, no teammate does, and every read is logged. The Access Assistant calls NVIDIA's Nemotron 3.5 Lightning model. A script loads the audit log into BigQuery on demand for the Data Studio (formerly Looker Studio) dashboard; each run replaces the tables. We built and tested locally on Floci then deployed on Nov 20. The live app has cost $0.02 so far, covered by program credits.

## 5. Timeline and team

We built RoleReady in under four weeks: kickoff Nov 3, product brief Nov 4, first prototype at the Nov 6 hackathon, deploy to Google Cloud Nov 20, feature freeze Nov 21, video Nov 24 and submission Nov 27. Two changes shaped the plan: a teammate left on Nov 10, and on Nov 15 we replaced hands-on outside testing with the survey and internal timing tests.

**Team.** Mohamed Kaba (Cloud Engineering) led the team, set up the Google Cloud project, deployed the app and hardened CI. Andrew Hernandez (Cloud Cybersecurity) built the permission rules, the Access Assistant and our IAM as code, and after Nov 10 also took on sign-in, invite links, revoke, the expiry job and the threat model. Joclyn Davis (Cloud Data Analytics) led product research and success metrics, ran the survey and feedback log, designed the agent evaluations, and built the BigQuery validation and Data Studio dashboard.

## 6. Testing and outcomes

RoleReady met every security target in our test runs.

**Security and testing.** Anything not explicitly allowed for a role is denied. Sign-in refuses unverified email addresses (#22), and after five failed invite-link attempts in 15 minutes, further accepts are refused until the window passes (#26). We applied least privilege to ourselves too: our Google Cloud access is written as code, every teammate's access ends Dec 1, and a teammate who tries to read the NVIDIA key gets PERMISSION\_DENIED. 275 tests pass, and CI is green on every recent merge.

| Measure | Target | Result |
| --- | --- | --- |
| Actions after access ended | 0 | 0 (sample and live) |
| Decisions written to the audit log | 100% | 187 of 187 (sample); 20 of 20 on the live app; audit chain verified |
| Duplicate expiry events | 0 | 0 (sample: 4 expired, 4 events; live: 1 expired, 1 event) |
| Agent actions without owner approval | 0 | 0 |
| Agent drafts correct | 27 of 30 | 28 of 30 on every run since the Nov 10 prompt fixes (4 runs, Nov 10–19) |
| Time to invite a freelancer | Under 2 min | 45 s and 1 min 42 s (two internal runs on the local app, Nov 23) |

In a scripted sample run of the full journey on the local app, 61 of 187 access attempts were allowed because the person had valid access, and 126 were blocked. As an independent check, we rebuilt every grant from the invitation records in BigQuery and rechecked all 187 decisions. We found 0 disagreements. Live checks on Nov 23 confirmed it: the expiry job logged the expired grant 2.8 seconds after its end time, a revoked grant was blocked on the next click, and nothing got through across 4 ended grants (1 expired, 3 revoked). The audit chain verified intact across 67 events, and the same recheck agreed with all 20 live decisions.

**Usability.** Survey respondents rated three tasks from app screenshots on a 1–5 ease scale: inviting a freelancer 3.5, seeing what they did 3.2, and removing access 3.5. They rated usefulness for a small business 4.2, and 5 of 6 rated it 4 or 5.

**Agent findings.** Model and prompt fixes raised draft accuracy from 21 of 30 to 28 of 30. Regression tests we wrote for a time zone bug in our own code (#13) caught a crash (#19) when the model answered with a zone name like "Pacific"; it was fixed in #20, and both cases now pass. Casual zone names like "LA time" and the model's weekday errors remain limitations. Because the owner must approve every draft, review gives a chance to catch them before any access is granted.

## 7. Risks

Naming a backup for each area covered the team member loss. Thin user evidence was the biggest risk: the survey helped, but business owners are still underrepresented. Agent date errors and prompt injection were contained by design: the agent has no grant tool, every draft passes schema checks, and the owner approves every invitation, so agent errors can't become access on their own. To control cost, we ran locally until the final deploy and set a $10 budget alert.

## 8. Next steps

- Fix the agent's weekday handling and casual time zone names like "LA time"
- Hands-on testing with real business owners, since the survey reached mostly freelancers
- Clearer activity history: filter by person and date, with plain labels (survey feedback; issue #41)
- Let owners change or extend an active grant (not built yet)

RoleReady shows that time-limited, least-privilege access, human-supervised AI and a verifiable audit trail can be delivered in a lightweight cloud app built for small businesses.
