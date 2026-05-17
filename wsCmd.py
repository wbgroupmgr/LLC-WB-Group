#!/usr/bin/env python3
"""
wsCmd.py — LLC task app web server management.

The LLC Editor is a task application that runs in two modes:
  local  — Flask dev server on this machine
  hosted — registered with a MultiTaskWS dispatcher (PythonAnywhere)

Provision a new business repo config:
    python3 wsCmd.py --newBus ~/GDrive/Family/Assets/LLC-WBGroup --year 2025

Setup (first time or reset forgotten passphrase):
    python3 wsCmd.py --setup --llcName WBGroupLLC --year 2025
    python3 wsCmd.py --setup --reset --llcName WBGroupLLC --year 2025

Start locally (passphrase auto-loaded from profile after --setup):
    python3 wsCmd.py --start --llcName WBGroupLLC
    python3 wsCmd.py --start --llcName WBGroupLLC --port 5001 --load

Start hosted (MultiTaskWS — placeholder):
    python3 wsCmd.py --start --host --llcName WBGroupLLC
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

# Ensure app root is on sys.path so all packages are importable.
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from ledger import setup_paths as _sp
from ledger.LLC import LLC
from ui.llcLogin_auth import _db_path, _find_user, _hash, _load_users, _save_users


def _latest_config_year(llc_name: str):
    """Return the latest fiscal year that has a config file, or None if none exist."""
    years = _sp.available_years(llc_name)
    return years[0] if years else None

# ── Constants ─────────────────────────────────────────────────────────────────

DEPS = ["flask", "pandas", "numpy", "pypdf", "deepdiff"]

_ADMIN_ID   = "wbgadminWS"
_ADMIN_NOTE = "Config in llcProfile JSON → MultiTaskWS_Config."

_SEED_USER = {
    "username":   "llcgroupmgr",
    "password":   _hash("llcManager0!"),
    "full_name":  "WBGroup LLC",
    "phone":      "",
    "role":       "llcManager",
    "created_at": "2026-01-01T00:00:00",
}


# ── Business provisioning ─────────────────────────────────────────────────────

def provision_new_bus(bus_repo: str, year: int, books_dir: str = "books") -> Path:
    """
    Generate ~/.llcRentalTracker/<llcName>_<year>_config.json for a business repo + year.

    llcName is auto-detected from the repo folder name.
    Returns the path to the written config file.
    """
    bus_path  = Path(bus_repo).expanduser().resolve()
    llc_name  = bus_path.name

    cfg_dir = _sp.TRACKER_CFG_DIR
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / f"{llc_name}_{year}_config.json"

    config = {
        "llcName":   llc_name,
        "bus_repo":  str(bus_path),
        "books_dir": books_dir,
        "year":      year,
    }

    cfg_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    print(f"  ✓ Config written : {cfg_path}")
    print(f"    llcName        : {llc_name}")
    print(f"    bus_repo       : {bus_path}")
    print(f"    books_dir      : {books_dir}")
    print(f"    year           : {year}")
    print(f"\n  Next: python3 wsCmd.py --setup --llcName {llc_name} --year {year}")
    return cfg_path


# ── WsCmd class ───────────────────────────────────────────────────────────────

class WsCmd:
    def __init__(self, llc_name: str, year: int = None):
        self.llc_name = llc_name
        self.year     = year or _latest_config_year(llc_name)
        # LLC object only needed for --start; skip silently if profile missing
        try:
            self.llc = LLC(llc_name, year=self.year)
        except Exception:
            self.llc = None
        self._db      = _db_path(llc_name)
        # Profile lives alongside the ledger DBs in the business repo Accts/
        # (setup_paths.ACCTS_DIR is set by load_config() before WsCmd is instantiated)
        self._profile = _sp.ACCTS_DIR / f"llcProfile_{llc_name}.json"

    # ── internal helpers ──────────────────────────────────────────────────────

    def _inject_env_from_profile(self) -> None:
        """Set LLC_GPG_PASSPHRASE and LLC_SECRET_KEY from llcProfile if not already in env."""
        cfg = getattr(self.llc, "MultiTaskWS_Config", None)
        if not cfg:
            return
        for env_var in ("LLC_GPG_PASSPHRASE", "LLC_SECRET_KEY"):
            if not os.environ.get(env_var) and cfg.get(env_var):
                os.environ[env_var] = cfg[env_var]

    def _webserver_tag(self) -> str:
        home = Path.home()
        if str(home).startswith("/home/"):        # PythonAnywhere Linux
            return f"Host_{home.name}"
        return f"local_{platform.node()}"

    def _load_profile(self) -> dict:
        if not self._profile.exists():
            return {}
        try:
            return json.loads(self._profile.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  ✗ Cannot parse {self._profile.name}: {exc}")
            sys.exit(1)

    def _save_profile(self, profile: dict) -> None:
        self._profile.parent.mkdir(parents=True, exist_ok=True)
        self._profile.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── setup steps ───────────────────────────────────────────────────────────

    def _reset_db(self) -> None:
        print("\n── Step 0: Reset User Database ─────────────────────────────────")
        if not self._db.exists():
            print("  No existing DB found — nothing to delete.")
            return
        print(f"  ⚠️  This will permanently delete: {self._db}")
        print("  All existing user accounts will be lost.")
        if input("  Type YES to confirm: ").strip() != "YES":
            print("  Cancelled — database not deleted.")
            sys.exit(0)
        self._db.unlink()
        print("  ✓ Deleted pw.json.gpg — starting fresh.")

    def _prompt_passphrase(self) -> str:
        print("\n── Step 1: GPG Passphrase ──────────────────────────────────────")
        print("Encrypts the user DB (pw.json.gpg).")
        print("Use the same passphrase every time the server runs.\n")
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

    def _install_deps(self) -> None:
        print("\n── Step 2: Install Dependencies ────────────────────────────────")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "--quiet"] + DEPS
        )
        if result.returncode != 0:
            print(f"  ✗ pip install failed. Run manually:")
            print(f"    pip install --user {' '.join(DEPS)}")
        else:
            print(f"  ✓ {', '.join(DEPS)} ready.")

    def _write_profile_config(self, passphrase: str) -> str:
        print("\n── Step 3: MultiTaskWS_Config → LLC Profile ────────────────────")
        secret_key = secrets.token_hex(32)
        os.environ["LLC_SECRET_KEY"] = secret_key
        tag = self._webserver_tag()

        profile = self._load_profile()
        profile["MultiTaskWS_Config"] = {
            "LLC_SECRET_KEY":     secret_key,
            "LLC_GPG_PASSPHRASE": passphrase,
            "WebServer":          tag,
        }
        self._save_profile(profile)

        print(f"  ✓ Saved MultiTaskWS_Config → {self._profile.name}")
        print(f"    LLC_SECRET_KEY    : {secret_key[:16]}…")
        print(f"    LLC_GPG_PASSPHRASE: {'*' * len(passphrase)}")
        print(f"    WebServer         : {tag}")
        return secret_key

    def _seed_userdb(self) -> None:
        print("\n── Step 4: User Database ───────────────────────────────────────")
        users = []

        if self._db.exists():
            try:
                users = _load_users(self.llc_name)
                print(f"  Found existing DB ({len(users)} user(s)).")
            except Exception as exc:
                print(f"  ✗ Could not read existing DB: {exc}")
                print("    Starting fresh.")

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

        _save_users(self.llc_name, users)
        print(f"  ✓ Saved → {self._db}")

    # ── public commands ───────────────────────────────────────────────────────

    def setup(self, reset: bool = False) -> None:
        """Set up the LLC task app (passphrase, deps, profile config, user DB)."""
        print()
        print("=" * 64)
        print(f"  LLC Task App — Setup  [{self.llc_name}]  year={self.year}")
        print("=" * 64)

        if reset:
            self._reset_db()

        passphrase = self._prompt_passphrase()
        self._install_deps()
        self._write_profile_config(passphrase)
        self._seed_userdb()

        print()
        print("=" * 64)
        print("  Setup complete.")
        print(f"  Credentials stored in: {self._profile.name} → MultiTaskWS_Config")
        print()
        print("  Recover credentials any time (no passphrase needed):")
        print(f"    python3 -c \"import json; print(json.dumps(")
        print(f"      json.load(open('{self._profile}'))['MultiTaskWS_Config'],")
        print( "      indent=2))\"")
        print()
        print("  Start locally (passphrase loaded automatically from profile):")
        print(f"    python3 wsCmd.py --start --llcName {self.llc_name}")
        print("=" * 64)
        print()

    def start(self, host_mode: bool = False, addr: str = "127.0.0.1",
              port: int = 5000, debug: bool = False,
              load: bool = False, ed_opt: str = "llc",
              notebook: bool = False) -> None:
        """Start the LLC task app (local or hosted placeholder)."""
        self._inject_env_from_profile()     # pull creds from llcProfile if not in env

        if host_mode:
            print()
            print("=" * 64)
            print(f"  LLC Task App — Hosted Start  [{self.llc_name}]")
            print()
            print("  [placeholder] Hosted start is managed by the MultiTaskWS")
            print("  dispatcher. The task app is registered via wsgi.py and")
            print("  activated by the PA Web tab → Reload.")
            print("=" * 64)
            print()
            return

        from util.utilEditSession import utilEditSession
        from ui.llcMgmt import llcMgmt

        print()
        print("=" * 64)
        print(f"  LLC Task App — Local Start  [{self.llc_name}]  year={self.year}")
        print(f"  http://{addr}:{port}/login")
        print("=" * 64)

        eSession = utilEditSession(llcName=self.llc_name, year=self.year, load=load, edOpt=ed_opt)
        app = llcMgmt(eSession)
        app.run(host=addr, port=port, debug=debug, notebook=notebook)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wsCmd",
        description="LLC task app web server management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 wsCmd.py --setup --llcName WBGroupLLC
  python3 wsCmd.py --setup --reset --llcName WBGroupLLC
  LLC_GPG_PASSPHRASE=<pp> python3 wsCmd.py --start --llcName WBGroupLLC
  LLC_GPG_PASSPHRASE=<pp> python3 wsCmd.py --start --llcName WBGroupLLC --port 5001 --load
  python3 wsCmd.py --start --host --llcName WBGroupLLC
""",
    )

    ap.add_argument("--llcName", metavar="NAME",
                    help="LLC name, e.g. WBGroupLLC (required for --setup and --start)")
    ap.add_argument("--year", type=int, default=None, metavar="YEAR",
                    help="Fiscal year, e.g. 2025 (required for --newBus; auto-detected for --setup/--start)")

    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--newBus", metavar="BUS_REPO_PATH",
                      help="Provision a new business repo — writes ~/.llcRentalTracker/<name>_<year>_config.json")
    mode.add_argument("--setup", action="store_true",
                      help="Set up the task app (passphrase, deps, user DB)")
    mode.add_argument("--start", action="store_true",
                      help="Start the task app server")

    # --newBus options
    ap.add_argument("--booksDir", default="books", metavar="DIR",
                    help="[--newBus] Accounting sub-directory name (default: books)")

    # --setup options
    ap.add_argument("--reset", action="store_true",
                    help="[--setup] Delete pw.json.gpg before setup")

    # --start options
    ap.add_argument("--host", action="store_true",
                    help="[--start] Hosted MultiTaskWS mode (placeholder)")
    ap.add_argument("--addr", default="127.0.0.1", metavar="IP",
                    help="[--start] Flask bind address (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=5000,
                    help="[--start] Flask port (default: 5000)")
    ap.add_argument("--debug", action="store_true",
                    help="[--start] Enable Flask debug mode")
    ap.add_argument("--load", action="store_true",
                    help="[--start] Load existing working data")
    ap.add_argument("--edOpt", default="llc",
                    metavar="OPT",
                    help="[--start] Editor option: llc | llcAsset | llcExpRev (default: llc)")
    ap.add_argument("--notebook", action="store_true",
                    help="[--start] Jupyter notebook display mode")

    return ap


