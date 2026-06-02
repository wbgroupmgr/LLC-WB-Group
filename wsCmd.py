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
from ui.llcLogin_auth import (_db_path, _find_user, _hash, _load_users,
                               _save_users, _gpg_decrypt, _gpg_encrypt)


def _latest_config_year(llc_name: str):
    """Return the latest fiscal year registered for llc_name, or None."""
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

# Used by addTracker
MULTITASKWS_CONFIG_BN = '.MultiTaskWS/MultiTaskWS_config.json'
TRACKER_DICT = {
      "name": "llcRentalTracker",
      "mount": "/rentalTracker",
      "url": "/rentalTracker/",
      "description": "rentalTracker : Financial Mgmt App for Property Rental LLC",
      "status": "online",
      "builtin": False,
      "stanza_key": "rentalTracker"
    }


# ── Bootstrap helpers ─────────────────────────────────────────────────────────

def _prompt_passphrase_pair(label: str, min_len: int = 12) -> str:
    """Prompt for a passphrase with confirmation. Returns the passphrase."""
    while True:
        pp = getpass.getpass(f"  Enter {label} (min {min_len} chars): ").strip()
        if len(pp) < min_len:
            print(f"  ✗ Too short — at least {min_len} characters required.")
            continue
        if getpass.getpass(f"  Confirm {label}: ").strip() != pp:
            print("  ✗ Passphrases do not match — try again.")
            continue
        return pp


def _ensure_master_passphrase(force: bool = False) -> str:
    """
    Read master_passphrase from ~/.llcRentalTracker/config.json.
    If config.json does not exist, lacks the key, or force=True, prompt and store it.
    Returns the master passphrase.
    """
    cfg = _sp.read_config()
    if not force and cfg.get("master_passphrase"):
        print("  ✓ MASTER passphrase loaded from config.json")
        return cfg["master_passphrase"]
    if force:
        cfg.pop("master_passphrase", None)
        _sp.write_config(cfg)

    print("\n──── MASTER Passphrase ────────────────────────────────────────")
    print("  Encrypts keys.json.gpg. Needed on every host that runs the app.")
    print("  Stored in ~/.llcRentalTracker/config.json (never in any repo).")
    pp = _prompt_passphrase_pair("MASTER passphrase")
    cfg["master_passphrase"] = pp
    _sp.write_config(cfg)
    _sp.CONFIG_FILE.chmod(0o600)
    print(f"  ✓ Stored in {_sp.CONFIG_FILE} (chmod 600)")
    return pp


def _ensure_keys(accts_dir: Path, master_pp: str, force: bool = False) -> dict:
    """
    Ensure books/Accts/keys.json.gpg exists and is decryptable with master_pp.
    If force=True, delete any existing file and recreate from a fresh prompt.
    Returns the decrypted keys dict.
    """
    keys_file = accts_dir / "keys.json.gpg"

    if force and keys_file.exists():
        keys_file.unlink()
        print(f"  ✓ Deleted existing {keys_file.name}")

    if keys_file.exists():
        try:
            data = json.loads(_gpg_decrypt(keys_file, master_pp).decode("utf-8"))
            print(f"  ✓ keys.json.gpg decrypted — secrets loaded")
            return data
        except Exception as exc:
            print(f"  ✗ Cannot decrypt {keys_file.name}: {exc}")
            print("    Check that your MASTER passphrase matches the one used to create it.")
            sys.exit(1)

    print("\n──── App Passphrase (LLC_GPG_PASSPHRASE) ──────────────────────")
    print("  Encrypts the user DB (pw.json.gpg). Shared across all platforms")
    print("  via keys.json.gpg — set it once, never change unless rotating keys.")
    gpg_pp     = _prompt_passphrase_pair("app passphrase")
    secret_key = secrets.token_hex(32)

    keys = {"LLC_GPG_PASSPHRASE": gpg_pp, "LLC_SECRET_KEY": secret_key}
    accts_dir.mkdir(parents=True, exist_ok=True)
    _gpg_encrypt(json.dumps(keys, indent=2).encode("utf-8"), keys_file, master_pp)

    print(f"  ✓ Created {keys_file}")
    print()
    print("  ⚠  Push keys.json.gpg to GitHub BEFORE running --setup:")
    print(f"     cd {accts_dir.parent.parent}")
    print(f"     git add {keys_file.relative_to(accts_dir.parent.parent)}")
    print( "     git commit -m 'feat: initial keys.json.gpg'")
    print( "     git push")
    return keys


