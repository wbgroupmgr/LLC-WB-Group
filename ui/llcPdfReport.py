"""
PDF report generator for NewPropertyAgent closing summary.
Uses reportlab to produce a landscape purchase summary including
preface metadata, original settlement lines, property basis,
depreciation estimate, journal entries, and accounting guide.
"""
import os
import re
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)


# ── page geometry (landscape letter) ────────────────────────────────────────
PAGE_SIZE   = landscape(letter)   # 11 × 8.5 in
H_MARGIN    = 0.55 * inch
V_MARGIN    = 0.55 * inch
USABLE_W    = PAGE_SIZE[0] - 2 * H_MARGIN   # ≈ 9.9 in

# ── colour palette (matches UI) ──────────────────────────────────────────────
_BLUE_DARK  = colors.HexColor('#1d4ed8')
_BLUE_MED   = colors.HexColor('#1e40af')
_BLUE_LIGHT = colors.HexColor('#dbeafe')
_GREEN_DARK = colors.HexColor('#166534')
_GREEN_FILL = colors.HexColor('#f0fdf4')
_AMBER_FILL = colors.HexColor('#fef3c7')
_GRAY_LIGHT = colors.HexColor('#f8fafc')
_GRAY_MED   = colors.HexColor('#e2e8f0')
_GRAY_DARK  = colors.HexColor('#64748b')
_SLATE      = colors.HexColor('#1e293b')
_TEAL       = colors.HexColor('#0369a1')
_INFO_BG    = colors.HexColor('#e0f2fe')
_INFO_FG    = colors.HexColor('#0c4a6e')

_STYLES = getSampleStyleSheet()

def _style(name, **kwargs):
    key = name + '_' + '_'.join(f'{k}{v}' for k, v in kwargs.items())
    if key in _STYLES:
        return _STYLES[key]
    s = ParagraphStyle(key, parent=_STYLES[name], **kwargs)
    _STYLES.add(s)
    return s

_H1    = _style('Heading1', fontSize=16, textColor=_BLUE_DARK, spaceAfter=2)
_H2    = _style('Heading2', fontSize=11, textColor=_BLUE_MED,  spaceBefore=10, spaceAfter=4)
_BODY  = _style('Normal',   fontSize=9,  textColor=_SLATE,     leading=13)
_SMALL = _style('Normal',   fontSize=8,  textColor=_GRAY_DARK, leading=11,     spaceAfter=0)
_INFO  = _style('Normal',   fontSize=8,  textColor=_INFO_FG,   leading=12)


def _fmt(v):
    try:
        return f'{float(v):,.2f}'
    except Exception:
        return str(v or '')


def _safe(v, maxlen=None):
    s = str(v or '').replace('<', '&lt;').replace('>', '&gt;')
    if maxlen and len(s) > maxlen:
        s = s[:maxlen - 1] + '…'
    return s


def _clean_filename(s):
    return re.sub(r'[^\w\-. ]', '_', str(s)).strip()


def _output_path(preface: dict, output_dir: str) -> str:
    raw_date = (preface.get('closingDate') or '').replace('/', '-').replace('.', '-')
    parts    = raw_date.split('-')
    if len(parts) == 3:
        date_part = f'{parts[0]}.{parts[1].zfill(2)}.{parts[2].zfill(2)}'
    else:
        date_part = raw_date or datetime.today().strftime('%Y.%m.%d')
    prop_nm  = _clean_filename(preface.get('propNm') or 'Property').replace(' ', '_')
    return os.path.join(output_dir, f'{date_part}_PurchaseNewProp_{prop_nm}.pdf')


def resolve_output_dir(preface: dict, top_dir: str | None = None) -> str | None:
    """
    Derive the output directory from preface.closingDoc / refDoc (preferred) or refDB.
    refDoc format: '<label>, <category>, <type>, <relative/path/to/file.pdf>'
    The last comma-separated segment is treated as a path relative to top_dir.
    """
    if top_dir is None:
        try:
            from ledger import setup_paths
            top_dir = str(setup_paths.TOP) if setup_paths.TOP else None
        except Exception:
            pass

    ref_doc = (preface.get('closingDoc') or preface.get('refDoc') or '').strip()
    if ref_doc and ',' in ref_doc:
        path_part = ref_doc.split(',')[-1].strip()
        if path_part and ('/' in path_part or '\\' in path_part):
            rel_dir = os.path.dirname(path_part)
            if top_dir and rel_dir:
                return os.path.join(top_dir, rel_dir)
            if os.path.isabs(path_part):
                return os.path.dirname(path_part)

    ref_db = (preface.get('refDB') or '').strip()
    if ref_db and ('/' in ref_db or '\\' in ref_db):
        if os.path.isabs(ref_db):
            return os.path.dirname(ref_db) if '.' in os.path.basename(ref_db) else ref_db
        if top_dir:
            candidate = os.path.dirname(ref_db) if '.' in os.path.basename(ref_db) else ref_db
            return os.path.join(top_dir, candidate)

    return None


