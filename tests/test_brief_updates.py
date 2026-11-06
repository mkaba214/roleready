"""Features added for the Nov 4 product brief: time zones, the focused dashboard,
and a least-privilege integration path for Newly."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.store import MemoryStore
from tests.conftest import OWNER, SAM, T0, as_user

KEY = "k" * 40  # test integration key (real keys come from Secret Manager)


def body(**over) -> dict:
    return {
        "invitee_email": SAM, "role": "contributor", "task_types": ["view_assets", "edit_drafts"],
        "start_at": (T0 + timedelta(minutes=10)).isoformat(),
        "expires_at": (T0 + timedelta(days=2)).isoformat(), **over,
    }


def invite_and_accept(c: TestClient, **over) -> dict:
    inv = c.post("/invitations", json=body(**over), headers=as_user(OWNER)).json()
    token = c.post(f"/invitations/{inv['id']}/approve", headers=as_user(OWNER)).json()["invite_token"]
    return c.post("/invitations/accept", json={"token": token}, headers=as_user(SAM)).json()


# Time zone ------------------------------------------------------------------
def test_invitation_and_grant_carry_time_zone(client) -> None:
    grant = invite_and_accept(client, timezone="America/Los_Angeles")
    assert grant["timezone"] == "America/Los_Angeles"
    inv = client.get("/invitations", headers=as_user(OWNER)).json()[0]
    assert inv["timezone"] == "America/Los_Angeles"
    created = next(e for e in client.get("/audit", headers=as_user(OWNER)).json() if e["action"] == "invitation.created")
    assert created["details"]["timezone"] == "America/Los_Angeles"


def test_default_time_zone_applies(client) -> None:
    grant = invite_and_accept(client)
    assert grant["timezone"] == "America/Chicago"


@pytest.mark.parametrize("tz", ["Mars/Olympus", "CST; DROP TABLE", "x" * 80])
def test_bad_time_zone_rejected(client, tz) -> None:
    r = client.post("/invitations", json=body(timezone=tz), headers=as_user(OWNER))
    assert r.status_code == 422


# Focused dashboard ------------------------------------------------------------
def test_metrics_report_success_measures(client, clock) -> None:
    grant = invite_and_accept(client)
    clock.advance(minutes=15)
    client.post("/actions/edit_drafts", headers=as_user(SAM))
    client.post("/actions/view_analytics", headers=as_user(SAM))
    client.post(f"/grants/{grant['id']}/revoke", headers=as_user(OWNER))
    client.post("/actions/edit_drafts", headers=as_user(SAM))
    clock.advance(days=3)
    client.post("/jobs/expire")

    m = client.get("/metrics", headers=as_user(OWNER)).json()
    by_name = {row["measure"]: row for row in m["measures"]}
    assert by_name["Protected actions allowed after access ended"]["actual"] == "0"
    assert by_name["Protected actions allowed after access ended"]["met"] is True
    assert by_name["Duplicate expiration events"]["met"] is True
    assert by_name["Grants made without owner approval"]["met"] is True
    assert by_name["Allowed and denied actions logged"]["met"] is True
    assert "1 allowed, 2 denied" in by_name["Allowed and denied actions logged"]["actual"]
    assert m["counts"]["grants_by_state"] == {"revoked": 1}


def test_metrics_catch_an_allow_after_end(svc, clock, store) -> None:
    """If a bug ever let an action through after expiry, the dashboard must show it."""
    from app.models import AuditDraft, Decision
    from tests.conftest import grant_access

    g = grant_access(svc)
    store.append_audit(AuditDraft(workspace_id="bloom-and-crumb", ts=g.expires_at + timedelta(minutes=1),
                                  actor=SAM, action="action.edit_drafts", target=g.id, decision=Decision.ALLOW, reason="ok"))
    row = next(r for r in svc.success_metrics(OWNER)["measures"] if r["measure"].startswith("Protected"))
    assert row["actual"] == "1" and row["met"] is False


def test_metrics_owner_only(client) -> None:
    assert client.get("/metrics", headers=as_user(SAM)).status_code == 403


# Newly integration ------------------------------------------------------------
def newly_app(clock, **kw):
    settings = Settings(auth_mode="firebase", owner_email=OWNER, integration_api_key=KEY, **kw)
    return TestClient(create_app(settings, store=MemoryStore(), clock=clock))


def as_newly(email: str, key: str = KEY) -> dict:
    return {"X-RoleReady-Integration-Key": key, "X-Acting-User": email}


def test_integration_off_by_default(app_factory) -> None:
    c = TestClient(app_factory(None))
    assert c.get("/me", headers=as_newly(SAM)).status_code == 401


def test_integration_rejects_bad_key_and_missing_user(clock) -> None:
    c = newly_app(clock)
    assert c.get("/me", headers=as_newly(SAM, key="wrong" * 10)).status_code == 401
    assert c.get("/me", headers={"X-RoleReady-Integration-Key": KEY}).status_code == 401
    assert c.get("/me", headers=as_newly(SAM)).json()["via"] == "newly"


def test_integration_cannot_act_as_owner_by_default(clock) -> None:
    c = newly_app(clock)
    r = c.post("/invitations", json=body(), headers=as_newly(OWNER))
    assert r.status_code == 403
    # The blocked attempt is in the audit trail, tagged with the channel.
    events = c.app.state.service.store.list_audit("bloom-and-crumb")
    assert events[-1].reason == "owner_blocked_on_channel" and events[-1].details["via"] == "newly"


def test_integration_freelancer_flow_is_tagged(clock) -> None:
    c = newly_app(clock, integration_allow_owner=True)
    inv = c.post("/invitations", json=body(), headers=as_newly(OWNER))
    assert inv.status_code == 201
    token = c.post(f"/invitations/{inv.json()['id']}/approve", headers=as_newly(OWNER)).json()["invite_token"]
    assert c.post("/invitations/accept", json={"token": token}, headers=as_newly(SAM)).status_code == 200
    clock.advance(minutes=15)
    assert c.post("/actions/edit_drafts", headers=as_newly(SAM)).status_code == 200
    assert c.post("/actions/manage_access", headers=as_newly(SAM)).status_code == 403
    events = c.app.state.service.store.list_audit("bloom-and-crumb")
    assert all(e.details.get("via") == "newly" for e in events)


def test_short_integration_key_refused() -> None:
    with pytest.raises(RuntimeError, match="at least 32"):
        create_app(Settings(auth_mode="demo", integration_api_key="short"))


# CORS ---------------------------------------------------------------------
def test_cors_only_for_listed_origins(clock) -> None:
    settings = Settings(auth_mode="demo", owner_email=OWNER, cors_allowed_origins=("https://app.example.test",))
    c = TestClient(create_app(settings, store=MemoryStore(), clock=clock))
    pre = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "X-Demo-User"}
    ok = c.options("/me", headers={"Origin": "https://app.example.test", **pre})
    assert ok.headers.get("access-control-allow-origin") == "https://app.example.test"
    bad = c.options("/me", headers={"Origin": "https://evil.test", **pre})
    assert "access-control-allow-origin" not in bad.headers
    # The integration key header is never allowed from a browser.
    key_pre = c.options("/me", headers={"Origin": "https://app.example.test", "Access-Control-Request-Method": "GET",
                                        "Access-Control-Request-Headers": "X-RoleReady-Integration-Key"})
    assert key_pre.status_code == 400


def test_wildcard_cors_and_emulator_on_cloud_run_refused() -> None:
    with pytest.raises(RuntimeError, match="exact origins"):
        create_app(Settings(auth_mode="demo", cors_allowed_origins=("*",)))
    with pytest.raises(RuntimeError, match="never be set on Cloud Run"):
        create_app(Settings(auth_mode="firebase", running_on_cloud_run=True, firebase_auth_emulator_host="localhost:4588"))
