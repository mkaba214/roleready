"""scripts/iam.py plan/apply logic, against an in-memory stand-in for the Google REST APIs.
(The real enforcement checks live in test_floci_enforcement.py and need a running Floci.)"""

from __future__ import annotations

import copy
import itertools
import json
import re
from urllib.parse import urlparse

import pytest

from scripts.iam import Cloud, CloudError, apply_plan, load_spec, make_plan

TEAM = {"mohamed": "m@example.test", "andrew": "a@example.test", "ashley": "s@example.test", "joclyn": "j@example.test"}


class FakeResponse:
    def __init__(self, status: int, data: dict | None = None) -> None:
        self.status_code = status
        self._data = data or {}
        self.text = json.dumps(self._data) if data is not None else ""

    def json(self) -> dict:
        return self._data


class FakeGoogle:
    """Just enough IAM, Resource Manager and Secret Manager to exercise scripts/iam.py."""

    def __init__(self) -> None:
        self.sas: set[str] = set()
        self.secrets: set[str] = set()
        self.policies: dict[str, dict] = {}
        self.etags = itertools.count(1)
        self.calls: list[tuple[str, str, dict | None]] = []

    def _policy(self, resource: str) -> dict:
        return self.policies.setdefault(resource, {"bindings": [], "etag": f"e{next(self.etags)}"})

    def request(self, method, url, headers=None, timeout=None, params=None, json=None):  # noqa: A002
        path = urlparse(url).path
        self.calls.append((method, path, json))
        if m := re.fullmatch(r"(/v1/projects/[^/:]+(?:/(?:secrets|serviceAccounts)/[^/:]+)?):(getIamPolicy|setIamPolicy)", path):
            resource, verb = m.groups()
            if "/secrets/" in resource and resource.rsplit("/", 1)[-1] not in self.secrets:
                return FakeResponse(404, {"error": {"message": "secret not found"}})
            if "/serviceAccounts/" in resource and resource.rsplit("/", 1)[-1].split("@")[0] not in self.sas:
                return FakeResponse(404, {"error": {"message": "sa not found"}})
            current = self._policy(resource)
            if verb == "getIamPolicy":
                return FakeResponse(200, copy.deepcopy(current))
            new = copy.deepcopy(json["policy"])
            if new.get("etag") != current["etag"]:
                return FakeResponse(409, {"error": {"message": "etag mismatch"}})
            new["etag"] = f"e{next(self.etags)}"
            self.policies[resource] = new
            return FakeResponse(200, copy.deepcopy(new))
        if re.fullmatch(r"/v1/projects/[^/]+/serviceAccounts", path) and method == "POST":
            self.sas.add(json["accountId"])
            return FakeResponse(200, {"email": json["accountId"]})
        if m := re.fullmatch(r"/v1/projects/[^/]+/serviceAccounts/([^/:@]+)@[^/:]+/keys", path):
            return FakeResponse(200, {"keys": []})
        if m := re.fullmatch(r"/v1/projects/[^/]+/serviceAccounts/([^/:@]+)@[^/:]+", path):
            return FakeResponse(200, {"email": m.group(1)}) if m.group(1) in self.sas else FakeResponse(404, {"error": {"message": "nope"}})
        if re.fullmatch(r"/v1/projects/[^/]+/secrets", path) and method == "POST":
            self.secrets.add(params["secretId"])
            return FakeResponse(200, {"name": params["secretId"]})
        if m := re.fullmatch(r"/v1/projects/[^/]+/secrets/([^/:]+):addVersion", path):
            return FakeResponse(200, {"name": f"{m.group(1)}/versions/1"})
        if m := re.fullmatch(r"/v1/projects/[^/]+/secrets/([^/:]+)", path):
            return FakeResponse(200, {"name": m.group(1)}) if m.group(1) in self.secrets else FakeResponse(404, {"error": {"message": "nope"}})
        return FakeResponse(404, {"error": {"message": f"no route {method} {path}"}})


@pytest.fixture
def spec() -> dict:
    return load_spec()


def floci(fake: FakeGoogle) -> Cloud:
    return Cloud("floci", "demo", session=fake)


def gcp(fake: FakeGoogle) -> Cloud:
    return Cloud("gcp", "demo", token="t", session=fake)


def test_floci_apply_then_plan_is_empty(spec) -> None:
    fake = FakeGoogle()
    plan = make_plan(floci(fake), spec, {})
    assert set(plan.create_sas) == {"roleready-run", "roleready-scheduler", "roleready-export",
                                    "person-mohamed", "person-andrew", "person-ashley", "person-joclyn"}
    assert set(plan.missing_secrets) == {"nvidia-api-key", "roleready-integration-key"}
    apply_plan(floci(fake), spec, plan)
    again = make_plan(floci(fake), spec, {})
    assert again.changes == 0 and again.findings == 0


