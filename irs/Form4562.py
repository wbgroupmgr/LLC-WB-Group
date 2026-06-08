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

    # Patterns match against XFA shortName (f1_N / c1_N / f2_N).
    # Field sequence verified against the 2025 Form 4562 IRS PDF (published Jan 2026).
    #
    # 2025 Form 4562 confirmed field layout — verified from IRS XFA accessibility labels.
    #
    # Header (same row: Name | BizCode | EIN):
    #   f1  = f1_1  = Name(s) shown on return (x=12.7mm, w=76.2mm)
    #   f2  = f1_2  = Business/activity (x=88.9mm, w=81.28mm) ← wider, description
    #   f3  = f1_3  = Identifying number / EIN (x=170.18mm, w=33mm) ← narrow, right-most
    #   f4  = f1_4  = Part I Line 1: §179 dollar limit
    #
    # 2025 FORM CHANGE — Line numbering shifted in Part III Section B:
    #   Line19h = "50-year property" (NEW in 2025) — f69–f74 — col(d) readOnly "50 yrs."
    #   Line19i = "Residential rental property" (WAS Line19h in prior forms) — f75–f86
    #             Line19i_1 (f75-f80): Row 1 of 2 — col(d) readOnly "27.5 yrs."
    #             Line19i_2 (f81-f86): Row 2 of 2 (second property slot)
    #   Line19j = "Nonresidential real property" (WAS Line19i) — f87–f98
    #             Line19j_1 (f87-f92): Row 1, col(d) readOnly "39 yrs."
    #             Line19j_2 (f93-f98): Row 2
    #
    # Cols (d)/(e)/(f) in Lines 19h/19i/19j are readOnly pre-printed values in XFA.
    # Only cols (b) and (c) and (g) need to be filled from books.
    LOCATION_RULES: List[Tuple[str, str]] = [
        # Header: Name (f1_1), BizCode (f1_2), EIN (f1_3)
        (r'^f1_[1-3]$',                              "Form4562.Header"),
        # Part I §179 (Lines 1–13): f1_4..f1_21 = our f4..f21
        (r'^f1_([4-9]|1\d|2[01])$',                 "Form4562.PartI.Sec179"),
        # Part II Special/Bonus depreciation: Lines 14–17 (f1_22..f1_25) + c1_* checkboxes
        (r'^f1_2[2-5]$',                             "Form4562.PartII.SpecialDepr"),
        (r'^c1_',                                    "Form4562.PartII.SpecialDepr"),
        # Part III Section B Lines 19a–19g (3yr–25yr): f1_26..f1_67 = our f27..f68
        (r'^f1_(2[6-9]|[3-5]\d|6[0-7])$',           "Form4562.PartIII.MACRS.Other"),
        # Part III Section B Line 19h: 50-year property (2025 form, NEW)
        # Cols (d)/(e)/(f) are readOnly pre-printed "50 yrs / MM / S/L" — do NOT fill them.
        (r'^f1_(6[89]|7[0-3])$',                     "Form4562.PartIII.MACRS.50yr"),
        # Part III Section B Line 19i: Residential Rental — 27.5yr GDS, MM, S/L
        # Line19i_1 (f75-f80) = Row 1; Line19i_2 (f81-f86) = Row 2 (second property slot)
        # Cols (d)/(e)/(f) are readOnly pre-printed "27.5 yrs / MM / S/L" — do NOT fill them.
        # Fill only: col (b) placed-in-service date, col (c) basis, col (g) deduction.
        # IRC §168(c)(1): 27.5yr for residential rental. IRC §168(d)(2): MM convention.
        (r'^f1_(7[4-9]|8[0-5])$',                   "Form4562.PartIII.MACRS.Line19i"),
        # Part III Section B Line 19j: Nonresidential real property — 39yr GDS
        # Line19j_1 (f87-f92) = Row 1; Line19j_2 (f93-f98) = Row 2
        (r'^f1_(8[6-9]|9[0-7])$',                   "Form4562.PartIII.MACRS.Other"),
        # Part III Section C ADS (Lines 20a-20e): f1_98..f1_127 = our f99..f128
        (r'^f1_(9[89]|1[01]\d|12[0-7])$',           "Form4562.PartIII.MACRS.ADS"),
        # Page 2 standalone fields before checkboxes:
        #   f2_1(F129)=Line 21 listed-property (Part IV, blank for W&B Group)
        #   f2_2(F130)=Line 22 total depreciation (Part IV Summary — the fill target)
        #   f2_3, f2_4 = adjacent Part IV/V fields
        (r'^f2_[1-4]$',                              "Form4562.PartIV.Summary"),
        # Page 2 — Part V Listed Property (Table_Ln26) + Part VI Amortization
        (r'^f2_',                                    "Form4562.PartV.ListedProp"),
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
                "part":    "Header (f1–f3)",
                "status":  "auto",
                "summary": "Auto-filled from Profile: LLC name, EIN, business activity code (531110).",
                "detail":  "f1=Name (f1_1), f2=EIN (f1_2), f3=business/activity (f1_3). Populated by BookToIRS from bookNS_Profile.json.",
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
                "part":    "Part III — MACRS Depreciation (Line 19i: Residential Rental)",
                "status":  "auto",
                "summary": f"Line 19i filled: 27.5-yr S/L MM (pre-printed), basis net-tangible, deduction {d_fmt}.",
                "detail":  (
                    "2025 Form 4562 change: residential rental moved to Line 19i (was Line 19h in prior years). "
                    "Line 19h is now '50-year property'. Line 19i (XFA: Line19i_1, f75-f80) is "
                    "'Residential rental property, 27.5yr GDS, MM, S/L'. "
                    "Cols (d)/(e)/(f) are pre-printed readOnly by the IRS — only cols (b) and (c) and (g) are filled. "
                    "f75=placed-in-service date, f76=depreciable basis (net tangible, land excluded), "
                    f"f80=deduction={d_fmt} from Acct.Exp.Depreciation. "
                    "CRITICAL: f76 basis must exclude land value (IRC §167; Treas. Reg. §1.167(a)-2)."
                ),
            },
            {
                "part":    "Part IV — Summary (Line 22)",
                "status":  "auto",
                "summary": f"Line 22 (f130/f2_2) = {d_fmt} → Form 1065 Line 16a → Form 8825 Line 14.",
                "detail":  (
                    "Page 2 standalone fields: f2_1(f129)=Line 21 'Listed property' (blank — no §280F assets). "
                    "f2_2(f130)=Line 22 total depreciation — the Part IV summary field. "
                    "f153 (f2_18 inside Table_Ln26) is Part V Listed Property table — leave blank. "
                    "Line 22 = sum of Parts II + III. For W&B Group equals Line 19i col(g) = IS.depreciation. "
                    "Flows to: Form 1065 Schedule K Line 16a, Form 8825 Line 14."
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
