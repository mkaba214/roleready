"""Permission matrix and time-window tests. Written first: these define the product."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import policy
from app.models import Grant, GrantStatus, Role, TaskType
from app.policy import evaluate, is_allowed

START = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)  # Mon 9:00 AM Central
END = datetime(2026, 11, 13, 23, 0, tzinfo=timezone.utc)  # Fri 5:00 PM Central
MID = START + timedelta(days=1)
ONE_SEC = timedelta(seconds=1)

EXPECTED = {
    #                     view_assets edit_drafts schedule_posts view_analytics manage_access
    Role.OWNER: (True, True, True, True, True),
    Role.CONTRIBUTOR: (True, True, True, False, False),
    Role.VIEWER: (True, False, False, True, False),
}
TASK_ORDER = [
    TaskType.VIEW_ASSETS,
    TaskType.EDIT_DRAFTS,
    TaskType.SCHEDULE_POSTS,
    TaskType.VIEW_ANALYTICS,
    TaskType.MANAGE_ACCESS,
]


def make_grant(role: Role, **kw) -> Grant:
    return Grant(role=role, status=GrantStatus.ACTIVE, start_at=START, expires_at=END, **kw)


# 15 cases: 3 roles x 5 tasks ------------------------------------------------
@pytest.mark.parametrize("role", list(EXPECTED))
@pytest.mark.parametrize("task_index", range(5))
def test_permission_matrix(role: Role, task_index: int) -> None:
    task = TASK_ORDER[task_index]
    assert is_allowed(make_grant(role), task, MID) is EXPECTED[role][task_index]


# 8 time-window cases ----------------------------------------------------------
@pytest.mark.parametrize(
    "now, expected, reason",
    [
        (START - ONE_SEC, False, "not_started"),
        (START, True, "ok"),
        (MID, True, "ok"),
        (END - ONE_SEC, True, "ok"),
        (END, False, "expired"),
        (END + ONE_SEC, False, "expired"),
        (END + timedelta(days=30), False, "expired"),
        (START - timedelta(days=1), False, "not_started"),
    ],
)
def test_time_window(now: datetime, expected: bool, reason: str) -> None:
    decision = evaluate(make_grant(Role.CONTRIBUTOR), TaskType.EDIT_DRAFTS, now)
    assert decision.allowed is expected
    assert decision.reason == reason


def test_example_from_the_plan() -> None:
    """The exact test shown in the team plan doc."""
    grant = Grant(role="contributor", status="active", start_at=START, expires_at=END, revoked_at=None)
    assert is_allowed(grant, "edit_drafts", START) is True
    assert is_allowed(grant, "edit_drafts", END) is False
    viewer = Grant(role="viewer", status="active", start_at=START, expires_at=END, revoked_at=None)
    assert is_allowed(viewer, "edit_drafts", START) is False


def test_revoked_denies_inside_window() -> None:
    g = make_grant(Role.CONTRIBUTOR, revoked_at=MID - timedelta(hours=1))
    assert evaluate(g, TaskType.VIEW_ASSETS, MID).reason == "revoked"


def test_expired_status_denies_inside_window() -> None:
    g = make_grant(Role.CONTRIBUTOR).model_copy(update={"status": GrantStatus.EXPIRED})
    assert evaluate(g, TaskType.VIEW_ASSETS, MID).reason == "expired"


def test_grant_narrower_than_role() -> None:
    g = make_grant(Role.CONTRIBUTOR, task_types=[TaskType.VIEW_ASSETS])
    assert evaluate(g, TaskType.EDIT_DRAFTS, MID).reason == "task_not_granted"


def test_grant_cannot_widen_role() -> None:
    # Even if a stored grant lists manage_access, the contributor role blocks it.
    g = make_grant(Role.CONTRIBUTOR, task_types=[TaskType.MANAGE_ACCESS])
    assert evaluate(g, TaskType.MANAGE_ACCESS, MID).reason == "role_forbids_task"


def test_no_grant_and_unknown_task_deny() -> None:
    assert evaluate(None, TaskType.VIEW_ASSETS, MID).reason == "no_grant"
    assert evaluate(make_grant(Role.OWNER), "delete_workspace", MID).reason == "unknown_task"


def test_naive_now_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate(make_grant(Role.VIEWER), TaskType.VIEW_ASSETS, datetime(2026, 11, 10))


# Invitation rules -------------------------------------------------------------
def test_validate_invitation_rules() -> None:
    now = START - timedelta(hours=1)
    ok = policy.validate_invitation("contributor", ["edit_drafts"], START, END, now)
    assert ok == []
    assert any("cannot be granted" in e for e in policy.validate_invitation("owner", ["view_assets"], START, END, now))
    assert any("manage_access" in e for e in policy.validate_invitation("viewer", ["manage_access"], START, END, now))
    assert any("does not allow" in e for e in policy.validate_invitation("viewer", ["edit_drafts"], START, END, now))
    assert any("after start_at" in e for e in policy.validate_invitation("viewer", ["view_assets"], END, START, now))
    assert any("expires_at is required" in e for e in policy.validate_invitation("viewer", ["view_assets"], START, None, now))
    assert any("longer than" in e for e in policy.validate_invitation("viewer", ["view_assets"], START, START + timedelta(days=31), now))
    assert any("in the past" in e for e in policy.validate_invitation("viewer", ["view_assets"], now - timedelta(hours=2), END, now))
    assert any("unknown task" in e for e in policy.validate_invitation("viewer", ["delete_all"], START, END, now))


def test_least_privilege_warnings() -> None:
    wide = policy.least_privilege_warnings("contributor", ["view_assets", "edit_drafts", "schedule_posts"], START, START + timedelta(days=20))
    assert any("20 days" in w for w in wide)
    assert any("every task" in w for w in wide)
    assert policy.least_privilege_warnings("viewer", ["view_assets"], START, END) == []


def test_effective_state() -> None:
    g = make_grant(Role.VIEWER)
    assert policy.effective_state(g, START - ONE_SEC) == "pending"
    assert policy.effective_state(g, MID) == "active"
    assert policy.effective_state(g, END) == "expired"
    assert policy.effective_state(g.model_copy(update={"status": GrantStatus.REVOKED}), MID) == "revoked"
