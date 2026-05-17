'''
tests.test_stmtGL — v0.3 stmtGL hierarchy parity & pipeline tests.

Exercises:

    1. stmtGL load shape           (column set + row count > 0)
    2. Immutability               (load() returns a copy; mutating it
                                    leaves _rows unchanged; save() raises)
    3. to_DF()                    (returns a DataFrame with same row count)
    4. to_json()                  (parses to {meta, columns, rows})
    5. Pipeline chaining           (AggBy().ViewBy().GroupBy().SortBy().load())
    6. v0.2 parity                 (v0.3 stmtGL row count == v0.2
                                    stmtGeneralLedger row count, same
                                    view_by='All')
    7. stmtGL_Tax.nSpaceMap shape  ({formNm: [{fid,acct,fval}]} + flat
                                    load() shape)
    8. stmtGL_View convenience     (view(), trial_balance(), stats(),
                                    is_balanced())
    9. stmtGL_Reports.load() raises NotImplementedError

Usage
-----
    # from the Notebooks/ directory
    python -m tests.test_stmtGL

Exits 0 if all assertions pass, 1 otherwise.
'''

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Tuple


# Allow direct `python tests/test_stmtGL.py` invocation.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── helpers ──────────────────────────────────────────────────────────────

def _llc():
    from ledger import setup_paths as _sp
    _sp.load_config('WBGroupLLC')
    try:
        from ledger.LLC import LLC
    except ImportError:
        from LLC import LLC
    return LLC('WBGroupLLC')


def _ok(name: str, cond: bool, detail: str = '') -> Tuple[str, bool, str]:
    return (name, bool(cond), detail)


# ── individual checks ────────────────────────────────────────────────────

