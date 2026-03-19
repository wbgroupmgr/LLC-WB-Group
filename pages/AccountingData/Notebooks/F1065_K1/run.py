"""
run_1065.py
===========
End-to-end demo: loads the GL, computes Form 1065, generates PDFs.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from gl_ledger import LLCGeneralLedger, LLCMember
from F1065 import Form1065Generator

# ── General Ledger ────────────────────────────────────────────────────────────
GL = {
    "Acct.Asset.Purchase":  -214_113.95,
    "Acct.Cash.Expense":      -1_766.92,
    "Acct.Cash.Income":        4_000.53,
    "Acct.Cash.Investment":  219_227.00,
    "Acct.Cash.Misc":             29.47,
    "Acct.Cash.Util":         -1_056.95,
    "Acct.Interest.Income":      400.00,
    "Balance":                 6_719.18,
}

# ── Optional: customise members ───────────────────────────────────────────────
members = [
    LLCMember("Managing Partner", "XX-1111111", 0.90,
               address="123 Hilltop Dr", city_st_zip="Austin, TX 78701",
               is_managing=True),
    LLCMember("Member B",         "XX-2222222", 0.05,
               address="456 Oak Ave",  city_st_zip="Dallas, TX 75201"),
    LLCMember("Member C",         "XX-3333333", 0.05,
               address="789 Pine Rd",  city_st_zip="Houston, TX 77001"),
]

# ── Class 1: import & compute ─────────────────────────────────────────────────
gl = LLCGeneralLedger.from_dict(
    GL,
    members      = members,
    entity_name  = "Sunset Ridge Rentals LLC",
    ein          = "12-3456789",
    tax_year     = 2024,
)

gl.summary()   # pretty console output

# ── Class 2: generate PDFs ────────────────────────────────────────────────────
gen   = Form1065Generator(gl)
files = gen.generate_all(output_dir="/mnt/user-data/outputs/1065_output")