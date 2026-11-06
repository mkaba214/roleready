"""Run the full RoleReady journey against a running server in demo auth mode.

Doubles as a smoke test after each deploy and as seed data for the dashboard.

  python scripts/demo_journey.py --base-url http://localhost:8000
  python scripts/demo_journey.py --base-url https://roleready-xxxx.a.run.app --window-minutes 3

Needs AUTH_MODE=demo on the server. Uses only the requests library.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone

import requests

OWNER_DEFAULT = "owner@bloomandcrumb.test"


def call(base: str, user: str, method: str, path: str, body: dict | None = None) -> requests.Response:
    return requests.request(method, base + path, json=body, headers={"X-Demo-User": user}, timeout=30)


def invite(base: str, owner: str, email: str, role: str, tasks: list[str], start: datetime, end: datetime) -> str:
    r = call(base, owner, "POST", "/invitations", {
        "invitee_email": email, "role": role, "task_types": tasks,
        "start_at": start.isoformat(), "expires_at": end.isoformat(), "reason": "demo journey",
    })
    r.raise_for_status()
    r = call(base, owner, "POST", f"/invitations/{r.json()['id']}/approve")
    r.raise_for_status()
    token = r.json()["invite_token"]
    r = call(base, email, "POST", "/invitations/accept", {"token": token})
    r.raise_for_status()
    return r.json()["id"]


def act(base: str, user: str, task: str) -> str:
    r = call(base, user, "POST", f"/actions/{task}")
    data = r.json()
    line = f"  {user:<24} {task:<15} {'ALLOW' if data['allowed'] else 'DENY '} {data['reason']}"
    print(line)
    return data["reason"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--owner", default=OWNER_DEFAULT)
    p.add_argument("--window-minutes", type=float, default=2.0, help="length of Sam's access window")
    p.add_argument("--no-wait", action="store_true", help="skip waiting for Sam's window to end")
    a = p.parse_args()
    base = a.base_url.rstrip("/")

    print("health:", requests.get(base + "/health", timeout=30).json())
    now = datetime.now(timezone.utc)
    sam_end = now + timedelta(minutes=a.window_minutes)
    sam = invite(base, a.owner, "sam@freelance.test", "contributor", ["view_assets", "edit_drafts", "schedule_posts"], now + timedelta(seconds=5), sam_end)
    riley = invite(base, a.owner, "riley@client.test", "viewer", ["view_assets", "view_analytics"], now + timedelta(seconds=5), now + timedelta(days=2))
    print(f"grants: sam={sam} riley={riley}")
    time.sleep(6)

    print("\nInside the window:")
    act(base, "sam@freelance.test", "edit_drafts")
    act(base, "sam@freelance.test", "view_analytics")
    act(base, "riley@client.test", "view_analytics")
    act(base, "riley@client.test", "schedule_posts")
    act(base, "mallory@evil.test", "view_assets")

    print("\nOwner revokes Riley:")
    call(base, a.owner, "POST", f"/grants/{riley}/revoke").raise_for_status()
    act(base, "riley@client.test", "view_assets")

    if not a.no_wait:
        wait = max(0.0, (sam_end - datetime.now(timezone.utc)).total_seconds()) + 1
        print(f"\nWaiting {wait:.0f}s for Sam's window to end...")
        time.sleep(wait)
        reason = act(base, "sam@freelance.test", "edit_drafts")
        assert reason == "expired", "access must end exactly at expires_at"

    verify = call(base, a.owner, "GET", "/audit/verify").json()
    print("\naudit chain:", verify)
    assert verify["ok"], "audit chain broken"
    print("Journey complete.")


if __name__ == "__main__":
    main()
