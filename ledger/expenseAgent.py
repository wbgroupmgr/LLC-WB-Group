"""
expenseAgent.py — normalize llcExpRev records in-place.

Three normalizations applied in order per record:

  1. swap_cash_side
     If Acct.Cash.* is in the Ledger field AND Acct.Cash is NOT in the acct
     field, swap acct ↔ Ledger and flip aType (Debit ↔ Credit).
     Rationale: bank-imported rows often arrive with the cash account on the
     wrong side; the primary account should always be the cash account so GL
     grouping is consistent.

  2. fill_acct_sub
     For rows where acctSub is empty / null / 'nan', infer a value:
       • 'Acct.Exp' in ref account  → 'Exp Other'
       • 'Depr'     in ref account  → 'Depreciation'
       • default                    → 2nd dot-node of ref + ' Other'
                                      e.g. 'Acct.Cash.Bank' → 'Cash Other'
     ref is Ledger when non-nan; otherwise acct.

  3. fill_prop_nm
     For rows where propNm is empty / null / 'nan', set 'propUnknown'.
"""

import math


_NAN_STR = frozenset({"nan", "null", "none", ""})


def _is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float):
        return math.isnan(v)
    return str(v).strip().lower() in _NAN_STR


class ExpenseAgent:

    def normalize(self, rows: list) -> tuple:
        """
        Apply all three normalizations to a list of llcExpRev record dicts.

        Returns (normalized_rows, summary) where summary is:
          {'swapped': int, 'acctSub_filled': int, 'propNm_filled': int,
           'total_changed': int}
        Caller's list is not mutated — each row is shallow-copied.
        """
        result = [dict(r) for r in rows]
        n_swap = n_sub = n_prop = 0
        for r in result:
            if self._swap_cash_side(r):
                n_swap += 1
            if self._fill_acct_sub(r):
                n_sub += 1
            if self._fill_prop_nm(r):
                n_prop += 1

        summary = {
            "swapped":       n_swap,
            "acctSub_filled": n_sub,
            "propNm_filled":  n_prop,
            "total_changed":  n_swap + n_sub + n_prop,
        }
        return result, summary

    # ── Rule 1 ────────────────────────────────────────────────────────────────

    def _swap_cash_side(self, r: dict) -> bool:
        acct   = str(r.get("acct")   or "").strip()
        ledger = str(r.get("Ledger") or "").strip()
        if "Acct.Cash" in ledger and "Acct.Cash" not in acct:
            r["acct"]   = ledger
            r["Ledger"] = acct
            r["aType"]  = "Credit" if str(r.get("aType", "")).strip() == "Debit" else "Debit"
            return True
        return False

    # ── Rule 2 ────────────────────────────────────────────────────────────────

    def _fill_acct_sub(self, r: dict) -> bool:
        if not _is_empty(r.get("acctSub")):
            return False

        ledger = str(r.get("Ledger") or "").strip()
        acct   = str(r.get("acct")   or "").strip()
        ref    = ledger if not _is_empty(ledger) else acct

        if "Acct.Exp" in ref:
            r["acctSub"] = "Exp Other"
        elif "Depr" in ref:
            r["acctSub"] = "Depreciation"
        else:
            parts = ref.split(".")
            node  = parts[1] if len(parts) > 1 else ref
            r["acctSub"] = f"{node} Other" if node else "Other"
        return True

    # ── Rule 3 ────────────────────────────────────────────────────────────────

    def _fill_prop_nm(self, r: dict) -> bool:
        if _is_empty(r.get("propNm")):
            r["propNm"] = "propUnknown"
            return True
        return False
