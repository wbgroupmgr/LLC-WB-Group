'''
llcFormSchedM2 — IRS Schedule M-2 (Analysis of Partners' Capital Accounts) aid.

Tracks changes in partners' aggregate capital accounts during the year.
Capital account beginning balance requires prior-year data (FIXME).
Net income / (loss) from Schedule M-1 (line 7) is used as the current-year addition.
Distributions are FIXME.

Columns: line, description, amount

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List

from uillc.llcReportEngine import llcReportEngine

_FIXME = ''


class llcFormSchedM2:

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
            {'line': '1',  'description': 'Balance at beginning of year',                     'amount': _FIXME},
            {'line': '2',  'description': 'Capital contributed — cash',                       'amount': _FIXME},
            {'line': '3',  'description': 'Capital contributed — property',                   'amount': _FIXME},
            {'line': '4',  'description': 'Net income (loss) per books (Sch M-1, line 1)',    'amount': net_income},
            {'line': '5',  'description': 'Other increases (itemize)',                        'amount': _FIXME},
            {'line': '6',  'description': 'Total of lines 1 through 5',                       'amount': net_income},   # simplified
            {'line': '7',  'description': 'Distributions — cash',                             'amount': _FIXME},
            {'line': '8',  'description': 'Distributions — property',                         'amount': _FIXME},
            {'line': '9',  'description': 'Other decreases (itemize)',                        'amount': _FIXME},
            {'line': '10', 'description': 'Total of lines 7 through 9',                      'amount': _FIXME},
            {'line': '11', 'description': 'Balance at end of year (line 6 less line 10)',     'amount': net_income},   # simplified
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
                'IRS Schedule M-2 aid. Net income from GL. '
                'Beginning balance and distributions marked FIXME.'
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
