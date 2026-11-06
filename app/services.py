"""Business logic: invitations, grants, actions, revoke and expiry.

The API layer handles HTTP. This layer enforces the rules again, so a bug in a
route can never skip a permission check.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import logging
import secrets
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from . import policy
from .audit import ChainCheck, verify_chain
from .clock import Clock
from .models import (
    AuditDraft,
    AuditEvent,
    Decision,
    Grant,
    GrantStatus,
    Invitation,
    InvitationRequest,
    InvitationStatus,
    Role,
    TaskType,
)
from .store import Store

log = logging.getLogger("roleready")


class ServiceError(Exception):
    status_code = 400


class PermissionDenied(ServiceError):
    status_code = 403


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409


class Gone(ServiceError):
    status_code = 410


class ValidationFailed(ServiceError):
    status_code = 422

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class ActionResult:
    allowed: bool
    reason: str
    task: str
    grant_id: str | None
    event_id: str | None


@dataclass
class ExpiryReport:
    checked: int = 0
    expired: list[str] = field(default_factory=list)
    already_handled: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "expired": self.expired, "already_handled": self.already_handled}


class RoleReadyService:
    def __init__(
        self,
        store: Store,
        clock: Clock,
        *,
        workspace_id: str,
        owner_email: str,
        invite_ttl: timedelta = timedelta(hours=72),
        default_timezone: str = "America/Chicago",
    ) -> None:
        self.store = store
        self.clock = clock
        self.workspace_id = workspace_id
        self.owner_email = owner_email.strip().lower()
        self.invite_ttl = invite_ttl
        self.default_timezone = default_timezone
        self.channel = "web"  # "web" or an integration name such as "newly"
        self.owner_allowed = True  # can callers on this channel act as the workspace owner?

    def for_channel(self, channel: str, *, owner_allowed: bool = True) -> "RoleReadyService":
        """Same service and store, but audit events record the client channel, and an
        integration channel can be barred from acting as the owner (least privilege)."""
        if channel == self.channel and owner_allowed == self.owner_allowed:
            return self
        clone = copy.copy(self)
        clone.channel = channel
        clone.owner_allowed = owner_allowed
        return clone

    def _with_channel(self, details: dict[str, Any] | None) -> dict[str, Any]:
        details = dict(details or {})
        if self.channel != "web":
            details["via"] = self.channel
        return details

    # Helpers ---------------------------------------------------------------
    def is_owner(self, email: str) -> bool:
        if not self.owner_allowed:
            return False
        return hmac.compare_digest(email.strip().lower(), self.owner_email)

    def require_owner(self, actor: str) -> None:
        if not self.is_owner(actor):
            reason = "not_owner" if self.owner_allowed else "owner_blocked_on_channel"
            self._audit(actor, "access.owner_only", target="", decision=Decision.DENY, reason=reason)
            raise PermissionDenied("only the workspace owner can do this")

    def _audit(
        self,
        actor: str,
        action: str,
        *,
        target: str = "",
        decision: Decision | None = None,
        reason: str = "",
        details: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> AuditEvent | None:
        draft = AuditDraft(
            workspace_id=self.workspace_id,
            ts=self.clock.now(),
            actor=actor,
            action=action,
            target=target,
            decision=decision,
            reason=reason,
            details=self._with_channel(details),
        )
        return self.store.append_audit(draft, event_id=event_id)

    def _draft(self, actor: str, action: str, **kw: Any) -> AuditDraft:
        kw["details"] = self._with_channel(kw.get("details"))
        return AuditDraft(workspace_id=self.workspace_id, ts=self.clock.now(), actor=actor, action=action, **kw)

    def record_assistant_use(self, actor: str, tool: str, *, ok: bool, details: dict[str, Any]) -> None:
        """Log every Access Assistant call, so the audit shows when the agent was used."""
        self._audit(actor, f"assistant.{tool}", reason="ok" if ok else "rejected", details=details)

    # Invitations -----------------------------------------------------------
    def create_invitation(self, actor: str, req: InvitationRequest, source: str = "manual") -> Invitation:
        self.require_owner(actor)
        now = self.clock.now()
        errors = policy.validate_invitation(req.role, req.task_types, req.start_at, req.expires_at, now)
        if self.is_owner(req.invitee_email):
            errors.append("the owner cannot invite themselves")
        if errors:
            raise ValidationFailed(errors)
        inv = Invitation(
            workspace_id=self.workspace_id,
            invitee_email=req.invitee_email,
            role=req.role,
            task_types=sorted(set(req.task_types)),
            start_at=req.start_at,
            expires_at=req.expires_at,
            timezone=req.timezone or self.default_timezone,
            reason=req.reason,
            source="assistant" if source == "assistant" else "manual",
            created_by=actor,
            created_at=now,
        )
        self.store.save_invitation(inv)
        self._audit(
            actor,
            "invitation.created",
            target=inv.id,
            details={
                "invitee": inv.invitee_email,
                "role": inv.role.value,
                "tasks": [t.value for t in inv.task_types],
                "start_at": inv.start_at.isoformat(),
                "expires_at": inv.expires_at.isoformat(),
                "timezone": inv.timezone,
                "source": inv.source,
            },
        )
        return inv

    def approve_invitation(self, actor: str, invitation_id: str) -> tuple[Invitation, str]:
        """Returns the invitation and the raw token. The raw token is shown once and never stored."""
        self.require_owner(actor)
        inv = self._get_invitation(invitation_id)
        if inv.status != InvitationStatus.DRAFT:
            raise Conflict(f"invitation is {inv.status.value}, not draft")
        now = self.clock.now()
        if inv.expires_at <= now:
            raise Conflict("the access window has already ended")
        token = secrets.token_urlsafe(32)
        inv.status = InvitationStatus.APPROVED
        inv.approved_by = actor
        inv.approved_at = now
        inv.token_hash = hash_token(token)
        inv.token_expires_at = min(now + self.invite_ttl, inv.expires_at)
        self.store.save_invitation(inv)
        self._audit(actor, "invitation.approved", target=inv.id, details={"invitee": inv.invitee_email})
        return inv, token

    def cancel_invitation(self, actor: str, invitation_id: str) -> Invitation:
        self.require_owner(actor)
        inv = self._get_invitation(invitation_id)
        if inv.status not in (InvitationStatus.DRAFT, InvitationStatus.APPROVED):
            raise Conflict(f"invitation is {inv.status.value}")
        inv.status = InvitationStatus.CANCELLED
        inv.cancelled_at = self.clock.now()
        self.store.save_invitation(inv)
        self._audit(actor, "invitation.cancelled", target=inv.id)
        return inv

    def accept_invitation(self, user_email: str, token: str) -> Grant:
        user_email = user_email.strip().lower()
        inv = self.store.find_invitation_by_token_hash(hash_token(token or ""))
        if inv is None:
            self._audit(user_email, "invitation.accept", decision=Decision.DENY, reason="invalid_token")
            raise NotFound("invitation not found")
        now = self.clock.now()
        if inv.status == InvitationStatus.ACCEPTED:
            self._audit(user_email, "invitation.accept", target=inv.id, decision=Decision.DENY, reason="token_reused")
            raise Gone("this invitation link was already used")
        if inv.status == InvitationStatus.CANCELLED:
            self._audit(user_email, "invitation.accept", target=inv.id, decision=Decision.DENY, reason="cancelled")
            raise Gone("this invitation was cancelled")
        if inv.status != InvitationStatus.APPROVED:
            raise Conflict("this invitation is not approved yet")
        if inv.token_expires_at is None or now >= inv.token_expires_at:
            self._audit(user_email, "invitation.accept", target=inv.id, decision=Decision.DENY, reason="token_expired")
            raise Gone("this invitation link has expired")
        if not hmac.compare_digest(user_email, inv.invitee_email):
            self._audit(user_email, "invitation.accept", target=inv.id, decision=Decision.DENY, reason="wrong_user")
            raise PermissionDenied("this invitation belongs to a different email address")

        grant = Grant(
            workspace_id=self.workspace_id,
            user_email=inv.invitee_email,
            role=inv.role,
            task_types=list(inv.task_types),
            start_at=inv.start_at,
            expires_at=inv.expires_at,
            timezone=inv.timezone,
            status=GrantStatus.ACTIVE,
            invitation_id=inv.id,
            created_at=now,
        )
        event = self._draft(
            user_email,
            "invitation.accepted",
            target=inv.id,
            decision=Decision.ALLOW,
            reason="ok",
            details={"grant_id": grant.id, "role": grant.role.value, "expires_at": grant.expires_at.isoformat()},
        )
        if not self.store.accept_invitation(inv.id, grant, event):
            raise Gone("this invitation link was already used")
        return grant

    def list_invitations(self, actor: str) -> list[Invitation]:
        self.require_owner(actor)
        return self.store.list_invitations(self.workspace_id)

    def _get_invitation(self, invitation_id: str) -> Invitation:
        inv = self.store.get_invitation(invitation_id)
        if inv is None or inv.workspace_id != self.workspace_id:
            raise NotFound("invitation not found")
        return inv

    # Grants ----------------------------------------------------------------
    def list_grants(self, actor: str) -> list[Grant]:
        self.require_owner(actor)
        return self.store.list_grants(self.workspace_id)

    def grants_for(self, user_email: str) -> list[Grant]:
        return self.store.find_grants_for_user(self.workspace_id, user_email.strip().lower())

    def revoke_grant(self, actor: str, grant_id: str) -> Grant:
        self.require_owner(actor)
        grant = self.store.get_grant(grant_id)
        if grant is None or grant.workspace_id != self.workspace_id:
            raise NotFound("grant not found")
        now = self.clock.now()
        event = self._draft(actor, "grant.revoked", target=grant_id, details={"user": grant.user_email})
        ok = self.store.transition_grant(
            grant_id,
            GrantStatus.ACTIVE,
            GrantStatus.REVOKED,
            {"revoked_at": now, "revoked_by": actor},
            event,
            event_id=f"{grant_id}:revoked",
        )
        if not ok:
            current = self.store.get_grant(grant_id)
            state = current.status.value if current else "missing"
            raise Conflict(f"grant is already {state}")
        return self.store.get_grant(grant_id)  # type: ignore[return-value]

    # Actions ---------------------------------------------------------------
    def perform_action(self, user_email: str, task: str) -> ActionResult:
        """Decide one request and log the decision, allowed or denied."""
        user_email = user_email.strip().lower()
        now = self.clock.now()
        if self.is_owner(user_email):
            decision = policy.evaluate(
                Grant(role=Role.OWNER, start_at=now - timedelta(seconds=1), expires_at=now + timedelta(days=1)),
                task,
                now,
            )
            grant_id = None
        else:
            grants = self.grants_for(user_email)
            decisions = [(g, policy.evaluate(g, task, now)) for g in grants]
            allowed = [(g, d) for g, d in decisions if d.allowed]
            if allowed:
                grant_id, decision = allowed[0][0].id, allowed[0][1]
            elif decisions:
                # Report the reason from the most recent grant.
                g, decision = max(decisions, key=lambda gd: gd[0].start_at)
                grant_id = g.id
            else:
                grant_id, decision = None, policy.evaluate(None, task, now)

        event = self._audit(
            user_email,
            f"action.{task}" if task in {t.value for t in TaskType} else "action.unknown",
            target=grant_id or "",
            decision=Decision.ALLOW if decision.allowed else Decision.DENY,
            reason=decision.reason,
            details={"task": task},
        )
        return ActionResult(decision.allowed, decision.reason, task, grant_id, event.id if event else None)

    # Expiry job ------------------------------------------------------------
    def expire_due_grants(self) -> ExpiryReport:
        """Safe to run any number of times. Each grant gets exactly one expired event."""
        now = self.clock.now()
        report = ExpiryReport()
        for grant in self.store.list_active_grants():
            if grant.workspace_id != self.workspace_id:
                continue
            report.checked += 1
            if grant.expires_at > now:
                continue
            event = self._draft(
                "system:expiry-job",
                "grant.expired",
                target=grant.id,
                details={"user": grant.user_email, "expires_at": grant.expires_at.isoformat()},
            )
            ok = self.store.transition_grant(
                grant.id,
                GrantStatus.ACTIVE,
                GrantStatus.EXPIRED,
                {"expired_at": now},
                event,
                event_id=f"{grant.id}:expired",
            )
            if ok:
                report.expired.append(grant.id)
            else:
                report.already_handled += 1
        log.info("expiry run: %s", report.as_dict())
        return report

    # Audit -----------------------------------------------------------------
    def audit_events(self, actor: str) -> list[AuditEvent]:
        self.require_owner(actor)
        return self.store.list_audit(self.workspace_id)

    def verify_audit(self, actor: str) -> ChainCheck:
        self.require_owner(actor)
        return verify_chain(self.store.list_audit(self.workspace_id))

    # Focused analytics -------------------------------------------------------
    def success_metrics(self, actor: str) -> dict[str, Any]:
        """The brief's success measures, computed live from operational records.

        This is the in-app dashboard. The BigQuery + Looker Studio export
        (scripts/export_bigquery.py) gives the same numbers from a batch snapshot.
        """
        self.require_owner(actor)
        now = self.clock.now()
        events = self.store.list_audit(self.workspace_id)
        grants = {g.id: g for g in self.store.list_grants(self.workspace_id)}
        invitations = self.store.list_invitations(self.workspace_id)

        # Expiry is a clock rule (ts >= expires_at). Revoke is an ordering rule: any allow
        # written after the revoke event in the hash chain is a violation.
        revoked_seq = {e.target: e.seq for e in events if e.action == "grant.revoked"}

        def after_end_of_access(e: AuditEvent) -> bool:
            g = grants.get(e.target)
            if g is None:
                return False
            return e.ts >= g.expires_at or (e.target in revoked_seq and e.seq > revoked_seq[e.target])

        actions = [e for e in events if e.action.startswith("action.")]
        allowed = [e for e in actions if e.decision == Decision.ALLOW]
        denied = [e for e in actions if e.decision == Decision.DENY]
        after_end = [e for e in allowed if after_end_of_access(e)]
        expired_per_grant = Counter(e.target for e in events if e.action == "grant.expired")
        duplicates = sum(1 for n in expired_per_grant.values() if n > 1)
        unapproved = [
            i for i in invitations
            if i.status == InvitationStatus.ACCEPTED and (not i.approved_by or not self.is_owner(i.approved_by))
        ]
        drafts = [e for e in events if e.action == "assistant.draft_invitation"]
        drafts_ok = sum(1 for e in drafts if e.reason == "ok")
        chain = verify_chain(events)
        states = Counter(policy.effective_state(g, now) for g in grants.values())

        measures = [
            {"measure": "Protected actions allowed after access ended", "target": "0",
             "actual": str(len(after_end)), "met": len(after_end) == 0},
            {"measure": "Allowed and denied actions logged", "target": "100%, chain intact",
             "actual": f"{len(allowed)} allowed, {len(denied)} denied, chain {'intact' if chain.ok else 'BROKEN'}",
             "met": chain.ok},
            {"measure": "Duplicate expiration events", "target": "0",
             "actual": str(duplicates), "met": duplicates == 0},
            {"measure": "Grants made without owner approval", "target": "0",
             "actual": str(len(unapproved)), "met": not unapproved},
            {"measure": "Assistant drafts passing policy checks", "target": "27 of 30 on the eval set",
             "actual": f"{drafts_ok} of {len(drafts)} live drafts (eval set: python -m evals.run_eval)", "met": None},
            {"measure": "First-time invite under 2 minutes", "target": "5 testers",
             "actual": "measured in user sessions (docs/feedback-log.md)", "met": None},
        ]
        return {
            "as_of": now.isoformat(),
            "measures": measures,
            "counts": {
                "invitations": len(invitations),
                "invitations_from_assistant": sum(1 for i in invitations if i.source == "assistant"),
                "grants_by_state": dict(states),
                "decisions_by_reason": dict(Counter(e.reason for e in actions)),
                "audit_events": len(events),
            },
        }
