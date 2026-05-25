"""
PDF report generator for NewPropertyAgent closing summary.
Uses reportlab to produce a one-page purchase summary including
preface metadata, property basis, depreciation estimate, and journal entries.
"""
import os
import re
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


# ── colour palette (matches UI) ──────────────────────────────────────────────
_BLUE_DARK  = colors.HexColor('#1d4ed8')
_BLUE_MED   = colors.HexColor('#1e40af')
_BLUE_LIGHT = colors.HexColor('#dbeafe')
_GREEN_DARK = colors.HexColor('#166534')
_GREEN_FILL = colors.HexColor('#f0fdf4')
_AMBER_FILL = colors.HexColor('#fef3c7')
_AMBER_DARK = colors.HexColor('#92400e')
_GRAY_LIGHT = colors.HexColor('#f8fafc')
_GRAY_MED   = colors.HexColor('#e2e8f0')
_GRAY_DARK  = colors.HexColor('#64748b')
_SLATE      = colors.HexColor('#1e293b')
_TEAL       = colors.HexColor('#0369a1')

_STYLES = getSampleStyleSheet()

def _style(name, **kwargs):
    s = _STYLES[name]
    return ParagraphStyle(
        name + '_custom_' + '_'.join(k + str(v) for k, v in kwargs.items()),
        parent=s,
        **kwargs
    )

_H1    = _style('Heading1', fontSize=16, textColor=_BLUE_DARK, spaceAfter=2)
_H2    = _style('Heading2', fontSize=11, textColor=_BLUE_MED, spaceBefore=10, spaceAfter=4)
_BODY  = _style('Normal',   fontSize=9,  textColor=_SLATE, leading=13)
_SMALL = _style('Normal',   fontSize=8,  textColor=_GRAY_DARK, leading=11)
_MONO  = _style('Code',     fontSize=8,  textColor=_TEAL)


def _fmt(v):
    try:
        return f'{float(v):,.2f}'
    except Exception:
        return str(v or '')


def _safe_str(v):
    return str(v or '').replace('<', '&lt;').replace('>', '&gt;')


def _clean_filename(s):
    return re.sub(r'[^\w\-. ]', '_', str(s)).strip()


def _output_path(preface: dict, output_dir: str) -> str:
    raw_date    = (preface.get('closingDate') or '').replace('/', '-').replace('.', '-')
    parts       = raw_date.split('-')
    if len(parts) == 3:
        date_part = f'{parts[0]}.{parts[1].zfill(2)}.{parts[2].zfill(2)}'
    else:
        date_part = raw_date or datetime.today().strftime('%Y.%m.%d')
    prop_nm     = _clean_filename(preface.get('propNm') or 'Property').replace(' ', '_')
    filename    = f'{date_part}_PurchaseNewProp_{prop_nm}.pdf'
    return os.path.join(output_dir, filename)


def resolve_output_dir(preface: dict, top_dir: str | None = None) -> str | None:
    """
    Derive the output directory from preface.refDoc (preferred) or preface.refDB.

    refDoc format: '<label>, <category>, <type>, <relative/path/to/file.pdf>'
    The last comma-separated segment is treated as a path relative to top_dir.
    Returns an absolute directory string, or None if no usable path found.
    """
    if top_dir is None:
        try:
            from ledger import setup_paths
            top_dir = str(setup_paths.TOP) if setup_paths.TOP else None
        except Exception:
            pass

    ref_doc = (preface.get('closingDoc') or preface.get('refDoc') or '').strip()
    # refDoc: 'H_805HighMesa, Closing Docs, Capitalize, Assets/805HighMesa/Docs/file.pdf'
    if ref_doc and ',' in ref_doc:
        path_part = ref_doc.split(',')[-1].strip()
        if path_part and ('/' in path_part or '\\' in path_part):
            # It's a relative path — directory portion only
            rel_dir = os.path.dirname(path_part)
            if top_dir and rel_dir:
                candidate = os.path.join(top_dir, rel_dir)
                return candidate
            if os.path.isabs(path_part):
                return os.path.dirname(path_part)

    # Fallback: refDB if it looks like a path
    ref_db = (preface.get('refDB') or '').strip()
    if ref_db and ('/' in ref_db or '\\' in ref_db):
        if os.path.isabs(ref_db):
            return os.path.dirname(ref_db) if '.' in os.path.basename(ref_db) else ref_db
        if top_dir:
            return os.path.join(top_dir, os.path.dirname(ref_db) if '.' in os.path.basename(ref_db) else ref_db)

    return None


