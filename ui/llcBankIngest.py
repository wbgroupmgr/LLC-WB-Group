"""
ui/llcBankIngest.py — Flask routes for the BankToBook views (issue #42)

Phase A (this commit) — Bank Reconciliation / Preview only:
    GET  /view/bank_reconcile      — CSV selector + propNm; renders bank_preview.html
    POST /api/bank/ingest/preview  — BankAgent.preview() → serialized PreviewResult (read-only)
    POST /api/bank/ingest/commit   — operator edits + BankAgent.commit() → llcExpRev
    POST /api/bank/ingest/discard  — delete stored preview

Bank Knowledge/Rules (Phase B) and Requisitions (Phase C) get their own
routes here later; their views are construction stubs for now.

Preview is serialised to a temp JSON in _PREVIEW_DIR; the browser holds the token.
The proven backend logic is reused from the reverted v1 (preview/commit was sound;
only the v1 single-page UI was discarded).
"""
from __future__ import annotations

import datetime
import json
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from flask import current_app, jsonify, render_template, request

# COA accounts offered in the editable preview dropdown
_KNOWN_ACCTS: list[tuple[str, str]] = [
    ('Acct.Cash.Bank',                     'Cash — Bank'),
    ('Acct.Exp.Ins',                       'Expense — Insurance'),
    ('Acct.Exp.Other',                     'Expense — Other'),
    ('Acct.Exp.Repair',                    'Expense — Repair/Maint'),
    ('Acct.Exp.Tax.Prop',                  'Expense — Property Tax'),
    ('Acct.Exp.Util',                      'Expense — Utilities'),
    ('Acct.Rev.Fees.Other',                'Revenue — Fees/Other'),
    ('Acct.Rev.Rent',                      'Revenue — Rent'),
    ('Acct.Fixed.Tangible.InConstruction', 'Fixed Asset — CIP (In Construction)'),
    ('Acct.Fixed.Tangible.InService',      'Fixed Asset — In Service'),
    ('Acct.Equity.Capital.Member',         'Equity — Member Capital'),
    ('Acct.Liab.Loan.Mortgage',            'Liability — Mortgage'),
]

_TXN_TYPES = ['ROUTINE_EXPENSE', 'RENT_INCOME', 'MEMBER_INVEST', 'SPECIAL_WIRE',
              'RETURN_PAIR', 'ACH_VERIFY', 'BANK_DEPOSIT', 'BANK_BONUS', 'UNKNOWN']
_CONFIDENCES = ['auto', 'review', 'flagged']

# ── preview storage ─────────────────────────────────────────────────────────────

_PREVIEW_DIR = Path(tempfile.gettempdir()) / 'llc_bank_previews'
_PREVIEW_DIR.mkdir(exist_ok=True)


def _preview_path(token: str) -> Path:
    return _PREVIEW_DIR / f'bank_preview_{token}.json'


def _store_preview(token, rows_dicts, stats, source, ts, propNm_default='') -> None:
    payload = {'token': token, 'rows': rows_dicts, 'stats': stats,
               'source': source, 'ts': ts, 'propNm_default': propNm_default}
    with open(_preview_path(token), 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)


def _load_preview(token: str) -> dict | None:
    p = _preview_path(token)
    if not p.exists():
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def _delete_preview(token: str) -> None:
    p = _preview_path(token)
    if p.exists():
        p.unlink()


# ── ClassifiedRow helpers ───────────────────────────────────────────────────────

def _cr_to_dict(cr) -> dict:
    return asdict(cr)


def _dict_to_cr(d: dict):
    from ledger.bankAgent.IngestAgent import ClassifiedRow
    known = ClassifiedRow.__dataclass_fields__.keys()
    return ClassifiedRow(**{k: d[k] for k in known if k in d})


# ── session helpers ─────────────────────────────────────────────────────────────

def _get_llc():
    es = current_app.config.get('_esession')
    return getattr(es, 'llc', None) if es else None


