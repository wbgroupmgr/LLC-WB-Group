"""
Form4562.py
===========
IRS Form 4562 (Depreciation and Amortization) service.

Subclass of irsForm.  Pulls depreciation figures from the official
llcFinancialReport databases (BS: buildings cost / accumulated depreciation;
IS: current-year depreciation expense).

Workflow
--------
    from irs.Form4562 import Form4562
    from ledger.LLC   import LLC

    llc    = LLC()
    f4562  = Form4562(llc=llc, verbose=True)

    nspace   = f4562._buildNSpace()
    f4562.saveNSpace(nspace)

    fillDict = f4562._buildFillDict(nspace)
    f4562.saveFILL(fillDict)

Form 4562 section summary for a real-estate rental LLC
-------------------------------------------------------
  Part I   – §179 deduction         (usually $0 for rental)
  Part II  – Special (bonus) depr.  (CPA review — bonus on new property)
  Part III – MACRS depreciation
    § A    – GDS: each asset class listed by date / cost / method / life / deduction
    § B    – ADS: alternative depreciation system (used if §163(j) RPTOB elected)
  Part IV  – Summary                (Line 22 = total → Form 1065 Line 16a)
  Part V   – Listed property        (vehicles, computers — usually $0)
  Part VI  – Amortization           (startup costs, loan fees)

Auto-filled from FR:
  Line 22  – Total depreciation = is_data.depreciation (→ Form 1065 Line 16a)
  Line 19a – Residential rental, cost = bs_data.buildings
  Line 19b – Accumulated depreciation = bs_data.accum_depr
  Line 19c – Current year deduction = is_data.depreciation

Timestamp of last change: 2026.04.18
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path

try:
    from irs.irsForm import irsForm
except ImportError:
    from irsForm import irsForm


# ════════════════════════════════════════════════════════════════════════════
#  FORM 4562 FIELD MAP
# ════════════════════════════════════════════════════════════════════════════

_FILL_MAP_4562: Dict[str, Dict] = {

    # ── Header ───────────────────────────────────────────────────────────
    "F4562_Nm":  {"source": "entity", "path": "entity_name",
                  "note": "Name(s) shown on return"},
    "F4562_EIN": {"source": "entity", "path": "ein",
                  "note": "Identifying number"},
    "F4562_Biz": {"source": "F1065", "path": "principal_activity",
                  "note": "Business or activity to which this form relates"},

    # ── Part I — Section 179 Deduction ───────────────────────────────────
    # Line 1 — dollar limit (statutory; from instructions)
    # Line 2 — total cost of §179 property
    # Line 11 — business income limitation
    # Line 12 — §179 deduction (enter on applicable line of return)
    "F4562_1":  {"source": "F4562", "path": "limit_179",
                 "note": "§179 dollar limit (statutory, from instructions)"},
    "F4562_12": {"source": "F4562", "path": "deduction_179",
                 "note": "§179 deduction — usually $0 for pure rental LLC"},

    # ── Part III — MACRS Depreciation ────────────────────────────────────
    # Section A — GDS
    # Line 19a — Residential rental property
    #   Column (b) — month/year placed in service
    #   Column (c) — basis for depreciation (cost net of §179/bonus)
    #   Column (e) — recovery period (27.5 yrs for residential)
    #   Column (g) — deduction for this year
    "F4562_19a_cost":  {"source": "BS",  "path": "buildings",
                         "note": "Line 19a (c): Cost / basis of residential rental property"},
    "F4562_19a_accum": {"source": "BS",  "path": "accum_depr",
                         "note": "Line 19a accumulated depreciation (for reference)"},
    "F4562_19a_depr":  {"source": "IS",  "path": "depreciation",
                         "note": "Line 19a (g): Current-year MACRS deduction"},

    # Line 19b — Nonresidential real property (39 yrs)
    # Line 19c — §168(f)(1) / other
    # (both blank for a residential-only rental LLC)

    # ── Part IV — Summary ─────────────────────────────────────────────────
    # Line 22 — total depreciation (= Part II + Part III totals)
    #            → enters Form 1065, Line 16a
    "F4562_22": {"source": "IS", "path": "depreciation",
                 "note": "Line 22: Total depreciation (→ Form 1065 Line 16a)"},

    # Line 40 — amortization (Part VI total)
    # Line 41 — §179 from Part I
    # Line 42 — total deductions (Lines 22 + 40)
    "F4562_42": {"source": "IS", "path": "depreciation",
                 "note": "Line 42: Total deductions (simplified = Line 22 when no §179 or amortization)"},
}

_CPA_NOTES_4562: Dict[str, str] = {
    "F4562_2":    "Line 2: Total cost of §179 property — enter if §179 election made",
    "F4562_3":    "Line 3: Threshold cost for §179 phase-out — statutory",
    "F4562_14":   "Line 14: Special depreciation allowance (bonus) — CPA review for new property",
    "F4562_15":   "Line 15: Property subject to §168(f)(1) election — CPA review",
    "F4562_16":   "Line 16: Other depreciation — CPA review",
    "F4562_19b_cost": "Line 19b: Nonresidential real property cost — CPA review if applicable",
    "F4562_19b_depr": "Line 19b: Nonresidential depreciation — CPA review",
    "F4562_19c_cost": "Line 19c cost — CPA review",
    "F4562_20a":  "Line 20a: GDS class-life assets — list each",
    "F4562_20b":  "Line 20b: 3-year property",
    "F4562_20c":  "Line 20c: 5-year property",
    "F4562_20d":  "Line 20d: 7-year property",
    "F4562_20e":  "Line 20e: 10-year property",
    "F4562_20f":  "Line 20f: 15-year property",
    "F4562_20g":  "Line 20g: 20-year property",
    "F4562_21":   "Line 21: Class lives other — CPA review",
    "F4562_25":   "Line 25: Listed property (§280F) — vehicles/computers",
    "F4562_40":   "Line 40: Amortization of startup/org costs — CPA review",
    "F4562_41":   "Line 41: §179 deduction from Part I",
}


# ════════════════════════════════════════════════════════════════════════════
#  FORM 4562 — irsForm subclass
# ════════════════════════════════════════════════════════════════════════════

class Form4562(irsForm):
    """
    IRS Form 4562 (Depreciation and Amortization) service.

    For a residential real-estate rental LLC the key auto-filled lines are:
      • Line 19a — residential rental property (cost + current-year deduction)
      • Line 22  — total depreciation (→ Form 1065 Line 16a)

    All §179, bonus depreciation, listed property, and amortization lines
    are marked ``publish="CPA:unknown"`` for accountant review.

    ``self.oID = "Form4562"``
    IRS template : {irsDir}/Form4562_IRS.pdf  (or Form_4562-IRS.pdf)
    """

    LOCATION_RULES: List[Tuple[str, str]] = [
        (r'^F4562_Nm|F4562_EIN|F4562_Biz', "Form4562.Header"),
        (r'^F4562_([1-9]|1[0-2])$',         "Form4562.PartI.Sec179"),
        (r'^F4562_1[3-6]$',                  "Form4562.PartII.SpecialDepr"),
        (r'^F4562_17|F4562_18',              "Form4562.PartIII.MACRS.Other"),
        (r'^F4562_19',                        "Form4562.PartIII.MACRS.RealProp"),
        (r'^F4562_20|F4562_21',              "Form4562.PartIII.MACRS.GDS"),
        (r'^F4562_2[2-4]',                   "Form4562.PartIV.Summary"),
        (r'^F4562_2[5-9]|F4562_3[0-9]',     "Form4562.PartV.ListedProp"),
        (r'^F4562_4[0-2]',                   "Form4562.PartVI.Amortization"),
        (r'^F4562_',                          "Form4562.Other"),
    ]

    _FILL_MAP  = _FILL_MAP_4562
    _CPA_NOTES = _CPA_NOTES_4562

    # ── IRS template filename override ────────────────────────────────────
    def FN(self) -> str:
        for name in ("Form4562_IRS.pdf", "Form_4562-IRS.pdf"):
            p = self.irsDir / name
            if p.exists():
                return str(p)
        return str(self.irsDir / "Form4562_IRS.pdf")

    def _loadKeyMap(self) -> Dict[str, str]:
        for name in ("Form4562-keys.pdf", "Form_4562-keys.pdf"):
            p = self.irsDir / name
            if p.exists():
                try:
                    from pypdf import PdfReader
                    rdr = PdfReader(str(p))
                    raw = rdr.get_fields() or {}
                    km: Dict[str, str] = {}
                    for fid, fobj in raw.items():
                        v = fobj.get("/V")
                        if v and str(v).strip() not in ("", "/Off"):
                            short = fid.split(".")[-1].split("[")[0]
                            km[short] = str(v).strip()
                    return km
                except Exception as exc:
                    if self.verbose:
                        print(f"  ⚠️  Keys PDF ({name}): {exc}")
        if self.verbose:
            print(f"  ⚠️  Keys PDF not found for {self.oID}")
        return {}

    def _loadLabelMap(self) -> Dict[str, str]:
        for name in ("Form4562-FieldNames.json", "Form_4562-FieldNames.json"):
            p = self.irsDir / name
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return {str(k): str(v) for k, v in data.items()}
                except Exception:
                    pass
        return {}

    # ════════════════════════════════════════════════════════════════════════
    #  COMBINED STEP: BUILD FILL DICT
    # ════════════════════════════════════════════════════════════════════════

    def _buildFillDict(                             # type: ignore[override]
        self,
        nSpaceDict: Dict,
        is_data:    Optional[Dict] = None,
        bs_data:    Optional[Dict] = None,
        **kwargs,
    ) -> Dict:
        """
        Single-pass fillDict for Form 4562.

        Publish=True for auto-computed lines (19a cost/depr, Line 22).
        Publish="CPA:unknown" for §179, bonus depr, listed property, amortization.
        Publish=False for all other fields.
        """
        # ── Step A: base dict ─────────────────────────────────────────────
        fillDict = super()._buildFillDict(nSpaceDict)

        lk_to_fid: Dict[str, str] = {
            fd["logicalKey"]: fid
            for fid, fd in fillDict.items()
            if fd["logicalKey"]
        }

        # ── Step B: load IS/BS from llcFinancialReport ─────────────────────
        if is_data is None or bs_data is None:
            td = self._resolveTaxData()
            if is_data is None:
                is_data = td.get("is_data", {})
            if bs_data is None:
                bs_data = td.get("bs_data", {})

        # ── Step C: static F4562 profile values ───────────────────────────
        # §179 limit (2025 statutory = $1,220,000; CPA confirms each year)
        f4562_static: Dict = {
            "limit_179":     "1,220,000",
            "deduction_179": "0",        # rental property not eligible
        }

        # ── Step D: load entity / F1065 profile ───────────────────────────
        entity, f1065_data = self._loadProfile()

        src_map: Dict = {
            "entity": entity,
            "F1065":  f1065_data,
            "IS":     is_data   or {},
            "BS":     bs_data   or {},
            "F4562":  f4562_static,
        }

        # ── Step E: apply FILL_MAP ────────────────────────────────────────
        for lk, spec in self._FILL_MAP.items():
            fid = lk_to_fid.get(lk)
            if not fid or fid not in fillDict:
                continue
            ftype = fillDict[fid]["fType"]
            if ftype in ("checkBox", "checkText", "box"):
                value = fillDict[fid].get("checkedValue", "/1")
            else:
                value = self._resolve(spec["source"], spec["path"], src_map) or ""
            fillDict[fid].update({
                "publish": True,
                "source":  spec["source"],
                "path":    spec["path"],
                "note":    spec.get("note", ""),
                "value":   value,
            })

        # ── Step F: apply CPA notes ────────────────────────────────────────
        for lk, note in self._CPA_NOTES.items():
            fid = lk_to_fid.get(lk)
            if not fid or fid not in fillDict:
                continue
            if fillDict[fid].get("publish") is True:
                continue
            fillDict[fid].update({
                "publish": "CPA:unknown",
                "source":  None,
                "path":    None,
                "note":    note,
                "value":   "",
            })

        # ── Diagnostics ───────────────────────────────────────────────────
        if self.verbose:
            pub = sum(1 for v in fillDict.values() if v.get("publish") is True)
            cpa = sum(1 for v in fillDict.values() if v.get("publish") == "CPA:unknown")
            blk = len(fillDict) - pub - cpa
            depr = is_data.get("depreciation", "?")
            cost = bs_data.get("buildings", "?")
            print(f"  ✅ Form4562 fillDict → {len(fillDict)} fields  "
                  f"(publish={pub}, cpa={cpa}, blank={blk})  "
                  f"[depr={depr}, buildings={cost}]")

        return fillDict

    # ── Tax data helpers (inherited from Form1065 → same llcFinancialReport) ─

    def _resolveTaxData(self) -> Dict:
        """
        Return IS/BS/owners from the official llcFinancialReport DB.
        Identical strategy to Form1065._resolveTaxData().
        """
        if self.llc is not None:
            try:
                try:
                    from ledger.llcFinancialReport import llcFinancialReport
                except ImportError:
                    from llcFinancialReport import llcFinancialReport

                fr = llcFinancialReport(self.llc)
                td = json.loads(fr.taxData())
                if self.verbose:
                    depr = td.get("is_data", {}).get("depreciation", "?")
                    cost = td.get("bs_data", {}).get("buildings", "?")
                    print(f"  ℹ️  Form4562 llcFinancialReport loaded  "
                          f"(depreciation={depr}, buildings={cost})")
                return td
            except Exception as exc:
                if self.verbose:
                    print(f"  ⚠️  Form4562 _resolveTaxData failed: {exc}")

        if self.verbose:
            print("  ⚠️  Form4562: self.llc is None — "
                  "pass llc to Form4562() or supply is_data/bs_data kwargs")
        return {"is_data": {}, "bs_data": {}, "owners": {}}
