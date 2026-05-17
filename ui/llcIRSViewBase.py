"""
llcIRSViewBase.py
=================
Shared data-loading base for all LLC Editor IRS "tax aid" view classes.

All IRS view files (llcForm1065, llcFormK1, llcFormSchedL, etc.) inherit
from this mixin instead of calling llcReportEngine directly.

Data is sourced from the official stmtFinancialReport databases (IS/BS/owners)
via Form1065._resolveTaxData(), guaranteeing that the editor views show the
EXACT same values that appear in the filed PDF (Form1065_FILL.pdf).

If a saved Form1065_fillDict.json exists in irsDir it is loaded and used
as the primary source (fastest).  Otherwise the data is built fresh from
stmtFinancialReport on the fly.

Usage
-----
    class llcForm1065(_llcIRSViewBase):
        def __init__(self, eSession):
            super().__init__(eSession)
            # self._is, self._bs, self._owners_agg, self._owners_list
            # self._entity, self._f1065 are all available

Timestamp of last change: 2026.04.18
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class _llcIRSViewBase:
    """
    Mixin / base for IRS editor view classes.

    Attributes
    ----------
    _is   : dict   — is_data  from stmtFinancialReport.taxData()
    _bs   : dict   — bs_data  from stmtFinancialReport.taxData()
    _owners_agg  : dict   — owners aggregate (count, contributions, distributions)
    _owners_list : list   — raw owners list from llcOwners JSON
    _entity      : dict   — entity info from llcProfile
    _f1065       : dict   — F1065 profile from llcProfile
    """

    def __init__(self, eSession):
        self.eSession = eSession
        llc = getattr(eSession, "llc", None)

        self._is:          Dict = {}
        self._bs:          Dict = {}
        self._owners_agg:  Dict = {}
        self._owners_list: List = []
        self._entity:      Dict = {}
        self._f1065:       Dict = {}

        if llc is not None:
            self._loadFromIRS(llc)

    # ── primary loader ────────────────────────────────────────────────────

    def _loadFromIRS(self, llc) -> None:
        """
        Load IS/BS/owners from Form1065's official pipeline.

        Priority:
          1. Saved Form1065_fillDict.json  (values already resolved)
          2. stmtFinancialReport(llc).taxData()  (build fresh)
        """
        try:
            from irs.Form1065 import Form1065
        except ImportError:
            try:
                import sys, os
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'irs'))
                from Form1065 import Form1065
            except ImportError:
                self._loadFallback(llc)
                return

        f = Form1065(llc=llc)

        # Try saved fillDict first (fastest — no FR computation)
        try:
            fd_path = f._fillDictFN()
            if fd_path.exists():
                self._loadFromSavedFillDict(f, fd_path)
                return
        except Exception:
            pass

        # Build fresh from stmtFinancialReport
        try:
            td = f._resolveTaxData()
            self._is          = td.get("is_data", {})
            self._bs          = td.get("bs_data", {})
            self._owners_agg  = td.get("owners",   {})
            self._owners_list = f._loadOwners()
            self._entity, self._f1065 = f._loadProfile()
        except Exception as exc:
            self._loadFallback(llc)

    def _loadFromSavedFillDict(self, form_obj, fd_path: Path) -> None:
        """
        Extract IS/BS/owners by reading the saved Form1065_fillDict.json.
        Reconstructs numeric values from the fillDict field values.
        """
        with open(fd_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        fields = raw.get("fields", raw)

        # Build a {logicalKey: numeric_value} lookup
        lk_num: Dict[str, float] = {}
        for fd in fields.values():
            lk = fd.get("logicalKey", "")
            val = fd.get("value", "")
            if lk and val:
                try:
                    lk_num[lk] = float(str(val).replace(",", "").strip())
                except (ValueError, TypeError):
                    pass

        # Map fillDict logicalKeys → is_data / bs_data keys
        _IS_MAP = {
            "P1_1a":  "rent_income",
            "P1_8":   "total_income",
            "P1_9":   "salaries",
            "P1_11":  "repairs",
            "P1_14":  "taxes_licenses",
            "P1_15":  "interest_expense",
            "P1_16a": "depreciation",
            "P1_21":  "other_deductions",
            "P1_22":  "total_expenses",
            "P1_23":  "net_income",
            "K_5":    "interest_income",
            "K_19a":  "distributions_cash",
            "K_2":    "rent_income",      # fallback if P1_1a missing
            "M2_6a":  "distributions_cash",
        }
        _BS_MAP = {
            "L_1_2":   "cash",
            "L_2a_2":  "ar",
            "L_9a_2":  "buildings",
            "L_9b_2":  "accum_depr",
            "L_11_2":  "land",
            "L_13_2":  "other_assets",
            "L_14_2":  "total_assets",
            "P1_F":    "total_assets",   # fallback
            "L_15_2":  "payables",
            "L_19a_2": "mortgage",
            "L_20_2":  "other_liab",
            "L_21_2":  "total_equity",
            "L_22_2":  "total_liab_capital",
        }

        is_data: Dict = {}
        for lk, key in _IS_MAP.items():
            if lk in lk_num and key not in is_data:
                is_data[key] = lk_num[lk]

        bs_data: Dict = {}
        for lk, key in _BS_MAP.items():
            if lk in lk_num and key not in bs_data:
                bs_data[key] = lk_num[lk]

        # owners from fillDict meta or from profile
        owners_count_str = ""
        for fd in fields.values():
            if fd.get("logicalKey") in ("P1_I", "B_25Fm"):
                owners_count_str = fd.get("value", "")
                break

        try:
            n = int(str(owners_count_str).strip())
        except (ValueError, TypeError):
            n = 0

        # Get owners list and aggregate from profile
        entity, f1065_data = form_obj._loadProfile()
        owners_list = form_obj._loadOwners()
        contribs = sum(float(o.get("capital_contributed", 0)) for o in owners_list)

        self._is          = is_data
        self._bs          = bs_data
        self._owners_agg  = {
            "count":              str(n or len(owners_list)),
            "cash_contributions": contribs,
            "distributions_cash": is_data.get("distributions_cash", 0.0),
        }
        self._owners_list = owners_list
        self._entity      = entity
        self._f1065       = f1065_data

    def _loadFallback(self, llc) -> None:
        """Last-resort: try loading directly from stmtFinancialReport without Form1065."""
        try:
            try:
                from ledger.stmtFinancialReport import stmtFinancialReport
            except ImportError:
                from stmtFinancialReport import stmtFinancialReport
            fr = stmtFinancialReport(llc)
            td = json.loads(fr.taxData())
            self._is         = td.get("is_data", {})
            self._bs         = td.get("bs_data", {})
            self._owners_agg = td.get("owners",   {})
        except Exception:
            pass

        try:
            try:
                from irs.irsForm import irsForm as _base
            except ImportError:
                return

            class _dummy(_base):
                pass
            dummy = _dummy.__new__(_dummy)
            dummy.llc      = llc
            dummy.verbose  = False
            dummy.oID      = "Form1065"
            from pathlib import Path
            from ledger import setup_paths as _sp
            dummy.irsDir      = Path(_sp.IRS_FORMS_DIR) if _sp.IRS_FORMS_DIR else Path(llc.acctDir(dirName="ye")) / "Forms_IRS"
            dummy._root_dir   = dummy.irsDir.parents[2]
            dummy._accts_dir  = dummy.irsDir.parents[0] / "Accts"
            self._owners_list = dummy._loadOwners()
            self._entity, self._f1065 = dummy._loadProfile()
        except Exception:
            pass

    # ── bind_session support ──────────────────────────────────────────────

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        llc = getattr(eSession, "llc", None)
        self._is = {}; self._bs = {}
        self._owners_agg = {}; self._owners_list = []
        self._entity = {}; self._f1065 = {}
        if llc is not None:
            self._loadFromIRS(llc)

    # ── value helpers ─────────────────────────────────────────────────────

    def _isv(self, key: str, default: float = 0.0) -> float:
        """Numeric value from is_data."""
        v = self._is.get(key, default)
        try:
            return round(float(v or 0), 2)
        except (TypeError, ValueError):
            return default

    def _bsv(self, key: str, default: float = 0.0) -> float:
        """Numeric value from bs_data."""
        v = self._bs.get(key, default)
        try:
            return round(float(v or 0), 2)
        except (TypeError, ValueError):
            return default

    def _ev(self, key: str, default: str = "") -> str:
        """String value from entity profile."""
        return str(self._entity.get(key, default) or default)

    def _fv_prof(self, key: str, default: str = "") -> str:
        """String value from F1065 profile."""
        return str(self._f1065.get(key, default) or default)

    def _owner_count(self) -> int:
        """Number of partners."""
        return len(self._owners_list)

    def _owners_detail(self) -> List[Dict]:
        """Per-partner detail from owners.detail (may be empty if using loaded IS/BS)."""
        return self._owners_agg.get("detail", []) or self._owners_list

    def _per_partner_alloc(self) -> List[Dict]:
        """
        Return per-partner allocation list:
        [{name, pct, type, ni_share, rent_share, distrib_share}]
        """
        ni    = self._isv("net_income")
        rent  = self._isv("rent_income")
        alloc = []
        for o in self._owners_list:
            nm_list = o.get("nm") or o.get("name") or [""]
            name    = nm_list[0] if isinstance(nm_list, list) else str(nm_list)
            pct     = float(o.get("pct", 0))
            alloc.append({
                "oID":         o.get("oID", ""),
                "name":        name,
                "pct":         pct,
                "type":        o.get("memType", "Individual"),
                "status":      o.get("status", ""),
                "ni_share":    round(ni   * pct, 2),
                "rent_share":  round(rent * pct, 2),
                "distrib":     round(max(0.0, ni) * pct, 2),
            })
        return alloc

    def _individual_majority_owner(self) -> bool:
        """True if any individual/estate owner holds >50% interest."""
        for o in self._owners_list:
            mtype = str(o.get("memType", "individual")).lower()
            pct   = float(o.get("pct", 0))
            if pct > 0.50 and mtype in ("individual", "estate", "person", "active", ""):
                return True
        return False

    def _entity_majority_owner(self) -> bool:
        """True if any corp/partnership/trust holds >50%."""
        entity_types = ("corp", "corporation", "partnership", "trust",
                        "llc_entity", "exempt", "org", "foreign")
        for o in self._owners_list:
            mtype = str(o.get("memType", "")).lower()
            pct   = float(o.get("pct", 0))
            if pct > 0.50 and any(t in mtype for t in entity_types):
                return True
        return False

    # ── common interface stubs ────────────────────────────────────────────

    def object_name(self) -> str:
        return self.__class__.__name__

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()
