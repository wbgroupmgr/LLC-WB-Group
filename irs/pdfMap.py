'''
#  Map GL and LLC entity fields into PDF fields
#
#  IRS Form 1065 (2023) letter-size pages:  612 × 792 pts

OLD-------
# Each entry: dict_key -> (acroform_name, page, x, y, w, h, font_size)
# acroform_name is None for fields with no AcroForm equivalent.

# ════════════════════════════════════════════════════════════════════════════
'''
import os
from typing import Dict, Optional, Any
import json

# Checkbox on/off values used by IRS AcroForm
CHECKBOX_ON  = "/1"
CHECKBOX_OFF = "/0"

# Fields whose values are bool (True→checked, False→unchecked)
BOOL_FIELDS = {
    "sch_b_2a_yes", "sch_b_2a_no",
    "sch_b_3a_yes", "sch_b_3a_no",
}


class irsGLMap(object):
    def __init__(self, llc, **kwargs):
        self.llc = llc
    # ════════════════════════════════════════════════════════════════════════════
    #  HELPER – format a float as IRS dollar string
    # ════════════════════════════════════════════════════════════════════════════

    def fetchGLMapDict(self):
        '''
        Load AccountingData/YEAR/map_GL_PDF_fldName.json)
        GL.field -> pdf.field_key
        '''
        acctDIR = self.llc.acctDir()
        with open(os.path.join(acctDIR, 'map_GL_PDF_fldName.json'),'r') as fio:
            return json.load(fio)
    
    def _fmt_dollar(self, value: float) -> str:
        """Format a number for an IRS field: '1,606' (no $ sign, no cents on whole)."""
        if value < 0:
            return f"({abs(value):,.0f})"
        return f"{value:,.0f}"
    
    
    def _fmt_dollar_cents(self, value: float) -> str:
        """Two-decimal version for balance-sheet / Schedule L fields."""
        if value < 0:
            return f"({abs(value):,.2f})"
        return f"{value:,.2f}"

    # build 1065
    # ════════════════════════════════════════════════════════════════════════════
    #  CONVENIENCE BUILDER  –  GL dict  →  1065 data dict
    #  (bridges Form1065Preparer output to Form1065Filler input)
    # ════════════════════════════════════════════════════════════════════════════

    def f1065Dict(self, glDict: Dict[str, float]):
        '''
        Cross ref glDict x GLFormDict -> f1065Dict

        glDict:   GL.field -> Value
        glMapDict: GL.field -> PDF.fid

        Output:
        f1065Dict: PDF.fid -> value

        chkNo/chkYes are added to form dict for writing PDF
        '''
        
        # Create dict of GL and LLC entity
        #    gl.field -> value
        glDict = self.glFullDict(glDict)

        # Create dict of GL -> Form fields
        f1065Dict = self.fetchGLMapDict()

        mDict = {fid:glDict[glID] for glID,fid in f1065Dict.items() if glID in glDict}
        mDict['chk'] = glDict['chk']
        
        return mDict
    

    
    def glFullDict(self,  gl: Dict[str, float]) -> Dict[str, Any]:
        """
        Build a Form1065 Dict that maps LLC Entity and GL data into a Form1065Dict
        
        Convert a raw General Ledger dict (same format used by Form1065Preparer)
        directly into a Form1065Filler data dict.
    
        GL sign convention:
          Positive = money IN  (income, capital contributions, ending balance)
          Negative = money OUT (expenses, asset purchases)
        """
        def pos(k):   return max(0.0, float(gl.get(k, 0)))
        def absv(k):  return abs(float(gl.get(k, 0)))
        def num(k): return round(k,2)

        # income
        line_1a  = num(pos("Acct.Cash.Income"))
        line_5_k = pos("Acct.Interest.Income")
        line_7   = pos("Acct.Cash.Misc")
        line_8   = num(line_1a + line_5_k + line_7)
     
        # deductions
        line_20  = num(absv("Acct.Cash.Expense") + absv("Acct.Cash.Util"))
        line_21  = line_20
        line_22  = num(line_8 - line_21)
     
        # balance sheet
        fixed    = num(absv("Acct.Asset.Purchase"))
        cash_end = num(pos("Balance"))
        cap_cont = num(pos("Acct.Cash.Investment"))

        formDict = self.llc.getGLTaxDict() | {    
            # page 1 income
            "line_1a":  line_1a,
            "line_1c":  line_1a,
            "line_7":   line_7,
            "line_8":   line_8,
    
            # page 1 deductions
            "line_20":  line_20,
            "line_21":  line_21,
            "line_22":  line_22,
    
            # schedule K
            "k_line_1":  line_22,
            "k_line_2":  line_1a,
            "k_line_5":  line_5_k,
            "k_line_11": line_7,
    
            # schedule L
            "l_cash_beg":         0.0,
            "l_cash_end":         cash_end,
            "l_fixed_assets_beg": 0.0,
            "l_fixed_assets_end": fixed,
            "l_total_assets_beg": 0.0,
            "l_total_assets_end": cash_end + fixed,
            "l_partners_cap_beg": 0.0,
            "l_partners_cap_end": cap_cont + line_22,
            "l_total_liab_beg":   0.0,
            "l_total_liab_end":   cap_cont + line_22,
    
            # schedule M-2
            "m2_beg_capital":    0.0,
            "m2_capital_contrib": cap_cont,
            "m2_net_income":      line_22,
            "m2_end_capital":     cap_cont + line_22,
    
        }
        return formDict


