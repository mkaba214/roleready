"""The full 60-case grid: 3 roles x 5 tasks x 4 grant states, through the real service."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import TaskType
from tests.conftest import OWNER, grant_access

ROLE_TASKS = {
    "owner": set(TaskType),
    "contributor": {TaskType.VIEW_ASSETS, TaskType.EDIT_DRAFTS, TaskType.SCHEDULE_POSTS},
    "viewer": {TaskType.VIEW_ASSETS, TaskType.VIEW_ANALYTICS},
}
STATES = ["pending", "active", "expired", "revoked"]


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("task", list(TaskType))
@pytest.mark.parametrize("role", list(ROLE_TASKS))
def test_grid(svc, clock, role: str, task: TaskType, state: str) -> None:
    if role == "owner":
        # The owner has no grant: the owner is always allowed, in every "state".
        result = svc.perform_action(OWNER, task.value)
        assert result.allowed is True
        return

    email = f"{role}@grid.test"
    tasks = tuple(sorted(t.value for t in ROLE_TASKS[role]))
    grant = grant_access(svc, email=email, role=role, tasks=tasks, start_in=timedelta(hours=1), length=timedelta(days=2))

    if state == "active":
        clock.advance(hours=2)
    elif state == "expired":
        clock.advance(days=3)
        svc.expire_due_grants()
    elif state == "revoked":
        clock.advance(hours=2)
        svc.revoke_grant(OWNER, grant.id)

    result = svc.perform_action(email, task.value)
    expected = state == "active" and task in ROLE_TASKS[role]
    assert result.allowed is expected, (role, task, state, result.reason)

    # Every decision, allowed or denied, lands in the audit log.
    last = svc.store.list_audit("bloom-and-crumb")[-1]
    assert last.action == f"action.{task.value}"
    assert last.decision.value == ("allow" if expected else "deny")
