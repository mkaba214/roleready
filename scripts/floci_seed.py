"""Seed Floci for local work: test sign-in users in emulated Firebase Auth, and a
Firestore round trip to prove the app's data path works.

  docker compose up -d floci-gcp
  python scripts/floci_seed.py
  python scripts/floci_seed.py --password 'a-local-password'

Uses only the requests library and Floci's REST endpoints (Firebase Auth emulator API).
Then sign in on http://localhost:8000 with any seeded email and the password.
"""

from __future__ import annotations

import argparse
import os

import requests

USERS = ["owner@bloomandcrumb.test", "sam@freelance.test", "riley@client.test"]


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