def _get_prop_names(objects: dict) -> list[str]:
    props: set[str] = {'LLC'}
    for key in ('llcAssets', 'llcPayables', 'llcReceivables'):
        mgr = objects.get(key)
        if mgr:
            try:
                for r in mgr.load():
                    p = r.get('propNm', '')
                    if p:
                        props.add(p)
            except Exception:
                pass
    return sorted(props)


def _infer_year_from_name(filename: str) -> int | None:
    m = re.search(r'(20\d{2})', filename)
    return int(m.group(1)) if m else None


def _req_rid_map(year: int, llc) -> dict:
    """{tID: rID} where rID is the 1-based position in the requisition DB."""
    try:
        from ledger.bankAgent.bkReqDocAgent import BkReqDocAgent
        docs = BkReqDocAgent(year, llc).all()
        return {d['tID']: i + 1 for i, d in enumerate(docs) if d.get('tID')}
    except Exception:
        return {}


def _detect_csv_year(csv_path: str) -> int | None:
    """Detect year from WF (col 0 = date) or Chase (col 1 = posting date) CSV."""
    try:
        import csv as _csv
        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            for row in _csv.reader(f):
                for cell in row[:3]:  # check cols 0-2 for a date
                    try:
                        return datetime.datetime.strptime(cell.strip(), '%m/%d/%Y').year
                    except ValueError:
                        pass
    except Exception:
        pass
    return None


def _bankstmts_dir(year: int) -> Path | None:
    """Return books/<year>/BankStmts/, creating it if needed."""
    try:
        from ledger import setup_paths
        top = setup_paths.TOP
        if not top:
            return None
        d = Path(top) / 'books' / str(year) / 'BankStmts'
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return None


def _save_upload_to_bankstmts(file_storage, original_name: str) -> tuple[Path, str] | None:
    """Save uploaded file to books/<year>/BankStmts/WBGroupLLC_<bank>_<date>.csv.
    Returns (saved_path, bank_source_name) or None on failure."""
    try:
        import csv as _csv, io as _io
        data = file_storage.read()
        file_storage.seek(0)  # reset so BankAgent can re-read via the path

        text = data.decode('utf-8', errors='replace')
        first_row = next(iter(_csv.reader(_io.StringIO(text))), [])

        # Detect bank from header
        h0 = first_row[0].strip().lower() if first_row else ''
        is_chase = h0 in ('details', 'transaction date', 'post date')
        bank_tag = 'Chase' if is_chase else 'WF'

        # Detect year from CSV content
        year: int | None = None
        for row in _csv.reader(_io.StringIO(text)):
            for cell in row[:3]:
                try:
                    year = datetime.datetime.strptime(cell.strip(), '%m/%d/%Y').year
                    break
                except ValueError:
                    pass
            if year:
                break
        if not year:
            year = datetime.date.today().year

        dest_dir = _bankstmts_dir(year)
        if not dest_dir:
            return None

        today = datetime.date.today().strftime('%Y%m%d')
        dest = dest_dir / f'WBGroupLLC_{bank_tag}_{today}.csv'
        # avoid overwrite — append counter if file exists
        counter = 1
        while dest.exists():
            dest = dest_dir / f'WBGroupLLC_{bank_tag}_{today}_{counter}.csv'
            counter += 1

        dest.write_bytes(data)
        return dest, f'BankStmts/{year}'
    except Exception:
        return None


