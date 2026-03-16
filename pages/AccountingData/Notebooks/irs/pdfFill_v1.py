"""
form1065_filler.py
==================
Python class that fills an IRS Form 1065 PDF (U.S. Return of Partnership Income)
from a plain Python dict.

- Paid Preparor Accredidation - see pages/IRAGuide/IRS_TaxPreparersAccredidation

Supports two fill modes
-----------------------
1. FILLABLE  – The official IRS PDF already has AcroForm fields (most versions do).
               The class detects field names and writes values directly.
2. OVERLAY   – Falls back to ReportLab coordinate-based text overlay when a field
               is not found in the AcroForm, or when given a flat/scanned PDF.

Quick start
-----------
    from form1065_filler import Form1065Filler, build_1065_dict_from_gl

    # Build from GL (uses the Form1065Preparer output dict)
    data = build_1065_dict_from_gl(gl_dict, entity_name="Sunset Ridge Rentals LLC",
                                   ein="12-3456789", tax_year=2024)

    filler = Form1065Filler("f1065.pdf")          # official IRS PDF
    filler.fill(data)
    filler.save("Form_1065_Filled.pdf")

    # Or use the all-in-one method (also creates a blank template):
    Form1065Filler.fill_from_dict("f1065.pdf", data, "Form_1065_Filled.pdf")

Dict keys
---------
All keys are optional; missing keys are silently skipped.

  ── ENTITY HEADER ──────────────────────────────────────────────────────────
  entity_name        str   Partnership / LLC name
  ein                str   XX-XXXXXXX
  tax_year           int   2024
  address            str   Street address
  city_state_zip     str   City, State ZIP
  principal_product  str   Principal product or service
  business_code      str   6-digit business activity code
  date_business_began str  MM/DD/YYYY
  total_assets       str   Total assets (Schedule L line 6)
  number_of_k1s      int   Number of Schedules K-1 attached

  ── PAGE 1 – INCOME ─────────────────────────────────────────────────────────
  line_1a            float  Gross receipts (rents)
  line_1b            float  Returns and allowances
  line_1c            float  Net (1a minus 1b)  – auto-computed if omitted
  line_2             float  Cost of goods sold
  line_3             float  Gross profit
  line_4             float  Ordinary income/(loss) from other partnerships
  line_5             float  Net farm profit/(loss)
  line_6             float  Net gain/(loss) Form 4797
  line_7             float  Other income/(loss)
  line_8             float  Total income – auto-computed if omitted

  ── PAGE 1 – DEDUCTIONS ─────────────────────────────────────────────────────
  line_9             float  Salaries and wages
  line_10            float  Guaranteed payments to partners
  line_11            float  Repairs and maintenance
  line_12            float  Bad debts
  line_13            float  Rent
  line_14            float  Taxes and licenses
  line_15            float  Interest
  line_16a           float  Depreciation (Form 4562)
  line_16b           float  Depreciation claimed elsewhere
  line_16c           float  Subtract 16b from 16a
  line_17            float  Depletion
  line_18            float  Retirement plans etc.
  line_19            float  Employee benefit programs
  line_20            float  Other deductions (attach schedule)
  line_21            float  Total deductions – auto-computed if omitted
  line_22            float  Ordinary business income/(loss) – auto-computed

  ── SIGNATURE BLOCK ─────────────────────────────────────────────────────────
  preparer_name      str
  preparer_ptin      str
  preparer_firm      str
  preparer_phone     str
  preparer_date      str   MM/DD/YYYY

  ── SCHEDULE B (selected questions) ────────────────────────────────────────
  sch_b_1_entity_type   str  "domestic_general" | "domestic_limited" |
                              "domestic_llc" | "foreign"
  sch_b_2a_yes          bool  Publicly traded partnership?
  sch_b_3a_yes          bool  Any partner a disregarded entity?

  ── SCHEDULE K (distributive share) ────────────────────────────────────────
  k_line_1           float  Ordinary income/(loss)
  k_line_2           float  Net rental real estate income
  k_line_5           float  Interest income
  k_line_6a          float  Ordinary dividends
  k_line_7           float  Royalties
  k_line_8           float  Net short-term capital gain/(loss)
  k_line_9a          float  Net long-term capital gain/(loss)
  k_line_11          float  Other income/(loss)
  k_line_12          float  Section 179 deduction
  k_line_13a         float  Contributions
  k_line_18          float  Tax-exempt interest income
  k_line_19a         float  Distributions of cash
  k_line_20          float  Other items

  ── SCHEDULE L (balance sheet) ──────────────────────────────────────────────
  l_cash_beg          float  Cash – beginning
  l_cash_end          float  Cash – end
  l_ar_beg            float  Accounts receivable – beg
  l_ar_end            float  Accounts receivable – end
  l_other_assets_beg  float  Other current assets – beg
  l_other_assets_end  float  Other current assets – end
  l_fixed_assets_beg  float  Fixed assets (cost) – beg
  l_fixed_assets_end  float  Fixed assets (cost) – end
  l_total_assets_beg  float  Total assets – beg
  l_total_assets_end  float  Total assets – end
  l_ap_beg            float  Accounts payable – beg
  l_ap_end            float  Accounts payable – end
  l_partners_cap_beg  float  Partners' capital – beg
  l_partners_cap_end  float  Partners' capital – end
  l_total_liab_beg    float  Total liabilities & capital – beg
  l_total_liab_end    float  Total liabilities & capital – end

  ── SCHEDULE M-1 ────────────────────────────────────────────────────────────
  m1_line_1          float  Net income per books
  m1_line_9          float  Income per return

  ── SCHEDULE M-2 ────────────────────────────────────────────────────────────
  m2_beg_capital      float  Beginning capital
  m2_capital_contrib  float  Capital contributed
  m2_net_income       float  Net income per books
  m2_distributions    float  Distributions
  m2_end_capital      float  Ending capital account

Dependencies
------------
  pip install pypdf reportlab
"""