def test_people_become_stand_in_accounts_on_floci_and_users_on_gcp(spec) -> None:
    fake = FakeGoogle()
    apply_plan(floci(fake), spec, make_plan(floci(fake), spec, {}))
    members = {m for b in fake.policies["/v1/projects/demo"]["bindings"] for m in b["members"]}
    assert "serviceAccount:person-andrew@demo.iam.gserviceaccount.com" in members

    fake2 = FakeGoogle()
    fake2.sas |= {"roleready-run", "roleready-scheduler", "roleready-export"}
    fake2.secrets |= {"nvidia-api-key", "roleready-integration-key"}
    apply_plan(gcp(fake2), spec, make_plan(gcp(fake2), spec, TEAM))
    members2 = {m for b in fake2.policies["/v1/projects/demo"]["bindings"] for m in b["members"]}
    assert "user:a@example.test" in members2 and not any("person-" in m for m in members2)


def test_gcp_needs_team_emails(spec) -> None:
    with pytest.raises(SystemExit, match="team.local.yaml"):
        make_plan(gcp(FakeGoogle()), spec, {})


def test_people_bindings_are_time_boxed_with_policy_version_3(spec) -> None:
    fake = FakeGoogle()
    apply_plan(floci(fake), spec, make_plan(floci(fake), spec, {}))
    project = fake.policies["/v1/projects/demo"]
    assert project["version"] == 3
    andrew = [b for b in project["bindings"] if any("person-andrew" in m for m in b["members"])]
    assert andrew and all(b["condition"]["expression"] == "request.time < timestamp('2026-12-01T00:00:00Z')" for b in andrew)
    run = [b for b in project["bindings"] if any(m.startswith("serviceAccount:roleready-run") for m in b["members"])]
    assert run and all("condition" not in b for b in run)


def test_apply_is_additive_and_reports_drift(spec) -> None:
    fake = FakeGoogle()
    fake.policies["/v1/projects/demo"] = {"etag": "e0", "bindings": [
        {"role": "roles/owner", "members": ["user:founder@example.test"]},
        {"role": "roles/datastore.user", "members": ["user:stranger@example.test"]},
    ]}
    apply_plan(floci(fake), spec, make_plan(floci(fake), spec, {}))
    roles = {b["role"]: b["members"] for b in fake.policies["/v1/projects/demo"]["bindings"]}
    assert roles["roles/owner"] == ["user:founder@example.test"]  # never touched
    plan = make_plan(floci(fake), spec, {})
    project = next(r for r in plan.resources if r.kind == "project")
    assert ("roles/datastore.user", "user:stranger@example.test", "") in project.drift  # reported, not removed


def test_dangerous_bindings_are_flagged(spec) -> None:
    fake = FakeGoogle()
    fake.policies["/v1/projects/demo"] = {"etag": "e0", "bindings": [
        {"role": "roles/editor", "members": ["serviceAccount:ci@demo.iam.gserviceaccount.com"]},
        {"role": "roles/logging.viewer", "members": ["allUsers"]},
    ]}
    project = next(r for r in make_plan(floci(fake), spec, {}).resources if r.kind == "project")
    assert any("service account" in d for d in project.danger)
    assert any("allUsers" in d for d in project.danger)


def test_gcp_never_creates_secret_values_and_turns_on_data_access_logs(spec) -> None:
    fake = FakeGoogle()
    fake.sas |= {"roleready-run", "roleready-scheduler", "roleready-export"}
    fake.secrets.add("nvidia-api-key")  # integration key not created yet
    plan = make_plan(gcp(fake), spec, TEAM)
    assert plan.missing_secrets == ["roleready-integration-key"]
    project = next(r for r in plan.resources if r.kind == "project")
    assert project.missing_audit_logs == ["secretmanager.googleapis.com"]
    done = apply_plan(gcp(fake), spec, plan)
    assert "roleready-integration-key" not in fake.secrets
    assert any("SKIPPED secret roleready-integration-key" in d for d in done)
    sets = [body for method, path, body in fake.calls if path == "/v1/projects/demo:setIamPolicy"]
    assert sets[-1]["updateMask"] == "auditConfigs,bindings,etag"
    audit = fake.policies["/v1/projects/demo"]["auditConfigs"]
    assert audit == [{"service": "secretmanager.googleapis.com", "auditLogConfigs": [{"logType": "DATA_READ"}]}]


def test_concurrent_edit_fails_instead_of_overwriting(spec) -> None:
    fake = FakeGoogle()
    plan = make_plan(floci(fake), spec, {})
    fake.policies["/v1/projects/demo"]["etag"] = "changed-by-someone-else"
    with pytest.raises(CloudError, match="409"):
        apply_plan(floci(fake), spec, plan)
