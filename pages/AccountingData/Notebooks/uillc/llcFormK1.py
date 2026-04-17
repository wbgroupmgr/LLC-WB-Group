'''
llcFormK1 — IRS Schedule K-1 (Form 1065) aid — per-partner allocations.

Table is TRANSPOSED: rows = K-1 line items, columns = partner names.
First column is the K-1 field label; subsequent columns are partner names
(from llcOwners, ordered by oID).

Data sources:
  Box 1  — Ordinary income/loss from IS net income share
  Box 2  — Net rental real estate income from Acct.Rev.Rent in GL
  Box 5  — Interest income from Acct.Exp.Other where acctSub/desc contains "interest"
  Box 14 — Self-employment earnings (same as Box 1 if positive)
  Box 19 — Distributions = max(0, Net Income × pct)  [moved from IS Member Distribution]
  Cap. Contributions — GL Credits to Acct.Equity.Owner.Capital.Funds weighted by propOwners
  Cap. Acct Beg Year — 0 (start of reporting period)
  Cap. Acct End Year — GL Debits to Acct.Fixed.Tangible* weighted by propOwners
  Capital Share      — from llcEquity.ownerShares()  (weighted by propOwners on GL)

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List

from ledger.llcEquity import llcEquity
from uillc.llcReportEngine import llcReportEngine


class llcFormK1:

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._equity  = llcEquity(eSession.llc)

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._equity  = llcEquity(eSession.llc)

    def object_name(self) -> str:
        return self.__class__.__name__

    # ── helpers ───────────────────────────────────────────────────────────────

    def _per_partner_k1(self) -> List[Dict[str, Any]]:
        '''
        Build one K-1 dict per partner (un-transposed).

        Box 1 Ord. Income  = IS Income SubTotal × P&L pct
        Box 1 Ord. Loss    = (IS Expense SubTotal + Depreciation) × P&L pct
                             (K-1 loss includes depreciation per IRS convention)
        Box 2              = Rent income (Acct.Rev.Rent Credits) × P&L pct
        Box 5              = Acct.Exp.Other "Interest" entries × P&L pct
        Box 19             = max(0, Net Income w/ Depreciation × P&L pct)
        Cap Beg Year       = 0
        Cap End Year       = Acct.Fixed.Tangible* Debit balances by propOwners
        '''
        # ── equity shares ─────────────────────────────────────────────────────
        shares = self._equity.ownerShares(self.engine)
        shares = [s for s in shares if s.get('name') != 'TOTAL']

        # ── IS subtotals (income / expense / depreciation) ────────────────────
        _, owner_names, is_pm = self.engine.buildISPerMember()
        income_subtotal  = float(is_pm.get('income_subtotal',  0.0))
        expense_subtotal = float(is_pm.get('expense_subtotal', 0.0))  # negative
        depreciation     = float(is_pm.get('depreciation',     0.0))  # positive amount
        ni_with_depr     = float(is_pm.get('net_income_with_depr', 0.0))

        # ── Box 2 — rent income ───────────────────────────────────────────────
        rent_total = self.engine._rent_income_total()

        # ── Box 5 — interest ──────────────────────────────────────────────────
        interest_total = self.engine._interest_expense_total()

        # ── capital accounts ──────────────────────────────────────────────────
        contrib_map = self.engine._contributions_by_owner()
        cap_end_map = self.engine._capital_end_year_by_owner()

        per_partner = []
        for s in shares:
            oID    = s.get('oID', '')
            pct_pl = float(s.get('pct_pl', 0))

            # Box 1 Ord. Income: IS income subtotal per member
            box1_income = round(income_subtotal * pct_pl, 2)

            # Box 1 Ord. Loss: expense subtotal (abs) + depreciation per member
            # expense_subtotal is negative (Credit−Debit), so abs() gives the expense amount
            box1_loss = round((abs(expense_subtotal) + depreciation) * pct_pl, 2)

            # Box 19 distribution = max(0, NI w/ Depr × pct)
            distribution = max(0.0, round(ni_with_depr * pct_pl, 2))

            # Box 5 interest (by P&L %)
            interest_share = round(interest_total * pct_pl, 2) if interest_total else ''

            per_partner.append({
                'Partner':               s['name'],
                'oID':                   oID,
                'Status':                s.get('status', ''),
                'Type':                  s.get('memType', ''),
                'Profit %':              f"{pct_pl * 100:.1f}%",
                'Capital Share':         s['capital_share'],
                # Box 1 — Ordinary business income / loss (from IS subtotals)
                'Box 1 Ord. Income':     box1_income,
                'Box 1 Ord. Loss':       box1_loss,
                # Box 2 — Net rental real estate income (from Acct.Rev.Rent)
                'Box 2 Net Rental Inc.': round(rent_total * pct_pl, 2),
                # Box 3 — Other net rental income (loss)
                'Box 3 Other Rental':    '',
                # Box 4 — Guaranteed payments
                'Box 4 Guar. Payments':  '',
                # Box 5 — Interest income (Acct.Exp.Other where acctSub/desc = Interest)
                'Box 5 Interest':        interest_share,
                # Box 6a — Ordinary dividends
                'Box 6a Dividends':      '',
                # Box 9a — Net capital gain (loss)
                'Box 9a Cap. Gain':      '',
                # Box 14 — Self-employment earnings
                'Box 14 SE Earnings':    box1_income if box1_income > 0 else '',
                # Box 19 — Distributions (max 0, from IS Net Income w/ Depreciation)
                'Box 19 Distributions':  distribution,
                # Capital account analysis
                'Cap. Acct Beg. Year':   0,
                'Cap. Contributions':    contrib_map.get(str(oID), ''),
                'Cap. Withdrawals':      '',
                'Cap. Acct End Year':    cap_end_map.get(str(oID), ''),
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
        alloc     = self._equity.ownerShares(self.engine)
        alloc     = [a for a in alloc if a.get('name') != 'TOTAL']
        total_ni  = round(sum(a.get('net_income_share', 0) for a in alloc), 2)
        rent      = self.engine._rent_income_total()
        return {
            'Partners':        len(alloc),
            'Total NI Alloc':  total_ni,
            'Total Rent (Box 2)': rent,
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Schedule K-1 aid. Transposed: rows = K-1 fields, columns = partners. '
                'Box 2 from Acct.Rev.Rent Credit balances. '
                'Box 5 from Acct.Exp.Other where acctSub/desc contains "interest". '
                'Box 19 = max(0, Net Income × P&L%). '
                'Cap End Year = Acct.Fixed.Tangible* Debit balance by propOwners. '
                'Cap Beg Year = 0 (start of period).'
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
