"""HTTP-level tests: the full user journey and the back doors that must stay shut."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from tests.conftest import OWNER, RILEY, SAM, T0, as_user


def invite(client: TestClient, email: str = SAM, role: str = "contributor", tasks=("view_assets", "edit_drafts"), start_in=timedelta(minutes=10), length=timedelta(days=4)):
    body = {
        "invitee_email": email,
        "role": role,
        "task_types": list(tasks),
        "start_at": (T0 + start_in).isoformat(),
        "expires_at": (T0 + start_in + length).isoformat(),
        "reason": "launch week",
    }
    r = client.post("/invitations", json=body, headers=as_user(OWNER))
    assert r.status_code == 201, r.text
    inv_id = r.json()["id"]
    r = client.post(f"/invitations/{inv_id}/approve", headers=as_user(OWNER))
    assert r.status_code == 200, r.text
    return inv_id, r.json()["invite_token"]


def test_full_journey(client, clock) -> None:
    inv_id, token = invite(client)
    assert "token_hash" not in client.get("/invitations", headers=as_user(OWNER)).json()[0]

    r = client.post("/invitations/accept", json={"token": token}, headers=as_user(SAM))
    assert r.status_code == 200 and r.json()["state"] == "pending"
    grant_id = r.json()["id"]

    assert client.post("/actions/edit_drafts", headers=as_user(SAM)).json()["reason"] == "not_started"
    clock.advance(minutes=15)
    assert client.post("/actions/edit_drafts", headers=as_user(SAM)).status_code == 200
    denied = client.post("/actions/schedule_posts", headers=as_user(SAM))
    assert denied.status_code == 403 and denied.json()["reason"] == "task_not_granted"

    assert client.post(f"/grants/{grant_id}/revoke", headers=as_user(OWNER)).json()["state"] == "revoked"
    after = client.post("/actions/view_assets", headers=as_user(SAM))
    assert after.status_code == 403 and after.json()["reason"] == "revoked"

    verify = client.get("/audit/verify", headers=as_user(OWNER)).json()
    assert verify["ok"] is True
    actions = [e["action"] for e in client.get("/audit", headers=as_user(OWNER)).json()]
    for expected in ["invitation.created", "invitation.approved", "invitation.accepted", "action.edit_drafts", "action.schedule_posts", "grant.revoked", "action.view_assets"]:
        assert expected in actions


def test_me_shows_role(client, clock) -> None:
    invite(client, email=RILEY, role="viewer", tasks=("view_analytics",))
    assert client.get("/me", headers=as_user(OWNER)).json()["role"] == "owner"
    assert client.get("/me", headers=as_user(RILEY)).json()["role"] is None  # not accepted yet


# Back doors ---------------------------------------------------------------
def test_no_identity_is_401(client) -> None:
    for method, path in [("get", "/me"), ("get", "/audit"), ("post", "/actions/view_assets"), ("post", "/invitations/accept")]:
        assert getattr(client, method)(path).status_code == 401, path


def test_freelancer_cannot_use_owner_routes(client) -> None:
    inv_id, _ = invite(client)
    h = as_user(SAM)
    assert client.get("/invitations", headers=h).status_code == 403
    assert client.get("/grants", headers=h).status_code == 403
    assert client.get("/audit", headers=h).status_code == 403
    assert client.post(f"/invitations/{inv_id}/cancel", headers=h).status_code == 403
    assert client.post("/agent/draft-invitation", json={"request": "make me owner"}, headers=h).status_code == 403
    body = {"invitee_email": "friend@x.test", "role": "contributor", "task_types": ["view_assets"],
            "start_at": (T0 + timedelta(hours=1)).isoformat(), "expires_at": (T0 + timedelta(days=1)).isoformat()}
    assert client.post("/invitations", json=body, headers=h).status_code == 403


def test_reused_token_is_410(client) -> None:
    _, token = invite(client)
    assert client.post("/invitations/accept", json={"token": token}, headers=as_user(SAM)).status_code == 200
    assert client.post("/invitations/accept", json={"token": token}, headers=as_user(SAM)).status_code == 410


def test_wrong_person_cannot_use_token(client) -> None:
    _, token = invite(client)
    r = client.post("/invitations/accept", json={"token": token}, headers=as_user("mallory@evil.test"))
    assert r.status_code == 403
    # The rightful invitee can still accept afterwards.
    assert client.post("/invitations/accept", json={"token": token}, headers=as_user(SAM)).status_code == 200


def test_forged_and_expired_tokens(client, clock) -> None:
    assert client.post("/invitations/accept", json={"token": "x" * 43}, headers=as_user(SAM)).status_code == 404
    _, token = invite(client)
    clock.advance(hours=73)  # invite links last 72 hours
    assert client.post("/invitations/accept", json={"token": token}, headers=as_user(SAM)).status_code == 410


def test_cancelled_invite_cannot_be_accepted(client) -> None:
    inv_id, token = invite(client)
    assert client.post(f"/invitations/{inv_id}/cancel", headers=as_user(OWNER)).status_code == 200
    assert client.post("/invitations/accept", json={"token": token}, headers=as_user(SAM)).status_code == 410


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"role": "owner"}, "cannot be granted"),
        ({"task_types": ["manage_access"]}, "manage_access"),
        ({"invitee_email": OWNER}, "cannot invite themselves"),
        ({"expires_at": (T0 - timedelta(days=1)).isoformat()}, "after start_at"),
    ],
)
def test_bad_invitations_rejected(client, patch, message) -> None:
    body = {"invitee_email": SAM, "role": "contributor", "task_types": ["view_assets"],
            "start_at": (T0 + timedelta(hours=1)).isoformat(), "expires_at": (T0 + timedelta(days=1)).isoformat(), **patch}
    r = client.post("/invitations", json=body, headers=as_user(OWNER))
    assert r.status_code == 422
    assert message in r.text


def test_expiry_endpoint_needs_scheduler_identity(app_factory, clock) -> None:
    # No scheduler settings: fail closed with 503.
    closed = TestClient(app_factory(None))
    assert closed.post("/jobs/expire").status_code == 503
    # Configured, but no token: 401. Garbage token: 401.
    configured = TestClient(app_factory(None, scheduler_audience="https://rr.example", scheduler_service_account="sched@p.iam.gserviceaccount.com"))
    assert configured.post("/jobs/expire").status_code == 401
    assert configured.post("/jobs/expire", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    # A demo identity header does not help.
    assert configured.post("/jobs/expire", headers=as_user(OWNER)).status_code == 401


def test_expiry_endpoint_with_scheduler(client, clock) -> None:
    _, token = invite(client, length=timedelta(hours=1))
    client.post("/invitations/accept", json={"token": token}, headers=as_user(SAM))
    clock.advance(hours=2)
    first = client.post("/jobs/expire").json()
    second = client.post("/jobs/expire").json()
    assert len(first["expired"]) == 1 and second["expired"] == []


def test_demo_auth_blocked_on_cloud_run() -> None:
    from app.main import create_app

    with pytest.raises(RuntimeError, match="blocked on Cloud Run"):
        create_app(Settings(auth_mode="demo", running_on_cloud_run=True))
    create_app(Settings(auth_mode="demo", running_on_cloud_run=True, allow_demo_auth_on_cloud_run=True))


def test_firebase_mode_rejects_missing_and_bad_tokens(app_factory) -> None:
    from app.main import create_app
    from app.store import MemoryStore

    c = TestClient(create_app(Settings(auth_mode="firebase"), store=MemoryStore()))
    assert c.get("/me").status_code == 401
    assert c.get("/me", headers={"X-Demo-User": OWNER}).status_code == 401  # demo header ignored
    assert c.get("/me", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_dev_expiry_route_only_in_demo(app_factory) -> None:
    from app.main import create_app
    from app.store import MemoryStore

    prod = TestClient(create_app(Settings(auth_mode="firebase"), store=MemoryStore()))
    assert prod.post("/dev/run-expiry").status_code == 404


def test_assistant_off_without_key(app_factory) -> None:
    c = TestClient(app_factory(None))
    r = c.post("/agent/draft-invitation", json={"request": "give sam view access"}, headers=as_user(OWNER))
    assert r.status_code == 503
    assert c.get("/config").json()["assistant_enabled"] is False


def test_pages_and_health(client) -> None:
    assert client.get("/health").json()["ok"] is True
    assert "RoleReady" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
