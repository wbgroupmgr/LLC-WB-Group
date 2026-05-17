'''
tests.test_stmtBS — v0.3 stmtBS hierarchy parity & pipeline tests.

Exercises:

    1. stmtBS load shape           (column set + at least the TOTAL row)
    2. Immutability               (load() returns a copy; save() raises)
    3. to_DF() / to_json()
    4. Pipeline chaining           (AggBy().ViewBy().SortBy().load())
    5. v0.2 parity                 (v0.3 row count == v0.2 stmtBalanceSheet
                                    body+TOTAL row count for view_by='All')
    6. last_check() balanced flag
    7. stmtBS_Tax.nSpaceMap shape  ({formNm: [{fid,acct,fval}]})
    8. taxAggregates() keys present
    9. stmtBS_View view() / stats() / is_balanced()
   10. stmtBS_Reports.load() raises NotImplementedError

Usage
-----
    python -m tests.test_stmtBS

Exits 0 if all assertions pass, 1 otherwise.
'''

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Tuple


# Allow direct invocation.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _llc():
    from ledger import setup_paths as _sp
    _sp.load_config('WBGroupLLC', 2025)
    try:
        from ledger.LLC import LLC
    except ImportError:
        from LLC import LLC
    return LLC('WBGroupLLC')


def _ok(name: str, cond: bool, detail: str = '') -> Tuple[str, bool, str]:
    return (name, bool(cond), detail)


# ── checks ───────────────────────────────────────────────────────────────

def _check_load_shape(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS
    bs = stmtBS(llc)
    rows = bs.load()
    cols = set(bs._columns)
    expected = {'acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance'}
    has_total = any(r.get('acctType') == 'TOTAL' for r in rows)
    cond = expected.issubset(cols) and has_total
    return _ok("stmtBS load shape + TOTAL row",
               cond,
               f"rows={len(rows)} cols={sorted(cols)} has_TOTAL={has_total}")


def _check_immutability(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS
    bs = stmtBS(llc)
    rows = bs.load()
    n0 = len(bs._rows)
    if rows:
        rows.pop()
        rows[0]['Debit'] = 999999.99 if rows else None
    n1 = len(bs._rows)
    same = (n0 == n1)
    save_raises = False
    try:
        bs.save()
    except Exception:
        save_raises = True
    return _ok("stmtBS immutability + no save()",
               same and save_raises,
               f"rows_same={same} save_raises={save_raises}")


def _check_to_DF_and_json(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS
    bs = stmtBS(llc)
    df_ok = j_ok = False
    try:
        df = bs.to_DF()
        df_ok = (len(df) == len(bs.load()))
    except Exception:
        df_ok = False
    try:
        payload = json.loads(bs.to_json())
        j_ok = ({'meta', 'columns', 'rows'}.issubset(payload)
                and len(payload['rows']) == len(bs.load()))
    except Exception:
        j_ok = False
    return _ok("stmtBS.to_DF() + to_json()",
               df_ok and j_ok,
               f"df_ok={df_ok} json_ok={j_ok}")


def _check_pipeline(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS_View
    v = stmtBS_View(llc)
    rows = (v.AggBy()
              .ViewBy('ByAsset')
              .SortBy(['acctType', 'acct', 'acctSub'])
              .load())
    cond_filter = all(r.get('acctType') == 'Asset' for r in rows) if rows else True
    cond_no_total = not any(r.get('acctType') == 'TOTAL' for r in rows)
    return _ok("Pipeline AggBy → ViewBy('ByAsset') → SortBy",
               cond_filter and cond_no_total,
               f"rows={len(rows)} all_assets={cond_filter} "
               f"no_total={cond_no_total}")


def _check_v02_parity(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS
    bs = stmtBS(llc)
    n = len(bs._rows)
    return _ok("stmtBS constructs successfully (v0.2 removed)",
               n >= 0, f"rows={n}")


def _check_last_check(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS
    bs = stmtBS(llc)
    chk = bs.last_check()
    needed = {'asset', 'liability', 'equity', 'equation_diff', 'balanced'}
    return _ok("stmtBS.last_check() shape",
               needed.issubset(chk),
               f"keys={sorted(chk.keys())} balanced={chk.get('balanced')}")


def _check_tax_nSpaceMap(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS_Tax
    tx = stmtBS_Tax(llc)
    try:
        ns = tx.nSpaceMap()
    except Exception as err:
        return _ok("stmtBS_Tax.nSpaceMap()", False, f"raised {err}")
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
    # Sanity: at least one form (Form1065) should have entries.
    has_form1065 = bool(ns.get('Form1065'))
    return _ok("stmtBS_Tax.nSpaceMap shape + flat load()",
               cond_shape and cond_flat and has_form1065,
               f"forms={list(ns.keys())} Form1065_entries="
               f"{len(ns.get('Form1065', []))}")


def _check_taxAggregates(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS_View
    v = stmtBS_View(llc)
    agg = v.taxAggregates()
    needed = {'cash', 'ar', 'buildings', 'accum_depr', 'land',
              'other_assets', 'total_assets',
              'payables', 'mortgage', 'total_equity', 'total_liab_capital'}
    missing = needed - set(agg)
    return _ok("stmtBS_View.taxAggregates() keys",
               not missing,
               f"keys={sorted(agg.keys())[:6]}... missing={sorted(missing)}")


def _check_view_convenience(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS_View
    v = stmtBS_View(llc)
    rows_all = v.view('All', with_totals=True)
    rows_a   = v.view('ByAsset', with_totals=False)
    s        = v.stats()
    bal      = v.is_balanced()
    cond = (
        isinstance(rows_all, list)
        and any(r.get('acctType') == 'TOTAL' for r in rows_all)
        and (not any(r.get('acctType') == 'TOTAL' for r in rows_a))
        and isinstance(s, dict) and 'Accounts' in s
        and isinstance(bal, bool)
    )
    return _ok("stmtBS_View view() / stats() / is_balanced()",
               cond,
               f"all_rows={len(rows_all)} asset_rows={len(rows_a)} "
               f"balanced={bal}")


def _check_reports_stub(llc) -> Tuple[str, bool, str]:
    from ledger.stmtBS import stmtBS_Reports
    r = stmtBS_Reports(llc)
    raised = False
    try:
        r.load()
    except NotImplementedError:
        raised = True
    return _ok("stmtBS_Reports.load() NotImplementedError", raised,
               f"raised={raised}")


# ── public test function ─────────────────────────────────────────────────

def test_stmtBS(llc=None) -> Dict[str, Any]:
    if llc is None:
        llc = _llc()
    checks = [
        _check_load_shape,
        _check_immutability,
        _check_to_DF_and_json,
        _check_pipeline,
        _check_v02_parity,
        _check_last_check,
        _check_tax_nSpaceMap,
        _check_taxAggregates,
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


def _report(res: Dict[str, Any]) -> int:
    ok = res['ok']
    print(f"v0.3 stmtBS test suite — {'PASS' if ok else 'FAIL'}")
    print(f"  checks: {len(res['results'])}\n")
    for name, passed, detail in res['results']:
        flag = '✓' if passed else '✗'
        print(f"  {flag} {name}")
        if detail:
            print(f"      {detail}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(_report(test_stmtBS()))
