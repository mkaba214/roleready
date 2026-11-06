"""Firestore store for Google Cloud.

Collections: invitations, grants, audit_events, audit_heads.
Every multi-document change runs in a Firestore transaction, so a grant can
never flip status without its audit event, and a repeated expiry run writes
nothing new.

Queries use single-field filters only, so no composite indexes are needed.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from ..audit import GENESIS_HASH, seal
from ..models import AuditDraft, AuditEvent, Grant, GrantStatus, Invitation, InvitationStatus
from .base import Store


def _plain(value: Any) -> Any:
    """Convert enums to their string values so Firestore stores plain data."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class FirestoreStore(Store):
    def __init__(self, client: firestore.Client | None = None, collection_prefix: str = "") -> None:
        self._db = client or firestore.Client()
        p = collection_prefix
        self._inv = self._db.collection(f"{p}invitations")
        self._grants = self._db.collection(f"{p}grants")
        self._events = self._db.collection(f"{p}audit_events")
        self._heads = self._db.collection(f"{p}audit_heads")

    @staticmethod
    def _doc(model: Invitation | Grant | AuditEvent) -> dict[str, Any]:
        return _plain(model.model_dump())

    # Invitations -----------------------------------------------------------
    def save_invitation(self, invitation: Invitation) -> None:
        self._inv.document(invitation.id).set(self._doc(invitation))

    def get_invitation(self, invitation_id: str) -> Invitation | None:
        snap = self._inv.document(invitation_id).get()
        return Invitation.model_validate(snap.to_dict()) if snap.exists else None

    def find_invitation_by_token_hash(self, token_hash: str) -> Invitation | None:
        query = self._inv.where(filter=FieldFilter("token_hash", "==", token_hash)).limit(1)
        for snap in query.stream():
            return Invitation.model_validate(snap.to_dict())
        return None

    def list_invitations(self, workspace_id: str) -> list[Invitation]:
        query = self._inv.where(filter=FieldFilter("workspace_id", "==", workspace_id))
        items = [Invitation.model_validate(s.to_dict()) for s in query.stream()]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    # Grants ----------------------------------------------------------------
    def get_grant(self, grant_id: str) -> Grant | None:
        snap = self._grants.document(grant_id).get()
        return Grant.model_validate(snap.to_dict()) if snap.exists else None

    def list_grants(self, workspace_id: str) -> list[Grant]:
        query = self._grants.where(filter=FieldFilter("workspace_id", "==", workspace_id))
        items = [Grant.model_validate(s.to_dict()) for s in query.stream()]
        return sorted(items, key=lambda g: g.start_at, reverse=True)

    def find_grants_for_user(self, workspace_id: str, user_email: str) -> list[Grant]:
        query = self._grants.where(filter=FieldFilter("workspace_id", "==", workspace_id)).where(
            filter=FieldFilter("user_email", "==", user_email)
        )
        return [Grant.model_validate(s.to_dict()) for s in query.stream()]

    def list_active_grants(self) -> list[Grant]:
        query = self._grants.where(filter=FieldFilter("status", "==", GrantStatus.ACTIVE.value))
        return [Grant.model_validate(s.to_dict()) for s in query.stream()]

    # Audit chain helpers (reads first, writes second, as transactions require)
    def _prepare_audit(self, txn: firestore.Transaction, draft: AuditDraft, event_id: str | None):
        head_ref = self._heads.document(draft.workspace_id)
        if event_id is not None:
            ev_ref = self._events.document(event_id)
            if ev_ref.get(transaction=txn).exists:
                return None
        else:
            ev_ref = self._events.document()  # auto id
        head = head_ref.get(transaction=txn)
        if head.exists:
            data = head.to_dict()
            seq, prev_hash = int(data["seq"]), str(data["hash"])
        else:
            seq, prev_hash = 0, GENESIS_HASH
        sealed = seal(draft, event_id=ev_ref.id, seq=seq + 1, prev_hash=prev_hash)
        return ev_ref, sealed, head_ref

    def _write_audit(self, txn: firestore.Transaction, ev_ref, sealed: AuditEvent, head_ref) -> None:
        txn.create(ev_ref, self._doc(sealed))
        txn.set(head_ref, {"seq": sealed.seq, "hash": sealed.hash, "updated_at": sealed.ts})

    # Atomic operations -----------------------------------------------------
    def accept_invitation(self, invitation_id: str, grant: Grant, event: AuditDraft) -> bool:
        inv_ref = self._inv.document(invitation_id)
        grant_ref = self._grants.document(grant.id)

        @firestore.transactional
        def run(txn: firestore.Transaction) -> bool:
            snap = inv_ref.get(transaction=txn)
            if not snap.exists or snap.to_dict().get("status") != InvitationStatus.APPROVED.value:
                return False
            prepared = self._prepare_audit(txn, event, None)
            assert prepared is not None
            txn.update(
                inv_ref,
                {"status": InvitationStatus.ACCEPTED.value, "accepted_at": event.ts, "grant_id": grant.id},
            )
            txn.create(grant_ref, self._doc(grant))
            self._write_audit(txn, *prepared)
            return True

        return run(self._db.transaction())

    def transition_grant(
        self,
        grant_id: str,
        from_status: GrantStatus,
        to_status: GrantStatus,
        updates: dict[str, Any],
        event: AuditDraft,
        event_id: str | None = None,
    ) -> bool:
        grant_ref = self._grants.document(grant_id)

        @firestore.transactional
        def run(txn: firestore.Transaction) -> bool:
            snap = grant_ref.get(transaction=txn)
            if not snap.exists or snap.to_dict().get("status") != from_status.value:
                return False
            prepared = self._prepare_audit(txn, event, event_id)
            if prepared is None:
                return False
            txn.update(grant_ref, {**_plain(updates), "status": to_status.value})
            self._write_audit(txn, *prepared)
            return True

        return run(self._db.transaction())

    # Audit -----------------------------------------------------------------
    def append_audit(self, event: AuditDraft, event_id: str | None = None) -> AuditEvent | None:
        @firestore.transactional
        def run(txn: firestore.Transaction) -> AuditEvent | None:
            prepared = self._prepare_audit(txn, event, event_id)
            if prepared is None:
                return None
            self._write_audit(txn, *prepared)
            return prepared[1]

        return run(self._db.transaction())

    def list_audit(self, workspace_id: str) -> list[AuditEvent]:
        query = self._events.where(filter=FieldFilter("workspace_id", "==", workspace_id))
        items = [AuditEvent.model_validate(s.to_dict()) for s in query.stream()]
        return sorted(items, key=lambda e: e.seq)
