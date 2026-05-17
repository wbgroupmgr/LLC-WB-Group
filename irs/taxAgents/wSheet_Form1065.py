"""
Form1065Preparer
================
Ingests a General Ledger for an LLC rental business and maps account balances
to the appropriate lines of IRS Form 1065 (U.S. Return of Partnership Income).

GL Account Mapping (rental LLC):
  Acct.Asset.Purchase    -> Schedule L (total assets / depreciable property)
  Acct.Cash.Expense      -> Page 1 Line 20 (other deductions)
  Acct.Cash.Income       -> Page 1 Line 1a (gross receipts / rents)
  Acct.Cash.Investment   -> Schedule L (partners' capital contributions)
  Acct.Cash.Misc         -> Page 1 Line 7 (other income)
  Acct.Cash.Util         -> Page 1 Line 20 (utilities, part of other deductions)
  Acct.Interest.Income   -> Page 1 Line 5 (interest income)
  Balance                -> Schedule L (ending cash/bank balance)

Usage:
  gl = {
      "Acct.Asset.Purchase":  -214113.95,
      "Acct.Cash.Expense":      -1766.92,
      "Acct.Cash.Income":        4000.53,
      "Acct.Cash.Investment":  219227.00,
      "Acct.Cash.Misc":            29.47,
      "Acct.Cash.Util":         -1056.95,
      "Acct.Interest.Income":     400.00,
      "Balance":                 6719.18,
  }
  preparer = Form1065Preparer(gl, tax_year=2024,
                               entity_name="Sunset Ridge Rentals LLC",
                               ein="12-3456789")
  preparer.compute()
  preparer.print_summary()
  preparer.export_pdf("Form_1065_Worksheet.pdf")
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, Optional

# ── optional PDF export ──────────────────────────────────────────────────────
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    _REPORTLAB = True
except ImportError:
    _REPORTLAB = False


# ════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class F1065Page1:
    """Form 1065 – Page 1 income / deduction lines."""
    # INCOME
    line_1a_gross_receipts:    float = 0.0   # Gross receipts / rental income
    line_5_interest_income:    float = 0.0   # Interest income
    line_7_other_income:       float = 0.0   # Other income (misc cash)
    total_income:              float = 0.0   # Sum of income lines

    # DEDUCTIONS
    line_20_other_deductions:  float = 0.0   # Cash expenses + utilities
    total_deductions:          float = 0.0

    # BOTTOM LINE
    ordinary_income_loss:      float = 0.0   # Line 22 (income − deductions)


@dataclass
class ScheduleL:
    """Schedule L – Balance Sheet per Books (simplified for rental LLC)."""
    # ASSETS
    cash_beginning:            float = 0.0
    cash_ending:               float = 0.0
    depreciable_property_cost: float = 0.0   # from Acct.Asset.Purchase (abs)
    total_assets:              float = 0.0

    # LIABILITIES & CAPITAL
    partners_capital_contrib:  float = 0.0   # Acct.Cash.Investment
    retained_earnings:         float = 0.0   # Cumulative ordinary income
    total_liabilities_capital: float = 0.0


@dataclass
class ScheduleK:
    """Schedule K – Partners' Distributive Share Items."""
    ordinary_income_loss:      float = 0.0
    net_rental_income:         float = 0.0
    interest_income:           float = 0.0
    other_income:              float = 0.0
    total_distributive_income: float = 0.0


@dataclass
class Form1065Result:
    """Container for all computed 1065 schedules."""
    entity_name:  str = ""
    ein:          str = ""
    tax_year:     int = 2024
    page1:        F1065Page1  = field(default_factory=F1065Page1)
    schedule_k:   ScheduleK   = field(default_factory=ScheduleK)
    schedule_l:   ScheduleL   = field(default_factory=ScheduleL)
    gl_raw:       Dict[str, float] = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════════════════
#  MAIN CLASS
# ════════════════════════════════════════════════════════════════════════════

