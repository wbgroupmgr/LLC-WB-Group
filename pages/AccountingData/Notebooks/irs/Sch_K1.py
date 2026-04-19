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


# ════════════════════════════════════════════════════════════════════════════
#  K-1 FIELD MAP  (logicalKey → fill spec)
# ════════════════════════════════════════════════════════════════════════════

_FILL_MAP_K1: Dict[str, Dict] = {

    # ── Partnership identification (same for every K-1) ──────────────────
    "K1_EIN":     {"source": "entity",  "path": "ein",
                   "note": "Partnership EIN"},
    "K1_TaxYr":   {"source": "F1065",   "path": "tax_year",
                   "note": "2-digit tax year, e.g. '25'"},
    "K1_PtEIN":   {"source": "partner", "path": "ein",
                   "note": "Partner's SSN or EIN"},
    "K1_PshipNm": {"source": "entity",  "path": "entity_name",
                   "note": "Partnership name"},
    "K1_PshipAddr": {"source": "entity", "path": "address",
                     "note": "Partnership address"},

    # ── Partner identification ────────────────────────────────────────────
    "K1_PtName":  {"source": "partner", "path": "name",
                   "note": "Partner's name"},
    "K1_PtAddr":  {"source": "partner", "path": "address",
                   "note": "Partner's address"},
    "K1_PtType":  {"source": "partner", "path": "mem_type",
                   "note": "General / limited / LLC member"},
    "K1_PtStatus": {"source": "partner", "path": "status",
                    "note": "Active / passive status"},

    # ── Partner percentages (Box J) ───────────────────────────────────────
    "K1_J_Profit":  {"source": "partner", "path": "pct_str",
                     "note": "Profit % (end of year)"},
    "K1_J_Loss":    {"source": "partner", "path": "pct_str",
                     "note": "Loss % (end of year)"},
    "K1_J_Capital": {"source": "partner", "path": "pct_str",
                     "note": "Capital % (end of year)"},

    # ── Box 1 — Ordinary business income (loss) ──────────────────────────
    "K1_1":  {"source": "partner_IS", "path": "ordinary_income",
               "note": "Box 1: Ordinary income × partner P&L %"},

    # ── Box 2 — Net rental real estate income (loss) ─────────────────────
    "K1_2":  {"source": "partner_IS", "path": "rent_income",
               "note": "Box 2: Rental income × partner P&L %"},

    # ── Box 5 — Interest income ───────────────────────────────────────────
    "K1_5":  {"source": "partner_IS", "path": "interest_income",
               "note": "Box 5: Interest income × partner P&L %"},

    # ── Box 14 — Self-employment earnings ────────────────────────────────
    "K1_14a": {"source": "partner_IS", "path": "se_earnings",
                "note": "Box 14a: SE earnings (ordinary income if positive)"},

    # ── Box 19 — Distributions ───────────────────────────────────────────
    "K1_19a": {"source": "partner_IS", "path": "distributions",
                "note": "Box 19a: Cash distributions = max(0,NI) × partner %"},

    # ── Box L — Capital account analysis ─────────────────────────────────
    "K1_L1":  {"source": "partner_cap", "path": "beg_capital",
                "note": "Capital account beginning of year (prior-year ending)"},
    "K1_L2":  {"source": "partner_cap", "path": "contributions",
                "note": "Capital contributed during year (cash)"},
    "K1_L3":  {"source": "partner_cap", "path": "net_income",
                "note": "Current year net income (loss) × partner %"},
    "K1_L4":  {"source": "partner_cap", "path": "distributions",
                "note": "Withdrawals and distributions"},
    "K1_L5":  {"source": "partner_cap", "path": "end_capital",
                "note": "Capital account end of year"},
}

# Fields requiring CPA / manual review
_CPA_NOTES_K1: Dict[str, str] = {
    "K1_3":   "Box 3: Other net rental income — CPA review",
    "K1_4":   "Box 4: Guaranteed payments — CPA review",
    "K1_6a":  "Box 6a: Ordinary dividends — CPA review",
    "K1_7":   "Box 7: Royalties — CPA review",
    "K1_8":   "Box 8: Net short-term capital gain — CPA review",
    "K1_9a":  "Box 9a: Net long-term capital gain — CPA review",
    "K1_10":  "Box 10: Net §1231 gain — CPA review",
    "K1_12":  "Box 12: §179 deduction — CPA review",
    "K1_13a": "Box 13a: Charitable contributions — CPA review",
    "K1_17a": "Box 17a: AMT — post-1986 depreciation — CPA review",
    "K1_20":  "Box 20: Other info (QBI §199A, etc.) — CPA review",
    "K1_L1":  "Capital beginning of year — requires prior-year data",
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
        # Call irsForm._buildFillDict directly (skip Form1065's FILL_MAP)
        from irs.irsForm import irsForm
        fillDict = irsForm._buildFillDict(self, nSpaceDict)

        # ── Step B: reverse index logicalKey → fID ─────────────────────────
        lk_to_fid: Dict[str, str] = {
            fd["logicalKey"]: fid
            for fid, fd in fillDict.items()
            if fd["logicalKey"]
        }

        # ── Step C: load official IS/BS/owners from llcFinancialReport ─────
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
        status    = partner_raw.get("status", "")
        pct_str   = f"{pct * 100:.1f}%"

        ni          = float(is_data.get("net_income", 0))
        rent        = float(is_data.get("rent_income", 0))
        interest    = float(is_data.get("interest_income", 0))
        contribs    = float(owners_agg.get("cash_contributions", 0))

        partner_ni          = round(ni * pct, 2)
        partner_rent        = round(rent * pct, 2)
        partner_interest    = round(interest * pct, 2)
        partner_distrib     = round(max(0.0, ni) * pct, 2)
        partner_contrib     = round(contribs * pct, 2)
        partner_se          = partner_ni if partner_ni > 0 else 0.0
        # Capital end year = contributions + NI - distributions (simplified)
        partner_cap_end     = round(partner_contrib + partner_ni - partner_distrib, 2)

        partner_src: Dict = {
            "name":     name,
            "address":  address,
            "ein":      partner_raw.get("ein", ""),
            "mem_type": mem_type,
            "status":   status,
            "pct_str":  pct_str,
        }
        partner_is_src: Dict = {
            "ordinary_income":  self._fmt(partner_ni),
            "rent_income":      self._fmt(partner_rent),
            "interest_income":  self._fmt(partner_interest) if partner_interest else "",
            "distributions":    self._fmt(partner_distrib),
            "se_earnings":      self._fmt(partner_se) if partner_se > 0 else "",
            "net_income":       self._fmt(partner_ni),
        }
        partner_cap_src: Dict = {
            "beg_capital":   "",                             # prior-year data needed
            "contributions": self._fmt(partner_contrib),
            "net_income":    self._fmt(partner_ni),
            "distributions": self._fmt(partner_distrib),
            "end_capital":   self._fmt(partner_cap_end),
        }

        # ── Step E: load profile ────────────────────────────────────────────
        entity, f1065_data = self._loadProfile()

        src_map: Dict = {
            "entity":     entity,
            "F1065":      f1065_data,
            "partner":    partner_src,
            "partner_IS": partner_is_src,
            "partner_cap": partner_cap_src,
        }

        # ── Step F: apply K-1 FILL_MAP  (publish=True + value) ────────────
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
