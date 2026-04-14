'''
llcGeneralLedger — computed read-only General Ledger view.
Data sourced from llcReportEngine (double-entry expanded GL).
Cross-source duplicate transactions are flagged with Status='⚠ Dup'.

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List

from uillc.llcReportEngine import llcReportEngine


class llcGeneralLedger:

    VIEW_COLUMNS = ['Status', 'dt', 'acctType', 'acct', 'aType', 'amt', 'desc', 'acctSub', 'refDB']
    VIEW_BY_OPTIONS = ['All', 'By Dups', 'ByAsset', 'ByLiability', 'ByEquity', 'ByIncome', 'ByExpense']

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def object_name(self) -> str:
        return self.__class__.__name__

    def _wk_fn(self, name: str) -> str:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return None
        tObj = wk.o
        return tObj.FN() if tObj else None

    def _apply_view_by(self, rows: List[Dict[str, Any]], view_by: str) -> List[Dict[str, Any]]:
        if not view_by or view_by == 'All':
            return rows
        if view_by == 'By Dups':
            return [r for r in rows if r.get('Status') == '⚠ Dup']
        acct_type = view_by[2:]
        return [r for r in rows if r.get('acctType', '') == acct_type]

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Full General Ledger via double-entry expansion.
        Uses resolve_dups=False so cross-source duplicates are flagged.
        '''
        merged = self.engine.getGLListWithDups()
        return self._apply_view_by(merged, view_by)

    def stats(self) -> Dict[str, Any]:
        rows = self.engine.getGLListWithDups()
        acct_counts: Dict[str, int] = {}
        total_debit = total_credit = dup_count = 0.0

        for row in rows:
            at = row.get('acctType', 'Unknown')
            acct_counts[at] = acct_counts.get(at, 0) + 1
            if row.get('Status') == '⚠ Dup':
                dup_count += 1
            try:   amt = float(row.get('amt', 0) or 0)
            except: amt = 0.0
            if str(row.get('aType', '')).strip().lower() in ('debit', 'dr', 'd'):
                total_debit += amt
            else:
                total_credit += amt

        result = {
            'Transactions': len(rows),
            'TotalDebit':   round(total_debit,  2),
            'TotalCredit':  round(total_credit, 2),
            'NetBalance':   round(total_debit - total_credit, 2),
            'ByAcctType':   acct_counts,
        }
        if dup_count:
            result['Duplicates'] = int(dup_count)
        return result

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'sources': {
                'llcExpRev': self._wk_fn('llcExpRev'),
                'llcAssets': self._wk_fn('llcAssets'),
            },
            'note': 'Read-only. Double-entry expanded GL. Cross-source dups flagged ⚠ Dup.',
        }

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()
