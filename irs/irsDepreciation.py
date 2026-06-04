"""
irsDepreciation — Shared MACRS depreciation knowledge service.

Single authoritative source for depreciation computation and basis extraction.
Used by Form4562Agent, and any other agent or closing tool (e.g. YEClosingAgent)
that computes or verifies residential rental MACRS depreciation.

IRS authority:
  IRC §168       — MACRS general depreciation system
  IRC §168(b)(3)(B) — Residential rental property → straight-line method
  IRC §168(c)    — 27.5-year GDS recovery period for residential rental
  IRC §168(d)(2) — Mid-month convention (MCC): property placed in service in
                   month M gets (12.5 - M) / 12 of the first-year annual rate.
  Pub 946 Table A-6 — IRS mid-month convention rates (this formula reproduces them)

Books-First rule (IRC §446):
  The dollar value placed on Form 4562 Part IV Line 22 MUST equal IS.depreciation
  from the books. The formula here is used for VERIFICATION ONLY — to confirm
  that IS.depreciation is consistent with the asset records and MACRS parameters.
  A discrepancy > $1 indicates either a books error or wrong parameters.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

# Residential rental MACRS parameters (IRC §168(b)(3)(B), §168(c), §168(d)(2))
MACRS_RECOVERY_YEARS: float = 27.5
MACRS_METHOD: str = 'S/L'     # straight-line
MACRS_CONVENTION: str = 'MM'  # mid-month

# Tolerance for formula-vs-books comparison
FORMULA_TOLERANCE: float = 1.00   # $1.00 — within rounding of IRS table rates


def net_tangible_basis(asset_rows: List[Dict[str, Any]]) -> float:
    """
    Compute the net depreciable basis from GL asset rows.

    Uses the same Debit-Credit accounting as stmtGL:
      Balance = sum(Debit amt) − sum(Credit amt)

    This correctly handles closing-cost entries that appear as Credits
    to the asset account (reducing net capitalized basis). Summing all
    `amt` values regardless of aType overstates the basis.

    Args:
        asset_rows: raw records from llcAssets.load() filtered to
                    Acct.Fixed.Tangible.InService rows.
    Returns:
        Net depreciable basis (float, ≥ 0).
    """
    debit = 0.0
    credit = 0.0
    for r in asset_rows:
        amt   = _safe_float(r.get('amt', r.get('amount', 0)))
        atype = str(r.get('aType', '') or '').strip()
        if atype in ('Credit', 'Cr', 'CR', 'C'):
            credit += amt
        else:
            debit += amt
    return round(max(debit - credit, 0.0), 2)


def macrs_residential_year1(depreciable_basis: float,
                             placed_month: int,
                             recovery_years: float = MACRS_RECOVERY_YEARS) -> float:
    """
    Compute Year 1 MACRS depreciation for residential rental property.

    Formula (IRC §168(d)(2) mid-month convention):
        annual     = depreciable_basis / recovery_years
        year1_frac = (12.5 - placed_month) / 12
        year1      = annual × year1_frac

    The IRS mid-month convention treats property placed in service in month M
    as if it were placed in service at the midpoint of that month (i.e., on
    the 15th). For August (month=8): (12.5-8)/12 = 4.5/12 months of depreciation.

    Args:
        depreciable_basis: net depreciable cost (land excluded).
                           Use net_tangible_basis() to compute from asset rows.
        placed_month: integer 1–12 (month property was placed in service).
        recovery_years: MACRS recovery period in years (default 27.5 for
                        residential rental per IRC §168(c)).
    Returns:
        Year 1 depreciation amount (rounded to 2 decimal places).
    Raises:
        ValueError: if placed_month is not 1–12.
    """
    if not (1 <= placed_month <= 12):
        raise ValueError(f"placed_month must be 1–12; got {placed_month}")
    if depreciable_basis <= 0:
        return 0.0
    annual     = depreciable_basis / recovery_years
    year1_frac = (12.5 - placed_month) / 12.0
    return round(annual * year1_frac, 2)


def verify_depreciation(is_depreciation: float,
                         depreciable_basis: float,
                         placed_month: int,
                         recovery_years: float = MACRS_RECOVERY_YEARS
                         ) -> Dict[str, Any]:
    """
    Verify that IS.depreciation is consistent with MACRS formula.

    Returns a result dict:
      {
        'expected':    float,   # MACRS formula result
        'actual':      float,   # IS.depreciation (books-authoritative)
        'diff':        float,   # abs(expected - actual)
        'within_tolerance': bool,
        'basis':       float,   # the depreciable_basis used
        'placed_month': int,
        'recovery_years': float,
      }

    Books-First: if within_tolerance is False, the BOOKS are the authority
    (IS.depreciation is what gets filed). The discrepancy must be investigated
    and the books corrected if wrong — NOT the form value.
    """
    expected = macrs_residential_year1(depreciable_basis, placed_month, recovery_years)
    diff     = round(abs(expected - is_depreciation), 2)
    return {
        'expected':          expected,
        'actual':            is_depreciation,
        'diff':              diff,
        'within_tolerance':  diff <= FORMULA_TOLERANCE,
        'basis':             depreciable_basis,
        'placed_month':      placed_month,
        'recovery_years':    recovery_years,
    }


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return default
