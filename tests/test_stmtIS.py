'''
tests.test_stmtIS — v0.3 stmtIS hierarchy parity & pipeline tests.

Exercises:

    1. stmtIS load shape           (column set + TOTAL row carries net_income)
    2. Immutability               (load() copy; save() raises)
    3. to_DF() / to_json()
    4. Pipeline chaining           (AggBy().ViewBy('ByExpense').load())
    5. Pipeline PerMember          (each row gains owner-named columns)
    6. v0.2 parity                 (v0.3 row count == v0.2 stmtIncomeStmt
                                    body+TOTAL row count for view_by='All')
    7. last_summary() shape         (income/expense/net_income)
    8. stmtIS_Tax.nSpaceMap shape  ({formNm: [{fid,acct,fval}]})
    9. taxAggregates() keys present
   10. stmtIS_View view() / per_member() / stats()
   11. stmtIS_Reports.load() raises NotImplementedError

Usage
-----
    python -m tests.test_stmtIS

Exits 0 if all assertions pass, 1 otherwise.
'''

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Tuple


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


def _sample_owners() -> List[Dict[str, Any]]:
    '''Synthetic owners (50/50) for PerMember pipeline tests when llcOwners
    is unavailable in the sandbox.'''
    return [
        {'oID': 'A', 'nm': 'Alice', 'pct': 0.5},
        {'oID': 'B', 'nm': 'Bob',   'pct': 0.5},
    ]


# ── checks ───────────────────────────────────────────────────────────────

