#!/usr/bin/env python3
"""
setupWebServerCmd.py — one-shot PythonAnywhere web server setup.

Run from pages/AccountingData/Notebooks/ after cloning the repo:
    python3.10 setupWebServerCmd.py

Forgot your passphrase / need a clean reset:
    python3.10 setupWebServerCmd.py --reset

Tasks
─────
  1. Prompt for LLC_GPG_PASSPHRASE
  2. Install pip dependencies
  3. Seed pw.json.gpg with default llcgroupmgr user (if missing)
  4. Generate LLC_SECRET_KEY; store it in pw.json.gpg under wbgadminWS
  5. Print the ready-to-paste PA WSGI file content

--reset flag (Step 0)
─────────────────────
  Deletes pw.json.gpg before setup so a fresh DB is created with the
  new passphrase.  Use when the old passphrase is lost or the DB is
  corrupt.  All existing user accounts will be removed.
"""

import argparse
import getpass
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Anchor Notebooks/ on sys.path so ledger, ui, util are importable.
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))

from ui.llcLogin_auth import (
    _db_path, _find_user, _hash, _load_users, _save_users,
)

# ── Config ────────────────────────────────────────────────────────────────────

LLC_NAME = "WBGroupLLC"

DEPS = ["flask", "pandas", "numpy", "pypdf", "deepdiff"]

_SEED_USER = {
    "username":   "llcgroupmgr",
    "password":   _hash("llcManager0!"),
    "full_name":  "WBGroup LLC",
    "phone":      "",
    "role":       "llcManager",
    "created_at": "2026-01-01T00:00:00",
}

_ADMIN_ID = "wbgadminWS"


# ── Steps ─────────────────────────────────────────────────────────────────────

def step_reset_db(db: Path) -> None:
    print("\n── Step 0: Reset User Database ─────────────────────────────────")
    if not db.exists():
        print("  No existing DB found — nothing to delete.")
        return
    print(f"  ⚠️  This will permanently delete: {db}")
    print("  All existing user accounts will be lost.")
    confirm = input("  Type YES to confirm: ").strip()
    if confirm.lower()[0] != "y":
        print("  Cancelled — database not deleted.")
        sys.exit(0)
    db.unlink()
    print("  ✓ Deleted pw.json.gpg — starting fresh.")


def step_passphrase() -> str:
    print("\n── Step 1: GPG Passphrase ──────────────────────────────────────")
    print("Encrypts the user DB (pw.json.gpg).")
    print("You must use the same passphrase every time the server runs.\n")
    while True:
        pp = getpass.getpass("  Enter LLC_GPG_PASSPHRASE (min 12 chars): ").strip()
        if len(pp) < 12:
            print("  ✗ Too short — at least 12 characters required.")
            continue
        if getpass.getpass("  Confirm passphrase: ").strip() != pp:
            print("  ✗ Passphrases do not match.")
            continue
        break
    os.environ["LLC_GPG_PASSPHRASE"] = pp
    print("  ✓ Passphrase accepted.")
    return pp


def step_pip() -> None:
    print("\n── Step 2: Install Dependencies ────────────────────────────────")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--user", "--quiet"] + DEPS
    )
    if result.returncode != 0:
        print(f"  ✗ pip install failed. Run manually:")
        print(f"    pip install --user {' '.join(DEPS)}")
    else:
        print(f"  ✓ {', '.join(DEPS)} ready.")


def step_userdb() -> list:
    print("\n── Step 3: User Database ───────────────────────────────────────")
    db = _db_path(LLC_NAME)
    users = []

    if db.exists():
        try:
            users = _load_users(LLC_NAME)
            print(f"  Found existing DB ({len(users)} user(s)).")
        except Exception as exc:
            print(f"  ✗ Could not read existing DB: {exc}")
            print("    Starting fresh.")
            users = []

    if not _find_user(users, "llcgroupmgr"):
        users.append(_SEED_USER)
        print("  + Added seed user: llcgroupmgr / llcManager0!")
    else:
        print("  ✓ llcgroupmgr already present.")

    _save_users(LLC_NAME, users)
    print(f"  ✓ Saved → {db}")
    return users


def step_secret_key(users: list, passphrase: str) -> str:
    print("\n── Step 4: Web Server Secret Key ───────────────────────────────")
    secret_key = secrets.token_hex(32)
    os.environ["LLC_SECRET_KEY"] = secret_key

    admin = _find_user(users, _ADMIN_ID)
    if admin:
        admin["notes"]          = secret_key
        admin["gpg_passphrase"] = passphrase
        print(f"  Updated {_ADMIN_ID} with new secret key and passphrase.")
    else:
        users.append({
            "username":       _ADMIN_ID,
            "password":       "",
            "full_name":      "webserver admin",
            "phone":          "",
            "role":           "llcManager",
            "notes":          secret_key,
            "gpg_passphrase": passphrase,
            "created_at":     datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        })
        print(f"  + Created {_ADMIN_ID} record.")

    _save_users(LLC_NAME, users)
    print(f"  ✓ LLC_SECRET_KEY and LLC_GPG_PASSPHRASE stored in pw.json.gpg.")
    return secret_key


def step_wsgi(passphrase: str, secret_key: str) -> None:
    print("\n── Step 5: WSGI Configuration File ────────────────────────────")
    pa_username = Path.home().name
    notebooks_path = str(_here)

    wsgi_content = f"""\
import sys, os

# Credentials — this file is readable only by your PA account.
os.environ.setdefault('LLC_GPG_PASSPHRASE', {passphrase!r})
os.environ.setdefault('LLC_SECRET_KEY',     {secret_key!r})

sys.path.insert(0, {notebooks_path!r})
from wsgi import application
"""

    print()
    print("  Copy the block below into your PA WSGI configuration file:")
    print("  Web tab → WSGI configuration file link → replace all content\n")
    print("  " + "─" * 62)
    for line in wsgi_content.splitlines():
        print("  " + line)
    print("  " + "─" * 62)
    print()
    print(f"  Detected PA username : {pa_username}")
    print(f"  Notebooks path       : {notebooks_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="LLC App — PA web server setup")
    ap.add_argument("--reset", action="store_true",
                    help="Delete pw.json.gpg before setup (use when passphrase is lost)")
    args = ap.parse_args()

    print()
    print("=" * 64)
    print("  LLC App — MultiTaskWS Web Server Setup")
    print("=" * 64)

    if args.reset:
        step_reset_db(_db_path(LLC_NAME))

    passphrase = step_passphrase()
    step_pip()
    users      = step_userdb()
    secret_key = step_secret_key(users, passphrase)
    step_wsgi(passphrase, secret_key)

    print("=" * 64)
    print("  Setup complete.")
    print("  → Hit Reload in the PA Web tab.")
    print("  → Visit your PA URL and log in: llcgroupmgr / llcManager0!")
    print()
    print("  Recover passphrase later (while server/env is running):")
    print("    python3 -c \"")
    print("    import sys; sys.path.insert(0,'pages/AccountingData/Notebooks')")
    print("    from ui.llcLogin_auth import _load_users, _find_user")
    print("    u = _find_user(_load_users('WBGroupLLC'), 'wbgadminWS')")
    print("    print('passphrase:', u['gpg_passphrase'])")
    print("    print('secret_key:', u['notes'])\"")
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
