"""
ledger/setup_paths.py
---------------------
Config-driven path resolver for llcRentalTracker.

Per-business config lives at:
    ~/.llcRentalTracker/<llcName>_<year>_config.json

Fields:
    bus_repo   — absolute path to the LLC business repo
    books_dir  — subdirectory name for accounting books (e.g. "books")
    year       — fiscal year (int)

Call load_config(llcName, year) once at startup (sets module globals).
Use load_year(llcName, year) to get a SessionPaths without touching module globals.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

_APP_ROOT       = Path(__file__).resolve().parents[1]   # repo root (llcRentalTracker/)
TRACKER_CFG_DIR = Path.home() / ".llcRentalTracker"

# ── Runtime paths — populated by load_config() ───────────────────────────────
TOP:           Path | None = None   # business repo root
ACCT_DATA_DIR: Path | None = None   # books/
ACCTS_DIR:     Path | None = None   # books/<year>/Accts/
EXPENSES_DIR:  Path | None = None   # books/<year>/Expenses/
IRS_FORMS_DIR: Path | None = None   # books/<year>/Forms/
BANK_STMTS:    Path | None = None   # books/<year>/BankStmts/
YEAR:          int  | None = None
BOOKS_DIR:     str  | None = None   # "books" (relative name from TOP)
DATA_NAME:     str  | None = None   # suffix used by data files, e.g. "WBGroupLLC"


@dataclass
class SessionPaths:
    """Year-specific paths for one active session. Does not touch module globals."""
    accts_dir:     Path
    expenses_dir:  Path
    irs_forms_dir: Path
    bank_stmts:    Path
    year:          int


def available_years(llc_name: str) -> list:
    """Return sorted-descending list of fiscal years that have a config file."""
    years = []
    for p in TRACKER_CFG_DIR.glob(f"{llc_name}_*_config.json"):
        stem = p.stem                          # e.g. "WBGroupLLC_2025_config"
        part = stem[len(llc_name) + 1:]       # e.g. "2025_config"
        try:
            years.append(int(part.split("_")[0]))
        except (ValueError, IndexError):
            continue
    return sorted(years, reverse=True)


def load_year(llc_name: str, year: int) -> SessionPaths:
    """Return a SessionPaths for (llc_name, year). Does NOT update module globals."""
    cfg_path = TRACKER_CFG_DIR / f"{llc_name}_{year}_config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)
    base  = Path(cfg["bus_repo"]).expanduser().resolve()
    books = base / cfg["books_dir"]
    yr    = int(cfg["year"])
    return SessionPaths(
        accts_dir     = books / str(yr) / "Accts",
        expenses_dir  = books / str(yr) / "Expenses",
        irs_forms_dir = books / str(yr) / "Forms",
        bank_stmts    = books / str(yr) / "BankStmts",
        year          = yr,
    )


def load_bootstrap(llc_name: str) -> dict:
    """Load config for the latest available year and set module globals."""
    years = available_years(llc_name)
    if not years:
        raise FileNotFoundError(f"No config found for {llc_name} in {TRACKER_CFG_DIR}")
    return load_config(llc_name, years[0])


def load_config(llcName: str, year: int) -> dict:
    """Read ~/.llcRentalTracker/<llcName>_<year>_config.json and populate all path constants."""
    global TOP, ACCT_DATA_DIR, ACCTS_DIR, EXPENSES_DIR, IRS_FORMS_DIR, BANK_STMTS, YEAR, BOOKS_DIR, DATA_NAME

    cfg_path = TRACKER_CFG_DIR / f"{llcName}_{year}_config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)

    base  = Path(cfg["bus_repo"]).expanduser().resolve()
    books = base / cfg["books_dir"]
    yr    = int(cfg["year"])

    TOP           = base
    BOOKS_DIR     = cfg["books_dir"]
    DATA_NAME     = cfg.get("dataName", cfg["llcName"])
    ACCT_DATA_DIR = books
    ACCTS_DIR     = books / str(yr) / "Accts"
    EXPENSES_DIR  = books / str(yr) / "Expenses"
    IRS_FORMS_DIR = books / str(yr) / "Forms"
    BANK_STMTS    = books / str(yr) / "BankStmts"
    YEAR          = yr

    app_root = str(_APP_ROOT)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    return cfg


if __name__ == "__main__":
    import datetime as _dt
    llc = sys.argv[1] if len(sys.argv) > 1 else "WBGroupLLC"
    yr  = int(sys.argv[2]) if len(sys.argv) > 2 else _dt.datetime.now().year
    load_config(llc, yr)
    print(f"TOP           : {TOP}")
    print(f"books         : {ACCT_DATA_DIR}")
    print(f"Accts         : {ACCTS_DIR}")
    print(f"IRS forms     : {IRS_FORMS_DIR}")
    print(f"Bank stmts    : {BANK_STMTS}")
    print(f"Year          : {YEAR}")