def _list_csv_candidates() -> list[dict]:
    """{name, path, source, year, age_days} from BankStmts/<year>/ + ~/Downloads (≤90d)."""
    candidates: list[dict] = []
    seen: set[str] = set()
    now = datetime.datetime.now()

    try:
        from ledger import setup_paths
        top = setup_paths.TOP
        books_dir = setup_paths.BOOKS_DIR or 'books'
        if top:
            books_root = Path(top) / books_dir
            if books_root.exists():
                for yr_dir in sorted(books_root.iterdir()):
                    if not yr_dir.is_dir() or not yr_dir.name.isdigit():
                        continue
                    bank_dir = yr_dir / 'BankStmts'
                    if not bank_dir.exists():
                        continue
                    for csv_file in sorted(bank_dir.glob('*.csv')):
                        ap = str(csv_file.resolve())
                        if ap in seen:
                            continue
                        seen.add(ap)
                        candidates.append({
                            'name': csv_file.name, 'path': ap,
                            'source': f'BankStmts/{yr_dir.name}',
                            'year': int(yr_dir.name), 'age_days': None,
                        })
    except Exception:
        pass

    try:
        dl = Path.home() / 'Downloads'
        if dl.exists():
            cutoff = now - datetime.timedelta(days=90)
            for csv_file in sorted(dl.glob('*.csv')):
                ap = str(csv_file.resolve())
                if ap in seen:
                    continue
                mtime = datetime.datetime.fromtimestamp(csv_file.stat().st_mtime)
                if mtime < cutoff:
                    continue
                seen.add(ap)
                candidates.append({
                    'name': csv_file.name, 'path': ap, 'source': 'Downloads',
                    'year': _infer_year_from_name(csv_file.name),
                    'age_days': (now - mtime).days,
                })
    except Exception:
        pass

    return candidates


# ── bind routes ─────────────────────────────────────────────────────────────────