def _section_title(text):
    return [
        Paragraph(text, _H2),
        HRFlowable(width='100%', thickness=0.5, color=_GRAY_MED, spaceAfter=4),
    ]


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
    rows = []
    for i in range(0, len(pairs), 2):
        row = []
        for lbl, val in pairs[i:i+2]:
            row.append(Paragraph(f'<font color="#6b7280" size="7">{lbl}</font>', _BODY))
            row.append(Paragraph(f'<b>{_safe_str(val)}</b>', _BODY))
        if len(row) == 2:   # odd pair at end
            row += ['', '']
        rows.append(row)

    t = Table(rows, colWidths=[0.85*inch, 2.2*inch, 0.85*inch, 2.2*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _GRAY_LIGHT),
        ('BOX',        (0, 0), (-1, -1), 0.5, _GRAY_MED),
        ('INNERGRID',  (0, 0), (-1, -1), 0.25, _GRAY_MED),
        ('LEFTPADDING',  (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING',   (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
        ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


def _basis_table(basis_data: dict, preface: dict):
    land_pct = preface.get('landPct') or 0
    bldg_pct = round(100.0 - float(land_pct), 2)

    rows = [
        [Paragraph('<b>Basis Component</b>', _BODY), Paragraph('<b>Amount</b>', _BODY)],
        ['Gross Capitalized Acquisition Cost',
         Paragraph(f'<b>${_fmt(basis_data.get("gross_basis", 0))}</b>', _BODY)],
    ]
    if land_pct:
        rows.append([
            f'→ Land ({land_pct}%)  —  Acct.Fixed.Land',
            f'${_fmt(basis_data.get("land_amt", 0))}',
        ])
        rows.append([
            f'→ Building ({bldg_pct}%)  —  Acct.Fixed.Tangible.InService',
            f'${_fmt(basis_data.get("bldg_amt", 0))}',
        ])

    # Depreciation rows
    fy  = basis_data.get('depr_full_year')
    ytd = basis_data.get('depr_ytd')
    mo  = basis_data.get('months_in_service', '?')
    if fy:
        rows.append(['', ''])  # spacer row
        rows.append([
            'Annual Depreciation (MACRS SL 27.5yr Mid-Month)',
            f'${_fmt(fy)} / yr',
        ])
        if ytd:
            rows.append([
                f'  → YTD from closing ({mo} months)',
                Paragraph(f'<b><font color="#0369a1">${_fmt(ytd)}</font></b>', _BODY),
            ])

    t = Table(rows, colWidths=[4.8*inch, 1.5*inch])
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), _BLUE_LIGHT),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, -1), 9),
        ('BOX',        (0, 0), (-1, -1), 0.5, _GRAY_MED),
        ('INNERGRID',  (0, 0), (-1, -1), 0.25, _GRAY_MED),
        ('LEFTPADDING',  (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]
    # shade gross row
    style.append(('BACKGROUND', (0, 1), (-1, 1), _GREEN_FILL))
    t.setStyle(TableStyle(style))
    return t


def _journal_table(records: list, depr_record: dict | None):
    headers = ['Status', 'Date', 'Dr/Cr', 'Amount', 'Account', 'Ledger', 'acctSub', 'Description', 'Tax Bucket', 'tID']
    col_w   = [0.55, 0.65, 0.42, 0.65, 1.3, 1.2, 1.1, 1.65, 0.72, 1.1]   # inches, sum~9.34 ≈ usable
    rows    = [headers]
    row_styles = []  # (bg_color, row_index)

    def _row_data(r, status_txt, is_fixed=False, is_depr=False):
        tID     = r.get('tID') or ''
        dt      = (r.get('dt') or '').replace('-', '.')
        acct    = r.get('acct') or ''
        ledger  = r.get('Ledger') or 'Acct.Cash.Escrow'
        acctSub = r.get('acctSub') or ''
        desc    = (r.get('desc') or r.get('Description') or '')[:60]
        bucket  = r.get('tax_bucket') or ''
        amt     = f"${_fmt(r.get('amt', 0))}"
        atype   = r.get('aType') or ''
        return [status_txt, dt, atype, amt, acct, ledger, acctSub, desc, bucket, tID]

    for i, r in enumerate(records):
        is_fixed = str(r.get('acct', '')).startswith('Acct.Fixed')
        rows.append(_row_data(r, '✓ New', is_fixed=is_fixed))
        if is_fixed:
            row_styles.append((_GREEN_FILL, len(rows) - 1))

    if depr_record:
        rows.append(_row_data(depr_record, '📅 Sched', is_depr=True))
        row_styles.append((_AMBER_FILL, len(rows) - 1))

    t = Table(rows, colWidths=[w * inch for w in col_w])
    style = [
        ('BACKGROUND',  (0, 0), (-1, 0), _BLUE_DARK),
        ('TEXTCOLOR',   (0, 0), (-1, 0), colors.white),
        ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, -1), 7),
        ('BOX',         (0, 0), (-1, -1), 0.5, _GRAY_MED),
        ('INNERGRID',   (0, 0), (-1, -1), 0.25, _GRAY_MED),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
        ('ALIGN',       (3, 0), (3, -1), 'RIGHT'),   # Amount col right-aligned
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _GRAY_LIGHT]),
        ('WORDWRAP',    (7, 1), (7, -1), True),  # Description
        ('WORDWRAP',    (6, 1), (6, -1), True),  # acctSub
    ]
    for bg, ridx in row_styles:
        style.append(('BACKGROUND', (0, ridx), (-1, ridx), bg))
    t.setStyle(TableStyle(style))
    return t


