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

Call load_config(llcName, year) once at startup before instantiating any LLC objects.
All path constants below are None until load_config() has been called.
"""

import json
import sys
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


def load_config(llcName: str, year: int) -> dict:
    """Read ~/.llcRentalTracker/<llcName>_<year>_config.json and populate all path constants."""
    global TOP, ACCT_DATA_DIR, ACCTS_DIR, EXPENSES_DIR, IRS_FORMS_DIR, BANK_STMTS, YEAR

    cfg_path = TRACKER_CFG_DIR / f"{llcName}_{year}_config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)

    base  = Path(cfg["bus_repo"]).expanduser().resolve()
    books = base / cfg["books_dir"]
    yr    = int(cfg["year"])

    TOP           = base
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