def main():
    ap   = _build_parser()
    args = ap.parse_args()

    if args.newBus:
        if not args.year:
            ap.error("--year is required for --newBus")
        provision_new_bus(args.newBus, year=args.year, books_dir=args.booksDir)
        return

    if not args.llcName:
        ap.error("--llcName is required for --setup and --start")

    # Resolve year: explicit arg > auto-detect latest config
    year = args.year or _latest_config_year(args.llcName)
    if not year:
        ap.error(
            f"No config found for '{args.llcName}' in {_sp.TRACKER_CFG_DIR}.\n"
            f"  Run first:  python3 wsCmd.py --newBus <bus_repo_path> --year <YEAR>\n"
            f"  Or pass:    --year <YEAR>"
        )

    try:
        _sp.load_config(args.llcName, year)
    except FileNotFoundError:
        print(f"\n  Error: config file not found for '{args.llcName}' year={year}.")
        print(f"  Expected: {_sp.TRACKER_CFG_DIR / f'{args.llcName}_{year}_config.json'}")
        print(f"  Run:  python3 wsCmd.py --newBus <bus_repo_path> --year {year}")
        sys.exit(1)
    ws = WsCmd(args.llcName, year=year)

    if args.setup:
        ws.setup(reset=args.reset)
    else:
        ws.start(
            host_mode=args.host,
            addr=args.addr,
            port=args.port,
            debug=args.debug,
            load=args.load,
            ed_opt=args.edOpt,
            notebook=args.notebook,
        )


if __name__ == "__main__":
    main()
