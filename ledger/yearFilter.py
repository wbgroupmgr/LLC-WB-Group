"""
ledger/yearFilter.py — fiscal-year filtering for the multi-year single-DB
ledger (issue #54).

The shared Accts/*.json files hold every registered year in one flat array.
Temporary accounts (Income/Expense) reset each period; permanent accounts
(Asset/Liability/Equity/Appreciation) carry a cumulative balance since
inception — filtering them to only the active year's dt would show $0 for
any year with no same-year activity yet (e.g. right after YearStart, before
the first transaction for the new year posts), even though the running
balance is real and should carry forward per
docs/BUS/design_LLL_01.9-YEClose_YearStart.md §1.1.

Two-stage filtering is required because source records are dual-account
(acct + Ledger, one each side of the double-entry pair) and a single record
commonly mixes one permanent account with one temporary account (e.g. a
2025 utility bill: acct=Acct.Cash.Bank / Ledger=Acct.Exp.Util). Dropping the
whole record when viewing 2026 would also drop its Cash side, silently
under-stating cash. So:

  1. filter_cumulative() — pre-expansion, coarse: keep every record dated on
     or before the active year's end. Never excludes by account type, so a
     permanent account's side of a mixed record is never lost.
  2. filter_period_rows() — post-expansion (ledgerGeneral.toDoubleEntry has
     already split each record into one row per account): drop Income/
     Expense rows not dated in the active year specifically. Each row now
     has exactly one `acct`, so this is unambiguous.

Acct.Equity.Income.Summary is a temporary/clearing account despite its
Equity acctType — by definition (a classic closing-entry suspense account)
it should never carry a balance into a later fiscal year. It's excluded
from cumulative carry-forward the same way Income/Expense are, even though
COA classifies its acctType as Equity, not Income/Expense.
"""
from __future__ import annotations

from typing import Any, Dict, List

_PERIOD_TYPES = {'Income', 'Expense'}
_ALWAYS_PERIOD_ACCTS = {'Acct.Equity.Income.Summary'}


def filter_cumulative(records: List[Dict[str, Any]], year: str) -> List[Dict[str, Any]]:
    """Pre-expansion filter: keep records dated on or before `year`'s end."""
    if not year:
        return records
    year_end = f"{year}.12.31"
    return [r for r in records if str(r.get('dt') or '') <= year_end]


def filter_period_rows(rows: List[Dict[str, Any]], llc, year: str) -> List[Dict[str, Any]]:
    """Post-expansion filter: drop Income/Expense (and Income.Summary) rows
    not dated in `year`."""
    if not year:
        return rows
    coa = llc.coa
    kept = []
    for r in rows:
        acct = str(r.get('acct', ''))
        is_period = coa._Type(acct) in _PERIOD_TYPES or acct in _ALWAYS_PERIOD_ACCTS
        if is_period and not str(r.get('dt') or '').startswith(year):
            continue
        kept.append(r)
    return kept
