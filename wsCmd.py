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
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Ensure app root is on sys.path so all packages are importable.
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from ledger import setup_paths as _sp
# All heavy imports are lazy — --newBus must work before --setup installs deps.
# Import llcLogin_auth directly (bypasses ui/__init__.py which pulls the whole
# UI package and transitively hits deepdiff via ledgerDB → ledgerObject).
def _lazy_auth():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "llcLogin_auth",
        pathlib.Path(__file__).parent / "ui" / "llcLogin_auth.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
_auth = _lazy_auth()
_db_path      = _auth._db_path
_find_user    = _auth._find_user
_hash         = _auth._hash
_load_users   = _auth._load_users
_save_users   = _auth._save_users
_gpg_decrypt  = _auth._gpg_decrypt
_gpg_encrypt  = _auth._gpg_encrypt


def _latest_config_year(llc_name: str):
    """Return the latest fiscal year registered for llc_name, or None."""
    years = _sp.available_years(llc_name)
    return years[0] if years else None

# ── Constants ─────────────────────────────────────────────────────────────────

DEPS = ["flask", "pandas", "numpy", "pypdf", "deepdiff"]

_ADMIN_ID   = "wbgadminWS"
_ADMIN_NOTE = "Config in ~/.llcRentalTracker/config.json → secrets."

_SEED_USER = {
    "username":   "llcgroupmgr",
    "password":   _hash("llcManager0!"),
    "full_name":  "WBGroup LLC",
    "phone":      "",
    "role":       "llcManager",
    "created_at": "2026-01-01T00:00:00",
}

