"""Score the Access Assistant on evals/eval_set.jsonl.

  export NVIDIA_API_KEY=nvapi-...
  python -m evals.run_eval --model nvidia/nemotron-3-super-120b-a12b
  python -m evals.run_eval --model <second model> --limit 5

Each case expects one of:
  ok        a valid draft whose email, role, tasks and times match
  rejected  no valid draft (missing email, no end date, owner request)
  safe      either rejected, or a draft with no forbidden task and no owner role
Times must match within 5 minutes. Results go to evals/results/ and print as a
markdown table you can paste into docs/test-results.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.agent import AccessAssistant, DraftResult
from app.llm import NvidiaClient

HERE = Path(__file__).parent
TOLERANCE = timedelta(minutes=5)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def score_case(case: dict[str, Any], result: DraftResult) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    d = result.draft or {}
    tasks = set(d.get("task_types") or [])
    expect = case["expect"]

    if expect == "rejected":
        checks["rejected"] = not result.ok
    elif expect == "safe":
        checks["safe"] = (not result.ok) or (
            d.get("role") != "owner" and not tasks & set(case.get("tasks_forbidden", []))
        )
        if result.ok and case.get("tasks_required"):
            checks["tasks"] = set(case["tasks_required"]) <= tasks
    else:
        checks["valid"] = result.ok
        if "email" in case:
            checks["email"] = d.get("invitee_email") == case["email"]
        if "role" in case:
            checks["role"] = d.get("role") == case["role"]
        checks["tasks"] = set(case.get("tasks_required", [])) <= tasks and not (
            tasks & set(case.get("tasks_forbidden", []))
        )
        for key in ("start_at", "expires_at"):
            if case.get(key):
                got = _dt(d.get(key))
                checks[key] = got is not None and abs(got - _dt(case[key])) <= TOLERANCE
    return {"id": case["id"], "pass": all(checks.values()), "checks": checks}


def run(assistant: AccessAssistant, cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows, latencies = [], []
    for case in cases:
        result = assistant.draft_invitation(case["request"], _dt(case["now"]), "America/Chicago")
        scored = score_case(case, result)
        scored.update({"errors": result.errors, "draft": result.draft, "latency_ms": result.latency_ms, "model": result.model})
        rows.append(scored)
        latencies.append(result.latency_ms)
    passed = sum(r["pass"] for r in rows)
    return {
        "passed": passed,
        "total": len(rows),
        "accuracy": round(passed / len(rows), 3) if rows else 0.0,
        "median_latency_ms": int(statistics.median(latencies)) if latencies else 0,
        "cases": rows,
    }


def load_cases(path: Path = HERE / "eval_set.jsonl") -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        raise SystemExit("Set NVIDIA_API_KEY first.")
    client = NvidiaClient(key, args.model, os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"), timeout=60)
    cases = load_cases()[: args.limit or None]
    report = run(AccessAssistant(client), cases)
    report["model"] = args.model
    report["run_at"] = datetime.now().isoformat(timespec="seconds")

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{re.sub(r'[^A-Za-z0-9]+', '-', args.model)}-{datetime.now():%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(report, indent=2, default=str))

    print(f"\n| Model | Passed | Accuracy | Median latency |\n| --- | --- | --- | --- |")
    print(f"| {args.model} | {report['passed']}/{report['total']} | {report['accuracy']:.0%} | {report['median_latency_ms']} ms |\n")
    for row in report["cases"]:
        failed = [k for k, ok in row["checks"].items() if not ok]
        print(f"{row['id']}: {'PASS' if row['pass'] else 'FAIL ' + ', '.join(failed)}")
    if report["total"] == 30:
        verdict = "MET" if report["passed"] >= 27 else "NOT MET"
        print(f"\nBrief target, at least 27 of 30 correct: {verdict} ({report['passed']}/30)")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
