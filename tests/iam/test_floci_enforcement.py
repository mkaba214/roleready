"""Prove least privilege against Floci with IAM enforcement ON.

  docker compose up -d floci-gcp        # docker-compose.yml turns on enforce mode
  FLOCI_GCP_URL=http://localhost:4588 pytest tests/iam -v

Skipped unless FLOCI_GCP_URL is set. Each run uses a fresh project id, so runs never collide.
Floci is a local test tool, not a security boundary: these tests show the POLICY is right.
The same policy is then applied to real Google Cloud with scripts/iam.py.
"""

from __future__ import annotations

import os
import secrets

import pytest

from scripts.iam import Cloud, CloudError, apply_plan, load_spec, make_plan

FLOCI = os.environ.get("FLOCI_GCP_URL")
pytestmark = pytest.mark.skipif(not FLOCI, reason="set FLOCI_GCP_URL=http://localhost:4588 with Floci running")


@pytest.fixture(scope="module")
def cloud() -> Cloud:
    c = Cloud("floci", f"rr-iam-{secrets.token_hex(3)}", floci_url=FLOCI)
    spec = load_spec()
    apply_plan(c, spec, make_plan(c, spec, {}))
    return c


def who(name: str) -> str:
    return name if name.startswith("roleready-") else f"person-{name}"


def status(cloud: Cloud, as_name: str, method: str, service: str, path: str, **kw) -> int:
    token = cloud.mint_token(cloud.sa_email(who(as_name)))
    try:
        cloud.call(method, service, path.format(p=cloud.project), token=token, **kw)
        return 200
    except CloudError as e:
        return e.status


def read_key(cloud: Cloud, as_name: str, secret: str = "nvidia-api-key") -> int:
    return status(cloud, as_name, "GET", "secrets", "/v1/projects/{p}/secrets/" + secret + "/versions/latest:access")


def test_enforcement_is_on(cloud) -> None:
    assert read_key(cloud, "roleready-scheduler") == 403, (
        "Floci let an unauthorized account read a secret. Start Floci with "
        "FLOCI_GCP_SERVICES_IAM_AUTHORIZATION_MODE=enforce (docker-compose.yml does this)."
    )


def test_run_service_reads_both_secrets(cloud) -> None:
    assert read_key(cloud, "roleready-run") == 200
    assert read_key(cloud, "roleready-run", "roleready-integration-key") == 200


@pytest.mark.parametrize("name", ["roleready-scheduler", "roleready-export", "mohamed", "joclyn"])
def test_nobody_else_reads_the_nvidia_key(cloud, name) -> None:
    assert read_key(cloud, name) == 403


def test_security_admin_can_rotate_the_key(cloud) -> None:
    assert status(cloud, "andrew", "POST", "secrets", "/v1/projects/{p}/secrets/nvidia-api-key:addVersion",
                  json={"payload": {"data": "cm90YXRlZA=="}}) == 200


@pytest.mark.parametrize(
    "method, service, path, body",
    [
        ("POST", "secrets", "/v1/projects/{p}/secrets/nvidia-api-key:addVersion", {"payload": {"data": "eA=="}}),
        ("POST", "secrets", "/v1/projects/{p}/secrets/nvidia-api-key:setIamPolicy", {"policy": {"bindings": []}}),
        ("POST", "crm", "/v1/projects/{p}:setIamPolicy", {"policy": {"bindings": []}}),
    ],
)
def test_run_service_cannot_escalate(cloud, method, service, path, body) -> None:
    assert status(cloud, "roleready-run", method, service, path, json=body) == 403


def test_only_the_iam_admin_can_change_project_iam(cloud) -> None:
    current = cloud.get_policy("project", "")
    assert status(cloud, "joclyn", "POST", "crm", "/v1/projects/{p}:setIamPolicy", json={"policy": current}) == 403
    assert status(cloud, "mohamed", "POST", "crm", "/v1/projects/{p}:setIamPolicy", json={"policy": current}) == 403
    assert status(cloud, "andrew", "POST", "crm", "/v1/projects/{p}:setIamPolicy", json={"policy": current}) == 200


@pytest.mark.parametrize("name", ["roleready-scheduler", "mohamed", "andrew", "joclyn"])
def test_nobody_can_impersonate_the_run_service(cloud, name) -> None:
    target = cloud.sa_email("roleready-run")
    assert status(cloud, name, "POST", "iamcredentials", f"/v1/projects/-/serviceAccounts/{target}:generateAccessToken",
                  json={"scope": ["https://www.googleapis.com/auth/cloud-platform"]}) == 403


@pytest.mark.parametrize("name", ["mohamed", "andrew"])
def test_nobody_can_create_service_account_keys(cloud, name) -> None:
    target = cloud.sa_email("roleready-run")
    assert status(cloud, name, "POST", "iam", f"/v1/projects/{{p}}/serviceAccounts/{target}/keys", json={}) == 403


def test_time_boxed_grant_stops_working_after_it_expires(cloud) -> None:
    """The same rule RoleReady enforces for freelancers, applied to cloud access."""
    cloud.create_sa("person-contractor", "Former contractor (test)")
    policy = cloud.get_policy("secret", "nvidia-api-key")
    member = f"serviceAccount:{cloud.sa_email('person-contractor')}"
    policy["version"] = 3
    policy.setdefault("bindings", []).append({
        "role": "roles/secretmanager.secretAccessor", "members": [member],
        "condition": {"title": "ended", "expression": "request.time < timestamp('2026-10-31T00:00:00Z')"},
    })
    cloud.set_policy("secret", "nvidia-api-key", policy)
    assert read_key(cloud, "person-contractor") == 403

    policy = cloud.get_policy("secret", "nvidia-api-key")
    policy["bindings"].append({
        "role": "roles/secretmanager.secretAccessor", "members": [member],
        "condition": {"title": "current", "expression": "request.time < timestamp('2030-01-01T00:00:00Z')"},
    })
    cloud.set_policy("secret", "nvidia-api-key", policy)
    assert read_key(cloud, "person-contractor") == 200
