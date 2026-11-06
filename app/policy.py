"""The policy engine. Pure functions only: no I/O, no clock reads.

Rule: deny by default. A request passes only when
  1. the grant exists and its status is active,
  2. start_at <= now < expires_at,
  3. the grant has not been revoked,
  4. the role allows the task, and
  5. the grant includes the task.

Expiry is checked here on every request. The scheduled expiry job only tidies
status and writes the audit event, so access ends on the exact second even if
the job runs late.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Grant, GrantStatus, Role, TaskType

ROLE_PERMISSIONS: dict[Role, frozenset[TaskType]] = {
    Role.OWNER: frozenset(TaskType),
    Role.CONTRIBUTOR: frozenset(
        {TaskType.VIEW_ASSETS, TaskType.EDIT_DRAFTS, TaskType.SCHEDULE_POSTS}
    ),
    Role.VIEWER: frozenset({TaskType.VIEW_ASSETS, TaskType.VIEW_ANALYTICS}),
}

# Owners are never created through an invitation.
INVITABLE_ROLES: frozenset[Role] = frozenset({Role.CONTRIBUTOR, Role.VIEWER})

MAX_WINDOW = timedelta(days=30)  # hard limit
RECOMMENDED_MAX_WINDOW = timedelta(days=14)  # least-privilege warning above this
START_GRACE = timedelta(minutes=5)  # how far in the past a start time may sit


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def _require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def granted_tasks(grant: Grant) -> frozenset[TaskType]:
    role_tasks = ROLE_PERMISSIONS[grant.role]
    if grant.task_types is None:
        return role_tasks
    return frozenset(grant.task_types) & role_tasks


def evaluate(grant: Grant | None, task: TaskType | str, now: datetime) -> PolicyDecision:
    """Decide one request. Every branch that is not an explicit allow is a deny."""
    _require_aware(now, "now")
    try:
        task = TaskType(task)
    except ValueError:
        return PolicyDecision(False, "unknown_task")

    if grant is None:
        return PolicyDecision(False, "no_grant")
    if grant.revoked_at is not None or grant.status == GrantStatus.REVOKED:
        return PolicyDecision(False, "revoked")
    if grant.status == GrantStatus.EXPIRED:
        return PolicyDecision(False, "expired")
    if grant.status != GrantStatus.ACTIVE:
        return PolicyDecision(False, "inactive")
    if now < grant.start_at:
        return PolicyDecision(False, "not_started")
    if now >= grant.expires_at:
        return PolicyDecision(False, "expired")
    if task not in ROLE_PERMISSIONS[grant.role]:
        return PolicyDecision(False, "role_forbids_task")
    if task not in granted_tasks(grant):
        return PolicyDecision(False, "task_not_granted")
    return PolicyDecision(True, "ok")


def is_allowed(grant: Grant | None, task: TaskType | str, now: datetime) -> bool:
    return evaluate(grant, task, now).allowed


def effective_state(grant: Grant, now: datetime) -> str:
    """What a person sees: pending, active, expired or revoked."""
    if grant.revoked_at is not None or grant.status == GrantStatus.REVOKED:
        return "revoked"
    if grant.status == GrantStatus.EXPIRED or now >= grant.expires_at:
        return "expired"
    if now < grant.start_at:
        return "pending"
    return "active"


def validate_invitation(
    role: Role | str | None,
    task_types: list[TaskType | str] | None,
    start_at: datetime | None,
    expires_at: datetime | None,
    now: datetime,
) -> list[str]:
    """Hard rules. Any error blocks the invitation."""
    _require_aware(now, "now")
    errors: list[str] = []

    parsed_role: Role | None = None
    try:
        parsed_role = Role(role) if role is not None else None
    except ValueError:
        errors.append(f"unknown role {role!r}")
    if parsed_role is None and role is None:
        errors.append("role is required")
    elif parsed_role is not None and parsed_role not in INVITABLE_ROLES:
        errors.append(f"role {parsed_role.value!r} cannot be granted by invitation")

    tasks: list[TaskType] = []
    for t in task_types or []:
        try:
            tasks.append(TaskType(t))
        except ValueError:
            errors.append(f"unknown task type {t!r}")
    if not task_types:
        errors.append("at least one task type is required")
    if TaskType.MANAGE_ACCESS in tasks:
        errors.append("manage_access is never granted by invitation")
    if parsed_role in INVITABLE_ROLES:
        outside = sorted(t.value for t in set(tasks) - ROLE_PERMISSIONS[parsed_role])
        if outside:
            errors.append(f"role {parsed_role.value!r} does not allow: {', '.join(outside)}")

    if start_at is None:
        errors.append("start_at is required")
    if expires_at is None:
        errors.append("expires_at is required (every grant needs an end)")
    if start_at is not None and expires_at is not None:
        try:
            _require_aware(start_at, "start_at")
            _require_aware(expires_at, "expires_at")
        except ValueError as exc:
            errors.append(str(exc))
            return errors
        if expires_at <= start_at:
            errors.append("expires_at must be after start_at")
        if expires_at - start_at > MAX_WINDOW:
            errors.append(f"window longer than {MAX_WINDOW.days} days")
        if start_at < now - START_GRACE:
            errors.append("start_at is in the past")
    return errors


def least_privilege_warnings(
    role: Role | str | None,
    task_types: list[TaskType | str] | None,
    start_at: datetime | None,
    expires_at: datetime | None,
) -> list[str]:
    """Soft rules. The owner may still approve, but sees why the draft looks wide."""
    warnings: list[str] = []
    try:
        parsed_role = Role(role) if role is not None else None
        tasks = {TaskType(t) for t in task_types or []}
    except ValueError:
        return warnings
    if start_at and expires_at and expires_at - start_at > RECOMMENDED_MAX_WINDOW:
        days = (expires_at - start_at).days
        warnings.append(f"window is {days} days; consider {RECOMMENDED_MAX_WINDOW.days} or fewer")
    if parsed_role in INVITABLE_ROLES and tasks == ROLE_PERMISSIONS[parsed_role] and len(tasks) > 2:
        warnings.append("draft grants every task the role allows; remove any the job does not need")
    if parsed_role == Role.CONTRIBUTOR and TaskType.SCHEDULE_POSTS in tasks and TaskType.EDIT_DRAFTS not in tasks:
        warnings.append("schedule_posts without edit_drafts is unusual; check the request")
    return warnings
