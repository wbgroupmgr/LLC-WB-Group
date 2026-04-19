'''
llcForm1065 — IRS Form 1065 (U.S. Return of Partnership Income), Page 1.

Complete field map for Form 1065 Page 1 (2024):
  • Tax year header + entity identification (Lines A–K)
  • Income section (Lines 1a–8)
  • Deductions section (Lines 9–21)
  • Ordinary business income (Line 22)
  • Sign Here section
  • Paid Preparer Use Only section

Each field is assigned a sequential fID (f1…fn) within this page.
The NAMESPACE dict maps every fID to its IRS form location string:
  "Form1065.Pg1.<Section>"

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).
Lines computed from the official financial-report databases are filled automatically.
All other fields default to "" (blank) — fill before filing.

Reference: IRS Form 1065 (2024), Page 1.
Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase


class llcForm1065(_llcIRSViewBase):

    # ── Page-level field namespace ─────────────────────────────────────────
    NAMESPACE: Dict[str, str] = {
        # Tax Year Header
        "f1":  "Form1065.Pg1.TaxYear",
        "f2":  "Form1065.Pg1.TaxYear",
        "f3":  "Form1065.Pg1.TaxYear",
        "f4":  "Form1065.Pg1.TaxYear",
        # Entity Identification
        "f5":  "Form1065.Pg1.EntityInfo",
        "f6":  "Form1065.Pg1.EntityInfo",
        "f7":  "Form1065.Pg1.EntityInfo",
        "f8":  "Form1065.Pg1.EntityInfo",
        "f9":  "Form1065.Pg1.EntityInfo",
        "f10": "Form1065.Pg1.EntityInfo",
        # Line A — Check Applicable Boxes
        "f11": "Form1065.Pg1.LineA",
        "f12": "Form1065.Pg1.LineA",
        "f13": "Form1065.Pg1.LineA",
        "f14": "Form1065.Pg1.LineA",
        "f15": "Form1065.Pg1.LineA",
        "f16": "Form1065.Pg1.LineA",
        # Lines B–K
        "f17": "Form1065.Pg1.LinesB-K",
        "f18": "Form1065.Pg1.LinesB-K",
        "f19": "Form1065.Pg1.LinesB-K",
        "f20": "Form1065.Pg1.LinesB-K",
        "f21": "Form1065.Pg1.LinesB-K",
        "f22": "Form1065.Pg1.LinesB-K",
        "f23": "Form1065.Pg1.LinesB-K",
        "f24": "Form1065.Pg1.LinesB-K",
        "f25": "Form1065.Pg1.LinesB-K",
        "f26": "Form1065.Pg1.LinesB-K",
        "f27": "Form1065.Pg1.LinesB-K",
        "f28": "Form1065.Pg1.LinesB-K",
        "f29": "Form1065.Pg1.LinesB-K",
        "f30": "Form1065.Pg1.LinesB-K",
        "f31": "Form1065.Pg1.LinesB-K",
        "f32": "Form1065.Pg1.LinesB-K",
        "f33": "Form1065.Pg1.LinesB-K",
        # Income — Lines 1a–8
        "f34": "Form1065.Pg1.Income",
        "f35": "Form1065.Pg1.Income",
        "f36": "Form1065.Pg1.Income",
        "f37": "Form1065.Pg1.Income",
        "f38": "Form1065.Pg1.Income",
        "f39": "Form1065.Pg1.Income",
        "f40": "Form1065.Pg1.Income",
        "f41": "Form1065.Pg1.Income",
        "f42": "Form1065.Pg1.Income",
        "f43": "Form1065.Pg1.Income",
        # Deductions — Lines 9–21
        "f44": "Form1065.Pg1.Deductions",
        "f45": "Form1065.Pg1.Deductions",
        "f46": "Form1065.Pg1.Deductions",
        "f47": "Form1065.Pg1.Deductions",
        "f48": "Form1065.Pg1.Deductions",
        "f49": "Form1065.Pg1.Deductions",
        "f50": "Form1065.Pg1.Deductions",
        "f51": "Form1065.Pg1.Deductions",
        "f52": "Form1065.Pg1.Deductions",
        "f53": "Form1065.Pg1.Deductions",
        "f54": "Form1065.Pg1.Deductions",
        "f55": "Form1065.Pg1.Deductions",
        "f56": "Form1065.Pg1.Deductions",
        "f57": "Form1065.Pg1.Deductions",
        "f58": "Form1065.Pg1.Deductions",
        # Ordinary Business Income
        "f59": "Form1065.Pg1.NetIncome",
        # Sign Here
        "f60": "Form1065.Pg1.SignHere",
        "f61": "Form1065.Pg1.SignHere",
        "f62": "Form1065.Pg1.SignHere",
        "f63": "Form1065.Pg1.SignHere",
        # Paid Preparer Use Only
        "f64": "Form1065.Pg1.PaidPreparer",
        "f65": "Form1065.Pg1.PaidPreparer",
        "f66": "Form1065.Pg1.PaidPreparer",
        "f67": "Form1065.Pg1.PaidPreparer",
        "f68": "Form1065.Pg1.PaidPreparer",
        "f69": "Form1065.Pg1.PaidPreparer",
        "f70": "Form1065.Pg1.PaidPreparer",
        "f71": "Form1065.Pg1.PaidPreparer",
        "f72": "Form1065.Pg1.PaidPreparer",
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
        # Income Statement values (from official FR database, same as FILL PDF)
        rent_income   = self._isv('rent_income')
        total_income  = self._isv('total_income')
        salaries      = self._isv('salaries')
        repairs       = self._isv('repairs')
        taxes_lic     = self._isv('taxes_licenses')
        interest_exp  = self._isv('interest_expense')
        depreciation  = self._isv('depreciation')
        other_deduct  = self._isv('other_deductions')
        total_expense = self._isv('total_expenses')
        net_income    = self._isv('net_income')

        # Balance Sheet values
        total_assets  = self._bsv('total_assets')

        # Owners
        n_partners    = self._owner_count()

        R = self._row   # shorthand

        rows: List[Dict[str, Any]] = [

            # ── Tax Year Header ──────────────────────────────────────────────
            R('f1',  'TaxYearBegin', 'Tax year beginning — month',           ''),
            R('f2',  'TaxYearBegin', 'Tax year beginning — day, 20___',      ''),
            R('f3',  'TaxYearEnd',   'Tax year ending — month',              ''),
            R('f4',  'TaxYearEnd',   'Tax year ending — day, 20___',         ''),

            # ── Entity Identification ────────────────────────────────────────
            R('f5',  '',   'Name of partnership',                            ''),
            R('f6',  '',   'Principal business activity',                    'Real Estate Rental'),
            R('f7',  '',   'Principal product or service',                   'Rental Income'),
            R('f8',  '',   'Business code number (NAICS)',                   '531110'),
            R('f9',  '',   'Number, street, and room or suite no. (or P.O. box)', ''),
            R('f10', '',   'City or town, state or province, country, and ZIP or foreign postal code', ''),

            # ── Line A — Check Applicable Boxes ─────────────────────────────
            R('f11', 'A(1)', 'Initial return  □',                           ''),
            R('f12', 'A(2)', 'Final return  □',                             ''),
            R('f13', 'A(3)', 'Name change  □',                              ''),
            R('f14', 'A(4)', 'Address change  □',                           ''),
            R('f15', 'A(5)', 'Amended return  □',                           ''),
            R('f16', 'A(6)', 'Technical termination (see instructions)  □', ''),

            # ── Lines B–K ────────────────────────────────────────────────────
            R('f17', 'B',  'Number of Schedules K-1 attached',              str(n_partners)),
            R('f18', 'C',  'Check if Schedules C and M-3 are attached  □',  ''),
            R('f19', 'D',  'Employer identification number (EIN)',           ''),
            R('f20', 'E',  'Date business started',                          ''),
            R('f21', 'F',  'Total assets (end of year)  [FR computed]',      total_assets),
            R('f22', 'G(1)', 'Type of entity: Domestic general partnership  □', ''),
            R('f23', 'G(2)', 'Type of entity: Domestic limited partnership  □', ''),
            R('f24', 'G(3)', 'Type of entity: Domestic limited liability company  ☑', '☑ LLC'),
            R('f25', 'G(4)', 'Type of entity: Domestic limited liability partnership  □', ''),
            R('f26', 'G(5)', 'Type of entity: Foreign partnership  □',      ''),
            R('f27', 'G(6)', 'Type of entity: Other  □',                    ''),
            R('f28', 'H1', 'Is this a publicly traded partnership (§469(k)(2))?  Yes □  No □', '☑ No'),
            R('f29', 'H2', 'Has partnership filed Form 8918 (Material Advisor)?  Yes □  No □', '☑ No'),
            R('f30', 'I1', 'Did the partnership have any foreign partners?  Yes □  No □', '☑ No'),
            R('f31', 'I2', 'If Yes to I1: number of Forms 8805 filed',       ''),
            R('f32', 'J',  'Accounting method:  Cash □  Accrual □  Other □', '☑ Cash'),
            R('f33', 'K',  'Does the partnership satisfy all four small-partnership exception conditions '
                           '(§6231(a)(1)(B))? See Schedule B, Q6 for detail.  Yes □  No □', ''),

            # ── Income  ──────────────────────────────────────────────────────
            # Lines 1a/1c/3: gross rental receipts (Form1065 P1_1a = IS.rent_income)
            R('f34', '1a', 'Gross receipts or sales  [FR computed]',         rent_income),
            R('f35', '1b', 'Returns and allowances',                          0),
            R('f36', '1c', 'Balance (line 1a minus line 1b)  [FR computed]', rent_income),
            R('f37', '2',  'Cost of goods sold (attach Form 1125-A)',         ''),
            R('f38', '3',  'Gross profit (line 1c minus line 2)',             rent_income),
            R('f39', '4',  'Ordinary income (loss) from other partnerships, estates, and trusts', ''),
            R('f40', '5',  'Net farm profit (loss) (attach Schedule F)',      ''),
            R('f41', '6',  'Net gain (loss) from Form 4797, Part II, line 17', ''),
            R('f42', '7',  'Other income (loss) (attach statement)',          ''),
            # Line 8: total income (Form1065 P1_8 = IS.total_income)
            R('f43', '8',  'Total income (loss). Combine lines 3 through 7  [FR computed]', total_income),

            # ── Deductions ───────────────────────────────────────────────────
            R('f44', '9',   'Salaries and wages (other than to partners) (less employment credits)  [FR computed]',
                             salaries or ''),
            R('f45', '10',  'Guaranteed payments to partners',               ''),
            R('f46', '11',  'Repairs and maintenance  [FR computed]',        repairs or ''),
            R('f47', '12',  'Bad debts',                                      ''),
            R('f48', '13',  'Rent',                                           ''),
            R('f49', '14',  'Taxes and licenses  [FR computed]',             taxes_lic or ''),
            R('f50', '15',  'Interest (see instructions)  [FR computed]',    interest_exp or ''),
            R('f51', '16a', 'Depreciation (if required, attach Form 4562)  [FR computed]', depreciation or ''),
            R('f52', '16b', 'Less depreciation reported on Form 1125-A and elsewhere on return', ''),
            R('f53', '16c', 'Net depreciation (16a minus 16b)  [FR computed]', depreciation or ''),
            R('f54', '17',  'Depletion (Do not deduct oil and gas depletion)', ''),
            R('f55', '18',  'Retirement plans, etc.',                         ''),
            R('f56', '19',  'Employee benefit programs',                      ''),
            R('f57', '20',  'Other deductions (attach statement)  [FR computed]', other_deduct or ''),
            R('f58', '21',  'Total deductions. Add lines 9 through 20  [FR computed]', total_expense),

            # ── Net Ordinary Income ──────────────────────────────────────────
            R('f59', '22',  'Ordinary business income (loss). Subtract line 21 from line 8  [FR computed]',
                             net_income),

            # ── Sign Here ────────────────────────────────────────────────────
            R('f60', 'Sign',      'Signature of general partner or LLC member manager', ''),
            R('f61', 'Date',      'Date signed',                              ''),
            R('f62', 'PrintName', 'Print/type name of signer',               ''),
            R('f63', 'Title',     'Title of signer',                          'Managing Member'),

            # ── Paid Preparer Use Only ────────────────────────────────────────
            R('f64', 'PrepName',    "Preparer's name",                        ''),
            R('f65', 'PrepSig',     "Preparer's signature",                   ''),
            R('f66', 'PrepDate',    'Date',                                   ''),
            R('f67', 'SelfEmp',     'Check if self-employed  □',              ''),
            R('f68', 'PTIN',        'PTIN',                                   ''),
            R('f69', 'FirmName',    "Firm's name",                            ''),
            R('f70', 'FirmEIN',     "Firm's EIN",                             ''),
            R('f71', 'FirmAddress', "Firm's address",                         ''),
            R('f72', 'FirmPhone',   'Phone no.',                               ''),
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        return {
            'Gross Income':  self._isv('total_income'),
            'Total Expense': self._isv('total_expenses'),
            'Net Income':    self._isv('net_income'),
            'Total Assets':  self._bsv('total_assets'),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'namespace':  self.NAMESPACE,
            'note': (
                'IRS Form 1065 (2024), Page 1. Field IDs f1–f72. '
                'FR-computed lines match Form1065_FILL.pdf values exactly. '
                'Blank fields require manual entry before filing. '
                'Consult a qualified tax professional before submitting.'
            ),
        }
