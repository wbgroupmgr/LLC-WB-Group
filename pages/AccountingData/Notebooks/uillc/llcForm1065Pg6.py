'''
llcForm1065Pg6 — IRS Form 1065, Page 6.
Combined view of three schedules on page 6 of Form 1065 (2024):

  Schedule L  — Balance Sheet per Books (22 lines)
  Schedule M-1 — Reconciliation of Income per Books with Income per Return
  Schedule M-2 — Analysis of Partners' Capital Accounts

Field IDs f1–f47 within this page.
NAMESPACE maps every fID to "Form1065.Pg6.<ScheduleName>".

End-of-year balances are computed from the official FR database.
Beginning-of-year balances default to "" (blank — require prior-year data).
Adjustment lines in M-1 default to "" (require CPA review).

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

CPA note: §6221(b) small partnerships meeting ALL four conditions of
Schedule B Q6 may not be required to complete Schedules L, M-1, or M-2.

Reference: IRS Form 1065 (2024), Page 6.
Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase

_ZERO = 0


class llcForm1065Pg6(_llcIRSViewBase):

    # ── Page-level field namespace ─────────────────────────────────────────
    NAMESPACE: Dict[str, str] = {
        # Schedule L — Balance Sheet
        "f1":  "Form1065.Pg6.SchedL",     # header
        "f2":  "Form1065.Pg6.SchedL",     # L1  cash
        "f3":  "Form1065.Pg6.SchedL",     # L2a AR
        "f4":  "Form1065.Pg6.SchedL",     # L2b allowance for bad debts
        "f5":  "Form1065.Pg6.SchedL",     # L3  inventories
        "f6":  "Form1065.Pg6.SchedL",     # L4  US govt obligations
        "f7":  "Form1065.Pg6.SchedL",     # L5  tax-exempt securities
        "f8":  "Form1065.Pg6.SchedL",     # L6  other current assets
        "f9":  "Form1065.Pg6.SchedL",     # L7  mortgage/RE loans (asset side)
        "f10": "Form1065.Pg6.SchedL",     # L8  other investments
        "f11": "Form1065.Pg6.SchedL",     # L9a buildings/depreciable assets
        "f12": "Form1065.Pg6.SchedL",     # L9b less accumulated depreciation
        "f13": "Form1065.Pg6.SchedL",     # L10a depletable assets
        "f14": "Form1065.Pg6.SchedL",     # L10b less accumulated depletion
        "f15": "Form1065.Pg6.SchedL",     # L11 land
        "f16": "Form1065.Pg6.SchedL",     # L12a intangibles
        "f17": "Form1065.Pg6.SchedL",     # L12b less accumulated amortization
        "f18": "Form1065.Pg6.SchedL",     # L13 other assets
        "f19": "Form1065.Pg6.SchedL",     # L14 total assets
        "f20": "Form1065.Pg6.SchedL",     # L15 accounts payable
        "f21": "Form1065.Pg6.SchedL",     # L16 mortgages < 1 yr
        "f22": "Form1065.Pg6.SchedL",     # L17 other current liabilities
        "f23": "Form1065.Pg6.SchedL",     # L18 nonrecourse loans
        "f24": "Form1065.Pg6.SchedL",     # L19 mortgages ≥ 1 yr
        "f25": "Form1065.Pg6.SchedL",     # L20 other liabilities
        "f26": "Form1065.Pg6.SchedL",     # L21 partners' capital
        "f27": "Form1065.Pg6.SchedL",     # L22 total liab + capital
        # Schedule M-1
        "f28": "Form1065.Pg6.SchedM1",    # M1-1 net income per books
        "f29": "Form1065.Pg6.SchedM1",    # M1-2 income on return not in books
        "f30": "Form1065.Pg6.SchedM1",    # M1-3 guaranteed payments
        "f31": "Form1065.Pg6.SchedM1",    # M1-4a depreciation excess
        "f32": "Form1065.Pg6.SchedM1",    # M1-4b T&E disallowed
        "f33": "Form1065.Pg6.SchedM1",    # M1-4c other book not return
        "f34": "Form1065.Pg6.SchedM1",    # M1-5 book income not on return
        "f35": "Form1065.Pg6.SchedM1",    # M1-6 deductions on return not in books
        "f36": "Form1065.Pg6.SchedM1",    # M1-7 income per return
        # Schedule M-2
        "f37": "Form1065.Pg6.SchedM2",    # M2-1 beginning capital
        "f38": "Form1065.Pg6.SchedM2",    # M2-2 cash contributions
        "f39": "Form1065.Pg6.SchedM2",    # M2-3 property contributions
        "f40": "Form1065.Pg6.SchedM2",    # M2-4 net income per books
        "f41": "Form1065.Pg6.SchedM2",    # M2-5 other increases
        "f42": "Form1065.Pg6.SchedM2",    # M2-6 subtotal
        "f43": "Form1065.Pg6.SchedM2",    # M2-7 distributions cash
        "f44": "Form1065.Pg6.SchedM2",    # M2-8 distributions property
        "f45": "Form1065.Pg6.SchedM2",    # M2-9 other decreases
        "f46": "Form1065.Pg6.SchedM2",    # M2-10 total decreases
        "f47": "Form1065.Pg6.SchedM2",    # M2-11 ending capital
    }

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        super().__init__(eSession)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _row(self, fid: str, line: str, description: str, beg_balance, end_balance) -> Dict[str, Any]:
        return {
            'fID':         fid,
            'line':        line,
            'location':    self.NAMESPACE.get(fid, ''),
            'description': description,
            'beg_balance': beg_balance,
            'end_balance': end_balance,
        }

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        # IS values
        net_income    = self._isv('net_income')

        # BS values
        cash_bal      = self._bsv('cash')
        ar_bal        = self._bsv('ar')
        buildings     = self._bsv('buildings')
        accum_depr    = self._bsv('accum_depr')
        land_bal      = self._bsv('land')
        other_asset   = self._bsv('other_assets')
        total_assets  = self._bsv('total_assets')
        payables      = self._bsv('payables')
        mortgage_bal  = self._bsv('mortgage')
        other_liab    = self._bsv('other_liab')
        partner_cap   = self._bsv('total_equity')
        total_l_c     = self._bsv('total_liab_capital') or round(
            payables + mortgage_bal + other_liab + partner_cap, 2)

        # M-2 values
        contributions = round(float(self._owners_agg.get('cash_contributions', 0.0)), 2)
        alloc         = self._per_partner_alloc()
        distributions = round(sum(a['distrib'] for a in alloc), 2)

        R = self._row   # shorthand

        rows: List[Dict[str, Any]] = [

            # ════ Schedule L — Balance Sheet per Books ════════════════════════
            R('f1',  '',   'Schedule L — Balance Sheet per Books  '
                           '(beginning = blank — requires prior-year data; end = FR computed)',
                           '', ''),

            # Assets
            R('f2',  '1',   'Cash  [FR computed]',                                  '', cash_bal),
            R('f3',  '2a',  'Trade notes and accounts receivable  [FR computed]',   '', ar_bal or _ZERO),
            R('f4',  '2b',  'Less allowance for bad debts',                          '', _ZERO),
            R('f5',  '3',   'Inventories',                                            '', _ZERO),
            R('f6',  '4',   'U.S. government obligations',                            '', _ZERO),
            R('f7',  '5',   'Tax-exempt securities',                                  '', _ZERO),
            R('f8',  '6',   'Other current assets  (attach statement)',               '', ''),
            R('f9',  '7',   'Mortgage and real estate loans  (asset side)',           '', _ZERO),
            R('f10', '8',   'Other investments  (attach statement)',                  '', _ZERO),
            R('f11', '9a',  'Buildings and other depreciable assets  [FR BS.buildings]',
                             '', buildings),
            R('f12', '9b',  'Less accumulated depreciation  [FR BS.accum_depr]',
                             '', accum_depr),
            R('f13', '10a', 'Depletable assets',                                     '', _ZERO),
            R('f14', '10b', 'Less accumulated depletion',                            '', _ZERO),
            R('f15', '11',  'Land (net of any amortization)  [FR BS.land]',          '', land_bal),
            R('f16', '12a', 'Intangible assets (amortizable only)',                  '', _ZERO),
            R('f17', '12b', 'Less accumulated amortization',                         '', _ZERO),
            R('f18', '13',  'Other assets  (attach statement)  [FR BS.other_assets]', '', other_asset or _ZERO),
            R('f19', '14',  'Total assets  [FR computed]',                           '', total_assets),

            # Liabilities and Capital
            R('f20', '15',  'Accounts payable  [FR BS.payables]',                   '', payables or _ZERO),
            R('f21', '16',  'Mortgages, notes, bonds payable in less than 1 year',  '', ''),
            R('f22', '17',  'Other current liabilities  (attach statement)',         '', ''),
            R('f23', '18',  'All nonrecourse loans',                                  '', _ZERO),
            R('f24', '19',  'Mortgages, notes, bonds payable in 1 year or more  [FR BS.mortgage]',
                             '', mortgage_bal),
            R('f25', '20',  'Other liabilities  [FR BS.other_liab]',                '', other_liab or _ZERO),
            R('f26', '21',  "Partners' capital accounts  [FR BS.total_equity]",     '', partner_cap),
            R('f27', '22',  'Total liabilities and capital  [FR computed]',         '', total_l_c),

            # ════ Schedule M-1 — Reconciliation of Income per Books vs Return ═
            R('f28', '1',   'Net income (loss) per books  [FR computed]',        '', net_income),
            R('f29', '2',   'Income on return not recorded on books this year (attach statement)', '', ''),
            R('f30', '3',   'Guaranteed payments (other than health insurance)',  '', ''),
            R('f31', '4a',  'Depreciation excess of tax over book depreciation', '', ''),
            R('f32', '4b',  'Travel and entertainment (50% disallowed under §274)', '', ''),
            R('f33', '4c',  'Other expenses recorded on books not on return',    '', ''),
            R('f34', '5',   'Income recorded on books not on return this year    '
                            '(tax-exempt interest, unrealized appreciation, etc.)', '', ''),
            R('f35', '6',   'Deductions on return not charged against book income  '
                            '(§179 excess, bonus depreciation, etc.)',             '', ''),
            R('f36', '7',   'Income (loss) per return  (Line 1 + 2 + 3 + 4 − 5 − 6)  '
                            '[Simplified = Line 1; adjust above items for accuracy]',
                             '', net_income),

            # ════ Schedule M-2 — Analysis of Partners' Capital Accounts ════════
            R('f37', '1',  'Balance at beginning of year  (prior-year ending capital)', '', ''),
            R('f38', '2',  'Capital contributed: cash  [FR llcOwners capital_contributed]',
                            '', contributions or _ZERO),
            R('f39', '3',  'Capital contributed: property',                     '', ''),
            R('f40', '4',  'Net income (loss) per books  (from M-1, Line 1)  [FR computed]',
                            '', net_income),
            R('f41', '5',  'Other increases  (attach explanation)',              '', ''),
            R('f42', '6',  'Subtotal  (Lines 1 through 5)',                      '', round(contributions + net_income, 2)),
            R('f43', '7',  'Distributions: cash  [FR computed: max(0,NI) × partner pcts]',
                            '', distributions),
            R('f44', '8',  'Distributions: property',                           '', _ZERO),
            R('f45', '9',  'Other decreases  (attach explanation)',              '', ''),
            R('f46', '10', 'Total of Lines 7, 8, and 9',                        '', distributions),
            R('f47', '11', "Balance at end of year  [FR BS.total_equity]",
                            '', partner_cap),
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        alloc = self._per_partner_alloc()
        return {
            'Total Assets':  self._bsv('total_assets'),
            'Total Equity':  self._bsv('total_equity'),
            'Net Income':    self._isv('net_income'),
            'Distributions': round(sum(a['distrib'] for a in alloc), 2),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'namespace':  self.NAMESPACE,
            'note': (
                'IRS Form 1065 (2024), Page 6. '
                'FR-computed values match Form1065_FILL.pdf exactly. '
                'Schedule L: end-of-year from FR BS; beginning = blank (prior-year data needed). '
                'Schedule M-1: book NI from FR IS; tax adjustments blank. '
                'Schedule M-2: contributions/NI/distributions FR-computed; beginning capital blank. '
                'Consult a qualified CPA before filing.'
            ),
        }
