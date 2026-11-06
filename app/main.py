"""RoleReady API and web UI.

Run locally:  uvicorn app.main:create_app --factory --reload --env-file .env
API docs:     http://localhost:8000/docs  (OpenAPI, useful for Newly and other clients)
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, policy
from .agent import AccessAssistant
from .auth import User, get_current_user, verify_scheduler
from .clock import Clock, SystemClock
from .config import Settings
from .llm import LLMClient, NvidiaClient
from .models import Grant, InvitationRequest, Role
from .services import RoleReadyService, ServiceError
from .store import Store, build_store

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("roleready")


class InvitationCreate(InvitationRequest):
    source: Literal["manual", "assistant"] = "manual"


class AcceptBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class DraftBody(BaseModel):
    request: str = Field(max_length=4000)
    timezone: str | None = None


class ExplainBody(BaseModel):
    question: str = Field(max_length=4000)


class ServiceUnavailable(ServiceError):
    status_code = 503


def create_app(
    settings: Settings | None = None,
    *,
    store: Store | None = None,
    clock: Clock | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.check_safe()
    logging.basicConfig(level=logging.INFO)

    app = FastAPI(title="RoleReady", version=__version__)
    app.state.settings = settings
    clock = clock or SystemClock()
    app.state.clock = clock
    base_svc = RoleReadyService(
        store or build_store(settings.store_backend, project=settings.gcp_project),
        clock,
        workspace_id=settings.workspace_id,
        owner_email=settings.owner_email,
        invite_ttl=timedelta(hours=settings.invite_ttl_hours),
        default_timezone=settings.default_timezone,
    )
    app.state.service = base_svc
    if llm is None and settings.assistant_enabled:
        llm = NvidiaClient(
            settings.nvidia_api_key,
            settings.nvidia_model,
            settings.nvidia_base_url,
            timeout=settings.nvidia_timeout_seconds,
        )
    assistant = AccessAssistant(llm, settings.default_timezone) if llm else None
    app.state.assistant = assistant

    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allowed_origins),
            allow_methods=["GET", "POST"],
            # The integration key header is deliberately absent: browsers must never hold it.
            allow_headers=["Authorization", "Content-Type", "X-Demo-User"],
            allow_credentials=False,
        )

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        body: dict = {"detail": str(exc)}
        if getattr(exc, "errors", None):
            body["errors"] = exc.errors  # type: ignore[attr-defined]
        return JSONResponse(body, status_code=exc.status_code)

    def svc_for(user: User) -> RoleReadyService:
        """The service, tagged with the client channel (web or an integration such as newly)."""
        return base_svc.for_channel(user.via, owner_allowed=user.via == "web" or settings.integration_allow_owner)

    def grant_view(g: Grant) -> dict:
        return {**g.model_dump(mode="json"), "state": policy.effective_state(g, clock.now())}

    # Pages and config ------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/config")
    def config() -> dict:
        firebase = None
        if settings.auth_mode == "firebase" and settings.firebase_api_key:
            firebase = {
                "apiKey": settings.firebase_api_key,
                "authDomain": settings.firebase_auth_domain,
                "projectId": settings.firebase_project_id,
            }
        return {
            "auth_mode": settings.auth_mode,
            "workspace": {"id": settings.workspace_id, "name": settings.workspace_name},
            "demo_users": (
                [settings.owner_email, "sam@freelance.test", "riley@client.test"]
                if settings.auth_mode == "demo"
                else []
            ),
            "firebase": firebase,
            # Local Floci / Firebase emulator only: the browser signs in against the emulator.
            "firebase_auth_emulator_url": (
                f"http://{settings.firebase_auth_emulator_host}" if settings.firebase_auth_emulator_host else None
            ),
            "assistant_enabled": assistant is not None,
            "timezone": settings.default_timezone,
        }

    @app.get("/me")
    def me(user: User = Depends(get_current_user)) -> dict:
        svc = svc_for(user)
        is_owner = svc.is_owner(user.email)
        grants = [] if is_owner else [grant_view(g) for g in svc.grants_for(user.email)]
        active_roles = sorted({g["role"] for g in grants if g["state"] in ("active", "pending")})
        return {
            "email": user.email,
            "via": user.via,
            "is_owner": is_owner,
            "role": Role.OWNER.value if is_owner else (active_roles[0] if active_roles else None),
            "grants": grants,
        }

    # Invitations -----------------------------------------------------------
    @app.post("/invitations", status_code=201)
    def create_invitation(body: InvitationCreate, user: User = Depends(get_current_user)) -> dict:
        return svc_for(user).create_invitation(user.email, body, source=body.source).public()

    @app.get("/invitations")
    def list_invitations(user: User = Depends(get_current_user)) -> list[dict]:
        return [i.public() for i in svc_for(user).list_invitations(user.email)]

    @app.post("/invitations/accept")
    def accept_invitation(body: AcceptBody, user: User = Depends(get_current_user)) -> dict:
        return grant_view(svc_for(user).accept_invitation(user.email, body.token))

    @app.post("/invitations/{invitation_id}/approve")
    def approve_invitation(invitation_id: str, request: Request, user: User = Depends(get_current_user)) -> dict:
        inv, token = svc_for(user).approve_invitation(user.email, invitation_id)
        base = str(request.base_url).rstrip("/")
        # The token rides in the URL fragment, which browsers never send to servers or logs.
        return {"invitation": inv.public(), "invite_token": token, "invite_link": f"{base}/#invite={token}"}

    @app.post("/invitations/{invitation_id}/cancel")
    def cancel_invitation(invitation_id: str, user: User = Depends(get_current_user)) -> dict:
        return svc_for(user).cancel_invitation(user.email, invitation_id).public()

    # Grants ----------------------------------------------------------------
    @app.get("/grants")
    def list_grants(user: User = Depends(get_current_user)) -> list[dict]:
        return [grant_view(g) for g in svc_for(user).list_grants(user.email)]

    @app.post("/grants/{grant_id}/revoke")
    def revoke_grant(grant_id: str, user: User = Depends(get_current_user)) -> dict:
        return grant_view(svc_for(user).revoke_grant(user.email, grant_id))

    # Actions ---------------------------------------------------------------
    @app.post("/actions/{task_type}")
    def perform_action(task_type: str, user: User = Depends(get_current_user)) -> JSONResponse:
        result = svc_for(user).perform_action(user.email, task_type[:64])
        body = {
            "allowed": result.allowed,
            "reason": result.reason,
            "task": result.task,
            "grant_id": result.grant_id,
            "event_id": result.event_id,
        }
        return JSONResponse(body, status_code=200 if result.allowed else 403)

    # Audit and analytics ---------------------------------------------------
    @app.get("/audit")
    def audit(user: User = Depends(get_current_user)) -> list[dict]:
        return [e.model_dump(mode="json") for e in svc_for(user).audit_events(user.email)]

    @app.get("/audit/verify")
    def audit_verify(user: User = Depends(get_current_user)) -> dict:
        return svc_for(user).verify_audit(user.email).as_dict()

    @app.get("/metrics")
    def metrics(user: User = Depends(get_current_user)) -> dict:
        """Focused analytics dashboard: the brief's success measures, live."""
        return svc_for(user).success_metrics(user.email)

    # Access Assistant (NVIDIA) ---------------------------------------------
    def _assistant_or_503() -> AccessAssistant:
        if assistant is None:
            raise ServiceUnavailable("Access Assistant is off: set NVIDIA_API_KEY")
        return assistant

    @app.post("/agent/draft-invitation")
    def agent_draft(body: DraftBody, user: User = Depends(get_current_user)) -> dict:
        svc = svc_for(user)
        svc.require_owner(user.email)
        result = _assistant_or_503().draft_invitation(body.request, clock.now(), body.timezone)
        svc.record_assistant_use(
            user.email,
            "draft_invitation",
            ok=result.ok,
            details={"errors": len(result.errors), "model": result.model or "", "latency_ms": result.latency_ms},
        )
        return result.as_dict()

    @app.post("/agent/explain-audit")
    def agent_explain(body: ExplainBody, user: User = Depends(get_current_user)) -> dict:
        svc = svc_for(user)
        events = svc.audit_events(user.email)  # owner check inside
        result = _assistant_or_503().explain_audit(body.question, events, settings.default_timezone)
        svc.record_assistant_use(
            user.email,
            "explain_audit",
            ok=result.grounded,
            details={"cited": len(result.cited_ids), "unknown": len(result.unknown_citations), "model": result.model or ""},
        )
        return result.as_dict()

    # Expiry job ------------------------------------------------------------
    @app.post("/jobs/expire")
    def run_expiry(_: str = Depends(verify_scheduler)) -> dict:
        return base_svc.expire_due_grants().as_dict()

    if settings.auth_mode == "demo":

        @app.post("/dev/run-expiry")
        def dev_run_expiry(user: User = Depends(get_current_user)) -> dict:
            """Demo mode only: lets the owner run the expiry job by hand."""
            svc = svc_for(user)
            svc.require_owner(user.email)
            return svc.expire_due_grants().as_dict()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
