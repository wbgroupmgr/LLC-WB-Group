'''
llcGeneralLedger — computed read-only view
Merges llcExpRev + llcAssets DB records into a single General Ledger list.
Delegates merge/dedup to ledgerGeneral.mergeGL(resolve_dups=False) so that
cross-source duplicate transactions are flagged with Status='⚠ Dup'.

Timestamp of last change: 2026.04.13
'''

from typing import Any, Dict, List

from ledger.ledgerGeneral import ledgerGeneral


class llcGeneralLedger:
    '''
    Read-only computed view — General Ledger.
    Merges llcExpRev and llcAssets DB data, marks cross-source duplicates,
    and returns a flat sorted list suitable for table_view.html.
    '''

    # Preferred column display order for the table (Status first)
    VIEW_COLUMNS = ['Status', 'dt', 'acctType', 'acct', 'aType', 'amt', 'desc', 'acctSub', 'refDB']

    # ViewBy options for the dropdown (BS order then IS order)
    VIEW_BY_OPTIONS = ['All', 'By Dups', 'ByAsset', 'ByLiability', 'ByEquity', 'ByIncome', 'ByExpense']

    def __init__(self, eSession):
        self.eSession = eSession
        self.gl = ledgerGeneral(eSession.llc)

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.gl = ledgerGeneral(eSession.llc)

    def object_name(self) -> str:
        return self.__class__.__name__

    # ── internal helpers ──────────────────────────────────────────────────────

    def _load_source(self, name: str) -> List[Dict[str, Any]]:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return []
        tObj = wk.o
        data = tObj.load()
        return data if isinstance(data, list) else []

    def _wk_fn(self, name: str) -> str:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return None
        tObj = wk.o
        return tObj.FN() if tObj else None

    def _apply_view_by(self, rows: List[Dict[str, Any]], view_by: str) -> List[Dict[str, Any]]:
        '''Filter merged GL rows according to the ViewBy selection.'''
        if not view_by or view_by == 'All':
            return rows
        if view_by == 'By Dups':
            return [r for r in rows if r.get('Status') == '⚠ Dup']
        # 'ByAsset' → acctType == 'Asset', etc.
        acct_type = view_by[2:]  # strip leading 'By'
        return [r for r in rows if r.get('acctType', '') == acct_type]

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Build the General Ledger via double-entry expansion + merge.

        Each source record (acct + Ledger fields) is expanded into two GL entries:
          - acct side  : acct=original acct, aType=original
          - ledger side: acct=Ledger value,  aType=toggled, sign-flipped tID

        The Ledger field is consumed and dropped from both entries.
        acctType is recomputed per entry from the COA.
        resolve_dups=False keeps all entries and marks cross-source dups.
        '''
        er_list    = self._load_source('llcExpRev')
        asset_list = self._load_source('llcAssets')

        # Expand to double-entry GL pairs (drops Ledger, recomputes tID + acctType)
        er_expanded    = self.gl.toDoubleEntry(er_list)
        asset_expanded = self.gl.toDoubleEntry(asset_list)

        # Merge: resolve_dups=False → keep all, flag cross-source dups
        merged = self.gl.mergeGL([er_expanded, asset_expanded], resolve_dups=False)
        return self._apply_view_by(merged, view_by)

    def stats(self) -> Dict[str, Any]:
        rows = self.load()   # full unfiltered list for accurate counts
        acct_counts: Dict[str, int] = {}
        total_debit = 0.0
        total_credit = 0.0
        dup_count = 0

        for row in rows:
            at = row.get('acctType', 'Unknown')
            acct_counts[at] = acct_counts.get(at, 0) + 1
            if row.get('Status') == '⚠ Dup':
                dup_count += 1
            try:
                amt = float(row.get('amt', 0) or 0)
            except (ValueError, TypeError):
                amt = 0.0
            a_type = str(row.get('aType', '')).strip().lower()
            if a_type in ('debit', 'dr', 'd'):
                total_debit += amt
            else:
                total_credit += amt

        result = {
            'Transactions': len(rows),
            'TotalDebit':   round(total_debit, 2),
            'TotalCredit':  round(total_credit, 2),
            'NetBalance':   round(total_debit - total_credit, 2),
            'ByAcctType':   acct_counts,
        }
        if dup_count:
            result['Duplicates'] = dup_count
        return result

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'sources': {
                'llcExpRev': self._wk_fn('llcExpRev'),
                'llcAssets': self._wk_fn('llcAssets'),
            },
            'note': 'Read-only computed view. Cross-source duplicates flagged as ⚠ Dup.',
        }

    # ── interface stubs (required by llcMgmt route handlers) ─────────────────

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()
