'''
llcOwnerEquity — Owner / Member Equity view.

Shows per-member capital allocation and profit/loss distribution:
  - Capital % from propOwners field of Asset/Equity transactions
  - P&L % from llcOwners.pct
  - YE net income share (allocated by P&L pct)
  - YE distribution placeholder (FIXME: populate when distribution data available)

Rendered by financial_view.html as a standalone section.

Timestamp of last change: 2026.04.14
'''

from collections import defaultdict
from typing import Any, Dict, List

from uillc.llcReportEngine import llcReportEngine


class llcOwnerEquity:

    VIEW_BY_OPTIONS: List[str] = []   # no ViewBy for this view

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def object_name(self) -> str:
        return self.__class__.__name__

    # ── helpers ───────────────────────────────────────────────────────────────

    def _capital_by_owner(self) -> Dict[str, float]:
        '''
        Sum asset/equity transaction amounts weighted by propOwners percentage.
        propOwners is a dict like {"FXR": 0.96, "AR": 0.02, "NR": 0.02}.
        '''
        rows = self.engine.getGLList(resolve_dups=True)
        capital: Dict[str, float] = defaultdict(float)
        for row in rows:
            at = row.get('acctType', '')
            if at not in ('Asset', 'Equity'):
                continue
            prop_owners = row.get('propOwners')
            if not isinstance(prop_owners, dict):
                continue
            try:
                amt = float(row.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            # Debit increases assets; credit increases liabilities/equity
            a_type = str(row.get('aType', '')).strip()
            signed = amt if a_type.lower() in ('debit', 'dr', 'd') else -amt
            for owner_id, pct in prop_owners.items():
                try:
                    capital[str(owner_id)] += signed * float(pct)
                except (TypeError, ValueError):
                    pass
        return {k: round(v, 2) for k, v in capital.items()}

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Return one row per member with capital contribution and P&L allocation.
        Columns: member, status, pct_pl, capital_share, net_income_share, distribution
        '''
        owners = self.engine.load_owners()
        pl_alloc = self.engine.owner_pl_allocation()     # [{oID, name, pct, net_income_share}, ...]
        capital_map = self._capital_by_owner()           # {oID: float}

        # Build lookup by oID
        pl_by_id = {r['oID']: r for r in pl_alloc}

        rows: List[Dict[str, Any]] = []
        for owner in owners:
            oid  = owner.get('oID', '')
            name = ', '.join(owner.get('nm', [])) if isinstance(owner.get('nm'), list) else str(owner.get('nm', ''))
            status   = owner.get('status', '')
            mem_type = owner.get('memType', '')

            pl_rec  = pl_by_id.get(oid, {})
            pct_pl  = pl_rec.get('pct', float(owner.get('pct', 0)))
            ni_share = pl_rec.get('net_income_share', 0.0)
            cap_share = capital_map.get(oid, 0.0)

            rows.append({
                'oID':              oid,
                'Member':           name,
                'Type':             mem_type,
                'Status':           status,
                'P&L %':            f"{pct_pl*100:.1f}%",
                'Capital Share':    round(cap_share, 2),
                'Net Income Share': round(ni_share,  2),
                'YE Distribution':  'FIXME',   # placeholder — populate when dist data available
            })

        # Totals row
        if rows:
            total_cap = round(sum(r['Capital Share']    for r in rows), 2)
            total_ni  = round(sum(r['Net Income Share'] for r in rows), 2)
            rows.append({
                'oID':              '',
                'Member':           'TOTAL',
                'Type':             '',
                'Status':           '',
                'P&L %':            '100%',
                'Capital Share':    total_cap,
                'Net Income Share': total_ni,
                'YE Distribution':  '',
            })

        return rows

    def stats(self) -> Dict[str, Any]:
        rows = self.load()
        total_row = next((r for r in rows if r.get('Member') == 'TOTAL'), {})
        return {
            'Members':         sum(1 for r in rows if r.get('Member') not in ('', 'TOTAL')),
            'Total Capital':   total_row.get('Capital Share', 0),
            'Total NI Share':  total_row.get('Net Income Share', 0),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'Read-only. Capital % from propOwners field; P&L % from llcOwners.pct. '
                'YE Distribution is a placeholder (FIXME).'
            ),
        }

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()
