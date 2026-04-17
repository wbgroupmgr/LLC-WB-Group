'''
llcFormSchedL — IRS Schedule L (Balance Sheet per Books) aid.

Mirrors the Balance Sheet data in the format expected by Form 1065 Schedule L.
Schedule L requires beginning-of-year and end-of-year balances.
Beginning balances are FIXME placeholders (need prior-year data).
End-of-year balances come from the computed Balance Sheet.

Columns: line, description, beg_debit, beg_credit, end_debit, end_credit

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List

from uillc.llcReportEngine import llcReportEngine

_FIXME = ''


class llcFormSchedL:

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def object_name(self) -> str:
        return self.__class__.__name__

    # ── helpers ───────────────────────────────────────────────────────────────

    def _bs_by_acct(self) -> Dict[str, Dict[str, float]]:
        '''Return {acct: {Debit, Credit, Balance}} from the current BS.'''
        rows, _ = self.engine.buildBS()
        result = {}
        for r in rows:
            if r.get('acctType') == 'TOTAL':
                continue
            result[r.get('acct', '')] = {
                'Debit':   r.get('Debit',   0),
                'Credit':  r.get('Credit',  0),
                'Balance': r.get('Balance', 0),
            }
        return result

    def _bs_type_total(self, acct_type: str, rows: List[Dict]) -> Dict[str, float]:
        d = sum(r.get('Debit', 0)   for r in rows if r.get('acctType') == acct_type)
        c = sum(r.get('Credit', 0)  for r in rows if r.get('acctType') == acct_type)
        return {'Debit': round(d, 2), 'Credit': round(c, 2), 'Balance': round(d - c, 2)}

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Return Schedule L formatted rows.
        {section, line, description, beg_balance, end_balance}
        '''
        bs_rows, _ = self.engine.buildBS()

        # Build end-of-year totals by acctType
        asset_end   = self._bs_type_total('Asset',     bs_rows)
        liab_end    = self._bs_type_total('Liability', bs_rows)
        equity_end  = self._bs_type_total('Equity',    bs_rows)

        rows: List[Dict[str, Any]] = [
            # Assets
            {'section': 'Assets',             'line': '1',  'description': 'Cash',                               'beg_balance': _FIXME, 'end_balance': 0},
            {'section': 'Assets',             'line': '2a', 'description': 'Trade notes/accounts receivable',    'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '2b', 'description': 'Less allowance for bad debts',       'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '3',  'description': 'Inventories',                        'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '4',  'description': 'U.S. government obligations',        'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '5',  'description': 'Tax-exempt securities',              'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '6',  'description': 'Other current assets',               'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '7',  'description': 'Loans to partners',                  'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '8',  'description': 'Mortgage/real estate loans',         'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '9',  'description': 'Other investments',                  'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '10a','description': 'Buildings & other fixed assets',     'beg_balance': _FIXME, 'end_balance': asset_end['Debit']},
            {'section': 'Assets',             'line': '10b','description': 'Less accumulated depreciation',      'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '11', 'description': 'Depletable assets',                  'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '12', 'description': 'Land (net of amortization)',         'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '13', 'description': 'Intangible assets',                  'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '14', 'description': 'Other assets',                       'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets',             'line': '15', 'description': 'Total assets',                       'beg_balance': _FIXME, 'end_balance': asset_end['Balance']},

            # Liabilities & Capital
            {'section': 'Liabilities',        'line': '16', 'description': 'Accounts payable',                   'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities',        'line': '17', 'description': 'Mortgages/notes payable < 1 yr',     'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities',        'line': '18', 'description': 'Other current liabilities',          'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities',        'line': '19', 'description': 'All nonrecourse loans',              'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities',        'line': '20', 'description': 'Loans from partners',                'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities',        'line': '21', 'description': 'Mortgages/notes payable ≥ 1 yr',     'beg_balance': _FIXME, 'end_balance': liab_end['Balance']},
            {'section': 'Liabilities',        'line': '22', 'description': 'Other liabilities',                  'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities',        'line': '23', 'description': 'Partners\' capital accounts',        'beg_balance': _FIXME, 'end_balance': equity_end['Balance']},
            {'section': 'Liabilities',        'line': '24', 'description': 'Total liabilities & capital',        'beg_balance': _FIXME, 'end_balance': round(liab_end['Balance'] + equity_end['Balance'], 2)},
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        _, check = self.engine.buildBS()
        return {
            'Assets':      check.get('asset',     0),
            'Liabilities': check.get('liability', 0),
            'Equity':      check.get('equity',    0),
            'Balanced':    str(check.get('balanced', '?')),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Schedule L aid. End-of-year balances from GL. '
                'Beginning-of-year balances marked FIXME — need prior-year data.'
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
