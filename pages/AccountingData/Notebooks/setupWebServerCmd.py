#!/usr/bin/env python3
"""
setupWebServerCmd.py — one-shot MultiTaskWS web server setup.

Run from pages/AccountingData/Notebooks/ after cloning the repo:
    python3.10 setupWebServerCmd.py

Forgot your passphrase / need a clean reset:
    python3.10 setupWebServerCmd.py --reset

Tasks
─────
  1. Prompt for LLC_GPG_PASSPHRASE
  2. Install pip dependencies
  3. Write MultiTaskWS_Config to llcProfile_WBGroupLLC.json
     (LLC_SECRET_KEY, LLC_GPG_PASSPHRASE, WebServer)
  4. Seed pw.json.gpg with default llcgroupmgr user (if missing)
  5. Create wbgadminWS record in pw.json.gpg (notes → pointer to profile)
  6. Print the ready-to-paste PA WSGI file content

--reset flag (Step 0)
─────────────────────
  Deletes pw.json.gpg before setup so a fresh DB is created with the
  new passphrase.  Use when the old passphrase is lost or the DB is
  corrupt.  All existing user accounts will be removed.

Credential recovery
───────────────────
  LLC_GPG_PASSPHRASE and LLC_SECRET_KEY are the sole authoritative
  source in llcProfile_WBGroupLLC.json under "MultiTaskWS_Config".
  Read them any time (no passphrase needed — profile is plain JSON):
      python3 -c "
      import json
      p = 'pages/AccountingData/Accts/llcProfile_WBGroupLLC.json'
      cfg = json.load(open(p))['MultiTaskWS_Config']
      print(json.dumps(cfg, indent=2))"
"""

import argparse
import getpass
import json
import os
import platform
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

LLC_NAME     = "WBGroupLLC"
_PROFILE     = _here.parent / "Accts" / f"llcProfile_{LLC_NAME}.json"

DEPS = ["flask", "pandas", "numpy", "pypdf", "deepdiff"]

_SEED_USER = {
    "username":   "llcgroupmgr",
    "password":   _hash("llcManager0!"),
    "full_name":  "WBGroup LLC",
    "phone":      "",
    "role":       "llcManager",
    "created_at": "2026-01-01T00:00:00",
}

_ADMIN_ID   = "wbgadminWS"
_ADMIN_NOTE = "Config variables are in LLC profile (llcProfile_WBGroupLLC.json → MultiTaskWS_Config)."


def _detect_webserver() -> str:
    """Return 'Host_<pa-user>' on PythonAnywhere, 'local_<hostname>' elsewhere."""
    home = Path.home()
    if str(home).startswith("/home/"):          # PA Linux home
        return f"Host_{home.name}"
    return f"local_{platform.node()}"


# ── Steps ─────────────────────────────────────────────────────────────────────

def step_reset_db(db: Path) -> None:
    print("\n── Step 0: Reset User Database ─────────────────────────────────")
    if not db.exists():
        print("  No existing DB found — nothing to delete.")
        return
    print(f"  ⚠️  This will permanently delete: {db}")
    print("  All existing user accounts will be lost.")
    confirm = input("  Type YES to confirm: ").strip()
    if confirm != "YES":
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


def step_profile_config(passphrase: str) -> str:
    """Write MultiTaskWS_Config to llcProfile JSON. Returns the new secret key."""
    print("\n── Step 3: MultiTaskWS Config → LLC Profile ────────────────────")
    secret_key = secrets.token_hex(32)
    os.environ["LLC_SECRET_KEY"] = secret_key
    web_server = _detect_webserver()

    cfg = {
        "LLC_SECRET_KEY":    secret_key,
        "LLC_GPG_PASSPHRASE": passphrase,
        "WebServer":         web_server,
    }

    try:
        profile = json.loads(_PROFILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ✗ Could not read {_PROFILE.name}: {exc}")
        sys.exit(1)

    profile["MultiTaskWS_Config"] = cfg
    _PROFILE.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  ✓ Saved MultiTaskWS_Config → {_PROFILE.name}")
    print(f"    LLC_SECRET_KEY    : {secret_key[:16]}…")
    print(f"    LLC_GPG_PASSPHRASE: {'*' * len(passphrase)}")
    print(f"    WebServer         : {web_server}")
    return secret_key


def step_userdb(secret_key: str) -> None:
    print("\n── Step 4 & 5: User Database ───────────────────────────────────")
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

    admin = _find_user(users, _ADMIN_ID)
    if admin:
        admin["notes"] = _ADMIN_NOTE
        print(f"  Updated {_ADMIN_ID} notes.")
    else:
        users.append({
            "username":   _ADMIN_ID,
            "password":   "",
            "full_name":  "webserver admin",
            "phone":      "",
            "role":       "llcManager",
            "notes":      _ADMIN_NOTE,
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        })
        print(f"  + Created {_ADMIN_ID} record.")

    _save_users(LLC_NAME, users)
    print(f"  ✓ Saved → {db}")


def step_wsgi(passphrase: str, secret_key: str) -> None:
    print("\n── Step 6: WSGI Configuration File ────────────────────────────")
    pa_username    = Path.home().name
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
    ap = argparse.ArgumentParser(description="LLC App — MultiTaskWS web server setup")
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
    secret_key = step_profile_config(passphrase)
    step_userdb(secret_key)
    step_wsgi(passphrase, secret_key)

    print("=" * 64)
    print("  Setup complete.")
    print("  → Hit Reload in the PA Web tab.")
    print("  → Visit your PA URL and log in: llcgroupmgr / llcManager0!")
    print()
    print("  Recover credentials any time (plain JSON — no passphrase needed):")
    print(f"    python3 -c \"import json; cfg=json.load(open('{_PROFILE}'))")
    print( "    print(json.dumps(cfg['MultiTaskWS_Config'], indent=2))\"")
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
