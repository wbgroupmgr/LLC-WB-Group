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
    python3 testForm.py --all
    python3 testForm.py --all --llcName WBGroupLLC --year 2025
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

_ALL_FORMS = ["Form1065", "Form8825", "Form4562", "Sch_K1"]


def _norm_form(name: str) -> str:
    name = name.strip()
    if name.startswith(("Form", "Sch_", "Schedule")):
        return name
    return "Form" + name


def _run_form(llc, form_nm: str) -> None:
    from irs.taxAgents.irsDiagAgent import IRSDiagAgent
    print(IRSDiagAgent(llc, form_nm).diagnose_text())


def main():
    ap = argparse.ArgumentParser(
        description="BookToIRS pipeline diagnostic — calls IRSDiagAgent"
    )
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--form",
                     help="Form name: Form4562 | Form8825 | Form1065 | Sch_K1 (or just 4562)")
    grp.add_argument("--all", action="store_true",
                     help=f"Run all forms: {', '.join(_ALL_FORMS)}")
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

    if args.all:
        for form_nm in _ALL_FORMS:
            print(f"\n{'═'*96}")
            print(f"  ── {form_nm} {'─'*(90 - len(form_nm))}")
            print(f"{'═'*96}")
            _run_form(llc, form_nm)
    else:
        _run_form(llc, _norm_form(args.form))


if __name__ == "__main__":
    main()
