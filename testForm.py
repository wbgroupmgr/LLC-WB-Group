#!/usr/bin/env python3
"""
testForm.py — BookToIRS full-pipeline diagnostic.

For every bookNS mapping for a given form, shows:
  SRC | fid | pdf_fid | location (form section) | UAS path | resolved value

Usage:
    python3 testForm.py --form Form4562
    python3 testForm.py --form Form8825
    python3 testForm.py --form Form1065
    python3 testForm.py --form Sch_K1
    python3 testForm.py --form Form4562 --llcName WBGroupLLC --year 2025

Also runs a quick sanity check against rptFinancialReport.taxData() so you
can see immediately if BookToIRS and the YE report agree on key values.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt(val) -> str:
    if val is None:
        return "(blank)"
    if isinstance(val, float):
        if val == 0.0:
            return "0.00  ← ZERO"
        return f"{val:,.2f}"
    s = str(val)
    if s == "":
        return "(blank)"
    return s


def _norm_form(name: str) -> str:
    name = name.strip()
    if name.startswith(("Form", "Sch_", "Schedule")):
        return name
    return "Form" + name   # "4562" → "Form4562"


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="BookToIRS pipeline diagnostic — shows all bookNS mappings and resolved values"
    )
    ap.add_argument("--form", required=True,
                    help="Form name: Form4562 | Form8825 | Form1065 | Sch_K1 (or just 4562)")
    ap.add_argument("--llcName", default=None, metavar="NAME")
    ap.add_argument("--year",    default=None, type=int, metavar="YEAR")
    args = ap.parse_args()

    # ── bootstrap ────────────────────────────────────────────────────────────
    from ledger import setup_paths as sp
    if args.llcName and args.year:
        sp.load_config(args.llcName, args.year)
    else:
        sp.load_bootstrap(args.llcName)

    from ledger.LLC import LLC
    llc = LLC(sp.DATA_NAME)

    form_name = _norm_form(args.form)

    # ── build BookToIRS pipeline ──────────────────────────────────────────────
    from irs.BookToIRS import BookToIRS, AID_SOURCES
    aid = BookToIRS(llc, form_name)
    aid._refreshStmtInstances()

    # ── load namespace field info (auto-build if missing) ─────────────────────
    form_cls  = aid._formClass()
    form_inst = form_cls(llc=llc)
    try:
        df_fields = form_inst.loadFieldsDF()
    except FileNotFoundError:
        print(f"  namespace JSON missing — building from IRS PDF...")
        try:
            nspace = form_inst._buildNSpace()
            form_inst.saveNSpace(nspace)
            df_fields = form_inst.loadFieldsDF()
            print(f"  namespace built: {len(nspace.get('fields', {}))} fields")
        except Exception as exc:
            print(f"\nERROR building namespace: {exc}")
            sys.exit(1)

    fid_meta = {}
    for _, row in df_fields.iterrows():
        fid_meta[row["fid"]] = {
            "pdf_fid":   row.get("pdf_fid", ""),
            "shortName": row.get("shortName", ""),
            "pdfField":  row.get("pdfField", ""),
            "location":  row.get("location", ""),
            "page":      row.get("page", ""),
        }

    # ── collect mappings per source ───────────────────────────────────────────
    W = {"src": 9, "fid": 6, "sn": 10, "loc": 30, "uas": 38, "val": 18}
    SEP = "  "

    def _hdr(label):
        return (f"{'SRC':{W['src']}}{SEP}{'fid':{W['fid']}}{SEP}"
                f"{'shortName':{W['sn']}}{SEP}{'location':{W['loc']}}{SEP}"
                f"{'UAS path':{W['uas']}}{SEP}{'value'}")

    print(f"\n{'='*110}")
    print(f"  BookToIRS Diagnostic — {form_name}")
    print(f"  LLC: {llc.objName}   Year: {sp.YEAR}")
    print(f"  bookNS dir: {sp.IRS_FORMS_DIR}")
    print(f"{'='*110}")
    print()
    print(_hdr(""))
    print("-" * 110)

    total_mapped = 0
    total_filled = 0
    total_zero   = 0
    total_blank  = 0

    for src in AID_SOURCES:
        # Raw bookNS entries: [[fid_raw, uas_path], ...]
        raw_pairs = aid.loadBookNS(src)
        if not raw_pairs:
            continue

        # Resolved values from the stmt
        stmt = aid._stmtInstance(src)
        if stmt is None:
            for fid_raw, uas in raw_pairs:
                print(f"  [ERROR] {src}: stmt instance failed — cannot resolve {fid_raw!r}")
            continue

        try:
            fill_dict = stmt.loadFillDict(form_name) or {}
        except Exception as exc:
            print(f"  [ERROR] {src}: loadFillDict raised {exc}")
            continue

        for fid_raw, uas in raw_pairs:
            # Normalize fid to match fill_dict keys
            import re
            m = re.match(r'^[fF]?(\d+)$', str(fid_raw).strip())
            norm_fid = f"F{int(m.group(1)):03d}" if m else str(fid_raw)

            val  = fill_dict.get(norm_fid)
            meta = fid_meta.get(norm_fid, {})
            loc  = (meta.get("location") or "").replace(f"{form_name}.", "")
            sn   = meta.get("shortName") or "?"

            val_str = _fmt(val)
            total_mapped += 1
            if val is None or val == "":
                total_blank += 1
            elif isinstance(val, float) and val == 0.0:
                total_zero += 1
            elif str(val) in ("0", "0.0", "0.00"):
                total_zero += 1
            else:
                total_filled += 1

            print(
                f"{src:{W['src']}}{SEP}"
                f"{norm_fid:{W['fid']}}{SEP}"
                f"{sn:{W['sn']}}{SEP}"
                f"{loc:{W['loc']}}{SEP}"
                f"{str(uas):{W['uas']}}{SEP}"
                f"{val_str}"
            )

    print("-" * 110)
    print(f"\n  Mapped: {total_mapped}   "
          f"Non-zero filled: {total_filled}   "
          f"Zero: {total_zero}   "
          f"Blank: {total_blank}")

    # ── Books sanity check — same stmt instances the pipeline uses ──────────────
    print(f"\n{'='*110}")
    print("  Books sanity check (same stmtIS_Tax / stmtBS_Tax the pipeline resolves from)")
    print(f"{'='*110}")
    is_stmt = aid._stmtInstance("IS")
    bs_stmt = aid._stmtInstance("BS")

    if is_stmt:
        agg = is_stmt.taxAggregates()
        keys_is = ["depreciation", "total_income", "total_expenses", "net_income",
                   "rent_income", "repairs", "utilities", "interest_expense",
                   "other_deductions", "taxes_licenses"]
        print("\n  IS taxAggregates:")
        for k in keys_is:
            if k in agg:
                print(f"    {k:30s} = {_fmt(agg[k])}")
        # direct acct_balance cross-check for depreciation
        depr_bal = is_stmt.acct_balance("Acct.Exp.Depreciation")
        print(f"\n  acct_balance('Acct.Exp.Depreciation') = {_fmt(depr_bal)}")

    if bs_stmt:
        agg = bs_stmt.taxAggregates()
        keys_bs = ["placed_in_service_date", "buildings", "land", "accum_depr",
                   "cash", "mortgage", "ar"]
        print("\n  BS taxAggregates:")
        for k in keys_bs:
            if k in agg:
                print(f"    {k:30s} = {_fmt(agg[k])}")

    print()


if __name__ == "__main__":
    main()