'''
DOCUMENTATION -----------------
## GL -> PDF Form1065
---------

All keys are optional; missing keys are silently skipped.

  ── ENTITY HEADER ──────────────────────────────────────────────────────────
  entity_name        str   Partnership / LLC name
  ein                str   XX-XXXXXXX
  tax_year           int   2024
  address            str   Street address
  city_state_zip     str   City, State ZIP
  principal_product  str   Principal product or service
  business_code      str   6-digit business activity code
  date_business_began str  MM/DD/YYYY
  total_assets       str   Total assets (Schedule L line 6)
  number_of_k1s      int   Number of Schedules K-1 attached

  ── PAGE 1 – INCOME ─────────────────────────────────────────────────────────
  line_1a            float  Gross receipts (rents)
  line_1b            float  Returns and allowances
  line_1c            float  Net (1a minus 1b)  – auto-computed if omitted
  line_2             float  Cost of goods sold
  line_3             float  Gross profit
  line_4             float  Ordinary income/(loss) from other partnerships
  line_5             float  Net farm profit/(loss)
  line_6             float  Net gain/(loss) Form 4797
  line_7             float  Other income/(loss)
  line_8             float  Total income – auto-computed if omitted

  ── PAGE 1 – DEDUCTIONS ─────────────────────────────────────────────────────
  line_9             float  Salaries and wages
  line_10            float  Guaranteed payments to partners
  line_11            float  Repairs and maintenance
  line_12            float  Bad debts
  line_13            float  Rent
  line_14            float  Taxes and licenses
  line_15            float  Interest
  line_16a           float  Depreciation (Form 4562)
  line_16b           float  Depreciation claimed elsewhere
  line_16c           float  Subtract 16b from 16a
  line_17            float  Depletion
  line_18            float  Retirement plans etc.
  line_19            float  Employee benefit programs
  line_20            float  Other deductions (attach schedule)
  line_21            float  Total deductions – auto-computed if omitted
  line_22            float  Ordinary business income/(loss) – auto-computed

  ── SIGNATURE BLOCK ─────────────────────────────────────────────────────────
  preparer_name      str
  preparer_ptin      str
  preparer_firm      str
  preparer_phone     str
  preparer_date      str   MM/DD/YYYY

  ── SCHEDULE B (selected questions) ────────────────────────────────────────
  sch_b_1_entity_type   str  "domestic_general" | "domestic_limited" |
                              "domestic_llc" | "foreign"
  sch_b_2a_yes          bool  Publicly traded partnership?
  sch_b_3a_yes          bool  Any partner a disregarded entity?

  ── SCHEDULE K (distributive share) ────────────────────────────────────────
  k_line_1           float  Ordinary income/(loss)
  k_line_2           float  Net rental real estate income
  k_line_5           float  Interest income
  k_line_6a          float  Ordinary dividends
  k_line_7           float  Royalties
  k_line_8           float  Net short-term capital gain/(loss)
  k_line_9a          float  Net long-term capital gain/(loss)
  k_line_11          float  Other income/(loss)
  k_line_12          float  Section 179 deduction
  k_line_13a         float  Contributions
  k_line_18          float  Tax-exempt interest income
  k_line_19a         float  Distributions of cash
  k_line_20          float  Other items

  ── SCHEDULE L (balance sheet) ──────────────────────────────────────────────
  l_cash_beg          float  Cash – beginning
  l_cash_end          float  Cash – end
  l_ar_beg            float  Accounts receivable – beg
  l_ar_end            float  Accounts receivable – end
  l_other_assets_beg  float  Other current assets – beg
  l_other_assets_end  float  Other current assets – end
  l_fixed_assets_beg  float  Fixed assets (cost) – beg
  l_fixed_assets_end  float  Fixed assets (cost) – end
  l_total_assets_beg  float  Total assets – beg
  l_total_assets_end  float  Total assets – end
  l_ap_beg            float  Accounts payable – beg
  l_ap_end            float  Accounts payable – end
  l_partners_cap_beg  float  Partners' capital – beg
  l_partners_cap_end  float  Partners' capital – end
  l_total_liab_beg    float  Total liabilities & capital – beg
  l_total_liab_end    float  Total liabilities & capital – end

  ── SCHEDULE M-1 ────────────────────────────────────────────────────────────
  m1_line_1          float  Net income per books
  m1_line_9          float  Income per return

  ── SCHEDULE M-2 ────────────────────────────────────────────────────────────
  m2_beg_capital      float  Beginning capital
  m2_capital_contrib  float  Capital contributed
  m2_net_income       float  Net income per books
  m2_distributions    float  Distributions
  m2_end_capital      float  Ending capital account
'''