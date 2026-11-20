"""Seed Floci for local work: test sign-in users in emulated Firebase Auth, and a
Firestore round trip to prove the app's data path works.

  docker compose up -d floci-gcp
  python scripts/floci_seed.py
  python scripts/floci_seed.py --password 'a-local-password'

Uses only the requests library and Floci's REST endpoints (Firebase Auth emulator API).
Seeded users are marked email-verified, because the app refuses unverified emails (threat S5).
Safe to rerun: existing users are kept and marked verified.
Then sign in on http://localhost:8000 with any seeded email and the password.
"""

from __future__ import annotations

import argparse
import os

import requests

USERS = ["owner@bloomandcrumb.test", "sam@freelance.test", "riley@client.test"]


def mark_verified(base: str, email: str) -> None:
    """Set emailVerified with the emulator's admin credential ("Bearer owner"). Users can't do this themselves."""
    admin = {"Authorization": "Bearer owner"}
    r = requests.post(f"{base}/identitytoolkit.googleapis.com/v1/accounts:lookup", headers=admin, json={"email": [email]}, timeout=15)
    users = r.json().get("users") if r.ok else None
    if not users:
        raise SystemExit(f"Could not look up {email}: HTTP {r.status_code} {r.text[:200]}")
    r = requests.post(
        f"{base}/identitytoolkit.googleapis.com/v1/accounts:update",
        headers=admin,
        json={"localId": users[0]["localId"], "emailVerified": True},
        timeout=15,
    )
    if not (r.ok and r.json().get("emailVerified")):
        raise SystemExit(f"Could not mark {email} verified: HTTP {r.status_code} {r.text[:200]}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--floci", default=os.environ.get("FLOCI_GCP_URL", "http://localhost:4588"))
    p.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "floci-local"))
    p.add_argument("--password", default="roleready-local-1")
    a = p.parse_args()
    base = a.floci.rstrip("/")

    print(f"Floci at {base}, project {a.project}")
    for email in USERS:
        r = requests.post(
            f"{base}/identitytoolkit.googleapis.com/v1/accounts:signUp",
            params={"key": "floci-local-key"},
            json={"email": email, "password": a.password, "returnSecureToken": True},
            timeout=15,
        )
        if r.ok:
            print(f"  created {email}")
        elif "EMAIL_EXISTS" in r.text:
            print(f"  exists  {email}")
        else:
            raise SystemExit(f"Could not create {email}: HTTP {r.status_code} {r.text[:200]}")
        mark_verified(base, email)

    # Firestore round trip through the official client (same library the app uses)
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", base.split("://", 1)[-1])
    try:
        from google.cloud import firestore
    except ImportError:
        print("google-cloud-firestore not installed; skipping the Firestore check (pip install -r requirements.txt)")
        return
    db = firestore.Client(project=a.project)
    db.collection("floci_check").document("ping").set({"ok": True})
    assert db.collection("floci_check").document("ping").get().to_dict() == {"ok": True}
    db.collection("floci_check").document("ping").delete()
    print("  Firestore round trip OK")
    print(f"\nSign in at http://localhost:8000 with any user above and password: {a.password}")


if __name__ == "__main__":
    main()