def generate_purchase_report(
    records:     list,
    preface:     dict,
    basis_data:  dict,
    depr_record: dict | None,
    output_dir:  str,
) -> str:
    """
    Build the PDF and write it to output_dir.
    Returns the full path of the written file.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = _output_path(preface, output_dir)

    prop_nm      = preface.get('propNm') or 'Property'
    closing_date = (preface.get('closingDate') or '').replace('-', '.')
    title_text   = f'New Property Purchase: {closing_date}  {prop_nm}'
    ts_text      = f'Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}'

    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        leftMargin=0.65*inch, rightMargin=0.65*inch,
        topMargin=0.65*inch,  bottomMargin=0.65*inch,
    )

    story = []

    # ── Title block ──────────────────────────────────────────────────────────
    story.append(Paragraph(title_text, _H1))
    story.append(Paragraph(ts_text,    _SMALL))
    story.append(HRFlowable(width='100%', thickness=1, color=_BLUE_DARK, spaceAfter=8))

    # ── Preface ──────────────────────────────────────────────────────────────
    story += _section_title('Closing Information')
    story.append(_preface_table(preface))
    story.append(Spacer(1, 10))

    # ── Property Basis ───────────────────────────────────────────────────────
    story += _section_title('Property Basis & Depreciation Estimate')
    story.append(_basis_table(basis_data, preface))
    story.append(Spacer(1, 10))

    # ── Journal Entries ──────────────────────────────────────────────────────
    story += _section_title('Journal Entries')
    story.append(_journal_table(records, depr_record))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        'All entries post through <b>Acct.Cash.Escrow</b> (clearing account; net must equal $0 when balanced).',
        _SMALL,
    ))

    doc.build(story)
    return out_path
