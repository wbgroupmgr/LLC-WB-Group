"""
ui/llcMonthlyRecon.py — Monthly Reconciliation report routes (issue #45)

Routes:
  GET /view/monthly_reconciliation?year=YYYY      — two-frame HTML view
  GET /api/monthly_recon/months?year=YYYY         — list of months with GL data
  GET /api/monthly_recon/report?ym=YYYY-MM        — full month report JSON
  GET /api/monthly_recon/pdf?ym=YYYY-MM           — PDF download

Report content (per month):
  - All GL transactions posted in the month
  - Summary by account (totals per account path)
  - Income / Expense / Net totals
  - Requisition status: covered vs. outstanding CIP transactions
"""
from __future__ import annotations

import calendar
import io
from collections import defaultdict
from datetime import date
from pathlib import Path

from flask import jsonify, render_template, request, send_file


# ── helpers ────────────────────────────────────────────────────────────────────

def _active_year() -> int:
    from ledger import setup_paths
    return int(getattr(setup_paths, 'YEAR', 2025) or 2025)


def _month_label(ym: str) -> str:
    try:
        y, m = ym.split('-')
        return f'{calendar.month_name[int(m)]} {y}'
    except Exception:
        return ym


def _get_es():
    from flask import current_app
    return current_app.config.get('_esession')


def _gl_for_year(year: int) -> list[dict]:
    """Return all GL rows for `year`, independent of the session's active
    fiscal year (eSession.llc.yr). getGLList() filters to whatever year the
    session is currently switched to, which silently broke this view's own
    year selector when it differed from the requested `year` — always use
    the unfiltered all-time GL and do our own date-prefix filtering here.
    """
    try:
        from ui.llcReportEngine import llcReportEngine
        es = _get_es()
        if es is None:
            return []
        rows = llcReportEngine(es).getGLListAllTime(resolve_dups=True)
        yr = str(year)
        return [r for r in rows if str(r.get('dt', '')).startswith(yr)]
    except Exception:
        return []


def _build_month_report(gl_all: list[dict], year: int, ym: str,
                        req_map: dict, missing_reqs: list[dict]) -> dict:
    """Aggregate GL rows for one month and attach requisition status."""
    txns = [r for r in gl_all if str(r.get('dt', '')).startswith(ym)]

    # Summary by account
    acct_totals: dict[str, dict] = {}
    income_total = 0.0
    expense_total = 0.0

    for r in txns:
        acct     = r.get('acct', '')
        atype    = r.get('aType', 'Debit')
        amt      = float(r.get('amt', 0) or 0)
        acct_type = r.get('acctType', '')

        if acct not in acct_totals:
            acct_totals[acct] = {'acct': acct, 'acctType': acct_type,
                                 'debit': 0.0, 'credit': 0.0, 'txn_count': 0}
        if atype == 'Debit':
            acct_totals[acct]['debit'] += amt
        else:
            acct_totals[acct]['credit'] += amt
        acct_totals[acct]['txn_count'] += 1

        # Period income/expense totals (cash-basis: credit = income, debit = expense for operating accounts)
        if acct_type == 'Income':
            income_total += amt
        elif acct_type == 'Expense':
            expense_total += amt

    # Requisitions for this month's CIP transactions
    month_tids = {r.get('tID', '') for r in txns}
    month_reqs = [req for req in req_map.values() if req.get('tID', '') in month_tids]
    month_missing = [m for m in missing_reqs if m.get('tID', '') in month_tids]

    return {
        'ym':              ym,
        'label':           _month_label(ym),
        'txn_count':       len(txns),
        'transactions':    sorted(txns, key=lambda r: (r.get('dt', ''), r.get('acct', ''))),
        'summary_by_acct': sorted(acct_totals.values(),
                                  key=lambda x: (x['acctType'], x['acct'])),
        'income_total':    round(income_total, 2),
        'expense_total':   round(expense_total, 2),
        'net':             round(income_total - expense_total, 2),
        'requisitions':    month_reqs,
        'outstanding_reqs': month_missing,
    }


