"""
"""
from irs.data_F1065 import Form1065
 
# ════════════════════════════════════════════════════════════════════════════
#  PDF BUILDER  (internal – uses ReportLab)
# ════════════════════════════════════════════════════════════════════════════

def _build_pdf(r: Form1065, output_path: str) -> None:
    """Render Form1065Result to a professional PDF worksheet."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    except Exception as err:
        raise ImportError("reportlab is required for PDF export. "
                              "Run: pip install reportlab")


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
