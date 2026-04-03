"""
"""
from dataclasses import dataclass

# ════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class ScheduleL:
    """Schedule L – Balance Sheet per Books (simplified for rental LLC)."""
    # ASSETS
    cash_beginning:            float = 0.0
    cash_ending:               float = 0.0
    depreciable_property_cost: float = 0.0   # from Acct.Asset.Purchase (abs)
    total_assets:              float = 0.0

    # LIABILITIES & CAPITAL
    partners_capital_contrib:  float = 0.0   # Acct.Cash.Investment
    retained_earnings:         float = 0.0   # Cumulative ordinary income
    total_liabilities_capital: float = 0.0