def _missing_reqs_for_year(objects: dict, year: int, req_map: dict) -> list[dict]:
    """CIP GL entries for `year` that have no requisition.

    Uses load_object() (raw, unfiltered) rather than load() — the latter
    filters to the session's active fiscal year, which broke this check
    whenever the requested `year` differed from that active year.
    """
    missing = []
    seen: set[str] = set()
    yr = str(year)
    for key in ('llcExpRev', 'llcAssets'):
        mgr = objects.get(key)
        if not mgr:
            continue
        try:
            for r in mgr.load_object():
                if not str(r.get('dt', '')).startswith(yr):
                    continue
                acct = str(r.get('acct', '')) + '|' + str(r.get('Ledger', ''))
                if 'InConstruction' not in acct:
                    continue
                tID = r.get('tID', '')
                if not tID or tID in req_map or tID in seen:
                    continue
                seen.add(tID)
                raw_acct = r.get('acct', '')
                ledger   = r.get('Ledger', '')
                eff_acct = ledger if raw_acct == 'Acct.Cash.Bank' and ledger else raw_acct
                missing.append({
                    'tID': tID, 'dt': r.get('dt', ''),
                    'amt': r.get('amt', 0), 'desc': r.get('desc', ''),
                    'propNm': r.get('propNm', ''), 'acct': eff_acct,
                })
        except Exception:
            pass
    return missing


# ── PDF generator ──────────────────────────────────────────────────────────────

