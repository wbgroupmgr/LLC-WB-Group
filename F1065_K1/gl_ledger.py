"""
gl_ledger.py
============
Class 1 of 2 — LLCGeneralLedger

Imports a General Ledger as a pandas DataFrame, validates accounts,
computes all Form 1065 line items, and allocates every dollar to each
LLC member according to their ownership percentage.

Partners (fixed for this engagement):
  • Managing Partner   90 %
  • Member B            5 %
  • Member C            5 %

GL Accounts supported
---------------------
  Acct.Asset.Purchase    → Capital asset (Schedule L)
  Acct.Cash.Expense      → Operating expense  (Line 20 deductions)
  Acct.Cash.Income       → Rental income      (Line 1a)
  Acct.Cash.Investment   → Partner capital    (Schedule L / M-2)
  Acct.Cash.Misc         → Other income       (Line 7)
  Acct.Cash.Util         → Utilities expense  (Line 20)
  Acct.Interest.Income   → Interest income    (Line 5 / Sch K Box 5)
  Balance                → Ending cash        (Schedule L)

Usage
-----
  from gl_ledger import LLCGeneralLedger

  # From a dict
  gl = LLCGeneralLedger.from_dict({
      "Acct.Asset.Purchase":  -214113.95,
      "Acct.Cash.Expense":      -1766.92,
      "Acct.Cash.Income":        4000.53,
      "Acct.Cash.Investment":  219227.00,
      "Acct.Cash.Misc":            29.47,
      "Acct.Cash.Util":         -1056.95,
      "Acct.Interest.Income":     400.00,
      "Balance":                 6719.18,
  })

  # From an existing DataFrame
  gl = LLCGeneralLedger(df)

  gl.summary()               # pretty-print all computed lines
  computed = gl.computed     # dict of all derived values
  alloc    = gl.allocations  # dict of per-member share dicts
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List


# ─────────────────────────────────────────────────────────────────────────────
#  MEMBER DEFINITION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LLCMember:
    name:       str
    ein_or_ssn: str
    pct:        float          # ownership as decimal, e.g. 0.90
    address:    str = ""
    city_st_zip:str = ""
    is_managing:bool = False

    @property
    def pct_display(self) -> str:
        return f"{self.pct * 100:.0f}%"


# Default three-member structure
DEFAULT_MEMBERS: List[LLCMember] = [
    LLCMember("Managing Partner",  "XX-1111111", 0.90, is_managing=True),
    LLCMember("Member B",          "XX-2222222", 0.05),
    LLCMember("Member C",          "XX-3333333", 0.05),
]


# ─────────────────────────────────────────────────────────────────────────────
#  KNOWN ACCOUNTS & THEIR ROLES
# ─────────────────────────────────────────────────────────────────────────────

ACCOUNT_ROLES = {
    "Acct.Asset.Purchase":  "asset",       # capitalised – not deducted on P&L
    "Acct.Cash.Expense":    "expense",     # Line 20 other deductions
    "Acct.Cash.Income":     "income",      # Line 1a gross receipts
    "Acct.Cash.Investment": "capital",     # Schedule L / M-2
    "Acct.Cash.Misc":       "other_income",# Line 7
    "Acct.Cash.Util":       "expense",     # Line 20 utilities
    "Acct.Interest.Income": "interest",    # Line 5 / Sch K Box 5
    "Balance":              "cash_end",    # Schedule L ending cash
}


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class LLCGeneralLedger:
    """
    Wraps a General Ledger DataFrame and exposes Form 1065 line items
    plus per-member allocations.

    DataFrame schema (either column layout accepted):
        Account | Amount          ← two-column format
        OR a single-column DataFrame indexed by account name
    """

    REQUIRED_COLUMNS_PAIRS = [("Account", "Amount"), ("account", "amount")]

    def __init__(
        self,
        df: pd.DataFrame,
        members: List[LLCMember] | None = None,
        entity_name: str = "Sunset Ridge Rentals LLC",
        ein: str = "12-3456789",
        tax_year: int = 2024,
    ):
        self.entity_name = entity_name
        self.ein         = ein
        self.tax_year    = tax_year
        self.members     = members or DEFAULT_MEMBERS
        self._df         = self._normalise(df)
        self._validate()
        self._gl: Dict[str, float] = self._to_dict()
        self.computed    = self._compute()
        self.allocations = self._allocate()

    # ── constructors ─────────────────────────────────────────────────────────

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, float],
        members: List[LLCMember] | None = None,
        **kwargs,
    ) -> "LLCGeneralLedger":
        """Build from a plain {account: balance} dict."""
        df = pd.DataFrame(
            list(data.items()), columns=["Account", "Amount"]
        )
        return cls(df, members=members, **kwargs)

    @classmethod
    def from_csv(cls, path: str, **kwargs) -> "LLCGeneralLedger":
        """Load from a two-column CSV (Account, Amount)."""
        df = pd.read_csv(path)
        return cls(df, **kwargs)

    @classmethod
    def from_excel(cls, path: str, sheet: str = "GL", **kwargs) -> "LLCGeneralLedger":
        """Load from an Excel workbook."""
        df = pd.read_excel(path, sheet_name=sheet)
        return cls(df, **kwargs)

    # ── normalise / validate ──────────────────────────────────────────────────

    def _normalise(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure columns are named 'Account' and 'Amount'."""
        df = df.copy()
        # already correct
        if set(df.columns) >= {"Account", "Amount"}:
            return df[["Account", "Amount"]].reset_index(drop=True)
        # lowercase variants
        if set(df.columns) >= {"account", "amount"}:
            return df.rename(columns={"account": "Account", "amount": "Amount"})[
                ["Account", "Amount"]
            ].reset_index(drop=True)
        # single-column index → melt
        if df.shape[1] == 1:
            df.index.name = "Account"
            df.columns    = ["Amount"]
            return df.reset_index()
        raise ValueError(
            f"Cannot normalise DataFrame with columns {list(df.columns)}. "
            "Expected ('Account', 'Amount') or ('account', 'amount')."
        )

    def _validate(self):
        """Warn about unknown accounts; raise if Amount column is not numeric."""
        self._df["Amount"] = pd.to_numeric(self._df["Amount"], errors="coerce")
        bad = self._df[self._df["Amount"].isna()]
        if not bad.empty:
            raise ValueError(f"Non-numeric Amount values:\n{bad}")

        known = set(ACCOUNT_ROLES)
        unknown = set(self._df["Account"]) - known
        if unknown:
            print(f"[GL WARNING] Unknown accounts (ignored in computations): {unknown}")

        pct_total = sum(m.pct for m in self.members)
        if abs(pct_total - 1.0) > 1e-6:
            raise ValueError(
                f"Member ownership percentages must sum to 100%. Got {pct_total*100:.2f}%"
            )

    def _to_dict(self) -> Dict[str, float]:
        return dict(zip(self._df["Account"], self._df["Amount"]))

    # ── core computation ─────────────────────────────────────────────────────

    def _get(self, key: str) -> float:
        return float(self._gl.get(key, 0.0))

    def _compute(self) -> Dict[str, float]:
        """Map GL accounts → Form 1065 line items."""
        g = self._get

        # ── income ──────────────────────────────────────────────────────────
        line_1a = max(0.0,  g("Acct.Cash.Income"))       # gross rental receipts
        line_5  = max(0.0,  g("Acct.Interest.Income"))   # interest income
        line_7  = max(0.0,  g("Acct.Cash.Misc"))         # other income
        line_8  = line_1a + line_5 + line_7              # total income

        # ── deductions ───────────────────────────────────────────────────────
        exp_op   = abs(g("Acct.Cash.Expense")) if g("Acct.Cash.Expense") < 0 else g("Acct.Cash.Expense")
        exp_util = abs(g("Acct.Cash.Util"))    if g("Acct.Cash.Util")    < 0 else g("Acct.Cash.Util")
        line_20  = exp_op + exp_util             # other deductions
        line_21  = line_20                       # total deductions
        line_22  = line_8 - line_21              # ordinary income / (loss)

        # ── balance sheet ─────────────────────────────────────────────────
        asset_cost   = abs(g("Acct.Asset.Purchase"))
        cash_end     = max(0.0, g("Balance"))
        cap_contrib  = max(0.0, g("Acct.Cash.Investment"))
        total_assets = cash_end + asset_cost
        cap_end      = cap_contrib + line_22
        total_liab   = cap_end

        return {
            # Page 1 – income
            "line_1a":          line_1a,
            "line_5":           line_5,
            "line_7":           line_7,
            "line_8":           line_8,
            # Page 1 – deductions
            "line_20_exp":      exp_op,
            "line_20_util":     exp_util,
            "line_20":          line_20,
            "line_21":          line_21,
            "line_22":          line_22,
            # Schedule L
            "cash_beg":         0.0,
            "cash_end":         cash_end,
            "asset_cost":       asset_cost,
            "total_assets":     total_assets,
            "cap_contrib":      cap_contrib,
            "cap_end":          cap_end,
            "total_liab":       total_liab,
            # Schedule K totals
            "k_ordinary":       line_22,
            "k_rental":         line_1a,
            "k_interest":       line_5,
            "k_other":          line_7,
            # Schedule M-2
            "m2_beg":           0.0,
            "m2_contrib":       cap_contrib,
            "m2_net":           line_22,
            "m2_dist":          0.0,
            "m2_end":           cap_contrib + line_22,
        }

    # ── per-member allocation ─────────────────────────────────────────────

    def _allocate(self) -> Dict[str, Dict[str, float]]:
        """
        Allocate every Schedule K item to each member by ownership %.

        Returns dict keyed by member name:
          { "ordinary_income": x, "rental_income": x, "interest": x,
            "other_income": x, "capital_contrib": x, "ending_capital": x }
        """
        c   = self.computed
        out = {}
        k_items = {
            "ordinary_income": c["k_ordinary"],
            "rental_income":   c["k_rental"],
            "interest_income": c["k_interest"],
            "other_income":    c["k_other"],
            "capital_contrib": c["cap_contrib"],
            "ending_capital":  c["cap_end"],
        }
        for m in self.members:
            out[m.name] = {k: round(v * m.pct, 2) for k, v in k_items.items()}
        return out

    # ── public helpers ────────────────────────────────────────────────────────

    @property
    def dataframe(self) -> pd.DataFrame:
        """Return the normalised GL DataFrame."""
        return self._df.copy()

    def get_member(self, name: str) -> LLCMember | None:
        for m in self.members:
            if m.name == name:
                return m
        return None

    def summary(self):
        """Print a formatted console summary."""
        c = self.computed
        sep = "=" * 62

        print(f"\n{sep}")
        print(f"  GENERAL LEDGER → FORM 1065 SUMMARY")
        print(f"  {self.entity_name}  |  EIN {self.ein}  |  TY {self.tax_year}")
        print(sep)

        print("\n  ── RAW GL ACCOUNTS ──────────────────────────────────────")
        for _, row in self._df.iterrows():
            role = ACCOUNT_ROLES.get(row["Account"], "n/a")
            print(f"    {row['Account']:<28}  {row['Amount']:>14,.2f}   [{role}]")

        def L(label, val, indent=2):
            sp = " " * indent
            print(f"  {sp}{label:<36}  {val:>14,.2f}")

        print("\n  ── PAGE 1 INCOME ────────────────────────────────────────")
        L("Line 1a  Gross Receipts (Rental)", c["line_1a"])
        L("Line 5   Interest Income",         c["line_5"])
        L("Line 7   Other Income (Misc)",     c["line_7"])
        L("Line 8   TOTAL INCOME",            c["line_8"])

        print("\n  ── PAGE 1 DEDUCTIONS ────────────────────────────────────")
        L("Line 20a  Operating Expenses",     c["line_20_exp"])
        L("Line 20b  Utilities",              c["line_20_util"])
        L("Line 20   TOTAL OTHER DEDUCTIONS", c["line_20"])
        L("Line 21   TOTAL DEDUCTIONS",       c["line_21"])

        print(f"\n  {'─'*58}")
        L("Line 22  ORDINARY INCOME / (LOSS)", c["line_22"])

        print("\n  ── SCHEDULE L BALANCE SHEET ─────────────────────────────")
        L("Cash – End of Year",               c["cash_end"])
        L("Depreciable Property (Cost)",      c["asset_cost"])
        L("TOTAL ASSETS",                     c["total_assets"])
        L("Partners' Capital Contributions",  c["cap_contrib"])
        L("Retained Earnings (Current Yr)",   c["line_22"])
        L("TOTAL PARTNERS' CAPITAL",          c["cap_end"])

        print("\n  ── SCHEDULE K ALLOCATIONS ───────────────────────────────")
        header = f"  {'Item':<26}" + "".join(f"  {m.name[:14]:>14}" for m in self.members)
        print(header)
        print("  " + "─" * (26 + 16 * len(self.members)))
        k_labels = {
            "ordinary_income": "Ordinary Income",
            "rental_income":   "Net Rental Income",
            "interest_income": "Interest Income",
            "other_income":    "Other Income",
            "capital_contrib": "Capital Contributed",
            "ending_capital":  "Ending Capital",
        }
        for key, label in k_labels.items():
            row_str = f"  {label:<26}"
            for m in self.members:
                row_str += f"  {self.allocations[m.name][key]:>14,.2f}"
            print(row_str)

        pct_row = f"  {'Ownership %':<26}"
        for m in self.members:
            pct_row += f"  {m.pct_display:>14}"
        print("  " + "─" * (26 + 16 * len(self.members)))
        print(pct_row)
        print(f"\n{sep}\n")