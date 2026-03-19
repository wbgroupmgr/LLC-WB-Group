"""
form1065_generator.py
=====================
Class 2 of 2 — Form1065Generator

Imports a LLCGeneralLedger object and produces:
  1. IRS Form 1065 worksheet PDF  (Page 1 income/deductions + Schedules K, L, M-2)
  2. One Schedule K-1 PDF per LLC member

All output is generated with ReportLab (no external IRS PDF required).

Usage
-----
  from gl_ledger import LLCGeneralLedger
  from form1065_generator import Form1065Generator

  gl  = LLCGeneralLedger.from_dict(GL_DICT, entity_name="Sunset Ridge Rentals LLC",
                                    ein="12-3456789", tax_year=2024)
  gen = Form1065Generator(gl)
  gen.generate_all(output_dir="output")
  # writes:
  #   output/Form_1065_Worksheet.pdf
  #   output/Schedule_K1_Managing_Partner.pdf
  #   output/Schedule_K1_Member_B.pdf
  #   output/Schedule_K1_Member_C.pdf
"""

from __future__ import annotations

import os
from typing import List

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak,
)

from gl_ledger import LLCGeneralLedger, LLCMember


# ─────────────────────────────────────────────────────────────────────────────
#  PALETTE  &  STYLE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

NAVY   = colors.HexColor("#1a3560")
BLUE   = colors.HexColor("#2e6da4")
LBLUE  = colors.HexColor("#d6e8f7")
GOLD   = colors.HexColor("#c8860a")
WHITE  = colors.white
GRAY   = colors.HexColor("#f4f6f9")
BORDER = colors.HexColor("#c4d0de")
GREEN  = colors.HexColor("#1a6e2e")
RED    = colors.HexColor("#a61c00")
LTGRAY = colors.HexColor("#e8edf2")

W = 7.0 * inch     # usable page width


def _sty(name: str, base, **kw) -> ParagraphStyle:
    parent = kw.pop("parent", base["Normal"])
    return ParagraphStyle(name, parent=parent, **kw)


def _fmt(v: float, parens: bool = True) -> str:
    """IRS-style number: whole dollars, negative in parens."""
    if parens and v < 0:
        return f"({abs(v):,.0f})"
    return f"{abs(v):,.0f}"


def _fmtc(v: float) -> str:
    """Two-decimal variant for balance-sheet amounts."""
    if v < 0:
        return f"({abs(v):,.2f})"
    return f"{v:,.2f}"


def _color(v: float):
    return GREEN if v >= 0 else RED


