'''
llcBalanceSheet — computed read-only Balance Sheet view.
Delegates to llcReportEngine.buildBS() for double-entry GL, aggregation,
and the accounting-equation check (Assets = Liabilities + Equity).

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List, Optional, Tuple

from uillc.llcReportEngine import llcReportEngine


class llcBalanceSheet:
    '''
    Read-only computed Balance Sheet view.
    Rows: {acctType, acct, Debit, Credit, Balance} + TOTAL.
    Accounting equation check exposed via last_check().
    '''

    VIEW_BY_OPTIONS = ['All', 'ByAsset', 'ByLiability', 'ByEquity']

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._check: Dict[str, Any] = {'balanced': None}

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._check   = {'balanced': None}

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
        '''Return aggregated Balance Sheet rows and cache the accounting-equation check.'''
        rows, check = self.engine.buildBS(view_by=view_by)
        self._check = check
        return rows

    def last_check(self) -> Dict[str, Any]:
        '''Return accounting-equation check from the most recent load() call.'''
        return self._check

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

        result: Dict[str, Any] = {
            'Accounts':    sum(acct_counts.values()),
            'TotalDebit':  total_row.get('Debit',   0),
            'TotalCredit': total_row.get('Credit',  0),
            'NetBalance':  total_row.get('Balance', 0),
            'ByAcctType':  acct_counts,
        }
        if self._check.get('balanced') is False:
            result['⚠ Equation'] = f"diff={self._check.get('equation_diff', '?')}"
        return result

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'sources': {
                'llcExpRev': self._wk_fn('llcExpRev'),
                'llcAssets': self._wk_fn('llcAssets'),
            },
            'note': 'Read-only. Double-entry GL. Assets = Liabilities + Equity check applied.',
        }

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()
