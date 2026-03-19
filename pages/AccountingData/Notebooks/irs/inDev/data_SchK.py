"""
Schedule K Data Object
"""
from dataclasses import dataclass, field

# ════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class ScheduleK:
    """Schedule K – Partners' Distributive Share Items."""
    ordinary_income_loss:      float = 0.0
    net_rental_income:         float = 0.0
    interest_income:           float = 0.0
    other_income:              float = 0.0
    total_distributive_income: float = 0.0
