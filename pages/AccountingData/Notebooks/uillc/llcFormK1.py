'''
llcFormK1 — IRS Schedule K-1 (Form 1065) aid — per-partner allocations.

Table is TRANSPOSED: rows = K-1 line items, columns = partner names.
First column is the K-1 field label; subsequent columns are partner names
(from llcOwners, ordered by oID).

Data sources (FR database — same pipeline as Sch_K1_FILL.pdf):
  Box 1  — Ordinary income = (net_income - rent_income) × pct
  Box 2  — Net rental income = rent_income × pct
  Box 5  — Interest income = interest_income × pct
  Box 14 — SE earnings = max(0, ordinary_ni) per partner
  Box 19 — Cash distributions = max(0, net_income) × pct
  Cap. Contributions — from llcOwners capital_contributed
  Capital End Year — contributions + ni_share − distributions

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase


class llcFormK1(_llcIRSViewBase):

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        super().__init__(eSession)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _per_partner_k1(self) -> List[Dict[str, Any]]:
        '''
        Build one K-1 dict per partner using FR data.

        Box 1  — Ordinary income = (net_income - rent_income) × pct
        Box 2  — Net rental = rent_income × pct
        Box 5  — Interest income × pct
        Box 14 — SE earnings = max(0, ordinary_ni per partner)
        Box 19 — Distribution = max(0, net_income) × pct
        Cap    — from owners profile
        '''
        ni          = self._isv('net_income')
        rent        = self._isv('rent_income')
        interest    = self._isv('interest_income')
        ordinary_ni = round(ni - rent, 2)

        per_partner = []
        for a in self._per_partner_alloc():
            pct  = a['pct']
            name = a['name']
            oID  = a['oID']

            box1_income  = round(ordinary_ni * pct, 2) if ordinary_ni > 0 else 0.0
            box1_loss    = round(abs(ordinary_ni) * pct, 2) if ordinary_ni < 0 else 0.0
            box2_rental  = a['rent_share']
            box5_int     = round(interest * pct, 2) if interest else ''
            box14_se     = box1_income if box1_income > 0 else ''
            box19_distrib = a['distrib']

            # Capital account: contributions − (end capital via formula)
            contribs_total = float(self._owners_agg.get('cash_contributions', 0.0))
            # Per-partner contribution approximated from total × pct
            contrib_share  = round(contribs_total * pct, 2)
            cap_end        = round(contrib_share + a['ni_share'] - box19_distrib, 2)

            per_partner.append({
                'Partner':               name,
                'oID':                   oID,
                'Status':                a.get('status', ''),
                'Type':                  a.get('type', 'Individual'),
                'Profit %':              f"{pct * 100:.1f}%",
                'Capital Share':         f"{pct * 100:.1f}%",
                # Box 1 — Ordinary business income / loss
                'Box 1 Ord. Income':     box1_income,
                'Box 1 Ord. Loss':       box1_loss,
                # Box 2 — Net rental real estate income
                'Box 2 Net Rental Inc.': box2_rental,
                # Box 3 — Other net rental income (loss)
                'Box 3 Other Rental':    '',
                # Box 4 — Guaranteed payments
                'Box 4 Guar. Payments':  '',
                # Box 5 — Interest income
                'Box 5 Interest':        box5_int,
                # Box 6a — Ordinary dividends
                'Box 6a Dividends':      '',
                # Box 9a — Net capital gain (loss)
                'Box 9a Cap. Gain':      '',
                # Box 14 — Self-employment earnings
                'Box 14 SE Earnings':    box14_se,
                # Box 19 — Cash distributions
                'Box 19 Distributions':  box19_distrib,
                # Capital account analysis
                'Cap. Acct Beg. Year':   0,
                'Cap. Contributions':    contrib_share,
                'Cap. Withdrawals':      '',
                'Cap. Acct End Year':    cap_end,
            })
        return per_partner

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Return transposed K-1 table.
        Rows = K-1 line items.
        Columns = 'K-1 Line' + one column per partner (partner name as heading).
        '''
        per_partner = self._per_partner_k1()
        if not per_partner:
            return []

        partner_names = [p['Partner'] for p in per_partner]
        skip_fields   = {'Partner'}
        all_fields    = [k for k in per_partner[0].keys() if k not in skip_fields]
        by_name       = {p['Partner']: p for p in per_partner}

        rows: List[Dict[str, Any]] = []
        for field in all_fields:
            row: Dict[str, Any] = {'K-1 Line': field}
            for pname in partner_names:
                row[pname] = by_name[pname].get(field, '')
            rows.append(row)

        return rows

    def stats(self) -> Dict[str, Any]:
        alloc = self._per_partner_alloc()
        return {
            'Partners':           self._owner_count(),
            'Total NI Alloc':     round(sum(a['ni_share'] for a in alloc), 2),
            'Total Rent (Box 2)': self._isv('rent_income'),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Schedule K-1 aid. Transposed: rows = K-1 fields, columns = partners. '
                'Values from FR database — identical to Sch_K1_FILL.pdf. '
                'Box 2 = rent_income × partner pct. '
                'Box 5 = interest_income × pct. '
                'Box 19 = max(0, net_income) × pct. '
                'Consult a qualified tax professional before filing.'
            ),
        }
