"""Expiry and revoke: access ends on time, repeated jobs change nothing."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import GrantStatus
from app.services import Conflict
from tests.conftest import OWNER, SAM, grant_access

WS = "bloom-and-crumb"


def events(svc, action: str) -> list:
    return [e for e in svc.store.list_audit(WS) if e.action == action]


def test_ten_runs_write_one_expired_event_per_grant(svc, clock) -> None:
    g1 = grant_access(svc, email="a@x.test")
    g2 = grant_access(svc, email="b@x.test", length=timedelta(days=1))
    clock.advance(days=6)
    reports = [svc.expire_due_grants() for _ in range(10)]
    assert sorted(reports[0].expired) == sorted([g1.id, g2.id])
    assert all(r.expired == [] for r in reports[1:])
    assert len(events(svc, "grant.expired")) == 2
    assert {e.id for e in events(svc, "grant.expired")} == {f"{g1.id}:expired", f"{g2.id}:expired"}


def test_job_before_expiry_does_nothing(svc, clock) -> None:
    g = grant_access(svc)
    clock.advance(days=2)
    report = svc.expire_due_grants()
    assert report.expired == []
    assert svc.store.get_grant(g.id).status == GrantStatus.ACTIVE


def test_access_ends_on_the_second_even_if_job_never_runs(svc, clock) -> None:
    g = grant_access(svc, start_in=timedelta(0), length=timedelta(hours=2))
    clock.set(g.expires_at - timedelta(seconds=1))
    assert svc.perform_action(SAM, "edit_drafts").allowed is True
    clock.set(g.expires_at)
    result = svc.perform_action(SAM, "edit_drafts")
    assert result.allowed is False and result.reason == "expired"
    assert svc.store.get_grant(g.id).status == GrantStatus.ACTIVE  # job has not run, access still ended


def test_revoke_takes_effect_on_next_request(svc, clock) -> None:
    g = grant_access(svc, start_in=timedelta(0))
    clock.advance(minutes=5)
    assert svc.perform_action(SAM, "view_assets").allowed is True
    svc.revoke_grant(OWNER, g.id)
    result = svc.perform_action(SAM, "view_assets")
    assert result.allowed is False and result.reason == "revoked"


def test_revoke_then_expire_keeps_revoked(svc, clock) -> None:
    g = grant_access(svc)
    clock.advance(hours=2)
    svc.revoke_grant(OWNER, g.id)
    clock.advance(days=10)
    report = svc.expire_due_grants()
    assert report.expired == []
    assert svc.store.get_grant(g.id).status == GrantStatus.REVOKED
    assert events(svc, "grant.expired") == []


def test_expire_then_revoke_conflicts(svc, clock) -> None:
    g = grant_access(svc)
    clock.advance(days=10)
    svc.expire_due_grants()
    with pytest.raises(Conflict):
        svc.revoke_grant(OWNER, g.id)
    assert len(events(svc, "grant.revoked")) == 0


def test_double_revoke_conflicts_and_logs_once(svc, clock) -> None:
    g = grant_access(svc)
    svc.revoke_grant(OWNER, g.id)
    with pytest.raises(Conflict):
        svc.revoke_grant(OWNER, g.id)
    assert len(events(svc, "grant.revoked")) == 1


def test_racing_revoke_and_expire_threads(svc, clock) -> None:
    """Many threads race to revoke and expire the same grant. Exactly one wins."""
    import threading

    g = grant_access(svc)
    clock.set(g.expires_at)  # due for expiry and still revocable
    outcomes: list[str] = []

    def do_revoke():
        try:
            svc.revoke_grant(OWNER, g.id)
            outcomes.append("revoked")
        except Conflict:
            outcomes.append("conflict")

    def do_expire():
        if svc.expire_due_grants().expired:
            outcomes.append("expired")

    threads = [threading.Thread(target=fn) for fn in [do_revoke, do_expire] * 10]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [o for o in outcomes if o in ("revoked", "expired")]
    assert len(winners) == 1
    final = svc.store.get_grant(g.id).status
    assert final.value == winners[0]
    assert len(events(svc, "grant.revoked")) + len(events(svc, "grant.expired")) == 1
