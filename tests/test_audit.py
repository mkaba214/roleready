"""The audit log tells the true story: tampering is detectable."""

from __future__ import annotations

from app.audit import compute_hash, verify_chain
from tests.conftest import OWNER, SAM, grant_access

WS = "bloom-and-crumb"


def build_history(svc, clock):
    grant_access(svc)
    clock.advance(hours=2)
    svc.perform_action(SAM, "edit_drafts")
    svc.perform_action(SAM, "view_analytics")
    return svc.store.list_audit(WS)


def test_chain_verifies(svc, clock) -> None:
    events = build_history(svc, clock)
    check = verify_chain(events)
    assert check.ok and check.checked == len(events) >= 5
    assert events[0].prev_hash == "0" * 64
    assert all(b.prev_hash == a.hash for a, b in zip(events, events[1:]))


def test_edited_row_breaks_chain_at_that_event(svc, clock, store) -> None:
    """Someone tries to hide a denied attempt by flipping it to allowed."""
    from app.models import Decision

    events = build_history(svc, clock)
    target = next(e for e in events if e.decision == Decision.DENY)
    store._unsafe_replace_event(target.model_copy(update={"decision": Decision.ALLOW, "reason": "ok"}))
    check = svc.verify_audit(OWNER)
    assert not check.ok
    assert check.broken_at == target.id
    assert "changed" in check.problem


def test_rehashed_edit_still_breaks_next_link(svc, clock, store) -> None:
    """An attacker who recomputes the edited row's hash still breaks the next row."""
    events = build_history(svc, clock)
    forged = events[2].model_copy(update={"actor": "someone-else@x.test"})
    forged.hash = compute_hash(forged)
    store._unsafe_replace_event(forged)
    check = svc.verify_audit(OWNER)
    assert not check.ok and check.broken_at == events[3].id


def test_deleted_row_detected() -> None:
    from app.clock import FakeClock
    from app.models import AuditDraft
    from app.store import MemoryStore
    from tests.conftest import T0

    store, clock = MemoryStore(), FakeClock(T0)
    for i in range(5):
        store.append_audit(AuditDraft(workspace_id=WS, ts=clock.advance(minutes=1), actor="a", action=f"x{i}"))
    events = store.list_audit(WS)
    del events[2]
    check = verify_chain(events)
    assert not check.ok and "sequence gap" in check.problem


def test_fixed_event_id_is_written_once(store, clock) -> None:
    from app.models import AuditDraft

    draft = AuditDraft(workspace_id=WS, ts=clock.now(), actor="system", action="grant.expired", target="g1")
    assert store.append_audit(draft, event_id="g1:expired") is not None
    assert store.append_audit(draft, event_id="g1:expired") is None
    assert len(store.list_audit(WS)) == 1


def test_non_owner_cannot_read_audit(svc) -> None:
    import pytest

    from app.services import PermissionDenied

    with pytest.raises(PermissionDenied):
        svc.audit_events(SAM)
    # ...and the attempt itself is logged.
    assert svc.store.list_audit(WS)[-1].reason == "not_owner"