# ─────────────────────────────────────────────────────────────────────────────
#  SHARED TABLE BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _section_header(title: str, color=BLUE) -> Table:
    s = ParagraphStyle("sh", fontName="Helvetica-Bold", fontSize=11,
                       textColor=WHITE, leftIndent=6)
    t = Table([[Paragraph(title, s)]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), color),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _data_table(rows: list, col_w: list, last_is_total: bool = False) -> Table:
    t = Table(rows, colWidths=col_w)
    cmds = [
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, GRAY]),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("LEFTPADDING",    (0, 0), (0, -1),  8),
        ("RIGHTPADDING",   (-1, 0), (-1, -1), 8),
        ("GRID",           (0, 0), (-1, -1), 0.4, BORDER),
    ]
    if last_is_total:
        n = len(rows) - 1
        cmds += [
            ("BACKGROUND", (0, n), (-1, n), NAVY),
            ("LINEABOVE",  (0, n), (-1, n), 1.5, GOLD),
        ]
    t.setStyle(TableStyle(cmds))
    return t


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class Form1065Generator:
    """
    Generates IRS Form 1065 worksheet + per-member Schedule K-1 PDFs
    from a LLCGeneralLedger instance.
    """

    def __init__(self, gl: LLCGeneralLedger):
        self.gl      = gl
        self.c       = gl.computed
        self.members = gl.members
        self.alloc   = gl.allocations
        self._base   = getSampleStyleSheet()

    # ── public API ────────────────────────────────────────────────────────────

    def generate_all(self, output_dir: str = ".") -> List[str]:
        """Generate Form 1065 + all K-1s. Returns list of file paths written."""
        os.makedirs(output_dir, exist_ok=True)
        paths = []
        paths.append(self.generate_1065(output_dir))
        for member in self.members:
            paths.append(self.generate_k1(member, output_dir))
        print(f"\n✅  Generated {len(paths)} PDF(s) in '{output_dir}/'")
        for p in paths:
            print(f"   • {p}")
        return paths

    def generate_1065(self, output_dir: str = ".") -> str:
        """Build and save the Form 1065 worksheet PDF."""
        path = os.path.join(output_dir, "Form_1065_Worksheet.pdf")
        doc  = SimpleDocTemplate(
            path, pagesize=letter,
            leftMargin=0.75*inch, rightMargin=0.75*inch,
            topMargin=0.75*inch,  bottomMargin=0.75*inch,
        )
        story = []
        story += self._1065_header()
        story += self._1065_entity_bar()
        story += [Spacer(1, 8)]
        story += self._1065_income()
        story += self._1065_deductions()
        story += self._1065_net_line()
        story += self._schedule_k_combined()
        story += self._schedule_l()
        story += self._schedule_m2()
        story += self._notes()
        doc.build(story)
        return path

    def generate_k1(self, member: LLCMember, output_dir: str = ".") -> str:
        """Build and save a Schedule K-1 for one member."""
        safe = member.name.replace(" ", "_")
        path = os.path.join(output_dir, f"Schedule_K1_{safe}.pdf")
        doc  = SimpleDocTemplate(
            path, pagesize=letter,
            leftMargin=0.75*inch, rightMargin=0.75*inch,
            topMargin=0.75*inch,  bottomMargin=0.75*inch,
        )
        story = []
        story += self._k1_header(member)
        story += self._k1_partner_info(member)
        story += self._k1_distributive_share(member)
        story += self._k1_capital_account(member)
        story += self._k1_footnote(member)
        doc.build(story)
        return path

    # ═════════════════════════════════════════════════════════════════════════
    #  FORM 1065 SECTIONS
    # ═════════════════════════════════════════════════════════════════════════

    def _1065_header(self) -> list:
        s_title = _sty("t", self._base, fontSize=18, textColor=WHITE,
                        alignment=TA_CENTER, fontName="Helvetica-Bold")
        s_sub   = _sty("s", self._base, fontSize=9,  textColor=LBLUE,
                        alignment=TA_CENTER, fontName="Helvetica")
        hdr = Table([
            [Paragraph("FORM 1065 — U.S. RETURN OF PARTNERSHIP INCOME", s_title)],
            [Paragraph(
                f"LLC Rental Business &nbsp;|&nbsp; Tax Year {self.gl.tax_year}"
                f" &nbsp;|&nbsp; Worksheet Prepared by Tax Advisor", s_sub)],
        ], colWidths=[W])
        hdr.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
            ("TOPPADDING",    (0, 0), (-1,  0), 12),
            ("BOTTOMPADDING", (0, 1), (-1,  1), 10),
            ("LINEBELOW",     (0, 0), (-1,  0), 1, GOLD),
        ]))
        return [hdr]

    def _1065_entity_bar(self) -> list:
        s = _sty("eb", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica")
        sb = _sty("ebs", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica-Bold")
        bar = Table([[
            Paragraph(f"<b>Entity:</b>  {self.gl.entity_name}", s),
            Paragraph(f"<b>EIN:</b>  {self.gl.ein}", s),
            Paragraph(f"<b>Principal Activity:</b>  Residential Rental", s),
            Paragraph(f"<b>Partners:</b>  {len(self.members)}", s),
        ]], colWidths=[W*0.35, W*0.18, W*0.30, W*0.17])
        bar.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), LBLUE),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        return [Spacer(1, 6), bar]

    def _1065_income(self) -> list:
        c  = self.c
        sl = _sty("il", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica")
        vl = _sty("iv", self._base, fontSize=9, textColor=NAVY,
                   fontName="Helvetica-Bold", alignment=TA_RIGHT)
        tl = _sty("it", self._base, fontSize=9, textColor=WHITE, fontName="Helvetica-Bold")
        tv = _sty("itv", self._base, fontSize=9, textColor=WHITE,
                   fontName="Helvetica-Bold", alignment=TA_RIGHT)

        def row(lbl, val, total=False):
            ls = tl if total else sl
            vs = _sty("x", self._base, fontSize=9,
                       textColor=(WHITE if total else _color(val)),
                       fontName="Helvetica-Bold", alignment=TA_RIGHT)
            return [Paragraph(lbl, ls), Paragraph(_fmt(val), vs)]

        rows = [
            row("Line 1a   Gross Receipts / Rental Income",          c["line_1a"]),
            row("Line 5    Interest Income",                          c["line_5"]),
            row("Line 7    Other Income (Miscellaneous Cash)",        c["line_7"]),
            row("Line 8    TOTAL INCOME",                             c["line_8"],  total=True),
        ]
        return [
            Spacer(1, 6),
            _section_header("PAGE 1 — INCOME  (IRC §61)"),
            Spacer(1, 2),
            _data_table(rows, [W*0.72, W*0.28], last_is_total=True),
        ]

    def _1065_deductions(self) -> list:
        c  = self.c
        sl = _sty("dl", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica")
        tl = _sty("dt", self._base, fontSize=9, textColor=WHITE, fontName="Helvetica-Bold")

        def row(lbl, val, total=False):
            ls = tl if total else sl
            vs = _sty("dx", self._base, fontSize=9,
                       textColor=(WHITE if total else _color(-val)),  # expenses are negative
                       fontName="Helvetica-Bold", alignment=TA_RIGHT)
            return [Paragraph(lbl, ls), Paragraph(_fmt(val), vs)]

        rows = [
            row("Line 20a  Operating Expenses  (Acct.Cash.Expense)",  c["line_20_exp"]),
            row("Line 20b  Utilities            (Acct.Cash.Util)",    c["line_20_util"]),
            row("Line 21   TOTAL DEDUCTIONS",                          c["line_21"],  total=True),
        ]
        note_s = _sty("dn", self._base, fontSize=7.5,
                       textColor=colors.HexColor("#555"), fontName="Helvetica-Oblique")
        return [
            Spacer(1, 6),
            _section_header("PAGE 1 — DEDUCTIONS  (IRC §162 / §168)"),
            Spacer(1, 2),
            _data_table(rows, [W*0.72, W*0.28], last_is_total=True),
            Spacer(1, 3),
            Paragraph(
                "★  Acct.Asset.Purchase is capitalised as depreciable property on Schedule L. "
                "MACRS depreciation (Form 4562) must be computed separately and added to Line 20.",
                note_s),
        ]

    def _1065_net_line(self) -> list:
        val  = self.c["line_22"]
        s_lbl = _sty("nl", self._base, fontSize=12, textColor=WHITE,
                      fontName="Helvetica-Bold")
        s_val = _sty("nv", self._base, fontSize=14, textColor=GOLD,
                      fontName="Helvetica-Bold", alignment=TA_RIGHT)
        t = Table([[
            Paragraph("LINE 22 — ORDINARY BUSINESS INCOME / (LOSS)", s_lbl),
            Paragraph(_fmt(val), s_val),
        ]], colWidths=[W*0.72, W*0.28])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
            ("LINEABOVE",     (0, 0), (-1, -1), 2, GOLD),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (0, -1),  8),
            ("RIGHTPADDING",  (1, 0), (1, -1),  8),
        ]))
        return [Spacer(1, 8), t]

    def _schedule_k_combined(self) -> list:
        """Schedule K — partners' distributive share totals + per-member breakdown."""
        c    = self.c
        alloc = self.alloc

        # ── header row ─────────────────────────────────────────────────────
        hdr_s = _sty("kh", self._base, fontSize=8.5, textColor=WHITE,
                      fontName="Helvetica-Bold")
        hdr_r = _sty("khr", self._base, fontSize=8.5, textColor=WHITE,
                      fontName="Helvetica-Bold", alignment=TA_RIGHT)

        cols = [W*0.30] + [W*0.175] * (len(self.members) + 1)  # label + total + members

        def hcell(txt, right=False):
            return Paragraph(txt, hdr_r if right else hdr_s)

        header_row = (
            [hcell("Schedule K Item")]
            + [hcell("Partnership\nTotal", right=True)]
            + [hcell(f"{m.name}\n({m.pct_display})", right=True) for m in self.members]
        )

        # ── data rows ──────────────────────────────────────────────────────
        lbl_s = _sty("kl", self._base, fontSize=8.5, textColor=NAVY, fontName="Helvetica")

        def vcell(val, is_total=False):
            col = WHITE if is_total else _color(val)
            fn  = "Helvetica-Bold"
            s   = _sty("kv", self._base, fontSize=8.5, textColor=col,
                        fontName=fn, alignment=TA_RIGHT)
            return Paragraph(_fmt(val), s)

        def drow(label, total_val, alloc_key, is_total=False):
            ls = _sty("kll", self._base, fontSize=8.5,
                       textColor=(WHITE if is_total else NAVY),
                       fontName=("Helvetica-Bold" if is_total else "Helvetica"))
            return (
                [Paragraph(label, ls)]
                + [vcell(total_val, is_total)]
                + [vcell(alloc[m.name][alloc_key], is_total) for m in self.members]
            )

        k_rows = [
            header_row,
            drow("Box 1   Ordinary Income/(Loss)", c["k_ordinary"], "ordinary_income"),
            drow("Box 2   Net Rental Real Estate Income", c["k_rental"], "rental_income"),
            drow("Box 5   Interest Income",         c["k_interest"], "interest_income"),
            drow("Box 11  Other Income",             c["k_other"],   "other_income"),
            drow("TOTAL DISTRIBUTIVE INCOME",        c["line_22"],   "ordinary_income", is_total=True),
        ]

        t = Table(k_rows, colWidths=cols)
        n = len(k_rows) - 1
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  NAVY),
            ("ROWBACKGROUNDS",(0, 1), (-1, n-1), [WHITE, GRAY]),
            ("BACKGROUND",    (0, n), (-1, n),  NAVY),
            ("LINEABOVE",     (0, n), (-1, n),  1.5, GOLD),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (0, -1),  8),
            ("RIGHTPADDING",  (-1, 0),(-1, -1), 8),
            ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ]))

        return [
            Spacer(1, 8),
            _section_header("SCHEDULE K — PARTNERS' DISTRIBUTIVE SHARE ITEMS"),
            Spacer(1, 2),
            t,
        ]

    def _schedule_l(self) -> list:
        c   = self.c
        sl  = _sty("ll", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica")
        tl  = _sty("lt", self._base, fontSize=9, textColor=WHITE, fontName="Helvetica-Bold")
        vl  = _sty("lv", self._base, fontSize=9, textColor=NAVY,
                    fontName="Helvetica-Bold", alignment=TA_RIGHT)
        tv  = _sty("ltv", self._base, fontSize=9, textColor=WHITE,
                    fontName="Helvetica-Bold", alignment=TA_RIGHT)
        gh  = _sty("lgh", self._base, fontSize=8, textColor=WHITE,
                    fontName="Helvetica-Bold", alignment=TA_RIGHT)

        def hrow():
            s = _sty("lhh", self._base, fontSize=8.5, textColor=WHITE,
                      fontName="Helvetica-Bold")
            return [
                Paragraph("Description", s),
                Paragraph("Beg. of Year", gh),
                Paragraph("End of Year",  gh),
            ]

        def arow(lbl, beg, end, total=False):
            ls  = tl if total else sl
            vs  = tv if total else vl
            col = [WHITE if total else _color(beg), WHITE if total else _color(end)]
            def vc(v, c): return Paragraph(_fmtc(v),
                _sty("lvc", self._base, fontSize=9, textColor=c,
                     fontName="Helvetica-Bold", alignment=TA_RIGHT))
            return [Paragraph(lbl, ls), vc(beg, col[0]), vc(end, col[1])]

        asset_rows = [
            hrow(),
            arow("  Cash & Bank Balances",              c["cash_beg"],    c["cash_end"]),
            arow("  Depreciable Property (Cost)  [Acct.Asset.Purchase]",
                                                         0.0,              c["asset_cost"]),
            arow("TOTAL ASSETS",                         0.0,              c["total_assets"], total=True),
        ]
        cap_rows = [
            hrow(),
            arow("  Partners' Capital Contributions",   0.0,              c["cap_contrib"]),
            arow("  Retained Earnings (Current Year)",  0.0,              c["line_22"]),
            arow("TOTAL LIABILITIES & PARTNERS' CAPITAL",0.0,             c["cap_end"], total=True),
        ]

        def make_tbl(rows):
            t = Table(rows, colWidths=[W*0.54, W*0.23, W*0.23])
            n = len(rows) - 1
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),  NAVY),
                ("ROWBACKGROUNDS",(0, 1), (-1, n-1), [WHITE, GRAY]),
                ("BACKGROUND",    (0, n), (-1, n),  NAVY),
                ("LINEABOVE",     (0, n), (-1, n),  1.5, GOLD),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (0, -1),  8),
                ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            return t

        sub_s = _sty("lsub", self._base, fontSize=9, textColor=BLUE, fontName="Helvetica-Bold")
        bal_ok = abs(c["total_assets"] - c["cap_end"]) < 0.02
        bal_s  = _sty("lb", self._base, fontSize=8.5,
                       textColor=(GREEN if bal_ok else RED), fontName="Helvetica-Bold")
        bal_msg = ("✔  Balance Sheet BALANCES" if bal_ok
                   else f"✘  OUT OF BALANCE  (diff: ${abs(c['total_assets']-c['cap_end']):,.2f})")

        return [
            Spacer(1, 8),
            _section_header("SCHEDULE L — BALANCE SHEET PER BOOKS"),
            Spacer(1, 2),
            Paragraph("ASSETS", sub_s), Spacer(1, 2),
            make_tbl(asset_rows),
            Spacer(1, 4),
            Paragraph("LIABILITIES & PARTNERS' CAPITAL", sub_s), Spacer(1, 2),
            make_tbl(cap_rows),
            Spacer(1, 4),
            Paragraph(bal_msg, bal_s),
        ]

    def _schedule_m2(self) -> list:
        c  = self.c
        sl = _sty("m2l", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica")
        tl = _sty("m2t", self._base, fontSize=9, textColor=WHITE, fontName="Helvetica-Bold")

        def row(lbl, val, total=False):
            ls = tl if total else sl
            vs = _sty("m2v", self._base, fontSize=9,
                       textColor=(WHITE if total else _color(val)),
                       fontName="Helvetica-Bold", alignment=TA_RIGHT)
            return [Paragraph(lbl, ls), Paragraph(_fmtc(val), vs)]

        rows = [
            row("Line 1   Balance at Beginning of Year",               c["m2_beg"]),
            row("Line 2   Capital Contributed During Year",             c["m2_contrib"]),
            row("Line 3   Net Income per Books (Ordinary Income)",      c["m2_net"]),
            row("Line 6   Distributions",                               c["m2_dist"]),
            row("Line 9   BALANCE AT END OF YEAR",                     c["m2_end"], total=True),
        ]
        return [
            Spacer(1, 8),
            _section_header("SCHEDULE M-2 — ANALYSIS OF PARTNERS' CAPITAL ACCOUNTS"),
            Spacer(1, 2),
            _data_table(rows, [W*0.72, W*0.28], last_is_total=True),
        ]

    def _notes(self) -> list:
        note_s = _sty("ns", self._base, fontSize=7.5,
                       textColor=colors.HexColor("#444"), fontName="Helvetica-Oblique")
        foot_s = _sty("fs", self._base, fontSize=7,
                       textColor=colors.HexColor("#888"), alignment=TA_CENTER)
        notes = [
            "1.  <b>Acct.Asset.Purchase</b> is treated as a capitalised depreciable asset (Schedule L). "
                "MACRS depreciation must be computed on Form 4562 and deducted on Line 16.",
            "2.  <b>Acct.Cash.Investment</b> is a capital contribution and does not flow through the income statement.",
            "3.  This worksheet does not constitute a filed tax return. File the official IRS Form 1065 "
                "with all required schedules and K-1s.",
            "4.  All allocations use the fixed ownership percentages: "
            + ", ".join(f"{m.name} {m.pct_display}" for m in self.members) + ".",
        ]
        items = [
            Spacer(1, 10),
            _section_header("PREPARER NOTES"),
            Spacer(1, 4),
        ]
        for n in notes:
            items.append(Paragraph(n, note_s))
            items.append(Spacer(1, 3))
        items += [
            Spacer(1, 8),
            HRFlowable(width=W, thickness=0.5, color=BORDER),
            Spacer(1, 4),
            Paragraph(
                "DISCLAIMER: Prepared for tax planning purposes only. "
                "Not a substitute for a filed IRS Form 1065. "
                "Consult a licensed CPA or Enrolled Agent before filing.",
                foot_s),
        ]
        return items

    # ═════════════════════════════════════════════════════════════════════════
    #  SCHEDULE K-1 SECTIONS
    # ═════════════════════════════════════════════════════════════════════════

    def _k1_header(self, m: LLCMember) -> list:
        TEAL = colors.HexColor("#0d4f6e")
        s_title = _sty("k1t", self._base, fontSize=16, textColor=WHITE,
                        alignment=TA_CENTER, fontName="Helvetica-Bold")
        s_sub   = _sty("k1s", self._base, fontSize=9,  textColor=LBLUE,
                        alignment=TA_CENTER, fontName="Helvetica")
        hdr = Table([
            [Paragraph("SCHEDULE K-1 (FORM 1065)", s_title)],
            [Paragraph(
                f"Partner's Share of Income, Deductions, Credits &nbsp;|&nbsp; "
                f"Tax Year {self.gl.tax_year}", s_sub)],
        ], colWidths=[W])
        hdr.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), TEAL),
            ("TOPPADDING",    (0, 0), (-1,  0), 12),
            ("BOTTOMPADDING", (0, 1), (-1,  1), 10),
            ("LINEBELOW",     (0, 0), (-1,  0), 1, GOLD),
        ]))

        # role badge
        role_txt = "Managing Partner" if m.is_managing else "Member"
        role_s   = _sty("k1r", self._base, fontSize=10, textColor=WHITE,
                          fontName="Helvetica-Bold", alignment=TA_CENTER)
        badge    = Table([[Paragraph(
            f"{'★ ' if m.is_managing else ''}{role_txt.upper()}  —  "
            f"{m.pct_display} OWNERSHIP INTEREST", role_s)]], colWidths=[W])
        badge.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GOLD),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return [hdr, badge]

    def _k1_partner_info(self, m: LLCMember) -> list:
        TEAL = colors.HexColor("#0d4f6e")
        ls = _sty("pi", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica")
        lb = _sty("pib", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica-Bold")

        def info_row(left_lbl, left_val, right_lbl, right_val):
            return [
                Paragraph(f"<b>{left_lbl}:</b>  {left_val}", ls),
                Paragraph(f"<b>{right_lbl}:</b>  {right_val}", ls),
            ]

        rows = [
            info_row("Partner Name",      m.name,           "EIN / SSN",       m.ein_or_ssn),
            info_row("Partnership Name",  self.gl.entity_name, "Partnership EIN", self.gl.ein),
            info_row("Tax Year",          str(self.gl.tax_year), "Partner Type",  "LLC Member"),
            info_row("Ownership %",       m.pct_display,    "Profit %",        m.pct_display),
        ]
        t = Table(rows, colWidths=[W*0.50, W*0.50])
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, GRAY]),
            ("TOPPADDING",     (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
            ("LEFTPADDING",    (0, 0), (-1, -1), 8),
            ("GRID",           (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        return [Spacer(1, 8), _section_header("PART I & II — INFORMATION ABOUT PARTNERSHIP & PARTNER",
                                               color=colors.HexColor("#0d4f6e")),
                Spacer(1, 2), t]

    def _k1_distributive_share(self, m: LLCMember) -> list:
        TEAL   = colors.HexColor("#0d4f6e")
        a      = self.alloc[m.name]
        c      = self.c

        lbl_s  = _sty("ks", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica")
        pct_s  = _sty("kp", self._base, fontSize=9, textColor=colors.HexColor("#555"),
                       fontName="Helvetica", alignment=TA_CENTER)
        tot_l  = _sty("ktl", self._base, fontSize=9, textColor=WHITE, fontName="Helvetica-Bold")
        tot_v  = _sty("ktv", self._base, fontSize=10, textColor=GOLD,
                       fontName="Helvetica-Bold", alignment=TA_RIGHT)

        TEAL_MED = colors.HexColor("#1a6e8e")

        # Column header
        hdr_s = _sty("khs", self._base, fontSize=8.5, textColor=WHITE,
                      fontName="Helvetica-Bold")
        hdr_r = _sty("khr2", self._base, fontSize=8.5, textColor=WHITE,
                      fontName="Helvetica-Bold", alignment=TA_RIGHT)
        header = [
            Paragraph("K-1 Box / Description", hdr_s),
            Paragraph("Partnership Total", hdr_r),
            Paragraph(f"Your Share ({m.pct_display})", hdr_r),
        ]

        def vrow(box, lbl, pct_total, partner_val, total=False):
            ls = tot_l if total else lbl_s
            def vc(v, t=False):
                col = WHITE if t else _color(v)
                s   = _sty("kvv", self._base, fontSize=9, textColor=col,
                             fontName="Helvetica-Bold", alignment=TA_RIGHT)
                return Paragraph(_fmt(v), s)
            return [Paragraph(f"{box}   {lbl}", ls), vc(pct_total, total), vc(partner_val, total)]

        rows = [
            header,
            vrow("Box 1",  "Ordinary Business Income/(Loss)", c["k_ordinary"], a["ordinary_income"]),
            vrow("Box 2",  "Net Rental Real Estate Income",   c["k_rental"],   a["rental_income"]),
            vrow("Box 5",  "Interest Income",                 c["k_interest"], a["interest_income"]),
            vrow("Box 11", "Other Income",                    c["k_other"],    a["other_income"]),
            vrow("",       "TOTAL DISTRIBUTIVE SHARE",        c["line_22"],    a["ordinary_income"], total=True),
        ]

        t = Table(rows, colWidths=[W*0.48, W*0.26, W*0.26])
        n = len(rows) - 1
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  TEAL),
            ("ROWBACKGROUNDS",(0, 1), (-1, n-1), [WHITE, GRAY]),
            ("BACKGROUND",    (0, n), (-1, n),  TEAL),
            ("LINEABOVE",     (0, n), (-1, n),  1.5, GOLD),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (0, -1),  8),
            ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        return [
            Spacer(1, 8),
            _section_header("PART III — PARTNER'S SHARE OF CURRENT YEAR INCOME & DEDUCTIONS",
                             color=TEAL),
            Spacer(1, 2),
            t,
        ]

    def _k1_capital_account(self, m: LLCMember) -> list:
        TEAL  = colors.HexColor("#0d4f6e")
        a     = self.alloc[m.name]
        c     = self.c

        lbl_s = _sty("cal", self._base, fontSize=9, textColor=NAVY, fontName="Helvetica")
        tot_l = _sty("cat", self._base, fontSize=9, textColor=WHITE, fontName="Helvetica-Bold")

        def vc(v, total=False):
            col = WHITE if total else _color(v)
            s   = _sty("cav", self._base, fontSize=9, textColor=col,
                         fontName="Helvetica-Bold", alignment=TA_RIGHT)
            return Paragraph(_fmtc(v), s)

        rows = [
            [Paragraph("Capital Account Analysis", _sty("cah", self._base, fontSize=8.5,
                        textColor=WHITE, fontName="Helvetica-Bold")),
             Paragraph("Amount", _sty("cahv", self._base, fontSize=8.5,
                        textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
            [Paragraph("Beginning Capital Account Balance", lbl_s), vc(0.0)],
            [Paragraph(f"Capital Contributed  ({m.pct_display} of ${c['cap_contrib']:,.0f})", lbl_s),
             vc(a["capital_contrib"])],
            [Paragraph(f"Current Year Net Income  ({m.pct_display} of ${c['line_22']:,.0f})", lbl_s),
             vc(a["ordinary_income"])],
            [Paragraph("Withdrawals and Distributions", lbl_s), vc(0.0)],
            [Paragraph("ENDING CAPITAL ACCOUNT", tot_l), vc(a["ending_capital"], total=True)],
        ]
        t = Table(rows, colWidths=[W*0.72, W*0.28])
        n = len(rows) - 1
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  TEAL),
            ("ROWBACKGROUNDS",(0, 1), (-1, n-1), [WHITE, GRAY]),
            ("BACKGROUND",    (0, n), (-1, n),  TEAL),
            ("LINEABOVE",     (0, n), (-1, n),  1.5, GOLD),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (0, -1),  8),
            ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        return [
            Spacer(1, 8),
            _section_header("PART II — CAPITAL ACCOUNT  (Tax Basis)", color=TEAL),
            Spacer(1, 2),
            t,
        ]

    def _k1_footnote(self, m: LLCMember) -> list:
        TEAL  = colors.HexColor("#0d4f6e")
        note_s = _sty("kfn", self._base, fontSize=8,
                       textColor=colors.HexColor("#444"), fontName="Helvetica-Oblique")
        foot_s = _sty("kff", self._base, fontSize=7,
                       textColor=colors.HexColor("#888"), alignment=TA_CENTER)
        notes = [
            f"1.  This Schedule K-1 reflects <b>{m.name}'s {m.pct_display} ownership interest</b> "
                f"in {self.gl.entity_name} for tax year {self.gl.tax_year}.",
            "2.  <b>Box 2 — Net Rental Real Estate Income</b> must be reported on your Form 1040 "
                "Schedule E (not Schedule C).",
            "3.  <b>Box 5 — Interest Income</b> flows to your Form 1040 Schedule B.",
            "4.  Passive activity loss rules (IRC §469) may limit deductibility of rental losses.",
            "5.  Retain this K-1 for your records. Do not file it with your tax return.",
        ]
        items = [
            Spacer(1, 10),
            _section_header("NOTES FOR PARTNER", color=TEAL),
            Spacer(1, 4),
        ]
        for n in notes:
            items.append(Paragraph(n, note_s))
            items.append(Spacer(1, 3))
        items += [
            Spacer(1, 8),
            HRFlowable(width=W, thickness=0.5, color=BORDER),
            Spacer(1, 4),
            Paragraph(
                "DISCLAIMER: This Schedule K-1 is prepared for tax planning purposes only. "
                "Consult a licensed CPA or tax attorney before filing your individual return.",
                foot_s),
        ]
        return items