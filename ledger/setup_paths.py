"""
ledger/setup_paths.py
---------------------
Config-driven path resolver for llcRentalTracker.

All filesystem and environment config lives in ONE file:
    ~/.llcRentalTracker/config.json

The profile JSON (llcProfile_<name>.json) holds entity data ONLY —
no paths, no year, no secrets.

config.json format (M BUS × N years):
    {
      "default":        ["<llcName>", <year>],
      "APP_SECRET_KEY": "<one Flask signing key for this llcRentalTracker instance>",
      "llcList": [
        {
          "llcName":            "WBGroupLLC",
          "dataName":           "WBGroupLLC",
          "bus_repo":           "<absolute path to LLC-WBGroup>",
          "books_dir":          "books",
          "years":              [2025, 2026],
          "APP_GPG_PASSPHRASE": "<unique passphrase — sole key for this BUS pw.json.gpg>"
        }
      ]
    }

APP_SECRET_KEY  — per-tracker (one Flask signing key for the whole app)
APP_GPG_PASSPHRASE — per-BUS (each BUS encrypts its own pw.json.gpg independently)

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

# ── Runtime globals — populated by load_config() ─────────────────────────────
TOP:           Path | None = None   # business repo root (bus_repo in config)
ACCT_DATA_DIR: Path | None = None   # books/
ACCTS_DIR:     Path | None = None   # books/Accts/  (shared across all years)
EXPENSES_DIR:  Path | None = None   # books/<year>/Expenses/
IRS_FORMS_DIR: Path | None = None   # books/<year>/Forms/
BANK_STMTS:    Path | None = None   # books/<year>/BankStmts/
YEAR:          int  | None = None
BOOKS_DIR:     str  | None = None   # "books" (relative name from TOP)
DATA_NAME:     str  | None = None   # suffix used by data files, e.g. "WBGroupLLC"
SECRETS:       dict        = {}     # { APP_GPG_PASSPHRASE, APP_SECRET_KEY } for active BUS


@dataclass
class SessionPaths:
    """Year-specific paths for one active session. Does not touch module globals."""
    accts_dir:     Path
    expenses_dir:  Path
    irs_forms_dir: Path
    bank_stmts:    Path
    year:          int


# ── Config I/O ────────────────────────────────────────────────────────────────

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


def write_secrets(llc_name: str, secrets_dict: dict) -> None:
    """Write APP_GPG_PASSPHRASE to the BUS stanza and APP_SECRET_KEY to top level."""
    cfg = read_config()
    updated = False
    for stanza in cfg.get("llcList", []):
        if stanza["llcName"] == llc_name:
            if "APP_GPG_PASSPHRASE" in secrets_dict:
                stanza["APP_GPG_PASSPHRASE"] = secrets_dict["APP_GPG_PASSPHRASE"]
            updated = True
    if not updated:
        raise KeyError(
            f"No stanza for '{llc_name}' in {CONFIG_FILE}. "
            "Run --newBus first to register the LLC."
        )
    if "APP_SECRET_KEY" in secrets_dict:
        cfg["APP_SECRET_KEY"] = secrets_dict["APP_SECRET_KEY"]
    write_config(cfg)


def get_default() -> tuple | None:
    """Return (llcName, year) from the default entry, or None if not set."""
    d = read_config().get("default")
    if not d:
        return None
    return (str(d[0]), int(d[1]))


def find_stanza(llc_name: str, year: int) -> dict | None:
    """Return the llcList stanza matching (llc_name, year), or None.

    Supports both old scalar 'year' field and new array 'years' field.
    """
    for s in read_config().get("llcList", []):
        if s["llcName"] != llc_name:
            continue
        years_field = s.get("years")
        if years_field is not None:
            if year in years_field:
                return s
        elif s.get("year") == year:
            return s
    return None


def find_bus_stanza(llc_name: str) -> dict | None:
    """Return the llcList stanza for llc_name (any year), or None."""
    for s in read_config().get("llcList", []):
        if s["llcName"] == llc_name:
            return s
    return None


# ── Public helpers ────────────────────────────────────────────────────────────

def available_years(llc_name: str) -> list:
    """Return sorted-descending list of fiscal years registered for llc_name."""
    years = []
    for s in read_config().get("llcList", []):
        if s["llcName"] != llc_name:
            continue
        if "years" in s:
            years.extend(int(y) for y in s["years"])
        elif "year" in s:
            years.append(int(s["year"]))
    return sorted(set(years), reverse=True)


def load_year(llc_name: str, year: int) -> SessionPaths:
    """Return a SessionPaths for (llc_name, year). Does NOT update module globals."""
    stanza = find_stanza(llc_name, year)
    if stanza is None:
        raise FileNotFoundError(
            f"No stanza for '{llc_name}/{year}' in {CONFIG_FILE}. "
            "Run --newBus to register."
        )
    base  = Path(stanza["bus_repo"]).expanduser().resolve()
    books = base / stanza["books_dir"]
    return SessionPaths(
        accts_dir     = books / "Accts",
        expenses_dir  = books / str(year) / "Expenses",
        irs_forms_dir = books / str(year) / "Forms",
        bank_stmts    = books / str(year) / "BankStmts",
        year          = year,
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
        raise FileNotFoundError(f"No config found for '{llc_name}' in {TRACKER_CFG_DIR}")
    return load_config(llc_name, years[0])


def load_config(llcName: str, year: int) -> dict:
    """Find stanza for (llcName, year) and populate all module-level path constants."""
    global TOP, ACCT_DATA_DIR, ACCTS_DIR, EXPENSES_DIR, IRS_FORMS_DIR, BANK_STMTS, YEAR, BOOKS_DIR, DATA_NAME, SECRETS

    stanza = find_stanza(llcName, year)
    if stanza is None:
        stanzas = read_config().get("llcList", [])
        names   = [s.get("llcName") for s in stanzas]
        raise FileNotFoundError(
            f"\n[setup_paths] FATAL: '{llcName}/{year}' not found in {CONFIG_FILE}.\n"
            f"  llcList names: {names}\n"
            f"  Run: python3 wsCmd.py --newBus <path> --year {year} --llcName {llcName}"
        )

    cfg = read_config()
    print(f"[setup_paths] Loaded '{llcName}/{year}' from {CONFIG_FILE} "
          f"→ bus_repo={stanza.get('bus_repo')}")

    base  = Path(stanza["bus_repo"]).expanduser().resolve()
    books = base / stanza["books_dir"]

    TOP           = base
    BOOKS_DIR     = stanza["books_dir"]
    DATA_NAME     = stanza.get("dataName", stanza["llcName"])
    ACCT_DATA_DIR = books
    ACCTS_DIR     = books / "Accts"
    EXPENSES_DIR  = books / str(year) / "Expenses"
    IRS_FORMS_DIR = books / str(year) / "Forms"
    BANK_STMTS    = books / str(year) / "BankStmts"
    YEAR          = year
    SECRETS       = {
        "APP_GPG_PASSPHRASE": stanza.get("APP_GPG_PASSPHRASE", ""),
        "APP_SECRET_KEY":     cfg.get("APP_SECRET_KEY", ""),
    }

    app_root = str(_APP_ROOT)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    return stanza


if __name__ == "__main__":
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
    print(f"SECRETS keys  : {list(SECRETS.keys())}")
