"""Settings from environment variables. Locally: uvicorn ... --env-file .env"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    store_backend: str = "memory"  # memory | firestore
    auth_mode: str = "firebase"  # firebase | demo  (fails closed: firebase is the default)
    allow_demo_auth_on_cloud_run: bool = False
    running_on_cloud_run: bool = False

    workspace_id: str = "bloom-and-crumb"
    workspace_name: str = "Bloom & Crumb"
    owner_email: str = "owner@bloomandcrumb.test"
    default_timezone: str = "America/Chicago"
    invite_ttl_hours: int = 72

    nvidia_api_key: str = ""
    nvidia_model: str = "nvidia/nemotron-3-super-120b-a12b"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_timeout_seconds: float = 15.0

    scheduler_audience: str = ""  # the Cloud Run service URL
    scheduler_service_account: str = ""  # email of the Cloud Scheduler service account

    firebase_project_id: str = ""
    firebase_api_key: str = ""  # public web config, not a secret
    firebase_auth_domain: str = ""
    firebase_auth_emulator_host: str = ""  # local Floci only, e.g. localhost:4588

    gcp_project: str = ""  # GOOGLE_CLOUD_PROJECT (floci-local when using Floci)

    # Newly (or any server-side integration) calls with a shared key from Secret Manager.
    integration_api_key: str = ""
    integration_name: str = "newly"
    integration_allow_owner: bool = False  # least privilege: off unless the team decides otherwise

    cors_allowed_origins: tuple[str, ...] = ()

    @property
    def assistant_enabled(self) -> bool:
        return bool(self.nvidia_api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            store_backend=e("STORE_BACKEND", "memory").strip().lower(),
            auth_mode=e("AUTH_MODE", "firebase").strip().lower(),
            allow_demo_auth_on_cloud_run=_bool("ALLOW_DEMO_AUTH_ON_CLOUD_RUN"),
            running_on_cloud_run=bool(e("K_SERVICE")),
            workspace_id=e("WORKSPACE_ID", cls.workspace_id),
            workspace_name=e("WORKSPACE_NAME", cls.workspace_name),
            owner_email=e("OWNER_EMAIL", cls.owner_email).strip().lower(),
            default_timezone=e("DEFAULT_TIMEZONE", cls.default_timezone),
            invite_ttl_hours=int(e("INVITE_TTL_HOURS", str(cls.invite_ttl_hours))),
            nvidia_api_key=e("NVIDIA_API_KEY", "").strip(),
            nvidia_model=e("NVIDIA_MODEL", cls.nvidia_model).strip(),
            nvidia_base_url=e("NVIDIA_BASE_URL", cls.nvidia_base_url).rstrip("/"),
            nvidia_timeout_seconds=float(e("NVIDIA_TIMEOUT_SECONDS", str(cls.nvidia_timeout_seconds))),
            scheduler_audience=e("SCHEDULER_AUDIENCE", "").strip(),
            scheduler_service_account=e("SCHEDULER_SERVICE_ACCOUNT", "").strip().lower(),
            firebase_project_id=e("FIREBASE_PROJECT_ID", e("GOOGLE_CLOUD_PROJECT", "")).strip(),
            firebase_api_key=e("FIREBASE_API_KEY", "").strip(),
            firebase_auth_domain=e("FIREBASE_AUTH_DOMAIN", "").strip(),
            firebase_auth_emulator_host=e("FIREBASE_AUTH_EMULATOR_HOST", "").strip(),
            gcp_project=e("GOOGLE_CLOUD_PROJECT", "").strip(),
            integration_api_key=e("INTEGRATION_API_KEY", "").strip(),
            integration_name=e("INTEGRATION_NAME", "newly").strip().lower() or "newly",
            integration_allow_owner=_bool("INTEGRATION_ALLOW_OWNER"),
            cors_allowed_origins=tuple(o.strip() for o in e("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()),
        )

    def check_safe(self) -> None:
        """Refuse to start in an unsafe configuration."""
        if self.auth_mode not in {"firebase", "demo"}:
            raise RuntimeError(f"AUTH_MODE must be 'firebase' or 'demo', not {self.auth_mode!r}")
        if self.auth_mode == "demo" and self.running_on_cloud_run and not self.allow_demo_auth_on_cloud_run:
            raise RuntimeError(
                "AUTH_MODE=demo lets anyone pick an identity with a header. It is blocked on Cloud Run "
                "unless ALLOW_DEMO_AUTH_ON_CLOUD_RUN=true is set on purpose (hackathon demo only)."
            )
        if self.integration_api_key and len(self.integration_api_key) < 32:
            raise RuntimeError("INTEGRATION_API_KEY must be at least 32 random characters (python -c \"import secrets; print(secrets.token_urlsafe(32))\")")
        if "*" in self.cors_allowed_origins:
            raise RuntimeError("CORS_ALLOWED_ORIGINS must list exact origins, not '*'")
        if self.firebase_auth_emulator_host and self.running_on_cloud_run:
            raise RuntimeError("FIREBASE_AUTH_EMULATOR_HOST accepts unsigned tokens and must never be set on Cloud Run")
        if self.store_backend == "memory" and self.running_on_cloud_run:
            # Allowed for a quick demo, but every instance would hold its own data.
            import logging

            logging.getLogger("roleready").warning(
                "STORE_BACKEND=memory on Cloud Run: data resets on restart. Set --max-instances 1 or use firestore."
            )
