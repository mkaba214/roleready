"""Storage interface. MemoryStore runs locally and in tests; FirestoreStore runs on Google Cloud."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import AuditDraft, AuditEvent, Grant, GrantStatus, Invitation


class Store(ABC):
    # Invitations -----------------------------------------------------------
    @abstractmethod
    def save_invitation(self, invitation: Invitation) -> None: ...

    @abstractmethod
    def get_invitation(self, invitation_id: str) -> Invitation | None: ...

    @abstractmethod
    def find_invitation_by_token_hash(self, token_hash: str) -> Invitation | None: ...

    @abstractmethod
    def list_invitations(self, workspace_id: str) -> list[Invitation]: ...

    # Grants ----------------------------------------------------------------
    @abstractmethod
    def get_grant(self, grant_id: str) -> Grant | None: ...

    @abstractmethod
    def list_grants(self, workspace_id: str) -> list[Grant]: ...

    @abstractmethod
    def find_grants_for_user(self, workspace_id: str, user_email: str) -> list[Grant]: ...

    @abstractmethod
    def list_active_grants(self) -> list[Grant]: ...

    # Atomic operations -----------------------------------------------------
    @abstractmethod
    def accept_invitation(self, invitation_id: str, grant: Grant, event: AuditDraft) -> bool:
        """In one transaction: flip the invitation approved -> accepted, create the
        grant and append the audit event. Returns False if the invitation was no
        longer approved (for example, a second acceptance raced the first)."""

    @abstractmethod
    def transition_grant(
        self,
        grant_id: str,
        from_status: GrantStatus,
        to_status: GrantStatus,
        updates: dict[str, Any],
        event: AuditDraft,
        event_id: str | None = None,
    ) -> bool:
        """In one transaction: move a grant between statuses and append the audit
        event. Returns False (and writes nothing) when the grant is not in
        from_status or when event_id already exists. This makes repeated expiry
        jobs and revoke/expire races safe."""

    # Audit -----------------------------------------------------------------
    @abstractmethod
    def append_audit(self, event: AuditDraft, event_id: str | None = None) -> AuditEvent | None:
        """Append to the workspace's hash chain. With a fixed event_id, a second
        call with the same id writes nothing and returns None."""

    @abstractmethod
    def list_audit(self, workspace_id: str) -> list[AuditEvent]:
        """All events for a workspace, ordered by sequence number."""
