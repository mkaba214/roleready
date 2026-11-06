"""Domain models shared by the policy engine, stores, services and API."""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def new_id() -> str:
    return secrets.token_hex(8)


def normalize_email(value: str) -> str:
    value = (value or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError(f"not a valid email address: {value!r}")
    return value


def valid_timezone(name: str) -> str:
    """An IANA time zone name such as America/Chicago. Rejects anything else."""
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise ValueError("time zone is required")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown time zone {name!r} (use an IANA name like America/Chicago)") from None
    return name


class Role(StrEnum):
    OWNER = "owner"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class TaskType(StrEnum):
    VIEW_ASSETS = "view_assets"
    EDIT_DRAFTS = "edit_drafts"
    SCHEDULE_POSTS = "schedule_posts"
    VIEW_ANALYTICS = "view_analytics"
    MANAGE_ACCESS = "manage_access"


class InvitationStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"


class GrantStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class InvitationRequest(BaseModel):
    """What an owner submits (by hand or from an Access Assistant draft)."""

    invitee_email: str
    role: Role
    task_types: list[TaskType]
    start_at: datetime
    expires_at: datetime
    # The zone the owner thinks in. Times are stored in UTC; this says how to show them.
    timezone: str | None = None
    reason: str = ""

    @field_validator("invitee_email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return None if v in (None, "") else valid_timezone(v)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return (v or "").strip()[:500]


class Invitation(BaseModel):
    id: str = Field(default_factory=new_id)
    workspace_id: str
    invitee_email: str
    role: Role
    task_types: list[TaskType]
    start_at: datetime
    expires_at: datetime
    timezone: str = "UTC"
    reason: str = ""
    status: InvitationStatus = InvitationStatus.DRAFT
    source: str = "manual"  # "manual" or "assistant"
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    token_hash: str | None = None
    token_expires_at: datetime | None = None
    accepted_at: datetime | None = None
    grant_id: str | None = None
    cancelled_at: datetime | None = None

    def public(self) -> dict[str, Any]:
        """API view: never expose the token hash."""
        return self.model_dump(mode="json", exclude={"token_hash"})


class Grant(BaseModel):
    id: str = Field(default_factory=new_id)
    workspace_id: str = "bloom-and-crumb"
    user_email: str = ""
    role: Role
    # None means "every task the role allows". Stored grants always carry an explicit list.
    task_types: list[TaskType] | None = None
    start_at: datetime
    expires_at: datetime
    timezone: str = "UTC"
    status: GrantStatus = GrantStatus.ACTIVE
    invitation_id: str | None = None
    created_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    expired_at: datetime | None = None


class AuditDraft(BaseModel):
    """An audit event before the store assigns its id, sequence number and hashes."""

    workspace_id: str
    ts: datetime
    actor: str
    action: str
    target: str = ""
    decision: Decision | None = None
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(AuditDraft):
    id: str
    seq: int
    prev_hash: str
    hash: str = ""