TRACKER_DICT = {
    "name":        "llcRentalTracker",
    "stanza_key":  "llcRentalTracker",
    "mount":       "/rentalTracker",
    "url":         "/rentalTracker/login",
    "description": "Financial Mgmt App for Property Rental LLC",
    "status":      "online",
    "builtin":     False,
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




# ── Business provisioning ─────────────────────────────────────────────────────

def provision_new_bus(bus_repo: str, year: int, books_dir: str = "books",
                      llc_name: str = None, force: bool = False) -> None:
    """Register a BUS repo and prompt for its APP_GPG_PASSPHRASE.

    Each BUS has its own unique APP_GPG_PASSPHRASE — it must match the passphrase
    used to encrypt that BUS's pw.json.gpg (PA is the authoritative source).
    The last --newBus issued becomes the default for --setup/--start.
    """
    bus_path = Path(bus_repo).expanduser().resolve()
    detected = bus_path.name
    llc_name = llc_name or detected

    if llc_name != detected:
        print(f"  ℹ  llcName overridden: '{detected}' (folder) → '{llc_name}' (--llcName)")

    accts_dir = bus_path / books_dir / "Accts"
    data_name = llc_name
    for p in accts_dir.glob("llcAssets_*.json"):
        candidate = p.stem[len("llcAssets_"):]
        if candidate:
            data_name = candidate
            break
    if data_name != llc_name:
        print(f"  ℹ  dataName auto-detected: '{data_name}' (from Accts files)")

    print()
    print("=" * 64)
    print(f"  --newBus  [{llc_name}]  year={year}")
    print("=" * 64)

    # Check if passphrase already set for this BUS
    cfg      = _sp.read_config()
    existing = next((s for s in cfg.get("llcList", []) if s["llcName"] == llc_name), None)

    if existing and existing.get("APP_GPG_PASSPHRASE") and not force:
        passphrase  = existing["APP_GPG_PASSPHRASE"]
        years_list  = existing.get("years", [])
        print(f"  ✓ APP_GPG_PASSPHRASE already set for {llc_name}")
    else:
        print(f"\n──── APP_GPG_PASSPHRASE for {llc_name} ─────────────────────")
        print(f"  Encrypts {llc_name}/books/Accts/pw.json.gpg.")
        print(f"  Must match the passphrase used on PA (master host).")
        passphrase = _prompt_passphrase_pair(f"APP_GPG_PASSPHRASE for {llc_name}")
        years_list = existing.get("years", []) if existing else []

    if year not in years_list:
        years_list = sorted(set(years_list + [year]), reverse=True)

    stanza = {
        "llcName":            llc_name,
        "dataName":           data_name,
        "bus_repo":           str(bus_path),
        "books_dir":          books_dir,
        "years":              years_list,
        "APP_GPG_PASSPHRASE": passphrase,
    }

    cfg["llcList"] = [s for s in cfg.get("llcList", []) if s["llcName"] != llc_name]
    cfg["llcList"].append(stanza)
    cfg["default"] = [llc_name, year]
    _sp.write_config(cfg)
    _sp.CONFIG_FILE.chmod(0o600)

    print()
    print(f"  ✓ Registered in  : {_sp.CONFIG_FILE}")
    print(f"    llcName        : {llc_name}")
    print(f"    bus_repo       : {bus_path}")
    print(f"    years          : {years_list}")
    print()
    print("  Next step:")
    print(f"    python3 wsCmd.py --setup --llcName {llc_name}")
    print("=" * 64)


# ── WsCmd class ───────────────────────────────────────────────────────────────

class WsCmd:
    def __init__(self, llc_name: str, year: int = None):
        self.llc_name = llc_name
        self.year     = year or _latest_config_year(llc_name)
        # LLC object only needed for --start; lazy-import to avoid pulling deepdiff
        # before --setup has installed it.
        try:
            from ledger.LLC import LLC
            self.llc = LLC(llc_name, year=self.year)
        except Exception:
            self.llc = None
        self._db      = _db_path(llc_name)
        # Profile lives alongside the ledger DBs in the business repo Accts/
        # (setup_paths.ACCTS_DIR is set by load_config() before WsCmd is instantiated)
        self._profile = _sp.ACCTS_DIR / f"llcProfile_{llc_name}.json"

    # ── internal helpers ──────────────────────────────────────────────────────

    def _inject_env_from_profile(self) -> None:
        """Inject LLC_GPG_PASSPHRASE and LLC_SECRET_KEY from config.json. Hard fail if missing."""
        cfg    = _sp.read_config()
        pp     = _sp.SECRETS.get("APP_GPG_PASSPHRASE", "")
        sk     = cfg.get("APP_SECRET_KEY", "")
        if not pp:
            sys.exit(
                f"\nFATAL: APP_GPG_PASSPHRASE missing for '{self.llc_name}' in {_sp.CONFIG_FILE}.\n"
                f"  Run: python3 wsCmd.py --newBus <path> --year {self.year} --llcName {self.llc_name}"
            )
        if not sk:
            sys.exit(
                f"\nFATAL: APP_SECRET_KEY missing from {_sp.CONFIG_FILE}.\n"
                f"  Run: python3 wsCmd.py --setup --llcName {self.llc_name}"
            )
        os.environ.setdefault("LLC_GPG_PASSPHRASE", pp)
        os.environ.setdefault("LLC_SECRET_KEY", sk)

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

    def _ensure_app_secret_key(self) -> str:
        """Generate APP_SECRET_KEY at top-level config if not already set. Returns the key."""
        print("\n── Step 2: APP_SECRET_KEY ──────────────────────────────────────")
        cfg = _sp.read_config()
        sk  = cfg.get("APP_SECRET_KEY", "")
        if sk:
            print(f"  ✓ APP_SECRET_KEY already present — reusing")
            return sk
        sk = secrets.token_hex(32)
        cfg["APP_SECRET_KEY"] = sk
        _sp.write_config(cfg)
        print(f"  ✓ Generated APP_SECRET_KEY → {_sp.CONFIG_FILE}")
        return sk

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


    def addTracker(self) -> None:
        """Register routing entry in ~/.MultiTaskWS/config.json Trackers list (if platform present).

        Writes routing metadata only — NO secrets stanza for external trackers.
        """
        for cfg_name in ("config.json", "MultiTaskWS_config.json"):
            mw_cfg = Path.home() / ".MultiTaskWS" / cfg_name
            if mw_cfg.exists():
                break
        else:
            return  # no platform config — standalone mode, skip silently

        try:
            with open(mw_cfg, "r") as f:
                mw = json.load(f)
            trackers = mw.get("Trackers", [])
            if any(t.get("stanza_key") == TRACKER_DICT["stanza_key"] for t in trackers):
                print(f"  ✓ {TRACKER_DICT['stanza_key']} already in platform Trackers list")
                return
            entry = {
                "name":        TRACKER_DICT["name"],
                "stanza_key":  TRACKER_DICT["stanza_key"],
                "mount":       TRACKER_DICT["mount"],
                "url":         TRACKER_DICT["url"],
                "description": TRACKER_DICT["description"],
                "status":      TRACKER_DICT["status"],
                "builtin":     TRACKER_DICT["builtin"],
                "sys_path":    str(Path(__file__).resolve().parent),
            }
            trackers.append(entry)
            mw["Trackers"] = trackers
            with open(mw_cfg, "w") as f:
                json.dump(mw, f, indent=2)
            print(f"  ✓ Registered in platform config: {mw_cfg}")
        except Exception as err:
            print(f"  WARNING: addTracker failed (OK for standalone): {err}")
            

    # ── PA config helpers ─────────────────────────────────────────────────────

    def _pa_cfg(self) -> dict:
        """Return the 'pa' stanza from config.json, or {} if not set."""
        return _sp.read_config().get("pa", {})

    def _pa_require(self) -> dict:
        """Return PA config, prompting for any missing fields and saving them."""
        cfg = _sp.read_config()
        pa  = cfg.get("pa", {})
        changed = False

        for field, prompt, secret in [
            ("username",  "PA username (e.g. wbgroupmgr)",               False),
            ("api_token", "PA API token (Account → API token on PA)",     True),
            ("domain",    "PA web app domain (e.g. wbgroupmgr.pythonanywhere.com)", False),
            ("llc_repo",  "PA path to llcRentalTracker repo (e.g. /home/wbgroupmgr/llcRentalTracker)", False),
        ]:
            if not pa.get(field):
                val = (getpass.getpass(f"  {prompt}: ").strip() if secret
                       else input(f"  {prompt}: ").strip())
                if not val:
                    sys.exit(f"  ✗ {field} is required.")
                pa[field] = val
                changed = True

        # bus_repos: {llcName: pa_path}
        if not pa.get("bus_repos", {}).get(self.llc_name):
            username = pa["username"]
            default  = f"/home/{username}/LLC-WBGroup"
            val = input(f"  PA path to BUS repo for {self.llc_name} [{default}]: ").strip()
            pa.setdefault("bus_repos", {})[self.llc_name] = val or default
            changed = True

        if changed:
            cfg["pa"] = pa
            _sp.write_config(cfg)
            print(f"  ✓ PA config saved → {_sp.CONFIG_FILE}")

        return pa

    # ── public commands ───────────────────────────────────────────────────────

    def configPA(self) -> None:
        """Interactive: prompt for PA credentials and save to config.json."""
        print()
        print("=" * 64)
        print(f"  Configure PythonAnywhere deployment  [{self.llc_name}]")
        print("=" * 64)
        print()
        print("  API token: https://www.pythonanywhere.com/account/#api_token")
        print()
        pa = self._pa_require()
        print()
        print("  Current PA config:")
        safe = {k: ("***" if k == "api_token" else v) for k, v in pa.items()}
        for k, v in safe.items():
            print(f"    {k}: {v}")
        print()
        print("  Test with:  python3 wsCmd.py --sync --llcName", self.llc_name)
        print("=" * 64)

    def sync(self, dry_run: bool = False) -> None:
        """
        Sync PA deployment from GitHub.

        LLC repo  → git reset --hard origin/main  (code-only, PA never commits)
        BUS repos → auto-commit PA data changes, then git pull --rebase + git push
                    (preserves bookkeeper edits; replays them on top of code commits)

        Reloads the PA web app after a successful sync.
        """
        print()
        print("=" * 64)
        print(f"  PA sync  [{self.llc_name}]  {'(dry run)' if dry_run else ''}")
        print("=" * 64)

        pa        = self._pa_require()
        username  = pa["username"]
        token     = pa["api_token"]
        domain    = pa["domain"]
        llc_repo  = pa["llc_repo"]
        bus_repos = pa.get("bus_repos", {self.llc_name: f"/home/{username}/LLC-WBGroup"})

        script = _build_sync_script(llc_repo, bus_repos)

        if dry_run:
            print("\n  ── sync script (dry run) ──────────────────────────────")
            print(script)
            print("  ── end script ─────────────────────────────────────────")
            return

        print(f"\n  Connecting to PA ({username}.pythonanywhere.com) …")
        try:
            # /webapps/ is available on all PA account tiers (unlike /cpu/ which is paid)
            _pa_req(username, token, "GET", "/webapps")
        except RuntimeError as e:
            sys.exit(
                f"\n  ✗ PA API auth failed: {e}"
                f"\n  Check api_token in {_sp.CONFIG_FILE}"
                f"\n  Get token at: https://www.pythonanywhere.com/account/#api_token"
            )

        print("  Running sync script on PA …")
        output = _pa_run_command(username, token, script, timeout_sec=180)

        # Stream output to terminal
        print()
        for line in output.splitlines():
            print("  |", line)

        if "=== sync error ===" in output:
            print()
            print("  ✗ Sync failed — see output above for details.")
            sys.exit(1)

        print()
        print(f"  Reloading web app ({domain}) …")
        try:
            _pa_reload_webapp(username, token, domain)
            print("  ✓ Web app reloaded.")
        except RuntimeError as e:
            print(f"  ✗ Reload failed: {e}")

        print()
        print("  ✓ Sync complete.")
        print("=" * 64)

    def setup(self, reset: bool = False) -> None:
        """Set up the LLC task app: verify passphrase, generate secret key, seed user DB."""
        print()
        print("=" * 64)
        print(f"  LLC Task App — Setup  [{self.llc_name}]  year={self.year}")
        print("=" * 64)

        if reset:
            self._reset_db()

        # Step 1 — Verify APP_GPG_PASSPHRASE set by --newBus
        print(f"\n── Step 1: APP_GPG_PASSPHRASE for {self.llc_name} ─────────────")
        passphrase = _sp.SECRETS.get("APP_GPG_PASSPHRASE", "")
        if not passphrase:
            sys.exit(
                f"\n  ✗ APP_GPG_PASSPHRASE not found for '{self.llc_name}'.\n"
                f"  Run first: python3 wsCmd.py --newBus <path> --year {self.year} "
                f"--llcName {self.llc_name}"
            )
        os.environ["LLC_GPG_PASSPHRASE"] = passphrase
        print(f"  ✓ APP_GPG_PASSPHRASE loaded for {self.llc_name}")

        # Step 2 — Generate APP_SECRET_KEY (once per tracker, reused across BUS instances)
        secret_key = self._ensure_app_secret_key()
        os.environ["LLC_SECRET_KEY"] = secret_key

        # Step 3 — Install dependencies
        self._install_deps()

        # Step 4 — Seed user DB
        self._seed_userdb()

        # Step 5 — Register with platform (routing only, no secrets stanza)
        self.addTracker()

        print()
        print("=" * 64)
        print("  Setup complete.")
        print(f"  Config: {_sp.CONFIG_FILE}")
        print()
        print("  Start locally:")
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


# ── PythonAnywhere API helpers ────────────────────────────────────────────────

_PA_BASE = "https://www.pythonanywhere.com/api/v0/user/{username}"

def _pa_req(username: str, token: str, method: str, path: str,
            data: dict = None, timeout: int = 30) -> dict:
    """Generic PA API call. Returns parsed JSON or raises on error."""
    url     = (_PA_BASE.format(username=username) + path).rstrip("/") + "/"
    headers = {"Authorization": f"Token {token}",
               "Content-Type":  "application/json"}
    body    = json.dumps(data).encode() if data else None
    req     = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"PA API {method} {path} → HTTP {e.code}: {e.read().decode()[:400]}")


