'''
llcForm1065SchKPg5 — IRS Form 1065, Schedule K (Page 5).
Partners' Distributive Share Items — total partnership amounts, Lines 1–23.

Field IDs f1–f52 within this page.
NAMESPACE maps every fID to "Form1065.Pg5.<SectionName>".

Key auto-computed lines (from FR database — same as FILL PDF):
  Line 1  — Ordinary business income = net_income − rent_income
  Line 2  — Net rental real estate income (IS.rent_income)
  Line 5  — Interest income (IS.interest_income)
  Line 13d — Total deductions (IS.total_expenses)
  Line 14a — SE earnings (ordinary income only; rental excluded under §1402)
  Line 19a — Cash distributions (sum of max(0, NI) × partner pcts)
  Line 17a — Post-1986 depreciation (IS.depreciation, for reference)

CPA note: Real estate rental LLCs report income on Line 2, not Line 1.
§469 passive rules apply to rental activities.

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

Reference: IRS Form 1065 (2024), Schedule K, Lines 1–23.
Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase


class llcForm1065SchKPg5(_llcIRSViewBase):

    # ── Page-level field namespace ─────────────────────────────────────────
    NAMESPACE: Dict[str, str] = {
        # Income Items
        "f1":  "Form1065.Pg5.SchK.Header",
        "f2":  "Form1065.Pg5.SchK.Income",   # L1  ordinary business income
        "f3":  "Form1065.Pg5.SchK.Income",   # L2  rental RE income
        "f4":  "Form1065.Pg5.SchK.Income",   # L3a other rental gross
        "f5":  "Form1065.Pg5.SchK.Income",   # L3b other rental expenses
        "f6":  "Form1065.Pg5.SchK.Income",   # L3c net other rental
        "f7":  "Form1065.Pg5.SchK.Income",   # L4a guaranteed pmts to capital
        "f8":  "Form1065.Pg5.SchK.Income",   # L4b guaranteed pmts to services
        "f9":  "Form1065.Pg5.SchK.Income",   # L4c guaranteed pmts total
        "f10": "Form1065.Pg5.SchK.Income",   # L5  interest income
        "f11": "Form1065.Pg5.SchK.Income",   # L6a ordinary dividends
        "f12": "Form1065.Pg5.SchK.Income",   # L6b qualified dividends
        "f13": "Form1065.Pg5.SchK.Income",   # L6c dividend equivalents
        "f14": "Form1065.Pg5.SchK.Income",   # L7  royalties
        "f15": "Form1065.Pg5.SchK.Income",   # L8  net ST cap gain/loss
        "f16": "Form1065.Pg5.SchK.Income",   # L9a net LT cap gain/loss
        "f17": "Form1065.Pg5.SchK.Income",   # L9b collectibles gain
        "f18": "Form1065.Pg5.SchK.Income",   # L9c unrecaptured §1250 gain
        "f19": "Form1065.Pg5.SchK.Income",   # L10 net §1231 gain/loss
        "f20": "Form1065.Pg5.SchK.Income",   # L11 other income (loss)
        # Deductions
        "f21": "Form1065.Pg5.SchK.Deductions",  # header
        "f22": "Form1065.Pg5.SchK.Deductions",  # L12 §179 deduction
        "f23": "Form1065.Pg5.SchK.Deductions",  # L13a contributions
        "f24": "Form1065.Pg5.SchK.Deductions",  # L13b investment interest expense
        "f25": "Form1065.Pg5.SchK.Deductions",  # L13c(1) §59(e) type
        "f26": "Form1065.Pg5.SchK.Deductions",  # L13c(2) §59(e) amount
        "f27": "Form1065.Pg5.SchK.Deductions",  # L13d other deductions
        # Self-Employment
        "f28": "Form1065.Pg5.SchK.SelfEmployment",
        "f29": "Form1065.Pg5.SchK.SelfEmployment",  # L14a SE earnings
        "f30": "Form1065.Pg5.SchK.SelfEmployment",  # L14b gross farming/fishing
        "f31": "Form1065.Pg5.SchK.SelfEmployment",  # L14c gross nonfarm income
        # Credits
        "f32": "Form1065.Pg5.SchK.Credits",
        "f33": "Form1065.Pg5.SchK.Credits",    # L15
        # AMT Items
        "f34": "Form1065.Pg5.SchK.AMT",
        "f35": "Form1065.Pg5.SchK.AMT",   # L17a post-1986 depreciation adj
        "f36": "Form1065.Pg5.SchK.AMT",   # L17b adjusted gain/loss
        "f37": "Form1065.Pg5.SchK.AMT",   # L17c depletion
        "f38": "Form1065.Pg5.SchK.AMT",   # L17d oil/gas gross income
        "f39": "Form1065.Pg5.SchK.AMT",   # L17e oil/gas deductions
        "f40": "Form1065.Pg5.SchK.AMT",   # L17f other AMT
        # Tax-Exempt Income
        "f41": "Form1065.Pg5.SchK.TaxExempt",
        "f42": "Form1065.Pg5.SchK.TaxExempt",  # L18a tax-exempt interest
        "f43": "Form1065.Pg5.SchK.TaxExempt",  # L18b other tax-exempt income
        "f44": "Form1065.Pg5.SchK.TaxExempt",  # L18c nondeductible expenses
        # Distributions
        "f45": "Form1065.Pg5.SchK.Distributions",
        "f46": "Form1065.Pg5.SchK.Distributions",  # L19a cash/securities
        "f47": "Form1065.Pg5.SchK.Distributions",  # L19b §737
        "f48": "Form1065.Pg5.SchK.Distributions",  # L19c other property
        # Other Information
        "f49": "Form1065.Pg5.SchK.OtherInfo",
        "f50": "Form1065.Pg5.SchK.OtherInfo",  # L20 other info
        "f51": "Form1065.Pg5.SchK.OtherInfo",  # L21 foreign taxes
        "f52": "Form1065.Pg5.SchK.OtherInfo",  # L22 more than one activity (at-risk)
    }

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        super().__init__(eSession)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _row(self, fid: str, line: str, description: str, amount) -> Dict[str, Any]:
        return {
            'fID':         fid,
            'line':        line,
            'location':    self.NAMESPACE.get(fid, ''),
            'description': description,
            'amount':      amount,
        }

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        net_income   = self._isv('net_income')
        rent_inc     = self._isv('rent_income')
        interest_inc = self._isv('interest_income')
        total_exp    = self._isv('total_expenses')
        depr         = self._isv('depreciation')
        ordinary_ni  = round(net_income - rent_inc, 2)

        # Distributions: sum per-partner max(0, NI) × pct
        alloc        = self._per_partner_alloc()
        distributions = round(sum(a['distrib'] for a in alloc), 2)

        R = self._row
        rows: List[Dict[str, Any]] = [

            # ── Income Items ─────────────────────────────────────────────────
            R('f1',  '',    "Schedule K — Partners' Distributive Share Items (Lines 1–11). "
                            "Income (Loss) Items", ''),

            R('f2',  '1',   'Ordinary business income (loss)  '
                            '(Form 1065, Line 22 less rental income; for a rental LLC '
                            'recurring rental income is reported on Line 2)  [FR computed]',
                             ordinary_ni),

            R('f3',  '2',   'Net rental real estate income (loss)  '
                            '[FR IS.rent_income]  [FR computed]',
                             rent_inc),

            R('f4',  '3a',  'Other gross rental income (loss)  '
                            '(non-real-estate rental; e.g., equipment)',
                             ''),

            R('f5',  '3b',  'Expenses from other rental activities',  ''),

            R('f6',  '3c',  'Other net rental income (loss)  (Line 3a minus Line 3b)', ''),

            R('f7',  '4a',  'Guaranteed payments to capital',          ''),

            R('f8',  '4b',  'Guaranteed payments to services', ''),

            R('f9',  '4c',  'Guaranteed payments — total  (Lines 4a + 4b)', ''),

            R('f10', '5',   'Interest income  [FR IS.interest_income]',
                             interest_inc if interest_inc else ''),

            R('f11', '6a',  'Ordinary dividends',  ''),
            R('f12', '6b',  'Qualified dividends',  ''),
            R('f13', '6c',  'Dividend equivalents', ''),
            R('f14', '7',   'Royalties',             ''),

            R('f15', '8',   'Net short-term capital gain (loss)  (Schedule D, Part I, line 11)', ''),
            R('f16', '9a',  'Net long-term capital gain (loss)  (Schedule D, Part II, line 12)', ''),
            R('f17', '9b',  'Collectibles (28%) gain (loss)',  ''),

            R('f18', '9c',  'Unrecaptured §1250 gain  '
                            '(arises on sale of depreciable real property; '
                            'enter the lesser of accumulated §1250 depreciation or LTCG)',
                             ''),

            R('f19', '10',  'Net §1231 gain (loss) — other than due to casualty or theft  '
                            '(Form 4797, Part I)',  ''),

            R('f20', '11',  'Other income (loss) — attach statement', ''),

            # ── Deductions ───────────────────────────────────────────────────
            R('f21', '',    'Schedule K — Deductions (Lines 12–13d). Deduction Items', ''),

            R('f22', '12',  'Section 179 deduction  '
                            '(Form 4562; limited to §179 taxable income)', ''),

            R('f23', '13a', 'Contributions (charitable; attach Form 8283 if non-cash > $500)', ''),

            R('f24', '13b', 'Investment interest expense  (Form 4952)', ''),

            R('f25', '13c(1)', '§59(e)(2) expenditures: Type',   ''),
            R('f26', '13c(2)', '§59(e)(2) expenditures: Amount', ''),

            R('f27', '13d', 'Other deductions  [FR IS.total_expenses]  [FR computed]',
                             total_exp),

            # ── Self-Employment ──────────────────────────────────────────────
            R('f28', '',    'Schedule K — Self-Employment (Line 14). SE Earnings', ''),

            R('f29', '14a', 'Net earnings (loss) from self-employment  '
                            '(general partners\' share of §1402 SE income; '
                            'rental income is EXCLUDED from SE under §1402(a)(1))',
                             ordinary_ni if ordinary_ni > 0 else 0),

            R('f30', '14b', 'Gross farming or fishing income', ''),
            R('f31', '14c', 'Gross nonfarm income',            ''),

            # ── Credits ──────────────────────────────────────────────────────
            R('f32', '',    'Schedule K — Credits (Line 15)', ''),

            R('f33', '15',  'Credits  (attach Form 3800 or applicable credit form; '
                            'e.g., §45L energy credit for qualified residential buildings)', ''),

            # ── AMT Items ────────────────────────────────────────────────────
            R('f34', '',    'Schedule K — AMT Items (Line 17)', ''),

            R('f35', '17a', 'Post-1986 depreciation adjustment  '
                            f'[FR IS.depreciation: ${depr:,.2f}]', ''),

            R('f36', '17b', 'Adjusted gain or loss', ''),
            R('f37', '17c', 'Depletion (other than oil and gas)', ''),
            R('f38', '17d', 'Oil, gas, and geothermal — gross income', ''),
            R('f39', '17e', 'Oil, gas, and geothermal — deductions',   ''),
            R('f40', '17f', 'Other AMT items', ''),

            # ── Tax-Exempt Income ─────────────────────────────────────────────
            R('f41', '',    'Schedule K — Tax-Exempt Income & Nondeductible Expenses (Line 18)', ''),
            R('f42', '18a', 'Tax-exempt interest income', ''),
            R('f43', '18b', 'Other tax-exempt income',    ''),
            R('f44', '18c', 'Nondeductible expenses',     ''),

            # ── Distributions ─────────────────────────────────────────────────
            R('f45', '',    'Schedule K — Distributions (Line 19)', ''),

            R('f46', '19a', 'Cash and marketable securities distributions  '
                            f'[FR computed: max(0, NI) × partner pcts = ${distributions:,.2f}]',
                             distributions),

            R('f47', '19b', 'Distribution subject to §737  '
                            '(appreciated property within 7 years of contribution)', ''),

            R('f48', '19c', 'Other property distributions', ''),

            # ── Other Information ─────────────────────────────────────────────
            R('f49', '',    'Schedule K — Other Information (Lines 20–22)', ''),

            R('f50', '20',  'Other information  '
                            '(attach statement; e.g., §199A QBI for rental — requires '
                            'rental safe-harbor or self-rental requirements)', ''),

            R('f51', '21',  'Foreign taxes paid or accrued  '
                            '(Form 1116 / Form 1118 credit basis)', ''),

            R('f52', '22',  'More than one activity for at-risk purposes?  '
                            '(attach statement if Yes)', ''),
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        alloc = self._per_partner_alloc()
        return {
            'Line 2 Rental Income': self._isv('rent_income'),
            'Total Deductions':     self._isv('total_expenses'),
            'Net Income':           self._isv('net_income'),
            'Distributions':        round(sum(a['distrib'] for a in alloc), 2),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'namespace':  self.NAMESPACE,
            'note': (
                'IRS Form 1065 (2024) Schedule K, Lines 1–22. '
                'FR-computed values match Form1065_FILL.pdf exactly. '
                'Line 2 rental income from IS.rent_income. '
                'Line 1 ordinary income = net income minus rental income. '
                'Lines 9c (§1250 gain), 12 (§179), 17a (AMT) require CPA input. '
                'Consult a qualified tax professional before filing.'
            ),
        }
