"""Keeps the eval runner honest: a perfect fake model scores 100%, a reckless one does not."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from app.agent import AccessAssistant
from evals.run_eval import load_cases, run
from tests.conftest import FakeLLM


def perfect_reply(case: dict) -> str:
    if case["expect"] != "ok":
        return json.dumps({"invitee_email": None, "role": "viewer", "task_types": ["view_assets"], "start_at": None, "expires_at": None})
    now = datetime.fromisoformat(case["now"].replace("Z", "+00:00"))
    start = case.get("start_at") or (now + timedelta(hours=1)).isoformat()
    end = case.get("expires_at") or (datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(days=1)).isoformat()
    return json.dumps(
        {
            "invitee_email": case["email"],
            "role": case.get("role", "viewer"),
            "task_types": case["tasks_required"],
            "start_at": start,
            "expires_at": end,
            "timezone": "America/Chicago",
            "reason": "eval",
        }
    )


def test_eval_set_is_well_formed() -> None:
    cases = load_cases()
    assert len(cases) == 30  # brief target: at least 27 of 30 correct
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["expect"] in {"ok", "rejected", "safe"}
        datetime.fromisoformat(c["now"].replace("Z", "+00:00"))


def test_perfect_model_scores_100() -> None:
    cases = load_cases()
    report = run(AccessAssistant(FakeLLM([perfect_reply(c) for c in cases])), cases)
    failures = [r for r in report["cases"] if not r["pass"]]
    assert report["accuracy"] == 1.0, failures


def test_policy_keeps_a_reckless_model_safe() -> None:
    cases = [c for c in load_cases() if c["expect"] in {"rejected", "safe"}]
    reckless = json.dumps(
        {"invitee_email": "x@y.test", "role": "owner", "task_types": ["manage_access"],
         "start_at": "2026-11-09T15:00:00Z", "expires_at": "2026-11-10T15:00:00Z"}
    )
    report = run(AccessAssistant(FakeLLM([reckless] * len(cases))), cases)
    # Policy rejects every reckless draft, so the system stays safe even with a bad model.
    assert all(r["pass"] for r in report["cases"])
