"""
ledger/setup_paths.py
---------------------
Config-driven path resolver for llcRentalTracker.

All filesystem and environment config lives in ONE file:
    ~/.llcRentalTracker/config.json

The profile JSON (llcProfile_<name>.json) holds entity data ONLY —
no paths, no year, no secrets.  Any filesystem key found in the profile
is a migration artifact and is ignored with a DeprecationWarning.

config.json format:
    {
      "default": ["<llcName>", <year>],
      "llcList": [
        {
          "llcName": "...",
          "bus_repo": "<absolute path to LLC-WBGroup>",
          "books_dir": "books",
          "year": 2025,
          "dataName": "...",
          "secrets": {
            "LLC_SECRET_KEY": "...",
            "LLC_GPG_PASSPHRASE": "...",
            "WebServer": "..."
          }
        }
      ]
    }

Call load_config(llcName, year) once at startup (sets module globals).
Call get_default() to read the default (llcName, year) without loading globals.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

_APP_ROOT       = Path(__file__).resolve().parents[1]   # repo root (llcRentalTracker/)
TRACKER_CFG_DIR = Path.home() / ".llcRentalTracker"
CONFIG_FILE     = TRACKER_CFG_DIR / "config.json"

# ── Runtime paths — populated by load_config() ───────────────────────────────
TOP:           Path | None = None   # business repo root (bus_repo in config)
ACCT_DATA_DIR: Path | None = None   # books/
ACCTS_DIR:     Path | None = None   # books/Accts/  (shared across all years)
EXPENSES_DIR:  Path | None = None   # books/<year>/Expenses/
IRS_FORMS_DIR: Path | None = None   # books/<year>/Forms/
BANK_STMTS:    Path | None = None   # books/<year>/BankStmts/
YEAR:          int  | None = None
BOOKS_DIR:     str  | None = None   # "books" (relative name from TOP)
DATA_NAME:     str  | None = None   # suffix used by data files, e.g. "WBGroupLLC"
SECRETS:       dict        = {}     # stanza["secrets"] — LLC_SECRET_KEY, passphrase, etc.


@dataclass
class SessionPaths:
    """Year-specific paths for one active session. Does not touch module globals."""
    accts_dir:     Path
    expenses_dir:  Path
    irs_forms_dir: Path
    bank_stmts:    Path
    year:          int


# ── Unified config I/O ────────────────────────────────────────────────────────

def read_config() -> dict:
    """Read ~/.llcRentalTracker/config.json. Returns empty structure if missing."""
    if not CONFIG_FILE.exists():
        return {"default": None, "llcList": []}
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def write_config(cfg: dict) -> None:
    """Write ~/.llcRentalTracker/config.json."""
    TRACKER_CFG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def write_secrets(llc_name: str, year: int, secrets_dict: dict) -> None:
    """Write secrets into the stanza for (llc_name, year) in config.json."""
    cfg = read_config()
    for stanza in cfg.get("llcList", []):
        if stanza["llcName"] == llc_name and int(stanza["year"]) == year:
            stanza["secrets"] = secrets_dict
            write_config(cfg)
            return
    raise KeyError(
        f"No stanza for {llc_name}/{year} in {CONFIG_FILE}. "
        "Run --newBus first to register the LLC."
    )


def get_default() -> tuple | None:
    """Return (llcName, year) from the default entry, or None if not set."""
    d = read_config().get("default")
    if not d:
        return None
    return (str(d[0]), int(d[1]))


def find_stanza(llc_name: str, year: int) -> dict | None:
    """Return the llcList stanza matching (llc_name, year), or None."""
    for s in read_config().get("llcList", []):
        if s["llcName"] == llc_name and int(s["year"]) == year:
            return s
    return None


# ── Public helpers ────────────────────────────────────────────────────────────

def available_years(llc_name: str) -> list:
    """Return sorted-descending list of fiscal years registered for llc_name."""
    years = [int(s["year"]) for s in read_config().get("llcList", [])
             if s["llcName"] == llc_name]
    # Fallback: scan legacy per-file configs that predate the unified format
    if not years:
        for p in TRACKER_CFG_DIR.glob(f"{llc_name}_*_config.json"):
            stem = p.stem
            part = stem[len(llc_name) + 1:]
            try:
                years.append(int(part.split("_")[0]))
            except (ValueError, IndexError):
                continue
    return sorted(years, reverse=True)


def load_year(llc_name: str, year: int) -> SessionPaths:
    """Return a SessionPaths for (llc_name, year). Does NOT update module globals."""
    stanza = find_stanza(llc_name, year)
    if stanza is None:
        # Fallback to legacy per-file config
        cfg_path = TRACKER_CFG_DIR / f"{llc_name}_{year}_config.json"
        with open(cfg_path, encoding="utf-8") as f:
            stanza = json.load(f)
    base  = Path(stanza["bus_repo"]).expanduser().resolve()
    books = base / stanza["books_dir"]
    yr    = int(stanza["year"])
    return SessionPaths(
        accts_dir     = books / "Accts",                  # shared across all years
        expenses_dir  = books / str(yr) / "Expenses",
        irs_forms_dir = books / str(yr) / "Forms",
        bank_stmts    = books / str(yr) / "BankStmts",
        year          = yr,
    )


def load_bootstrap(llc_name: str = None) -> dict:
    """Load config for llc_name (or the default if omitted) and set module globals."""
    if llc_name is None:
        default = get_default()
        if default is None:
            raise FileNotFoundError(
                f"No default LLC configured in {CONFIG_FILE}. "
                "Run: python3 wsCmd.py --newBus <path> --year <year>"
            )
        return load_config(default[0], default[1])
    years = available_years(llc_name)
    if not years:
        raise FileNotFoundError(f"No config found for {llc_name} in {TRACKER_CFG_DIR}")
    return load_config(llc_name, years[0])


def load_config(llcName: str, year: int) -> dict:
    """Find stanza for (llcName, year) and populate all module-level path constants."""
    global TOP, ACCT_DATA_DIR, ACCTS_DIR, EXPENSES_DIR, IRS_FORMS_DIR, BANK_STMTS, YEAR, BOOKS_DIR, DATA_NAME, SECRETS

    stanza = find_stanza(llcName, year)
    if stanza is None:
        # No silent fallback — fail immediately with a clear diagnosis.
        stanzas = read_config().get("llcList", [])
        names   = [s.get("llcName") for s in stanzas]
        years   = [s.get("year")   for s in stanzas]
        raise FileNotFoundError(
            f"\n[setup_paths] FATAL: '{llcName}/{year}' not found in {CONFIG_FILE}.\n"
            f"  llcList names:  {names}\n"
            f"  llcList years:  {years}\n"
            f"  Fix: add a stanza with llcName='{llcName}' and year={year} to {CONFIG_FILE}.\n"
            f"  Or run: python3 wsCmd.py --newBus <path> --year {year}"
        )
    print(f"[setup_paths] Loaded '{llcName}/{year}' from {CONFIG_FILE} "
          f"→ bus_repo={stanza.get('bus_repo')}")

    base  = Path(stanza["bus_repo"]).expanduser().resolve()
    books = base / stanza["books_dir"]
    yr    = int(stanza["year"])

    TOP           = base
    BOOKS_DIR     = stanza["books_dir"]
    DATA_NAME     = stanza.get("dataName", stanza["llcName"])
    ACCT_DATA_DIR = books
    ACCTS_DIR     = books / "Accts"                  # shared across all years
    EXPENSES_DIR  = books / str(yr) / "Expenses"
    IRS_FORMS_DIR = books / str(yr) / "Forms"
    BANK_STMTS    = books / str(yr) / "BankStmts"
    YEAR          = yr
    SECRETS       = stanza.get("secrets", {})

    app_root = str(_APP_ROOT)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    return stanza


if __name__ == "__main__":
    import datetime as _dt
    llc = sys.argv[1] if len(sys.argv) > 1 else None
    yr  = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if llc and yr:
        load_config(llc, yr)
    else:
        load_bootstrap(llc)
    print(f"TOP           : {TOP}")
    print(f"books         : {ACCT_DATA_DIR}")
    print(f"Accts         : {ACCTS_DIR}")
    print(f"IRS forms     : {IRS_FORMS_DIR}")
    print(f"Bank stmts    : {BANK_STMTS}")
    print(f"Year          : {YEAR}")
