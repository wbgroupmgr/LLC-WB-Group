'''
tests/_aggHelpers — shared aggregation helpers for the three-way
equality tests (testBalSh, testIncStmt).

All aggregates are keyed by (acctMajor, acct, aType) → amt.  This is the
canonical "double-entry column sum" key the user spelled out in the
reset-and-simplify brief:

    [acctMajor, acct, aType].amt.sum()

where acctMajor is the account classification returned by
ChartOfAccounts._Type(acct) — one of {'Asset','Liability','Equity',
'Income','Expense','Appreciation'}.
'''

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

AggKey   = Tuple[str, str, str]       # (acctMajor, acct, aType)
AggDict  = Dict[AggKey, float]

BS_TYPES = {'Asset', 'Liability', 'Equity'}
IS_TYPES = {'Income', 'Expense'}

# Epsilon for float equality — balances round to 2 dp so 1e-4 is far
# below any meaningful difference.
EPS = 1e-4


# ── Source double-entry expansion ────────────────────────────────────────

def expand_source(llc, source_records: List[Dict[str, Any]]
                  ) -> List[Dict[str, Any]]:
    '''
    Double-entry-expand a list of source records (llcAssets-style:
    one row per transaction with `aType`/`Ledger`/`acct`) into GL-shaped
    records (one row per side of the double entry).  Delegates to
    ``ledger.ledgerGeneral.toDoubleEntry`` so this matches production.
    '''
    try:
        from ledger.ledgerGeneral import ledgerGeneral
    except ImportError:
        from ledgerGeneral import ledgerGeneral
    return ledgerGeneral(llc).toDoubleEntry(source_records or []) or []


# ── Aggregation ──────────────────────────────────────────────────────────

def _coa_type(llc, acct: str) -> str:
    try:
        return llc.coa._Type(acct)
    except Exception:
        return ''


def agg_records(llc,
                records: List[Dict[str, Any]],
                keep_types: set,
                ) -> AggDict:
    '''
    Aggregate GL-shaped records (with `acct`, `aType`, `amt`) into
    (acctMajor, acct, aType) → amt-sum.  Drops rows whose acctMajor is
    not in ``keep_types`` and drops zero-valued buckets so the result
    compares cleanly to peer aggregates that lack COA-seed rows.
    '''
    bucket: Dict[AggKey, float] = defaultdict(float)
    for r in records or []:
        acct = r.get('acct', '') or ''
        # acctType on a GL record is already set during double-entry
        # expansion; fall back to COA classifier if not.
        at = r.get('acctType') or _coa_type(llc, acct)
        if at not in keep_types:
            continue
        aType = str(r.get('aType', '') or '')
        try:
            amt = float(r.get('amt', 0) or 0)
        except (TypeError, ValueError):
            amt = 0.0
        bucket[(at, acct, aType)] += amt

    return {k: round(v, 2) for k, v in bucket.items() if abs(v) >= EPS}


def agg_view_rows(llc,
                  view_rows: List[Dict[str, Any]],
                  keep_types: set,
                  ) -> AggDict:
    '''
    Aggregate BS/IS view rows (which carry Debit / Credit columns) into
    (acctMajor, acct, aType).amt-sum shape so they can be compared to
    source / GL aggregates.
    '''
    bucket: Dict[AggKey, float] = defaultdict(float)
    for r in view_rows or []:
        at = r.get('acctType', '') or ''
        if at == 'TOTAL' or at not in keep_types:
            continue
        acct = r.get('acct', '') or ''
        try:
            d = float(r.get('Debit',  0) or 0)
        except (TypeError, ValueError):
            d = 0.0
        try:
            c = float(r.get('Credit', 0) or 0)
        except (TypeError, ValueError):
            c = 0.0
        if abs(d) >= EPS:
            bucket[(at, acct, 'Debit')]  += d
        if abs(c) >= EPS:
            bucket[(at, acct, 'Credit')] += c

    return {k: round(v, 2) for k, v in bucket.items() if abs(v) >= EPS}


# ── Diff / report ────────────────────────────────────────────────────────

def diff_aggs(name_a: str, agg_a: AggDict,
              name_b: str, agg_b: AggDict
              ) -> List[str]:
    '''
    Return a list of human-readable mismatch lines between two aggregates.
    Empty list → the two dicts agree within EPS on every key.
    '''
    keys = set(agg_a) | set(agg_b)
    out: List[str] = []
    for k in sorted(keys):
        a = agg_a.get(k)
        b = agg_b.get(k)
        if a is None:
            out.append(f"  only in {name_b}: {k} = {b}")
        elif b is None:
            out.append(f"  only in {name_a}: {k} = {a}")
        elif abs(a - b) >= EPS:
            out.append(f"  mismatch at {k}: {name_a}={a}  {name_b}={b}  (Δ={round(a-b, 4)})")
    return out


def fmt_agg(agg: AggDict, limit: int = 12) -> str:
    rows = sorted(agg.items())
    head = rows[:limit]
    s = '\n'.join(f"    {k} → {v}" for k, v in head)
    if len(rows) > limit:
        s += f"\n    …(+{len(rows) - limit} more)"
    return s or '    (empty)'
