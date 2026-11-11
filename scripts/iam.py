"""RoleReady IAM as code: lint, plan, apply and audit infra/iam/iam.yaml.

Targets
  floci  Floci's Google Cloud emulator (default http://localhost:4588). Teammates become
         stand-in service accounts (person-<name>) because Floci can only issue
         service-account credentials. Start Floci with IAM enforcement ON (docker-compose.yml).
  gcp    The real project. Uses your gcloud sign-in: gcloud auth print-access-token.

Commands
  lint                      least-privilege rules on the YAML, no network (CI runs this)
  plan   --target T         show what apply would add, plus drift and dangerous bindings
  apply  --target T         create missing service accounts and add missing bindings (additive)
  audit  --target gcp       plan + user-managed key check; exits 1 on any finding (weekly review)
  token  --target floci --as NAME   print a Floci access token for a service account or person

Safety
  * Apply only ADDS. It never removes a binding: drift is reported, and you remove it by hand
    after review (gcloud ... remove-iam-policy-binding), so a typo cannot lock the team out.
  * Every write uses the policy etag (read-modify-write), so concurrent edits fail instead of clobbering.
  * Secret VALUES are never created on gcp. infra/setup.sh does that (the optional integration key is created by hand with gcloud secrets create).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "infra" / "iam" / "iam.yaml"
TEAM_PATH = ROOT / "infra" / "iam" / "team.local.yaml"
FLOCI_DEFAULT = "http://localhost:4588"
GCP_BASES = {
    "iam": "https://iam.googleapis.com",
    "crm": "https://cloudresourcemanager.googleapis.com",
    "secrets": "https://secretmanager.googleapis.com",
    "iamcredentials": "https://iamcredentials.googleapis.com",
}
CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"

# --- Least-privilege rules ------------------------------------------------------------
BASIC_ROLES = {"roles/owner", "roles/editor", "roles/viewer"}
PUBLIC_MEMBERS = {"allUsers", "allAuthenticatedUsers"}
# Roles that let a holder become a service account or mint its credentials.
ESCALATION_ROLES = {
    "roles/iam.serviceAccountTokenCreator",
    "roles/iam.serviceAccountKeyAdmin",
    "roles/iam.workloadIdentityUser",
}
# The only project roles each workload may hold.
SA_PROJECT_ROLE_ALLOWLIST = {
    "roleready-run": {"roles/datastore.user"},
    "roleready-scheduler": set(),
    "roleready-export": {"roles/datastore.viewer", "roles/bigquery.jobUser", "roles/bigquery.dataEditor"},
}
# Separation of duties: nobody may both rewrite IAM and deploy code.
SOD_CONFLICTS = [("roles/resourcemanager.projectIamAdmin", "roles/run.admin")]
SECRET_ACCESSOR = "roles/secretmanager.secretAccessor"
ALLOWED_SECRET_ACCESSORS = {"sa:roleready-run"}


@dataclass(frozen=True)
class Binding:
    kind: str  # project | secret | sa
    resource: str  # "" for project, secret id, or service account short name
    role: str
    member: str  # spec form: sa:<name> or person:<name>
    expires: str | None


def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def load_team(path: Path = TEAM_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return {str(k): str(v).strip().lower() for k, v in data.items()}


def expand(spec: dict[str, Any]) -> list[Binding]:
    """Flatten the YAML into one Binding per (resource, role, member). People expire at build_ends."""
    out: list[Binding] = []
    build_ends = spec["build_ends"]

    def entries(kind: str, resource: str, items: Iterable[dict[str, Any]]) -> None:
        for item in items or []:
            member = item["member"]
            if "expires" in item:
                expires = None if item["expires"] in (None, "none") else str(item["expires"])
            else:
                expires = build_ends if member.startswith("person:") else None
            for role in item["roles"]:
                out.append(Binding(kind, resource, role, member, expires))

    entries("project", "", spec.get("project_bindings"))
    for secret, items in (spec.get("secret_bindings") or {}).items():
        entries("secret", secret, items)
    for sa, items in (spec.get("service_account_bindings") or {}).items():
        entries("sa", sa, items)
    return out


def lint(spec: dict[str, Any]) -> list[str]:
    """Return every least-privilege violation. Empty list = clean."""
    errors: list[str] = []
    sas = set((spec.get("service_accounts") or {}).keys())
    team = set((spec.get("team") or {}).keys())
    bindings = expand(spec)

    try:
        ends = datetime.fromisoformat(str(spec["build_ends"]).replace("Z", "+00:00"))
        if ends.tzinfo is None:
            errors.append("build_ends must include a UTC offset, e.g. 2026-12-01T00:00:00Z")
    except (KeyError, ValueError):
        errors.append("build_ends must be an ISO 8601 timestamp")

    for name, info in (spec.get("team") or {}).items():
        if not (info or {}).get("lead_for"):
            errors.append(f"team.{name} needs a lead_for description (why they need access)")
    for name, info in (spec.get("service_accounts") or {}).items():
        if not (info or {}).get("purpose"):
            errors.append(f"service_accounts.{name} needs a purpose")
        if name not in SA_PROJECT_ROLE_ALLOWLIST:
            errors.append(f"service account {name} has no entry in SA_PROJECT_ROLE_ALLOWLIST (scripts/iam.py)")

    for b in bindings:
        where = f"{b.kind}:{b.resource or 'project'} {b.role} -> {b.member}"
        kind, _, name = b.member.partition(":")
        if kind not in ("sa", "person") or not name:
            errors.append(f"{where}: member must be sa:<name> or person:<name>")
            continue
        if b.member in PUBLIC_MEMBERS or name in PUBLIC_MEMBERS:
            errors.append(f"{where}: public access is never allowed")
        if kind == "sa" and name not in sas:
            errors.append(f"{where}: unknown service account {name}")
        if kind == "person" and name not in team:
            errors.append(f"{where}: unknown teammate {name}")
        if b.role in BASIC_ROLES:
            errors.append(f"{where}: basic roles (owner/editor/viewer) are too broad; pick predefined roles")
        if b.role in ESCALATION_ROLES:
            errors.append(f"{where}: {b.role} lets the holder impersonate or mint keys; not allowed")
        if kind == "person" and b.expires is None:
            errors.append(f"{where}: people's access must expire (set expires or rely on build_ends)")
        if b.role == "roles/iam.serviceAccountUser" and b.kind != "sa":
            errors.append(f"{where}: grant serviceAccountUser on one service account, never project-wide")
        if b.role == SECRET_ACCESSOR and b.member not in ALLOWED_SECRET_ACCESSORS:
            errors.append(f"{where}: only the Cloud Run service account may read secret values")
        if b.role == SECRET_ACCESSOR and b.kind == "project":
            errors.append(f"{where}: grant secretAccessor on each secret, not project-wide")
        if kind == "sa" and b.kind == "project" and b.role not in SA_PROJECT_ROLE_ALLOWLIST.get(name, set()):
            errors.append(f"{where}: {name} may only hold {sorted(SA_PROJECT_ROLE_ALLOWLIST.get(name, set())) or 'no project roles'}")
        if b.kind == "sa" and b.resource not in sas:
            errors.append(f"{where}: unknown service account resource {b.resource}")

    roles_by_member: dict[str, set[str]] = {}
    for b in bindings:
        roles_by_member.setdefault(b.member, set()).add(b.role)
    for member, roles in roles_by_member.items():
        for a, c in SOD_CONFLICTS:
            if a in roles and c in roles:
                errors.append(f"{member}: separation of duties, cannot hold both {a} and {c}")
    return errors


# --- Talking to Floci or Google Cloud ---------------------------------------------------
class CloudError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class Cloud:
    """The handful of IAM, Resource Manager, Secret Manager and IAM Credentials REST calls we need.
    Same paths on Floci and Google; only the base URL and the token differ."""

    def __init__(self, target: str, project: str, *, floci_url: str = FLOCI_DEFAULT,
                 token: str | None = None, session: Any = None) -> None:
        if target not in ("floci", "gcp"):
            raise ValueError("target must be floci or gcp")
        self.target, self.project = target, project
        self.floci_url = floci_url.rstrip("/")
        self.token = token
        self.http = session or requests.Session()

    def base(self, service: str) -> str:
        return self.floci_url if self.target == "floci" else GCP_BASES[service]

    def call(self, method: str, service: str, path: str, *, token: str | None = None, **kw: Any) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        bearer = token or self.token
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        r = self.http.request(method, self.base(service) + path, headers=headers, timeout=30, **kw)
        if r.status_code >= 400:
            try:
                message = r.json().get("error", {}).get("message") or r.text[:300]
            except ValueError:
                message = r.text[:300]
            raise CloudError(r.status_code, message)
        return r.json() if r.text.strip() else {}

    def sa_email(self, name: str) -> str:
        return f"{name}@{self.project}.iam.gserviceaccount.com"

    # Service accounts
    def sa_exists(self, name: str) -> bool:
        try:
            self.call("GET", "iam", f"/v1/projects/{self.project}/serviceAccounts/{self.sa_email(name)}")
            return True
        except CloudError as e:
            if e.status in (403, 404):
                return False
            raise

    def create_sa(self, name: str, display_name: str) -> None:
        self.call("POST", "iam", f"/v1/projects/{self.project}/serviceAccounts",
                  json={"accountId": name, "serviceAccount": {"displayName": display_name[:100]}})

    def user_managed_keys(self, name: str) -> list[dict[str, Any]]:
        data = self.call("GET", "iam", f"/v1/projects/{self.project}/serviceAccounts/{self.sa_email(name)}/keys",
                         params={"keyTypes": "USER_MANAGED"})
        return data.get("keys", [])

    # Secrets
    def secret_exists(self, secret: str) -> bool:
        try:
            self.call("GET", "secrets", f"/v1/projects/{self.project}/secrets/{secret}")
            return True
        except CloudError as e:
            if e.status == 404:
                return False
            raise

    def create_secret(self, secret: str, value: bytes) -> None:
        import base64

        self.call("POST", "secrets", f"/v1/projects/{self.project}/secrets", params={"secretId": secret},
                  json={"replication": {"automatic": {}}})
        self.call("POST", "secrets", f"/v1/projects/{self.project}/secrets/{secret}:addVersion",
                  json={"payload": {"data": base64.b64encode(value).decode()}})

    # Policies
    def _policy_path(self, kind: str, resource: str) -> tuple[str, str]:
        if kind == "project":
            return "crm", f"/v1/projects/{self.project}"
        if kind == "secret":
            return "secrets", f"/v1/projects/{self.project}/secrets/{resource}"
        if kind == "sa":
            return "iam", f"/v1/projects/{self.project}/serviceAccounts/{self.sa_email(resource)}"
        raise ValueError(kind)

    def get_policy(self, kind: str, resource: str) -> dict[str, Any]:
        service, path = self._policy_path(kind, resource)
        if kind == "secret":
            return self.call("GET", service, f"{path}:getIamPolicy", params={"options.requestedPolicyVersion": 3})
        if kind == "sa":
            return self.call("POST", service, f"{path}:getIamPolicy", params={"options.requestedPolicyVersion": 3})
        return self.call("POST", service, f"{path}:getIamPolicy", json={"options": {"requestedPolicyVersion": 3}})

    def set_policy(self, kind: str, resource: str, policy: dict[str, Any]) -> dict[str, Any]:
        service, path = self._policy_path(kind, resource)
        body: dict[str, Any] = {"policy": policy}
        if kind == "project" and self.target == "gcp" and "auditConfigs" in policy:
            body["updateMask"] = "auditConfigs,bindings,etag"
        return self.call("POST", service, f"{path}:setIamPolicy", json=body)

    # Floci only: credentials for testing as a given identity
    def mint_token(self, sa_email: str) -> str:
        data = self.call("POST", "iamcredentials", f"/v1/projects/-/serviceAccounts/{sa_email}:generateAccessToken",
                         json={"scope": [CLOUD_PLATFORM], "lifetime": "900s"})
        return data["accessToken"]


# --- Plan ---------------------------------------------------------------------------------
def resolve_member(member: str, target: str, project: str, team: dict[str, str]) -> str:
    kind, _, name = member.partition(":")
    if kind == "sa":
        return f"serviceAccount:{name}@{project}.iam.gserviceaccount.com"
    if kind == "person":
        if target == "floci":
            return f"serviceAccount:person-{name}@{project}.iam.gserviceaccount.com"
        email = team.get(name)
        if not email:
            raise SystemExit(f"No email for {member}. Copy infra/iam/team.local.example.yaml to infra/iam/team.local.yaml.")
        return f"user:{email}"
    raise ValueError(member)


def condition_for(expires: str | None) -> dict[str, str] | None:
    if not expires:
        return None
    return {
        "title": f"expires-{expires[:10]}",
        "description": "Time-boxed BUILD access, managed by infra/iam/iam.yaml",
        "expression": f"request.time < timestamp('{expires}')",
    }


def _cond_key(cond: dict[str, Any] | None) -> str:
    return (cond or {}).get("expression", "")


@dataclass
class ResourcePlan:
    kind: str
    resource: str
    add: list[tuple[str, str, dict | None]] = field(default_factory=list)  # (role, member, condition)
    drift: list[tuple[str, str, str]] = field(default_factory=list)  # (role, member, condition expr)
    danger: list[str] = field(default_factory=list)
    missing_audit_logs: list[str] = field(default_factory=list)
    policy: dict[str, Any] | None = None


@dataclass
class Plan:
    target: str
    project: str
    create_sas: list[str] = field(default_factory=list)
    missing_secrets: list[str] = field(default_factory=list)
    resources: list[ResourcePlan] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)

    @property
    def changes(self) -> int:
        return len(self.create_sas) + sum(len(r.add) + len(r.missing_audit_logs) for r in self.resources)

    @property
    def findings(self) -> int:
        return (len(self.missing_secrets) + len(self.key_findings)
                + sum(len(r.drift) + len(r.danger) for r in self.resources))


def desired(spec: dict[str, Any], target: str, project: str, team: dict[str, str]) -> dict[tuple[str, str], list[tuple[str, str, dict | None]]]:
    out: dict[tuple[str, str], list[tuple[str, str, dict | None]]] = {}
    for b in expand(spec):
        out.setdefault((b.kind, b.resource), []).append(
            (b.role, resolve_member(b.member, target, project, team), condition_for(b.expires)))
    return out


def dangerous_bindings(policy: dict[str, Any]) -> list[str]:
    found = []
    for b in policy.get("bindings", []):
        for m in b.get("members", []):
            if m in PUBLIC_MEMBERS:
                found.append(f"{b['role']} granted to {m}")
            if m.startswith("serviceAccount:") and b["role"] in {"roles/owner", "roles/editor"}:
                found.append(f"{b['role']} granted to service account {m}")
            if b["role"] in ESCALATION_ROLES:
                found.append(f"{b['role']} granted to {m} (can impersonate or mint keys)")
    return found


def make_plan(cloud: Cloud, spec: dict[str, Any], team: dict[str, str]) -> Plan:
    plan = Plan(cloud.target, cloud.project)
    wanted_sas = list((spec.get("service_accounts") or {}).keys())
    if cloud.target == "floci":
        wanted_sas += [f"person-{name}" for name in (spec.get("team") or {})]
    plan.create_sas = [sa for sa in wanted_sas if not cloud.sa_exists(sa)]
    secrets = list((spec.get("secret_bindings") or {}).keys())
    plan.missing_secrets = [s for s in secrets if not cloud.secret_exists(s)]

    for (kind, resource), wants in desired(spec, cloud.target, cloud.project, team).items():
        rp = ResourcePlan(kind, resource)
        missing_resource = (kind == "secret" and resource in plan.missing_secrets) or (
            kind == "sa" and resource in plan.create_sas)
        policy = {"bindings": []} if missing_resource else cloud.get_policy(kind, resource)
        rp.policy = policy
        have = {(b["role"], m, _cond_key(b.get("condition")))
                for b in policy.get("bindings", []) for m in b.get("members", [])}
        want_keys = {(role, m, _cond_key(c)) for role, m, c in wants}
        rp.add = [(role, m, c) for role, m, c in wants if (role, m, _cond_key(c)) not in have]
        managed_roles = {role for role, _, _ in wants}
        rp.drift = sorted(k for k in have if k[0] in managed_roles and k not in want_keys)
        rp.danger = dangerous_bindings(policy)
        if kind == "project" and cloud.target == "gcp":
            logged = {c.get("service") for c in policy.get("auditConfigs", [])
                      if any(lc.get("logType") == "DATA_READ" for lc in c.get("auditLogConfigs", []))}
            rp.missing_audit_logs = [s for s in spec.get("data_access_logs", []) if s not in logged]
        plan.resources.append(rp)
    return plan


def merged_policy(rp: ResourcePlan) -> dict[str, Any]:
    """Add rp.add to rp.policy without removing anything."""
    policy = json.loads(json.dumps(rp.policy or {"bindings": []}))
    bindings = policy.setdefault("bindings", [])
    for role, member, cond in rp.add:
        match = next((b for b in bindings if b["role"] == role and _cond_key(b.get("condition")) == _cond_key(cond)), None)
        if match is None:
            match = {"role": role, "members": []}
            if cond:
                match["condition"] = cond
            bindings.append(match)
        if member not in match["members"]:
            match["members"].append(member)
    if any(b.get("condition") for b in bindings):
        policy["version"] = 3
    for service in rp.missing_audit_logs:
        configs = policy.setdefault("auditConfigs", [])
        entry = next((c for c in configs if c.get("service") == service), None)
        if entry is None:
            entry = {"service": service, "auditLogConfigs": []}
            configs.append(entry)
        if not any(c.get("logType") == "DATA_READ" for c in entry["auditLogConfigs"]):
            entry["auditLogConfigs"].append({"logType": "DATA_READ"})
    return policy


def apply_plan(cloud: Cloud, spec: dict[str, Any], plan: Plan) -> list[str]:
    done: list[str] = []
    sa_info = spec.get("service_accounts") or {}
    for sa in plan.create_sas:
        display = (sa_info.get(sa) or {}).get("display_name") or f"Stand-in for teammate {sa[7:]} (Floci only)"
        cloud.create_sa(sa, display)
        done.append(f"created service account {sa}")
    for secret in plan.missing_secrets:
        if cloud.target == "floci":
            cloud.create_secret(secret, f"floci-placeholder-{secret}".encode())
            done.append(f"created Floci secret {secret} with a placeholder value")
    for rp in plan.resources:
        if rp.kind == "secret" and rp.resource in plan.missing_secrets and cloud.target == "gcp":
            done.append(f"SKIPPED secret {rp.resource}: create it first (infra/setup.sh, or gcloud secrets create for the integration key)")
            continue
        if not rp.add and not rp.missing_audit_logs:
            continue
        if rp.kind in ("secret", "sa") and (rp.resource in plan.missing_secrets or rp.resource in plan.create_sas):
            rp.policy = cloud.get_policy(rp.kind, rp.resource)  # created just now; fetch its etag
        cloud.set_policy(rp.kind, rp.resource, merged_policy(rp))
        for role, member, cond in rp.add:
            done.append(f"{rp.kind}:{rp.resource or cloud.project} + {role} -> {member}"
                        + (f" (until {cond['expression'].split(chr(39))[1]})" if cond else ""))
        for service in rp.missing_audit_logs:
            done.append(f"project audit logs + DATA_READ for {service}")
    return done


def print_plan(plan: Plan) -> None:
    print(f"\nIAM plan for {plan.target} project {plan.project}")
    for sa in plan.create_sas:
        print(f"  + service account {sa}")
    for s in plan.missing_secrets:
        print(f"  ! secret {s} does not exist" + (" (apply creates a placeholder)" if plan.target == "floci" else " (create it first)"))
    for rp in plan.resources:
        label = f"{rp.kind}:{rp.resource or plan.project}"
        for role, member, cond in rp.add:
            print(f"  + {label}  {role} -> {member}" + ("  [time-boxed]" if cond else ""))
        for s in rp.missing_audit_logs:
            print(f"  + {label}  Data Access logs (DATA_READ) for {s}")
        for role, member, expr in rp.drift:
            print(f"  ~ DRIFT {label}  {role} -> {member} is not in iam.yaml" + (f" [{expr}]" if expr else ""))
        for d in rp.danger:
            print(f"  !! DANGER {label}  {d}")
    for k in plan.key_findings:
        print(f"  !! KEY {k}")
    print(f"\n{plan.changes} change(s) to apply, {plan.findings} finding(s) to review.")


def gcloud_token() -> str:
    try:
        return subprocess.run(["gcloud", "auth", "print-access-token"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Could not get a token from gcloud ({exc}). Run: gcloud auth login") from None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["lint", "plan", "apply", "audit", "token"])
    p.add_argument("--target", choices=["floci", "gcp"], default="floci")
    p.add_argument("--project", default=os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "floci-local")
    p.add_argument("--floci-url", default=os.environ.get("FLOCI_GCP_URL", FLOCI_DEFAULT))
    p.add_argument("--spec", default=str(SPEC_PATH))
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt on gcp apply")
    p.add_argument("--as", dest="as_name", help="token: service account or person name")
    a = p.parse_args(argv)

    spec = load_spec(Path(a.spec))
    errors = lint(spec)
    if a.command == "lint":
        for e in errors:
            print(f"  x {e}")
        print("IAM lint: clean" if not errors else f"IAM lint: {len(errors)} problem(s)")
        return 1 if errors else 0
    if errors:
        print("Fix lint errors first:\n" + "\n".join(f"  x {e}" for e in errors))
        return 1

    if a.target == "gcp" and a.project == "floci-local":
        raise SystemExit("Set --project (or PROJECT_ID) to your real Google Cloud project id.")
    cloud = Cloud(a.target, a.project, floci_url=a.floci_url, token=gcloud_token() if a.target == "gcp" else None)

    if a.command == "token":
        if a.target != "floci" or not a.as_name:
            raise SystemExit("token works with --target floci --as <service-account-or-person>")
        name = a.as_name if a.as_name in (spec.get("service_accounts") or {}) else f"person-{a.as_name}"
        print(cloud.mint_token(cloud.sa_email(name)))
        return 0

    team = load_team()
    plan = make_plan(cloud, spec, team)
    if a.command == "audit":
        if a.target != "gcp":
            raise SystemExit("audit runs against --target gcp")
        for sa in spec.get("service_accounts") or {}:
            if sa not in plan.create_sas:
                for key in cloud.user_managed_keys(sa):
                    plan.key_findings.append(f"{sa} has a user-managed key {key.get('name', '').rsplit('/', 1)[-1]}; delete it")
    print_plan(plan)
    if a.command in ("plan", "audit"):
        return 1 if (a.command == "audit" and (plan.changes or plan.findings)) else 0

    if not plan.changes and not plan.missing_secrets:
        print("Nothing to apply.")
        return 0
    if a.target == "gcp" and not a.yes:
        if input(f"Apply {plan.changes} change(s) to {a.project}? Type the project id to confirm: ").strip() != a.project:
            print("Cancelled.")
            return 1
    for line in apply_plan(cloud, spec, plan):
        print(f"  done: {line}")
    print("Applied. Run plan again: it should show 0 changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