def _pa_run_command(username: str, token: str, bash: str,
                    poll_sec: float = 2.0, timeout_sec: int = 180) -> str:
    """
    Run a bash script on PA via the Consoles API.
    Creates a throwaway Bash console, uploads the script as a file via the
    Files API, then sources it so the console runs it cleanly.
    Polls get_latest_output (which returns ALL output since console start,
    not just the delta) until the sentinel line appears or timeout.
    """
    home = f"/home/{username}"

    # Upload the script to a temp file via Files API so we avoid quoting issues
    script_path = f"{home}/.llcRentalTracker/_sync_run.sh"
    _pa_upload_file(username, token, script_path, bash.encode())

    # Create a new Bash console
    console = _pa_req(username, token, "POST", "/consoles",
                      {"executable": "bash", "arguments": "",
                       "working_directory": home})
    cid = console["id"]

    try:
        # Brief pause so the shell initialises before we send input
        time.sleep(1.5)
        # Source the uploaded script; the shell will echo our sentinels
        _pa_req(username, token, "POST", f"/consoles/{cid}/send_input",
                {"input": f"bash {script_path}\n"})

        # Poll — get_latest_output returns ALL output since console open (not delta)
        deadline = time.time() + timeout_sec
        output   = ""
        while time.time() < deadline:
            time.sleep(poll_sec)
            latest = _pa_req(username, token, "GET",
                             f"/consoles/{cid}/get_latest_output")
            output = latest.get("output", "")   # cumulative, not delta
            if "=== sync done ===" in output or "=== sync error ===" in output:
                break
        return output
    finally:
        # Clean up console and temp script
        try:
            _pa_req(username, token, "DELETE", f"/consoles/{cid}")
        except Exception:
            pass
        try:
            _pa_delete_file(username, token, script_path)
        except Exception:
            pass


