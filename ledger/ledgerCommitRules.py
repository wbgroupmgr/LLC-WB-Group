"""
ledger/ledgerCommitRules.py — Equity/Liability ownership rules, enforced at
ledger commit time (issue #64).

Hard-reject gate for llcAssets/llcExpRev: propNm and propOwners must be set
on the record *before* it enters the books, not caught later by a reactive
forensic check (see SK1B-R07u, irs/taxAgents/FormSchK1Agent.py:1270, which
this gate is meant to make redundant for all new entries going forward).

Rules (accountant-reviewed, 2026-07-06 session):
  - propNm required on every record except Acct.Equity.* accounts (entity-
    level equity movements use 'LLC'/'Cash_LLC' by convention, not enforced
    by name). Form 8825/4562 report per property — IRC §168.
  - propOwners ({oID: pct}) required whenever either side (acct/Ledger) of
    the double-entry pair touches Acct.Equity.Owner.Capital.{Funds,Dist,
    Reinvestment} — per-partner capital account attribution, IRC §705/§722.

Out of scope (see issue #65): llcPayables/llcReceivables are not validated
here. Pre-existing 2025 data is never re-validated — this only gates newly
written records going forward.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

OWNERSHIP_ACCTS = {
    'Acct.Equity.Owner.Capital.Funds',
    'Acct.Equity.Owner.Capital.Dist',
    'Acct.Equity.Owner.Capital.Reinvestment',
}

PROPNM_EXEMPT_PREFIX = 'Acct.Equity.'


class OwnershipRuleViolation(Exception):
    """Raised when a ledger record is missing a required propNm/propOwners tag."""


def validate_ownership_rules(records: Iterable[Dict[str, Any]]) -> None:
    errors = []
    for r in records:
        acct   = str(r.get('acct') or '')
        ledger = str(r.get('Ledger') or '')
        tid    = r.get('tID', '<no tID>')

        if not acct.startswith(PROPNM_EXEMPT_PREFIX):
            if not str(r.get('propNm') or '').strip():
                errors.append(f"{tid}: missing propNm (required for {acct or ledger})")

        if acct in OWNERSHIP_ACCTS or ledger in OWNERSHIP_ACCTS:
            po = r.get('propOwners')
            if not isinstance(po, dict) or not po:
                errors.append(
                    f"{tid}: missing propOwners (required for {acct or ledger} — IRC §705/§722)"
                )

    if errors:
        raise OwnershipRuleViolation(
            "Ledger commit rejected — Equity/Liability ownership rules (issue #64):\n  "
            + "\n  ".join(errors)
        )