class Form1065Preparer:
    """
    Parses a General Ledger dict and maps balances to IRS Form 1065 lines.

    Conventions
    -----------
    * Income accounts: positive values → income earned
    * Expense/Asset accounts: negative values → money spent / invested
    * The class normalises signs internally for presentation.
    """

    # ── GL → 1065 mapping ───────────────────────────────────────────────────
    KNOWN_ACCOUNTS = {
        "Acct.Asset.Purchase",
        "Acct.Cash.Expense",
        "Acct.Cash.Income",
        "Acct.Cash.Investment",
        "Acct.Cash.Misc",
        "Acct.Cash.Util",
        "Acct.Interest.Income",
        "Balance",
    }

    def __init__(
        self,
        general_ledger: Dict[str, float],
        tax_year: int = 2024,
        entity_name: str = "LLC Rental Partnership",
        ein: str = "XX-XXXXXXX",
        beginning_cash: float = 0.0,
    ):
        self.gl = general_ledger
        self.tax_year = tax_year
        self.entity_name = entity_name
        self.ein = ein
        self.beginning_cash = beginning_cash
        self.result: Optional[Form1065Result] = None
        self._validate_gl()

    # ── validation ───────────────────────────────────────────────────────────

    def _validate_gl(self) -> None:
        unknown = set(self.gl.keys()) - self.KNOWN_ACCOUNTS
        if unknown:
            print(f"[WARNING] Unrecognised GL accounts (will be ignored): {unknown}")
        for acct, val in self.gl.items():
            if not isinstance(val, (int, float)):
                raise TypeError(f"GL value for '{acct}' must be numeric, got {type(val)}")

    def _get(self, key: str, default: float = 0.0) -> float:
        return self.gl.get(key, default)

    # ── computation ──────────────────────────────────────────────────────────

    def compute(self) -> Form1065Result:
        """Map GL balances to Form 1065 lines and return a Form1065Result."""

        # ── raw GL values ────────────────────────────────────────────────────
        asset_purchase   = self._get("Acct.Asset.Purchase")    # negative (cash out)
        cash_expense     = self._get("Acct.Cash.Expense")       # negative (cash out)
        cash_income      = self._get("Acct.Cash.Income")        # positive (cash in)
        cash_investment  = self._get("Acct.Cash.Investment")    # positive (capital in)
        cash_misc        = self._get("Acct.Cash.Misc")          # positive (misc income)
        cash_util        = self._get("Acct.Cash.Util")          # negative (utility expense)
        interest_income  = self._get("Acct.Interest.Income")    # positive
        balance          = self._get("Balance")                  # ending cash balance

        # ════════════════════════════════════
        #  PAGE 1 – INCOME
        # ════════════════════════════════════
        # Line 1a – Gross receipts (rental income only; positive)
        line_1a = abs(cash_income) if cash_income > 0 else 0.0

        # Line 5 – Interest income
        line_5 = abs(interest_income) if interest_income > 0 else 0.0

        # Line 7 – Other income (misc cash receipts)
        line_7 = abs(cash_misc) if cash_misc > 0 else 0.0

        total_income = line_1a + line_5 + line_7

        # ════════════════════════════════════
        #  PAGE 1 – DEDUCTIONS
        # ════════════════════════════════════
        # Line 20 – Other deductions:
        #   • Acct.Cash.Expense (operating expenses)
        #   • Acct.Cash.Util    (utilities)
        #   NOTE: Acct.Asset.Purchase goes to Schedule L (capital asset),
        #         not deducted directly on Page 1 (treated as depreciable property).
        line_20_cash_exp  = abs(cash_expense) if cash_expense < 0 else cash_expense
        line_20_util      = abs(cash_util)    if cash_util    < 0 else cash_util
        line_20           = line_20_cash_exp + line_20_util

        total_deductions  = line_20

        # ════════════════════════════════════
        #  LINE 22 – ORDINARY INCOME / (LOSS)
        # ════════════════════════════════════
        ordinary_income   = total_income - total_deductions

        # ════════════════════════════════════
        #  SCHEDULE K
        # ════════════════════════════════════
        sk_ordinary      = ordinary_income
        sk_rental        = line_1a          # net rental flows through K-1 Box 2
        sk_interest      = line_5
        sk_other         = line_7
        sk_total         = sk_ordinary      # ordinary already nets everything

        # ════════════════════════════════════
        #  SCHEDULE L – BALANCE SHEET
        # ════════════════════════════════════
        depr_property_cost  = abs(asset_purchase)   # capitalised at cost
        partners_contrib    = abs(cash_investment) if cash_investment > 0 else 0.0
        ending_cash         = abs(balance) if balance > 0 else 0.0
        beginning_cash_val  = self.beginning_cash

        total_assets        = ending_cash + depr_property_cost
        retained_earnings   = ordinary_income        # simplified single-period
        total_liab_capital  = partners_contrib + retained_earnings

        # ════════════════════════════════════
        #  ASSEMBLE RESULT
        # ════════════════════════════════════
        p1 = F1065Page1(
            line_1a_gross_receipts   = line_1a,
            line_5_interest_income   = line_5,
            line_7_other_income      = line_7,
            total_income             = total_income,
            line_20_other_deductions = line_20,
            total_deductions         = total_deductions,
            ordinary_income_loss     = ordinary_income,
        )

        sk = ScheduleK(
            ordinary_income_loss      = sk_ordinary,
            net_rental_income         = sk_rental,
            interest_income           = sk_interest,
            other_income              = sk_other,
            total_distributive_income = sk_total,
        )

        sl = ScheduleL(
            cash_beginning            = beginning_cash_val,
            cash_ending               = ending_cash,
            depreciable_property_cost = depr_property_cost,
            total_assets              = total_assets,
            partners_capital_contrib  = partners_contrib,
            retained_earnings         = retained_earnings,
            total_liabilities_capital = total_liab_capital,
        )

        self.result = Form1065Result(
            entity_name  = self.entity_name,
            ein          = self.ein,
            tax_year     = self.tax_year,
            page1        = p1,
            schedule_k   = sk,
            schedule_l   = sl,
            gl_raw       = dict(self.gl),
        )
        return self.result

    # ── text summary ─────────────────────────────────────────────────────────

    def print_summary(self) -> None:
        """Print a formatted console summary of all 1065 schedules."""
        if self.result is None:
            self.compute()
        r = self.result
        p = r.page1
        k = r.schedule_k
        l = r.schedule_l

        def f(v): return f"${v:>14,.2f}"
        sep = "=" * 58

        print(f"\n{sep}")
        print(f"  IRS FORM 1065 WORKSHEET  |  Tax Year {r.tax_year}")
        print(f"  {r.entity_name}  |  EIN: {r.ein}")
        print(sep)

        print("\n  PAGE 1 — INCOME")
        print(f"  Line 1a  Gross Receipts (Rental)      {f(p.line_1a_gross_receipts)}")
        print(f"  Line 5   Interest Income               {f(p.line_5_interest_income)}")
        print(f"  Line 7   Other Income (Misc)           {f(p.line_7_other_income)}")
        print(f"  {'─'*52}")
        print(f"           TOTAL INCOME                  {f(p.total_income)}")

        print("\n  PAGE 1 — DEDUCTIONS")
        print(f"  Line 20  Other Deductions")
        print(f"             Cash Expenses               {f(abs(r.gl_raw.get('Acct.Cash.Expense',0)))}")
        print(f"             Utilities                   {f(abs(r.gl_raw.get('Acct.Cash.Util',0)))}")
        print(f"  {'─'*52}")
        print(f"           TOTAL DEDUCTIONS              {f(p.total_deductions)}")

        print(f"\n  LINE 22  ORDINARY INCOME / (LOSS)     {f(p.ordinary_income_loss)}")

        print(f"\n  SCHEDULE K — DISTRIBUTIVE SHARE ITEMS")
        print(f"  K-1 Box 1  Ordinary Income/(Loss)     {f(k.ordinary_income_loss)}")
        print(f"  K-1 Box 2  Net Rental Income           {f(k.net_rental_income)}")
        print(f"  K-1 Box 5  Interest Income             {f(k.interest_income)}")
        print(f"  K-1 Box 11 Other Income                {f(k.other_income)}")
        print(f"  {'─'*52}")
        print(f"             TOTAL DISTRIBUTIVE INCOME  {f(k.total_distributive_income)}")

        print(f"\n  SCHEDULE L — BALANCE SHEET (End of Year)")
        print(f"  ASSETS")
        print(f"    Cash (ending balance)               {f(l.cash_ending)}")
        print(f"    Depreciable Property (cost)         {f(l.depreciable_property_cost)}")
        print(f"  {'─'*52}")
        print(f"    TOTAL ASSETS                        {f(l.total_assets)}")
        print(f"  LIABILITIES & PARTNERS' CAPITAL")
        print(f"    Partners' Capital Contributions     {f(l.partners_capital_contrib)}")
        print(f"    Retained Earnings (current yr)      {f(l.retained_earnings)}")
        print(f"  {'─'*52}")
        print(f"    TOTAL LIABILITIES & CAPITAL         {f(l.total_liabilities_capital)}")
        print(f"\n{sep}\n")

    # ── PDF export ────────────────────────────────────────────────────────────

    def export_pdf(self, output_path: str = "Form_1065_Worksheet.pdf") -> str:
        """Generate a formatted PDF worksheet. Returns the output path."""
        if not _REPORTLAB:
            raise ImportError("reportlab is required for PDF export. "
                              "Run: pip install reportlab")
        if self.result is None:
            self.compute()
        _build_pdf(self.result, output_path)
        print(f"✅  PDF saved → {output_path}")
        return output_path

    # ── dict / JSON export ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return all computed values as a plain dict (JSON-serialisable)."""
        if self.result is None:
            self.compute()
        r = self.result
        return {
            "entity_name": r.entity_name,
            "ein":         r.ein,
            "tax_year":    r.tax_year,
            "page1": {
                "line_1a_gross_receipts":   r.page1.line_1a_gross_receipts,
                "line_5_interest_income":   r.page1.line_5_interest_income,
                "line_7_other_income":      r.page1.line_7_other_income,
                "total_income":             r.page1.total_income,
                "line_20_other_deductions": r.page1.line_20_other_deductions,
                "total_deductions":         r.page1.total_deductions,
                "ordinary_income_loss":     r.page1.ordinary_income_loss,
            },
            "schedule_k": {
                "ordinary_income_loss":      r.schedule_k.ordinary_income_loss,
                "net_rental_income":         r.schedule_k.net_rental_income,
                "interest_income":           r.schedule_k.interest_income,
                "other_income":              r.schedule_k.other_income,
                "total_distributive_income": r.schedule_k.total_distributive_income,
            },
            "schedule_l": {
                "cash_beginning":            r.schedule_l.cash_beginning,
                "cash_ending":               r.schedule_l.cash_ending,
                "depreciable_property_cost": r.schedule_l.depreciable_property_cost,
                "total_assets":              r.schedule_l.total_assets,
                "partners_capital_contrib":  r.schedule_l.partners_capital_contrib,
                "retained_earnings":         r.schedule_l.retained_earnings,
                "total_liabilities_capital": r.schedule_l.total_liabilities_capital,
            },
            "gl_raw": r.gl_raw,
        }


