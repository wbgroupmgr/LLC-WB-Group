'''
llcIncomeStmt — computed read-only Income Statement view.
Delegates to llcReportEngine.buildIS() for double-entry GL and aggregation.

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List

from uillc.llcReportEngine import llcReportEngine


class llcIncomeStmt:
    '''
    Read-only computed Income Statement view.
    Rows: {acctType, acct, Debit, Credit, Balance} + TOTAL/Net-Income row.
    '''

    VIEW_BY_OPTIONS = ['All', 'ByIncome', 'ByExpense', 'PerMember']

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._summary: Dict[str, Any] = {}

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._summary = {}

    def object_name(self) -> str:
        return self.__class__.__name__

    def _wk_fn(self, name: str) -> str:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return None
        tObj = wk.o
        return tObj.FN() if tObj else None

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''Return aggregated Income Statement rows; cache the net-income summary.
        When view_by == 'PerMember', returns an empty list (use load_per_member() instead).
        '''
        if view_by == 'PerMember':
            self._summary = {}
            return []
        rows, summary = self.engine.buildIS(view_by=view_by)
        self._summary = summary
        return rows

    def load_per_member(self):
        '''
        Return IS with per-owner allocation columns.

        Returns (rows, owner_names, summary) from llcReportEngine.buildISPerMember().
        '''
        rows, owner_names, summary = self.engine.buildISPerMember()
        self._summary = summary
        return rows, owner_names, summary

    def last_summary(self) -> Dict[str, Any]:
        '''Return IS summary from the most recent load() call.'''
        return self._summary

    def stats(self) -> Dict[str, Any]:
        rows = self.load()
        acct_counts: Dict[str, int] = {}
        total_row = {}
        for row in rows:
            at = row.get('acctType', '')
            if at == 'TOTAL':
                total_row = row
                continue
            acct_counts[at] = acct_counts.get(at, 0) + 1

        return {
            'Accounts':    sum(acct_counts.values()),
            'TotalDebit':  total_row.get('Debit',   0),
            'TotalCredit': total_row.get('Credit',  0),
            'NetIncome':   self._summary.get('net_income', total_row.get('Balance', 0)),
            'Income':      self._summary.get('income',  0),
            'Expense':     self._summary.get('expense', 0),
            'ByAcctType':  acct_counts,
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'sources': {
                'llcExpRev': self._wk_fn('llcExpRev'),
                'llcAssets': self._wk_fn('llcAssets'),
            },
            'note': 'Read-only. Double-entry GL. Income / Expense groups. Balance = Net Income.',
        }

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()
