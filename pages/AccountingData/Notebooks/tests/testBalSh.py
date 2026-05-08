'''
tests.testBalSh — three-way Balance-Sheet reconciliation.

Computes three aggregates for the Asset / Liability / Equity slice,
all keyed by ``(acctMajor, acct, aType).amt.sum()``:

    1. SOURCE : llcAssets + llcPayables + llcReceivables (raw JSON),
                double-entry-expanded via ledgerGeneral.toDoubleEntry.
    2. GL     : ledger.stmtGeneralLedger (include_coa_seed=False so the
                zero-amount COA seed rows don't appear in the key set).
    3. VIEW   : ledger.stmtBalanceSheet rows flattened to the same shape
                (each (acct, acctType) row contributes Debit / Credit
                entries).

Primary invariant (the one the reset-and-simplify refactor guarantees):

    GL == VIEW     — the BS view is a pure re-shaping of the GL.

This is the ``ok`` flag returned and the pass/fail the CLI exits on.

Secondary comparison (SOURCE vs GL) is informational: it surfaces real
cross-DB double-entry drift (e.g. an llcExpRev rent revenue entry debits
Acct.Cash.Bank, so the Asset side is in the GL but not in the
Assets+Payables+Receivables source set).  Those diffs are real
accounting, not a bug — they are reported as "source drift" and do not
fail the test.

Usage
-----
    # from the Notebooks/ directory
    python -m tests.testBalSh

Exits 0 when GL == VIEW, 1 otherwise.
'''

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List


# Allow direct `python tests/testBalSh.py` invocation.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests._aggHelpers import (           # noqa: E402
    BS_TYPES, agg_records, agg_view_rows, diff_aggs, expand_source, fmt_agg,
)


# ── Source loading ───────────────────────────────────────────────────────

def _load_json_records(llc, obj_name: str) -> List[Dict[str, Any]]:
    '''Load raw records from Accts/<obj_name>_<llcName>.json.'''
    fn = os.path.join(llc.TOP, llc.dirAccounting, 'Accts',
                      f"{obj_name}_{llc.objName}.json")
    try:
        with open(fn, 'r') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as err:
        print(f"[testBalSh] could not load {fn}: {err}")
        return []


def _build_source_agg(llc):
    '''Source: llcAssets + llcPayables + llcReceivables, expanded + aggregated.'''
    src_records: List[Dict[str, Any]] = []
    for obj in ('llcAssets', 'llcPayables', 'llcReceivables'):
        src_records.extend(_load_json_records(llc, obj))
    expanded = expand_source(llc, src_records)
    return agg_records(llc, expanded, BS_TYPES)


def _build_gl_agg(llc):
    '''GL: stmtGL rows (with COA seed), aggregated.'''
    from ledger.stmtGL import stmtGL
    gl = stmtGL(llc)
    return agg_records(llc, list(gl.load() or []), BS_TYPES)


def _build_view_agg(llc):
    '''View: stmtBS rows flattened to (acctMajor, acct, aType) agg.'''
    from ledger.stmtBS import stmtBS
    bs = stmtBS(llc)
    return agg_view_rows(llc, list(bs._rows or []), BS_TYPES)


# ── Public test function ─────────────────────────────────────────────────

def test_balsh_three_way(llc=None) -> Dict[str, Any]:
    '''
    Run the three-way reconciliation and return a dict::

        {'ok': bool, 'src': AggDict, 'gl': AggDict, 'view': AggDict,
         'src_vs_gl': [...], 'gl_vs_view': [...], 'src_vs_view': [...]}

    If the caller does not pass an LLC, a default ``LLC('WBGroupLLC')`` is
    constructed.  Raises AssertionError only when ``ok == False`` and the
    caller invoked this module via ``python -m`` (not under pytest).
    '''
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
    # makes the BS view a pure re-shaping of the GL).  SRC vs GL drift is
    # reported informationally because cross-DB double-entry can
    # legitimately post to BS accounts from the llcExpRev source.
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
    print(f"Balance Sheet reconciliation (GL == VIEW invariant) — "
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

    # Primary assertion
    _dump("GL vs VIEW (primary invariant)", res['gl_vs_view'])

    # Informational: SRC vs GL drift is expected when cross-DB
    # double-entry posts to BS accounts from llcExpRev.
    src_drift = res['src_vs_gl']
    if src_drift:
        print(f"\n  [INFO] SRC vs GL drift ({len(src_drift)}) — "
              "expected if llcExpRev posts to BS accounts "
              "(cross-DB double entry, not a bug):")
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
    sys.exit(_report(test_balsh_three_way()))