# ── shared table style helpers ────────────────────────────────────────────────

def _base_style(header_bg=None):
    return [
        ('BACKGROUND',   (0, 0), (-1, 0),  header_bg or _BLUE_DARK),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, -1), 8),
        ('BOX',          (0, 0), (-1, -1), 0.5, _GRAY_MED),
        ('INNERGRID',    (0, 0), (-1, -1), 0.25, _GRAY_MED),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _GRAY_LIGHT]),
    ]


def _section_title(text):
    return [
        Paragraph(text, _H2),
        HRFlowable(width='100%', thickness=0.5, color=_GRAY_MED, spaceAfter=4),
    ]


# ── section builders ──────────────────────────────────────────────────────────

def _preface_table(preface: dict):
    p = preface
    pairs = [
        ('Property',     p.get('propNm')     or '—'),
        ('Address',      p.get('propAddr')   or '—'),
        ('Closing Date', (p.get('closingDate') or '').replace('-', '.')),
        ('tID Prefix',   p.get('tID_Prefix') or '—'),
        ('Asset Type',   p.get('assetType')  or '—'),
        ('Asset State',  p.get('assetState') or '—'),
        ('acctSub',      p.get('acctSub')    or 'Closing'),
        ('Owners',       p.get('propOwners') or '—'),
        ('Closing Doc',  p.get('closingDoc') or '—'),
        ('refDB',        p.get('refDB')      or 'propAgent'),
    ]
    # 4-col layout: label | value | label | value
    col_w = [0.85, 2.55, 0.85, 2.55]
    rows  = []
    for i in range(0, len(pairs), 2):
        row = []
        for lbl, val in pairs[i:i+2]:
            row.append(Paragraph(f'<font color="#6b7280" size="7">{lbl}</font>', _BODY))
            row.append(Paragraph(f'<b>{_safe(val)}</b>', _BODY))
        if len(row) == 2:
            row += ['', '']
        rows.append(row)

    t = Table(rows, colWidths=[w * inch for w in col_w])
    t.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, -1), _GRAY_LIGHT),
        ('BOX',          (0, 0), (-1, -1), 0.5, _GRAY_MED),
        ('INNERGRID',    (0, 0), (-1, -1), 0.25, _GRAY_MED),
        ('LEFTPADDING',  (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


def _settlement_table(classified: list):
    """Original closing settlement rows as classified in Step 2."""
    # Columns: #  Description  Dr/Cr  Amount  GL Account  Tax Treatment  Rule
    col_w = [0.3, 3.4, 0.5, 0.8, 1.9, 1.2, 1.8]   # sum = 9.9 in
    headers = ['#', 'Description', 'Dr/Cr', 'Amount', 'GL Account', 'Tax Treatment', 'Rule']
    rows = [headers]
    row_styles = []

    for i, r in enumerate(classified):
        desc   = _safe(r.get('Description') or r.get('desc') or '', 80)
        atype  = r.get('aType') or ''
        amt    = f"${_fmt(r.get('amt') or r.get('Buyer') or r.get('Seller') or 0)}"
        acct   = _safe(r.get('acct') or '')
        bucket = r.get('tax_bucket') or ''
        rule   = _safe(r.get('_rule') or r.get('rule') or '—', 40)
        rows.append([str(i + 1), desc, atype, amt, acct, bucket, rule])
        if str(acct).startswith('Acct.Fixed'):
            row_styles.append((_GREEN_FILL, len(rows) - 1))

    style = _base_style()
    style.append(('ALIGN', (3, 0), (3, -1), 'RIGHT'))
    for bg, ridx in row_styles:
        style.append(('BACKGROUND', (0, ridx), (-1, ridx), bg))

    t = Table(rows, colWidths=[w * inch for w in col_w])
    t.setStyle(TableStyle(style))
    return t


def _basis_table(basis_data: dict, preface: dict):
    land_pct = float(preface.get('landPct') or 0)
    bldg_pct = round(100.0 - land_pct, 2)
    col_w = [7.2, 1.5]   # sum = 8.7, leaves room in landscape

    rows = [
        [Paragraph('<b>Basis Component</b>', _BODY), Paragraph('<b>Amount</b>', _BODY)],
        ['Gross Capitalized Acquisition Cost',
         Paragraph(f'<b>${_fmt(basis_data.get("gross_basis", 0))}</b>', _BODY)],
    ]
    if land_pct:
        rows.append([f'  → Land ({land_pct}%)  —  Acct.Fixed.Land',
                     f'${_fmt(basis_data.get("land_amt", 0))}'])
        rows.append([f'  → Building ({bldg_pct}%)  —  Acct.Fixed.Tangible.InService',
                     f'${_fmt(basis_data.get("bldg_amt", 0))}'])

    fy  = basis_data.get('depr_full_year')
    ytd = basis_data.get('depr_ytd')
    mo  = basis_data.get('months_in_service', '?')
    if fy:
        rows.append(['', ''])
        rows.append(['Annual Depreciation (MACRS SL 27.5yr Mid-Month)', f'${_fmt(fy)} / yr'])
        if ytd:
            rows.append([f'  → YTD from closing ({mo} months)',
                         Paragraph(f'<b><font color="#0369a1">${_fmt(ytd)}</font></b>', _BODY)])

    style = [
        ('BACKGROUND',   (0, 0), (-1, 0),  _BLUE_LIGHT),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  _BLUE_MED),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, -1), 9),
        ('BOX',          (0, 0), (-1, -1), 0.5, _GRAY_MED),
        ('INNERGRID',    (0, 0), (-1, -1), 0.25, _GRAY_MED),
        ('LEFTPADDING',  (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('ALIGN',        (1, 0), (1, -1),  'RIGHT'),
        ('BACKGROUND',   (0, 1), (-1, 1),  _GREEN_FILL),
    ]
    t = Table(rows, colWidths=[w * inch for w in col_w])
    t.setStyle(TableStyle(style))
    return t


def _journal_table(records: list, depr_record: dict | None):
    # Landscape gives ~9.9 in usable; distribute across 10 columns
    col_w   = [0.55, 0.65, 0.42, 0.75, 1.55, 1.45, 1.35, 1.75, 0.75, 0.87]  # sum = 10.09
    headers = ['Status', 'Date', 'Dr/Cr', 'Amount', 'Account', 'Ledger',
               'acctSub', 'Description', 'Tax Bucket', 'tID']
    rows       = [headers]
    row_styles = []

    def _row(r, status_txt):
        return [
            status_txt,
            (r.get('dt') or '').replace('-', '.'),
            r.get('aType') or '',
            f"${_fmt(r.get('amt', 0))}",
            _safe(r.get('acct') or ''),
            _safe(r.get('Ledger') or 'Acct.Cash.Escrow'),
            _safe(r.get('acctSub') or ''),
            _safe(r.get('desc') or r.get('Description') or '', 70),
            r.get('tax_bucket') or '',
            _safe(r.get('tID') or ''),
        ]

    for r in records:
        rows.append(_row(r, '✓ New'))
        if str(r.get('acct', '')).startswith('Acct.Fixed'):
            row_styles.append((_GREEN_FILL, len(rows) - 1))

    if depr_record:
        rows.append(_row(depr_record, '📅 Sched'))
        row_styles.append((_AMBER_FILL, len(rows) - 1))

    style = _base_style()
    style.append(('ALIGN', (3, 0), (3, -1), 'RIGHT'))
    for bg, ridx in row_styles:
        style.append(('BACKGROUND', (0, ridx), (-1, ridx), bg))

    t = Table(rows, colWidths=[w * inch for w in col_w])
    t.setStyle(TableStyle(style))
    return t


def _help_section():
    """Accounting guidance block — mirrors the Step 4 Help panel."""
    items = []
    items.append(Paragraph('📖  Accounting Guide — Basis &amp; Journal', _H2))
    items.append(HRFlowable(width='100%', thickness=0.5, color=_GRAY_MED, spaceAfter=6))

    # Two-column guide using a table
    left = (
        '<b>🏗 Basis Frame</b><br/>'
        '<b>Gross Acquisition Cost</b> = all Capitalize+Debit items summed '
        '(purchase price, title, recording, taxes, surveys…).<br/><br/>'
        'The assessor\'s land % splits the gross into '
        '<b>Acct.Fixed.Land</b> (non-depreciable) and '
        '<b>Acct.Fixed.Tangible.InService</b> (depreciable over 27.5 yrs for residential). '
        'These are the two fixed-asset entries posted to the GL.'
    )
    right = (
        '<b>📋 Journal Frame</b><br/>'
        'Shows the <b>exact records</b> written to llcAssets. Every row clears through '
        '<b>Acct.Cash.Escrow</b> as the Ledger (counter-account), so the escrow '
        'account nets to <b>$0</b> when the journal is balanced — no residual liability.<br/><br/>'
        'Fixed asset rows are highlighted <b>green</b>. Credit rows (Cash to Close, New Loan, '
        'Owner Capital) show the funding source that cancels the escrow balance.'
    )
    guide_t = Table(
        [[Paragraph(left, _INFO), Paragraph(right, _INFO)]],
        colWidths=[USABLE_W / 2, USABLE_W / 2],
    )
    guide_t.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, -1), _INFO_BG),
        ('BOX',          (0, 0), (-1, -1), 0.5, colors.HexColor('#7dd3fc')),
        ('LEFTPADDING',  (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING',   (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ('LINEAFTER',    (0, 0), (0, -1),  0.5, colors.HexColor('#7dd3fc')),
    ]))
    items.append(guide_t)

    bs_note = (
        '<b>Balance Sheet effect after commit:</b>  '
        'Acct.Cash.Escrow = <b>$0</b> (cleared)  ·  '
        'Acct.Fixed.Land ↑ land amount  ·  '
        'Acct.Fixed.Tangible.InService ↑ building amount  ·  '
        'funding accounts (Bank / Mortgage / Capital) ↓ by their credit amounts.'
    )
    items.append(Spacer(1, 4))
    items.append(Paragraph(bs_note, _INFO))
    return items