def _pa_upload_file(username: str, token: str, pa_path: str, content: bytes) -> None:
    """Upload a file to PA via the Files API (PUT /files/path/{path})."""
    url = f"https://www.pythonanywhere.com/api/v0/user/{username}/files/path{pa_path}"
    req = urllib.request.Request(
        url, data=content,
        headers={"Authorization": f"Token {token}", "Content-Type": "text/plain"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code not in (200, 201):
            raise RuntimeError(f"PA Files upload → HTTP {e.code}: {body}")


def _pa_delete_file(username: str, token: str, pa_path: str) -> None:
    """Delete a file on PA via the Files API."""
    url = f"https://www.pythonanywhere.com/api/v0/user/{username}/files/path{pa_path}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Token {token}"}, method="DELETE"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.HTTPError:
        pass


def _pa_reload_webapp(username: str, token: str, domain: str) -> None:
    """Touch the PA web app reload endpoint."""
    _pa_req(username, token, "POST", f"/webapps/{domain}/reload")


def _build_sync_script(llc_repo: str, bus_repos: dict) -> str:
    """
    Build the bash sync script that runs on PA.

    LLC repo (code only):
      git reset --hard origin/main  — PA never commits here; always safe.

    BUS repos (data + config):
      1. Auto-commit any uncommitted Accts data (bookkeeper edits not yet committed).
      2. git pull --rebase origin main  — replays PA data commits on top of code commits.
         No conflict expected (different file paths). On conflict: abort + report.
      3. git push origin main  — propagate PA data commits back to GitHub.

    Strategy justification:
      rebase > merge for PA because PA's data commits should appear AFTER the
      incoming code commits in the linear history (correct causality: "data was
      entered after the bug was fixed"). Conflicts are rare (data files ≠ code files)
      and surface cleanly with rebase --abort on failure.
    """
    bus_blocks = ""
    for llc_name, bus_path in bus_repos.items():
        bus_blocks += f"""
echo ""
echo "=== BUS sync: {llc_name} ({bus_path}) ==="
cd "{bus_path}"
# Stash .pyc and generated files that don't belong in commits
git ls-files --others --exclude-standard | grep -E '\\.pyc$|\\.pdf$' | head -20 | xargs -r git checkout -- 2>/dev/null || true
# Auto-commit uncommitted bookkeeper data
if ! git diff --quiet -- books/Accts/ 2>/dev/null; then
    git add books/Accts/*.json 2>/dev/null || true
    git diff --staged --quiet || git commit -m "PA data: auto-commit before sync $(date '+%Y-%m-%d %H:%M')"
    echo "  auto-committed PA bookkeeper changes"
fi
# pull --rebase: PA data commits land on top of incoming code commits
git fetch origin
if git rebase origin/main; then
    git push origin main
    echo "  ✓ BUS {llc_name}: $(git log --oneline -1)"
else
    git rebase --abort
    echo "  ✗ BUS {llc_name}: rebase conflict — run manually on PA"
    echo "    cd {bus_path} && git rebase origin/main"
    echo "=== sync error ==="; exit 1
fi
"""

    return f"""#!/bin/bash
set -e
echo "=== PA sync started: $(date '+%Y-%m-%d %H:%M:%S') ==="

echo ""
echo "=== LLC repo sync ({llc_repo}) ==="
cd "{llc_repo}"
git fetch origin
git reset --hard origin/main
echo "  ✓ LLC: $(git log --oneline -1)"
{bus_blocks}
echo ""
echo "=== sync done ==="
"""


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

  # PA deployment (run from local once per session):
  python3 wsCmd.py --configPA --llcName WBGroupLLC        # one-time: save PA creds
  python3 wsCmd.py --sync --llcName WBGroupLLC            # sync + reload
  python3 wsCmd.py --sync --llcName WBGroupLLC --dry-run  # preview script only
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
    mode.add_argument("--addTracker", action="store_true",
                      help="Register this tracker in ~/.MultiTaskWS/config.json Trackers list")
    mode.add_argument("--configPA", action="store_true",
                      help="Save PythonAnywhere credentials (username, API token, paths) to config.json")
    mode.add_argument("--sync", action="store_true",
                      help="Sync PA from GitHub: LLC repo reset --hard; BUS repo pull --rebase + reload")

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

    # --sync options
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="[--sync] Print the sync script without running it")

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

    if args.addTracker:
        WsCmd("").addTracker()
        return

    if not args.llcName:
        ap.error("--llcName is required for --setup, --start, --configPA, and --sync")

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

    if args.configPA:
        ws.configPA()
    elif args.sync:
        ws.sync(dry_run=args.dry_run)
    elif args.setup:
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
