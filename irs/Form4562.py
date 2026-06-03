"""
Form4562.py
===========
IRS Form 4562 (Depreciation and Amortization) service.

Form 4562 reports all depreciation and amortization deductions; for a
residential rental LLC the key lines are Part III Line 19h (27.5-year
MACRS for the building) and Part IV Line 22 (total → Form 1065 Line 16a).

Architecture
------------
Form4562 is a thin subclass of ``irsForm``.  The entire fill pipeline is
driven by the ``bookNS_<src>.json`` mapping tables (Form4562 sections) via
``BookToIRS``, exactly as Form8825.  No logicalKey-based _FILL_MAP is used.

Workflow
--------
    from irs.Form4562 import Form4562
    from ledger.LLC   import LLC

    f4562 = Form4562(llc=LLC('WBGroupLLC'))

    nspace   = f4562._buildNSpace()
    f4562.saveNSpace(nspace)

    # The Aid / BookToIRS pipeline produces the FILL.pdf via
    # f4562.aid().regenerate() — see ui/llcBookToIRSAid.regenerate().

Data sources (Form4562 sections in the bookNS files)
----------------------------------------------------
    bookNS_Profile.json  → f2 entity name, f3 EIN, f4 business activity
    bookNS_BS.json       → f69 placed-in-service date, f70 building cost,
                           f71 recovery period, f72 convention, f73 method
    bookNS_IS.json       → f5 §179 limit, f21 §179 deduction, f26 prior MACRS,
                           f74 current-year deduction, f153 Line 22 total

Form 4562 section summary for a real-estate rental LLC
-------------------------------------------------------
  Part I   – §179 deduction         (f5–f21; $0 — buildings excluded by IRC §179(d)(1))
  Part II  – Special (bonus) depr.  (f22–f25; $0 — no separately tracked 5-yr/15-yr assets)
  Part III – MACRS depreciation
    § A    – GDS / residential rental property (f69–f74 for Line 19h)
  Part IV  – Summary                (f153 Line 22 → Form 1065 Line 16a)
  Part V   – Listed property        ($0 — no vehicles/computers)
  Part VI  – Amortization           ($0 — no startup/loan-fee amortization)

Namespace note
--------------
  f1 is the XFA root container (fType=container) and is intentionally excluded
  from fillable fields.  f2 is the first fillable text field ("Name(s) shown on
  return") — this is correct IRS XFA structure, not a numbering error.

Future task: auto-split land value from building cost using the property
tax assessment ratio.  Land is not depreciable and must be excluded from
the basis entered in f70.  Currently requires manual CPA adjustment.

Timestamp of last change: 2026.05.13
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from irs.irsForm import irsForm


# ════════════════════════════════════════════════════════════════════════════
#  FORM 4562 — irsForm subclass
# ════════════════════════════════════════════════════════════════════════════

class Form4562(irsForm):
    """
    IRS Form 4562 service.

    Inherits the full 4-step pipeline from ``irsForm``.
    Per-fid values are resolved entirely by the BookToIRS Aid pipeline;
    no logicalKey-based _FILL_MAP is required.

    ``self.oID = "Form4562"``
    IRS template : ``{irsDir}/Form4562_IRS.pdf``
    """

    LOCATION_RULES: List[Tuple[str, str]] = [
        (r'^P1_Hdr',             "Form4562.Header"),
        (r'^P1_L([1-9]|1[0-2])', "Form4562.PartI.Sec179"),
        (r'^P2_',                "Form4562.PartII.SpecialDepr"),
        (r'^P3_L1[7-8]',         "Form4562.PartIII.MACRS.Other"),
        (r'^P3_L19',             "Form4562.PartIII.MACRS.RealProp"),
        (r'^P3_L2[0-1]',         "Form4562.PartIII.MACRS.GDS"),
        (r'^P4_',                "Form4562.PartIV.Summary"),
        (r'^P5_',                "Form4562.PartV.ListedProp"),
        (r'^P6_',                "Form4562.PartVI.Amortization"),
        (r'^P',                  "Form4562.Other"),
    ]

    _FILL_MAP:  Dict[str, Dict] = {}

    # ── CPA:unknown field-level notes ───────────────────────────────────────
    _CPA_NOTES: Dict[str, str]  = {
        # Part I — §179 (rental buildings excluded)
        "P1_L2":   "Line 2: Total cost of §179 property — enter if §179 election made",
        "P1_L3":   "Line 3: §179 phase-out threshold — statutory",
        # Part II — Special/Bonus depreciation
        "P2_L14":  "Line 14: Special depreciation allowance (bonus) — CPA review for new property",
        "P2_L15":  "Line 15: Property subject to §168(f)(1) election — CPA review",
        "P2_L16":  "Line 16: Other depreciation — CPA review",
        # Part III — non-residential / other classes
        "P3_L19a": "Line 19a: Nonresidential real property — CPA review if applicable",
        "P3_L19b": "Line 19b: Nonresidential depreciation — CPA review",
        "P3_L19c": "Line 19c: §168(f)(1) other — CPA review",
        "P3_L20a": "Line 20a: GDS class-life assets — list each",
        "P3_L20b": "Line 20b: 3-year property",
        "P3_L20c": "Line 20c: 5-year property (appliances — bonus may apply if separately tracked)",
        "P3_L20d": "Line 20d: 7-year property",
        "P3_L20e": "Line 20e: 10-year property",
        "P3_L20f": "Line 20f: 15-year property (land improvements — driveways, fences)",
        "P3_L20g": "Line 20g: 20-year property",
        "P3_L21":  "Line 21: Class lives other — CPA review",
        # Land value advisory
        "P3_L19h_c": (
            "Line 19h (c) basis ($437,950): includes land — land is NOT depreciable. "
            "Subtract land value (property tax assessment ratio or appraisal) before filing. "
            "Auto land-split is a planned future enhancement."
        ),
        # Part V — listed property
        "P5_L25":  "Line 25: Listed property §280F — vehicles/computers",
        # Part VI — amortization
        "P6_L40":  "Line 40: Amortization of startup/org costs — CPA review",
        "P6_L41":  "Line 41: §179 deduction from Part I",
    }

    # ── Per-Part disposition summary (shown in Review modal) ────────────────
    # These are instance methods; the class-level lists below are kept only as
    # a fallback skeleton (no live dollar values).  Always call part_notes() /
    # depr_reconciliation() on an instance to get book-sourced numbers.
    _PART_NOTES: List[Dict[str, str]] = []        # populated by part_notes()
    _DEPR_RECONCILIATION: Dict[str, str] = {}     # populated by depr_reconciliation()

    def _live_depr(self) -> float:
        """Read current-year depreciation from the IS (Acct.Exp.Depreciation)."""
        try:
            from ledger.stmtIS import stmtIS
            return stmtIS(self.llc).taxAggregates().get('depreciation', 0.0)
        except Exception:
            return 0.0

    def part_notes(self) -> List[Dict[str, str]]:
        """Return per-part disposition notes with live depreciation from books."""
        d = self._live_depr()
        d_fmt = f"${d:,.2f}"
        return [
            {
                "part":    "Header (f2–f4)",
                "status":  "auto",
                "summary": "Auto-filled from Profile: LLC name, EIN, business activity code (531110).",
                "detail":  "f2=Name, f3=EIN, f4=business/activity. These are populated by the BookToIRS pipeline from bookNS_Profile.json.",
            },
            {
                "part":    "Part I — §179 Deduction (Lines 1–12)",
                "status":  "zero",
                "summary": "§0 deduction. Residential rental buildings are excluded from §179 by IRC §179(d)(1).",
                "detail":  (
                    "§179 allows immediate 100% expensing of qualifying business property, but "
                    "residential rental real property (the building structure) is explicitly "
                    "excluded. The depreciation in Acct.Fixed.Depreciation.Accum is safe-harbor "
                    "§1.263(a)-3 improvement expensing — it is NOT §179 property. "
                    "Line 1 (dollar limit = $1,220,000) and Line 12 ($0 deduction) are filled; "
                    "all other Part I lines are blank."
                ),
            },
            {
                "part":    "Part II — Special (Bonus) Depreciation (Lines 14–16)",
                "status":  "zero",
                "summary": "$0 currently. No separately-tracked 5-year (appliances) or 15-year (land improvements) assets.",
                "detail":  (
                    "Bonus depreciation (100% in 2025 for qualifying property) does not apply "
                    "to the residential building structure (27.5-year property). It may apply to "
                    "5-year assets (refrigerators, stoves, carpet) or 15-year assets (fences, "
                    "driveways, landscaping) if those were separately purchased. W&B Group "
                    "currently has no such records. CPA review required if cost segregation study "
                    "identifies reclassifiable components."
                ),
            },
            {
                "part":    "Part III — MACRS Depreciation (Lines 17–21, Line 19h)",
                "status":  "auto",
                "summary": f"Line 19h filled: 27.5-yr S/L MM, basis $437,950 (⚠ land not yet split), deduction {d_fmt}.",
                "detail":  (
                    "Line 19h (residential rental, 27.5 yrs, MM convention, S/L method) is the "
                    "core entry. Placed-in-service date: 8/2025. "
                    f"Current deduction (f74) = {d_fmt} sourced from Acct.Exp.Depreciation — "
                    "this is a safe-harbor proxy; the true MACRS Year 1 deduction is ~$4,779 "
                    "after subtracting land (≈20% of $437,950 = $87,590 land; depreciable basis "
                    "≈ $350,360; $350,360 / 27.5 × 4.5/12 = $4,779). "
                    "CRITICAL: f70 basis ($437,950) includes land value — must be corrected "
                    "to depreciable-only basis before filing."
                ),
            },
            {
                "part":    "Part IV — Summary (Line 22)",
                "status":  "auto",
                "summary": f"Line 22 = {d_fmt} (total depreciation) → Form 1065 Line 16a → Form 8825 Line 14.",
                "detail":  (
                    "Line 22 is the sum of all depreciation from Parts II and III. "
                    "For W&B Group this equals the Part III Line 19h deduction. "
                    "This figure flows to: Form 1065 Schedule K Line 16a (depreciation), "
                    "and Form 8825 Line 14 (depreciation expense on the rental property)."
                ),
            },
            {
                "part":    "Part V — Listed Property (Lines 25–36)",
                "status":  "zero",
                "summary": "$0. No vehicles, computers, or §280F listed property used in the rental.",
                "detail":  (
                    "Listed property (vehicles, computers, entertainment equipment) is subject "
                    "to stricter rules under §280F when used for business. A pure residential "
                    "rental LLC with no vehicle or computer assets has nothing to report here."
                ),
            },
            {
                "part":    "Part VI — Amortization (Lines 42–43)",
                "status":  "zero",
                "summary": "$0 currently. No loan origination fees or startup costs separately capitalized.",
                "detail":  (
                    "Common amortizable items for rental LLCs: loan origination points "
                    "(amortized over loan term), mortgage insurance premiums, "
                    "partnership organization costs (§709), and startup costs (§195). "
                    "CPA should confirm whether any of the closing costs include such items. "
                    "If present, they would appear here and also flow to Form 1065 Line 20."
                ),
            },
        ]

    def depr_reconciliation(self) -> Dict[str, str]:
        """Return depreciation reconciliation note with live value from books."""
        d = self._live_depr()
        d_fmt = f"${d:,.2f}"
        return {
            "title": "Depreciation Account Reconciliation",
            "accounts": {
                "Acct.Exp.Depreciation":         f"{d_fmt} (Income Statement — current-year expense)",
                "Acct.Fixed.Depreciation.Accum": f"{d_fmt} (Balance Sheet — accumulated contra-asset)",
            },
            "explanation": (
                f"These two accounts record the same {d_fmt} as safe-harbor §1.263(a)-3 "
                "improvement expensing (pre-rental improvement costs). Safe-harbor expensing "
                "is an OPERATING EXPENSE — it flows to Form 8825 Line 14 (Depreciation), "
                "NOT to §179 (Part I). "
                "§179 is for qualifying EQUIPMENT (personal property), not residential buildings. "
                "The building structure itself requires a separate MACRS entry (~$4,779/yr "
                "Year 1 after land split) that has not yet been booked. "
                "Until that MACRS entry is recorded, Form 4562 Part III and Form 8825 Line 14 "
                f"both show the same {d_fmt} proxy — this is acceptable for Year 1 but should "
                "be reviewed by the CPA before filing."
            ),
            "flow": "Acct.Exp.Depreciation → Form 8825 Line 14 → Form 1065 Sch K Line 2 (rental income/loss)",
            "form4562_flow": "Form 4562 Part III Line 19h (g) → Line 22 → Form 1065 Line 16a",
        }

    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)

    def aid(self) -> "BookToIRS":
        """Factory for the BookToIRS bridge service."""
        from irs.BookToIRS import BookToIRS
        return BookToIRS(self.llc, "Form4562")

    def FN(self) -> str:
        canonical = self.irsDir / f"{self.oID}_IRS.pdf"
        return str(canonical)
