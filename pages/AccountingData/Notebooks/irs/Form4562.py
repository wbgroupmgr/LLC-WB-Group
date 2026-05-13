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
  Part I   – §179 deduction         (f5–f21; usually $0 for rental)
  Part II  – Special (bonus) depr.  (f22–f25; CPA review)
  Part III – MACRS depreciation
    § A    – GDS / residential rental property (f69–f74 for Line 19h)
  Part IV  – Summary                (f153 Line 22 → Form 1065 Line 16a)
  Part V   – Listed property        (usually $0)
  Part VI  – Amortization           (f308 Line 42, f309 Line 43)

Future task: auto-split land value from building cost using the property
tax assessment ratio.  Land is not depreciable and must be excluded from
the basis entered in f70.  Currently requires manual CPA adjustment.

Timestamp of last change: 2026.05.12
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
    _CPA_NOTES: Dict[str, str]  = {
        # Part I — §179 (rental property not eligible)
        "P1_L2":   "Line 2: Total cost of §179 property — enter if §179 election made",
        "P1_L3":   "Line 3: §179 phase-out threshold — statutory",
        # Part II — Special/Bonus depreciation
        "P2_L14":  "Line 14: Special depreciation allowance (bonus) — CPA review for new property",
        "P2_L15":  "Line 15: Property subject to §168(f)(1) election — CPA review",
        "P2_L16":  "Line 16: Other depreciation — CPA review",
        # Part III — non-residential / other classes
        "P3_L19a": "Line 19a: Nonresidential real property cost — CPA review if applicable",
        "P3_L19b": "Line 19b: Nonresidential depreciation — CPA review",
        "P3_L19c": "Line 19c: §168(f)(1) other — CPA review",
        "P3_L20a": "Line 20a: GDS class-life assets — list each",
        "P3_L20b": "Line 20b: 3-year property",
        "P3_L20c": "Line 20c: 5-year property (appliances — bonus may apply)",
        "P3_L20d": "Line 20d: 7-year property",
        "P3_L20e": "Line 20e: 10-year property",
        "P3_L20f": "Line 20f: 15-year property (land improvements — driveways, fences)",
        "P3_L20g": "Line 20g: 20-year property",
        "P3_L21":  "Line 21: Class lives other — CPA review",
        # Part V — listed property
        "P5_L25":  "Line 25: Listed property §280F — vehicles/computers",
        # Part VI — amortization
        "P6_L40":  "Line 40: Amortization of startup/org costs — CPA review",
        "P6_L41":  "Line 41: §179 deduction from Part I",
        # Land value advisory — future auto-split task
        "P3_L19h_c": (
            "Line 19h basis: land value must be excluded before entry. "
            "CPA: confirm land/building split via property tax assessment or appraisal. "
            "Auto land-split is a planned future enhancement."
        ),
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
