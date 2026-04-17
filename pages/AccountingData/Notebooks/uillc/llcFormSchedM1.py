'''
llcFormSchedM1 — IRS Schedule M-1 (Reconciliation of Income per Books with
Income per Return) aid view.

Schedule M-1 reconciles book income to tax return income.
Most adjustments require knowledge of tax-basis elections; items not
derivable from the GL are marked FIXME.

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List

from uillc.llcReportEngine import llcReportEngine

_FIXME = ''


class llcFormSchedM1:

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)

    def object_name(self) -> str:
        return self.__class__.__name__

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        _, s = self.engine.buildIS()
        net_income = round(s.get('net_income', 0), 2)

        rows: List[Dict[str, Any]] = [
            {'line': '1',  'description': 'Net income (loss) per books',                                        'amount': net_income},
            {'line': '2',  'description': 'Income on return not recorded on books',                             'amount': _FIXME},
            {'line': '3',  'description': 'Guaranteed payments',                                               'amount': _FIXME},
            {'line': '4',  'description': 'Expenses on books not on return: depreciation',                     'amount': _FIXME},
            {'line': '4b', 'description': 'Travel & entertainment excess',                                     'amount': _FIXME},
            {'line': '4c', 'description': 'Other expenses on books not on return',                             'amount': _FIXME},
            {'line': '5',  'description': 'Income on books not on return (tax-exempt income, etc.)',           'amount': _FIXME},
            {'line': '6',  'description': 'Deductions on return not on books (excess depreciation, etc.)',     'amount': _FIXME},
            {'line': '7',  'description': 'Income (loss) per return (lines 1+2+3+4−5−6)',                      'amount': net_income},  # simplified — FIXME with adjustments
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        _, s = self.engine.buildIS()
        return {
            'Net Income (Books)': round(s.get('net_income', 0), 2),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Schedule M-1 aid. Book net income from GL. '
                'Adjustments marked FIXME require manual entry.'
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
