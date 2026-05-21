"""
Flask route bindings for the ClosingAid service.
Talks to /api/closing/... endpoints consumed by _closing_aid_dialog.html.
"""
import math
import traceback
from flask import jsonify, request

from ledger.closingAid import ClosingAid, ClosingBalanceError

_aid = ClosingAid()


def _safe_json(obj):
    """Recursively replace float NaN/Inf with None for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def bind_closing_routes(app, objects, sanitize):

    @app.route('/api/closing/classify', methods=['POST'])
    def closing_classify():
        try:
            body          = request.get_json(force=True) or {}
            rows          = body.get('rows', [])
            session_rules = body.get('session_rules', [])
            classified    = _aid.classify(rows, session_rules=session_rules)
            return jsonify({'ok': True, 'classified': _safe_json(classified)})
        except Exception as err:
            tb = traceback.format_exc()
            print(f'[ClosingAid classify ERROR]\n{tb}')   # → PA error log
            return jsonify({'ok': False, 'error': str(err) or repr(err), 'traceback': tb}), 500

    @app.route('/api/closing/balance_sheet', methods=['POST'])
    def closing_balance_sheet():
        try:
            body = request.get_json(force=True) or {}
            classified = body.get('classified', [])
            bs = _aid.toBalanceSheet(classified)
            return jsonify({'ok': True, **_safe_json(bs)})
        except Exception as err:
            return jsonify({'ok': False, 'error': str(err)}), 500

    @app.route('/api/closing/property_basis', methods=['POST'])
    def closing_property_basis():
        try:
            body = request.get_json(force=True) or {}
            classified = body.get('classified', [])
            land_pct   = float(body.get('landPct') or 0)
            basis      = _aid.propertyBasis(classified)
            # Also compute the split preview if landPct given
            if land_pct > 0:
                land_amt = round(basis['gross_basis'] * land_pct / 100.0, 2)
                bldg_amt = round(basis['gross_basis'] - land_amt, 2)
                basis['land_amt']  = land_amt
                basis['bldg_amt']  = bldg_amt
                basis['land_pct']  = land_pct
                basis['bldg_pct']  = round(100.0 - land_pct, 2)
            return jsonify({'ok': True, **_safe_json(basis)})
        except Exception as err:
            return jsonify({'ok': False, 'error': str(err)}), 500

    @app.route('/api/closing/commit', methods=['POST'])
    def closing_commit():
        try:
            body = request.get_json(force=True) or {}
            classified = body.get('classified', [])
            preface    = body.get('preface', {})

            records = _aid.toAssetRecords(classified, preface)

            mgr = objects.get('llcAssets')
            if mgr is None:
                return jsonify({'ok': False, 'error': 'llcAssets object not available'}), 500

            existing = mgr.load() or []
            mgr.save(existing + records)

            return jsonify({
                'ok':           True,
                'committed':    len(records),
                'total_records': len(existing) + len(records),
            })
        except ClosingBalanceError as err:
            return jsonify({'ok': False, 'error': str(err)}), 422
        except Exception as err:
            return jsonify({'ok': False, 'error': str(err)}), 500
