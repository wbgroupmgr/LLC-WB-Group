'''
llcForm1065 — IRS Form 1065 (U.S. Return of Partnership Income) aid view.

Provides a structured summary of the data needed to complete Form 1065.
Lines are sourced from the Income Statement (via llcReportEngine) where
available; FIXME placeholders mark items requiring manual entry or data
not yet modeled.

Reference: IRS Form 1065 (2024) lines 1–22 (ordinary income/loss section)
plus Schedule B questions and Schedule K aggregates.

Timestamp of last change: 2026.04.14
'''

from typing import Any, Dict, List

from uillc.llcReportEngine import llcReportEngine


_FIXME = 'FIXME'


class llcForm1065:

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

    def _is_summary(self) -> Dict[str, Any]:
        _, s = self.engine.buildIS()
        return s

    def _acct_total(self, acct_fragment: str, acct_type: str) -> float:
        '''Sum GL amounts for accounts matching the given acct fragment and type.'''
        rows = self.engine.getGLList(resolve_dups=True)
        total = 0.0
        for r in rows:
            if r.get('acctType', '') != acct_type:
                continue
            acct = r.get('acct', '')
            if acct_fragment.lower() not in acct.lower():
                continue
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            atype = str(r.get('aType', '')).strip().lower()
            total += amt if atype in ('debit', 'dr', 'd') else -amt
        return round(total, 2)

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Return Form 1065 line items as a list of {section, line, description, amount}.
        '''
        s = self._is_summary()
        gross_income  = round(s.get('income',  0), 2)
        total_expense = round(s.get('expense', 0), 2)
        net_income    = round(s.get('net_income', 0), 2)

        rows: List[Dict[str, Any]] = [
            # ── Income ──────────────────────────────────────────────────────
            {'section': 'Income',  'line': '1a',  'description': 'Gross receipts or sales',            'amount': gross_income},
            {'section': 'Income',  'line': '1b',  'description': 'Returns and allowances',             'amount': 0},
            {'section': 'Income',  'line': '1c',  'description': 'Net receipts (1a - 1b)',              'amount': gross_income},
            {'section': 'Income',  'line': '2',   'description': 'Cost of goods sold (Sch A)',         'amount': _FIXME},
            {'section': 'Income',  'line': '3',   'description': 'Gross profit',                       'amount': gross_income},
            {'section': 'Income',  'line': '4',   'description': 'Ordinary income from partnerships',  'amount': _FIXME},
            {'section': 'Income',  'line': '5',   'description': 'Net farm profit (loss)',              'amount': _FIXME},
            {'section': 'Income',  'line': '6',   'description': 'Net gain (loss) from Form 4797',     'amount': _FIXME},
            {'section': 'Income',  'line': '7',   'description': 'Other income (loss)',                 'amount': _FIXME},
            {'section': 'Income',  'line': '8',   'description': 'Total income (loss)',                 'amount': gross_income},

            # ── Deductions ──────────────────────────────────────────────────
            {'section': 'Deductions', 'line': '9',  'description': 'Salaries and wages',               'amount': self._acct_total('salary', 'Expense') or _FIXME},
            {'section': 'Deductions', 'line': '10', 'description': 'Guaranteed payments to partners',  'amount': _FIXME},
            {'section': 'Deductions', 'line': '11', 'description': 'Repairs and maintenance',          'amount': self._acct_total('maint', 'Expense') or _FIXME},
            {'section': 'Deductions', 'line': '12', 'description': 'Bad debts',                        'amount': _FIXME},
            {'section': 'Deductions', 'line': '13', 'description': 'Rent',                             'amount': _FIXME},
            {'section': 'Deductions', 'line': '14', 'description': 'Taxes and licenses',               'amount': self._acct_total('proptax', 'Expense') or _FIXME},
            {'section': 'Deductions', 'line': '15', 'description': 'Interest',                         'amount': self._acct_total('morgint', 'Expense') or _FIXME},
            {'section': 'Deductions', 'line': '16a', 'description': 'Depreciation (Form 4562)',        'amount': self._acct_total('deprec', 'Expense') or _FIXME},
            {'section': 'Deductions', 'line': '17', 'description': 'Depletion',                        'amount': _FIXME},
            {'section': 'Deductions', 'line': '18', 'description': 'Retirement plans',                 'amount': _FIXME},
            {'section': 'Deductions', 'line': '19', 'description': 'Employee benefit programs',        'amount': _FIXME},
            {'section': 'Deductions', 'line': '20', 'description': 'Other deductions (attach stmt)',   'amount': total_expense},
            {'section': 'Deductions', 'line': '21', 'description': 'Total deductions',                 'amount': total_expense},

            # ── Net Ordinary Income ──────────────────────────────────────────
            {'section': 'Net Income', 'line': '22', 'description': 'Ordinary business income (loss)', 'amount': net_income},
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        s = self._is_summary()
        return {
            'Gross Income': round(s.get('income',     0), 2),
            'Total Expense': round(s.get('expense',   0), 2),
            'Net Income':   round(s.get('net_income', 0), 2),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'note': (
                'IRS Form 1065 aid. Computed lines use double-entry GL data. '
                'Lines marked FIXME require manual entry or additional data.'
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
