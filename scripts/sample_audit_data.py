"""Generate realistic sample audit data for the success-measures dashboard (Joclyn).

Acts out a busy week at Bloom & Crumb against a running RoleReady server in demo mode, then saves
the audit log as newline-delimited JSON in the same columns as `scripts/export_bigquery.py`
(table `roleready.audit_events`). Upload the file to BigQuery (a free BigQuery Sandbox works) and
build Looker Studio charts from `scripts/metrics.sql` before the app is deployed to Google Cloud.

  uvicorn app.main:create_app --factory --env-file .env        # AUTH_MODE=demo, STORE_BACKEND=memory
  python scripts/sample_audit_data.py --out ~/roleready-sample/audit_events.jsonl

Every row is written by the real app, so the hash chain is genuine. Takes about 4 minutes because
access windows are real minutes. Needs only the requests library.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OWNER = "owner@bloomandcrumb.test"
TASKS = ["view_assets", "edit_drafts", "schedule_posts", "view_analytics", "manage_access"]

# Same columns, in the same order, as SCHEMA in scripts/export_bigquery.py.
BQ_SCHEMA = [
    {"name": "id", "type": "STRING"},
    {"name": "seq", "type": "INTEGER"},
    {"name": "ts", "type": "TIMESTAMP"},
    {"name": "workspace_id", "type": "STRING"},
    {"name": "actor", "type": "STRING"},
    {"name": "action", "type": "STRING"},
    {"name": "target", "type": "STRING"},
    {"name": "decision", "type": "STRING"},
    {"name": "reason", "type": "STRING"},
    {"name": "details", "type": "STRING"},
    {"name": "hash", "type": "STRING"},
]

# (email, role, tasks, minutes from now until start, window length in minutes, revoke after N rounds)
FREELANCERS = [
    ("sam@freelance.test", "contributor", ["view_assets", "edit_drafts", "schedule_posts"], 0.05, 2.0, None),
    ("riley@client.test", "viewer", ["view_assets", "view_analytics"], 0.05, 3.0, 4),
    ("jordan@freelance.test", "contributor", ["edit_drafts"], 0.05, 1.5, None),
    ("casey@agency.test", "viewer", ["view_analytics"], 0.05, 2.5, None),
    ("alex@freelance.test", "contributor", ["view_assets", "edit_drafts"], 0.05, 3.0, 6),
    ("taylor@studio.test", "viewer", ["view_assets"], 0.75, 1.75, None),
]
STRANGERS = ["mallory@evil.test", "eve@unknown.test"]


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def call(self, user: str, method: str, path: str, body: dict | None = None) -> requests.Response:
        return requests.request(method, self.base + path, json=body, headers={"X-Demo-User": user}, timeout=30)

    def ok(self, user: str, method: str, path: str, body: dict | None = None) -> dict:
        r = self.call(user, method, path, body)
        r.raise_for_status()
        return r.json()


def invite(c: Client, email: str, role: str, tasks: list[str], start: datetime, end: datetime) -> tuple[str, str]:
    inv = c.ok(OWNER, "POST", "/invitations", {
        "invitee_email": email, "role": role, "task_types": tasks, "timezone": "America/Chicago",
        "start_at": start.isoformat(), "expires_at": end.isoformat(), "reason": "sample dashboard data",
    })
    token = c.ok(OWNER, "POST", f"/invitations/{inv['id']}/approve")["invite_token"]
    grant = c.ok(email, "POST", "/invitations/accept", {"token": token})
    return grant["id"], token


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--out", default="~/roleready-sample/audit_events.jsonl", help="keep it outside the repo")
    p.add_argument("--seed", type=int, default=7, help="same seed, same sequence of attempts")
    p.add_argument("--round-seconds", type=float, default=15.0)
    a = p.parse_args()
    rng = random.Random(a.seed)
    c = Client(a.base_url)
    print("health:", requests.get(c.base + "/health", timeout=30).json())

    # 1. Owner invites and approves each freelancer; each accepts their single-use link.
    now = datetime.now(timezone.utc)
    grants: dict[str, str] = {}
    tokens: dict[str, str] = {}
    ends: dict[str, datetime] = {}
    for email, role, tasks, start_min, window_min, _ in FREELANCERS:
        start = now + timedelta(minutes=start_min)
        end = start + timedelta(minutes=window_min)
        grants[email], tokens[email] = invite(c, email, role, tasks, start, end)
        ends[email] = end
        print(f"invited {email:<24} {role:<12} until {end:%H:%M:%S} UTC")

    # A reused link and a stranger using someone else's link are both refused and logged.
    c.call("sam@freelance.test", "POST", "/invitations/accept", {"token": tokens["sam@freelance.test"]})
    c.call("mallory@evil.test", "POST", "/invitations/accept", {"token": tokens["riley@client.test"]})

    # 2. Rounds of work. The expiry job runs every 4th round, like the one-minute Cloud Scheduler job.
    last_end = max(ends.values())
    rnd = 0
    while datetime.now(timezone.utc) < last_end + timedelta(seconds=a.round_seconds * 2):
        rnd += 1
        for email, _, tasks, _, _, revoke_after in FREELANCERS:
            if revoke_after == rnd:
                c.ok(OWNER, "POST", f"/grants/{grants[email]}/revoke")
                print(f"round {rnd}: owner revoked {email}")
            # Mostly tasks they were given, sometimes one they were not.
            for _ in range(rng.randint(1, 3)):
                task = rng.choice(tasks) if rng.random() < 0.75 else rng.choice(TASKS)
                c.call(email, "POST", f"/actions/{task}")
        if rng.random() < 0.5:
            c.call(rng.choice(STRANGERS), "POST", f"/actions/{rng.choice(TASKS)}")
        if rnd % 4 == 0:
            c.ok(OWNER, "POST", "/dev/run-expiry")
        print(f"round {rnd} done")
        time.sleep(a.round_seconds)

    # 3. Run the expiry job 10 more times: the brief's target is zero duplicate expired events.
    for _ in range(10):
        c.ok(OWNER, "POST", "/dev/run-expiry")

    # 4. Everyone tries once more after their access ended. All of these must be denied.
    for email, _, tasks, _, _, _ in FREELANCERS:
        c.call(email, "POST", f"/actions/{tasks[0]}")

    # 5. Save the audit log in the BigQuery table's columns.
    events = c.ok(OWNER, "GET", "/audit")
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for e in events:
            f.write(json.dumps({
                "id": e["id"], "seq": e["seq"], "ts": e["ts"], "workspace_id": e["workspace_id"],
                "actor": e["actor"], "action": e["action"], "target": e.get("target", ""),
                "decision": e.get("decision"), "reason": e.get("reason", ""),
                "details": json.dumps(e.get("details") or {}), "hash": e.get("hash", ""),
            }) + "\n")
    schema_path = out.with_name("schema.json")
    schema_path.write_text(json.dumps(BQ_SCHEMA, indent=2) + "\n")

    print("audit chain:", c.ok(OWNER, "GET", "/audit/verify"))
    print(f"Saved {len(events)} audit events to {out} and the table schema to {schema_path}")


if __name__ == "__main__":
    main()