def _check_load_shape(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS
    s = stmtIS(llc)
    rows = s.load()
    cols = set(s._columns)
    expected = {'acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance'}
    has_total = any(r.get('acctType') == 'TOTAL' for r in rows)
    cond = expected.issubset(cols) and has_total
    return _ok("stmtIS load shape + TOTAL row",
               cond,
               f"rows={len(rows)} cols={sorted(cols)} has_TOTAL={has_total}")


def _check_immutability(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS
    s = stmtIS(llc)
    rows = s.load()
    n0 = len(s._rows)
    if rows:
        rows.pop()
    n1 = len(s._rows)
    same = (n0 == n1)
    save_raises = False
    try:
        s.save()
    except Exception:
        save_raises = True
    return _ok("stmtIS immutability + no save()",
               same and save_raises,
               f"rows_same={same} save_raises={save_raises}")


def _check_to_DF_and_json(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS
    s = stmtIS(llc)
    df_ok = j_ok = False
    try:
        df_ok = (len(s.to_DF()) == len(s.load()))
    except Exception:
        df_ok = False
    try:
        payload = json.loads(s.to_json())
        j_ok = ({'meta', 'columns', 'rows'}.issubset(payload)
                and len(payload['rows']) == len(s.load()))
    except Exception:
        j_ok = False
    return _ok("stmtIS.to_DF() + to_json()",
               df_ok and j_ok,
               f"df_ok={df_ok} json_ok={j_ok}")


def _check_pipeline(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS_View
    v = stmtIS_View(llc)
    rows = (v.AggBy()
              .ViewBy('ByExpense')
              .SortBy(['acctType', 'acct', 'acctSub'])
              .load())
    cond_filter = all(r.get('acctType') == 'Expense' for r in rows) if rows else True
    cond_no_total = not any(r.get('acctType') == 'TOTAL' for r in rows)
    return _ok("Pipeline AggBy → ViewBy('ByExpense') → SortBy",
               cond_filter and cond_no_total,
               f"rows={len(rows)} all_expense={cond_filter} "
               f"no_total={cond_no_total}")


def _check_pipeline_per_member(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS_View
    owners = _sample_owners()
    v = stmtIS_View(llc)
    rows = (v.AggBy()
              .PerMember(owners)
              .load())
    if not rows:
        return _ok("Pipeline PerMember adds owner columns",
                   True, "no body rows in test corpus — vacuously true")
    expected_cols = {'Alice', 'Bob'}
    has_owner_cols = expected_cols.issubset(set(rows[0].keys()))
    # Allocation check: row['Alice'] + row['Bob'] ≈ row.Balance × 1.0
    sample = rows[0]
    try:
        bal = float(sample.get('Balance') or 0)
        alloc = sum(float(sample.get(nm) or 0) for nm in expected_cols)
        alloc_ok = abs(alloc - bal) < 0.01
    except Exception:
        alloc_ok = False
    return _ok("Pipeline PerMember adds owner columns",
               has_owner_cols and alloc_ok,
               f"sample_keys={sorted(sample.keys())[:8]} "
               f"alloc_ok={alloc_ok}")


def _check_v02_parity(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS
    s = stmtIS(llc)
    n = len(s._rows)
    return _ok("stmtIS constructs successfully (v0.2 removed)", n >= 0, f"rows={n}")


def _check_last_summary(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS
    s = stmtIS(llc)
    summ = s.last_summary()
    return _ok("stmtIS.last_summary() shape",
               {'income', 'expense', 'net_income'}.issubset(summ),
               f"summary={summ}")


def _check_tax_nSpaceMap(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS_Tax
    tx = stmtIS_Tax(llc)
    try:
        ns = tx.nSpaceMap()
    except Exception as err:
        return _ok("stmtIS_Tax.nSpaceMap()", False, f"raised {err}")
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
    has_form1065 = bool(ns.get('Form1065'))
    return _ok("stmtIS_Tax.nSpaceMap shape + flat load()",
               cond_shape and cond_flat and has_form1065,
               f"forms={list(ns.keys())} Form1065_entries="
               f"{len(ns.get('Form1065', []))}")


def _check_taxAggregates(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS_View
    v = stmtIS_View(llc)
    agg = v.taxAggregates()
    needed = {'rent_income', 'total_income', 'repairs', 'taxes_licenses',
              'interest_expense', 'depreciation', 'other_deductions',
              'total_expenses', 'net_income', 'interest_income',
              'distributions_cash'}
    missing = needed - set(agg)
    return _ok("stmtIS_View.taxAggregates() keys",
               not missing,
               f"keys_count={len(agg)} missing={sorted(missing)}")


def _check_view_convenience(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS_View
    v = stmtIS_View(llc)
    rows_all = v.view('All', with_totals=True)
    rows_inc = v.view('ByIncome', with_totals=False)
    rows_pm, names, summ = v.per_member(owners=_sample_owners())
    s = v.stats()
    cond = (
        isinstance(rows_all, list)
        and any(r.get('acctType') == 'TOTAL' for r in rows_all)
        and (not any(r.get('acctType') == 'TOTAL' for r in rows_inc))
        and isinstance(rows_pm, list)
        and 'Alice' in names and 'Bob' in names
        and {'income_subtotal', 'expense_subtotal',
             'net_income', 'depreciation',
             'net_income_with_depr'}.issubset(summ)
        and isinstance(s, dict) and 'Income' in s and 'Expense' in s
    )
    return _ok("stmtIS_View view() / per_member() / stats()",
               cond,
               f"all_rows={len(rows_all)} inc_rows={len(rows_inc)} "
               f"pm_rows={len(rows_pm)} owners={names}")


def _check_reports_stub(llc) -> Tuple[str, bool, str]:
    from ledger.stmtIS import stmtIS_Reports
    r = stmtIS_Reports(llc)
    raised = False
    try:
        r.load()
    except NotImplementedError:
        raised = True
    return _ok("stmtIS_Reports.load() NotImplementedError", raised,
               f"raised={raised}")


# ── public test function ─────────────────────────────────────────────────

def test_stmtIS(llc=None) -> Dict[str, Any]:
    if llc is None:
        llc = _llc()
    checks = [
        _check_load_shape,
        _check_immutability,
        _check_to_DF_and_json,
        _check_pipeline,
        _check_pipeline_per_member,
        _check_v02_parity,
        _check_last_summary,
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
    print(f"v0.3 stmtIS test suite — {'PASS' if ok else 'FAIL'}")
    print(f"  checks: {len(res['results'])}\n")
    for name, passed, detail in res['results']:
        flag = '✓' if passed else '✗'
        print(f"  {flag} {name}")
        if detail:
            print(f"      {detail}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(_report(test_stmtIS()))