def _build_pdf(report: dict, llc_name: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    C_HEADER  = colors.HexColor('#1e3a8a')
    C_WHITE   = colors.white
    C_ALT     = colors.HexColor('#f0f4ff')
    C_BORDER  = colors.HexColor('#d1d5db')
    C_SUB     = colors.HexColor('#3b82f6')
    C_WARN    = colors.HexColor('#fef3c7')
    C_WARN_BD = colors.HexColor('#d97706')

    def _fmt(v: float) -> str:
        if v < 0:
            return f'({abs(v):,.2f})'
        return f'{v:,.2f}'

    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=letter,
                             leftMargin=0.75*inch, rightMargin=0.75*inch,
                             topMargin=0.75*inch, bottomMargin=0.75*inch)
    sty  = getSampleStyleSheet()
    h1   = ParagraphStyle('H1', parent=sty['Heading1'], fontSize=14,
                          textColor=C_HEADER, spaceAfter=4)
    h2   = ParagraphStyle('H2', parent=sty['Heading2'], fontSize=10,
                          textColor=C_HEADER, spaceAfter=4, spaceBefore=10)
    body = ParagraphStyle('Body', parent=sty['Normal'], fontSize=8, spaceAfter=3)
    note = ParagraphStyle('Note', parent=sty['Normal'], fontSize=7,
                          textColor=colors.HexColor('#6b7280'), spaceAfter=3)
    warn = ParagraphStyle('Warn', parent=sty['Normal'], fontSize=8,
                          textColor=colors.HexColor('#92400e'), spaceAfter=3)

    def _tbl_style(n_rows: int, last_bold: bool = False) -> TableStyle:
        cmds = [
            ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, -1), 7.5),
            ('BACKGROUND',    (0, 0), (-1, 0),  C_HEADER),
            ('TEXTCOLOR',     (0, 0), (-1, 0),  C_WHITE),
            ('GRID',          (0, 0), (-1, -1), 0.4, C_BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ]
        for i in range(1, n_rows):
            if i % 2 == 0:
                cmds.append(('BACKGROUND', (0, i), (-1, i), C_ALT))
        if last_bold and n_rows > 1:
            cmds += [
                ('FONTNAME',   (0, n_rows - 1), (-1, n_rows - 1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, n_rows - 1), (-1, n_rows - 1),
                 colors.HexColor('#dbeafe')),
                ('LINEABOVE',  (0, n_rows - 1), (-1, n_rows - 1), 0.8, C_SUB),
            ]
        return TableStyle(cmds)

    story = []

    # ── Title ──────────────────────────────────────────────────────────────────
    story.append(Paragraph(f'Monthly Reconciliation Report', h1))
    story.append(Paragraph(f'{report["label"]}  ·  {llc_name}', body))
    story.append(HRFlowable(width='100%', thickness=1.5, color=C_HEADER, spaceAfter=8))

    # ── Section 1: Transaction Listing ────────────────────────────────────────
    story.append(Paragraph('Section 1 — Transaction Listing', h2))
    story.append(Paragraph(
        f'All {report["txn_count"]} GL entries posted during this period.',
        note))

    txn_hdr  = [['Date', 'Account', 'Description', 'Property', 'D/C', 'Amount']]
    txn_rows = []
    for r in report['transactions']:
        txn_rows.append([
            r.get('dt', ''),
            r.get('acct', ''),
            (r.get('desc', '') or '')[:45],
            r.get('propNm', '') or '',
            r.get('aType', '')[0],    # D or C
            _fmt(float(r.get('amt', 0) or 0)),
        ])
    if not txn_rows:
        txn_rows = [['—', '—', 'No transactions', '—', '—', '—']]
    data = txn_hdr + txn_rows
    col_w = [0.7*inch, 2.0*inch, 2.1*inch, 1.2*inch, 0.3*inch, 0.8*inch]
    ts = _tbl_style(len(data))
    ts.add('ALIGN', (5, 0), (5, -1), 'RIGHT')
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(ts)
    story += [tbl, Spacer(1, 0.1*inch)]

    # ── Section 2: Account Summary ────────────────────────────────────────────
    story.append(Paragraph('Section 2 — Account Summary', h2))
    sum_hdr  = [['Account', 'Type', 'Txns', 'Debits', 'Credits']]
    sum_rows = []
    for s in report['summary_by_acct']:
        sum_rows.append([
            s['acct'],
            s['acctType'],
            str(s['txn_count']),
            _fmt(s['debit']) if s['debit'] else '',
            _fmt(s['credit']) if s['credit'] else '',
        ])
    # Totals row
    tot_d = sum(s['debit']  for s in report['summary_by_acct'])
    tot_c = sum(s['credit'] for s in report['summary_by_acct'])
    sum_rows.append(['TOTAL', '', '', _fmt(tot_d), _fmt(tot_c)])
    if not sum_rows[:-1]:
        sum_rows = [['—', '—', '0', '—', '—'], ['TOTAL', '', '', '—', '—']]
    data2 = sum_hdr + sum_rows
    col_w2 = [2.4*inch, 0.9*inch, 0.4*inch, 1.1*inch, 1.1*inch]
    ts2 = _tbl_style(len(data2), last_bold=True)
    ts2.add('ALIGN', (2, 0), (4, -1), 'RIGHT')
    tbl2 = Table(data2, colWidths=col_w2, repeatRows=1)
    tbl2.setStyle(ts2)
    story += [tbl2, Spacer(1, 0.1*inch)]

    # ── Section 3: Period Totals ───────────────────────────────────────────────
    story.append(Paragraph('Section 3 — Period Totals', h2))
    totals_data = [
        ['Income (Revenue)',  _fmt(report['income_total'])],
        ['Expenses',         _fmt(report['expense_total'])],
        ['Net Income/(Loss)', _fmt(report['net'])],
    ]
    ts3 = TableStyle([
        ('FONTNAME',   (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME',   (0, 2), (-1, 2),  'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, -1), 9),
        ('ALIGN',      (1, 0), (1, -1),  'RIGHT'),
        ('GRID',       (0, 0), (-1, -1), 0.4, C_BORDER),
        ('BACKGROUND', (0, 2), (-1, 2),  colors.HexColor('#dbeafe')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ])
    tbl3 = Table(totals_data, colWidths=[3.0*inch, 1.2*inch])
    tbl3.setStyle(ts3)
    story += [tbl3, Spacer(1, 0.1*inch)]

    # ── Section 4: Requisition Status ─────────────────────────────────────────
    story.append(Paragraph('Section 4 — Requisition Status (Capital Expenditures)', h2))
    n_covered    = len(report['requisitions'])
    n_outstanding = len(report['outstanding_reqs'])

    if n_outstanding > 0:
        story.append(Paragraph(
            f'⚠ {n_outstanding} CIP transaction(s) are missing requisitions. '
            f'Documentation required before year-end filing (IRC §263).',
            warn))
        out_hdr  = [['tID', 'Date', 'Amount', 'Description', 'Property']]
        out_rows = [[
            m.get('tID', ''), m.get('dt', ''),
            _fmt(float(m.get('amt', 0) or 0)),
            (m.get('desc', '') or '')[:40],
            m.get('propNm', '') or '',
        ] for m in report['outstanding_reqs']]
        data_out = out_hdr + out_rows
        ts_out = _tbl_style(len(data_out))
        ts_out.add('BACKGROUND', (0, 0), (-1, len(data_out) - 1), C_WARN)
        ts_out.add('BACKGROUND', (0, 0), (-1, 0), C_WARN_BD)
        ts_out.add('ALIGN', (2, 1), (2, -1), 'RIGHT')
        tbl_out = Table(data_out,
                        colWidths=[1.5*inch, 0.7*inch, 0.9*inch, 2.3*inch, 1.2*inch],
                        repeatRows=1)
        tbl_out.setStyle(ts_out)
        story += [tbl_out, Spacer(1, 0.08*inch)]
    else:
        story.append(Paragraph('✓ All CIP transactions have requisitions.', body))

    if n_covered > 0:
        story.append(Paragraph(f'{n_covered} requisition(s) on file for this period:', body))
        req_hdr  = [['tID', 'Date', 'Amount', 'Purpose', 'Property']]
        req_rows = [[
            r.get('tID', ''), r.get('dt', ''),
            _fmt(float(r.get('amt', 0) or 0)),
            (r.get('purpose', '') or '')[:45],
            r.get('propNm', '') or '',
        ] for r in report['requisitions']]
        data_req = req_hdr + req_rows
        ts_req = _tbl_style(len(data_req))
        ts_req.add('ALIGN', (2, 1), (2, -1), 'RIGHT')
        tbl_req = Table(data_req,
                        colWidths=[1.5*inch, 0.7*inch, 0.9*inch, 2.4*inch, 1.1*inch],
                        repeatRows=1)
        tbl_req.setStyle(ts_req)
        story += [tbl_req, Spacer(1, 0.08*inch)]

    story.append(Spacer(1, 0.15*inch))
    story.append(Paragraph(
        'IRS Note: Monthly reconciliation records must be retained for a minimum of 3 years '
        '(IRC §6001). Aggregate these monthly figures to populate Schedule K / Form 8825 line items.',
        note))

    doc.build(story)
    return buf.getvalue()


# ── route binder ───────────────────────────────────────────────────────────────

def bind_monthly_recon_routes(app, objects: dict) -> None:

    @app.route('/view/monthly_reconciliation')
    def view_monthly_reconciliation():
        try:
            year = int(request.args.get('year', _active_year()))
        except (TypeError, ValueError):
            year = _active_year()
        return render_template(
            'monthly_recon.html',
            configured_year=year,
        )

    @app.route('/api/monthly_recon/months')
    def api_monthly_recon_months():
        try:
            year    = int(request.args.get('year', _active_year()))
            gl_rows = _gl_for_year(year)

            from ledger.bankAgent.bkReqDocAgent import BkReqDocAgent
            es  = _get_es()
            llc = es.llc if es else None
            req_map = {d['tID']: d for d in BkReqDocAgent(year, llc).all()}
            missing = _missing_reqs_for_year(objects, year, req_map)
            missing_by_ym: dict[str, int] = defaultdict(int)
            for m in missing:
                ym = str(m.get('dt', ''))[:7]
                if ym:
                    missing_by_ym[ym] += 1

            # Collect unique year-months present in GL
            ym_set: set[str] = set()
            for r in gl_rows:
                ym = str(r.get('dt', ''))[:7]
                if ym and len(ym) == 7:
                    ym_set.add(ym)

            months = sorted(ym_set)
            result = [{
                'ym':           ym,
                'label':        _month_label(ym),
                'txn_count':    sum(1 for r in gl_rows
                                    if str(r.get('dt', '')).startswith(ym)),
                'missing_reqs': missing_by_ym.get(ym, 0),
            } for ym in months]

            return jsonify({'ok': True, 'year': year, 'months': result})
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500

    @app.route('/api/monthly_recon/report')
    def api_monthly_recon_report():
        try:
            ym   = request.args.get('ym', '')
            year = int(ym[:4]) if ym and len(ym) >= 4 else _active_year()
            if not ym:
                return jsonify({'ok': False, 'error': 'ym param required (YYYY-MM)'}), 400

            gl_rows = _gl_for_year(year)

            from ledger.bankAgent.bkReqDocAgent import BkReqDocAgent
            es  = _get_es()
            llc = es.llc if es else None
            rda     = BkReqDocAgent(year, llc)
            req_map = {d['tID']: d for d in rda.all()}
            missing = _missing_reqs_for_year(objects, year, req_map)

            report = _build_month_report(gl_rows, year, ym, req_map, missing)

            # BookState (issue #53/#57) — surface whether this report's GL
            # snapshot is currently in sync with RealDB, so drift is visible
            # on the one view an operator checks month to month.
            book_state_status = None
            if llc is not None:
                from ledger import bookState
                books = getattr(es, 'books', None)
                book_state_status = books.book_state_status() if books else {
                    'inSync': None, 'current': bookState.compute(llc),
                }

            return jsonify({'ok': True, 'report': report, 'bookState': book_state_status})
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500

    @app.route('/api/monthly_recon/refresh_books', methods=['POST'])
    def api_monthly_recon_refresh_books():
        """Force the session's shared BooksContext GL cache to rebuild against
        the current RealDB files, clearing the "Books changed since last GL
        build" warning. That warning is a diagnostic-only comparison (issue
        #53/#57) — it never self-clears unless something elsewhere in the app
        happens to touch es.books.gl_rows, which nothing on this view does.
        """
        try:
            es = _get_es()
            books = getattr(es, 'books', None) if es else None
            if books is None:
                return jsonify({'ok': False, 'error': 'no active session'}), 400
            books.invalidate()
            books.gl_rows  # force rebuild now, recording a fresh source_state
            return jsonify({'ok': True, 'bookState': books.book_state_status()})
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500

    @app.route('/api/monthly_recon/pdf')
    def api_monthly_recon_pdf():
        try:
            ym   = request.args.get('ym', '')
            year = int(ym[:4]) if ym and len(ym) >= 4 else _active_year()
            if not ym:
                return jsonify({'ok': False, 'error': 'ym param required'}), 400

            gl_rows = _gl_for_year(year)

            from ledger.bankAgent.bkReqDocAgent import BkReqDocAgent
            es  = _get_es()
            llc = es.llc if es else None
            rda     = BkReqDocAgent(year, llc)
            req_map = {d['tID']: d for d in rda.all()}
            missing = _missing_reqs_for_year(objects, year, req_map)
            report  = _build_month_report(gl_rows, year, ym, req_map, missing)

            llc_name = getattr(llc, 'objName', 'LLC') if llc else 'LLC'
            pdf_bytes = _build_pdf(report, llc_name)

            buf = io.BytesIO(pdf_bytes)
            fname = f'{llc_name}_{ym}_MonthlyRecon.pdf'
            return send_file(buf, mimetype='application/pdf',
                             as_attachment=True, download_name=fname)
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500
