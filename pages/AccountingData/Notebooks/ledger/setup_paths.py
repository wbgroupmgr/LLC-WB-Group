"""
ledger/setup_paths.py
---------------------
Canonical path resolver for the LLC-WB-Group project.

Hierarchy from this file's location:
    parents[0]  →  .../Notebooks/ledger/          (this package)
    parents[1]  →  .../Notebooks/                 (NOTEBOOKS_DIR  — sys.path root)
    parents[2]  →  .../AccountingData/             (ACCT_DATA_DIR)
    parents[3]  →  .../pages/
    parents[4]  →  .../LLC-WB-Group/               (TOP)

Usage — from any script or notebook:
    import sys, os
    sys.path.insert(0, '<path-to-Notebooks>')  # only if not already on path
    from ledger import setup_paths

    # or, from inside the ledger package:
    from . import setup_paths

Path constants exposed:
    setup_paths.TOP             LLC-WB-Group root
    setup_paths.NOTEBOOKS_DIR   Notebooks/
    setup_paths.ACCT_DATA_DIR   AccountingData/
    setup_paths.ACCTS_DIR       AccountingData/Accts/
    setup_paths.EXPENSES_DIR    AccountingData/Expenses/
    setup_paths.BANK_STMTS_2025 AccountingData/2025/BankStmts/
    setup_paths.BANK_STMTS_2026 AccountingData/2026/BankStmts/
    setup_paths.TAX_RECORDS_2025 AccountingData/2025/YE_Tax_Records/
    setup_paths.IRS_FORMS_DIR   .../YE_Tax_Records/Forms_IRS/
"""

import sys
from pathlib import Path

_here = Path(__file__).resolve()

# ── Core anchors (parents[N] from this file) ─────────────────────────────────
TOP           = _here.parents[4]   # LLC-WB-Group/
NOTEBOOKS_DIR = _here.parents[1]   # Notebooks/
ACCT_DATA_DIR = _here.parents[2]   # AccountingData/

# ── Data sub-directories ─────────────────────────────────────────────────────
ACCTS_DIR        = ACCT_DATA_DIR / "Accts"
EXPENSES_DIR     = ACCT_DATA_DIR / "Expenses"
BANK_STMTS_2025  = ACCT_DATA_DIR / "2025" / "BankStmts"
BANK_STMTS_2026  = ACCT_DATA_DIR / "2026" / "BankStmts"
TAX_RECORDS_2025 = ACCT_DATA_DIR / "2025" / "YE_Tax_Records"
IRS_FORMS_DIR    = TAX_RECORDS_2025 / "Forms_IRS"

# ── Ensure Notebooks/ is on sys.path so sibling packages are importable ──────
if str(NOTEBOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(NOTEBOOKS_DIR))


if __name__ == "__main__":
    _pkgs = ["ledger", "irs", "F1065_K1", "uillc", "util"]
    print(f"TOP            : {TOP}")
    print(f"Notebooks root : {NOTEBOOKS_DIR}")
    print(f"AccountingData : {ACCT_DATA_DIR}")
    print(f"Accts dir      : {ACCTS_DIR}")
    print(f"Bank stmts 2025: {BANK_STMTS_2025}")
    print(f"Bank stmts 2026: {BANK_STMTS_2026}")
    print(f"IRS forms dir  : {IRS_FORMS_DIR}")
    print("\nPackages importable from Notebooks/:")
    for pkg in _pkgs:
        status = "✓" if (NOTEBOOKS_DIR / pkg).is_dir() else "✗ (not found)"
        print(f"  {status}  {pkg}")
