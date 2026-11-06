"""Least-privilege rules for infra/iam/iam.yaml. Runs in CI with no network.
A pull request that widens access in a forbidden way fails here."""

from __future__ import annotations

import copy

import pytest

from scripts.iam import SPEC_PATH, expand, lint, load_spec


@pytest.fixture
def spec() -> dict:
    return load_spec(SPEC_PATH)


def test_repo_policy_is_clean(spec) -> None:
    assert lint(spec) == []


def test_people_expire_and_workloads_do_not(spec) -> None:
    for b in expand(spec):
        if b.member.startswith("person:"):
            assert b.expires == spec["build_ends"], b
        else:
            assert b.expires is None, b


def test_only_the_run_service_reads_secrets(spec) -> None:
    readers = {b.member for b in expand(spec) if b.role == "roles/secretmanager.secretAccessor"}
    assert readers == {"sa:roleready-run"}


def test_scheduler_has_no_project_roles(spec) -> None:
    assert not [b for b in expand(spec) if b.member == "sa:roleready-scheduler"]


def mutate(spec: dict, section: str, entry: dict) -> list[str]:
    s = copy.deepcopy(spec)
    s.setdefault(section, []).append(entry)
    return lint(s)


@pytest.mark.parametrize(
    "entry, message",
    [
        ({"member": "person:joclyn", "roles": ["roles/editor"]}, "basic roles"),
        ({"member": "person:mohamed", "roles": ["roles/owner"]}, "basic roles"),
        ({"member": "person:ashley", "roles": ["roles/iam.serviceAccountTokenCreator"]}, "impersonate"),
        ({"member": "person:mohamed", "roles": ["roles/iam.serviceAccountKeyAdmin"]}, "impersonate"),
        ({"member": "person:mohamed", "roles": ["roles/iam.serviceAccountUser"]}, "never project-wide"),
        ({"member": "person:joclyn", "roles": ["roles/secretmanager.secretAccessor"]}, "only the Cloud Run service account"),
        ({"member": "sa:roleready-run", "roles": ["roles/secretmanager.secretAccessor"]}, "not project-wide"),
        ({"member": "sa:roleready-scheduler", "roles": ["roles/run.invoker"]}, "may only hold"),
        ({"member": "sa:roleready-run", "roles": ["roles/storage.admin"]}, "may only hold"),
        ({"member": "person:andrew", "roles": ["roles/run.admin"]}, "separation of duties"),
        ({"member": "person:joclyn", "roles": ["roles/bigquery.admin"], "expires": "none"}, "must expire"),
        ({"member": "person:mallory", "roles": ["roles/logging.viewer"]}, "unknown teammate"),
        ({"member": "sa:mystery", "roles": ["roles/logging.viewer"]}, "unknown service account"),
        ({"member": "allUsers", "roles": ["roles/logging.viewer"]}, "member must be"),
    ],
)
def test_lint_catches_dangerous_changes(spec, entry, message) -> None:
    errors = mutate(spec, "project_bindings", entry)
    assert any(message in e for e in errors), errors


def test_lint_catches_secret_reader_on_secret(spec) -> None:
    s = copy.deepcopy(spec)
    s["secret_bindings"]["nvidia-api-key"].append({"member": "person:andrew", "roles": ["roles/secretmanager.secretAccessor"]})
    assert any("only the Cloud Run service account" in e for e in lint(s))


def test_lint_requires_purpose_and_reason(spec) -> None:
    s = copy.deepcopy(spec)
    s["service_accounts"]["roleready-run"]["purpose"] = ""
    s["team"]["joclyn"]["lead_for"] = ""
    errors = lint(s)
    assert any("needs a purpose" in e for e in errors)
    assert any("needs a lead_for" in e for e in errors)
