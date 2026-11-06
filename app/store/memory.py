"""In-memory store for local development and tests. Data vanishes on restart.

Run a single process with this store. Two Cloud Run instances would each hold
their own copy, so production uses FirestoreStore.
"""

from __future__ import annotations

import threading
from typing import Any

from ..audit import GENESIS_HASH, seal
from ..models import AuditDraft, AuditEvent, Grant, GrantStatus, Invitation, InvitationStatus, new_id
from .base import Store


class MemoryStore(Store):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._invitations: dict[str, Invitation] = {}
        self._grants: dict[str, Grant] = {}
        self._events: dict[str, AuditEvent] = {}
        self._heads: dict[str, tuple[int, str]] = {}  # workspace_id -> (seq, hash)

    # Invitations -----------------------------------------------------------
    def save_invitation(self, invitation: Invitation) -> None:
        with self._lock:
            self._invitations[invitation.id] = invitation.model_copy(deep=True)

    def get_invitation(self, invitation_id: str) -> Invitation | None:
        with self._lock:
            inv = self._invitations.get(invitation_id)
            return inv.model_copy(deep=True) if inv else None

    def find_invitation_by_token_hash(self, token_hash: str) -> Invitation | None:
        with self._lock:
            for inv in self._invitations.values():
                if inv.token_hash and inv.token_hash == token_hash:
                    return inv.model_copy(deep=True)
            return None

    def list_invitations(self, workspace_id: str) -> list[Invitation]:
        with self._lock:
            items = [i.model_copy(deep=True) for i in self._invitations.values() if i.workspace_id == workspace_id]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    # Grants ----------------------------------------------------------------
    def get_grant(self, grant_id: str) -> Grant | None:
        with self._lock:
            g = self._grants.get(grant_id)
            return g.model_copy(deep=True) if g else None

    def list_grants(self, workspace_id: str) -> list[Grant]:
        with self._lock:
            items = [g.model_copy(deep=True) for g in self._grants.values() if g.workspace_id == workspace_id]
        return sorted(items, key=lambda g: g.start_at, reverse=True)

    def find_grants_for_user(self, workspace_id: str, user_email: str) -> list[Grant]:
        with self._lock:
            return [
                g.model_copy(deep=True)
                for g in self._grants.values()
                if g.workspace_id == workspace_id and g.user_email == user_email
            ]

    def list_active_grants(self) -> list[Grant]:
        with self._lock:
            return [g.model_copy(deep=True) for g in self._grants.values() if g.status == GrantStatus.ACTIVE]

    # Atomic operations -----------------------------------------------------
    def accept_invitation(self, invitation_id: str, grant: Grant, event: AuditDraft) -> bool:
        with self._lock:
            inv = self._invitations.get(invitation_id)
            if inv is None or inv.status != InvitationStatus.APPROVED:
                return False
            updated = inv.model_copy(
                deep=True,
                update={"status": InvitationStatus.ACCEPTED, "accepted_at": event.ts, "grant_id": grant.id},
            )
            self._invitations[invitation_id] = updated
            self._grants[grant.id] = grant.model_copy(deep=True)
            self._append_locked(event, None)
            return True

    def transition_grant(
        self,
        grant_id: str,
        from_status: GrantStatus,
        to_status: GrantStatus,
        updates: dict[str, Any],
        event: AuditDraft,
        event_id: str | None = None,
    ) -> bool:
        with self._lock:
            grant = self._grants.get(grant_id)
            if grant is None or grant.status != from_status:
                return False
            if event_id is not None and event_id in self._events:
                return False
            self._grants[grant_id] = grant.model_copy(deep=True, update={**updates, "status": to_status})
            self._append_locked(event, event_id)
            return True

    # Audit -----------------------------------------------------------------
    def append_audit(self, event: AuditDraft, event_id: str | None = None) -> AuditEvent | None:
        with self._lock:
            if event_id is not None and event_id in self._events:
                return None
            return self._append_locked(event, event_id)

    def _append_locked(self, draft: AuditDraft, event_id: str | None) -> AuditEvent:
        seq, prev_hash = self._heads.get(draft.workspace_id, (0, GENESIS_HASH))
        sealed = seal(draft, event_id=event_id or new_id(), seq=seq + 1, prev_hash=prev_hash)
        self._events[sealed.id] = sealed
        self._heads[draft.workspace_id] = (sealed.seq, sealed.hash)
        return sealed.model_copy(deep=True)

    def list_audit(self, workspace_id: str) -> list[AuditEvent]:
        with self._lock:
            items = [e.model_copy(deep=True) for e in self._events.values() if e.workspace_id == workspace_id]
        return sorted(items, key=lambda e: e.seq)

    # Test helper: lets tamper tests edit a stored row directly.
    def _unsafe_replace_event(self, event: AuditEvent) -> None:
        with self._lock:
            self._events[event.id] = event
