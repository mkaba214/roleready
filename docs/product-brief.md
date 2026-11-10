# RoleReady - Product Brief

*GCLP BUILD Phase | UN SDG 9: Industry, Innovation and Infrastructure*

**Status:** Working draft for team review - UPDATED November 9, 2026. Scope, assignments, and targets remain subject to team agreement unless identified as confirmed.

## 1. Audience and User Persona

RoleReady is designed for small business owners who work with freelancers or temporary collaborators but may lack dedicated IT staff to manage digital access.

Our proposed user persona is Dana, the owner of Bloom & Crumb, a six-person bakery business. Dana hires temporary collaborators to help with tasks such as creating promotional content, editing drafts, and scheduling social media posts.

Dana needs a straightforward way to provide appropriate access without giving collaborators unnecessary permissions or leaving access active after their work ends.

*The persona and workflow are preliminary assumptions to be validated through user research.*

## 2. Problem Statement

Small businesses may depend on freelancers and temporary collaborators to perform specialized tasks. However, managing temporary access can introduce security and administrative challenges.

Business owners need to determine which permissions collaborators require, how long those permissions should remain active, and when access should end.

Without a consistent access management process, collaborators may retain unnecessary permissions after completing their assignments. Owners may also lack a convenient way to review access activity or identify permissions that require attention.

**RoleReady is intended to help owners limit collaborator permissions, approve temporary access, and verify when access has ended.**

### Background Research and Evidence

Existing research suggests that managing access for temporary workers and external collaborators is a relevant security concern.

Upwork reported that approximately 64 million Americans performed freelance work in 2023, illustrating the scale of independent work in the United States. Verizon's 2025 Data Breach Investigations Report found third-party involvement in 30% of breaches, demonstrating the broader security risks associated with external relationships.

A 2022 Beyond Identity survey also reported that 83% of surveyed former employees retained access to digital assets belonging to previous employers, highlighting concerns about access persisting after working relationships end.

These findings provide broader context but do not establish how frequently small-business owners encounter the specific problems RoleReady addresses. The team plans to investigate those needs through interviews and usability testing.

