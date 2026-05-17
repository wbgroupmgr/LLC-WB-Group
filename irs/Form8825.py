"""
Form8825.py
===========
IRS Form 8825 (Rental Real Estate Income & Expenses of a Partnership or
S Corporation) service.

Form 8825 is the partnership-side analogue of Schedule E (Form 1040).
It captures all rental-property gross rents and operating expenses; the
final Line 21 net flows into ``Schedule K, Line 2`` of Form 1065.

Architecture
------------
Form8825 is a thin subclass of ``irsForm`` — it delegates the entire
4-step pipeline (build namespace → save namespace + worksheet PDF →
build fillDict → save FILL.pdf) to the base class. Just like Form1065,
the per-fid value resolution is driven by the ``bookNS_<src>.json``
mapping tables (Form8825 sections), so the form benefits from every
service the Aid (``ui/llcBookToIRSAid.py``) provides without any
class-side wiring.

Workflow
--------
    from irs.Form8825 import Form8825
    from ledger.LLC   import LLC

    f8825 = Form8825(llc=LLC('WBGroupLLC'))

    nspace   = f8825._buildNSpace()           # discover AcroForm fields
    f8825.saveNSpace(nspace)                  # → Form8825_namespace.{json,pdf}

    # The Aid / BookToIRS pipeline produces the FILL.pdf via
    # f8825.saveFILL_FromDF(...) — see ui/llcBookToIRSAid.regenerate().

Data sources (Form8825 sections in the bookNS files)
----------------------------------------------------
    bookNS_Profile.json   → Property address + type code + LLC name/EIN
    bookNS_BS.json        → Depreciation (accumulated, per-row)
    bookNS_IS.json        → Gross rents + operating expenses + totals
    bookNS_GL.json        → (none today — fallback)

Per the simple W&B Group example: $4,000 rental income, no operating
expenses, ~$5,246 depreciation. The Aid renders this as Lines 1, 2,
14, 16, 17, 21 plus the per-property total on Line 20a.

Timestamp of last change: 2026.05.03
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from irs.irsForm import irsForm


# ════════════════════════════════════════════════════════════════════════════
#  FORM 8825 — irsForm subclass
# ════════════════════════════════════════════════════════════════════════════

class Form8825(irsForm):
    """
    IRS Form 8825 service.

    Inherits the full 4-step pipeline from ``irsForm``:

        nspace   = f._buildNSpace()
        f.saveNSpace(nspace)
        fillDict = f._buildFillDict(nspace)   # publish + value resolution
        f.saveFILL(fillDict)

    ``self.oID = "Form8825"``  (drives all file names)
    IRS template : ``{irsDir}/Form8825_IRS.pdf``
    """

    # Lightweight location-derivation rules.  The Form8825 PDF only has two
    # pages: Page 1 holds Properties A–D; Page 2 holds Properties E–H plus
    # the partnership totals (Lines 18–21).  Containers (Table_Line1, RowA…
    # RowH, Col_a…Col_e) are excluded by the base ``_buildNSpace``.
    LOCATION_RULES: List[Tuple[str, str]] = [
        # Page 1
        (r'^P1_Hdr',                 "Form8825.Pg1.Header"),
        (r'^P1_Prop',                "Form8825.Pg1.PropertyDetail"),
        (r'^P1_L(1[0-6])',           "Form8825.Pg1.Expenses"),
        (r'^P1_L([0-9])',            "Form8825.Pg1.Income"),
        (r'^P1_',                    "Form8825.Pg1.Other"),
        # Page 2 — totals + roll-up rows
        (r'^P2_L(2[01])',            "Form8825.Pg2.Totals"),
        (r'^P2_L(1[7-9]|18[a-c])',   "Form8825.Pg2.NetIncome"),
        (r'^P2_',                    "Form8825.Pg2.Other"),
    ]

    # Form8825 has no per-logicalKey FILL_MAP today — the Aid drives every
    # value through the bookNS path.  Subclasses that want logicalKey-based
    # rendering (like Form1065) override these.
    _FILL_MAP:  Dict[str, Dict] = {}
    _CPA_NOTES: Dict[str, str]  = {
        # Lines that intentionally have no automatic mapping.  Surfaced as
        # advisory chips in the Aid dialog when the operator views them.
        "P1_L15a":  "Line 15a description (text) — type the expense category here",
        "P1_L18a":  "Net gain (loss) from Form 4797 — CPA review (rare for hold-to-rent LLC)",
        "P1_L18b":  "Form 4684 casualty/theft — CPA review",
        "P2_L19":   "Net rental real estate income before passive activity limits — CPA review",
    }

    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)

    def aid(self) -> "BookToIRS":
        """Factory for the BookToIRS bridge service.  Delegates all Aid
        operations (read/write mappings, regenerate) to this bridge instance."""
        from irs.BookToIRS import BookToIRS
        return BookToIRS(self.llc, "Form8825")

    # ── IRS template filename override (matches Form1065 convention) ──────
    def FN(self) -> str:
        canonical = self.irsDir / f"{self.oID}_IRS.pdf"
        return str(canonical)
