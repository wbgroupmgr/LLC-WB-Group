'''
llcFormSchedM1 — IRS Schedule M-1 (Reconciliation of Income per Books with
Income per Return) aid view.

Schedule M-1 reconciles book income to tax return income.
Most adjustments require knowledge of tax-basis elections; items not
derivable from the FR database are marked blank.

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase

_FIXME = ''


class llcFormSchedM1(_llcIRSViewBase):

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        super().__init__(eSession)

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        net_income = self._isv('net_income')

        rows: List[Dict[str, Any]] = [
            {'line': '1',  'description': 'Net income (loss) per books  [FR computed]',
             'amount': net_income},
            {'line': '2',  'description': 'Income on return not recorded on books',
             'amount': _FIXME},
            {'line': '3',  'description': 'Guaranteed payments',
             'amount': _FIXME},
            {'line': '4',  'description': 'Expenses on books not on return: depreciation',
             'amount': _FIXME},
            {'line': '4b', 'description': 'Travel & entertainment excess',
             'amount': _FIXME},
            {'line': '4c', 'description': 'Other expenses on books not on return',
             'amount': _FIXME},
            {'line': '5',  'description': 'Income on books not on return (tax-exempt income, etc.)',
             'amount': _FIXME},
            {'line': '6',  'description': 'Deductions on return not on books (excess depreciation, etc.)',
             'amount': _FIXME},
            {'line': '7',  'description': 'Income (loss) per return (lines 1+2+3+4−5−6)  '
                           '[Simplified = Line 1; adjust above items for accuracy]',
             'amount': net_income},
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        return {
            'Net Income (Books)': self._isv('net_income'),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Schedule M-1 aid. Book net income from FR database — '
                'identical to Form1065_FILL.pdf M-1 value. '
                'Adjustments marked blank require manual entry.'
            ),
        }
