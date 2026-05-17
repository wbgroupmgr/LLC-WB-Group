"""
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from irs.data_SchL import ScheduleL
from irs.data_SchK import ScheduleK

# ════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class F1065Page1:
    """Form 1065 – Page 1 income / deduction lines."""
    # INCOME
    line_1a_gross_receipts:    float = 0.0   # Gross receipts / rental income
    line_5_interest_income:    float = 0.0   # Interest income
    line_7_other_income:       float = 0.0   # Other income (misc cash)
    total_income:              float = 0.0   # Sum of income lines

    # DEDUCTIONS
    line_20_other_deductions:  float = 0.0   # Cash expenses + utilities
    total_deductions:          float = 0.0

    # BOTTOM LINE
    ordinary_income_loss:      float = 0.0   # Line 22 (income − deductions)


@dataclass
class Form1065:
    """Container for all computed 1065 schedules."""
    entity_name:  str = ""
    ein:          str = ""
    tax_year:     int = 2024
    page1:        F1065Page1  = field(default_factory=F1065Page1)
    schedule_k:   ScheduleK   = field(default_factory=ScheduleK)
    schedule_l:   ScheduleL   = field(default_factory=ScheduleL)
    gl_raw:       Dict[str, float] = field(default_factory=dict)