# ── public entry point ────────────────────────────────────────────────────────

def generate_purchase_report(
    records:     list,
    preface:     dict,
    basis_data:  dict,
    depr_record: dict | None,
    output_dir:  str,
    classified:  list | None = None,
) -> str:
    """
    Build the PDF and write it to output_dir.  Returns the full path written.
    classified — original Step-2 rows for the settlement lines section.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = _output_path(preface, output_dir)

    prop_nm      = preface.get('propNm') or 'Property'
    closing_date = (preface.get('closingDate') or '').replace('-', '.')
    title_text   = f'New Property Purchase:  {closing_date}  —  {prop_nm}'
    ts_text      = f'Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}'

    doc = SimpleDocTemplate(
        out_path,
        pagesize=PAGE_SIZE,
        leftMargin=H_MARGIN, rightMargin=H_MARGIN,
        topMargin=V_MARGIN,  bottomMargin=V_MARGIN,
    )

    story = []

    # ── Title ─────────────────────────────────────────────────────────────────
    story.append(Paragraph(title_text, _H1))
    story.append(Paragraph(ts_text, _SMALL))
    story.append(HRFlowable(width='100%', thickness=1, color=_BLUE_DARK, spaceAfter=8))

    # ── Closing Information ───────────────────────────────────────────────────
    story += _section_title('Closing Information')
    story.append(_preface_table(preface))
    story.append(Spacer(1, 10))

    # ── Original Settlement Lines (Step 2 view) ───────────────────────────────
    if classified:
        story += _section_title('Original Closing Settlement Lines')
        story.append(_settlement_table(classified))
        story.append(Spacer(1, 10))

    # ── Property Basis & Depreciation ────────────────────────────────────────
    story += _section_title('Property Basis & Depreciation Estimate')
    story.append(_basis_table(basis_data, preface))
    story.append(Spacer(1, 10))

    # ── Journal Entries ───────────────────────────────────────────────────────
    story += _section_title('Journal Entries  (actual records committed to llcAssets)')
    story.append(_journal_table(records, depr_record))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        'All entries post through <b>Acct.Cash.Escrow</b> '
        '(clearing account; net must equal $0 when balanced).',
        _SMALL,
    ))
    story.append(Spacer(1, 16))

    # ── Accounting Guide ──────────────────────────────────────────────────────
    story += _help_section()

    doc.build(story)
    return out_path
