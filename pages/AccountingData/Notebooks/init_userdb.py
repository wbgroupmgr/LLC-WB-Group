#!/usr/bin/env python3
"""
init_userdb.py — create or reset the LLC user database.

Creates Accts/pw.json.gpg with a single seed user:
    username : llcgroupmgr
    password : llcManager0!
    full_name: WBGroup LLC
    role     : llcManager

Run once before starting the server for the first time, or to reset credentials.

Usage:
    export LLC_GPG_PASSPHRASE="your-strong-passphrase"
    python init_userdb.py [--force]

The same passphrase must be set in the environment every time the server runs.
"""

import argparse
import sys
from pathlib import Path

# Ensure Notebooks/ is on sys.path so ledger.setup_paths resolves correctly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui.llcLogin_auth import _db_path, _hash, _gpg_encrypt, _get_passphrase

_SEED_USER = {
    "username":   "llcgroupmgr",
    "password":   _hash("llcManager0!"),
    "full_name":  "WBGroup LLC",
    "phone":      "",
    "role":       "llcManager",
    "created_at": "2026-01-01T00:00:00",
}


def main():
    parser = argparse.ArgumentParser(description="Seed the LLC user database")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing pw.json.gpg without prompting")
    args = parser.parse_args()

    import json
    llc_name = "WBGroupLLC"
    db = _db_path(llc_name)

    if db.exists() and not args.force:
        ans = input(f"{db} already exists. Overwrite? [y/N] ").strip().lower()
        if ans != "y":
            print("Aborted.")
            return

    try:
        passphrase = _get_passphrase()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    plaintext = json.dumps([_SEED_USER], indent=2, ensure_ascii=False).encode()
    try:
        _gpg_encrypt(plaintext, db, passphrase)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Created {db}")
    print(f"  username : {_SEED_USER['username']}")
    print(f"  password : llcManager0!")
    print(f"  role     : {_SEED_USER['role']}")


if __name__ == "__main__":
    main()
