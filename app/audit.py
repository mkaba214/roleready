"""Tamper-evident audit log helpers.

Each event stores the hash of the event before it. Editing, deleting or
reordering any row breaks the chain, and verify_chain() names the first
broken event.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .models import AuditDraft, AuditEvent

GENESIS_HASH = "0" * 64


def _ts(value: datetime) -> str:
    # Microsecond precision survives a Firestore round trip, so the hash stays stable.
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def hash_payload(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "seq": event.seq,
        "ts": _ts(event.ts),
        "workspace_id": event.workspace_id,
        "actor": event.actor,
        "action": event.action,
        "target": event.target,
        "decision": event.decision.value if event.decision else None,
        "reason": event.reason,
        "details": event.details,
        "prev_hash": event.prev_hash,
    }


def compute_hash(event: AuditEvent) -> str:
    body = json.dumps(hash_payload(event), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def seal(draft: AuditDraft, *, event_id: str, seq: int, prev_hash: str) -> AuditEvent:
    """Turn a draft into a chained event."""
    event = AuditEvent(**draft.model_dump(), id=event_id, seq=seq, prev_hash=prev_hash)
    event.hash = compute_hash(event)
    return event


@dataclass(frozen=True)
class ChainCheck:
    ok: bool
    checked: int
    broken_at: str | None = None
    problem: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checked": self.checked, "broken_at": self.broken_at, "problem": self.problem}


def verify_chain(events: Iterable[AuditEvent]) -> ChainCheck:
    ordered = sorted(events, key=lambda e: e.seq)
    prev = GENESIS_HASH
    for index, event in enumerate(ordered, start=1):
        if event.seq != index:
            return ChainCheck(False, index - 1, event.id, f"sequence gap: expected {index}, found {event.seq}")
        if event.prev_hash != prev:
            return ChainCheck(False, index - 1, event.id, "prev_hash does not match the previous event")
        if compute_hash(event) != event.hash:
            return ChainCheck(False, index - 1, event.id, "event content changed after it was written")
        prev = event.hash
    return ChainCheck(True, len(ordered))
