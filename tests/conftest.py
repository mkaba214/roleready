from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import verify_scheduler
from app.clock import FakeClock
from app.config import Settings
from app.llm import LLMResult
from app.main import create_app
from app.models import InvitationRequest
from app.services import RoleReadyService
from app.store import MemoryStore

OWNER = "owner@bloomandcrumb.test"
SAM = "sam@freelance.test"  # contributor
RILEY = "riley@client.test"  # viewer
# Mon Nov 9, 2026, 8:00 AM Central (UTC-6)
T0 = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)


class FakeLLM:
    """Returns scripted replies and records every prompt it receives."""

    def __init__(self, replies: list[str | dict] | None = None, model: str = "fake/model") -> None:
        self.replies = list(replies or [])
        self.calls: list[tuple[str, str]] = []
        self.model = model

    def complete(self, system: str, user: str, *, max_tokens: int = 1024, temperature: float = 0.2) -> LLMResult:
        self.calls.append((system, user))
        reply = self.replies.pop(0) if self.replies else "{}"
        text = json.dumps(reply) if isinstance(reply, dict) else reply
        return LLMResult(text=text, model=self.model)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def svc(store: MemoryStore, clock: FakeClock) -> RoleReadyService:
    return RoleReadyService(store, clock, workspace_id="bloom-and-crumb", owner_email=OWNER)


def grant_access(
    svc: RoleReadyService,
    email: str = SAM,
    role: str = "contributor",
    tasks: tuple[str, ...] = ("view_assets", "edit_drafts", "schedule_posts"),
    start_in: timedelta = timedelta(hours=1),
    length: timedelta = timedelta(days=4),
):
    """Owner creates, approves; invitee accepts. Returns the grant."""
    now = svc.clock.now()
    req = InvitationRequest(
        invitee_email=email,
        role=role,
        task_types=list(tasks),
        start_at=now + start_in,
        expires_at=now + start_in + length,
        reason="test",
    )
    inv = svc.create_invitation(OWNER, req)
    _, token = svc.approve_invitation(OWNER, inv.id)
    return svc.accept_invitation(email, token)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def app_factory(clock: FakeClock):
    def make(llm: FakeLLM | None = None, *, scheduler_ok: bool = False, **settings_kw):
        settings = Settings(auth_mode="demo", owner_email=OWNER, **settings_kw)
        app = create_app(settings, store=MemoryStore(), clock=clock, llm=llm)
        if scheduler_ok:
            app.dependency_overrides[verify_scheduler] = lambda: "scheduler@test.iam.gserviceaccount.com"
        return app

    return make


@pytest.fixture
def client(app_factory, fake_llm) -> TestClient:
    return TestClient(app_factory(fake_llm, scheduler_ok=True))


def as_user(email: str) -> dict[str, str]:
    return {"X-Demo-User": email}