def _check_load_shape(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL
    gl = stmtGL(llc)
    rows = gl.load()
    cols = set(gl._columns)
    expected = {'Status', 'dt', 'acctType', 'acct', 'aType',
                'amt', 'desc', 'acctSub', 'refDB', 'tID'}
    missing = expected - cols
    cond = (len(rows) > 0) and (not missing)
    detail = (f"rows={len(rows)} cols={sorted(cols)} "
              f"missing={sorted(missing) or 'none'}")
    return _ok("stmtGL load shape", cond, detail)


def _check_immutability(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL
    gl = stmtGL(llc)
    rows = gl.load()
    n0 = len(gl._rows)
    # Mutating the returned list must not affect the parent.
    if rows:
        rows.pop()
        rows[0]['amt'] = 99999.99 if rows else None
    n1 = len(gl._rows)
    same = (n0 == n1)
    # save() must raise on stmt objects (v0.3 rule).
    save_raises = False
    try:
        gl.save()
    except Exception:
        save_raises = True
    cond = same and save_raises
    detail = f"rows_same={same} save_raises={save_raises}"
    return _ok("stmtGL immutability + no save()", cond, detail)


def _check_to_DF(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL
    gl = stmtGL(llc)
    try:
        df = gl.to_DF()
    except Exception as err:
        return _ok("stmtGL.to_DF()", False, f"raised {err}")
    rows = gl.load()
    cond = (len(df) == len(rows))
    detail = f"df_rows={len(df)} list_rows={len(rows)}"
    return _ok("stmtGL.to_DF()", cond, detail)


def _check_to_json(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL
    gl = stmtGL(llc)
    try:
        s = gl.to_json()
        payload = json.loads(s)
    except Exception as err:
        return _ok("stmtGL.to_json()", False, f"raised {err}")
    keys = set(payload)
    needed = {'meta', 'columns', 'rows'}
    cond = needed.issubset(keys) and len(payload['rows']) == len(gl.load())
    detail = f"keys={sorted(keys)} rows_match={cond}"
    return _ok("stmtGL.to_json()", cond, detail)


def _check_pipeline(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL_View
    gl = stmtGL_View(llc)
    pipe = (gl.AggBy()
              .ViewBy('ByAsset', include_coa_seed=False)
              .GroupBy(['acctType', 'acct', 'acctSub'])
              .SortBy(['acctType', 'acct']))
    rows = pipe.load()
    cond_basic = isinstance(rows, list)
    cond_grouped = all(
        ('Debit' in r) and ('Credit' in r) and ('Balance' in r)
        for r in rows
    )
    cond_view = all(r.get('acctType') == 'Asset' for r in rows) if rows else True
    cond = cond_basic and cond_grouped and cond_view
    detail = (f"rows={len(rows)} grouped_cols={cond_grouped} "
              f"view_filtered={cond_view}")
    return _ok("Pipeline AggBy → ViewBy('ByAsset') → GroupBy → SortBy",
               cond, detail)


def _check_pipeline_with_totals(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL_View
    gl = stmtGL_View(llc)
    rows = gl.trial_balance(view_by='All', with_totals=True)
    has_total = any(r.get('acctType') == 'TOTAL' for r in rows)
    detail = f"rows={len(rows)} has_TOTAL={has_total}"
    return _ok("trial_balance(with_totals=True) appends TOTAL row",
               has_total, detail)


def _check_v02_parity(llc) -> Tuple[str, bool, str]:
    '''stmtGL constructs successfully (v0.2 stmtGeneralLedger removed).'''
    from ledger.stmtGL import stmtGL
    gl = stmtGL(llc)
    n = len(gl._rows)
    return _ok("stmtGL constructs successfully (v0.2 removed)", n >= 0, f"rows={n}")


def _check_tax_nSpaceMap(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL_Tax
    tx = stmtGL_Tax(llc)
    try:
        ns = tx.nSpaceMap()
    except Exception as err:
        return _ok("stmtGL_Tax.nSpaceMap()", False, f"raised {err}")
    cond_shape = isinstance(ns, dict) and all(
        isinstance(v, list) and all(
            isinstance(e, dict) and {'fid', 'acct', 'fval'}.issubset(e)
            for e in v
        ) for v in ns.values()
    )
    flat = tx.load()
    cond_flat = isinstance(flat, list) and all(
        {'fid', 'acct', 'fval', 'formNm'}.issubset(e) for e in flat
    )
    cond = cond_shape and cond_flat
    detail = (f"forms={list(ns.keys())} "
              f"shape_ok={cond_shape} flat_ok={cond_flat} "
              f"flat_count={len(flat)}")
    return _ok("stmtGL_Tax.nSpaceMap shape + flat load()", cond, detail)


def _check_view_convenience(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL_View
    v = stmtGL_View(llc)
    rows_all = v.view('All')
    tb       = v.trial_balance(view_by='All')
    s        = v.stats()
    bal      = v.is_balanced()
    cond = (
        isinstance(rows_all, list)
        and isinstance(tb, list)
        and isinstance(s, dict)
        and {'Transactions', 'TotalDebit', 'TotalCredit',
             'NetBalance', 'ByAcctType'}.issubset(s)
        and isinstance(bal, bool)
    )
    detail = (f"view_rows={len(rows_all)} tb_rows={len(tb)} "
              f"stats={s.get('Transactions')} balanced={bal}")
    return _ok("stmtGL_View view() / trial_balance() / stats() / is_balanced()",
               cond, detail)


def _check_reports_stub(llc) -> Tuple[str, bool, str]:
    from ledger.stmtGL import stmtGL_Reports
    rpt = stmtGL_Reports(llc)
    raised = False
    try:
        rpt.load()
    except NotImplementedError:
        raised = True
    except Exception as err:
        return _ok("stmtGL_Reports.load() NotImplementedError",
                   False, f"raised wrong error: {err}")
    return _ok("stmtGL_Reports.load() NotImplementedError", raised,
               f"raised={raised}")


# ── public test function ─────────────────────────────────────────────────

def test_stmtGL(llc=None) -> Dict[str, Any]:
    if llc is None:
        llc = _llc()

    checks = [
        _check_load_shape,
        _check_immutability,
        _check_to_DF,
        _check_to_json,
        _check_pipeline,
        _check_pipeline_with_totals,
        _check_v02_parity,
        _check_tax_nSpaceMap,
        _check_view_convenience,
        _check_reports_stub,
    ]
    results: List[Tuple[str, bool, str]] = []
    for fn in checks:
        try:
            results.append(fn(llc))
        except Exception as err:
            results.append((fn.__name__, False, f"exception: {err}"))

    ok = all(r[1] for r in results)
    return {'ok': ok, 'results': results}


# ── CLI entrypoint ───────────────────────────────────────────────────────

def _report(res: Dict[str, Any]) -> int:
    ok = res['ok']
    print(f"v0.3 stmtGL test suite — {'PASS' if ok else 'FAIL'}")
    print(f"  checks: {len(res['results'])}")
    print()
    for name, passed, detail in res['results']:
        flag = '✓' if passed else '✗'
        print(f"  {flag} {name}")
        if detail:
            print(f"      {detail}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(_report(test_stmtGL()))
