'''
llcFormSchedL — IRS Schedule L (Balance Sheet per Books) aid.

Mirrors the Balance Sheet data in the format expected by Form 1065 Schedule L.
Schedule L requires beginning-of-year and end-of-year balances.
Beginning balances are blank (need prior-year data).
End-of-year balances come from the official FR Balance Sheet database.

Columns: section, line, description, beg_balance, end_balance

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase

_FIXME = ''


class llcFormSchedL(_llcIRSViewBase):

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        super().__init__(eSession)

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Return Schedule L formatted rows.
        {section, line, description, beg_balance, end_balance}
        '''
        # Assets
        cash        = self._bsv('cash')
        ar          = self._bsv('ar')
        buildings   = self._bsv('buildings')
        accum_depr  = self._bsv('accum_depr')
        land        = self._bsv('land')
        other_asset = self._bsv('other_assets')
        total_asset = self._bsv('total_assets')

        # Liabilities
        payables    = self._bsv('payables')
        mortgage    = self._bsv('mortgage')
        other_liab  = self._bsv('other_liab')
        total_equity= self._bsv('total_equity')
        total_l_c   = self._bsv('total_liab_capital') or round(
            payables + mortgage + other_liab + total_equity, 2)

        rows: List[Dict[str, Any]] = [
            # Assets
            {'section': 'Assets', 'line': '1',   'description': 'Cash',
             'beg_balance': _FIXME, 'end_balance': cash},
            {'section': 'Assets', 'line': '2a',  'description': 'Trade notes/accounts receivable',
             'beg_balance': _FIXME, 'end_balance': ar or _FIXME},
            {'section': 'Assets', 'line': '2b',  'description': 'Less allowance for bad debts',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '3',   'description': 'Inventories',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '4',   'description': 'U.S. government obligations',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '5',   'description': 'Tax-exempt securities',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '6',   'description': 'Other current assets',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '7',   'description': 'Loans to partners',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '8',   'description': 'Mortgage/real estate loans',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '9',   'description': 'Other investments',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '10a', 'description': 'Buildings & other fixed assets  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': buildings},
            {'section': 'Assets', 'line': '10b', 'description': 'Less accumulated depreciation  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': accum_depr},
            {'section': 'Assets', 'line': '11',  'description': 'Depletable assets',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '12',  'description': 'Land (net of amortization)  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': land},
            {'section': 'Assets', 'line': '13',  'description': 'Intangible assets',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Assets', 'line': '14',  'description': 'Other assets  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': other_asset or _FIXME},
            {'section': 'Assets', 'line': '15',  'description': 'Total assets  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': total_asset},

            # Liabilities & Capital
            {'section': 'Liabilities', 'line': '16', 'description': 'Accounts payable  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': payables or _FIXME},
            {'section': 'Liabilities', 'line': '17', 'description': 'Mortgages/notes payable < 1 yr',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities', 'line': '18', 'description': 'Other current liabilities',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities', 'line': '19', 'description': 'All nonrecourse loans',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities', 'line': '20', 'description': 'Loans from partners',
             'beg_balance': _FIXME, 'end_balance': _FIXME},
            {'section': 'Liabilities', 'line': '21', 'description': 'Mortgages/notes payable ≥ 1 yr  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': mortgage},
            {'section': 'Liabilities', 'line': '22', 'description': 'Other liabilities  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': other_liab or _FIXME},
            {'section': 'Liabilities', 'line': '23', 'description': "Partners' capital accounts  [FR computed]",
             'beg_balance': _FIXME, 'end_balance': total_equity},
            {'section': 'Liabilities', 'line': '24', 'description': 'Total liabilities & capital  [FR computed]',
             'beg_balance': _FIXME, 'end_balance': total_l_c},
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        return {
            'Assets':      self._bsv('total_assets'),
            'Liabilities': round(self._bsv('payables') + self._bsv('mortgage') + self._bsv('other_liab'), 2),
            'Equity':      self._bsv('total_equity'),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Schedule L aid. End-of-year balances from FR database — '
                'identical to Form1065_FILL.pdf Schedule L values. '
                'Beginning-of-year balances blank — need prior-year data.'
            ),
        }
