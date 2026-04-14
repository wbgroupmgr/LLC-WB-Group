'''
llcFormK1 — IRS Schedule K-1 (Form 1065) aid — per-partner allocations.

Generates one K-1 summary row per member based on:
  - Net income/loss share (from llcOwners.pct)
  - Capital account beginning/ending balance (FIXME — needs historical data)
  - Distributions (FIXME — needs distribution transaction data)

Rendered as a table with one row per partner.

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List

from uillc.llcReportEngine import llcReportEngine

_FIXME = 'FIXME'


class llcFormK1:

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
        Return one K-1 row per partner with key Schedule K-1 boxes populated.
        '''
        alloc = self.engine.owner_pl_allocation()   # [{oID, name, pct, net_income_share}]

        rows: List[Dict[str, Any]] = []
        for a in alloc:
            ni = round(a.get('net_income_share', 0), 2)
            rows.append({
                'Partner':              a.get('name', ''),
                'oID':                  a.get('oID', ''),
                'Status':               a.get('status', ''),
                'Profit %':             f"{a.get('pct', 0)*100:.1f}%",
                # Box 1 — Ordinary business income (loss)
                'Box 1 Ord. Income':    ni if ni >= 0 else 0,
                'Box 2 Net Rental Inc.': _FIXME,
                'Box 3 Other Net Rental': _FIXME,
                # Box 4 — Guaranteed payments
                'Box 4 Guar. Payments': _FIXME,
                # Box 5 — Interest income
                'Box 5 Interest':       _FIXME,
                # Box 6a — Ordinary dividends
                'Box 6a Dividends':     _FIXME,
                # Box 9a — Net capital gain (loss)
                'Box 9a Cap. Gain':     _FIXME,
                # Box 14 — Self-employment earnings
                'Box 14 SE Earnings':   ni if ni >= 0 else _FIXME,
                # Box 19 — Distributions
                'Box 19 Distributions': _FIXME,
                # Capital account
                'Cap. Acct Beg. Year':  _FIXME,
                'Cap. Contributions':   _FIXME,
                'Cap. Withdrawals':     _FIXME,
                'Cap. Acct End Year':   _FIXME,
            })
        return rows

    def stats(self) -> Dict[str, Any]:
        alloc = self.engine.owner_pl_allocation()
        total_ni = round(sum(a.get('net_income_share', 0) for a in alloc), 2)
        return {
            'Partners':       len(alloc),
            'Total NI Alloc': total_ni,
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Schedule K-1 aid. P&L allocation from llcOwners.pct. '
                'Capital accounts and distributions marked FIXME — need historical data.'
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
