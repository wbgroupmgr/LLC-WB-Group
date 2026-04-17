'''
llcOwnerEquity — Owner / Member Equity view.

Uses ledger.llcOwners.capitalDist() to expand raw asset transactions by
stakeholder ownership percentage, then groups them by (member, account) so
each member gets its own section in the financial_view.html template.

Row structure (matches financial_view.html):
  acctType  — member name  (becomes the section-header label in the template)
  acct      — GL account code
  acctSub   — GL sub-account
  Debit     — owner-weighted debit balance
  Credit    — owner-weighted credit balance
  Balance   — Debit − Credit (owner's share)

A Net Income Share row is appended at the end of each member's section.
A grand-total TOTAL row is appended last.

Timestamp of last change: 2026.04.14
'''

from collections import defaultdict
from typing import Any, Dict, List

from ledger.llcOwners import llcOwners as LLCOwners
from uillc.llcReportEngine import llcReportEngine


class llcOwnerEquity:

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def object_name(self) -> str:
        return self.__class__.__name__

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Build per-member capital distribution rows.

        Steps:
          1. Load raw llcAssets records.
          2. Expand by propOwners via llcOwners.capitalDist() — one record per
             (transaction × owner), amt scaled by integer ownership pct.
          3. Group by (owner, acct, acctSub) → sum amounts.
          4. Emit rows with member name as acctType (drives section headers).
          5. Append a Net Income Share row per member.
          6. Append a grand TOTAL row.
        '''
        # ── 1. Load raw assets and expand by owner ─────────────────────────
        asset_list = self.engine._load_source('llcAssets')
        owners_svc = LLCOwners(self.eSession.llc)
        expanded   = owners_svc.capitalDist(asset_list)

        if not expanded:
            return []

        # ── 2. Group by (o_oID, o_nm, acct, acctSub) → sum amt ────────────
        owner_names: Dict[str, str] = {}          # o_oID → o_nm (insertion-ordered)
        buckets: Dict[tuple, float] = defaultdict(float)

        for rec in expanded:
            o_oID    = rec.get('o_oID', '')
            o_nm     = rec.get('o_nm', o_oID)
            acct     = rec.get('acct', '')
            acct_sub = str(rec.get('acctSub') or '')
            try:
                amt = float(rec.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0

            if o_oID not in owner_names:
                owner_names[o_oID] = o_nm

            buckets[(o_oID, acct, acct_sub)] += amt

        # ── 3. Fetch net-income and owner P&L pct ──────────────────────────
        _, is_summary  = self.engine.buildIS()
        net_income     = float(is_summary.get('net_income', 0.0))
        owners_data    = self.engine.load_owners()
        owner_pct_map  = {o['oID']: float(o.get('pct', 0.0)) for o in owners_data}

        # ── 4 + 5. Build rows per member ───────────────────────────────────
        rows: List[Dict[str, Any]] = []

        for o_oID, o_nm in owner_names.items():

            # Account rows for this member, sorted by acct
            member_acct_rows = sorted(
                ((acct, acct_sub, total_amt)
                 for (oid, acct, acct_sub), total_amt in buckets.items()
                 if oid == o_oID),
                key=lambda x: (x[0], x[1])
            )

            for acct, acct_sub, total_amt in member_acct_rows:
                bal = round(total_amt, 2)
                rows.append({
                    'acctType': o_nm,                       # member → section header
                    'acct':     acct,
                    'acctSub':  acct_sub,
                    'Debit':    round(bal,  2) if bal >= 0 else 0.0,
                    'Credit':   round(-bal, 2) if bal < 0  else 0.0,
                    'Balance':  bal,
                })

            # Net income share row at the end of this member's section
            pct_pl   = owner_pct_map.get(o_oID, 0.0)
            ni_share = round(net_income * pct_pl, 2)
            rows.append({
                'acctType': o_nm,
                'acct':     f'Net Income Share ({pct_pl * 100:.1f}%)',
                'acctSub':  '',
                'Debit':    0.0,
                'Credit':   0.0,
                'Balance':  ni_share,
            })

        # ── 6. Grand TOTAL row ─────────────────────────────────────────────
        total_d = round(sum(r['Debit']   for r in rows), 2)
        total_c = round(sum(r['Credit']  for r in rows), 2)
        total_b = round(sum(r['Balance'] for r in rows), 2)
        rows.append({
            'acctType': 'TOTAL', 'acct': '', 'acctSub': '',
            'Debit': total_d, 'Credit': total_c, 'Balance': total_b,
        })

        return rows

    def stats(self) -> Dict[str, Any]:
        rows    = self.load()
        total   = next((r for r in rows if r.get('acctType') == 'TOTAL'), {})
        members = len({r['acctType'] for r in rows
                       if r.get('acctType') not in ('', 'TOTAL')})
        return {
            'Members':       members,
            'Total Balance': total.get('Balance', 0),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'Capital distribution from llcAssets.propOwners (integer %). '
                'Net Income Share from llcOwners.pct (decimal). '
                'Section headers = member names.'
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