def bind_bankIngest_routes(app, objects: dict):

    @app.route('/view/bank_reconcile')
    def view_bank_reconcile():
        from ledger import setup_paths
        return render_template(
            'bank_preview.html',
            prop_names=_get_prop_names(objects),
            csv_candidates=_list_csv_candidates(),
            configured_year=getattr(setup_paths, 'YEAR', None),
            known_accts=_KNOWN_ACCTS,
        )

    @app.route('/api/bank/ingest/preview', methods=['POST'])
    def api_bank_ingest_preview():
        try:
            llc = _get_llc()
            if llc is None:
                return jsonify({'ok': False, 'error': 'LLC not initialised'}), 500

            from ledger.bankAgent.BankAgent import BankAgent

            csv_path_str = None
            saved_path_str = None
            if 'csv_file' in request.files and request.files['csv_file'].filename:
                f = request.files['csv_file']
                orig_name = f.filename or 'upload.csv'
                saved = _save_upload_to_bankstmts(f, orig_name)
                if saved:
                    csv_path_str = str(saved[0])
                    saved_path_str = str(saved[0])
                else:
                    # fallback: temp file (shouldn't normally happen)
                    tmp = Path(tempfile.mktemp(suffix='.csv', prefix='bank_upload_'))
                    f.seek(0)
                    f.save(str(tmp))
                    csv_path_str = str(tmp)
                propNm_default = request.form.get('propNm_default', 'LLC') or 'LLC'
            else:
                body = request.get_json(force=True) or {}
                csv_path_str = (body.get('csv_path') or '').strip()
                propNm_default = body.get('propNm_default', 'LLC') or 'LLC'

            if not csv_path_str:
                return jsonify({'ok': False, 'error': 'No CSV provided'}), 400

            result = BankAgent(llc).preview(csv_path_str, propNm_default=propNm_default)

            rows_dicts = [_cr_to_dict(cr) for cr in result.rows]
            _store_preview(result._token, rows_dicts, result.stats.as_dict(),
                           result.source, result.ts, propNm_default)

            csv_year = _detect_csv_year(csv_path_str)
            from ledger import setup_paths
            configured_year = getattr(setup_paths, 'YEAR', None)
            # Requisitions follow the previewed CSV's year, not the active fiscal year.
            req_year = int(csv_year or configured_year or 2025)
            req_map = _req_rid_map(req_year, llc)

            return jsonify({
                'ok': True, 'token': result._token, 'rows': rows_dicts,
                'stats': result.stats.as_dict(), 'source': result.source, 'ts': result.ts,
                'csv_year': csv_year, 'configured_year': configured_year,
                'year_warn': bool(csv_year and configured_year and csv_year != configured_year),
                'req_map': req_map, 'req_year': req_year,
                'saved_path': saved_path_str,  # non-null when upload was saved to BankStmts
            })
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500

    @app.route('/api/bank/ingest/commit', methods=['POST'])
    def api_bank_ingest_commit():
        try:
            body = request.get_json(force=True) or {}
            token = (body.get('token') or '').strip()
            edits = body.get('edits', [])  # [{tID, acct, propNm, acctSub}]
            if not token:
                return jsonify({'ok': False, 'error': 'token required'}), 400

            stored = _load_preview(token)
            if stored is None:
                return jsonify({'ok': False, 'error': 'Preview not found (expired or discarded)'}), 404

            llc = _get_llc()
            if llc is None:
                return jsonify({'ok': False, 'error': 'LLC not initialised'}), 500

            from ledger.bankAgent.BankAgent import BankAgent, PreviewResult, PreviewStats

            rows = [_dict_to_cr(d) for d in stored['rows']]
            edit_map = {e['tID']: e for e in edits if e.get('tID')}
            changed_rows = []
            for cr in rows:
                ed = edit_map.get(cr.tID)
                if not ed:
                    continue
                new_acct = ed.get('acct', cr.acct)
                new_propNm = ed.get('propNm', cr.propNm)
                new_sub = ed.get('acctSub', ed.get('acct_sub', cr.acctSub))
                if new_acct != cr.acct or new_propNm != cr.propNm or new_sub != cr.acctSub:
                    cr.acct, cr.propNm, cr.acctSub = new_acct, new_propNm, new_sub
                    if cr.flag != 'DUPLICATE' and cr.vendor_key:
                        changed_rows.append(cr)

            stats_d = stored['stats']
            stats_obj = PreviewStats(**{k: v for k, v in stats_d.items()
                                        if k in PreviewStats.__dataclass_fields__})
            preview_obj = PreviewResult(rows=rows, stats=stats_obj,
                                        source=stored['source'], ts=stored['ts'])
            preview_obj._token = token

            commit_result = BankAgent(llc).commit(preview_obj)

            try:
                es = current_app.config.get('_esession')
                if es and hasattr(es, 'books') and hasattr(es.books, 'invalidate'):
                    es.books.invalidate()
            except Exception:
                pass

            _delete_preview(token)

            return jsonify({
                'ok': True,
                'rows_written': commit_result.rows_written,
                'rows_duplicate': commit_result.rows_duplicate,
                'rows_amount_collision': commit_result.rows_amount_collision,
                'source': commit_result.source, 'ts': commit_result.ts,
                'notif_path': commit_result.notif_path,
            })
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500

    @app.route('/api/bank/ingest/discard', methods=['POST'])
    def api_bank_ingest_discard():
        body = request.get_json(force=True) or {}
        token = (body.get('token') or '').strip()
        if token:
            _delete_preview(token)
        return jsonify({'ok': True})

    # ── Bank Knowledge / Rules (Phase B) ────────────────────────────────────────

    @app.route('/view/bank_kb_rules')
    def view_bank_kb_rules():
        return render_template(
            'bank_kb_rules.html',
            prop_names=_get_prop_names(objects),
            known_accts=_KNOWN_ACCTS,
            txn_types=_TXN_TYPES,
            confidences=_CONFIDENCES,
        )

    @app.route('/api/bank/kb/rules', methods=['GET'])
    def api_bank_kb_get():
        try:
            from ledger.bankAgent.bkVendorKB import BkVendorKB
            return jsonify({'ok': True, 'rules': BkVendorKB().rules()})
        except Exception as err:
            return jsonify({'ok': False, 'error': str(err)}), 500

    @app.route('/api/bank/kb/rules', methods=['POST'])
    def api_bank_kb_save():
        """Replace-all save from the KB editor (operator-authored rule set)."""
        try:
            from ledger.bankAgent.bkVendorKB import BkVendorKB
            body = request.get_json(force=True) or {}
            rules = body.get('rules', [])
            saved = BkVendorKB().set_rules(rules)
            return jsonify({'ok': True, 'rules': saved, 'count': len(saved)})
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500

    # ── Requisitions (Phase C) ──────────────────────────────────────────────────

    def _active_year() -> int:
        from ledger import setup_paths
        return int(getattr(setup_paths, 'YEAR', 2025) or 2025)

    def _missing_reqs(req_map: dict, year: int) -> list[dict]:
        """GL transactions for `year` that need a requisition but have none —
        CIP (InConstruction) rows in llcExpRev/llcAssets without a matching tID."""
        missing = []
        seen = set()
        yr = str(year)
        for key in ('llcExpRev', 'llcAssets'):
            mgr = objects.get(key)
            if not mgr:
                continue
            try:
                for r in mgr.load():
                    if not str(r.get('dt', '')).startswith(yr):
                        continue   # requisition year follows the transaction year
                    acct = str(r.get('acct', '')) + '|' + str(r.get('Ledger', ''))
                    if 'InConstruction' not in acct:
                        continue
                    tID = r.get('tID', '')
                    if not tID or tID in req_map or tID in seen:
                        continue
                    seen.add(tID)
                    raw_acct = r.get('acct', '')
                    ledger   = r.get('Ledger', '')
                    # GL stores both sides; cash-side has acct=Acct.Cash.Bank —
                    # flip to the counter-account so the requisition shows the real account.
                    eff_acct = ledger if raw_acct == 'Acct.Cash.Bank' and ledger else raw_acct
                    missing.append({
                        'tID': tID, 'dt': r.get('dt', ''),
                        'amt': r.get('amt', 0), 'desc': r.get('desc', ''),
                        'propNm': r.get('propNm', ''), 'acct': eff_acct,
                        'purpose': r.get('acctSub', ''),
                        'src': key,
                    })
            except Exception:
                pass
        return missing

    @app.route('/view/requisitions')
    def view_requisitions():
        # year follows the context that opened the view (?year= from preview),
        # defaulting to the active fiscal year.
        try:
            year = int(request.args.get('year', _active_year()))
        except (TypeError, ValueError):
            year = _active_year()
        return render_template(
            'requisitions.html',
            prop_names=_get_prop_names(objects),
            known_accts=_KNOWN_ACCTS,
            configured_year=year,
        )

    @app.route('/api/bank/reqdocs', methods=['GET'])
    def api_bank_reqdocs_get():
        try:
            from ledger.bankAgent.bkReqDocAgent import BkReqDocAgent
            year = int(request.args.get('year', _active_year()))
            rda  = BkReqDocAgent(year, _get_llc())
            docs = rda.all()
            return jsonify({'ok': True, 'year': year, 'docs': docs,
                            'missing': _missing_reqs(rda.as_map(), year)})
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500

    @app.route('/api/bank/reqdocs', methods=['POST'])
    def api_bank_reqdocs_save():
        """Replace-all save from the Requisition editor."""
        try:
            from ledger.bankAgent.bkReqDocAgent import BkReqDocAgent
            body = request.get_json(force=True) or {}
            year = int(body.get('year', _active_year()))
            rda  = BkReqDocAgent(year, _get_llc())
            saved = rda.set_all(body.get('docs', []))
            return jsonify({'ok': True, 'docs': saved, 'count': len(saved),
                            'missing': _missing_reqs(rda.as_map(), year)})
        except Exception as err:
            import traceback
            return jsonify({'ok': False, 'error': str(err),
                            'traceback': traceback.format_exc()}), 500
