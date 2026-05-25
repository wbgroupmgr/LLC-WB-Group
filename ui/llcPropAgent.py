"""
Flask route bindings for the PropAgent service.
Talks to /api/propAgent/... endpoints consumed by _prop_agent_dialog.html.
"""
import math
import os
import traceback
from flask import jsonify, request

from ledger.propAgent import PropAgent, PropAgentBalanceError
from ui.llcPdfReport import generate_purchase_report

_aid = PropAgent()


def _safe_json(obj):
    """Recursively replace float NaN/Inf with None for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def bind_propAgent_routes(app, objects, sanitize):

    @app.route('/api/propAgent/classify', methods=['POST'])
    def closing_classify():
        try:
            body          = request.get_json(force=True) or {}
            rows          = body.get('rows', [])
            session_rules = body.get('session_rules', [])
            classified    = _aid.classify(rows, session_rules=session_rules)
            return jsonify({'ok': True, 'classified': _safe_json(classified)})
        except Exception as err:
            tb = traceback.format_exc()
            print(f'[PropAgent classify ERROR]\n{tb}')   # → PA error log
            return jsonify({'ok': False, 'error': str(err) or repr(err), 'traceback': tb}), 500

    @app.route('/api/propAgent/balance_sheet', methods=['POST'])
    def closing_balance_sheet():
        try:
            body = request.get_json(force=True) or {}
            classified = body.get('classified', [])
            bs = _aid.toBalanceSheet(classified)
            return jsonify({'ok': True, **_safe_json(bs)})
        except Exception as err:
            return jsonify({'ok': False, 'error': str(err)}), 500

    @app.route('/api/propAgent/property_basis', methods=['POST'])
    def closing_property_basis():
        try:
            body         = request.get_json(force=True) or {}
            classified   = body.get('classified', [])
            land_pct     = float(body.get('landPct') or 0)
            preface      = body.get('preface', {})
            closing_date = body.get('closingDate', '') or (preface.get('closingDate', ''))
            basis        = _aid.propertyBasis(classified)
            if land_pct > 0:
                land_amt = round(basis['gross_basis'] * land_pct / 100.0, 2)
                bldg_amt = round(basis['gross_basis'] - land_amt, 2)
                basis['land_amt']  = land_amt
                basis['bldg_amt']  = bldg_amt
                basis['land_pct']  = land_pct
                basis['bldg_pct']  = round(100.0 - land_pct, 2)
            # Depreciation estimate (MACRS mid-month) — uses building portion
            bldg_for_depr = basis.get('bldg_amt', basis['gross_basis'])
            if closing_date and bldg_for_depr > 0:
                basis.update(_aid.depreciationEstimate(bldg_for_depr, closing_date))
            # Return actual committed records (post land-split) so preview matches reality
            if preface:
                basis['records'] = _aid.toAssetRecords(classified, preface)
            return jsonify({'ok': True, **_safe_json(basis)})
        except Exception as err:
            return jsonify({'ok': False, 'error': str(err)}), 500

    @app.route('/api/propAgent/balance_assist', methods=['POST'])
    def closing_balance_assist():
        try:
            body         = request.get_json(force=True) or {}
            classified   = body.get('classified', [])
            closing_date = body.get('closingDate', '')
            # Load all GL sources for funding context
            gl_rows = []
            for key in ('llcExpRev', 'llcAssets', 'llcPayables', 'llcReceivables'):
                mgr = objects.get(key)
                if mgr:
                    try:
                        gl_rows.extend(mgr.load() or [])
                    except Exception:
                        pass
            result = _aid.balance_assist(classified, closing_date, gl_rows)
            return jsonify({'ok': True, **_safe_json(result)})
        except Exception as err:
            tb = traceback.format_exc()
            print(f'[PropAgent balance_assist ERROR]\n{tb}')
            return jsonify({'ok': False, 'error': str(err) or repr(err)}), 500

    @app.route('/api/propAgent/check_existing', methods=['POST'])
    def closing_check_existing():
        try:
            body         = request.get_json(force=True) or {}
            classified   = body.get('classified', [])
            closing_date = body.get('closingDate', '')
            gl_rows = []
            for key in ('llcExpRev', 'llcAssets', 'llcPayables', 'llcReceivables'):
                mgr = objects.get(key)
                if mgr:
                    try:
                        gl_rows.extend(mgr.load() or [])
                    except Exception:
                        pass
            matches = _aid.check_existing(classified, closing_date, gl_rows)
            return jsonify({'ok': True, 'matches': _safe_json(matches)})
        except Exception as err:
            tb = traceback.format_exc()
            print(f'[PropAgent check_existing ERROR]\n{tb}')
            return jsonify({'ok': False, 'error': str(err) or repr(err)}), 500

    @app.route('/api/propAgent/commit', methods=['POST'])
    def closing_commit():
        try:
            body          = request.get_json(force=True) or {}
            classified    = body.get('classified', [])
            preface       = body.get('preface', {})
            override_tids = set(body.get('override_tids', []))  # existing tIDs to replace

            records = _aid.toAssetRecords(classified, preface)
            # Append optional scheduled YE depreciation record
            depr_record = body.get('depr_record')
            if depr_record and isinstance(depr_record, dict) and depr_record.get('tID'):
                records.append(depr_record)

            mgr = objects.get('llcAssets')
            if mgr is None:
                return jsonify({'ok': False, 'error': 'llcAssets object not available'}), 500

            existing = mgr.load() or []
            # Remove overridden records; dup-mode records stay alongside new ones
            filtered = [r for r in existing if r.get('tID') not in override_tids]
            mgr.save(filtered + records)

            return jsonify({
                'ok':            True,
                'committed':     len(records),
                'replaced':      len(existing) - len(filtered),
                'total_records': len(filtered) + len(records),
            })
        except PropAgentBalanceError as err:
            return jsonify({'ok': False, 'error': str(err)}), 422
        except Exception as err:
            return jsonify({'ok': False, 'error': str(err)}), 500

    @app.route('/api/propAgent/pdf_report', methods=['POST'])
    def closing_pdf_report():
        try:
            body        = request.get_json(force=True) or {}
            records     = body.get('records', [])       # post-split records (_records)
            preface     = body.get('preface', {})
            basis_data  = body.get('basis_data', {})
            depr_record = body.get('depr_record') or None
            output_dir  = body.get('output_dir', '').strip()

            if not output_dir:
                return jsonify({'ok': False, 'error': 'output_dir is required'}), 400
            if not os.path.isabs(output_dir):
                return jsonify({'ok': False, 'error': 'output_dir must be an absolute path'}), 400

            pdf_path = generate_purchase_report(records, preface, basis_data, depr_record, output_dir)
            return jsonify({'ok': True, 'pdf_path': pdf_path})
        except Exception as err:
            tb = traceback.format_exc()
            print(f'[PropAgent pdf_report ERROR]\n{tb}')
            return jsonify({'ok': False, 'error': str(err) or repr(err)}), 500
