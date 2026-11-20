"""Create a verified Firebase sign-in account for a teammate or freelancer (threat S5).

RoleReady refuses Firebase sign-ins whose email isn't verified, because the public web API key
lets anyone sign up with any address. So accounts are made here, by someone with
roles/firebaseauth.admin, before the invite link goes out:

  python scripts/firebase_user.py --project $PROJECT_ID add sam@freelance.test
  python scripts/firebase_user.py --project $PROJECT_ID add sam@freelance.test --replace

`add` creates the account with no password, marked verified, and prints a one-time
password-setup link. Send that link to the same email address together with the invite link;
the person picks their own password. An account that already exists and is verified is left
alone. One that exists but is NOT verified may have been claimed by someone else first: the
script stops, and --replace deletes it and starts over.

Uses Application Default Credentials (`gcloud auth application-default login`). To practice on
Floci, set FIREBASE_AUTH_EMULATOR_HOST=localhost:4588 and use --project floci-local.
"""

from __future__ import annotations

import argparse
import sys

import firebase_admin
import firebase_admin.exceptions
from firebase_admin import auth

sys.path.insert(0, ".")
from app.models import normalize_email  # noqa: E402


def add(email: str, replace: bool, app) -> None:
    try:
        user = auth.get_user_by_email(email, app=app)
    except auth.UserNotFoundError:
        user = None

    if user and user.email_verified:
        print(f"exists and verified: {email} (nothing changed)")
    else:
        if user:
            if not replace:
                raise SystemExit(
                    f"{email} already has an UNVERIFIED account, which may have been made by someone else.\n"
                    "Rerun with --replace to delete it and create a fresh verified one."
                )
            auth.delete_user(user.uid, app=app)
            print(f"deleted unverified account: {email}")
        auth.create_user(email=email, email_verified=True, app=app)
        print(f"created verified account: {email}")

    try:
        link = auth.generate_password_reset_link(email, app=app)
    except firebase_admin.exceptions.FirebaseError as exc:
        # Floci doesn't implement password links (accounts:sendOobCode returns 404). On a real
        # project, check that the Email/Password provider is enabled in Firebase Authentication.
        raise SystemExit(f"account is ready, but no password-setup link could be made ({type(exc).__name__})") from None
    print("\nPassword-setup link (send only to this email address; anyone holding it can set the password):")
    print(link)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    a_add = sub.add_parser("add", help="create a verified account and print a password-setup link")
    a_add.add_argument("email")
    a_add.add_argument("--replace", action="store_true", help="delete an existing unverified account first")
    a = p.parse_args()

    app = firebase_admin.initialize_app(options={"projectId": a.project}, name="firebase-user")
    if a.cmd == "add":
        add(normalize_email(a.email), a.replace, app)


if __name__ == "__main__":
    main()
