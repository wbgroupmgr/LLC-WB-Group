#!/usr/bin/env python3
"""
testForm.py — BookToIRS diagnostic CLI.

Delegates entirely to IRSDiagAgent. Output is organized by Section,
blank values are omitted, no location column.

Usage:
    python3 testForm.py --form Form4562
    python3 testForm.py --form Form8825
    python3 testForm.py --form Form1065
    python3 testForm.py --form Sch_K1
    python3 testForm.py --form Form4562 --llcName WBGroupLLC --year 2025
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))


def _norm_form(name: str) -> str:
    name = name.strip()
    if name.startswith(("Form", "Sch_", "Schedule")):
        return name
    return "Form" + name


def main():
    ap = argparse.ArgumentParser(
        description="BookToIRS pipeline diagnostic — calls IRSDiagAgent"
    )
    ap.add_argument("--form", required=True,
                    help="Form name: Form4562 | Form8825 | Form1065 | Sch_K1 (or just 4562)")
    ap.add_argument("--llcName", default=None, metavar="NAME")
    ap.add_argument("--year",    default=None, type=int, metavar="YEAR")
    args = ap.parse_args()

    from ledger import setup_paths as sp
    if args.llcName and args.year:
        sp.load_config(args.llcName, args.year)
    else:
        sp.load_bootstrap(args.llcName)

    from ledger.LLC import LLC
    llc = LLC(sp.DATA_NAME)

    from irs.taxAgents.irsDiagAgent import IRSDiagAgent
    print(IRSDiagAgent(llc, _norm_form(args.form)).diagnose_text())


if __name__ == "__main__":
    main()
