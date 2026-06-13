#!/usr/bin/env python3
"""
testForm.py — BookToIRS diagnostic CLI.

Usage:
    python3 testForm.py --form Form4562
    python3 testForm.py --form Form8825
    python3 testForm.py --form Form1065
    python3 testForm.py --form Sch_K1 --m 1
    python3 testForm.py --form Sch_K1 --all --m 1
    python3 testForm.py --form Form4562 --all
    python3 testForm.py --form Form4562 --llcName WBGroupLLC --year 2025

Flags:
    --form     Form name: Form4562 | Form8825 | Form1065 | Sch_K1 (or bare 4562)
    --all      Show ALL fields including blank/unmapped (default: skip blank)
    --m N      Member number (1-based) for Sch_K1; default=1 (first partner)
    --llcName  LLC identifier; defaults to bootstrap config
    --year     Tax year integer; defaults to bootstrap config
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))


_VALID_FORMS = {"Form4562", "Form8825", "Form1065", "Sch_K1"}

# Common typo aliases → canonical form name
_ALIASES = {"1069": "Form1065", "Form1069": "Form1065"}


def _norm_form(name: str) -> str:
    name = name.strip()
    if name in _ALIASES:
        canonical = _ALIASES[name]
        print(f"[testform] NOTE: '{name}' not a valid form — assuming '{canonical}'", flush=True)
        return canonical
    if name.startswith(("Form", "Sch_", "Schedule")):
        return name
    return "Form" + name


def main():
    ap = argparse.ArgumentParser(
        description="BookToIRS pipeline diagnostic — calls IRSDiagAgent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--form", required=True,
                    help="Form4562 | Form8825 | Form1065 | Sch_K1 (or bare number)")
    ap.add_argument("--all", dest="show_all", action="store_true",
                    help="Show ALL fields including blank/unmapped")
    ap.add_argument("--m", dest="member", type=int, default=1, metavar="N",
                    help="Member number (1-based) for Sch_K1; default=1")
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

    form_nm     = _norm_form(args.form)
    if form_nm not in _VALID_FORMS:
        print(f"ERROR: unknown form '{form_nm}'. Valid: {', '.join(sorted(_VALID_FORMS))}", file=sys.stderr)
        sys.exit(1)
    partner_idx = max(0, args.member - 1)   # convert 1-based CLI → 0-based index

    from irs.taxAgents.irsDiagAgent import IRSDiagAgent
    print(IRSDiagAgent(llc, form_nm).diagnose_text(
        show_all=args.show_all, partner_idx=partner_idx))


if __name__ == "__main__":
    main()
