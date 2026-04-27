'''
tests.testIncStmt — three-way Income-Statement reconciliation.

Computes three aggregates for the Income / Expense slice, all keyed by
``(acctMajor, acct, aType).amt.sum()``:

    1. SOURCE : llcExpRev (raw JSON), double-entry-expanded via
                ledgerGeneral.toDoubleEntry.
    2. GL     : ledger.stmtGeneralLedger (include_coa_seed=False so the
                zero-amount COA seed rows don't appear in the key set).
    3. VIEW   : ledger.stmtIncomeStmt rows flattened to the same shape
                (each (acct, acctType) row contributes Debit / Credit
                entries).

Primary invariant (the one the reset-and-simplify refactor guarantees):

    GL == VIEW     — the IS view is a pure re-shaping of the GL.

This is the ``ok`` flag returned and the pass/fail the CLI exits on.

Secondary comparison (SOURCE vs GL) is informational: it surfaces real
cross-DB double-entry drift (e.g. depreciation rows posted to llcAssets
contribute an Acct.Exp.Depreciation Debit to the GL but are absent from
the llcExpRev source set).  Those diffs are real accounting, not a bug.

Usage
-----
    # from the Notebooks/ directory
    python -m tests.testIncStmt

Exits 0 when GL == VIEW, 1 otherwise.
'''

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests._aggHelpers import (           # noqa: E402
    IS_TYPES, agg_records, agg_view_rows, diff_aggs, expand_source, fmt_agg,
)


# ── Source loading ───────────────────────────────────────────────────────

def _load_json_records(llc, obj_name: str) -> List[Dict[str, Any]]:
    fn = os.path.join(llc.TOP, llc.dirAccounting, 'Accts',
                      f"{obj_name}_{llc.objName}.json")
    try:
        with open(fn, 'r') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as err:
        print(f"[testIncStmt] could not load {fn}: {err}")
        return []


def _build_source_agg(llc):
    '''Source: llcExpRev, expanded + aggregated.'''
    src_records = _load_json_records(llc, 'llcExpRev')
    expanded = expand_source(llc, src_records)
    return agg_records(llc, expanded, IS_TYPES)


def _build_gl_agg(llc):
    '''GL: stmtGeneralLedger rows (no COA seeds), aggregated.'''
    try:
        from ledger.stmtGeneralLedger import stmtGeneralLedger
    except ImportError:
        from stmtGeneralLedger import stmtGeneralLedger
    gl = stmtGeneralLedger(llc, view_by='All', include_coa_seed=False)
    return agg_records(llc, list(gl._rows or []), IS_TYPES)


def _build_view_agg(llc):
    '''View: stmtIncomeStmt rows flattened to (acctMajor, acct, aType) agg.'''
    try:
        from ledger.stmtIncomeStmt import stmtIncomeStmt
    except ImportError:
        from stmtIncomeStmt import stmtIncomeStmt
    is_ = stmtIncomeStmt(llc)
    return agg_view_rows(llc, list(is_._rows or []), IS_TYPES)


# ── Public test function ─────────────────────────────────────────────────

def test_incstmt_three_way(llc=None) -> Dict[str, Any]:
    '''Run the three-way reconciliation.  See testBalSh.test_balsh_three_way.'''
    if llc is None:
        try:
            from ledger.LLC import LLC
        except ImportError:
            from LLC import LLC
        llc = LLC('WBGroupLLC')

    src_agg  = _build_source_agg(llc)
    gl_agg   = _build_gl_agg(llc)
    view_agg = _build_view_agg(llc)

    src_vs_gl   = diff_aggs('SRC',  src_agg,  'GL',   gl_agg)
    gl_vs_view  = diff_aggs('GL',   gl_agg,   'VIEW', view_agg)
    src_vs_view = diff_aggs('SRC',  src_agg,  'VIEW', view_agg)

    # Primary invariant: GL == VIEW (the reset-and-simplify refactor
    # makes the IS view a pure re-shaping of the GL).  SRC vs GL drift is
    # reported informationally because cross-DB double-entry can post to
    # IS accounts from the llcAssets / llcPayables / llcReceivables sources.
    ok = not gl_vs_view

    return {
        'ok':          ok,
        'src':         src_agg,
        'gl':          gl_agg,
        'view':        view_agg,
        'src_vs_gl':   src_vs_gl,
        'gl_vs_view':  gl_vs_view,
        'src_vs_view': src_vs_view,
    }


# ── CLI entrypoint ───────────────────────────────────────────────────────

def _report(res: Dict[str, Any]) -> int:
    ok = res['ok']
    print(f"Income Statement reconciliation (GL == VIEW invariant) — "
          f"{'PASS' if ok else 'FAIL'}")
    print(f"  SRC  keys: {len(res['src'])}")
    print(f"  GL   keys: {len(res['gl'])}")
    print(f"  VIEW keys: {len(res['view'])}")

    def _dump(title: str, diffs: List[str]) -> None:
        if not diffs:
            return
        print(f"\n  {title} ({len(diffs)}):")
        for d in diffs:
            print(d)

    _dump("GL vs VIEW (primary invariant)", res['gl_vs_view'])

    src_drift = res['src_vs_gl']
    if src_drift:
        print(f"\n  [INFO] SRC vs GL drift ({len(src_drift)}) — "
              "expected if llcAssets/Payables/Receivables post to IS "
              "accounts (cross-DB double entry, not a bug):")
        for d in src_drift:
            print(d)

    if ok:
        print("\n  ✓ GL and VIEW agree on every (acctMajor, acct, aType).")
        return 0

    print("\nSRC sample:");  print(fmt_agg(res['src']))
    print("GL  sample:");    print(fmt_agg(res['gl']))
    print("VIEW sample:");   print(fmt_agg(res['view']))
    return 1


if __name__ == '__main__':
    sys.exit(_report(test_incstmt_three_way()))
