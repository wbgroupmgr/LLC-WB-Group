"""
Sch_K1.py
=========
IRS Schedule K-1 (Form 1065) service — per-partner allocations.

Subclass of Form1065.  Reuses Form1065's financial data pipeline
(``_resolveTaxData`` → IS/BS/owners) and distributes each line by
the partner's profit/loss percentage.

Workflow — single-partner PDF
------------------------------
    from irs.Sch_K1   import Sch_K1
    from ledger.LLC   import LLC

    llc  = LLC()
    k1   = Sch_K1(llc=llc, verbose=True)

    nspace   = k1._buildNSpace()
    k1.saveNSpace(nspace)

    for i, owner in enumerate(owners):
        fillDict = k1._buildFillDict(nspace, partner_idx=i)
        k1.saveFILL(fillDict, suffix=f"_{owner['oID']}")

Workflow — all partners at once
--------------------------------
    k1.saveFILL_allPartners(nspace)   # convenience wrapper

Data sources
------------
  partnership  – same entity/F1065 profile as Form1065
  partner      – llcOwners[i]: name, address, pct
  partner_IS   – IS totals × partner.pct  (rent, interest, NI, distributions)
  partner_cap  – capital account: contributions × pct, NI × pct, distributions × pct

Timestamp of last change: 2026.04.18
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path

try:
    from irs.Form1065 import Form1065
except ImportError:
    from Form1065 import Form1065

try:
    from irs.taxAgents.FormSchK1Agent import gl_contributions, gl_distributions, gl_ending_capital
except ImportError:
    # Fallback stubs — should never be reached in production
    def gl_contributions(llc, oID): return 0.0     # noqa: E704
    def gl_distributions(llc, oID): return 0.0     # noqa: E704
    def gl_ending_capital(llc, oID, pct, net_rental=None): return 0.0  # noqa: E704


# ════════════════════════════════════════════════════════════════════════════
#  DATE PARSING  — "Jan. 01" or "01/01" → (month_str, day_str)
# ════════════════════════════════════════════════════════════════════════════

def _parse_month_day(date_str: str):
    """Return (MM, DD) strings from 'Jan. 01' or 'MM/DD' or 'MM-DD'."""
    _MONTH_MAP = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
        'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
        'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
    }
    s = str(date_str or '').strip().lower()
    for abbr, mm in _MONTH_MAP.items():
        if s.startswith(abbr):
            day_m = re.search(r'(\d{1,2})\s*$', s)
            return mm, (day_m.group(1).zfill(2) if day_m else '01')
    m = re.match(r'(\d{1,2})[/\-](\d{1,2})', s)
    if m:
        return m.group(1).zfill(2), m.group(2).zfill(2)
    return '01', '01'


# ════════════════════════════════════════════════════════════════════════════
#  K-1 FIELD MAP  (logicalKey → fill spec)
# ════════════════════════════════════════════════════════════════════════════

_FILL_MAP_K1: Dict[str, Dict] = {

    # ── Tax year header (same for every K-1) ────────────────────────────────
    "K1_TaxYrBeginMon": {"source": "F1065", "path": "date_from_month",
                         "note": "Tax year beginning — month (MM)"},
    "K1_TaxYrBeginDay": {"source": "F1065", "path": "date_from_day",
                         "note": "Tax year beginning — day (DD)"},
    "K1_TaxYrEndMon":   {"source": "F1065", "path": "date_to_month",
                         "note": "Tax year ending — month (MM)"},
    "K1_TaxYrEndDay":   {"source": "F1065", "path": "date_to_day",
                         "note": "Tax year ending — day (DD)"},
    "K1_TaxYr":         {"source": "F1065", "path": "tax_year_2d",
                         "note": "Tax year ending — 2-digit (e.g. '25')"},
    "K1_Final":         {"source": "F1065", "path": "is_final_k1",
                         "note": "Final K-1 flag (checkBox — only set when True)"},
    "K1_Amended":       {"source": "F1065", "path": "is_amended_k1",
                         "note": "Amended K-1 flag (checkBox — only set when True)"},

    # ── Partnership identification (Part I, same for every K-1) ─────────────
    "K1_EIN":       {"source": "entity",  "path": "ein",
                     "note": "Partnership EIN (Line A)"},
    "K1_PshipNm":   {"source": "entity",  "path": "entity_name",
                     "note": "Partnership name (Line B)"},
    "K1_PshipAddr": {"source": "entity",  "path": "address",
                     "note": "Partnership street address (Line B)"},
    "K1_PshipCSZ":  {"source": "entity",  "path": "city_state_zip",
                     "note": "Partnership city/state/ZIP (Line B)"},
    "K1_IRSCtr":    {"source": "F1065",   "path": "irs_center",
                     "note": "IRS Service Center (Line C)"},
    "K1_PTP":       {"source": "F1065",   "path": "is_ptp",
                     "note": "PTP flag (Line D) — always False for private LLC"},

    # ── Partner identification (Part II, per-partner) ────────────────────────
    "K1_PtEIN":     {"source": "partner", "path": "ein",
                     "note": "Partner's SSN or EIN (Line E)"},
    "K1_PtName":    {"source": "partner", "path": "name",
                     "note": "Partner's name (Line F)"},
    "K1_PtAddr":    {"source": "partner", "path": "address",
                     "note": "Partner's address/city/state/ZIP (Line F)"},
    "K1_PtTypeGP":  {"source": "partner", "path": "is_gp_manager",
                     "note": "Line G: GP/LLC member-manager checkbox"},
    "K1_PtTypeLP":  {"source": "partner", "path": "is_lp_member",
                     "note": "Line G: LP/LLC member checkbox"},
    "K1_PtDomestic":{"source": "partner", "path": "is_domestic",
                     "note": "Line H1: Domestic partner"},
    "K1_PtForeign": {"source": "partner", "path": "is_foreign",
                     "note": "Line H1: Foreign partner"},
    "K1_PtDE":      {"source": "partner", "path": "is_de",
                     "note": "Line H2: Disregarded entity"},
    "K1_PtRetPlan": {"source": "partner", "path": "is_ret_plan",
                     "note": "Line I: Partner is retirement plan"},

    # ── Box J — ownership percentages (end of year) ──────────────────────────
    "K1_J_Profit":    {"source": "partner", "path": "pct_str",
                       "note": "Box J Profit % end of year"},
    "K1_J_Loss":      {"source": "partner", "path": "pct_str",
                       "note": "Box J Loss % end of year"},
    "K1_J_Capital":   {"source": "partner", "path": "pct_str",
                       "note": "Box J Capital % end of year"},
    # Beginning of year — blank for first year; same as end for ongoing
    "K1_J_ProfitBeg": {"source": "partner", "path": "pct_str_beg",
                       "note": "Box J Profit % beginning of year"},
    "K1_J_LossBeg":   {"source": "partner", "path": "pct_str_beg",
                       "note": "Box J Loss % beginning of year"},
    "K1_J_CapBeg":    {"source": "partner", "path": "pct_str_beg",
                       "note": "Box J Capital % beginning of year"},

    # ── Box K1 — partner's share of liabilities ──────────────────────────────
    # IRC §752; Treas. Reg. §1.752-2/3
    # Beginning-of-year (f31/f33/f35): $0 for a first-year LLC (no debt at BOY).
    # W&B: typical commercial RE mortgage = qualified nonrecourse (§465(b)(6)).
    # QNR: commercial lender, no personal guarantees, real property collateral only.
    "K1_K_NonrecBeg": {"source": "partner_BS", "path": "nonrecourse_beg",
                       "note": "Box K1: Nonrecourse liabilities beginning of year (first year = $0)"},
    "K1_K_QNRBeg":    {"source": "partner_BS", "path": "qnr_beg",
                       "note": "Box K1: QNR financing beginning of year (first year = $0)"},
    "K1_K_RecBeg":    {"source": "partner_BS", "path": "recourse_beg",
                       "note": "Box K1: Recourse liabilities beginning of year (first year = $0)"},
    "K1_K_Nonrec":   {"source": "partner_BS", "path": "nonrecourse",
                      "note": "Box K1: Nonrecourse liabilities × pct (end of year)"},
    "K1_K_QNR":      {"source": "partner_BS", "path": "qnr",
                      "note": "Box K1: Qualified nonrecourse financing × pct (end of year)"},
    "K1_K_Rec":      {"source": "partner_BS", "path": "recourse",
                      "note": "Box K1: Recourse liabilities × pct (end of year)"},

    # ── Box L — capital account analysis (tax basis, Rev. Proc. 2020-13) ────
    "K1_L_TaxBasis": {"source": "F1065",      "path": "cap_tax_basis_flag",
                      "note": "Box L method: Tax basis (checkBox, always checked)"},
    "K1_L1":         {"source": "partner_cap", "path": "beg_capital",
                      "note": "Box L: Capital account beginning of year"},
    "K1_L2":         {"source": "partner_cap", "path": "contributions",
                      "note": "Box L: Capital contributed during year"},
    "K1_L3":         {"source": "partner_cap", "path": "net_income",
                      "note": "Box L: Current year net income (loss) × pct"},
    "K1_L4":         {"source": "partner_cap", "path": "distributions",
                      "note": "Box L: Withdrawals and distributions"},
    "K1_L5":         {"source": "partner_cap", "path": "end_capital",
                      "note": "Box L: Ending capital account"},

    # ── Line N — §704(c) unrecognized gain/loss ──────────────────────────────
    "K1_N_Beg": {"source": "partner", "path": "sec704c_beg",
                 "note": "Line N: Net §704(c) gain — beginning ($0 if cash-only)"},
    "K1_N_End": {"source": "partner", "path": "sec704c_end",
                 "note": "Line N: Net §704(c) gain — end ($0 if cash-only)"},

    # ── Part III — Income / Deductions (per-partner) ─────────────────────────
    # Box 1: IRC §469(c)(2) — rental LLC MUST be $0 (passive, not ordinary)
    "K1_1":  {"source": "partner_IS", "path": "ordinary_income",
               "note": "Box 1: Ordinary income × pct — MUST be $0 (IRC §469(c)(2))"},
    # Box 2: Books-First (IRC §446/703) — IS.net_rental × pct
    "K1_2":  {"source": "partner_IS", "path": "net_rental",
               "note": "Box 2: Net rental income × pct (Books-First IRC §446)"},
    # Box 3: Other rental — $0 for real-estate-only LLC
    "K1_3":  {"source": "partner_IS", "path": "other_rental",
               "note": "Box 3: Other net rental income — $0"},
    # Box 4: Guaranteed payments — $0 (IRC §707(c)); W&B has none
    "K1_4a": {"source": "partner_IS", "path": "guaranteed_svcs",
               "note": "Box 4a: Guaranteed payments for services — $0"},
    "K1_4b": {"source": "partner_IS", "path": "guaranteed_cap",
               "note": "Box 4b: Guaranteed payments for capital — $0"},
    "K1_4c": {"source": "partner_IS", "path": "guaranteed_tot",
               "note": "Box 4c: Total guaranteed payments — $0"},
    # Box 5: Interest income (IRC §702(a)(1) separately stated)
    "K1_5":  {"source": "partner_IS", "path": "interest_income",
               "note": "Box 5: Interest income × pct"},
    # Boxes 6-10: Investment items — $0 unless property sold
    "K1_6a": {"source": "partner_IS", "path": "ord_dividends",
               "note": "Box 6a: Ordinary dividends — $0"},
    "K1_7":  {"source": "partner_IS", "path": "royalties",
               "note": "Box 7: Royalties — $0"},
    "K1_8":  {"source": "partner_IS", "path": "st_cap_gain",
               "note": "Box 8: Net ST capital gain — $0 unless property sold"},
    "K1_9a": {"source": "partner_IS", "path": "lt_cap_gain",
               "note": "Box 9a: Net LT capital gain — $0 unless property sold"},
    "K1_10": {"source": "partner_IS", "path": "sec1231_gain",
               "note": "Box 10: §1231 gain — $0 unless property sold"},
    # Box 12: §179 — passive limitation (IRC §469(j)(1)) applies
    "K1_12": {"source": "partner_IS", "path": "sec179",
               "note": "Box 12: §179 deduction × pct (if any; IRC §469(j)(1) limits)"},
    # Box 14a: SE earnings — MUST be $0 (IRC §1402(a)(1)/(13))
    "K1_14a": {"source": "partner_IS", "path": "se_earnings",
                "note": "Box 14a: SE earnings — MUST be $0 (IRC §1402(a)(1))"},
    # Box 19a: Distributions
    "K1_19a": {"source": "partner_IS", "path": "distributions",
                "note": "Box 19a: Cash distributions = max(0,NI) × pct"},
}

# Fields requiring CPA / manual review (auto-mapped as CPA:unknown when not set)
_CPA_NOTES_K1: Dict[str, str] = {
    # K1_K_NonrecBeg / K1_K_QNRBeg / K1_K_RecBeg are now in FILL_MAP (first year = $0)
    # K1_L1 is now in FILL_MAP (first year = $0)
    "K1_9b":  "Box 9b: Collectibles gain — CPA review",
    "K1_9c":  "Box 9c: Unrecaptured §1250 gain — CPA review if property sold",
    "K1_17a": "Box 17a: AMT post-1986 depreciation adjustment — CPA review",
    "K1_20":  "Box 20: QBI deduction §199A — rental real estate safe harbor (Rev. Proc. 2019-38); CPA review",
}


# ════════════════════════════════════════════════════════════════════════════
#  Sch_K1  — Form1065 subclass
# ════════════════════════════════════════════════════════════════════════════

class Sch_K1(Form1065):
    """
    IRS Schedule K-1 (Form 1065) — per-partner allocation service.

    Inherits all financial data resolution from Form1065 via
    ``_resolveTaxData()``.  Distributes totals by each partner's P&L
    percentage to generate one fillDict (and one FILL PDF) per partner.

    ``self.oID = "Sch_K1"``  (drives all file names)
    IRS template : {irsDir}/Sch_K1_IRS.pdf
    """

    # ── Location-derivation rules ─────────────────────────────────────────
    LOCATION_RULES = [
        (r'^K1_EIN|K1_TaxYr|K1_Pship',  "Sch_K1.Header.Partnership"),
        (r'^K1_Pt',                       "Sch_K1.Header.Partner"),
        (r'^K1_J_',                       "Sch_K1.Header.Percentages"),
        (r'^K1_L',                        "Sch_K1.CapitalAcct"),
        (r'^K1_1[4-9]|K1_2[0-2]',        "Sch_K1.OtherBoxes"),
        (r'^K1_',                         "Sch_K1.Boxes"),
    ]

    _FILL_MAP  = _FILL_MAP_K1      # override parent's Form1065 map
    _CPA_NOTES = _CPA_NOTES_K1     # override parent's CPA notes

    def aid(self) -> "BookToIRS":
        """Factory for the BookToIRS bridge service for per-partner K-1 PDFs."""
        from irs.BookToIRS import BookToIRS
        return BookToIRS(self.llc, "Sch_K1")

    # ── IRS template filename override ────────────────────────────────────
    def FN(self) -> str:
        for name in ("Sch_K1_IRS.pdf", "Schedule_K_1-IRS.pdf",
                     "Sch-K1-IRS.pdf", "SchK1_IRS.pdf"):
            p = self.irsDir / name
            if p.exists():
                return str(p)
        return str(self.irsDir / "Sch_K1_IRS.pdf")

    def _loadKeyMap(self) -> Dict[str, str]:
        for name in ("Sch_K1-keys.pdf", "Schedule_K_1-keys.pdf"):
            p = self.irsDir / name
            if p.exists():
                try:
                    from pypdf import PdfReader
                    rdr = PdfReader(str(p))
                    raw = rdr.get_fields() or {}
                    km: Dict[str, str] = {}
                    for fid, fobj in raw.items():
                        v = fobj.get("/V")
                        if v and str(v).strip() not in ("", "/Off"):
                            short = fid.split(".")[-1].split("[")[0]
                            km[short] = str(v).strip()
                    return km
                except Exception as exc:
                    if self.verbose:
                        print(f"  ⚠️  Keys PDF read error ({name}): {exc}")
        if self.verbose:
            print(f"  ⚠️  Keys PDF not found for {self.oID}")
        return {}

    def _loadLabelMap(self) -> Dict[str, str]:
        for name in ("Sch_K1-FieldNames.json", "Schedule_K_1-FieldNames.json"):
            p = self.irsDir / name
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return {str(k): str(v) for k, v in data.items()}
                except Exception:
                    pass
        return {}

    # ════════════════════════════════════════════════════════════════════════
    #  COMBINED STEP: BUILD K-1 FILL DICT (per-partner)
    # ════════════════════════════════════════════════════════════════════════

    def _buildFillDict(                                 # type: ignore[override]
        self,
        nSpaceDict: Dict,
        partner_idx: int = 0,
        is_data:    Optional[Dict] = None,
        bs_data:    Optional[Dict] = None,
        **kwargs,
    ) -> Dict:
        """
        Build the per-partner K-1 fillDict.

        Parameters
        ----------
        nSpaceDict  : dict — output of ``_buildNSpace()``
        partner_idx : int  — 0-based index into ``owners.detail`` list
        is_data     : dict — override IS totals (testing only)
        bs_data     : dict — override BS totals (testing only)

        Returns
        -------
        dict   Complete fillDict — ALL fields, publish flags, per-partner values.
        """
        # ── Step A: base dict (all fields, publish=False) ──────────────────
        # Prefer the saved namespace file (which has our logicalKey assignments)
        # over the PDF-derived nSpaceDict (which has no logicalKeys).
        from irs.irsForm import irsForm
        saved_ns_path = self._nspaceFN()
        if saved_ns_path.exists():
            try:
                with open(saved_ns_path, "r", encoding="utf-8") as _fh:
                    _saved = json.load(_fh)
                # Merge logicalKey/label from saved file into nSpaceDict fields
                _saved_fields = _saved.get("fields", {})
                _ns_fields = nSpaceDict.get("fields", {})
                for _fid, _sfd in _saved_fields.items():
                    if _fid in _ns_fields:
                        _ns_fields[_fid]["logicalKey"] = _sfd.get("logicalKey", "")
                        _ns_fields[_fid]["label"]      = _sfd.get("label", "")
            except Exception:
                pass  # fall through to original nSpaceDict
        fillDict = irsForm._buildFillDict(self, nSpaceDict)

        # ── Step B: reverse index logicalKey → fID ─────────────────────────
        lk_to_fid: Dict[str, str] = {
            fd["logicalKey"]: fid
            for fid, fd in fillDict.items()
            if fd["logicalKey"]
        }

        # ── Step C: load official IS/BS/owners from stmtFinancialReport ─────
        if is_data is None or bs_data is None:
            td = self._resolveTaxData()
            if is_data is None:
                is_data = td.get("is_data", {})
            if bs_data is None:
                bs_data = td.get("bs_data", {})
            owners_agg = td.get("owners", {})
        else:
            owners_agg = {}

        owners_detail: List[Dict] = owners_agg.get("detail", [])
        if partner_idx >= len(owners_detail) and owners_detail:
            raise IndexError(
                f"partner_idx={partner_idx} out of range "
                f"(only {len(owners_detail)} partners in owners.detail)")

        partner_raw = owners_detail[partner_idx] if owners_detail else {}

        # ── Step D: compute per-partner values ─────────────────────────────
        pct       = float(partner_raw.get("pct", 0.0))
        nm_list   = partner_raw.get("nm", [""])
        name      = nm_list[0] if nm_list else ""
        address   = partner_raw.get("addr", "")
        mem_type  = partner_raw.get("memType", "Individual")
        status    = str(partner_raw.get("status", "") or "")
        pct_str   = f"{pct * 100:.1f}%"

        ni          = float(is_data.get("net_income", 0))
        net_rental  = float(is_data.get("net_rental", 0))
        interest    = float(is_data.get("interest_income", 0))

        partner_ni          = round(ni * pct, 2)
        partner_rent        = round(net_rental * pct, 2)
        partner_interest    = round(interest * pct, 2)

        # Per-partner contributions (f40 / Box L L2) — GL-sourced, Books-First.
        # Source: Credits to Acct.Equity.Owner.Capital.Funds in llcAssets,
        # weighted by propOwners per partner (IRC §722; COA Standard Mapping).
        oID = partner_raw.get("oID", partner_raw.get("ownerID", ""))
        partner_contrib, _ = gl_contributions(self.llc, oID)  # attributed float only

        # Per-partner distributions (f43 / Box L L5) — GL-sourced.
        # Source: Credits to Acct.Equity.Owner.Capital.Dist, weighted by propOwners.
        # NOT equal to allocated income — these are actual cash payments.
        partner_distrib = gl_distributions(self.llc, oID)

        # Tax basis ending capital (f44 / Box L L6) = L2 + L3 − L5 (IRC §705).
        partner_cap_end = gl_ending_capital(
            self.llc, oID, pct, net_rental=net_rental)

        # Partner type flags (Line G, H1, H2) — IRC §761(b)
        is_manager = "manager" in status.lower()
        # CHECK_SENTINEL: a truthy string that triggers checkBox publish
        _CHECK = "1"
        partner_src: Dict = {
            "name":          name,
            "address":       address,
            "ein":           partner_raw.get("SSN", partner_raw.get("ssn",
                             partner_raw.get("ein", ""))),
            "mem_type":      mem_type,
            "status":        status,
            "pct_str":       pct_str,
            # Box J: if no ownership change during the year, beginning = ending.
            # IRS K-1 instructions: "If there was no change in the partners'
            # shares of profit, loss, and capital during the tax year, enter
            # the end-of-year percentages in both the beginning and ending columns."
            "pct_str_beg":   pct_str,
            "is_gp_manager": _CHECK if is_manager else "",
            "is_lp_member":  "" if is_manager else _CHECK,
            "is_domestic":   _CHECK,         # SSN present → US person (domestic)
            "is_foreign":    "",
            "is_de":         "",             # individual humans are never DREs
            "is_ret_plan":   "",
            "sec704c_beg":   "",             # $0 for cash-only contributions
            "sec704c_end":   "",
        }
        partner_is_src: Dict = {
            "ordinary_income":  "",          # Box 1 — MUST be $0 (IRC §469(c)(2))
            "net_rental":       self._fmt(partner_rent),
            "interest_income":  self._fmt(partner_interest) if partner_interest else "",
            "distributions":    self._fmt(partner_distrib),
            "se_earnings":      "",          # Box 14a — MUST be $0 (IRC §1402(a)(1))
            "net_income":       self._fmt(partner_ni),
            # Part III all-zero boxes for pure rental LLC
            "other_rental":    "",
            "guaranteed_svcs": "",
            "guaranteed_cap":  "",
            "guaranteed_tot":  "",
            "ord_dividends":   "",
            "royalties":       "",
            "st_cap_gain":     "",
            "lt_cap_gain":     "",
            "sec1231_gain":    "",
            "sec179":          (self._fmt(round(
                                float(is_data.get("depreciation_sec179", 0)) * pct, 2))
                                if is_data.get("depreciation_sec179") else ""),
        }
        partner_cap_src: Dict = {
            # Box L — tax basis capital account (IRC §705; Rev. Proc. 2020-13)
            # IRC §705: basis begins at contribution, increased by income, decreased by distrib.
            # First-year LLC: beginning capital is always $0 — entity had no prior history.
            "beg_capital":   "0",
            # Contributions: per-partner actual cash contributed at formation.
            # If $0, the section agent (SK1B-R07) warns that contributions may be missing.
            "contributions": self._fmt(partner_contrib) or "",
            # L3: current-year net income allocated = IS.net_rental × pct (IRC §702(a))
            "net_income":    self._fmt(partner_rent),
            # L4: withdrawals/distributions to partner during year
            "distributions": self._fmt(partner_distrib) or "",
            # L5: ending capital = L1 + L2 + L3 − L4
            "end_capital":   self._fmt(partner_cap_end) if partner_cap_end else "",
        }

        # ── Box K1: partner's share of liabilities (IRC §752) ──────────────
        # W&B: typical commercial RE mortgage = qualified nonrecourse (§465(b)(6))
        mortgage_total = 0.0
        try:
            from ledger.stmtBS import stmtBS_Tax
            mortgage_total = float(stmtBS_Tax(self.llc).taxAggregates().get("mortgage", 0))
        except Exception:
            pass
        # Fall back to bs_data if available
        if not mortgage_total and bs_data:
            mortgage_total = float(bs_data.get("mortgage", 0))
        partner_mortgage = round(mortgage_total * pct, 2)
        partner_bs_src: Dict = {
            # Beginning-of-year liabilities (f31/f33/f35):
            # First-year LLC: property was purchased DURING the year, so no debt existed
            # at January 1. All liabilities began at acquisition date mid-year → BOY = $0.
            "nonrecourse_beg": "0",
            "qnr_beg":         "0",
            "recourse_beg":    "0",
            # End-of-year liabilities (f32/f34/f36):
            # W&B mortgage classified as QNR (§465(b)(6)): commercial lender, real-property
            # collateral only, no personal guarantees. Shared by profit % (Treas. Reg. §1.752-3(a)(3)).
            "nonrecourse": "",
            "qnr":         self._fmt(partner_mortgage) if partner_mortgage else "",
            "recourse":    "",
        }

        # ── Step E: load profile; augment with derived date fields ──────────
        entity, f1065_data = self._loadProfile()
        _bm, _bd = _parse_month_day(f1065_data.get("date_from", ""))
        _em, _ed = _parse_month_day(f1065_data.get("date_to", ""))
        _ty = str(f1065_data.get("tax_year") or self.tax_year or "")[- 2:] or "25"
        f1065_data["date_from_month"]     = _bm
        f1065_data["date_from_day"]       = _bd
        f1065_data["date_to_month"]       = _em
        f1065_data["date_to_day"]         = _ed
        f1065_data["tax_year_2d"]         = _ty
        f1065_data.setdefault("is_final_k1",       False)
        f1065_data.setdefault("is_amended_k1",     False)
        f1065_data.setdefault("is_ptp",            False)
        f1065_data.setdefault("irs_center",        "")
        f1065_data.setdefault("cap_tax_basis_flag", True)  # mandatory Rev. Proc. 2020-13

        src_map: Dict = {
            "entity":      entity,
            "F1065":       f1065_data,
            "partner":     partner_src,
            "partner_IS":  partner_is_src,
            "partner_cap": partner_cap_src,
            "partner_BS":  partner_bs_src,
        }

        # ── Step F: apply K-1 FILL_MAP  (publish=True + value) ────────────
        for lk, spec in self._FILL_MAP.items():
            fid = lk_to_fid.get(lk)
            if not fid or fid not in fillDict:
                continue
            fd    = fillDict[fid]
            ftype = fd["fType"]

            if ftype in ("checkBox", "checkText", "box"):
                # Only check when source resolves to a truthy value (fix: was always checked)
                resolved = self._resolve(spec["source"], spec["path"], src_map)
                if not resolved:
                    continue  # leave as unpublished (unchecked)
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

        # ── Step G: apply _CPA_NOTES  (publish="CPA:unknown") ─────────────
        for lk, note in self._CPA_NOTES.items():
            fid = lk_to_fid.get(lk)
            if not fid or fid not in fillDict:
                continue
            if fillDict[fid].get("publish") is True:
                continue
            fillDict[fid].update({
                "publish": "CPA:unknown",
                "source":  None,
                "path":    None,
                "note":    note,
                "value":   "",
            })

        # ── Diagnostics ─────────────────────────────────────────────────────
        if self.verbose:
            pub = sum(1 for v in fillDict.values() if v.get("publish") is True)
            cpa = sum(1 for v in fillDict.values() if v.get("publish") == "CPA:unknown")
            print(f"  ✅ K-1 fillDict [{name}]  → {len(fillDict)} fields  "
                  f"(publish={pub}, cpa={cpa})")

        return fillDict

    # ── Save all K-1 PDFs in one call ─────────────────────────────────────

    def saveFILL_allPartners(self, nSpaceDict: Dict) -> List[str]:
        """
        Generate one FILL PDF per partner.

        Returns list of output paths.
        """
        td      = self._resolveTaxData()
        owners  = td.get("owners", {}).get("detail", [])
        paths   = []

        if not owners:
            if self.verbose:
                print("  ⚠️  No partners found in owners.detail — nothing generated.")
            return paths

        for i, owner in enumerate(owners):
            oID    = owner.get("oID", f"p{i}")
            fillDict = self._buildFillDict(nSpaceDict, partner_idx=i)
            path     = self.saveFILL(fillDict, suffix=f"_{oID}")
            paths.append(path)

        if self.verbose:
            print(f"  ✅ K-1 PDFs generated: {len(paths)} partner(s)")
        return paths
