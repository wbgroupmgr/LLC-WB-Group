"""
Form1065.py
===========
IRS Form 1065 (U.S. Return of Partnership Income) service.

Workflow
--------
    from irs.Form1065 import Form1065
    from ledger.LLC   import LLC

    llc   = LLC()
    f1065 = Form1065(llc=llc)

    nspace   = f1065._buildNSpace()           # discover AcroForm fields
    f1065.saveNSpace(nspace)                  # save namespace JSON + worksheet PDF

    fillDict = f1065._buildFillDict(nspace)   # assign publish flags + resolve values
    f1065.saveFILL(fillDict)                  # write FILL.pdf + save fillDict JSON

Data sources for the FILL PDF
------------------------------
  entity  – llcProfile_WBGroupLLC.json   →  profile["entity"]
  F1065   – llcProfile_WBGroupLLC.json   →  profile["F1065"]
  IS      – llcFinancialReport(llc).taxData()  →  td["is_data"]
  BS      – llcFinancialReport(llc).taxData()  →  td["bs_data"]
  owners  – llcFinancialReport(llc).taxData()  →  td["owners"]

IS/BS/owners are ALWAYS sourced from the official llcFinancialReport databases
built from self.llc.  Working EditSessions are intentionally excluded; they
must not feed the filed return.  Pass ``is_data`` / ``bs_data`` kwargs only
to override specific lines for testing.

Timestamp of last change: 2026.04.18
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from irs.irsForm import irsForm

# ── Folder paths (relative to this file) ────────────────────────────────────
_HERE      = Path(__file__).resolve().parent          # …/Notebooks/irs/
_FORMS_DIR = _HERE.parent.parent / "2025" / "YE_Tax_Records" / "Forms_IRS"
_ROOT_DIR  = _HERE.parent.parent.parent.parent        # LLC-WB-Group root


# ════════════════════════════════════════════════════════════════════════════
#  GL → IRS FIELD MAP  (logicalKey → fill spec)
#
#  source  : "entity" | "F1065" | "IS" | "BS" | "owners"
#  path    : dotted key within that source object
#  note    : human description
# ════════════════════════════════════════════════════════════════════════════

_FILL_MAP: Dict[str, Dict] = {

    # ── Page 1 Header ─────────────────────────────────────────────────────
    "P1_Hdr_0": {"source": "F1065",  "path": "date_from",
                 "note": "Tax year beginning month/day  e.g. 'Jan. 01'"},
    "P1_Hdr_1": {"source": "F1065",  "path": "tax_year",
                 "note": "2-digit tax year suffix  e.g. '25'"},
    "P1_Hdr_2": {"source": "F1065",  "path": "date_to",
                 "note": "Tax year ending month/day  e.g. 'Dec. 31'"},
    "P1_Hdr_3": {"source": "F1065",  "path": "tax_year",
                 "note": "2-digit ending year suffix"},
    "P1_Hdr_4": {"source": "entity", "path": "entity_name",
                 "note": "Legal LLC name"},
    "P1_Hdr_5": {"source": "entity", "path": "address",
                 "note": "Principal office street address"},
    "P1_Hdr_7": {"source": "F1065",  "path": "C_city",
                 "note": "City"},
    "P1_Hdr_8": {"source": "F1065",  "path": "C_state",
                 "note": "State abbreviation"},
    "P1_Hdr_9": {"source": "F1065",  "path": "C_zip",
                 "note": "ZIP code"},

    # ── Page 1 Entity Info (Lines A–K) ────────────────────────────────────
    "P1_A":  {"source": "F1065",  "path": "principal_activity",
              "note": "Principal business activity"},
    "P1_B":  {"source": "F1065",  "path": "B_product",
              "note": "Principal product or service"},
    "P1_C":  {"source": "F1065",  "path": "C_busCode",
              "note": "Business activity code (NAICS)"},
    "P1_D":  {"source": "entity", "path": "ein",
              "note": "Employer Identification Number"},
    "P1_E":  {"source": "entity", "path": "date_business_began",
              "note": "Date business started"},
    "P1_F":  {"source": "BS",     "path": "total_assets",
              "note": "Total assets end of year from Balance Sheet"},
    "P1_I":  {"source": "owners", "path": "count",
              "note": "Number of Schedule K-1s = number of partners"},

    # ── Page 1 Income ──────────────────────────────────────────────────────
    "P1_1a": {"source": "IS", "path": "rent_income",
              "note": "Gross rental receipts  (Acct.Rev.Rent.*)"},
    "P1_1c": {"source": "IS", "path": "rent_income",
              "note": "Line 1c = 1a − 1b  (1b blank/zero for rental)"},
    "P1_3":  {"source": "IS", "path": "rent_income",
              "note": "Gross profit = 1c − 2  (Line 2 COGS=0 for rental)"},
    "P1_7":  {"source": "IS", "path": "other_income",
              "note": "Other income  (Acct.Rev.* excl. Rent)"},
    "P1_8":  {"source": "IS", "path": "total_income",
              "note": "Total income = sum of lines 3–7"},

    # ── Page 1 Deductions ─────────────────────────────────────────────────
    "P1_9":   {"source": "IS", "path": "salaries",
               "note": "Salaries and wages  (Acct.Exp.Salary.*)"},
    "P1_11":  {"source": "IS", "path": "repairs",
               "note": "Repairs and maintenance  (Acct.Exp.Repair.*)"},
    "P1_14":  {"source": "IS", "path": "taxes_licenses",
               "note": "Taxes and licenses  (Acct.Exp.Tax.*)"},
    "P1_15":  {"source": "IS", "path": "interest_expense",
               "note": "Interest expense  (Acct.Exp.Interest.*)"},
    "P1_16a": {"source": "IS", "path": "depreciation",
               "note": "Depreciation expense  (Acct.Exp.Depr.*)"},
    "P1_16c": {"source": "IS", "path": "depreciation",
               "note": "Net depreciation = 16a − 16b  (16b blank here)"},
    "P1_21":  {"source": "IS", "path": "other_deductions",
               "note": "Other deductions not listed above"},
    "P1_22":  {"source": "IS", "path": "total_expenses",
               "note": "Total deductions = sum of lines 9–21"},
    "P1_23":  {"source": "IS", "path": "net_income",
               "note": "Ordinary business income (loss) = Line 8 − Line 22"},

    # ── Page 1 Paid Preparer ──────────────────────────────────────────────
    "P1_PP_0": {"source": "F1065", "path": "preparer_name",
                "note": "Paid preparer name"},
    "P1_PP_2": {"source": "F1065", "path": "preparer_date",
                "note": "Preparer signature date"},
    "P1_PP_3": {"source": "F1065", "path": "preparer_ptin",
                "note": "Preparer PTIN"},
    "P1_PP_4": {"source": "F1065", "path": "preparer_ein",
                "note": "Preparer / firm EIN"},
    "P1_PP_5": {"source": "F1065", "path": "preparer_firm",
                "note": "Preparer firm name"},
    "P1_PP_6": {"source": "F1065", "path": "preparer_addr",
                "note": "Preparer firm address"},

    # ── Page 4 Partnership Representative ────────────────────────────────
    "B_PR_1":  {"source": "F1065", "path": "B_PRDI_FirstNm",
                "note": "Partnership Representative first name"},
    "B_PR_2":  {"source": "F1065", "path": "B_PRDI_Last",
                "note": "Partnership Representative last name"},
    "B_PR_3":  {"source": "F1065", "path": "B_PRDI_Street",
                "note": "PR street address"},
    "B_PR_4":  {"source": "F1065", "path": "B_PRDI_City",
                "note": "PR city"},
    "B_PR_5":  {"source": "F1065", "path": "B_PRDI_St",
                "note": "PR state"},
    "B_PR_6":  {"source": "F1065", "path": "B_PRDI_Zip",
                "note": "PR ZIP"},
    "B_PR_7":  {"source": "F1065", "path": "B_PRDI_Ph",
                "note": "PR daytime phone"},
    "B_PRDI_1": {"source": "F1065", "path": "B_PRDI_FirstNm",
                 "note": "DI first name"},
    "B_PRDI_2": {"source": "F1065", "path": "B_PRDI_Last",
                 "note": "DI last name"},
    "B_PRDI_3": {"source": "F1065", "path": "B_PRDI_Street",
                 "note": "DI street"},
    "B_PRDI_4": {"source": "F1065", "path": "B_PRDI_City",
                 "note": "DI city"},
    "B_PRDI_5": {"source": "F1065", "path": "B_PRDI_St",
                 "note": "DI state"},
    "B_PRDI_6": {"source": "F1065", "path": "B_PRDI_Zip",
                 "note": "DI ZIP"},
    "B_PRDI_7": {"source": "F1065", "path": "B_PRDI_Ph",
                 "note": "DI phone"},

    # ── Sched B: partner count ────────────────────────────────────────────
    "B_25Fm":  {"source": "owners", "path": "count",
                "note": "Number of Schedule K-1s attached"},

    # ── Schedule K (Page 5) ───────────────────────────────────────────────
    "K_1":    {"source": "IS", "path": "net_income",
               "note": "Ordinary business income (loss) — same as Pg1 Line 23"},
    "K_2":    {"source": "IS", "path": "rent_income",
               "note": "Net rental real estate income (loss)"},
    "K_5":    {"source": "IS", "path": "interest_income",
               "note": "Interest income  (Acct.Rev.Interest.*)"},
    "K_19a":  {"source": "IS", "path": "distributions_cash",
               "note": "Distributions of cash"},
    "K_20a":  {"source": "IS", "path": "interest_income",
               "note": "Investment income = interest income"},

    # ── Schedule L – ASSETS (end of year = _2 sub-field) ─────────────────
    "L_1_2":   {"source": "BS", "path": "cash",
                "note": "Cash — end of year"},
    "L_2a_2":  {"source": "BS", "path": "ar",
                "note": "Accounts receivable — end of year (gross)"},
    "L_9a_2":  {"source": "BS", "path": "buildings",
                "note": "Buildings / depreciable assets — end of year (cost)"},
    "L_9b_2":  {"source": "BS", "path": "accum_depr",
                "note": "Less accumulated depreciation — end of year"},
    "L_11_2":  {"source": "BS", "path": "land",
                "note": "Land — end of year"},
    "L_13_2":  {"source": "BS", "path": "other_assets",
                "note": "Other assets — end of year"},
    "L_14_2":  {"source": "BS", "path": "total_assets",
                "note": "Total assets — end of year"},

    # ── Schedule L – LIABILITIES & CAPITAL ───────────────────────────────
    "L_15_2":  {"source": "BS", "path": "payables",
                "note": "Accounts payable — end of year"},
    "L_19a_2": {"source": "BS", "path": "mortgage",
                "note": "Mortgages, notes payable ≥ 1 year — end of year"},
    "L_20_2":  {"source": "BS", "path": "other_liab",
                "note": "Other liabilities — end of year"},
    "L_21_2":  {"source": "BS", "path": "total_equity",
                "note": "Partners' capital accounts — end of year"},
    "L_22_2":  {"source": "BS", "path": "total_liab_capital",
                "note": "Total liabilities and capital — end of year"},

    # ── Schedule M-1 ──────────────────────────────────────────────────────
    "M1_1":    {"source": "IS", "path": "net_income",
                "note": "Net income (loss) per books"},
    "M1_5":    {"source": "IS", "path": "net_income",
                "note": "M-1 Line 5 subtotal (simplified = net_income)"},
    "M1_9":    {"source": "IS", "path": "net_income",
                "note": "Income per return (simplified when no M-1 adjustments)"},

    # ── Schedule M-2 ──────────────────────────────────────────────────────
    "M2_2a":   {"source": "owners", "path": "cash_contributions",
                "note": "Capital contributed: cash"},
    "M2_3":    {"source": "IS",     "path": "net_income",
                "note": "Net income (loss) per books"},
    "M2_6a":   {"source": "IS",     "path": "distributions_cash",
                "note": "Distributions: cash"},
    "M2_8":    {"source": "IS",     "path": "distributions_cash",
                "note": "Total of lines 6a, 6b, 7 (= 6a when 6b and 7 are zero)"},
    "M2_9":    {"source": "BS",     "path": "total_equity",
                "note": "Balance at end of year = partners' capital per GL"},
}

# Fields that need CPA / manual entry
_CPA_NOTES: Dict[str, str] = {
    "P1_Hdr_6": "Suite / Room / Apt — blank for this LLC",
    "P1_1b":    "Returns and allowances — enter 0 or blank for rental LLC",
    "P1_2":     "Cost of goods sold — enter 0 for rental LLC",
    "P1_4":     "Ordinary income from OTHER partnerships — CPA review",
    "P1_5":     "Net farm profit — not applicable",
    "P1_6":     "Net gain (loss) from Form 4797 — CPA review if property disposed",
    "P1_10":    "Guaranteed payments to partners — CPA review",
    "P1_12":    "Bad debts — CPA review",
    "P1_13":    "Rent (expense) — usually 0 if LLC owns its property",
    "P1_16b":   "Less: depreciation reported elsewhere (Form 4562) — CPA review",
    "P1_17":    "Depletion — not applicable for real estate LLC",
    "P1_18":    "Retirement plan contributions — CPA review",
    "P1_19":    "Employee benefit programs — CPA review",
    "P1_20":    "Energy efficient commercial building deduction — CPA review",
    "P1_H":     "Accounting method (Cash / Accrual / Other) — CPA review",
    "M1_2":     "Income on return not in books — CPA review",
    "M1_3":     "Guaranteed payments — CPA review",
    "M1_4a":    "Depreciation excess of tax over book — CPA review",
    "M1_4b":    "Travel & entertainment disallowed — CPA review",
    "M1_4c":    "Other book-not-return items — CPA review",
    "M1_6":     "Income in books not on return — CPA review",
    "M1_7":     "Deductions on return not in books — CPA review",
    "M2_1":     "Beginning capital — requires prior-year ending balance",
    "M2_2b":    "Capital contributed: property — CPA review",
    "M2_5":     "M-2 subtotal — computed: lines 1+2a+2b+3+4",
    "L_2b_2":   "Less allowance for bad debts — CPA review",
    "L_16_2":   "Mortgages payable < 1 year — CPA review",
    "L_17_2":   "Other current liabilities — CPA review",
    "L_18_2":   "All nonrecourse loans — CPA review",
}


# ════════════════════════════════════════════════════════════════════════════
#  FORM 1065 — irsForm subclass
# ════════════════════════════════════════════════════════════════════════════

class Form1065(irsForm):
    """
    IRS Form 1065 (U.S. Return of Partnership Income) service.

    Inherits the 4-step workflow from ``irsForm``:

        nspace   = f._buildNSpace()
        f.saveNSpace(nspace)
        fillDict = f._buildFillDict(nspace)   # single-pass: publish flags + values
        f.saveFILL(fillDict)                   # writes FILL.pdf + fillDict JSON

    ``self.oID = "Form1065"``  (drives all file names)
    IRS template : {irsDir}/Form1065_IRS.pdf  (or legacy Form_1065-IRS.pdf)
    """

    # ── Location-derivation rules (ordered — first match wins) ───────────
    LOCATION_RULES: List[Tuple[str, str]] = [
        # Page 1
        (r'^P1_Hdr',               "Form1065.Pg1.Header"),
        (r'^P1_Sign',              "Form1065.Pg1.SignHere"),
        (r'^P1_PP',                "Form1065.Pg1.PaidPreparer"),
        (r'^P1_[A-F]$',            "Form1065.Pg1.EntityInfo"),
        (r'^P1_[GHIJK]',           "Form1065.Pg1.EntityInfo"),
        (r'^P1_(1[a-c]?|[2-8])$',  "Form1065.Pg1.Income"),
        (r'^P1_(9|1[0-9]|2[0-3]|16[ab]?)', "Form1065.Pg1.Deductions"),
        (r'^P1_(2[4-9]|3[0-2])',   "Form1065.Pg1.TaxAndPayments"),
        (r'^P1_',                  "Form1065.Pg1.Other"),
        # Pages 2–4 — Schedule B / Partnership Rep
        (r'^B_PR',                 "Form1065.Pg4.PartnerRep"),
        (r'^B_',                   "Form1065.Pg2-3.SchedB"),
        # Page 5 — Schedule K
        (r'^K_',                   "Form1065.Pg5.SchedK"),
        # Page 6 — Schedule L / M-1 / M-2 / ANI
        (r'^L_ANI',                "Form1065.Pg6.ANI"),
        (r'^L_',                   "Form1065.Pg6.SchedL"),
        (r'^M1_',                  "Form1065.Pg6.SchedM1"),
        (r'^M2_',                  "Form1065.Pg6.SchedM2"),
        # Sched B Yes/No synthesised keys  (c{pg}_{seq}_Yes / _No)
        (r'^c\d+_\d+_',            "Form1065.Pg2-3.SchedB"),
    ]

    _FILL_MAP  = _FILL_MAP
    _CPA_NOTES = _CPA_NOTES

    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        print("xxxx form1065 324", self.verbose)

    # ── IRS template filename override ───────────────────────────────────
    def FN(self) -> str:
        canonical = self.irsDir / f"{self.oID}_IRS.pdf"
        if canonical.exists():
            return str(canonical)
        legacy = self.irsDir / "Form_1065-IRS.pdf"
        if legacy.exists():
            return str(legacy)
        return str(canonical)

    # ── Keys PDF loader override (legacy name) ────────────────────────────
    def _loadKeyMap(self) -> Dict[str, str]:
        candidates = [
            self.irsDir / f"{self.oID}-keys.pdf",
            self.irsDir / "Form_1065-keys.pdf",
        ]
        for p in candidates:
            if p.exists():
                try:
                    from pypdf import PdfReader
                    rdr = PdfReader(str(p))
                    raw = rdr.get_fields() or {}
                    km: Dict[str, str] = {}
                    for fid, fobj in raw.items():
                        v = fobj.get("/V")
                        if v is None:
                            continue
                        v_str = str(v).strip()
                        if v_str and v_str != "/Off":
                            short = fid.split(".")[-1].split("[")[0]
                            km[short] = v_str
                    return km
                except Exception as exc:
                    if self.verbose:
                        print(f"  ⚠️  Keys PDF read error ({p.name}): {exc}")
        if self.verbose:
            print(f"  ⚠️  Keys PDF not found for {self.oID} — logicalKeys will be empty")
        return {}

    # ── FieldNames loader override ────────────────────────────────────────
    def _loadLabelMap(self) -> Dict[str, str]:
        candidates = [
            self.irsDir / f"{self.oID}-FieldNames.json",
            self.irsDir / "Form_1065-FieldNames.json",
        ]
        for p in candidates:
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return {str(k): str(v) for k, v in data.items()}
                except Exception:
                    pass
        if self.verbose:
            print(f"  ⚠️  FieldNames JSON not found for {self.oID} — labels will be empty")
        return {}

    # ════════════════════════════════════════════════════════════════════════
    #  COMBINED STEP: BUILD FILL DICT
    #  (replaces old _buildGLMap + _buildFillDict two-step)
    # ════════════════════════════════════════════════════════════════════════

    def _defaultFill(self, nSpaceDict):
        # ── Step A: base dict — all fields, publish=False, value="" ───────
        return super()._buildFillDict(nSpaceDict)

    def _buildFillDict(                             # type: ignore[override]
        self,
        nSpaceDict: Dict,
        is_data:    Optional[Dict] = None,
        bs_data:    Optional[Dict] = None,
        **kwargs,
    ) -> Dict:
        """
        Single-pass: build fillDict for ALL namespace fields.

        For every non-container field in ``nSpaceDict``:
          • Sets ``publish=True``         — fields mapped in ``_FILL_MAP``
          • Sets ``publish="CPA:unknown"``— fields listed in ``_CPA_NOTES``
          • Sets ``publish=True``         — Schedule B No-answer checkText defaults
          • Sets ``publish=False``        — all remaining fields

        Values are resolved from the official llcFinancialReport databases
        (IS/BS/owners via ``_resolveTaxData()``).  Pass ``is_data`` / ``bs_data``
        only to override specific lines for testing.

        Parameters
        ----------
        nSpaceDict : dict
            Output of ``_buildNSpace()``.
        is_data : dict, optional
            Override IS lines.
        bs_data : dict, optional
            Override BS lines.

        Returns
        -------
        dict  Complete fillDict — ALL fields, publish flags set, values resolved.
        """
        
        # for verbose test progress
        tstFld = kwargs.get('testField', None)
        print(f"{self.oID} buildFillDict Entry verbose:{self.verbose}, testField:{tstFld}")
            
        # ── Step A: base dict — all fields, publish=False, value="" ───────
        fillDict = super()._buildFillDict(nSpaceDict)

        # ── Step B: build reverse index logicalKey → fID ──────────────────
        lk_to_fid: Dict[str, str] = {
            fd["logicalKey"]: fid
            for fid, fd in fillDict.items()
            if fd["logicalKey"]
        }

        # ── Step C: load official IS / BS / owners from llcFinancialReport ─
        owners_agg: Dict = {
            "count":              "0",
            "cash_contributions": 0.0,
            "distributions_cash": 0.0,
        }
        if is_data is None or bs_data is None:
            td = self._resolveTaxData()
            if is_data is None:
                is_data = td.get("is_data", {})
            if bs_data is None:
                bs_data = td.get("bs_data", {})
            owners_agg = td.get("owners", owners_agg)
                
        # ── Step D: load entity / F1065 profile ───────────────────────────
        entity, f1065_data = self._loadProfile()

        # ── Step E: source map ────────────────────────────────────────────
        src_map: Dict = {
            "entity":       entity,
            "F1065":        f1065_data,
            "IS":           is_data   or {},
            "BS":           bs_data   or {},
            "owners":       owners_agg,
            "schB_default": {"No": "/2", "Yes": "/1"},
        }
        if self.verbose:
            print(f"--- {self.oID} buildFillDict StepE verbose{self.verbose}, testFld:{tstFld}, is_data:{len(is_data)}, bs_data:{len(bs_data)}")
            if tstFld:
                print(f"--- buildFill: StepE testfield {fillDict[tstFld]['value']}")


        # ── Step F: apply _FILL_MAP  (publish=True + resolve value) ───────
        for lk, spec in self._FILL_MAP.items():
            fid = lk_to_fid.get(lk)
            if not fid or fid not in fillDict:
                continue
            fd    = fillDict[fid]
            ftype = fd["fType"]

            if ftype in ("checkBox", "checkText", "box"):
                value = fd.get("checkedValue", "/1")
            else:
                value = self._resolve(spec["source"], spec["path"], src_map) or ""

            fillDict[fid].update({
                "publish": True,
                "source":  spec["source"],
                "path":    spec["path"],
                "note":    spec.get("note", ""),
                "value":   value,
            })
        
        if self.verbose:
            print(f"---- {self.oID} buildFillDict StepF verbose{self.verbose}, testFld:{tstFld}")
            if tstFld:
                print(f"-----buildFill: StepF testfield {fillDict[tstFld]}")


        # ── Step G: apply _CPA_NOTES  (publish="CPA:unknown") ─────────────
        for lk, note in self._CPA_NOTES.items():
            fid = lk_to_fid.get(lk)
            if not fid or fid not in fillDict:
                continue
            if fillDict[fid].get("publish") is True:
                continue   # FILL_MAP takes precedence
            fillDict[fid].update({
                "publish": "CPA:unknown",
                "source":  None,
                "path":    None,
                "note":    note,
                "value":   "",
            })

        # ── Step H: Schedule B No defaults ────────────────────────────────
        # All Sched B Yes/No questions default to "No".
        # checkText (index [1] = No) → publish=True, value=checkedValue.
        # checkBox  (index [0] = Yes) → remains publish=False.
        for fid, fd in fillDict.items():
            if fd.get("publish") is True:
                continue   # already handled
            ftype = fd.get("fType", "")
            lk    = fd.get("logicalKey", "")
            sn    = fd.get("shortName", "")

            is_schb_no = False

            # Path A — synthesised logicalKey  c{pg}_{seq}_No
            if ftype == "checkText" and re.match(r'^c\d+_\d+_No$', lk):
                is_schb_no = True

            # Path B — old-style "box" fType with pdfField index ≥ 1
            if not is_schb_no and ftype == "box" and sn.startswith("c"):
                leaf  = fd.get("pdfField", "").split(".")[-1]
                m_idx = re.search(r'\[(\d+)\]$', leaf)
                if m_idx and int(m_idx.group(1)) >= 1:
                    is_schb_no = True

            if is_schb_no:
                fillDict[fid].update({
                    "publish": True,
                    "source":  "schB_default",
                    "path":    "No",
                    "note":    "Sched B default: No — override to Yes if applicable",
                    "value":   fd.get("checkedValue", "/2"),
                })

        
        if self.verbose and tstFld :
            print(f"buildFill: Final testfield {fillDict[tstFld]['value']}")


        # ── Diagnostics ────────────────────────────────────────────────────
        if self.verbose:
            pub = sum(1 for v in fillDict.values() if v.get("publish") is True)
            cpa = sum(1 for v in fillDict.values() if v.get("publish") == "CPA:unknown")
            blk = len(fillDict) - pub - cpa
            txt = sum(1 for v in fillDict.values()
                      if v.get("publish") is True
                      and v["fType"] not in ("checkBox", "checkText", "box"))
            chk = pub - txt
            print(f"  ✅ fillDict built  → {len(fillDict)} fields total  "
                  f"(publish={pub} [text={txt}, chk={chk}], "
                  f"cpa={cpa}, blank={blk})")

        return fillDict

    # ════════════════════════════════════════════════════════════════════════
    #  TAX DATA HELPERS
    # ════════════════════════════════════════════════════════════════════════

    def _resolveTaxData(self) -> Dict:
        """
        Return IS/BS/owners data from the **official** llcFinancialReport DB.

        Always uses ``llcFinancialReport(self.llc).taxData()``.
        Working EditSessions are intentionally excluded.

        Falls back to empty dicts (with warning) only if ``self.llc`` is None
        or the import fails.
        """
        if self.llc is not None:
            try:
                try:
                    from ledger.llcFinancialReport import llcFinancialReport
                except ImportError:
                    from llcFinancialReport import llcFinancialReport

                fr = llcFinancialReport(self.llc)
                td = self._getFRData(fr)

                if self.verbose:
                    ni = td.get("is_data", {}).get("net_income", "?")
                    ta = td.get("bs_data", {}).get("total_assets", "?")
                    print(f"  ℹ️  llcFinancialReport loaded  "
                          f"(net_income={ni}, total_assets={ta})")
                return td

            except Exception as exc:
                if self.verbose:
                    print(f"  ⚠️  _resolveTaxData: llcFinancialReport failed: {exc}")

        if self.verbose:
            print("  ⚠️  _resolveTaxData: self.llc is None — "
                  "pass llc to Form1065() or supply is_data/bs_data kwargs")
        return {"is_data": {}, "bs_data": {}, "owners": {}}

    def _getFRData(self, fr) -> Dict:
        """
        Call ``fr.taxData()`` and return the parsed dict
        ``{ is_data, bs_data, owners, meta }``.
        """
        try:
            return json.loads(fr.taxData())
        except Exception as exc:
            if self.verbose:
                print(f"  ⚠️  _getFRData: taxData() failed: {exc}")
            return {"is_data": {}, "bs_data": {}, "owners": {}}


# ════════════════════════════════════════════════════════════════════════════
#  LEGACY CLASS — kept for backward compatibility
# ════════════════════════════════════════════════════════════════════════════

class Form1065Preparer:
    """
    Legacy class — maps GL balances to Form 1065 lines.
    Kept for backward compatibility.  New code should use Form1065(irsForm).
    """

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
        self.result = None
        self._validate_gl()

    def _validate_gl(self) -> None:
        unknown = set(self.gl.keys()) - self.KNOWN_ACCOUNTS
        if unknown:
            print(f"[WARNING] Unrecognised GL accounts (will be ignored): {unknown}")
        for acct, val in self.gl.items():
            if not isinstance(val, (int, float)):
                raise TypeError(f"GL value for '{acct}' must be numeric, got {type(val)}")

    def _get(self, key: str, default: float = 0.0) -> float:
        return self.gl.get(key, default)

    def compute(self):
        asset_purchase   = self._get("Acct.Asset.Purchase")
        cash_expense     = self._get("Acct.Cash.Expense")
        cash_income      = self._get("Acct.Cash.Income")
        cash_investment  = self._get("Acct.Cash.Investment")
        cash_misc        = self._get("Acct.Cash.Misc")
        cash_util        = self._get("Acct.Cash.Util")
        interest_income  = self._get("Acct.Interest.Income")

        line_1a = abs(cash_income) if cash_income > 0 else 0.0
        line_5  = abs(interest_income) if interest_income > 0 else 0.0
        line_7  = abs(cash_misc) if cash_misc > 0 else 0.0
        total_income = line_1a + line_5 + line_7

        line_20 = (abs(cash_expense) if cash_expense < 0 else cash_expense) + \
                  (abs(cash_util)    if cash_util    < 0 else cash_util)
        total_deductions = line_20
        ordinary_income  = total_income - total_deductions

        return {
            "line_1a": line_1a,
            "line_5":  line_5,
            "line_7":  line_7,
            "total_income": total_income,
            "line_20": line_20,
            "total_deductions": total_deductions,
            "ordinary_income":  ordinary_income,
        }

    @staticmethod
    def _buildGL2IRSMap(
        namespace_path: Optional[Path] = None,
        output_path:    Optional[Path] = None,
        verbose: bool = True,
    ) -> Dict:
        """Legacy — use Form1065(irsForm)._buildFillDict(nspace) instead."""
        ns_path  = namespace_path or (_FORMS_DIR / "Form1065_namespace.json")
        out_path = output_path    or (_FORMS_DIR / "Form1065_GLMap.json")

        if not ns_path.exists():
            raise FileNotFoundError(f"Namespace JSON not found: {ns_path}")

        with open(ns_path, encoding="utf-8") as fh:
            ns = json.load(fh)

        fields     = ns.get("fields", {})
        form_fill:  Dict[str, Dict] = {}
        form_empty: Dict[str, Dict] = {}

        for fid, fd in fields.items():
            lk    = fd.get("logicalKey", "")
            label = fd.get("label", "")
            ftype = fd.get("fType", "")
            page  = fd.get("page", 0)
            loc   = fd.get("location", "")

            if ftype in ("container", "image"):
                continue

            fill_spec = _FILL_MAP.get(lk)
            if fill_spec:
                form_fill[fid] = {
                    "logicalKey": lk, "label": label,
                    "source": fill_spec["source"],
                    "path":   fill_spec["path"],
                    "note":   fill_spec.get("note", ""),
                    "page": page, "location": loc,
                }
            else:
                cpa_note = _CPA_NOTES.get(lk, "Not auto-mapped — CPA or manual entry required")
                form_empty[fid] = {
                    "logicalKey": lk, "label": label,
                    "note": cpa_note, "page": page, "location": loc,
                }

        gl_map = {
            "form":        "Form1065",
            "source_json": str(ns_path.name),
            "generated":   __import__("datetime").date.today().isoformat(),
            "formFill":    form_fill,
            "formEmpty":   form_empty,
        }

        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(gl_map, fh, indent=2, ensure_ascii=False)

        if verbose:
            print(f"  ✅  Form1065_GLMap.json  →  {out_path.name}")
        return gl_map
