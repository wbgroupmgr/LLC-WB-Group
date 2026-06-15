"""
ledger/yeFinancialReport.py
YEFinancialReportAgent — generates a Year-End Financial Report PDF.

Output: books/{year}/Forms/{dataName}_{year}_YEFinancialReport.pdf

Usage:
    from ledger.yeFinancialReport import YEFinancialReportAgent
    agent = YEFinancialReportAgent(eSession)
    path  = agent.generate()   # returns Path of output PDF
"""

import datetime
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── reportlab imports ─────────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle
)
from reportlab.platypus.flowables import HRFlowable

# ── colour palette ────────────────────────────────────────────────────────────
C_HEADER   = colors.HexColor('#1e3a8a')
C_SUBHDR   = colors.HexColor('#1d4ed8')
C_ROW_ALT  = colors.HexColor('#f0f4ff')
C_NEG      = colors.HexColor('#dc2626')
C_MUTED    = colors.HexColor('#6b7280')
C_BORDER   = colors.HexColor('#e5e7eb')
C_WARN_BG  = colors.HexColor('#fffbeb')
C_WARN_BD  = colors.HexColor('#fbbf24')
C_BLACK    = colors.black
C_WHITE    = colors.white


def _fmt(v: Any, parens: bool = True) -> str:
    """Format a number as currency string; negatives in parens."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return str(v or '')
    if n < 0 and parens:
        return f'(${abs(n):,.2f})'
    return f'${n:,.2f}'


def _pct(v: Any) -> str:
    try:
        return f'{float(v or 0):.1f}%'
    except (TypeError, ValueError):
        return str(v or '')


# ── Page frame builder ────────────────────────────────────────────────────────
_M = 0.75 * inch

def _make_frame(name: str, page_w, page_h, top_margin=_M) -> Frame:
    return Frame(_M, _M, page_w - 2 * _M, page_h - top_margin - _M,
                 id=name, leftPadding=0, rightPadding=0,
                 topPadding=0, bottomPadding=0)


# ─────────────────────────────────────────────────────────────────────────────
class YEFinancialReportAgent:
    """
    Generates a year-end financial report PDF from the live GL.

    Sections:
      Cover  — entity metadata, year, EIN
      § 1    — Financial Summary (prose)
      § 2    — Balance Sheet + notes
      § 3    — Income Statement + notes
      § 4    — Depreciation Schedule
      § 5    — Member Capital Account Analysis
      § 6    — Outstanding Items & CPA Flags
    """

    VERSION = '0.3'

    def __init__(self, eSession):
        self.eSession = eSession
        self.llc      = eSession.llc
        self.year     = int(getattr(self.llc, 'yr', datetime.date.today().year))

    # ── entry point ───────────────────────────────────────────────────────────

    def generate(self) -> Path:
        """Build the PDF and return its Path."""
        from ledger import setup_paths
        from ui.llcReportEngine  import llcReportEngine
        from ledger.auditor      import GLAuditor
        from ledger.stmtBS       import stmtBS_View
        from ledger.stmtIS       import stmtIS_View

        engine     = llcReportEngine(self.eSession)
        gl_records = engine.getGLList(resolve_dups=True, force=True)
        auditor    = GLAuditor(self.llc, gl_records)

        self._eq      = auditor.equation_summary()
        self._gl      = gl_records
        self._profile = self._load_profile(setup_paths)
        self._owners  = engine.load_owners()
        self._bs_rows = stmtBS_View(self.llc, gl_records=gl_records).view(view_by='All', with_totals=False)
        is_view       = stmtIS_View(self.llc, gl_records=gl_records)
        self._is_rows = is_view.view(view_by='All', with_totals=True)
        self._is_agg  = is_view.taxAggregates()   # authoritative income/expense totals
        self._assets  = self._load_assets(setup_paths)
        self._props   = self._classify_props()   # {active:[...], construction:[...]}

        out_dir  = Path(str(setup_paths.IRS_FORMS_DIR))
        out_dir.mkdir(parents=True, exist_ok=True)
        data_nm  = getattr(self.llc, 'objName', 'LLC')
        out_path = out_dir / f'{data_nm}_{self.year}_YEFinancialReport.pdf'

        self._build_pdf(out_path)
        return out_path

    # ── PDF construction ──────────────────────────────────────────────────────

    def _build_pdf(self, path: Path):
        pw, ph = LETTER
        doc = BaseDocTemplate(
            str(path),
            pagesize=LETTER,
            leftMargin=_M, rightMargin=_M,
            topMargin=_M,  bottomMargin=_M,
        )
        cover_frame  = _make_frame('cover',  pw, ph, top_margin=_M)
        body_frame   = _make_frame('body',   pw, ph, top_margin=_M + 0.4 * inch)

        def _cover_page(canvas, doc):
            pass

        def _body_page(canvas, doc):
            canvas.saveState()
            # header bar
            canvas.setFillColor(C_HEADER)
            canvas.rect(_M, ph - _M - 0.32 * inch, pw - 2 * _M, 0.32 * inch, fill=1, stroke=0)
            canvas.setFillColor(C_WHITE)
            canvas.setFont('Helvetica-Bold', 9)
            ent = self._entity_name()
            canvas.drawString(_M + 6, ph - _M - 0.22 * inch, f'{ent}  ·  {self.year} Fiscal Period Financial Report')
            # footer
            canvas.setFillColor(C_MUTED)
            canvas.setFont('Helvetica', 7)
            canvas.drawRightString(pw - _M, 0.45 * inch,
                f'Prepared by llcRentalTracker v{self.VERSION}  ·  Page {doc.page}')
            canvas.restoreState()

        doc.addPageTemplates([
            PageTemplate(id='Cover', frames=[cover_frame], onPage=_cover_page),
            PageTemplate(id='Body',  frames=[body_frame],  onPage=_body_page),
        ])

        story = []
        story += self._cover()
        story += [NextPageTemplate('Body'), PageBreak()]
        story += self._section1_summary()
        story += [PageBreak()]
        story += self._section2_balance_sheet()
        story += [PageBreak()]
        story += self._section3_income_stmt()
        story += [PageBreak()]
        story += self._section4_depreciation()
        story += self._section5_capital()
        story += [PageBreak()]
        story += self._section6_flags()

        doc.build(story)

    # ── styles ────────────────────────────────────────────────────────────────

    def _styles(self):
        ss = getSampleStyleSheet()
        def s(name, **kw):
            base = kw.pop('parent', 'Normal')
            return ParagraphStyle(name, parent=ss[base], **kw)
        return {
            'title':    s('title',    fontSize=26, textColor=C_HEADER, spaceAfter=4,
                          fontName='Helvetica-Bold'),
            'subtitle': s('subtitle', fontSize=13, textColor=C_SUBHDR, spaceAfter=2,
                          fontName='Helvetica'),
            'meta':     s('meta',     fontSize=9,  textColor=C_MUTED,  spaceAfter=2),
            'h1':       s('h1',       fontSize=13, textColor=C_HEADER, spaceBefore=12,
                          spaceAfter=4, fontName='Helvetica-Bold'),
            'h2':       s('h2',       fontSize=10, textColor=C_SUBHDR, spaceBefore=8,
                          spaceAfter=3, fontName='Helvetica-Bold'),
            'body':     s('body',     fontSize=9,  spaceAfter=4, leading=13),
            'note':     s('note',     fontSize=8,  textColor=C_MUTED, spaceAfter=3, leading=11),
            'warn':     s('warn',     fontSize=8,  textColor=colors.HexColor('#92400e'),
                          spaceAfter=3),
        }

    # ── cover page ────────────────────────────────────────────────────────────

    def _cover(self) -> list:
        st  = self._styles()
        ent = self._entity_name()
        ein = self._profile.get('entity', {}).get('ein', '')
        addr = self._profile.get('entity', {}).get('address', '')
        csz  = self._profile.get('entity', {}).get('city_state_zip', '')
        prod = self._profile.get('entity', {}).get('product', 'Rental Property')
        today = datetime.date.today().strftime('%B %d, %Y')

        items = [
            Spacer(1, 1.8 * inch),
            Paragraph(ent, ParagraphStyle('ct', fontSize=28, textColor=C_HEADER,
                                          fontName='Helvetica-Bold', spaceAfter=6)),
            Spacer(1, 0.2 * inch),
            HRFlowable(width='100%', thickness=2, color=C_HEADER, spaceAfter=0),
            Spacer(1, 0.15 * inch),
            Paragraph('Fiscal Period Financial Report', ParagraphStyle('cs', fontSize=18,
                      textColor=C_SUBHDR, fontName='Helvetica', spaceAfter=4)),
            Paragraph(f'For the Year Ended December 31, {self.year}',
                      ParagraphStyle('cy', fontSize=13, textColor=C_MUTED,
                                     fontName='Helvetica', spaceAfter=20)),
            Spacer(1, 0.3 * inch),
        ]
        meta = [
            ['EIN:', ein],
            ['Business Activity:', prod],
            ['Address:', f'{addr},  {csz}'],
            ['Date Prepared:', today],
            ['Accounting Method:', 'Cash Basis'],
            ['Prepared By:', f'llcRentalTracker v{self.VERSION}'],
        ]
        tbl = Table(meta, colWidths=[1.5 * inch, 4.5 * inch])
        tbl.setStyle(TableStyle([
            ('FONTNAME',  (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTSIZE',  (0,0), (-1,-1), 9),
            ('TEXTCOLOR', (0,0), (0,-1), C_MUTED),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        items += [tbl, Spacer(1, 0.5 * inch),
                  HRFlowable(width='100%', thickness=1, color=C_BORDER)]
        return items

    # ── Section 1: Financial Summary ──────────────────────────────────────────

    def _section1_summary(self) -> list:
        ss   = getSampleStyleSheet()
        st   = self._styles()
        eq   = self._eq
        ent  = self._entity_name()
        ein  = self._profile.get('entity', {}).get('ein', '')
        prod = self._profile.get('entity', {}).get('product', 'Rental Property')
        addr = self._profile.get('entity', {}).get('address', '')
        csz  = self._profile.get('entity', {}).get('city_state_zip', '')
        began = self._profile.get('entity', {}).get('date_business_began', '')
        email = self._profile.get('entity', {}).get('email', 'wbgroupmgr@gmail.com')

        ni     = self._is_agg.get('net_income', 0)
        income = self._is_agg.get('total_income', 0)
        exp    = self._is_agg.get('total_expenses', 0)

        # BS normalizes acct to top-2 nodes (e.g. 'Acct.Cash'); match on 'Cash'.
        cash = round(sum(
            float(r.get('Balance', 0) or 0)
            for r in self._bs_rows
            if 'Cash' in str(r.get('acct', '')) and r.get('acctType') != 'TOTAL'
        ), 2)

        # Member list uses oID only (no personal names)
        owner_lines = '  |  '.join(
            f"Member {i+1} ({o.get('oID','')}) — {_pct(float(o.get('pct', 0) or 0) * 100)}"
            for i, o in enumerate(self._owners)
        )
        active_props = self._props.get('active', [])
        const_props  = self._props.get('construction', [])

        _blt = ParagraphStyle('blt1', parent=ss['Normal'], fontSize=9,
                              leftIndent=14, spaceAfter=2, leading=13)

        ni_word = f"net loss of {_fmt(abs(ni))}" if ni < 0 else f"net income of {_fmt(ni)}"
        depr = abs(sum(r.get('Balance', 0) or 0 for r in self._bs_rows
                       if 'Depreciation.Accum' in r.get('acctMinor', '')))

        items = [
            Paragraph('Section 1 — Financial Summary', st['h1']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),

            Paragraph('<b>Entity Overview</b>', st['h2']),
            Paragraph(
                f'{ent} (EIN {ein}) is a multi-member limited liability company organized '
                f'under Texas law, engaged in {prod.lower()}. The LLC was organized on '
                f'{began}. It is treated as a partnership for federal income tax purposes '
                f'and files Form 1065. Members and ownership percentages: {owner_lines}. '
                f'Contact: {email}.',
                st['body']),

            Paragraph('<b>Active Rental Properties</b>', st['h2']),
        ]
        basis_by_prop = self._prop_inservice_basis()
        if active_props:
            for p in active_props:
                pnm   = p['name']
                addr_part  = f' — {p["addr"]}' if p['addr'] else ''
                basis      = basis_by_prop.get(pnm, 0)
                basis_part = f'  |  Depreciable Basis: {_fmt(basis)}' if basis else ''
                items.append(Paragraph(f'• {pnm}{addr_part}{basis_part}', _blt))
        else:
            items.append(Paragraph('None', st['body']))

        if const_props:
            items.append(Paragraph('<b>Assets Under Development (Not Yet In Service)</b>', st['h2']))
            for p in const_props:
                label = f'{p["name"]} — capitalized basis {_fmt(p["basis"])}'
                items.append(Paragraph(f'• {label}', _blt))
            items.append(Paragraph(
                'No depreciation may be claimed until each asset is placed in service. '
                'Pre-service costs may need reclassification — see Section 6 (CPA Flags).',
                st['note']))

        items += [
            Paragraph('<b>Year in Review</b>', st['h2']),
            Paragraph(
                f'For the year ended December 31, {self.year}, the LLC reported gross rental '
                f'income of {_fmt(income)} and total operating expenses of {_fmt(exp)}, '
                f'resulting in a {ni_word}. Depreciation expense of {_fmt(depr)} '
                f'(MACRS, 27.5-year residential, mid-month convention) is included in '
                f'total expenses and relates solely to active rental properties.',
                st['body']),

            Paragraph('<b>Cash Position</b>', st['h2']),
            Paragraph(
                f'Cash on hand (Acct.Cash.Bank) as of December 31, {self.year}: {_fmt(cash)}. '
                f'See Section 2 (Balance Sheet) for all asset and liability detail.',
                st['body']),

            Paragraph('<b>Member Capital</b>', st['h2']),
            Paragraph(
                f'Each member\'s share of the {ni_word} has been allocated to their '
                f'respective capital accounts per the LLC Operating Agreement. '
                f'See Section 5 (Member Capital Account Analysis) for Item L detail.',
                st['body']),
        ]
        return items

    # ── Section 2: Balance Sheet ──────────────────────────────────────────────

    def _section2_balance_sheet(self) -> list:
        st = self._styles()
        eq = self._eq

        items = [
            Paragraph(f'Section 2 — Balance Sheet', st['h1']),
            Paragraph(f'As of December 31, {self.year}', st['subtitle']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),
        ]

        # Build rows grouped by acctType
        rows = self._bs_section_rows()
        col_w = [3.2*inch, 1.3*inch, 1.3*inch, 1.3*inch]
        hdr   = [['Account', 'Debit', 'Credit', 'Balance']]
        data  = hdr + rows
        ts = self._table_style(len(data))
        tbl = Table(data, colWidths=col_w, repeatRows=1)
        tbl.setStyle(ts)
        items.append(tbl)
        items.append(Spacer(1, 0.15 * inch))

        # Equation note
        ni  = eq.get('net_income', 0)
        lhs = eq.get('assets', 0)
        rhs = lhs - ni
        note_txt = (
            f'<b>Note — Open-Period Accounting:</b> The BS equation gap '
            f'({_fmt(ni)}) equals the period Net {"Loss" if ni < 0 else "Income"}. '
            f'The GL is balanced under A = L + E + NI '
            f'({_fmt(lhs)} = {_fmt(rhs)} + {_fmt(ni)}). '
            f'Revenue/expense accounts remain open for IRS K-1 detail; '
            f'no closing entries are posted.'
        )
        items.append(Paragraph(note_txt, st['note']))

        items += [
            Paragraph('<b>Accounting Notes</b>', st['h2']),
            Paragraph('Note 1 — Accounting Method: Cash basis. Revenue recognised when received; '
                      'expenses deducted when paid.', st['note']),
            Paragraph('Note 2 — Fixed Assets: Carried at historical cost. Building basis includes '
                      'purchase price plus capitalised acquisition costs per IRS Pub. 551.', st['note']),
            Paragraph('Note 3 — Depreciation: MACRS General Depreciation System, 27.5-year '
                      'residential rental, mid-month convention (IRS Pub. 946 Table A-1).', st['note']),
            Paragraph('Note 4 — Land: Not depreciated. Value determined by tax-assessor ratio '
                      'applied to total acquisition cost.', st['note']),
        ]
        return items

    # ── Section 3: Income Statement ───────────────────────────────────────────

    def _section3_income_stmt(self) -> list:
        st = self._styles()

        items = [
            Paragraph('Section 3 — Income Statement (Profit & Loss)', st['h1']),
            Paragraph(f'For Year Ended December 31, {self.year}', st['subtitle']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),
        ]

        col_w = [3.5*inch, 1.2*inch, 1.2*inch, 1.2*inch]
        rows = self._is_section_rows()
        ni   = self._is_agg.get('net_income', 0)   # authoritative from taxAggregates
        hdr  = [['Account', 'Debit', 'Credit', 'Balance']]
        data = hdr + rows
        tbl  = Table(data, colWidths=col_w, repeatRows=1)
        tbl.setStyle(self._is_table_style(data))
        items.append(tbl)
        items.append(Spacer(1, 0.15 * inch))

        # Per-member allocation table
        items.append(Paragraph('<b>Per-Member Net Income/(Loss) Allocation</b>', st['h2']))
        alloc_rows = [['Member', 'Ownership %', 'Amount']]
        for o in self._owners:
            pct = float(o.get('pct', 0) or 0) * 100
            share = round(ni * pct / 100, 2)
            alloc_rows.append([self._owner_name(o), _pct(pct), _fmt(share)])
        alloc_rows.append(['Total', '100%', _fmt(ni)])
        at = Table(alloc_rows, colWidths=[3*inch, 1.5*inch, 1.5*inch])
        at.setStyle(self._alloc_style(len(alloc_rows)))
        items.append(at)
        items.append(Spacer(1, 0.15 * inch))

        items += [
            Paragraph('<b>Income Notes</b>', st['h2']),
            Paragraph('Note 1 — All revenue is rental income per IRC §61. No unrelated '
                      'business income was received.', st['note']),
            Paragraph('Note 2 — Depreciation is an ordinary deduction under IRC §167/168. '
                      'See Section 4 for Form 4562 detail.', st['note']),
            Paragraph('Note 3 — Rental real estate activity is passive under IRC §469. '
                      'Net loss carries forward to offset future passive income. '
                      'Members should track passive activity carryforward on Form 8582.', st['note']),
        ]
        return items

    # ── Section 4: Depreciation ───────────────────────────────────────────────

    def _section4_depreciation(self) -> list:
        st = self._styles()
        items = [
            Paragraph('Section 4 — Depreciation Schedule (Form 4562 Reference)', st['h1']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),
            Paragraph('<b>In-Service Assets (depreciation posted)</b>', st['h2']),
        ]
        rows  = self._depr_rows()
        hdr   = [['Property', 'In Service', 'Type', 'Dep. Basis', 'Method', 'Life', 'Deduction']]
        data  = hdr + rows
        col_w = [1.6*inch, 0.85*inch, 0.85*inch, 0.95*inch, 0.7*inch, 0.5*inch, 0.8*inch]
        tbl   = Table(data, colWidths=col_w, repeatRows=1)
        tbl.setStyle(self._depr_style(len(data)))
        items += [tbl, Spacer(1, 0.1*inch),
                  Paragraph('IRS MACRS mid-month convention (real property): '
                             'year-1 fraction = (25 − 2M) / 24, where M = placement month.',
                             st['note'])]

        # InConstruction sub-table
        const_props = self._props.get('construction', [])
        if const_props:
            items += [
                Spacer(1, 0.15*inch),
                Paragraph('<b>Assets Under Construction — Not Yet In Service (no depreciation)</b>',
                          st['h2']),
            ]
            ic_hdr  = [['propNm', 'Asset Class', 'Capitalized Basis', 'Est. MACRS Life',
                        'Est. Bonus Depr (2025)', 'Status']]
            ic_rows = []
            for p in const_props:
                pnm   = p['name']
                basis = p['basis']
                # Classify: RV / personal property vs. real property
                is_rv = 'RV' in pnm.upper() or 'rv' in pnm.lower()
                cls   = '5-yr personal property' if is_rv else 'TBD — review with CPA'
                life  = '5 years (MACRS)' if is_rv else 'TBD'
                bonus = '60% in year placed in service' if is_rv else 'Depends on asset class'
                ic_rows.append([pnm, cls, _fmt(basis), life, bonus, 'InConstruction'])
            ic_data = ic_hdr + ic_rows
            ic_cw   = [1.0*inch, 1.4*inch, 0.9*inch, 1.0*inch, 1.5*inch, 1.2*inch]
            ic_tbl  = Table(ic_data, colWidths=ic_cw, repeatRows=1)
            ic_tbl.setStyle(self._depr_style(len(ic_data)))
            items += [ic_tbl, Spacer(1, 0.1*inch),
                      Paragraph(
                          'RV held for short-term rental: personal property (5-year MACRS, '
                          '200% DB, half-year convention). 60% first-year bonus depreciation '
                          'available in year placed in service. Pre-service preparation costs '
                          'must be capitalized to basis, not expensed. '
                          'See Section 6 — CPA Flags for required reclassifications.',
                          st['note'])]
        return items

    # ── Section 5: Member Capital ─────────────────────────────────────────────

    def _section5_capital(self) -> list:
        from irs.taxAgents.FormSchK1Agent import gl_contributions, gl_distributions
        st  = self._styles()
        ni  = self._is_agg.get('net_income', 0)   # authoritative IS net income
        items = [
            Spacer(1, 0.1 * inch),
            Paragraph('Section 5 — Member Capital Account Analysis (K-1 Item L)', st['h1']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),
        ]

        members  = self._owners
        col_lbls = [m.get('nm', ['?'])[0] if isinstance(m.get('nm'), list) else str(m.get('nm','?'))
                    for m in members]
        pcts     = [float(m.get('pct', 0) or 0) * 100 for m in members]

        # Use gl_contributions/distributions — same source as Schedule K-1 Box L.
        # gl_contributions scans stmtGL(llc) for Capital.Funds/Reinvestment credits per owner.
        def _row(label, vals):
            tot = sum(vals)
            return [label] + [_fmt(v) for v in vals] + [_fmt(tot)]

        beg_vals  = [0.0] * len(members)
        cont_vals = []
        dist_vals = []
        for m in members:
            oID = m.get('oID', '')
            attributed, _ = gl_contributions(self.llc, oID)
            cont_vals.append(attributed)
            dist_vals.append(gl_distributions(self.llc, oID))  # returns float

        ni_vals  = [round(ni * pcts[i] / 100, 2) for i in range(len(members))]
        end_vals = [beg_vals[i] + cont_vals[i] + ni_vals[i] - dist_vals[i]
                    for i in range(len(members))]

        hdr   = ['Item L'] + col_lbls + ['Total']
        tdata = [hdr,
                 _row('(a) Beginning Capital', beg_vals),
                 _row('(b) Contributions', cont_vals),
                 _row('(c) Net Income/(Loss) Share', ni_vals),
                 _row('(d) Other Increases', [0.0]*len(members)),
                 _row('(e) Withdrawals/Distributions', dist_vals),
                 _row('(f) Ending Capital', end_vals)]

        ncols = len(members) + 2
        cw    = [1.8*inch] + [1.1*inch] * (ncols - 1)
        tbl   = Table(tdata, colWidths=cw, repeatRows=1)
        tbl.setStyle(self._capital_style(len(tdata), len(members)))
        items += [tbl, Spacer(1, 0.1*inch),
                  Paragraph('Ending capital per member must match K-1 Item L(f). '
                             'Provide this schedule to your CPA for K-1 preparation.', st['note'])]
        return items

    # ── Section 6: CPA Flags ──────────────────────────────────────────────────

    def _flag_id(self, cat: str, flag: str) -> str:
        return hashlib.md5(f'{cat}|{flag}'.encode()).hexdigest()[:8]

    def _load_dispositions(self) -> dict:
        from ledger import setup_paths
        fp = Path(str(setup_paths.IRS_FORMS_DIR)) / 'YE_CPA_flags.json'
        try:
            return json.loads(fp.read_text(encoding='utf-8')) if fp.exists() else {}
        except Exception:
            return {}

    def save_disposition(self, flag_id: str, status: str, note: str = '') -> None:
        from ledger import setup_paths
        fp = Path(str(setup_paths.IRS_FORMS_DIR)) / 'YE_CPA_flags.json'
        data = self._load_dispositions()
        data[flag_id] = {
            'status': status,
            'note':   note,
            'date':   datetime.date.today().isoformat(),
        }
        fp.write_text(json.dumps(data, indent=2), encoding='utf-8')

    def _section6_flags(self) -> list:
        st    = self._styles()
        flags = self._build_flags()
        disps = self._load_dispositions()
        items = [
            Paragraph('Section 6 — Outstanding Items & CPA Notes', st['h1']),
            Paragraph('The following items require accountant or IRS attention before Form 1065 is filed.',
                      st['body']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),
        ]

        from reportlab.lib.styles import getSampleStyleSheet as _gss
        _base  = _gss()['Normal']
        _cell  = ParagraphStyle('flagCell',  parent=_base, fontSize=8, leading=11, wordWrap='LTR')
        _cat   = ParagraphStyle('flagCat',   parent=_base, fontSize=8, leading=11,
                                textColor=C_MUTED, wordWrap='LTR')
        _stat  = ParagraphStyle('flagStat',  parent=_base, fontSize=7, leading=10, wordWrap='LTR')
        _hdr_s = ParagraphStyle('flagHdr',   parent=_base, fontSize=8, leading=10,
                                textColor=C_WHITE, fontName='Helvetica-Bold', wordWrap='LTR')

        STATUS_LABEL = {
            'no_action':  'No Action',
            'unresolved': 'Unresolved',
        }
        C_NO_ACTION   = colors.HexColor('#d1fae5')
        C_UNRESOLVED  = colors.HexColor('#fee2e2')

        hdr_row = [Paragraph(t, _hdr_s)
                   for t in ['#', 'Category', 'Flag', 'Action Required', 'CPA Status']]
        rows   = []
        styles = []
        for i, f in enumerate(flags):
            fid    = f.get('id', '')
            disp   = disps.get(fid, {})
            status = disp.get('status', 'pending')
            note   = disp.get('note', '')
            label  = STATUS_LABEL.get(status, 'Pending')
            stat_cell_txt = label + (f'\n{note}' if note else '')
            rows.append([
                Paragraph(str(i + 1), _cell),
                Paragraph(f['cat'],    _cat),
                Paragraph(f['flag'],   _cell),
                Paragraph(f['action'], _cell),
                Paragraph(stat_cell_txt, _stat),
            ])
            row_idx = i + 1  # +1 for header
            if status == 'no_action':
                styles.append(('BACKGROUND', (4, row_idx), (4, row_idx), C_NO_ACTION))
            elif status == 'unresolved':
                styles.append(('BACKGROUND', (4, row_idx), (4, row_idx), C_UNRESOLVED))

        data = [hdr_row] + rows
        cw   = [0.3*inch, 0.9*inch, 2.2*inch, 2.8*inch, 0.9*inch]
        tbl  = Table(data, colWidths=cw, repeatRows=1)
        base_style = [
            ('BACKGROUND',    (0,0), (-1,0),  C_HEADER),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [C_WHITE, C_WARN_BG]),
            ('GRID',          (0,0), (-1,-1), 0.5, C_BORDER),
            ('VALIGN',        (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ]
        tbl.setStyle(TableStyle(base_style + styles))
        items.append(tbl)
        return items

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _load_profile(self, sp) -> dict:
        try:
            fn = Path(str(sp.ACCTS_DIR)) / f'llcProfile_{self.llc.objName}.json'
            return json.loads(fn.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def _load_assets(self, sp) -> list:
        """Load current-year llcAssets records directly (already year-filtered by eSession)."""
        try:
            wk = self.eSession.oDict.get('llcAssets')
            fn = Path(wk.o.FN())
            data = json.loads(fn.read_text(encoding='utf-8'))
            yr = str(self.year)
            return [r for r in data if str(r.get('dt','')).startswith(yr)]
        except Exception:
            return []

    def _entity_name(self) -> str:
        return self._profile.get('entity', {}).get('entity_name', str(self.llc.objName))

    def _owner_name(self, o: dict) -> str:
        nm = o.get('nm', o.get('oID', ''))
        return nm[0] if isinstance(nm, list) and nm else str(nm)

    def _classify_props(self) -> dict:
        """
        Scan ALL GL records to find every propNm and classify it:
          active       — has Acct.Fixed.Tangible.InService entries (placed in service)
          construction — only Acct.Fixed.Tangible.InConstruction (not yet in service)
        Returns {'active': [...], 'construction': [...]}
        each item: {name, addr, basis, expense_total}
        """
        from collections import defaultdict
        prop_accts   = defaultdict(set)
        prop_addr    = {}
        prop_basis   = defaultdict(float)   # InConstruction debit balance
        prop_exp     = defaultdict(float)   # expensed amounts

        for r in self._gl:
            pnm  = r.get('propNm', '') or ''
            if not pnm or pnm in ('Cash_LLC',):
                continue
            acct = r.get('acct', '') or ''
            amt  = float(r.get('amt', 0) or 0)
            atyp = (r.get('aType', '') or '').lower()
            prop_accts[pnm].add(acct)
            if r.get('propAddr') and pnm not in prop_addr:
                prop_addr[pnm] = r.get('propAddr', '')
            if 'InConstruction' in acct:
                prop_basis[pnm] += amt if 'debit' in atyp else -amt
            if 'Exp.' in acct:
                prop_exp[pnm] += amt if 'debit' in atyp else -amt

        active, construction = [], []
        for pnm, accts in sorted(prop_accts.items()):
            entry = {'name': pnm, 'addr': prop_addr.get(pnm, ''),
                     'basis': round(prop_basis.get(pnm, 0), 2),
                     'expense_total': round(prop_exp.get(pnm, 0), 2)}
            if any('InService' in a for a in accts):
                active.append(entry)
            elif any('InConstruction' in a for a in accts):
                construction.append(entry)
        return {'active': active, 'construction': construction}

    def _bs_section_rows(self) -> list:
        rows = []
        cur_type = ''
        for r in self._bs_rows:
            at = r.get('acctType', '')
            if at == 'TOTAL':
                continue
            if at != cur_type:
                rows.append([f'── {at} ──', '', '', ''])
                cur_type = at
            acct  = r.get('acct', '') or ''
            minor = r.get('acctMinor', '') or ''
            full_code = f'{acct}.{minor}'.rstrip('.') if minor else acct
            d = r.get('Debit', 0) or 0
            c = r.get('Credit', 0) or 0
            b = r.get('Balance', 0) or 0
            rows.append([f'  {full_code}',
                         _fmt(d) if d else '',
                         _fmt(c) if c else '',
                         _fmt(b, parens=True)])
        # totals
        td = sum(r.get('Debit',0) or 0 for r in self._bs_rows if r.get('acctType') != 'TOTAL')
        tc = sum(r.get('Credit',0) or 0 for r in self._bs_rows if r.get('acctType') != 'TOTAL')
        tb = round(td - tc, 2)
        rows.append(['TOTAL', _fmt(td), _fmt(tc), _fmt(tb, parens=True)])
        return rows

    def _is_section_rows(self) -> list:
        # Aggregate per-property rows into one row per account, matching the app IS View.
        # Income is credit-normal (Balance = Debit-Credit is negative); flip for display.

        data_rows  = [r for r in self._is_rows if r.get('acctType') != 'TOTAL']
        total_idx  = {r.get('row_type', ''): r for r in self._is_rows if r.get('acctType') == 'TOTAL'}

        def _tb(rt):
            return float(total_idx.get(rt, {}).get('Balance', 0) or 0)

        # Aggregate by (acctType, acct), preserving first-seen order.
        agg = {}
        for r in data_rows:
            at   = r.get('acctType', '')
            acct = r.get('acct', '') or r.get('acctMinor', '')
            key  = (at, acct)
            if key not in agg:
                agg[key] = {'acctType': at, 'acct': acct,
                            'Debit': 0.0, 'Credit': 0.0, 'Balance': 0.0}
            agg[key]['Debit']   += float(r.get('Debit', 0) or 0)
            agg[key]['Credit']  += float(r.get('Credit', 0) or 0)
            agg[key]['Balance'] += float(r.get('Balance', 0) or 0)

        income_rows  = [(k, v) for k, v in agg.items() if v['acctType'] == 'Income']
        expense_rows = [(k, v) for k, v in agg.items() if v['acctType'] == 'Expense']

        def _dr(at, acct, d, c, b):
            display_b = -b if at == 'Income' else b
            return [f'  {acct}',
                    _fmt(d) if d else '',
                    _fmt(c) if c else '',
                    _fmt(display_b, parens=True)]

        rows = []

        if income_rows:
            rows.append(['── Income ──', '', '', ''])
            for (at, acct), data in income_rows:
                rows.append(_dr(at, acct, data['Debit'], data['Credit'], data['Balance']))
            ri = _tb('rental-income-subtotal')
            oi = _tb('ordinary-income-subtotal')
            if abs(ri) > 0.01:
                rows.append(['  SubTotal Rental Income', '', '', _fmt(ri, parens=True)])
            if abs(oi) > 0.01:
                rows.append(['  SubTotal Ordinary Income', '', '', _fmt(oi, parens=True)])

        if expense_rows:
            rows.append(['── Expense ──', '', '', ''])
            for (at, acct), data in expense_rows:
                rows.append(_dr(at, acct, data['Debit'], data['Credit'], data['Balance']))
            re = _tb('rental-expense-subtotal')
            oe = _tb('ordinary-expense-subtotal')
            if abs(re) > 0.01:
                rows.append(['  SubTotal Rental Expense', '', '', _fmt(re, parens=True)])
            if abs(oe) > 0.01:
                rows.append(['  SubTotal Ordinary Expense', '', '', _fmt(oe, parens=True)])

        ni = _tb('total-net')
        rows.append(['NET INCOME / (LOSS)', '', '', _fmt(ni, parens=True)])
        return rows

    def _prop_inservice_basis(self) -> dict:
        """Sum all InService debit entries per propNm across ALL years (not year-filtered)."""
        try:
            wk = self.eSession.oDict.get('llcAssets')
            fn = Path(wk.o.FN())
            all_data = json.loads(fn.read_text(encoding='utf-8'))
        except Exception:
            return {}
        basis = defaultdict(float)
        for r in all_data:
            if 'Tangible.InService' not in (r.get('acct', '') or ''):
                continue
            pnm = r.get('propNm', '') or ''
            if not pnm:
                continue
            basis[pnm] += float(r.get('amt', 0) or 0)
        return {k: round(v, 2) for k, v in basis.items()}

    def _depr_rows(self) -> list:
        basis_by_prop = self._prop_inservice_basis()
        rows = []
        for r in self._assets:
            if not r.get('_is_depr'):
                continue
            pnm   = r.get('propNm', '')
            dt    = r.get('dt', '')
            atyp  = r.get('assetType', 'Residential')
            amt   = float(r.get('amt', 0) or 0)
            life  = 39.0 if atyp == 'Commercial' else 27.5
            basis = basis_by_prop.get(pnm, 0)
            basis_str = _fmt(basis) if basis else '—'
            rows.append([pnm, dt, atyp, basis_str, 'MACRS', f'{life}yr', _fmt(amt)])
        if not rows:
            rows = [['No depreciation posted', '', '', '', '', '', '']]
        return rows

    def _build_flags(self) -> list:
        def _f(cat, flag, action):
            return {'id': self._flag_id(cat, flag), 'cat': cat, 'flag': flag, 'action': action}

        flags = [
            _f('Accounting', 'Form 1065 Line F — accounting method not recorded in profile',
               'Confirm Cash or Accrual with CPA; update llcProfile F1065 field.'),
            _f('Liabilities', 'No mortgage payable recorded in llcPayables',
               'If property was financed, add mortgage principal balance as of 12/31. If cash purchase, document.'),
            _f('Liabilities', 'No security deposit liability recorded',
               'If deposits are held, add to llcPayables as Acct.Liab.Customer.Security.'),
            _f('Tax', 'Passive activity loss (IRC §469) — net loss carries forward',
               'Members must track carryforward on Form 8582. Loss deductible when property sold or passive income earned.'),
            _f('Tax', "At-risk rules (IRC §465) — verify each member's at-risk amount",
               'Loss deductible only to extent member is at-risk. CPA must calculate outside basis.'),
            _f('Property', 'County tax proration ($1,661) classified as InService basis reduction',
               'CPA should verify: is this a current-year expense credit or a basis adjustment?'),
            _f('K-1', 'K-1s must be delivered to members by March 15 (or extension date)',
               'Generate Schedule K-1 PDFs from IS PerMember view and deliver to each member.'),
            _f('Docs', 'Operating Agreement profit/loss allocation: 96% / 2% / 2%',
               'Confirm this matches the signed Operating Agreement on file. Any discrepancy voids K-1 allocation.'),
        ]
        # Dynamic: check if depreciation is posted for InService assets
        has_depr = any(r.get('_is_depr') for r in self._assets)
        if not has_depr and self._props.get('active'):
            flags.insert(0, _f(
                'Depreciation',
                'No depreciation entry found for in-service assets',
                'Run YE Posting from llcAssets view to post MACRS depreciation before filing.',
            ))

        # Dynamic: RV / InConstruction flags
        for p in self._props.get('construction', []):
            pnm   = p['name']
            basis = p['basis']
            exp   = p['expense_total']
            is_rv = 'RV' in pnm.upper()
            asset_label = f'RV ({pnm})' if is_rv else f'Asset {pnm}'

            flags.append(_f('Asset',
                f'{asset_label}: InConstruction — not yet placed in service as of 12/31/{self.year}',
                'Document the date the asset first becomes available for rental. '
                'No depreciation until in-service date. Report in-service date on Form 4562.'))
            if exp > 0:
                flags.append(_f('Capitalization',
                    f'{asset_label}: {_fmt(exp)} expensed as repairs/other but asset is pre-service',
                    f'CPA should reclassify {_fmt(exp)} from Acct.Exp.* to '
                    f'Acct.Fixed.Tangible.InConstruction (increasing basis to '
                    f'{_fmt(basis + exp)}). Pre-service costs must be capitalized '
                    f'per IRS Reg. §1.263(a)-1.'))
            if is_rv:
                flags.append(_f('Tax — RV',
                    'RV rental activity type unknown — passive vs. active determines loss deductibility',
                    'Determine average rental period. ≤7 days avg → NOT passive (IRC §469(j)(8)); '
                    'losses deductible against ordinary income immediately. >7 days → passive rules apply.'))
                flags.append(_f('Tax — RV', 'RV listed property check (IRC §280F)',
                    'Confirm GVWR. If >6,000 lbs → not subject to luxury-auto annual caps. '
                    'Business-use log required regardless.'))
                flags.append(_f('Tax — RV',
                    '60% bonus depreciation election available in year RV is placed in service',
                    'Decide with CPA whether to take 60% first-year bonus (2025 TCJA rate for '
                    '5-year personal property). Reduces basis for subsequent years.'))
        return flags

    # ── Table styles ──────────────────────────────────────────────────────────

    def _table_style(self, n_rows: int) -> TableStyle:
        cmds = [
            ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('BACKGROUND', (0,0), (-1,0),  C_HEADER),
            ('TEXTCOLOR',  (0,0), (-1,0),  C_WHITE),
            ('ALIGN',      (1,0), (-1,-1), 'RIGHT'),
            ('GRID',       (0,0), (-1,-1), 0.5, C_BORDER),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 4),
        ]
        # alternating rows
        for i in range(1, n_rows):
            if i % 2 == 0:
                cmds.append(('BACKGROUND', (0,i), (-1,i), C_ROW_ALT))
        # last row = total
        cmds += [
            ('FONTNAME',   (0, n_rows-1), (-1, n_rows-1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, n_rows-1), (-1, n_rows-1), colors.HexColor('#dbeafe')),
            ('LINEABOVE',  (0, n_rows-1), (-1, n_rows-1), 1.0, C_SUBHDR),
        ]
        return TableStyle(cmds)

    def _is_table_style(self, data: list) -> TableStyle:
        """IS table: base style + bold/highlight subtotal and net rows."""
        cmds = [
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 8),
            ('BACKGROUND',    (0,0), (-1,0),  C_HEADER),
            ('TEXTCOLOR',     (0,0), (-1,0),  C_WHITE),
            ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
            ('GRID',          (0,0), (-1,-1), 0.5, C_BORDER),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 4),
        ]
        for i in range(1, len(data)):
            if i % 2 == 0:
                cmds.append(('BACKGROUND', (0,i), (-1,i), C_ROW_ALT))
        for i, row in enumerate(data[1:], 1):
            label = str(row[0]) if row else ''
            if 'SubTotal' in label:
                cmds += [
                    ('FONTNAME',   (0,i), (-1,i), 'Helvetica-Bold'),
                    ('BACKGROUND', (0,i), (-1,i), colors.HexColor('#e0e7ff')),
                    ('LINEABOVE',  (0,i), (-1,i), 0.5, C_SUBHDR),
                ]
            elif 'NET INCOME' in label or 'NET LOSS' in label:
                cmds += [
                    ('FONTNAME',   (0,i), (-1,i), 'Helvetica-Bold'),
                    ('BACKGROUND', (0,i), (-1,i), colors.HexColor('#dbeafe')),
                    ('LINEABOVE',  (0,i), (-1,i), 1.0, C_SUBHDR),
                ]
        return TableStyle(cmds)

    def _alloc_style(self, n_rows: int) -> TableStyle:
        cmds = [
            ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('BACKGROUND', (0,0), (-1,0),  C_SUBHDR),
            ('TEXTCOLOR',  (0,0), (-1,0),  C_WHITE),
            ('ALIGN',      (1,0), (-1,-1), 'RIGHT'),
            ('GRID',       (0,0), (-1,-1), 0.5, C_BORDER),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('FONTNAME',   (0, n_rows-1), (-1, n_rows-1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, n_rows-1), (-1, n_rows-1), colors.HexColor('#dbeafe')),
        ]
        return TableStyle(cmds)

    def _depr_style(self, n_rows: int) -> TableStyle:
        return TableStyle([
            ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('BACKGROUND', (0,0), (-1,0),  C_HEADER),
            ('TEXTCOLOR',  (0,0), (-1,0),  C_WHITE),
            ('ALIGN',      (3,1), (-1,-1), 'RIGHT'),
            ('GRID',       (0,0), (-1,-1), 0.5, C_BORDER),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [C_WHITE, C_ROW_ALT]),
        ])

    def _capital_style(self, n_rows: int, n_members: int) -> TableStyle:
        cmds = [
            ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('BACKGROUND', (0,0), (-1,0),  C_HEADER),
            ('TEXTCOLOR',  (0,0), (-1,0),  C_WHITE),
            ('ALIGN',      (1,0), (-1,-1), 'RIGHT'),
            ('GRID',       (0,0), (-1,-1), 0.5, C_BORDER),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [C_WHITE, C_ROW_ALT]),
            # ending capital row bold
            ('FONTNAME',   (0, n_rows-1), (-1, n_rows-1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, n_rows-1), (-1, n_rows-1), colors.HexColor('#dbeafe')),
            ('LINEABOVE',  (0, n_rows-1), (-1, n_rows-1), 1.0, C_SUBHDR),
        ]
        return TableStyle(cmds)
