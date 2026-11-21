#!/usr/bin/env python3
"""
Management of the user accounts of the web interface (e.g. to recover access):

    ./manage_users.py list
    ./manage_users.py add <username>       (asks for the password)
    ./manage_users.py passwd <username>
    ./manage_users.py delete <username>

The password given with add and passwd is temporary: the user must change it
after the next login, unless --no-change-required is given (e.g. to recover
the access to your own account). The passwords must satisfy the policy of
password_strength.py (at least 10 characters, not a common password...).

Uses the database of AQ_DB_PATH (default: aq_dashboard.db next to this file).
"""

import argparse
import getpass
import sys

from auth import MIN_PASSWORD_LENGTH, AuthError, AuthManager
from logger_configurator import LoggerConfigurator
from password_strength import evaluate
from persistent_storage import PersistentStorage

ERRORS = {
    "password_too_short": f"The password is too short (at least {MIN_PASSWORD_LENGTH} characters)",
    "password_too_long": "The password is too long",
    "password_too_weak": "The password is too weak",
    "invalid_username": "Invalid user name (1-32 characters: letters, digits, _ . -)",
    "user_exists": "This user already exists",
    "unknown_user": "Unknown user",
}

HINTS = {
    "too_short": f"use at least {MIN_PASSWORD_LENGTH} characters",
    "user_name": "do not use the user name",
    "common": "avoid common passwords and words",
    "years": "avoid years and dates",
    "repeats": "avoid repeated characters",
    "sequences": "avoid sequences such as abc, 123 or qwerty",
    "longer": "add more characters or words",
}


def ask_password(username: str) -> str:
    while True:
        password = getpass.getpass(f"Password (at least {MIN_PASSWORD_LENGTH} characters): ")
        strength = evaluate(password, [username])
        if strength["acceptable"]:
            break
        print("Too weak: " + "; ".join(HINTS[c] for c in strength["feedback"] if c in HINTS))
    if password != getpass.getpass("Repeat the password: "):
        sys.exit("The passwords differ")
    return password


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["list", "add", "passwd", "delete"])
    parser.add_argument("username", nargs="?")
    parser.add_argument("--no-change-required", action="store_true",
                        help="add, passwd: the user does not have to change the password after the login")
    args = parser.parse_args()
    if args.command != "list" and not args.username:
        parser.error("a user name is needed")
    storage = PersistentStorage()
    auth = AuthManager(storage, LoggerConfigurator.configure_logger("ManageUsers"), enabled=False)
    must_change = not args.no_change_required
    try:
        if args.command == "list":
            users = auth.list_users()
            print("\n".join(u + (" (must change the password)" if auth.must_change_password(u) else "") for u in users)
                  or "No user account")
        elif args.command == "add":
            auth.create_user(args.username, ask_password(args.username), must_change=must_change)
        elif args.command == "passwd":
            auth.set_password(args.username, ask_password(args.username), must_change=must_change)
        else:
            auth.delete_user(args.username)
    except AuthError as e:
        sys.exit(f"Error: {ERRORS.get(str(e), str(e))}")
    if args.command in ("add", "passwd") and must_change:
        print(f"{args.username} must change this password after the next login")


if __name__ == "__main__":
    main()