# ════════════════════════════════════════════════════════════════════════════
#  PDF BUILDER  (internal – uses ReportLab)
# ════════════════════════════════════════════════════════════════════════════

def _build_pdf(r: Form1065Result, output_path: str) -> None:
    """Render Form1065Result to a professional PDF worksheet."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    # palette
    NAVY   = colors.HexColor("#1a3560")
    BLUE   = colors.HexColor("#2e6da4")
    LBLUE  = colors.HexColor("#d6e8f7")
    GOLD   = colors.HexColor("#c8860a")
    WHITE  = colors.white
    GRAY   = colors.HexColor("#f4f6f9")
    BORDER = colors.HexColor("#c4d0de")
    GREEN  = colors.HexColor("#1a6e2e")
    RED    = colors.HexColor("#a61c00")

    base   = getSampleStyleSheet()
    W      = 7.0 * inch

    def sty(name, **kw):
        parent = kw.pop("parent", base["Normal"])
        return ParagraphStyle(name, parent=parent, **kw)

    title_s  = sty("T",  fontSize=17, textColor=WHITE,  alignment=TA_CENTER, fontName="Helvetica-Bold")
    sub_s    = sty("S",  fontSize=9,  textColor=LBLUE,  alignment=TA_CENTER, fontName="Helvetica")
    h1_s     = sty("H1", fontSize=11, textColor=WHITE,  fontName="Helvetica-Bold", leftIndent=6)
    lbl_s    = sty("L",  fontSize=9,  textColor=NAVY,   fontName="Helvetica")
    val_s    = sty("V",  fontSize=9,  textColor=NAVY,   fontName="Helvetica-Bold", alignment=TA_RIGHT)
    tot_l_s  = sty("TL", fontSize=9,  textColor=WHITE,  fontName="Helvetica-Bold")
    tot_v_s  = sty("TV", fontSize=9,  textColor=WHITE,  fontName="Helvetica-Bold", alignment=TA_RIGHT)
    note_s   = sty("N",  fontSize=7.5,textColor=colors.HexColor("#555"), fontName="Helvetica-Oblique")
    foot_s   = sty("F",  fontSize=7,  textColor=colors.HexColor("#888"), alignment=TA_CENTER)
    grn_v_s  = sty("GV", fontSize=9,  textColor=GREEN,  fontName="Helvetica-Bold", alignment=TA_RIGHT)
    red_v_s  = sty("RV", fontSize=9,  textColor=RED,    fontName="Helvetica-Bold", alignment=TA_RIGHT)

    def fmt(v, parens=True):
        if parens and v < 0:
            return f"(${abs(v):,.2f})"
        return f"${abs(v):,.2f}"

    def amt_sty(v):
        return grn_v_s if v >= 0 else red_v_s

    def row(label, value, bg=WHITE, total=False):
        ls = tot_l_s if total else lbl_s
        vs = (tot_v_s if total else amt_sty(value))
        return [Paragraph(label, ls), Paragraph(fmt(value), vs)]

    def sec(title):
        t = Table([[Paragraph(title, h1_s)]], colWidths=[W])
        t.setStyle(TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), BLUE),
            ("TOPPADDING",   (0,0),(-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
            ("LEFTPADDING",  (0,0),(-1,-1), 8),
        ]))
        return t

    def tbl(data, cols, stripe=True):
        t = Table(data, colWidths=cols)
        style_cmds = [
            ("TOPPADDING",   (0,0),(-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
            ("LEFTPADDING",  (0,0),(0,-1),  8),
            ("RIGHTPADDING", (1,0),(1,-1),  8),
            ("GRID",         (0,0),(-1,-1), 0.4, BORDER),
        ]
        if stripe:
            style_cmds.append(("ROWBACKGROUNDS",(0,0),(-1,-1),[WHITE,GRAY]))
        t.setStyle(TableStyle(style_cmds))
        return t

    def total_row_tbl(data, cols):
        """Last row is a dark total row."""
        t = Table(data, colWidths=cols)
        n = len(data) - 1
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS",(0,0),(-1,n-1),[WHITE,GRAY]),
            ("BACKGROUND",    (0,n),(-1, n), NAVY),
            ("LINEABOVE",     (0,n),(-1, n), 1.5, GOLD),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
            ("LEFTPADDING",   (0,0),(0,-1),  8),
            ("RIGHTPADDING",  (1,0),(1,-1),  8),
            ("GRID",          (0,0),(-1,-1), 0.4, BORDER),
        ]))
        return t

    story = []
    p1 = r.page1
    sk = r.schedule_k
    sl = r.schedule_l
    gl = r.gl_raw

    # ── HEADER ───────────────────────────────────────────────────────────────
    hdr = Table([
        [Paragraph("IRS FORM 1065 WORKSHEET", title_s)],
        [Paragraph(f"U.S. Return of Partnership Income &nbsp;|&nbsp; "
                   f"Tax Year {r.tax_year} &nbsp;|&nbsp; LLC Rental Business", sub_s)],
    ], colWidths=[W])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), NAVY),
        ("TOPPADDING",   (0,0),(-1, 0), 12),
        ("BOTTOMPADDING",(0,1),(-1, 1), 10),
        ("LINEBELOW",    (0,0),(-1, 0), 1, GOLD),
    ]))
    story += [hdr, Spacer(1,6)]

    # entity info bar
    info = Table([[
        Paragraph(f"<b>Entity:</b> {r.entity_name}", lbl_s),
        Paragraph(f"<b>EIN:</b> {r.ein}", lbl_s),
        Paragraph(f"<b>Form:</b> 1065 &nbsp;(Partnership)", lbl_s),
        Paragraph(f"<b>Year:</b> {r.tax_year}", lbl_s),
    ]], colWidths=[W*0.35, W*0.22, W*0.27, W*0.16])
    info.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), LBLUE),
        ("TOPPADDING",   (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LEFTPADDING",  (0,0),(-1,-1), 8),
        ("GRID",         (0,0),(-1,-1), 0.4, BORDER),
    ]))
    story += [info, Spacer(1,10)]

    # ── GL IMPORT SUMMARY ────────────────────────────────────────────────────
    story.append(sec("GENERAL LEDGER — IMPORTED ACCOUNT BALANCES"))
    story.append(Spacer(1,2))

    gl_header = Table([[
        Paragraph("GL Account", sty("GH", fontSize=8.5, textColor=WHITE, fontName="Helvetica-Bold")),
        Paragraph("Raw Balance", sty("GH2", fontSize=8.5, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        Paragraph("1065 Mapping", sty("GH3", fontSize=8.5, textColor=WHITE, fontName="Helvetica-Bold")),
        Paragraph("Schedule / Line", sty("GH4", fontSize=8.5, textColor=WHITE, fontName="Helvetica-Bold")),
    ]], colWidths=[W*0.28, W*0.18, W*0.30, W*0.24])
    gl_header.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), NAVY),
        ("TOPPADDING",   (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LEFTPADDING",  (0,0),(-1,-1), 6),
        ("GRID",         (0,0),(-1,-1), 0.4, BORDER),
    ]))
    story.append(gl_header)

    mapping_rows = [
        ("Acct.Asset.Purchase",  "Depreciable Property (capitalised)",  "Schedule L — Assets"),
        ("Acct.Cash.Expense",    "Other Deductions (operating)",        "Page 1 — Line 20"),
        ("Acct.Cash.Income",     "Gross Receipts / Rental Income",      "Page 1 — Line 1a"),
        ("Acct.Cash.Investment", "Partners' Capital Contributions",     "Schedule L — Capital"),
        ("Acct.Cash.Misc",       "Other Income (miscellaneous)",        "Page 1 — Line 7"),
        ("Acct.Cash.Util",       "Utilities Expense",                   "Page 1 — Line 20"),
        ("Acct.Interest.Income", "Interest Income",                     "Page 1 — Line 5"),
        ("Balance",              "Ending Cash / Bank Balance",          "Schedule L — Assets"),
    ]
    gl_data = []
    for i, (acct, desc, sched) in enumerate(mapping_rows):
        v = gl.get(acct, 0.0)
        bg = WHITE if i % 2 == 0 else GRAY
        vs = amt_sty(v)
        gl_data.append([
            Paragraph(acct, lbl_s),
            Paragraph(fmt(v), vs),
            Paragraph(desc, lbl_s),
            Paragraph(sched, lbl_s),
        ])
    gl_body = Table(gl_data, colWidths=[W*0.28, W*0.18, W*0.30, W*0.24])
    gl_body.setStyle(TableStyle([
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[WHITE,GRAY]),
        ("TOPPADDING",   (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LEFTPADDING",  (0,0),(-1,-1), 6),
        ("RIGHTPADDING", (1,0),(1,-1),  6),
        ("GRID",         (0,0),(-1,-1), 0.4, BORDER),
    ]))
    story += [gl_body, Spacer(1,10)]

    # ── PAGE 1 INCOME ────────────────────────────────────────────────────────
    story.append(sec("FORM 1065 — PAGE 1  |  INCOME"))
    story.append(Spacer(1,2))
    inc_data = [
        row("Line 1a   Gross Receipts / Rental Income",    p1.line_1a_gross_receipts),
        row("Line 5    Interest Income",                   p1.line_5_interest_income),
        row("Line 7    Other Income (Misc Cash Receipts)", p1.line_7_other_income),
        row("TOTAL INCOME  (Line 8)",                      p1.total_income, total=True),
    ]
    story += [total_row_tbl(inc_data, [W*0.70, W*0.30]), Spacer(1,10)]

    # ── PAGE 1 DEDUCTIONS ────────────────────────────────────────────────────
    story.append(sec("FORM 1065 — PAGE 1  |  DEDUCTIONS"))
    story.append(Spacer(1,2))
    ded_data = [
        row("Line 20a  Cash Operating Expenses",          abs(gl.get("Acct.Cash.Expense",0))),
        row("Line 20b  Utilities",                        abs(gl.get("Acct.Cash.Util",0))),
        row("TOTAL DEDUCTIONS  (Line 21)",                p1.total_deductions, total=True),
    ]
    story += [total_row_tbl(ded_data, [W*0.70, W*0.30]), Spacer(1,10)]

    # ── LINE 22 ───────────────────────────────────────────────────────────────
    net_clr = GREEN if p1.ordinary_income_loss >= 0 else RED
    net_tbl = Table([[
        Paragraph("LINE 22 — ORDINARY BUSINESS INCOME / (LOSS)", sty("NL", fontSize=11, textColor=WHITE, fontName="Helvetica-Bold")),
        Paragraph(fmt(p1.ordinary_income_loss), sty("NV", fontSize=13, textColor=GOLD, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
    ]], colWidths=[W*0.70, W*0.30])
    net_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), NAVY),
        ("LINEABOVE",    (0,0),(-1,-1), 2, GOLD),
        ("TOPPADDING",   (0,0),(-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LEFTPADDING",  (0,0),(0,-1),  8),
        ("RIGHTPADDING", (1,0),(1,-1),  8),
    ]))
    story += [net_tbl, Spacer(1,10)]

    # ── SCHEDULE K ────────────────────────────────────────────────────────────
    story.append(sec("SCHEDULE K — PARTNERS' DISTRIBUTIVE SHARE ITEMS"))
    story.append(Spacer(1,2))
    k_data = [
        row("Box 1   Ordinary Business Income / (Loss)",   sk.ordinary_income_loss),
        row("Box 2   Net Rental Real Estate Income",        sk.net_rental_income),
        row("Box 5   Interest Income",                      sk.interest_income),
        row("Box 11  Other Income",                         sk.other_income),
        row("TOTAL DISTRIBUTIVE INCOME",                    sk.total_distributive_income, total=True),
    ]
    story += [total_row_tbl(k_data, [W*0.70, W*0.30]), Spacer(1,10)]

    # ── SCHEDULE L ────────────────────────────────────────────────────────────
    story.append(sec("SCHEDULE L — BALANCE SHEET PER BOOKS (End of Tax Year)"))
    story.append(Spacer(1,2))

    asset_data = [
        row("  Cash — Beginning of Year",              sl.cash_beginning),
        row("  Cash — End of Year  (Balance acct)",    sl.cash_ending),
        row("  Depreciable Property at Cost  (Acct.Asset.Purchase)", sl.depreciable_property_cost),
        row("TOTAL ASSETS",                            sl.total_assets, total=True),
    ]
    story.append(Paragraph("ASSETS", sty("AS", fontSize=9, textColor=BLUE, fontName="Helvetica-Bold")))
    story += [total_row_tbl(asset_data, [W*0.70, W*0.30]), Spacer(1,4)]

    cap_data = [
        row("  Partners' Capital Contributions  (Acct.Cash.Investment)", sl.partners_capital_contrib),
        row("  Current Year Retained Earnings  (Ordinary Income)",       sl.retained_earnings),
        row("TOTAL LIABILITIES & PARTNERS' CAPITAL",                     sl.total_liabilities_capital, total=True),
    ]
    story.append(Paragraph("LIABILITIES & PARTNERS' CAPITAL", sty("LP", fontSize=9, textColor=BLUE, fontName="Helvetica-Bold")))
    story += [total_row_tbl(cap_data, [W*0.70, W*0.30]), Spacer(1,8)]

    # balance check
    diff = abs(sl.total_assets - sl.total_liabilities_capital)
    bal_ok = diff < 0.02
    bal_color = GREEN if bal_ok else RED
    bal_text  = "✔  Balance Sheet BALANCES" if bal_ok else f"✘  Balance Sheet OUT OF BALANCE  (difference: ${diff:,.2f})"
    story.append(Paragraph(bal_text, sty("BC", fontSize=8.5, textColor=bal_color, fontName="Helvetica-Bold")))
    story.append(Spacer(1,10))

    # ── NOTES ────────────────────────────────────────────────────────────────
    story.append(sec("PREPARER NOTES & ASSUMPTIONS"))
    story.append(Spacer(1,4))
    notes = [
        "1.  <b>Acct.Asset.Purchase</b> is treated as a capitalised depreciable asset on Schedule L. "
            "Depreciation deduction (§168 MACRS) must be computed separately on <b>Form 4562</b> "
            "and added to Line 20 deductions.",
        "2.  <b>Acct.Cash.Investment</b> is classified as partners' capital contributions "
            "(Schedule L line 21). It does not flow through the income statement.",
        "3.  <b>Acct.Cash.Expense</b> and <b>Acct.Cash.Util</b> are combined on Line 20 "
            "(Other Deductions). Attach a supporting schedule itemising each expense.",
        "4.  <b>Acct.Interest.Income</b> is reported on Line 5 and flows to Schedule K Box 5 "
            "for pass-through to each partner's K-1.",
        "5.  This worksheet is a <i>planning tool</i>. The preparer must complete the official "
            "IRS Form 1065 and all required schedules (K-1 per partner, Schedule B, etc.).",
    ]
    for n in notes:
        story.append(Paragraph(n, note_s))
        story.append(Spacer(1,3))

    story.append(Spacer(1,8))
    story.append(HRFlowable(width=W, thickness=0.5, color=BORDER))
    story.append(Spacer(1,4))
    story.append(Paragraph(
        "DISCLAIMER: This worksheet is generated from imported GL data for tax planning purposes only. "
        "It does not constitute a filed tax return or legal / tax advice. "
        "Consult a licensed CPA or Enrolled Agent before filing IRS Form 1065.",
        foot_s))

    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch,  bottomMargin=0.75*inch)
    doc.build(story)


# ════════════════════════════════════════════════════════════════════════════
#  DEMO — run directly: python form1065.py
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    general_ledger = {
        "Acct.Asset.Purchase":  -214_113.95,
        "Acct.Cash.Expense":      -1_766.92,
        "Acct.Cash.Income":        4_000.53,
        "Acct.Cash.Investment":  219_227.00,
        "Acct.Cash.Misc":             29.47,
        "Acct.Cash.Util":         -1_056.95,
        "Acct.Interest.Income":      400.00,
        "Balance":                 6_719.18,
    }

    preparer = Form1065Preparer(
        general_ledger,
        tax_year     = 2024,
        entity_name  = "Sunset Ridge Rentals LLC",
        ein          = "12-3456789",
        beginning_cash = 0.00,
    )

    preparer.compute()
    preparer.print_summary()

    try:
        preparer.export_pdf("Form_1065_Worksheet.pdf")
    except ImportError as e:
        print(f"[PDF skipped] {e}")

    # JSON export example
    import json
    data = preparer.to_dict()
    print("\nJSON snapshot (page1 only):")
    print(json.dumps(data["page1"], indent=2))