from __future__ import annotations

import io
import os
import re
import copy
from typing import Any, Dict, List, Optional, Tuple

# ── pypdf ────────────────────────────────────────────────────────────────────
try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        NameObject, create_string_object, ArrayObject,
        DictionaryObject, BooleanObject, NumberObject,
        IndirectObject,
    )
    _PYPDF = True
except ImportError:
    _PYPDF = False

# ── reportlab (overlay fallback) ────────────────────────────────────────────
try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    _REPORTLAB = True
except ImportError:
    _REPORTLAB = False


# ════════════════════════════════════════════════════════════════════════════
#  FIELD MAP  –  dict_key  →  (acroform_field_name, page, x, y, w, h)
#
#  acroform_field_name : exact string used in IRS AcroForm (None = overlay only)
#  page                : 1-based page number
#  x, y, w, h          : ReportLab overlay coords in points (1 pt = 1/72 inch)
#                        origin = bottom-left of page
#  IRS Form 1065 (2023) letter-size pages:  612 × 792 pts
# ════════════════════════════════════════════════════════════════════════════

# Each entry: dict_key -> (acroform_name, page, x, y, w, h, font_size)
# acroform_name is None for fields with no AcroForm equivalent.

FIELD_MAP: Dict[str, Tuple[Optional[str], int, float, float, float, float, int]] = {

    # ── ENTITY HEADER  (page 1) ──────────────────────────────────────────────
    "entity_name":         ("topmostSubform[0].Page1[0].f1_01[0]",     1,  168, 714, 270,  14, 10),
    "ein":                 ("topmostSubform[0].Page1[0].f1_02[0]",     1,  450, 714, 120,  14, 10),
    "address":             ("topmostSubform[0].Page1[0].f1_03[0]",     1,  168, 698, 270,  14, 10),
    "city_state_zip":      ("topmostSubform[0].Page1[0].f1_04[0]",     1,  168, 682, 270,  14, 10),
    "principal_product":   ("topmostSubform[0].Page1[0].f1_05[0]",     1,  168, 666, 180,  12,  9),
    "business_code":       ("topmostSubform[0].Page1[0].f1_06[0]",     1,  360, 666,  80,  12,  9),
    "date_business_began": ("topmostSubform[0].Page1[0].f1_07[0]",     1,  450, 666, 100,  12,  9),
    "total_assets":        ("topmostSubform[0].Page1[0].f1_08[0]",     1,  450, 650, 120,  12,  9),
    "number_of_k1s":       ("topmostSubform[0].Page1[0].f1_09[0]",     1,  450, 634,  60,  12,  9),
    "tax_year":            (None,                                        1,  250, 750, 100,  14, 10),

    # ── PAGE 1 INCOME ────────────────────────────────────────────────────────
    "line_1a":             ("topmostSubform[0].Page1[0].f1_11[0]",     1,  486, 598,  90,  12,  9),
    "line_1b":             ("topmostSubform[0].Page1[0].f1_12[0]",     1,  486, 584,  90,  12,  9),
    "line_1c":             ("topmostSubform[0].Page1[0].f1_13[0]",     1,  486, 570,  90,  12,  9),
    "line_2":              ("topmostSubform[0].Page1[0].f1_14[0]",     1,  486, 556,  90,  12,  9),
    "line_3":              ("topmostSubform[0].Page1[0].f1_15[0]",     1,  486, 542,  90,  12,  9),
    "line_4":              ("topmostSubform[0].Page1[0].f1_16[0]",     1,  486, 528,  90,  12,  9),
    "line_5":              ("topmostSubform[0].Page1[0].f1_17[0]",     1,  486, 514,  90,  12,  9),
    "line_6":              ("topmostSubform[0].Page1[0].f1_18[0]",     1,  486, 500,  90,  12,  9),
    "line_7":              ("topmostSubform[0].Page1[0].f1_19[0]",     1,  486, 486,  90,  12,  9),
    "line_8":              ("topmostSubform[0].Page1[0].f1_20[0]",     1,  486, 472,  90,  12,  9),

    # ── PAGE 1 DEDUCTIONS ────────────────────────────────────────────────────
    "line_9":              ("topmostSubform[0].Page1[0].f1_21[0]",     1,  486, 450,  90,  12,  9),
    "line_10":             ("topmostSubform[0].Page1[0].f1_22[0]",     1,  486, 436,  90,  12,  9),
    "line_11":             ("topmostSubform[0].Page1[0].f1_23[0]",     1,  486, 422,  90,  12,  9),
    "line_12":             ("topmostSubform[0].Page1[0].f1_24[0]",     1,  486, 408,  90,  12,  9),
    "line_13":             ("topmostSubform[0].Page1[0].f1_25[0]",     1,  486, 394,  90,  12,  9),
    "line_14":             ("topmostSubform[0].Page1[0].f1_26[0]",     1,  486, 380,  90,  12,  9),
    "line_15":             ("topmostSubform[0].Page1[0].f1_27[0]",     1,  486, 366,  90,  12,  9),
    "line_16a":            ("topmostSubform[0].Page1[0].f1_28[0]",     1,  486, 352,  90,  12,  9),
    "line_16b":            ("topmostSubform[0].Page1[0].f1_29[0]",     1,  486, 338,  90,  12,  9),
    "line_16c":            ("topmostSubform[0].Page1[0].f1_30[0]",     1,  486, 324,  90,  12,  9),
    "line_17":             ("topmostSubform[0].Page1[0].f1_31[0]",     1,  486, 310,  90,  12,  9),
    "line_18":             ("topmostSubform[0].Page1[0].f1_32[0]",     1,  486, 296,  90,  12,  9),
    "line_19":             ("topmostSubform[0].Page1[0].f1_33[0]",     1,  486, 282,  90,  12,  9),
    "line_20":             ("topmostSubform[0].Page1[0].f1_34[0]",     1,  486, 268,  90,  12,  9),
    "line_21":             ("topmostSubform[0].Page1[0].f1_35[0]",     1,  486, 254,  90,  12,  9),
    "line_22":             ("topmostSubform[0].Page1[0].f1_36[0]",     1,  486, 236,  90,  12, 10),

    # ── SIGNATURE BLOCK ──────────────────────────────────────────────────────
    "preparer_name":       ("topmostSubform[0].Page1[0].f1_40[0]",     1,  150, 105, 180,  12,  9),
    "preparer_ptin":       ("topmostSubform[0].Page1[0].f1_41[0]",     1,  340, 105, 100,  12,  9),
    "preparer_date":       ("topmostSubform[0].Page1[0].f1_42[0]",     1,  450, 105,  90,  12,  9),
    "preparer_firm":       ("topmostSubform[0].Page1[0].f1_43[0]",     1,  150,  90, 180,  12,  9),
    "preparer_phone":      ("topmostSubform[0].Page1[0].f1_44[0]",     1,  340,  90, 120,  12,  9),

    # ── SCHEDULE B checkboxes / questions (page 2) ───────────────────────────
    "sch_b_2a_yes":        ("topmostSubform[0].Page2[0].c2_1[0]",      2,  480, 680,  10,  10,  9),
    "sch_b_2a_no":         ("topmostSubform[0].Page2[0].c2_2[0]",      2,  500, 680,  10,  10,  9),
    "sch_b_3a_yes":        ("topmostSubform[0].Page2[0].c2_3[0]",      2,  480, 660,  10,  10,  9),
    "sch_b_3a_no":         ("topmostSubform[0].Page2[0].c2_4[0]",      2,  500, 660,  10,  10,  9),

    # ── SCHEDULE K (page 4) ──────────────────────────────────────────────────
    "k_line_1":            ("topmostSubform[0].Page4[0].f4_01[0]",     4,  486, 698,  90,  12,  9),
    "k_line_2":            ("topmostSubform[0].Page4[0].f4_02[0]",     4,  486, 684,  90,  12,  9),
    "k_line_5":            ("topmostSubform[0].Page4[0].f4_05[0]",     4,  486, 640,  90,  12,  9),
    "k_line_6a":           ("topmostSubform[0].Page4[0].f4_06[0]",     4,  486, 626,  90,  12,  9),
    "k_line_7":            ("topmostSubform[0].Page4[0].f4_08[0]",     4,  486, 598,  90,  12,  9),
    "k_line_8":            ("topmostSubform[0].Page4[0].f4_09[0]",     4,  486, 584,  90,  12,  9),
    "k_line_9a":           ("topmostSubform[0].Page4[0].f4_10[0]",     4,  486, 570,  90,  12,  9),
    "k_line_11":           ("topmostSubform[0].Page4[0].f4_13[0]",     4,  486, 528,  90,  12,  9),
    "k_line_12":           ("topmostSubform[0].Page4[0].f4_14[0]",     4,  486, 514,  90,  12,  9),
    "k_line_13a":          ("topmostSubform[0].Page4[0].f4_15[0]",     4,  486, 500,  90,  12,  9),
    "k_line_18":           ("topmostSubform[0].Page4[0].f4_22[0]",     4,  486, 388,  90,  12,  9),
    "k_line_19a":          ("topmostSubform[0].Page4[0].f4_23[0]",     4,  486, 370,  90,  12,  9),
    "k_line_20":           ("topmostSubform[0].Page4[0].f4_25[0]",     4,  486, 340,  90,  12,  9),

    # ── SCHEDULE L  (page 5) ─────────────────────────────────────────────────
    "l_cash_beg":          ("topmostSubform[0].Page5[0].f5_01[0]",     5,  370, 698,  80,  12,  9),
    "l_cash_end":          ("topmostSubform[0].Page5[0].f5_02[0]",     5,  460, 698,  90,  12,  9),
    "l_ar_beg":            ("topmostSubform[0].Page5[0].f5_03[0]",     5,  370, 684,  80,  12,  9),
    "l_ar_end":            ("topmostSubform[0].Page5[0].f5_04[0]",     5,  460, 684,  90,  12,  9),
    "l_other_assets_beg":  ("topmostSubform[0].Page5[0].f5_07[0]",     5,  370, 656,  80,  12,  9),
    "l_other_assets_end":  ("topmostSubform[0].Page5[0].f5_08[0]",     5,  460, 656,  90,  12,  9),
    "l_fixed_assets_beg":  ("topmostSubform[0].Page5[0].f5_09[0]",     5,  370, 642,  80,  12,  9),
    "l_fixed_assets_end":  ("topmostSubform[0].Page5[0].f5_10[0]",     5,  460, 642,  90,  12,  9),
    "l_total_assets_beg":  ("topmostSubform[0].Page5[0].f5_17[0]",     5,  370, 556,  80,  12,  9),
    "l_total_assets_end":  ("topmostSubform[0].Page5[0].f5_18[0]",     5,  460, 556,  90,  12,  9),
    "l_ap_beg":            ("topmostSubform[0].Page5[0].f5_19[0]",     5,  370, 542,  80,  12,  9),
    "l_ap_end":            ("topmostSubform[0].Page5[0].f5_20[0]",     5,  460, 542,  90,  12,  9),
    "l_partners_cap_beg":  ("topmostSubform[0].Page5[0].f5_29[0]",     5,  370, 430,  80,  12,  9),
    "l_partners_cap_end":  ("topmostSubform[0].Page5[0].f5_30[0]",     5,  460, 430,  90,  12,  9),
    "l_total_liab_beg":    ("topmostSubform[0].Page5[0].f5_31[0]",     5,  370, 416,  80,  12,  9),
    "l_total_liab_end":    ("topmostSubform[0].Page5[0].f5_32[0]",     5,  460, 416,  90,  12,  9),

    # ── SCHEDULE M-1 (page 5) ────────────────────────────────────────────────
    "m1_line_1":           ("topmostSubform[0].Page5[0].f5_33[0]",     5,  486, 310,  90,  12,  9),
    "m1_line_9":           ("topmostSubform[0].Page5[0].f5_41[0]",     5,  486, 226,  90,  12,  9),

    # ── SCHEDULE M-2 (page 5) ────────────────────────────────────────────────
    "m2_beg_capital":      ("topmostSubform[0].Page5[0].f5_42[0]",     5,  486, 196,  90,  12,  9),
    "m2_capital_contrib":  ("topmostSubform[0].Page5[0].f5_43[0]",     5,  486, 182,  90,  12,  9),
    "m2_net_income":       ("topmostSubform[0].Page5[0].f5_44[0]",     5,  486, 168,  90,  12,  9),
    "m2_distributions":    ("topmostSubform[0].Page5[0].f5_47[0]",     5,  486, 140,  90,  12,  9),
    "m2_end_capital":      ("topmostSubform[0].Page5[0].f5_49[0]",     5,  486, 112,  90,  12,  9),
}

