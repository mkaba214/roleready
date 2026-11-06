"""Who is calling?

firebase mode: the browser signs in with Firebase Authentication and sends
  "Authorization: Bearer <Firebase ID token>". The server verifies the token.
demo mode: the caller picks an identity with the X-Demo-User header. Local
  development and tests only. Blocked on Cloud Run unless explicitly allowed.
integration (any mode, off unless INTEGRATION_API_KEY is set): a trusted
  server, such as the Newly Backend, sends X-RoleReady-Integration-Key plus
  X-Acting-User. The integration signs its own users in; RoleReady still
  applies every permission rule to the acting user, tags the audit trail with
  the channel, and (by default) refuses owner actions over the integration.

/jobs/expire accepts only a Google-signed OIDC token from the Cloud Scheduler
service account. Without that configuration the endpoint refuses every call.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from .config import Settings
from .models import EMAIL_RE

log = logging.getLogger("roleready")

INTEGRATION_KEY_HEADER = "x-roleready-integration-key"
ACTING_USER_HEADER = "x-acting-user"


@dataclass(frozen=True)
class User:
    email: str
    uid: str
    via: str = "web"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        return token or None
    return None


@lru_cache(maxsize=1)
def _firebase_app(project_id: str):
    import firebase_admin

    options = {"projectId": project_id} if project_id else None
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options=options)


def _integration_user(request: Request, settings: Settings, key: str) -> User:
    if not settings.integration_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "integration access is not enabled")
    if not hmac.compare_digest(key.encode("utf-8"), settings.integration_api_key.encode("utf-8")):
        log.warning("integration key rejected")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid integration key")
    email = request.headers.get(ACTING_USER_HEADER, "").strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "integration calls must name the acting user (X-Acting-User)")
    name = settings.integration_name
    return User(email=email, uid=f"{name}:{email}", via=name)


def get_current_user(request: Request, settings: Settings = Depends(get_settings)) -> User:
    integration_key = request.headers.get(INTEGRATION_KEY_HEADER)
    if integration_key is not None:
        return _integration_user(request, settings, integration_key)

    if settings.auth_mode == "demo":
        email = request.headers.get("x-demo-user", "").strip().lower()
        if not email or not EMAIL_RE.match(email):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in first (demo mode: send X-Demo-User)")
        return User(email=email, uid=f"demo:{email}")

    token = _bearer(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        from firebase_admin import auth as fb_auth

        claims = fb_auth.verify_id_token(token, app=_firebase_app(settings.firebase_project_id))
    except Exception as exc:  # invalid, expired or forged token (or a setup problem: check the log)
        log.warning("firebase token rejected: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired sign-in token") from None
    email = str(claims.get("email", "")).lower()
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token has no email claim")
    return User(email=email, uid=str(claims.get("uid") or claims.get("sub")))


def verify_scheduler(request: Request, settings: Settings = Depends(get_settings)) -> str:
    """Only Cloud Scheduler, signing as its own service account, may run the expiry job."""
    if not settings.scheduler_audience or not settings.scheduler_service_account:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "expiry job auth is not configured")
    token = _bearer(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing OIDC token")
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(token, g_requests.Request(), audience=settings.scheduler_audience)
    except Exception as exc:
        log.warning("scheduler OIDC token rejected: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid OIDC token") from None
    caller = str(claims.get("email", "")).lower()
    if not claims.get("email_verified") or caller != settings.scheduler_service_account:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "caller is not the scheduler service account")
    return caller
