'''
llcFormSchedM2 — IRS Schedule M-2 (Analysis of Partners' Capital Accounts) aid.

Tracks changes in partners' aggregate capital accounts during the year.
Capital account beginning balance requires prior-year data (blank).
Net income from Schedule M-1 (line 7) is used as the current-year addition.
Cash distributions computed from max(0, NI) × partner pcts.

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

Columns: line, description, amount

Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase

_FIXME = ''


class llcFormSchedM2(_llcIRSViewBase):

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        super().__init__(eSession)

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        net_income    = self._isv('net_income')
        # Cash contributions: aggregate from owners profile
        contributions = round(float(self._owners_agg.get('cash_contributions', 0.0)), 2)
        # Distributions: sum of per-partner max(0, ni) × pct
        alloc         = self._per_partner_alloc()
        distributions = round(sum(a['distrib'] for a in alloc), 2)

        rows: List[Dict[str, Any]] = [
            {'line': '1',  'description': 'Balance at beginning of year',
             'amount': _FIXME},
            {'line': '2',  'description': 'Capital contributed — cash  [FR computed]',
             'amount': contributions or _FIXME},
            {'line': '3',  'description': 'Capital contributed — property',
             'amount': _FIXME},
            {'line': '4',  'description': 'Net income (loss) per books (Sch M-1, line 1)  [FR computed]',
             'amount': net_income},
            {'line': '5',  'description': 'Other increases (itemize)',
             'amount': _FIXME},
            {'line': '6',  'description': 'Total of lines 1 through 5  [simplified: lines 2+4]',
             'amount': round(contributions + net_income, 2)},
            {'line': '7',  'description': 'Distributions — cash  [FR computed: max(0,NI) × partner pcts]',
             'amount': distributions},
            {'line': '8',  'description': 'Distributions — property',
             'amount': _FIXME},
            {'line': '9',  'description': 'Other decreases (itemize)',
             'amount': _FIXME},
            {'line': '10', 'description': 'Total of lines 7 through 9',
             'amount': distributions},
            {'line': '11', 'description': 'Balance at end of year (line 6 less line 10)  [FR computed]',
             'amount': round(contributions + net_income - distributions, 2)},
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        alloc = self._per_partner_alloc()
        return {
            'Net Income (Books)': self._isv('net_income'),
            'Contributions':      round(float(self._owners_agg.get('cash_contributions', 0.0)), 2),
            'Distributions':      round(sum(a['distrib'] for a in alloc), 2),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Schedule M-2 aid. Net income from FR database — '
                'identical to Form1065_FILL.pdf M-2 values. '
                'Beginning balance blank (prior-year data needed).'
            ),
        }