# ── Business provisioning ─────────────────────────────────────────────────────

def provision_new_bus(bus_repo: str, year: int, books_dir: str = "books",
                      llc_name: str = None, force: bool = False) -> None:
    """
    Add a business stanza to ~/.llcRentalTracker/config.json and set it as default.

    llcName defaults to the repo folder name but can be overridden via --llcName.
    The last --newBus issued becomes the default for wsgi.py and --setup/--start.
    """
    bus_path = Path(bus_repo).expanduser().resolve()
    detected = bus_path.name
    llc_name = llc_name or detected

    if llc_name != detected:
        print(f"  ℹ  llcName overridden: '{detected}' (folder) → '{llc_name}' (--llcName)")

    # Auto-detect dataName from existing Accts files (single shared DB under books/Accts/)
    accts_dir = bus_path / books_dir / "Accts"
    data_name = llc_name
    for p in accts_dir.glob("llcAssets_*.json"):
        stem = p.stem
        candidate = stem[len("llcAssets_"):]
        if candidate:
            data_name = candidate
            break
    if data_name != llc_name:
        print(f"  ℹ  dataName auto-detected: '{data_name}' (from Accts files)")

    # ── Bootstrap MASTER passphrase + keys.json.gpg ──────────────────────────
    print()
    print("=" * 64)
    print(f"  --newBus Bootstrap  [{llc_name}]  year={year}"
          + ("  [--F force]" if force else ""))
    print("=" * 64)

    if force:
        # Delete pw.json.gpg upfront so it is recreated below
        pw_file = accts_dir / "pw.json.gpg"
        if pw_file.exists():
            pw_file.unlink()
            print(f"  ✓ Deleted existing pw.json.gpg")

    master_pp = _ensure_master_passphrase(force=force)
    keys      = _ensure_keys(accts_dir, master_pp, force=force)

    # With --F: recreate pw.json.gpg with the fresh LLC_GPG_PASSPHRASE
    if force:
        pw_file = accts_dir / "pw.json.gpg"
        _gpg_encrypt(
            json.dumps([dict(_SEED_USER)], indent=2).encode("utf-8"),
            pw_file,
            keys["LLC_GPG_PASSPHRASE"],
        )
        print(f"  ✓ Created pw.json.gpg  (seed user: llcgroupmgr / llcManager0!)")
        print(f"    Push this file to GitHub after --newBus completes.")

    # ── Register stanza ───────────────────────────────────────────────────────
    stanza = {
        "llcName":   llc_name,
        "dataName":  data_name,
        "bus_repo":  str(bus_path),
        "books_dir": books_dir,
        "year":      year,
    }

    cfg = _sp.read_config()
    # Replace existing entry for same (llcName, year) if present
    cfg["llcList"] = [s for s in cfg.get("llcList", [])
                      if not (s["llcName"] == llc_name and int(s["year"]) == year)]
    cfg["llcList"].append(stanza)
    cfg["default"] = [llc_name, year]
    _sp.write_config(cfg)

    print()
    print(f"  ✓ Registered in  : {_sp.CONFIG_FILE}")
    print(f"    llcName        : {llc_name}")
    print(f"    bus_repo       : {bus_path}")
    print(f"    books_dir      : {books_dir}")
    print(f"    year           : {year}")
    print()
    print("  Next steps:")
    print("    1. git add books/Accts/keys.json.gpg && git push  (if just created)")
    print(f"   2. python3 wsCmd.py --setup --llcName {llc_name}")
    print("    3. git add books/Accts/pw.json.gpg && git push")
    print("=" * 64)


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
        if input("  Type YES to confirm: ").strip().upper() != "YES":
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


    def addTracker(self):
        """Add this tracker's stanza into ~/.MultiTaskWS/MultiTaskWS_config.json."""
        cFN = os.path.join(Path.home(), MULTITASKWS_CONFIG_BN)
        try:
            with open(cFN, 'r') as fio:
                cfgDict = json.load(fio)
            tList = cfgDict['Trackers']
            if any(tDict['name'] == TRACKER_DICT['name'] for tDict in tList):
                return
            entry = dict(TRACKER_DICT,
                         sys_path=str(Path(__file__).resolve().parent))
            cfgDict['Trackers'].append(entry)
            with open(cFN, 'w') as fio:
                json.dump(cfgDict, fio, indent=2)
        except Exception as err:
            print(f"WARNING: wsCmd -- addTracker failed.  Ok for local, needed for MultiTaskWS", err)
            

    # ── public commands ───────────────────────────────────────────────────────

    def setup(self, reset: bool = False) -> None:
        """Set up the LLC task app (passphrase, deps, profile config, user DB)."""
        print()
        print("=" * 64)
        print(f"  LLC Task App — Setup  [{self.llc_name}]  year={self.year}")
        print("=" * 64)

        if reset:
            self._reset_db()

        # Prefer keys.json.gpg path (new design); fall back to manual prompt
        keys_file = _sp.ACCTS_DIR / "keys.json.gpg" if _sp.ACCTS_DIR else None
        if keys_file and keys_file.exists():
            master_pp = _sp.read_config().get("master_passphrase", "")
            if not master_pp:
                master_pp = _ensure_master_passphrase()
            keys = _ensure_keys(_sp.ACCTS_DIR, master_pp)
            passphrase = keys.get("LLC_GPG_PASSPHRASE", "")
            os.environ["LLC_GPG_PASSPHRASE"] = passphrase
            secret_key = keys.get("LLC_SECRET_KEY", secrets.token_hex(32))
            os.environ["LLC_SECRET_KEY"] = secret_key
            print(f"\n── Step 1: Secrets from keys.json.gpg ──────────────────────")
            print(f"  ✓ LLC_GPG_PASSPHRASE loaded")
            print(f"  ✓ LLC_SECRET_KEY     loaded")
        else:
            passphrase = self._prompt_passphrase()   # legacy path (no keys.json.gpg)
            secret_key = None

        self._install_deps()
        # Write profile; if we got secret_key from keys.json.gpg, use it
        if secret_key:
            print("\n── Step 3: MultiTaskWS_Config → LLC Profile ────────────────────")
            tag = self._webserver_tag()
            profile = self._load_profile()
            profile["MultiTaskWS_Config"] = {
                "LLC_SECRET_KEY":     secret_key,
                "LLC_GPG_PASSPHRASE": passphrase,
                "WebServer":          tag,
            }
            self._save_profile(profile)
            print(f"  ✓ Saved MultiTaskWS_Config → {self._profile.name}")
        else:
            self._write_profile_config(passphrase)
        self._seed_userdb()
        self.addTracker()

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
                    help="LLC name matching data file suffix, e.g. WBGroupLLC. "
                         "Required for --setup/--start. Optional for --newBus (overrides folder-name auto-detect).")
    ap.add_argument("--year", type=int, default=None, metavar="YEAR",
                    help="Fiscal year, e.g. 2025 (required for --newBus; auto-detected for --setup/--start)")

    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--newBus", metavar="BUS_REPO_PATH",
                      help="Register a business repo — adds stanza to ~/.llcRentalTracker/config.json and sets it as default")
    mode.add_argument("--setup", action="store_true",
                      help="Set up the task app (passphrase, deps, user DB)")
    mode.add_argument("--start", action="store_true",
                      help="Start the task app server")

    # --newBus options
    ap.add_argument("--booksDir", default="books", metavar="DIR",
                    help="[--newBus] Accounting sub-directory name (default: books)")
    ap.add_argument("--F", action="store_true", dest="force",
                    help="[--newBus] Force full-stack re-creation: "
                         "clears config.json master_passphrase, deletes and "
                         "recreates keys.json.gpg and pw.json.gpg from fresh prompts")

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
        provision_new_bus(args.newBus, year=args.year, books_dir=args.booksDir,
                          llc_name=args.llcName, force=args.force)
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
