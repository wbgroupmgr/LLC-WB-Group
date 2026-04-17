'''
llcEquity — Owner / Member Equity computation service.

Encapsulates all owner-equity logic so it can be shared between the
Owner Equity view (llcOwnerEquity) and the Schedule K-1 view (llcFormK1).

Usage:
    equity = llcEquity(llc)
    shares = equity.ownerShares(FR)

    Where FR is any object that exposes:
      - FR.buildIS()   → (rows, {net_income, income, expense})
      - FR.load_owners()  → list of {oID, nm, pct, status, memType, ...}
      - FR.getGLList(resolve_dups=True) → list of GL record dicts

Returns a list of per-owner dicts:
    {oID, name, status, memType, pct_pl,
     capital_share, net_income_share, distribution}

Timestamp of last change: 2026.04.14
'''

from collections import defaultdict
from typing import Any, Dict, List


class llcEquity:
    '''
    Owner equity computation service.
    Pass the LLC object so the service is scoped to the right entity.
    All financial data is supplied via the FR (financial report) argument
    to ownerShares(), making this usable in both notebook and web-app contexts.
    '''

    def __init__(self, llc):
        self.llc = llc

    # ── internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _signed_amt(row: Dict[str, Any]) -> float:
        '''Return amount as a signed debit-positive value.'''
        try:
            amt = float(row.get('amt', 0) or 0)
        except (TypeError, ValueError):
            amt = 0.0
        atype = str(row.get('aType', '')).strip().lower()
        # Debit increases assets / equity (positive)
        return amt if atype in ('debit', 'dr', 'd') else -amt

    @staticmethod
    def _owner_name(owner: Dict[str, Any]) -> str:
        nm = owner.get('nm', '')
        if isinstance(nm, list):
            return ', '.join(nm)
        return str(nm)

    def _capital_by_owner(self, gl_rows: List[Dict[str, Any]]) -> Dict[str, float]:
        '''
        Sum GL amounts for Asset / Equity accounts weighted by the
        per-transaction propOwners dict.

        propOwners example: {"o20250801_1": 100}  — integer percent (100 = 100%)
        '''
        capital: Dict[str, float] = defaultdict(float)
        for row in gl_rows:
            if row.get('acctType', '') not in ('Asset', 'Equity'):
                continue
            prop_owners = row.get('propOwners')
            if not isinstance(prop_owners, dict):
                continue
            signed = self._signed_amt(row)
            for oid, pct in prop_owners.items():
                try:
                    # propOwners stores integer percent (100 = 100%) → divide by 100
                    capital[str(oid)] += signed * float(pct) / 100.0
                except (TypeError, ValueError):
                    pass
        return {k: round(v, 2) for k, v in capital.items()}

    # ── public interface ──────────────────────────────────────────────────────

    def ownerShares(self, FR) -> List[Dict[str, Any]]:
        '''
        Compute per-owner equity shares.

        FR must expose:
          buildIS()              → (rows, summary)  — summary has 'net_income'
          load_owners()          → list of owner records
          getGLList(resolve_dups=True) → list of GL dicts

        Returns:
          List of {oID, name, status, memType, pct_pl,
                   capital_share, net_income_share, distribution}
          plus a TOTAL row at the end.
        '''
        # ── get net income from IS ────────────────────────────────────────
        _, is_summary = FR.buildIS()
        net_income = float(is_summary.get('net_income', 0.0))

        # ── load owners ───────────────────────────────────────────────────
        owners = FR.load_owners()

        # ── capital weighted by propOwners in GL ──────────────────────────
        gl_rows    = FR.getGLList(resolve_dups=True)
        capital_map = self._capital_by_owner(gl_rows)

        # ── build per-owner rows ──────────────────────────────────────────
        rows: List[Dict[str, Any]] = []
        for o in owners:
            oid      = o.get('oID', '')
            pct_pl   = float(o.get('pct', 0))
            cap      = capital_map.get(oid, 0.0)
            ni_share = round(net_income * pct_pl, 2)

            rows.append({
                'oID':              oid,
                'name':             self._owner_name(o),
                'status':           o.get('status', ''),
                'memType':          o.get('memType', ''),
                'pct_pl':           pct_pl,
                'capital_share':    round(cap, 2),
                'net_income_share': ni_share,
                'distribution':     '',          # FIXME: populate when distribution data exists
            })

        # ── append TOTAL row ──────────────────────────────────────────────
        if rows:
            rows.append({
                'oID':              '',
                'name':             'TOTAL',
                'status':           '',
                'memType':          '',
                'pct_pl':           round(sum(r['pct_pl']           for r in rows), 4),
                'capital_share':    round(sum(r['capital_share']    for r in rows), 2),
                'net_income_share': round(sum(r['net_income_share'] for r in rows), 2),
                'distribution':     '',
            })

        return rows
