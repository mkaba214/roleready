"""Threat model: failed invite-link attempts are rate-limited per signed-in user.

Invite tokens are 256-bit random values, so guessing one is already infeasible. The limit is
defense in depth: it caps how fast one account can probe links, and it records that someone tried.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from tests.conftest import OWNER, RILEY, SAM, as_user
from tests.test_api import invite

BAD = {"token": "x" * 43}


def accept(client: TestClient, user: str, body: dict) -> int:
    return client.post("/invitations/accept", json=body, headers=as_user(user)).status_code


def fail(client: TestClient, user: str, times: int) -> None:
    for _ in range(times):
        assert accept(client, user, BAD) == 404


def test_five_failures_lock_out_that_user_only(client) -> None:
    _, token = invite(client)
    fail(client, SAM, 5)
    r = client.post("/invitations/accept", json={"token": token}, headers=as_user(SAM))
    assert r.status_code == 429  # even a good link is refused while locked out
    assert 0 < int(r.headers["Retry-After"]) <= 15 * 60
    assert "too many" in r.json()["detail"]
    assert accept(client, RILEY, BAD) == 404  # other people aren't affected


def test_lockout_ends_after_the_window(client, clock) -> None:
    _, token = invite(client)
    fail(client, SAM, 5)
    clock.advance(minutes=14)
    assert accept(client, SAM, {"token": token}) == 429
    clock.advance(minutes=1)
    assert accept(client, SAM, {"token": token}) == 200


def test_old_failures_age_out(client, clock) -> None:
    """A rolling window: 4 typos today and 1 tomorrow is not 5 in a row."""
    fail(client, SAM, 4)
    clock.advance(minutes=16)
    fail(client, SAM, 4)
    assert accept(client, SAM, BAD) == 404


def test_a_successful_accept_clears_the_count(client) -> None:
    _, token = invite(client)
    fail(client, SAM, 4)
    assert accept(client, SAM, {"token": token}) == 200
    fail(client, SAM, 4)
    assert accept(client, SAM, BAD) == 404


def test_lockout_is_audited_once(client) -> None:
    """Logged when the limit is reached, not on every refused try, so a script can't flood the audit chain."""
    fail(client, SAM, 5)
    for _ in range(10):
        assert accept(client, SAM, BAD) == 429
    events = client.get("/audit", headers=as_user(OWNER)).json()
    locked = [e for e in events if e["reason"] == "too_many_attempts"]
    assert len(locked) == 1
    assert locked[0]["actor"] == SAM and locked[0]["decision"] == "deny"
    assert sum(e["action"] == "invitation.accept" for e in events) == 6  # 5 failures + 1 lockout


def test_limits_come_from_settings(app_factory) -> None:
    c = TestClient(app_factory(None, accept_max_failures=2, accept_lockout_minutes=1))
    fail(c, SAM, 2)
    assert accept(c, SAM, BAD) == 429
