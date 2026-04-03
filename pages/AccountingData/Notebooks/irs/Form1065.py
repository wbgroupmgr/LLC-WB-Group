"""
"""

from typing import Dict, Optional
from pathlib import Path

from irs.taxAgent.data_F1065 import F1065Page1
from irs.taxAgent.data_SchL import ScheduleL
from irs.taxAgent.data_SchK import ScheduleK
from irs.taxAgent.data_F1065 import Form1065

from irs.pdf import _build_pdf



# ════════════════════════════════════════════════════════════════════════════
#  MAIN CLASS
# ════════════════════════════════════════════════════════════════════════════

class Form1065Preparer:
    """
    Parses a General Ledger dict and maps balances to IRS Form 1065 lines.

    Usage
    ------
    .compute()
        output Form1065(
            entity_name  = self.entity_name,
            ein          = self.ein,
            tax_year     = self.tax_year,
            page1        = p1,
            schedule_k   = sk,
            schedule_l   = sl,
            gl_raw       = dict(self.gl),
        )
        return self.result

    

    Conventions
    -----------
    * Income accounts: positive values → income earned
    * Expense/Asset accounts: negative values → money spent / invested
    * The class normalises signs internally for presentation.
    """

    # ── GL → 1065 mapping ───────────────────────────────────────────────────
    KNOWN_ACCOUNTS = {
        "Acct.Asset.Purchase",
        "Acct.Cash.Expense",
        "Acct.Cash.Income",
        "Acct.Cash.Investment",
        "Acct.Cash.Misc",
        "Acct.Cash.Util",
        "Acct.Interest.Income",
        "Balance",
    }

    def __init__(
        self,
        general_ledger: Dict[str, float],
        tax_year: int = 2024,
        entity_name: str = "LLC Rental Partnership",
        ein: str = "XX-XXXXXXX",
        beginning_cash: float = 0.0,
    ):
        self.gl = general_ledger
        self.tax_year = tax_year
        self.entity_name = entity_name
        self.ein = ein
        self.beginning_cash = beginning_cash
        self.result: Optional[Form1065] = None
        self._validate_gl()

    # ── validation ───────────────────────────────────────────────────────────

    def _validate_gl(self) -> None:
        unknown = set(self.gl.keys()) - self.KNOWN_ACCOUNTS
        if unknown:
            print(f"[WARNING] Unrecognised GL accounts (will be ignored): {unknown}")
        for acct, val in self.gl.items():
            if not isinstance(val, (int, float)):
                raise TypeError(f"GL value for '{acct}' must be numeric, got {type(val)}")

    def _get(self, key: str, default: float = 0.0) -> float:
        return self.gl.get(key, default)

    # ── computation ──────────────────────────────────────────────────────────

    def pg1(

    def compute(self) -> Form1065:
        """
        Map GL balances to Form 1065 lines and return a Form1065.
        
        """

        # ── raw GL values ────────────────────────────────────────────────────
        asset_purchase   = self._get("Acct.Asset.Purchase")    # negative (cash out)
        cash_expense     = self._get("Acct.Cash.Expense")       # negative (cash out)
        cash_income      = self._get("Acct.Cash.Income")        # positive (cash in)
        cash_investment  = self._get("Acct.Cash.Investment")    # positive (capital in)
        cash_misc        = self._get("Acct.Cash.Misc")          # positive (misc income)
        cash_util        = self._get("Acct.Cash.Util")          # negative (utility expense)
        interest_income  = self._get("Acct.Interest.Income")    # positive
        balance          = self._get("Balance")                  # ending cash balance

        # ════════════════════════════════════
        #  PAGE 1 – INCOME
        # ════════════════════════════════════
        # Line 1a – Gross receipts (rental income only; positive)
        line_1a = abs(cash_income) if cash_income > 0 else 0.0

        # Line 5 – Interest income
        line_5 = abs(interest_income) if interest_income > 0 else 0.0

        # Line 7 – Other income (misc cash receipts)
        line_7 = abs(cash_misc) if cash_misc > 0 else 0.0

        total_income = line_1a + line_5 + line_7

        # ════════════════════════════════════
        #  PAGE 1 – DEDUCTIONS
        # ════════════════════════════════════
        # Line 20 – Other deductions:
        #   • Acct.Cash.Expense (operating expenses)
        #   • Acct.Cash.Util    (utilities)
        #   NOTE: Acct.Asset.Purchase goes to Schedule L (capital asset),
        #         not deducted directly on Page 1 (treated as depreciable property).
        line_20_cash_exp  = abs(cash_expense) if cash_expense < 0 else cash_expense
        line_20_util      = abs(cash_util)    if cash_util    < 0 else cash_util
        line_20           = line_20_cash_exp + line_20_util

        total_deductions  = line_20

        # ════════════════════════════════════
        #  LINE 22 – ORDINARY INCOME / (LOSS)
        # ════════════════════════════════════
        ordinary_income   = total_income - total_deductions

        # ════════════════════════════════════
        #  SCHEDULE K
        # ════════════════════════════════════
        sk_ordinary      = ordinary_income
        sk_rental        = line_1a          # net rental flows through K-1 Box 2
        sk_interest      = line_5
        sk_other         = line_7
        sk_total         = sk_ordinary      # ordinary already nets everything

        # ════════════════════════════════════
        #  SCHEDULE L – BALANCE SHEET
        # ════════════════════════════════════
        depr_property_cost  = abs(asset_purchase)   # capitalised at cost
        partners_contrib    = abs(cash_investment) if cash_investment > 0 else 0.0
        ending_cash         = abs(balance) if balance > 0 else 0.0
        beginning_cash_val  = self.beginning_cash

        total_assets        = ending_cash + depr_property_cost
        retained_earnings   = ordinary_income        # simplified single-period
        total_liab_capital  = partners_contrib + retained_earnings

        # ════════════════════════════════════
        #  ASSEMBLE RESULT
        # ════════════════════════════════════
        p1 = F1065Page1(
            line_1a_gross_receipts   = line_1a,
            line_5_interest_income   = line_5,
            line_7_other_income      = line_7,
            total_income             = total_income,
            line_20_other_deductions = line_20,
            total_deductions         = total_deductions,
            ordinary_income_loss     = ordinary_income,
        )

        sk = ScheduleK(
            ordinary_income_loss      = sk_ordinary,
            net_rental_income         = sk_rental,
            interest_income           = sk_interest,
            other_income              = sk_other,
            total_distributive_income = sk_total,
        )

        sl = ScheduleL(
            cash_beginning            = beginning_cash_val,
            cash_ending               = ending_cash,
            depreciable_property_cost = depr_property_cost,
            total_assets              = total_assets,
            partners_capital_contrib  = partners_contrib,
            retained_earnings         = retained_earnings,
            total_liabilities_capital = total_liab_capital,
        )

        self.result = Form1065(
            entity_name  = self.entity_name,
            ein          = self.ein,
            tax_year     = self.tax_year,
            page1        = p1,
            schedule_k   = sk,
            schedule_l   = sl,
            gl_raw       = dict(self.gl),
        )
        return self.result

    # ── text summary ─────────────────────────────────────────────────────────

    def print_summary(self) -> None:
        """Print a formatted console summary of all 1065 schedules."""
        if self.result is None:
            self.compute()
        r = self.result
        p = r.page1
        k = r.schedule_k
        l = r.schedule_l

        def f(v): return f"${v:>14,.2f}"
        sep = "=" * 58

        print(f"\n{sep}")
        print(f"  IRS FORM 1065 WORKSHEET  |  Tax Year {r.tax_year}")
        print(f"  {r.entity_name}  |  EIN: {r.ein}")
        print(sep)

        print("\n  PAGE 1 — INCOME")
        print(f"  Line 1a  Gross Receipts (Rental)      {f(p.line_1a_gross_receipts)}")
        print(f"  Line 5   Interest Income               {f(p.line_5_interest_income)}")
        print(f"  Line 7   Other Income (Misc)           {f(p.line_7_other_income)}")
        print(f"  {'─'*52}")
        print(f"           TOTAL INCOME                  {f(p.total_income)}")

        print("\n  PAGE 1 — DEDUCTIONS")
        print(f"  Line 20  Other Deductions")
        print(f"             Cash Expenses               {f(abs(r.gl_raw.get('Acct.Cash.Expense',0)))}")
        print(f"             Utilities                   {f(abs(r.gl_raw.get('Acct.Cash.Util',0)))}")
        print(f"  {'─'*52}")
        print(f"           TOTAL DEDUCTIONS              {f(p.total_deductions)}")

        print(f"\n  LINE 22  ORDINARY INCOME / (LOSS)     {f(p.ordinary_income_loss)}")

        print(f"\n  SCHEDULE K — DISTRIBUTIVE SHARE ITEMS")
        print(f"  K-1 Box 1  Ordinary Income/(Loss)     {f(k.ordinary_income_loss)}")
        print(f"  K-1 Box 2  Net Rental Income           {f(k.net_rental_income)}")
        print(f"  K-1 Box 5  Interest Income             {f(k.interest_income)}")
        print(f"  K-1 Box 11 Other Income                {f(k.other_income)}")
        print(f"  {'─'*52}")
        print(f"             TOTAL DISTRIBUTIVE INCOME  {f(k.total_distributive_income)}")

        print(f"\n  SCHEDULE L — BALANCE SHEET (End of Year)")
        print(f"  ASSETS")
        print(f"    Cash (ending balance)               {f(l.cash_ending)}")
        print(f"    Depreciable Property (cost)         {f(l.depreciable_property_cost)}")
        print(f"  {'─'*52}")
        print(f"    TOTAL ASSETS                        {f(l.total_assets)}")
        print(f"  LIABILITIES & PARTNERS' CAPITAL")
        print(f"    Partners' Capital Contributions     {f(l.partners_capital_contrib)}")
        print(f"    Retained Earnings (current yr)      {f(l.retained_earnings)}")
        print(f"  {'─'*52}")
        print(f"    TOTAL LIABILITIES & CAPITAL         {f(l.total_liabilities_capital)}")
        print(f"\n{sep}\n")

    # ── PDF export ────────────────────────────────────────────────────────────

    def export_pdf(self, output_path: str = "Form_1065_Worksheet.pdf") -> str:
        """Generate a formatted PDF worksheet. Returns the output path."""
        if self.result is None:
            self.compute()
        _build_pdf(self.result, output_path)
        print(f"✅  PDF saved → {Path(output_path).name}")
        return output_path

    # ── dict / JSON export ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return all computed values as a plain dict (JSON-serialisable)."""
        if self.result is None:
            self.compute()
        r = self.result
        return {
            "entity_name": r.entity_name,
            "ein":         r.ein,
            "tax_year":    r.tax_year,
            "page1": {
                "line_1a_gross_receipts":   r.page1.line_1a_gross_receipts,
                "line_5_interest_income":   r.page1.line_5_interest_income,
                "line_7_other_income":      r.page1.line_7_other_income,
                "total_income":             r.page1.total_income,
                "line_20_other_deductions": r.page1.line_20_other_deductions,
                "total_deductions":         r.page1.total_deductions,
                "ordinary_income_loss":     r.page1.ordinary_income_loss,
            },
            "schedule_k": {
                "ordinary_income_loss":      r.schedule_k.ordinary_income_loss,
                "net_rental_income":         r.schedule_k.net_rental_income,
                "interest_income":           r.schedule_k.interest_income,
                "other_income":              r.schedule_k.other_income,
                "total_distributive_income": r.schedule_k.total_distributive_income,
            },
            "schedule_l": {
                "cash_beginning":            r.schedule_l.cash_beginning,
                "cash_ending":               r.schedule_l.cash_ending,
                "depreciable_property_cost": r.schedule_l.depreciable_property_cost,
                "total_assets":              r.schedule_l.total_assets,
                "partners_capital_contrib":  r.schedule_l.partners_capital_contrib,
                "retained_earnings":         r.schedule_l.retained_earnings,
                "total_liabilities_capital": r.schedule_l.total_liabilities_capital,
            },
            "gl_raw": r.gl_raw,
        }