**Sources:** [Upwork (2023)](https://www.upwork.com/research/freelance-forward-2023-research-report) · [Verizon DBIR (2025)](https://www.verizon.com/about/news/2025-data-breach-investigations-report) · [Beyond Identity (2022)](https://www.beyondidentity.com/resource/former-employees-admit-to-using-continued-account-access-to-harm-previous-employers)

## 3. Friction-to-Feature Map

The following map connects proposed user difficulties to RoleReady's planned features and the evidence we will collect. These difficulties remain assumptions to be validated through user research.

| Proposed user difficulty | Proposed response | Evidence to collect |
| :---- | :---- | :---- |
| Owner forgets to end temporary access | Explicit expiration and manual revocation | Interview examples; expiration and revocation tests |
| Collaborator receives excessive permissions | Limited roles and permission recommendations | Which tasks collaborators actually need |
| Owner cannot understand past activity | Audit history and agent explanations | Whether users can identify who did what |
| Preparing access takes too much effort | Plain-language invitation drafting | Completion time, errors, and user feedback |

## 4. Proposed Solution

RoleReady is an AI-assisted access management product intended to help small business owners bring temporary collaborators into their work with appropriate permissions, clear access periods, and a record of access decisions.

The proposed BUILD version will deliver a functioning prototype in one simulated business workspace. An NVIDIA-powered Access Assistant will prepare invitation drafts, flag permissions that may exceed the collaborator's needs, and explain relevant audit records. The owner reviews and approves invitations; the application independently checks permissions and denies protected actions before access begins, after expiration, or after revocation.

This first version will demonstrate the complete access lifecycle within RoleReady. Possible future development could include connections to external business applications, single sign-on, customizable permissions, and more advanced reporting. These possibilities are outside the proposed BUILD commitment.

## 5. Core User Experience

The business owner prepares an invitation, optionally using natural language through the AI assistant. The invitation identifies the collaborator, their role, permitted tasks, and the access start and expiration times, including the time zone.

The owner reviews and approves the invitation. Then a copyable invitation link is shared with the collaborator.

The collaborator accepts the invitation. The collaborator can perform authorized tasks within the simulated workspace. For example, the social media collaborator can edit a social media draft, but they cannot manage user permissions.

The application checks each attempted action against the collaborator's permissions and access period. It records both allowed and denied actions in the audit history.

The owner can review access activity, revoke access early, or allow it to expire automatically. Once access expires or is revoked, the application denies further actions.

## 6. Minimum Viable Product (MVP)

The proposed MVP includes

- a single simulated business workspace,
- three user roles (Owner, Contributor, and Viewer),
- five defined task types

| Task type | Owner | Contributor (freelancer) | Viewer (client reviewer) |
| :---- | :---- | :---- | :---- |
| view_assets | Allow | Allow | Allow |
| edit_drafts | Allow | Allow | Deny |
| schedule_posts | Allow | Allow | Deny |
| view_analytics | Allow | Deny | Allow |
| manage_access | Allow | Deny | Deny |

The MVP will also include

- temporary access invitations,
- approval and revocation controls,
- automatic expiration,
- an audit history

It will utilize an NVIDIA-powered Access Assistant and a focused analytics dashboard.

Real third-party account integrations, SSO, payments, multiple business workspaces, and live email delivery are outside the proposed MVP scope.

## 7. Technology and Data

The BUILD project requires Google Cloud and an NVIDIA-powered agent.

**Google Cloud:** Google Cloud will support the backend, operational data storage, and analytics. The team will select specific services based on the application's needs and available resources.

**NVIDIA:** An NVIDIA-powered Access Assistant will draft invitations, recommend appropriately limited permissions, and explain audit records. The owner approves access, and the application enforces permissions independently of the assistant.

**Data flow:** Operational records will capture invitations, access grants, and audit events. The proposed analytics approach is to transfer these records in batches to BigQuery and use Looker Studio for reporting. The application will use operational records to determine current access; analytics reports may reflect a delayed snapshot.

## 8. Proposed Success Measures

The team will evaluate RoleReady against the following targets:

| Success measure | Proposed acceptance target |
| :---- | :---- |
| Expiration and revocation | Zero successful protected actions after access ends |
| Audit completeness | 100% of tested allowed and denied actions logged |
| Expiration reliability | Zero duplicate expiration events after 10 repeated job runs |
| Agent safety | Zero grants made without owner approval |
| Agent accuracy | At least 27 of 30 invitation drafts correct |
| Usability | Five first-time testers, targeting under two minutes per invitation |

These targets are proposed in the build plan and will be tested during development.

## 9. SDG 9 Connection

RoleReady supports the goals of resilient infrastructure and small-enterprise participation in digital markets by demonstrating access management practices suitable for businesses without dedicated IT teams.

**Target 9.1:** least-privilege, time-limited access with an audit trail is standard practice at large IT organizations. RoleReady makes these security practices affordable for a business with no IT staff.

**Target 9.3:** safer short-term access lowers the risk of hiring freelancers, which helps small businesses work with outside talent and take part in wider markets.

**Limit:** RoleReady is a prototype; its real-world impact will be tested through user interviews.

## 10. Open Decisions and Risks

The NVIDIA agent's specific function and how it connects to the backend still need to be determined.

Major risks include limited development time, integration complexity, unreliable agent responses, and insufficient evidence about actual small-business needs. The team will prioritize a working end-to-end demonstration, validate assumptions through user testing, and document limitations.

## 11. Project Timeline and Responsibilities

The four-person team will develop and test RoleReady during the October 31-November 28 BUILD period.

**Andrew's BUILD plan proposes the following leads, subject to team confirmation.**

- Mohamed leads cloud engineering and integration
- Andrew leads permission rules and the AI agent
- Ashley leads authentication and access lifecycle security
- Andrew and Ashley handle access approval
- Joclyn leads research, success metrics, analytics, agent evaluation, and written documentation

**Proposed milestones:**

- **November 4:** Brief drafted (updated Nov 9).
- **November 6:** Newly Vibecoding Hackathon Prototyping Session.
- **November 9-12:** User interviews.
- **November 13:** Initial user testing and prioritized improvements.
- **November 20:** Integrated prototype, analytics, and testing evidence.
- **November 21:** Feature freeze.
- **November 27:** Planned submission, ahead of the November 28 deadline stated in the plan.
- **November 28 11:59 PM ET deadline.**

The final submission will include a functioning prototype, code repository, testing evidence, documentation, presentation, and demonstration video.

## 12. Decisions Requested from the Team

This brief is intended to establish a shared understanding of RoleReady's proposed scope and implementation. The team is asked to review and confirm:

- **MVP scope:** Are the proposed roles, permissions, task types, and core user journey appropriate for the BUILD deadline?
- **NVIDIA integration:** What specific function will the NVIDIA agent perform?
- **Architecture:** Which Google Cloud services are necessary, and what will the initial deployment approach be?
- **Analytics:** Is batch-based export to BigQuery and Looker Studio appropriate for the MVP?
- **Responsibilities and milestones:** Are the proposed assignments and delivery dates achievable?

Decisions and any changes to scope will be reflected in the updated project plan.

## Sources

[UN Goal 9](https://sdgs.un.org/goals/goal9)

[Andrew's BUILD plan](https://docs.google.com/document/d/1tRtnf4P3P_FI_a-orNwMCthp9WhFsLl5FF_06xmrPCo/edit?tab=t.0#heading=h.p1dz6lgxfvz3)
