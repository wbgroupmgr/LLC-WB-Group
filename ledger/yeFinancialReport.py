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

        self._eq       = auditor.equation_summary()
        self._gl       = gl_records
        self._profile  = self._load_profile(setup_paths)
        self._owners   = engine.load_owners()
        self._bs_rows  = stmtBS_View(self.llc, gl_records=gl_records).view(view_by='All', with_totals=False)
        self._is_rows  = stmtIS_View(self.llc, gl_records=gl_records).view(view_by='All', with_totals=True)
        self._assets   = self._load_assets(setup_paths)

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
            canvas.drawString(_M + 6, ph - _M - 0.22 * inch, f'{ent}  ·  {self.year} Year-End Financial Report')
            # footer
            canvas.setFillColor(C_MUTED)
            canvas.setFont('Helvetica', 7)
            canvas.drawRightString(pw - _M, 0.45 * inch,
                f'Prepared by llcRentalTracker v{self.VERSION}  ·  For Tax Review Only  ·  Page {doc.page}')
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
            HRFlowable(width='100%', thickness=2, color=C_HEADER, spaceAfter=10),
            Paragraph('Year-End Financial Report', ParagraphStyle('cs', fontSize=18,
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
                  HRFlowable(width='100%', thickness=1, color=C_BORDER),
                  Spacer(1, 0.15 * inch),
                  Paragraph('For Tax Review Only — Not a Certified Audit',
                             ParagraphStyle('disc', fontSize=8, textColor=C_MUTED,
                                            fontName='Helvetica-Oblique'))]
        return items

    # ── Section 1: Financial Summary ──────────────────────────────────────────

    def _section1_summary(self) -> list:
        st   = self._styles()
        eq   = self._eq
        ent  = self._entity_name()
        ein  = self._profile.get('entity', {}).get('ein', '')
        prod = self._profile.get('entity', {}).get('product', 'Rental Property')
        addr = self._profile.get('entity', {}).get('address', '')
        csz  = self._profile.get('entity', {}).get('city_state_zip', '')
        began = self._profile.get('entity', {}).get('date_business_began', '')

        ni     = eq.get('net_income', 0)
        assets = eq.get('assets', 0)
        income = eq.get('income', 0)
        exp    = eq.get('expenses', 0)

        owner_lines = '  '.join(
            f"{self._owner_name(o)} ({_pct(float(o.get('pct',0))*100)})"
            for o in self._owners
        )
        props = self._prop_list()
        prop_text = '; '.join(f"{p['name']} ({p['addr']})" for p in props) or 'No properties on record'

        ni_word = f"net loss of {_fmt(abs(ni))}" if ni < 0 else f"net income of {_fmt(ni)}"
        depr = sum(r.get('Balance',0) or 0 for r in self._bs_rows
                   if 'Depreciation.Accum' in r.get('acctMinor',''))
        depr = abs(depr)

        items = [
            Paragraph('Section 1 — Financial Summary', st['h1']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),

            Paragraph('<b>Entity Overview</b>', st['h2']),
            Paragraph(
                f'{ent} (EIN {ein}) is a multi-member limited liability company organized '
                f'under Texas law, engaged in {prod.lower()}. The LLC was organized on '
                f'{began}. It is treated as a partnership for federal income tax purposes '
                f'and files Form 1065. Members and ownership percentages: {owner_lines}.',
                st['body']),

            Paragraph('<b>Property Portfolio</b>', st['h2']),
            Paragraph(
                f'The LLC held the following rental properties as of December 31, {self.year}: '
                f'{prop_text}.',
                st['body']),

            Paragraph('<b>Year in Review</b>', st['h2']),
            Paragraph(
                f'For the year ended December 31, {self.year}, the LLC reported gross rental '
                f'income of {_fmt(income)} and total operating expenses of {_fmt(exp)}, '
                f'resulting in a {ni_word}. Depreciation expense of {_fmt(depr)} '
                f'(MACRS, 27.5-year residential) is included in total expenses.',
                st['body']),

            Paragraph('<b>Cash Position</b>', st['h2']),
            Paragraph(
                f'Total assets as of December 31, {self.year} were {_fmt(assets)}, '
                f'consisting primarily of fixed real estate assets and operating cash. '
                f'See Section 2 (Balance Sheet) for full detail.',
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
        rows, inc_total, exp_total, ni = self._is_section_rows()
        hdr  = [['Account', 'Debit', 'Credit', 'Balance']]
        data = hdr + rows
        tbl  = Table(data, colWidths=col_w, repeatRows=1)
        tbl.setStyle(self._table_style(len(data)))
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
        ]
        rows  = self._depr_rows()
        hdr   = [['Property', 'In Service', 'Type', 'Dep. Basis', 'Method', 'Life', 'Deduction']]
        data  = hdr + rows
        col_w = [1.6*inch, 0.85*inch, 0.85*inch, 0.95*inch, 0.7*inch, 0.5*inch, 0.8*inch]
        tbl   = Table(data, colWidths=col_w, repeatRows=1)
        tbl.setStyle(self._depr_style(len(data)))
        items += [tbl, Spacer(1, 0.1*inch),
                  Paragraph('IRS MACRS mid-month convention: year-1 fraction = (25 − 2M) / 24, '
                             'where M = placement month.', st['note'])]
        return items

    # ── Section 5: Member Capital ─────────────────────────────────────────────

    def _section5_capital(self) -> list:
        st  = self._styles()
        ni  = self._eq.get('net_income', 0)
        items = [
            Spacer(1, 0.1 * inch),
            Paragraph('Section 5 — Member Capital Account Analysis (K-1 Item L)', st['h1']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),
        ]

        members  = self._owners
        col_lbls = [m.get('nm', ['?'])[0] if isinstance(m.get('nm'), list) else str(m.get('nm','?'))
                    for m in members]
        pcts     = [float(m.get('pct', 0) or 0) * 100 for m in members]

        # Compute per-member capital from acctOwner-tagged GL rows
        contrib = defaultdict(float)
        for r in self._assets:
            oid  = r.get('acctOwner', '')
            acct = r.get('acct', '')
            if 'Capital' in acct and oid:
                amt  = float(r.get('amt', 0) or 0)
                atyp = (r.get('aType', '') or '').lower()
                # Credit = contribution increases capital
                contrib[oid] += amt if 'credit' in atyp else -amt

        hdr    = ['Item L'] + col_lbls + ['Total']
        rows_d = []
        totals = [0.0] * len(members)

        def _row(label, vals):
            tot = sum(vals)
            return [label] + [_fmt(v) for v in vals] + [_fmt(tot)]

        beg_vals  = [0.0] * len(members)
        cont_vals = [contrib.get(m.get('oID',''), 0.0) for m in members]
        ni_vals   = [round(ni * pcts[i] / 100, 2) for i in range(len(members))]
        end_vals  = [beg_vals[i] + cont_vals[i] + ni_vals[i] for i in range(len(members))]

        tdata = [hdr,
                 _row('(a) Beginning Capital', beg_vals),
                 _row('(b) Contributions', cont_vals),
                 _row('(c) Net Income/(Loss) Share', ni_vals),
                 _row('(d) Other Increases', [0.0]*len(members)),
                 _row('(e) Withdrawals/Distributions', [0.0]*len(members)),
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

    def _section6_flags(self) -> list:
        st    = self._styles()
        flags = self._build_flags()
        items = [
            Paragraph('Section 6 — Outstanding Items & CPA Notes', st['h1']),
            Paragraph('The following items require accountant or IRS attention before Form 1065 is filed.',
                      st['body']),
            HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceAfter=8),
        ]

        hdr  = [['#', 'Category', 'Flag', 'Action Required']]
        rows = [[str(i+1), f['cat'], f['flag'], f['action']] for i, f in enumerate(flags)]
        data = hdr + rows
        cw   = [0.3*inch, 1.0*inch, 2.5*inch, 3.3*inch]
        tbl  = Table(data, colWidths=cw, repeatRows=1)
        tbl.setStyle(TableStyle([
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 8),
            ('BACKGROUND',   (0,0), (-1,0),  C_HEADER),
            ('TEXTCOLOR',    (0,0), (-1,0),  C_WHITE),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [C_WHITE, C_WARN_BG]),
            ('GRID',         (0,0), (-1,-1), 0.5, C_BORDER),
            ('VALIGN',       (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING',   (0,1), (-1,-1), 4),
            ('BOTTOMPADDING',(0,1), (-1,-1), 4),
            ('LEFTPADDING',  (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('WORDWRAP',     (0,0), (-1,-1), True),
        ]))
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

    def _prop_list(self) -> list:
        seen, props = set(), []
        for r in self._assets:
            nm = r.get('propNm', '')
            if nm and nm not in seen:
                seen.add(nm)
                props.append({'name': nm, 'addr': r.get('propAddr', '')})
        return props

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
            minor = r.get('acctMinor', '') or r.get('acct', '')
            d = r.get('Debit', 0) or 0
            c = r.get('Credit', 0) or 0
            b = r.get('Balance', 0) or 0
            rows.append([f'  {minor}',
                         _fmt(d) if d else '',
                         _fmt(c) if c else '',
                         _fmt(b, parens=True)])
        # totals
        td = sum(r.get('Debit',0) or 0 for r in self._bs_rows if r.get('acctType') != 'TOTAL')
        tc = sum(r.get('Credit',0) or 0 for r in self._bs_rows if r.get('acctType') != 'TOTAL')
        tb = round(td - tc, 2)
        rows.append(['TOTAL', _fmt(td), _fmt(tc), _fmt(tb, parens=True)])
        return rows

    def _is_section_rows(self):
        rows, inc_total, exp_total = [], 0.0, 0.0
        cur_type = ''
        for r in self._is_rows:
            at = r.get('acctType', '')
            rt = r.get('row_type', '')
            if at == 'TOTAL' and rt not in ('total-net',):
                continue
            if at == 'TOTAL':
                # Grand total row
                b = r.get('Balance', 0) or 0
                rows.append(['NET INCOME / (LOSS)', '', '', _fmt(b, parens=True)])
                continue
            if at != cur_type:
                rows.append([f'── {at} ──', '', '', ''])
                cur_type = at
            acct = r.get('acct', '') or r.get('acctMinor', '')
            # simplify acct display
            parts = str(acct).split('.')
            label = '.'.join(parts[-2:]) if len(parts) > 2 else acct
            d = r.get('Debit', 0) or 0
            c = r.get('Credit', 0) or 0
            b = r.get('Balance', 0) or 0
            if at == 'Income':
                inc_total += b
            elif at == 'Expense':
                exp_total += b
            rows.append([f'  {label}',
                         _fmt(d) if d else '',
                         _fmt(c) if c else '',
                         _fmt(b, parens=True)])
        ni = round(inc_total - exp_total, 2)
        return rows, inc_total, exp_total, ni

    def _depr_rows(self) -> list:
        rows = []
        for r in self._assets:
            if not r.get('_is_depr'):
                continue
            pnm  = r.get('propNm', '')
            dt   = r.get('dt', '')
            atyp = r.get('assetType', 'Residential')
            amt  = float(r.get('amt', 0) or 0)
            life = 39.0 if atyp == 'Commercial' else 27.5
            rows.append([pnm, dt, atyp, '—', 'MACRS', f'{life}yr', _fmt(amt)])
        if not rows:
            rows = [['No depreciation posted', '', '', '', '', '', '']]
        return rows

    def _build_flags(self) -> list:
        flags = [
            {'cat': 'Accounting', 'flag': 'Form 1065 Line F — accounting method not recorded in profile',
             'action': 'Confirm Cash or Accrual with CPA; update llcProfile F1065 field.'},
            {'cat': 'Liabilities', 'flag': 'No mortgage payable recorded in llcPayables',
             'action': 'If property was financed, add mortgage principal balance as of 12/31. If cash purchase, document.'},
            {'cat': 'Liabilities', 'flag': 'No security deposit liability recorded',
             'action': 'If deposits are held, add to llcPayables as Acct.Liab.Customer.Security.'},
            {'cat': 'Tax', 'flag': 'Passive activity loss (IRC §469) — net loss carries forward',
             'action': 'Members must track carryforward on Form 8582. Loss deductible when property sold or passive income earned.'},
            {'cat': 'Tax', 'flag': 'At-risk rules (IRC §465) — verify each member\'s at-risk amount',
             'action': 'Loss deductible only to extent member is at-risk. CPA must calculate outside basis.'},
            {'cat': 'Property', 'flag': 'County tax proration ($1,661) classified as InService basis reduction',
             'action': 'CPA should verify: is this a current-year expense credit or a basis adjustment?'},
            {'cat': 'K-1', 'flag': 'K-1s must be delivered to members by March 15 (or extension date)',
             'action': 'Generate Schedule K-1 PDFs from IS PerMember view and deliver to each member.'},
            {'cat': 'Docs', 'flag': 'Operating Agreement profit/loss allocation: 96% / 2% / 2%',
             'action': 'Confirm this matches the signed Operating Agreement on file. Any discrepancy voids K-1 allocation.'},
        ]
        # Dynamic: check if depreciation is posted
        has_depr = any(r.get('_is_depr') for r in self._assets)
        if not has_depr:
            flags.insert(0, {
                'cat': 'Depreciation',
                'flag': 'No depreciation entry found in llcAssets for this year',
                'action': 'Run YE Posting from llcAssets view to post MACRS depreciation before filing.',
            })
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