# Checkbox on/off values used by IRS AcroForm
CHECKBOX_ON  = "/1"
CHECKBOX_OFF = "/0"

# Fields whose values are bool (True→checked, False→unchecked)
BOOL_FIELDS = {
    "sch_b_2a_yes", "sch_b_2a_no",
    "sch_b_3a_yes", "sch_b_3a_no",
}


# ════════════════════════════════════════════════════════════════════════════
#  HELPER – format a float as IRS dollar string
# ════════════════════════════════════════════════════════════════════════════

def _fmt_dollar(value: float) -> str:
    """Format a number for an IRS field: '1,606' (no $ sign, no cents on whole)."""
    if value < 0:
        return f"({abs(value):,.0f})"
    return f"{value:,.0f}"


def _fmt_dollar_cents(value: float) -> str:
    """Two-decimal version for balance-sheet / Schedule L fields."""
    if value < 0:
        return f"({abs(value):,.2f})"
    return f"{value:,.2f}"


# ════════════════════════════════════════════════════════════════════════════
#  MAIN CLASS
# ════════════════════════════════════════════════════════════════════════════

class Form1065Filler:
    """
    Fill IRS Form 1065 PDF fields from a Python dict.

    Parameters
    ----------
    pdf_path : str
        Path to the *blank* IRS Form 1065 PDF (downloadable from irs.gov).
    use_cents : bool
        If True, format dollar amounts with two decimal places.
    verbose : bool
        Print field-fill status to stdout.
    """

    def __init__(
        self,
        pdf_path: str,
        use_cents: bool = False,
        verbose:   bool = True,
    ):
        if not _PYPDF:
            raise ImportError("pypdf is required:  pip install pypdf")
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        self.pdf_path  = pdf_path
        self.use_cents = use_cents
        self.verbose   = verbose

        self._reader: PdfReader   = PdfReader(pdf_path)
        self._writer: PdfWriter   = PdfWriter()
        self._writer.append(self._reader)   # clone all pages

        # discover actual AcroForm field names in the PDF
        self._acro_fields: Dict[str, Any] = self._discover_acro_fields()
        if self.verbose:
            print(f"[Form1065Filler] Loaded '{pdf_path}'  "
                  f"({len(self._reader.pages)} pages, "
                  f"{len(self._acro_fields)} AcroForm fields detected)")

    # ── public API ───────────────────────────────────────────────────────────

    def fill(self, data: Dict[str, Any]) -> "Form1065Filler":
        """
        Fill fields from *data* dict. Applies auto-computations for
        totals if the caller omitted them.
        Returns self for chaining.
        """
        data = self._auto_compute(dict(data))
        filled_acro    = 0
        filled_overlay = 0
        overlay_ops: Dict[int, List] = {}   # page → list of (x,y,w,h,text,fs)

        for key, value in data.items():
            if key not in FIELD_MAP:
                if self.verbose:
                    print(f"  [SKIP]    '{key}' not in FIELD_MAP")
                continue

            acro_name, page, x, y, w, h, fs = FIELD_MAP[key]
            text_val = self._to_text(key, value)

            # ── try AcroForm first ────────────────────────────────────────
            acro_ok = False
            if acro_name:
                acro_ok = self._fill_acro(acro_name, text_val, key in BOOL_FIELDS, value)
                if acro_ok:
                    filled_acro += 1
                    if self.verbose:
                        print(f"  [ACRO]    {key:30s} = {text_val}")

            # ── fallback overlay ─────────────────────────────────────────
            if not acro_ok:
                if not _REPORTLAB:
                    if self.verbose:
                        print(f"  [SKIP-OVL] {key} — reportlab not installed")
                    continue
                overlay_ops.setdefault(page, []).append((x, y, w, h, text_val, fs))
                filled_overlay += 1
                if self.verbose:
                    print(f"  [OVERLAY] {key:30s} = {text_val}  (p{page})")

        # apply overlays page by page
        if overlay_ops:
            self._apply_overlays(overlay_ops)

        if self.verbose:
            print(f"\n  ✅  Filled {filled_acro} AcroForm fields + "
                  f"{filled_overlay} overlay fields")
        return self

    def save(self, output_path: str) -> str:
        """Write filled PDF to *output_path*. Returns the path."""
        # flatten form so values are visible in all readers
        if hasattr(self._writer, "_root_object"):
            try:
                # Mark NeedAppearances so readers regenerate field appearances
                acroform = self._writer._root_object.get("/AcroForm")
                if acroform:
                    acroform.update({
                        NameObject("/NeedAppearances"): BooleanObject(True)
                    })
            except Exception:
                pass

        with open(output_path, "wb") as f:
            self._writer.write(f)
        if self.verbose:
            print(f"\n  💾  Saved → {output_path}")
        return output_path

    # ── class-method convenience ─────────────────────────────────────────────

    @classmethod
    def fill_from_dict(
        cls,
        input_pdf:   str,
        data:        Dict[str, Any],
        output_pdf:  str,
        verbose:     bool = True,
    ) -> str:
        """One-liner: load blank PDF, fill, save. Returns output path."""
        filler = cls(input_pdf, verbose=verbose)
        filler.fill(data)
        return filler.save(output_pdf)

    @classmethod
    def inspect_fields(cls, pdf_path: str) -> Dict[str, Any]:
        """
        Return a dict of all AcroForm fields found in the PDF.
        Useful for debugging / mapping new form versions.
        """
        reader = PdfReader(pdf_path)
        fields = {}
        raw = reader.get_fields()
        if raw:
            for name, field in raw.items():
                fields[name] = {
                    "type":  field.get("/FT"),
                    "value": field.get("/V"),
                    "rect":  field.get("/Rect"),
                }
        return fields

    @classmethod
    def print_field_map(cls) -> None:
        """Print the built-in FIELD_MAP in a readable table."""
        print(f"\n{'Key':<25} {'AcroForm Field':<48} {'Pg':>3}  {'x':>4} {'y':>4}")
        print("─" * 88)
        for key, (af, pg, x, y, *_) in FIELD_MAP.items():
            af_short = (af or "OVERLAY")[-46:]
            print(f"  {key:<23} {af_short:<48} {pg:>3}  {x:>4.0f} {y:>4.0f}")

    # ── internal helpers ─────────────────────────────────────────────────────

    def _discover_acro_fields(self) -> Dict[str, Any]:
        """Return dict of {field_name: field_obj} from the PDF's AcroForm."""
        raw = self._reader.get_fields()
        if not raw:
            return {}
        return {name: obj for name, obj in raw.items()}

    def _fill_acro(
        self,
        acro_name: str,
        text_val:  str,
        is_bool:   bool,
        raw_value: Any,
    ) -> bool:
        """
        Write a value into an AcroForm field.
        Returns True if the field was found and written.
        """
        # pypdf 3+ uses update_page_form_field_values
        # We iterate writer pages and their annotations directly for reliability.
        found = False
        for page in self._writer.pages:
            if "/Annots" not in page:
                continue
            annots = page["/Annots"]
            for annot_ref in annots:
                try:
                    annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                except Exception:
                    continue
                if annot.get("/T") == acro_name or str(annot.get("/T")) == acro_name:
                    # determine value to write
                    if is_bool:
                        write_val = CHECKBOX_ON if raw_value else CHECKBOX_OFF
                        annot.update({NameObject("/V"): NameObject(write_val),
                                       NameObject("/AS"): NameObject(write_val)})
                    else:
                        annot.update({NameObject("/V"): create_string_object(text_val)})
                    found = True

        # Also try pypdf's high-level API as a second pass
        if not found:
            try:
                self._writer.update_page_form_field_values(
                    self._writer.pages[0] if len(self._writer.pages) == 1 else None,
                    {acro_name: CHECKBOX_ON if (is_bool and raw_value) else
                                CHECKBOX_OFF if (is_bool and not raw_value) else
                                text_val},
                )
                found = True
            except Exception:
                pass

        return found

    def _apply_overlays(self, ops: Dict[int, List]) -> None:
        """Render text overlays using ReportLab, then merge into writer pages."""
        from reportlab.pdfgen import canvas as rl_canvas
        from pypdf import PdfReader as _R

        page_h = 792.0   # letter height in points

        for page_num, fields in ops.items():
            buf = io.BytesIO()
            c   = rl_canvas.Canvas(buf, pagesize=(612, page_h))
            c.setFont("Helvetica", 9)

            for (x, y, w, h, text, fs) in fields:
                c.setFont("Helvetica", fs)
                # right-align numbers, left-align text
                is_num = bool(re.match(r"^[\d,.()\-]+$", text.replace(" ", "")))
                if is_num:
                    c.drawRightString(x + w - 2, y + 2, text)
                else:
                    c.drawString(x + 2, y + 2, text)

            c.save()
            buf.seek(0)
            overlay_reader = _R(buf)
            overlay_page   = overlay_reader.pages[0]

            # merge overlay onto the target writer page (0-indexed)
            target = self._writer.pages[page_num - 1]
            target.merge_page(overlay_page)

    def _to_text(self, key: str, value: Any) -> str:
        """Convert a dict value to the string to write into the PDF field."""
        if key in BOOL_FIELDS:
            return CHECKBOX_ON if value else CHECKBOX_OFF
        if isinstance(value, bool):
            return "X" if value else ""
        if isinstance(value, (int, float)):
            return (
                _fmt_dollar_cents(value) if self.use_cents
                else _fmt_dollar(value)
            )
        return str(value)

    # ── auto-compute totals ──────────────────────────────────────────────────

    @staticmethod
    def _auto_compute(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fill in computed lines that the caller omitted.
        All computations mirror IRS Form 1065 arithmetic.
        """
        def get(k): return float(data.get(k) or 0)

        # Line 1c = 1a − 1b
        if "line_1c" not in data:
            v = get("line_1a") - get("line_1b")
            if v: data["line_1c"] = v

        # Line 8  = total income
        if "line_8" not in data:
            total = (get("line_1c") + get("line_3") + get("line_4") +
                     get("line_5")  + get("line_6") + get("line_7"))
            if total: data["line_8"] = total

        # Line 16c = 16a − 16b
        if "line_16c" not in data:
            v = get("line_16a") - get("line_16b")
            if v: data["line_16c"] = v

        # Line 21 = total deductions
        if "line_21" not in data:
            total = sum(get(f"line_{n}") for n in
                        [9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20]) + get("line_16c")
            if total: data["line_21"] = total

        # Line 22 = ordinary income/(loss)
        if "line_22" not in data:
            v = get("line_8") - get("line_21")
            data["line_22"] = v

        # Schedule K line 1 mirrors line 22
        if "k_line_1" not in data and "line_22" in data:
            data["k_line_1"] = data["line_22"]

        # Schedule M-2 ending capital
        if "m2_end_capital" not in data:
            v = (get("m2_beg_capital") + get("m2_capital_contrib") +
                 get("m2_net_income")  - get("m2_distributions"))
            if v: data["m2_end_capital"] = v

        return data


# ════════════════════════════════════════════════════════════════════════════
#  CONVENIENCE BUILDER  –  GL dict  →  1065 data dict
#  (bridges Form1065Preparer output to Form1065Filler input)
# ════════════════════════════════════════════════════════════════════════════

def build_1065_dict_from_gl(
    gl: Dict[str, float],
    entity_name:   str  = "LLC Rental Partnership",
    ein:           str  = "XX-XXXXXXX",
    tax_year:      int  = 2024,
    address:       str  = "",
    city_state_zip:str  = "",
    business_code: str  = "531110",   # IRS code: Lessors of residential buildings
    preparer_name: str  = "",
    preparer_ptin: str  = "",
    preparer_date: str  = "",
) -> Dict[str, Any]:
    """
    Convert a raw General Ledger dict (same format used by Form1065Preparer)
    directly into a Form1065Filler data dict.

    GL sign convention:
      Positive = money IN  (income, capital contributions, ending balance)
      Negative = money OUT (expenses, asset purchases)
    """
    def pos(k):   return max(0.0, float(gl.get(k, 0)))
    def absv(k):  return abs(float(gl.get(k, 0)))

    # income
    line_1a  = pos("Acct.Cash.Income")
    line_5_k = pos("Acct.Interest.Income")
    line_7   = pos("Acct.Cash.Misc")
    line_8   = line_1a + line_5_k + line_7

    # deductions
    line_20  = absv("Acct.Cash.Expense") + absv("Acct.Cash.Util")
    line_21  = line_20
    line_22  = line_8 - line_21

    # balance sheet
    fixed    = absv("Acct.Asset.Purchase")
    cash_end = pos("Balance")
    cap_cont = pos("Acct.Cash.Investment")

    return {
        # header
        "entity_name":        entity_name,
        "ein":                ein,
        "tax_year":           tax_year,
        "address":            address,
        "city_state_zip":     city_state_zip,
        "principal_product":  "Residential Rental Property",
        "business_code":      business_code,
        "number_of_k1s":      1,

        # page 1 income
        "line_1a":  line_1a,
        "line_7":   line_7,
        "line_8":   line_8,

        # page 1 deductions
        "line_20":  line_20,
        "line_21":  line_21,
        "line_22":  line_22,

        # schedule K
        "k_line_1":  line_22,
        "k_line_2":  line_1a,
        "k_line_5":  line_5_k,
        "k_line_11": line_7,

        # schedule L
        "l_cash_beg":         0.0,
        "l_cash_end":         cash_end,
        "l_fixed_assets_beg": 0.0,
        "l_fixed_assets_end": fixed,
        "l_total_assets_beg": 0.0,
        "l_total_assets_end": cash_end + fixed,
        "l_partners_cap_beg": 0.0,
        "l_partners_cap_end": cap_cont + line_22,
        "l_total_liab_beg":   0.0,
        "l_total_liab_end":   cap_cont + line_22,

        # schedule M-2
        "m2_beg_capital":    0.0,
        "m2_capital_contrib": cap_cont,
        "m2_net_income":      line_22,
        "m2_end_capital":     cap_cont + line_22,

        # preparer block
        "preparer_name": preparer_name,
        "preparer_ptin": preparer_ptin,
        "preparer_date": preparer_date,
    }


