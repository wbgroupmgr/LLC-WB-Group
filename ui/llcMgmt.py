'''
llcMgmt — Flask app wiring all LLC editor views.

Views:
  Transactions:
    llcAssets       — Asset records (editable, table_view.html)
    llcExpRev       — Expense/Revenue records (editable, table_view.html)
    stmtGeneralLedger— Merged GL computed view (read-only, table_view.html)
    llcBank         — Bank CSV reconciliation (read-only, bank_view.html)

  Financial Statements:
    stmtBalanceSheet — Balance Sheet (read-only, financial_view.html)
    stmtIncomeStmt   — Income Statement (read-only, financial_view.html)
    stmtOwnerEquity  — Owner / Member Equity (read-only, financial_view.html)

  IRS Tax Aids (v0.2.4.7 — PDF-embed restructure):
    llcForm1065     — Form 1065_FILL.pdf  (irs_pdf_view.html)
    llcFormK1       — Sch_K1_FILL.pdf      (irs_pdf_view.html)

  The previous per-page constructed views (SchB Pg2/3/4, SchK Pg5, Pg6 and
  the standalone Sched L / M-1 / M-2 detail tables) were retired in v0.2.4.7
  in favour of embedding the canonical FILL.pdf produced by the IRS pipeline.
  The full per-field round-trip is now covered by tests/testIrsFillPDF.py.

Timestamp of last change: 2026.04.24  (v0.2.4.7 — PDF-embed tax views)
'''

import json
import logging
import math
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ledger import setup_paths as _sp

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for

from ui.llcAssets          import llcAssets
from ui.llcExpRev          import llcExpRev
from ui.llcPayables        import llcPayables
from ui.llcReceivables     import llcReceivables
from ui.llcOwners          import llcOwners
from ui.llcCustomers       import llcCustomers
from ui.llcMilestones      import llcMilestones
from ui.stmtGL_View  import stmtGL_View  as stmtGeneralLedger
from ui.stmtBS_View  import stmtBS_View  as stmtBalanceSheet
from ui.stmtIS_View  import stmtIS_View  as stmtIncomeStmt
from ui.stmtOwnerEquity      import stmtOwnerEquity
from ui.llcBankView         import llcBankView
from ui.stmtPropertyEquity   import stmtPropertyEquity
from ui.llcForm1065         import llcForm1065
from ui.llcFormK1           import llcFormK1
from ui.llcForm8825         import llcForm8825
from ui.llcForm4562         import llcForm4562
from ui.llcLogin_auth       import make_auth_routes
from ui.llcPropAgent        import bind_propAgent_routes
from ui.llcExpAgent         import bind_expAgent_routes


class llcMgmt:

    # ── View catalogue ────────────────────────────────────────────────────────
    VIEW_ORDER = [
        # Transactions
        "llcAssets",
        "llcExpRev",
        "llcPayables",
        "llcReceivables",
        "llcBank",
        # Financial Statements  (General Ledger first — per DataModelGuide)
        "stmtGeneralLedger",
        "stmtBalanceSheet",
        "stmtIncomeStmt",
        "stmtOwnerEquity",
        "stmtPropertyEquity",
        # IRS Tax Aids — v0.2.4.7 PDF-embed restructure (F1065 + K-1 + 8825)
        "llcForm1065",
        "llcFormK1",
        "llcForm8825",
        "llcForm4562",
    ]

    VIEW_LABELS = {
        "llcAssets":          "Assets",
        "llcExpRev":          "Exp / Revenue",
        "llcPayables":        "Payables (A/P)",
        "llcReceivables":     "Receivables (A/R)",
        "stmtGeneralLedger":   "General Ledger",
        "llcBank":            "Bank Reconciliation",
        "stmtBalanceSheet":    "Balance Sheet",
        "stmtIncomeStmt":      "Income Statement",
        "stmtOwnerEquity":     "Owner Equity",
        "stmtPropertyEquity":  "Property Equity",
        "llcForm1065":         "Form 1065",
        "llcFormK1":           "Schedule K-1",
        "llcForm8825":         "Form 8825",
        "llcForm4562":         "Form 4562",
        "yeFinancialReport":   "Financial Report\nYE Report",
        # LLC Admin directory views
        "llcOwners":           "Members / Owners",
        "llcCustomers":        "Tenants / Customers",
        "llcMilestones":       "State / Fed Milestones",
        # IRS Submission view
        "taxSubmission":       "IRS Submission",
    }

    VIEW_TITLES = {
        "stmtBalanceSheet":    "Balance Sheet",
        "stmtIncomeStmt":      "Income Statement",
        "stmtOwnerEquity":     "Owner / Member Equity",
        "stmtPropertyEquity":  "Property Equity Report",
        "llcForm1065":        "Form 1065 – U.S. Return of Partnership Income",
        "llcFormK1":          "Schedule K-1 – Partner's Share of Income",
        "llcForm8825":        "Form 8825 – Rental Real Estate Income and Expenses",
        "llcForm4562":        "Form 4562 – Depreciation and Amortization",
        # Admin directory views
        "llcOwners":          "LLC Members / Owners",
        "llcCustomers":       "Tenants / Customers",
        "llcMilestones":      "State & Federal Milestones",
    }

    # Fixed column sets for admin directory views (no COA mapping).
    # These drive the table_view EDITOR — editable fields only.
    ADMIN_COLUMNS = {
        "llcOwners":     ["oID", "nm", "addr", "status", "memType", "pct", "SSN", "kw"],
        "llcCustomers":  ["oID", "nm", "addr", "rent", "start", "kwList"],
        "llcMilestones": ["dueDate", "agency", "form", "Milestone", "status", "notes"],
    }

    # Admin VIEW display columns — may include computed fields not stored in JSON.
    # SSN masked; RetainedEarning injected by /admin route from IS.
    ADMIN_DISPLAY_COLUMNS = {
        "llcOwners":     ["oID", "nm", "status", "pct", "SSN", "RetainedEarning"],
        "llcCustomers":  ["oID", "nm", "addr", "rent", "start"],
        "llcMilestones": ["dueDate", "agency", "form", "Milestone", "status", "notes"],
    }
    # Columns that are computed (not stored) — shown read-only in admin_view
    ADMIN_COMPUTED_COLS = {"RetainedEarning"}

    # View groups for the home page
    VIEW_GROUPS = [
        {
            "label": "Transactions - Journal Entry",
            "icon":  "📂",
            "views": ["llcAssets", "llcExpRev", "llcPayables", "llcReceivables",
                      "llcBank"],
        },
        {
            "label": "Financial Books",
            "icon":  "📊",
            "views": ["stmtGeneralLedger", "stmtBalanceSheet", "stmtIncomeStmt",
                      "stmtOwnerEquity", "stmtPropertyEquity"],
        },
        {
            "label": "IRS Tax Forms",
            "icon":  "🧾",
            "views": ["llcForm1065", "llcFormK1", "llcForm8825", "llcForm4562"],
        },
        {
            "label": "Reports - Analysis",
            "icon":  "📄",
            "views": ["yeFinancialReport"],
        },
    ]

    # Views that use general_ledger_view.html (2-frame GL page, v0.2.3.4)
    GL_VIEWS = {"stmtGeneralLedger"}
    # IRS tax views — render irs_pdf_view.html with the FILL.pdf embedded.
    # Each entry maps view_name → form_id (used by the /forms/<id>.pdf route
    # and the wrapper class FORM_ID).
    PDF_VIEWS = {
        "llcForm1065": "Form1065",
        "llcFormK1":   "Sch_K1",
        "llcForm8825": "Form8825",
        "llcForm4562": "Form4562",
    }
    # Views that use financial_view.html
    FINANCIAL_VIEWS = {"stmtBalanceSheet", "stmtIncomeStmt", "stmtOwnerEquity"}
    # Views that use property_equity.html
    PROPERTY_VIEWS = {"stmtPropertyEquity"}
    # Views that use bank_view.html
    BANK_VIEWS = {"llcBank"}
    # All computed (read-only) views
    READ_ONLY_VIEWS = {
        "stmtGeneralLedger", "stmtBalanceSheet", "stmtIncomeStmt", "stmtOwnerEquity",
        "llcBank", "stmtPropertyEquity",
        "llcForm1065", "llcFormK1", "llcForm8825", "llcForm4562",
    }

    # Preferred column sets for computed views
    GL_COLUMNS = ['Status', 'dt', 'acctType', 'acct', 'acctMinor', 'propNm', 'aType', 'amt', 'desc', 'acctSub', 'refDB']

    # ViewBy options per computed view (empty = no dropdown shown)
    VIEW_BY_OPTIONS: Dict[str, List[str]] = {
        'stmtGeneralLedger': ['All', 'By Dups', 'ByAsset', 'ByLiability', 'ByEquity', 'ByIncome', 'ByExpense'],
        'stmtBalanceSheet':  ['All', 'ByAsset', 'ByLiability', 'ByEquity', 'Details'],
        'stmtIncomeStmt':    ['All', 'ByIncome', 'ByExpense', 'ByProperty', 'ByPropertyDetails', 'PerMember', 'PerMemberDetails'],
        # IRS Form 1065 / Sch K-1 are now PDF-embed views (v0.2.4.7) — no
        # row-level publish filter at the view layer; the publish flag is
        # baked into the underlying FILL.pdf.
    }

    RECORD_VIEW_OPTIONS = {
        "account": [
            "dt", "amt", "aType", "acct", "acctType", "Ledger", "acctSub", "desc",
        ],
        "property": [
            "dt", "amt", "aType", "acct", "Ledger",
            "propNm", "propID", "propAddr", "propOwners",
        ],
        "all": [
            "dt", "amt", "aType", "acct", "acctType", "Ledger", "desc",
            "acctSub", "propNm", "propID", "propAddr", "propOwners",
            "tID", "tDB", "refDB", "refDoc", "_unknown",
        ],
    }

    def __init__(self, eSession, title: str = None):
        self.eSession = eSession
        self.llc_name = getattr(getattr(eSession, "llc", None), "objName", None)
        session_title = self.llc_name
        base_title = title or session_title or "LLC Management App"
        # v0.2: surface the package version in the app title so the running
        # editor is self-identifying in the browser tab and home header.
        try:
            from ui import __version__ as _ui_version
        except Exception:
            _ui_version = None
        self.version = _ui_version
        self.title = f"{base_title} (ui {_ui_version})" if _ui_version else base_title

        template_dir = Path(__file__).resolve().parent / "templates"
        self.app = Flask(__name__, template_folder=str(template_dir))
        # Explicit session cookie settings — SameSite=Lax ensures the cookie is
        # sent for top-level navigations including popup/new-tab opens.
        self.app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        self.app.config["SESSION_COOKIE_PATH"]     = "/"

        import hashlib
        _key = os.environ.get("LLC_SECRET_KEY")
        _key_src = "env"
        if not _key:
            _mw_cfg = Path.home() / ".MultiTaskWS" / "MultiTaskWS_config.json"
            if _mw_cfg.exists():
                try:
                    _mw = json.loads(_mw_cfg.read_text())
                    _key = (_mw.get("rentalTracker", {}).get("WEB_SECRET_KEY")
                            or _mw.get("WEB_SECRET_KEY"))
                    if _key:
                        _key_src = "mw_config"
                except Exception:
                    pass
        if not _key:
            _seed = f"llcRentalTracker:{_sp.CONFIG_FILE}:{self.llc_name or 'LLC'}"
            _key = hashlib.sha256(_seed.encode()).hexdigest()
            _key_src = "derived"
        self.app.secret_key = _key
        self.app._llc_version = self.version

        # Inject LLC_GPG_PASSPHRASE from config.json secrets if not already in env.
        # setup_paths.SECRETS is loaded from ~/.llcRentalTracker/config.json at startup.
        # Fallback to llc.MultiTaskWS_Config for legacy installs not yet migrated.
        if not os.environ.get("LLC_GPG_PASSPHRASE"):
            _pp = (_sp.SECRETS or {}).get("LLC_GPG_PASSPHRASE")
            if not _pp:
                _mw_legacy = getattr(getattr(eSession, "llc", None), "MultiTaskWS_Config", None)
                _pp = (_mw_legacy or {}).get("LLC_GPG_PASSPHRASE")
            if _pp:
                os.environ["LLC_GPG_PASSPHRASE"] = _pp

        self._setup_logging()
        self.app.logger.info(
            "startup: llc=%s year=%s secret_key_src=%s gpg_passphrase=%s",
            self.llc_name, getattr(self.eSession, "year", "?"), _key_src,
            "set" if os.environ.get("LLC_GPG_PASSPHRASE") else "MISSING",
        )

        # Store eSession and llc_name in app.config so auth routes and Switch Year can access them
        self.app.config['_esession']  = eSession
        self.app.config['_llc_name']  = self.llc_name or "LLC"

        make_auth_routes(self.app, llc_name=self.app.config['_llc_name'])

        self.objects = self._build_objects()

        @self.app.context_processor
        def inject_globals():
            from ledger import setup_paths as _sp
            llc_nm = self.app.config.get('_llc_name', '')
            # k1_owners: available on every page for the nav dropdown per-member links
            try:
                k1_mgr  = self.objects.get("llcFormK1")
                k1_owners_nav = k1_mgr.owners() if k1_mgr else []
            except Exception:
                k1_owners_nav = []
            return {
                "app_title":        self.title,
                "available_views":  self.available_views(),
                "view_groups":      self.VIEW_GROUPS,
                "view_labels":      self.VIEW_LABELS,
                "current_user":     session.get("full_name", ""),
                "current_role":     session.get("role", ""),
                "current_year":     session.get("year", getattr(self.eSession, 'year', '')),
                "available_years":  _sp.available_years(llc_nm) if llc_nm else [],
                "k1_owners":        k1_owners_nav,
            }

        self._bind_routes()

    def _canonical_name(self, name: str) -> str:
        aliases = {
            "llcAsset":          "llcAssets",
            "llcAssets":         "llcAssets",
            "llcExpRev":         "llcExpRev",
            # v0.2: A/P and A/R
            "llcPayable":        "llcPayables",
            "llcPayables":       "llcPayables",
            "llcAP":             "llcPayables",
            "llcReceivable":     "llcReceivables",
            "llcReceivables":    "llcReceivables",
            "llcAR":             "llcReceivables",
            "stmtGeneralLedger":  "stmtGeneralLedger",
            "stmtIncomeStmt":     "stmtIncomeStmt",
            "stmtBalanceSheet":   "stmtBalanceSheet",
            "stmtOwnerEquity":    "stmtOwnerEquity",
            "llcBank":           "llcBank",
            "stmtPropertyEquity": "stmtPropertyEquity",
            "llcForm1065":          "llcForm1065",
            "llcFormK1":            "llcFormK1",
            "llcForm8825":          "llcForm8825",
            "Form8825":             "llcForm8825",
            "llcForm4562":          "llcForm4562",
            "Form4562":             "llcForm4562",
            # Admin directory views
            "llcOwners":            "llcOwners",
            "llcCustomers":         "llcCustomers",
            "llcMilestones":        "llcMilestones",
        }
        return aliases.get(name, name)

    def _auto_wknode(self, oid: str, default_filename: str):
        '''
        v0.2 helper: build a WkNode for an editable view when the caller's
        eSession doesn't already include one.

          1. Try to find a sibling WkNode already in eSession and place the
             new DB alongside it in the same Accts folder.
          2. Fall back to the current working directory if no sibling exists.
          3. Create the JSON file as an empty list [] if missing, so load()
             returns [] instead of raising.
        '''
        try:
            from ui.llcSession import ObjNode, WkNode
        except Exception:
            return None

        accts_dir = None
        working_dir = None
        for existing_wk in self.eSession.oDict.values():
            try:
                accts_dir = Path(existing_wk.o.FN()).parent
                working_dir = Path(existing_wk.FN()).parent
                break
            except Exception:
                continue

        if accts_dir is None:
            accts_dir   = Path.cwd()
            working_dir = accts_dir / "working"

        obj_path = accts_dir / default_filename
        wk_path  = working_dir / default_filename

        if not obj_path.exists():
            try:
                obj_path.parent.mkdir(parents=True, exist_ok=True)
                obj_path.write_text("[]\n", encoding="utf-8")
            except Exception:
                pass

        obj = ObjNode(oid, str(obj_path))
        wk  = WkNode(obj, str(wk_path))
        return wk

    def _build_objects(self) -> Dict[str, Any]:
        objects: Dict[str, Any] = {}

        # ── editable views: built from WkNode objects in eSession ─────────────
        for wk in self.eSession.oDict.values():
            obj_name = self._canonical_name(getattr(getattr(wk, "o", None), "oID", ""))
            if obj_name in objects:
                continue

            mgr = None
            if obj_name == "llcAssets":
                mgr = llcAssets(wk)
            elif obj_name == "llcExpRev":
                mgr = llcExpRev(wk)
            elif obj_name == "llcPayables":
                mgr = llcPayables(wk)
            elif obj_name == "llcReceivables":
                mgr = llcReceivables(wk)

            if mgr is not None:
                if hasattr(mgr, "bind_session"):
                    mgr.bind_session(self.eSession)
                objects[obj_name] = mgr

        # ── v0.2: auto-register Payables / Receivables if the caller's
        # eSession didn't include them. We derive the Accts folder from an
        # existing sibling WkNode (typically llcAssets) and create a WkNode
        # pointing to the empty JSON DB. If no sibling is available we fall
        # back to a memory-only WkNode so the view still renders with
        # headers + zero rows instead of "Under Construction".
        _auto_register = [
            ("llcPayables",    "llcPayables_WBGroupLLC.json",    llcPayables),
            ("llcReceivables", "llcReceivables_WBGroupLLC.json",  llcReceivables),
            ("llcOwners",      "llcOwners_WBGroupLLC.json",       llcOwners),
            ("llcCustomers",   "llcCustomers_WBGroupLLC.json",    llcCustomers),
            ("llcMilestones",  "llcMilestones_WBGroupLLC.json",   llcMilestones),
        ]
        for key, default_fn, cls in _auto_register:
            if key in objects:
                continue
            wk = self._auto_wknode(key, default_fn)
            if wk is None:
                continue
            mgr = cls(wk)
            if hasattr(mgr, "bind_session"):
                mgr.bind_session(self.eSession)
            objects[key] = mgr
            try:
                self.eSession.oDict.setdefault(key, wk)
            except Exception:
                pass

        # ── computed (read-only) views ────────────────────────────────────────
        objects["stmtGeneralLedger"]  = stmtGeneralLedger(self.eSession)
        objects["stmtBalanceSheet"]   = stmtBalanceSheet(self.eSession)
        objects["stmtIncomeStmt"]     = stmtIncomeStmt(self.eSession)
        objects["stmtOwnerEquity"]    = stmtOwnerEquity(self.eSession)
        objects["llcBank"]           = llcBankView(self.eSession)
        objects["stmtPropertyEquity"] = stmtPropertyEquity(self.eSession)

        # ── IRS tax aid views (v0.2.4.7 — PDF-embed only) ────────────────────
        objects["llcForm1065"] = llcForm1065(self.eSession)
        objects["llcFormK1"]   = llcFormK1(self.eSession)
        objects["llcForm8825"] = llcForm8825(self.eSession)
        objects["llcForm4562"] = llcForm4562(self.eSession)

        return objects

    def _rebuild_objects(self):
        """Rebuild the objects dict after an eSession switch (e.g. Switch Year)."""
        self.objects = self._build_objects()

    def available_views(self) -> List[Dict[str, Any]]:
        items = []
        for name in self.VIEW_ORDER:
            items.append({
                "name":              name,
                "label":             self.VIEW_LABELS.get(name, name),
                "present":           name in self.objects,
                "under_construction": False,
            })
        return items

    def _supports_record_views(self, obj_type: str) -> bool:
        return obj_type in ("llcAssets", "llcExpRev", "llcPayables", "llcReceivables")

    def _normalize_view_mode(self, value: str) -> str:
        value = (value or "all").strip().lower()
        alias_map = {
            "by account": "account", "account": "account", "acct": "account",
            "by property": "property", "byproperty": "property",
            "property": "property", "prop": "property",
            "by all": "all", "all": "all",
        }
        return alias_map.get(value, "all")

    def _is_dir_view(self, obj_type: str) -> bool:
        return obj_type in self.ADMIN_COLUMNS

    def _get_columns(self, rows: List[Dict[str, Any]], obj_type: str, view_mode: str = "all") -> List[str]:
        if obj_type in self.ADMIN_COLUMNS:
            return list(self.ADMIN_COLUMNS[obj_type])
        if self._supports_record_views(obj_type):
            mode = self._normalize_view_mode(view_mode)
            return list(self.RECORD_VIEW_OPTIONS[mode])

        if obj_type == "stmtGeneralLedger":
            return list(self.GL_COLUMNS)

        # Financial views: use priority ordering
        cols: Set[str] = set()
        for row in rows:
            if isinstance(row, dict):
                cols.update(row.keys())

        if not cols:
            return ["acctType", "acct"]

        priority = ["acctType", "acct", "Debit", "Credit", "Balance",
                    "dt", "amt", "aType", "desc", "acctSub", "refDB"]
        ordered = [c for c in priority if c in cols]
        ordered += sorted(c for c in cols if c not in priority)
        return ordered

    def _display_scalar(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            s = json.dumps(value, ensure_ascii=False)
        elif value is None:
            s = ""
        else:
            s = str(value)
        return s if len(s) <= 64 else s[:61] + "..."

    def _format_stat_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return ""
        return str(value)

    def _get_forms_dir(self):
        """Return the IRS_FORMS_DIR Path or None."""
        try:
            from ledger.setup_paths import IRS_FORMS_DIR
            if IRS_FORMS_DIR:
                from pathlib import Path as _Path
                return _Path(IRS_FORMS_DIR)
        except Exception:
            pass
        return None

    def _stats_labels(self, stats: Dict[str, Any]) -> List[Dict[str, str]]:
        labels: List[Dict[str, str]] = []
        for key, value in (stats or {}).items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    labels.append({
                        "value": self._format_stat_value(sub_value),
                        "text":  str(sub_key),
                        "group": str(key),
                    })
            else:
                labels.append({
                    "value": self._format_stat_value(value),
                    "text":  str(key),
                    "group": "",
                })
        return labels

    def _parse_payload(self, payload, default):
        if payload is None or payload == "":
            return default
        if isinstance(payload, (dict, list)):
            return payload
        return json.loads(payload)

    def _row_id(self, row: Dict[str, Any], index: int) -> str:
        # tID is the natural key for asset/expense records; fall back to id, oID, then index
        k = row.get("tID") or row.get("id") or row.get("oID")
        return str(k) if k is not None else str(index)

    @staticmethod
    def _row_index_arg(n_rows: int) -> Optional[int]:
        '''Parse the `idx` form/query arg into a valid 0-based row index, else None.'''
        raw = request.values.get("idx")
        if raw is None or str(raw).strip() == "":
            return None
        try:
            i = int(raw)
        except (TypeError, ValueError):
            return None
        return i if 0 <= i < n_rows else None

    @staticmethod
    def _gen_unique_tid(payload: Dict[str, Any], existing_rows: List[Dict[str, Any]]) -> str:
        '''Generate a unique tID in format <dt>_<D|C><amt:.2f>[_N] for a new record.
        N (≥2) is appended when the base tID already exists.'''
        dt    = str(payload.get('dt', '') or '').strip()
        amt   = float(payload.get('amt', 0) or 0)
        atype = str(payload.get('aType', 'Debit') or 'Debit').strip()
        dc    = 'C' if atype == 'Credit' else 'D'
        base  = f"{dt}_{dc}{amt:.2f}"
        existing = {str(r.get('tID', '') or '') for r in existing_rows}
        if base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    def _merge_save(self, manager, payload_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        '''
        Merge-save: fold payload_rows into the full working dataset and save.

        This prevents a filtered-view Save from deleting records that were
        not visible in the current view.  The algorithm is:

          1. Load ALL records from the working file (unfiltered).
          2. Index them by their natural key (tID → id → oID → positional index).
          3. For each record in payload_rows:
               • If its key matches an existing record  → update that record.
               • If its key is new                      → append as a new record.
          4. Records that appear in the full set but NOT in the payload are kept
             unchanged.
          5. Save the merged full list via manager.save().

        When the payload is the complete unfiltered set (normal Save from an
        unfiltered view) every record matches and the behaviour is identical to
        a plain replace-save.
        '''
        all_rows = manager.load()   # always loads from the working file (full, unfiltered)

        def _key(row: Dict[str, Any], idx: int) -> str:
            k = row.get('tID') or row.get('id') or row.get('oID')
            return str(k) if k is not None else f'__idx__{idx}'

        # Build key → position map for the current full dataset
        key_to_idx: Dict[str, int] = {}
        for i, row in enumerate(all_rows):
            k = _key(row, i)
            if k not in key_to_idx:
                key_to_idx[k] = i

        new_records: List[Dict[str, Any]] = []
        for j, p_row in enumerate(payload_rows):
            k = _key(p_row, j)
            if k in key_to_idx:
                all_rows[key_to_idx[k]] = p_row   # update existing
            else:
                new_records.append(p_row)          # genuinely new record

        all_rows.extend(new_records)
        return manager.save(all_rows)

    @staticmethod
    def _sanitize(obj: Any) -> Any:
        '''Recursively replace float NaN/Inf with None so Flask jsonify stays valid JSON.'''
        if isinstance(obj, dict):
            return {k: llcMgmt._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [llcMgmt._sanitize(v) for v in obj]
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj

    def _setup_logging(self) -> None:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        fmt = logging.Formatter("%(asctime)s %(levelname)s [%(module)s] %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        fh = RotatingFileHandler(log_dir / "llcRentalTracker.log",
                                 maxBytes=1_000_000, backupCount=3)
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()   # stderr → PA error log
        sh.setFormatter(fmt)
        self.app.logger.setLevel(logging.INFO)
        self.app.logger.addHandler(fh)
        self.app.logger.addHandler(sh)
        self.app.logger.propagate = False

    def _parse_changed_ids(self) -> Set[str]:
        raw = request.args.get("chg", "")
        if not raw:
            return set()
        return {x.strip() for x in raw.split(",") if x.strip()}

    def _view_rows(self, rows: List[Dict[str, Any]], changed_ids: Set[str] = None) -> List[Dict[str, Any]]:
        changed_ids = changed_ids or set()
        result = []
        for idx, row in enumerate(rows):
            record_id = self._row_id(row, idx)
            result.append({
                "_row_index": idx,
                "_record_id": record_id,
                "_changed":   record_id in changed_ids,
                "data":       row,
            })
        return result

    # Routes that don't require a logged-in session.
    _PUBLIC_ENDPOINTS = {"login", "logout", "register", "static"}

    def _bind_routes(self):
        app = self.app

        @app.before_request
        def _require_login():
            # endpoint is None during trailing-slash redirects — treat as public
            if not request.endpoint or request.endpoint in self._PUBLIC_ENDPOINTS:
                return
            if not session.get("logged_in"):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "authentication required"}), 401
                next_path = request.script_root + request.path
                app.logger.info(
                    "auth: redirect to login — endpoint=%s script_root=%r path=%r next=%r",
                    request.endpoint, request.script_root, request.path, next_path,
                )
                return redirect(url_for("login", next=next_path))

        @app.route("/.well-known/appspecific/com.chrome.devtools.json")
        def chrome_devtools_json():
            return jsonify([])

        # ── IRS FILL.pdf binary route (v0.2.4.7) ──────────────────────────────
        # Serves Forms_IRS/<form_id>_FILL.pdf as application/pdf.  Used by the
        # iframe src in irs_pdf_view.html.  ?download=1 triggers a "Save As"
        # response instead of inline rendering.
        @app.route("/forms/<form_id>.pdf")
        def serve_irs_pdf(form_id: str):
            allowed = set(self.PDF_VIEWS.values())
            if form_id not in allowed:
                abort(404)
            es = self.eSession
            if es is None:
                abort(404)
            try:
                irs_dir = es.paths.irs_forms_dir
            except Exception:
                abort(404)
            # K-1 per-partner: ?member=oID serves Sch_K1_{oID}_FILL.pdf
            member = request.args.get("member", "").strip()
            if form_id == "Sch_K1" and member:
                pdf_path = irs_dir / f"Sch_K1_{member}_FILL.pdf"
                dl_name  = f"Sch_K1_{member}_FILL.pdf"
            else:
                pdf_path = irs_dir / f"{form_id}_FILL.pdf"
                dl_name  = f"{form_id}_FILL.pdf"
            if not pdf_path.exists():
                abort(404)
            as_attachment = request.args.get("download", "0") == "1"
            return send_file(
                str(pdf_path),
                mimetype="application/pdf",
                as_attachment=as_attachment,
                download_name=dl_name,
            )

        @app.route("/forms/<form_id>_NS.pdf")
        def serve_irs_ns_pdf(form_id: str):
            """Serve the AcroForm namespace reference PDF for any IRS form."""
            allowed = set(self.PDF_VIEWS.values())
            if form_id not in allowed:
                abort(404)
            es = self.eSession
            if es is None:
                abort(404)
            try:
                irs_dir = es.paths.irs_forms_dir
            except Exception:
                abort(404)
            pdf_path = irs_dir / f"{form_id}_namespace.pdf"
            if not pdf_path.exists():
                abort(404)
            return send_file(
                str(pdf_path),
                mimetype="application/pdf",
                download_name=f"{form_id}_namespace.pdf",
            )

        # ── Home ──────────────────────────────────────────────────────────────
        @app.route("/")
        def home():
            session_views = []
            seen = set()
            for key, wk in self.eSession.oDict.items():
                obj_name = self._canonical_name(getattr(getattr(wk, "o", None), "oID", key))
                fn  = wk.FN()   if hasattr(wk, 'FN')                        else ''
                ofn = wk.o.FN() if hasattr(wk, 'o') and hasattr(wk.o, 'FN') else ''
                stamp = (obj_name, fn, ofn)
                if stamp in seen:
                    continue
                seen.add(stamp)
                session_views.append({
                    "name":         obj_name,
                    "raw_name":     key,
                    "working_file": fn,
                    "object_file":  ofn,
                })

            return render_template(
                "home.html",
                title=self.title,
                session_views=session_views,
            )

        # ── Home Financial Snapshot API ───────────────────────────────────────
        @app.route("/api/home/snapshot")
        def api_home_snapshot():
            try:
                from ui.llcReportEngine import llcReportEngine as _RE
                from ledger.stmtIS import stmtIS as _stmtIS
                from ledger.stmtBS import stmtBS as _stmtBS

                engine     = _RE(self.eSession)
                gl_records = engine.getGLList(resolve_dups=True, force=True)

                is_agg = _stmtIS(self.eSession.llc, gl_records=gl_records).taxAggregates()
                bs_agg = _stmtBS(self.eSession.llc, gl_records=gl_records).taxAggregates()

                # Monthly Revenue/Expense for bar chart — GL rows only,
                # filtered to Acct.Rev.* (income) and Acct.Exp.* (expense).
                # Using one side of double-entry per account avoids double-counting
                # and excludes Asset/Equity/Liability entries (e.g. capital contributions).
                monthly: Dict[str, Dict] = {}
                for r in gl_records:
                    dt   = str(r.get('dt') or '')
                    acct = str(r.get('acct') or '')
                    if len(dt) < 7:
                        continue
                    ym  = dt[:7]   # "2025.08"
                    amt = float(r.get('amt') or 0)
                    if ym not in monthly:
                        monthly[ym] = {'income': 0.0, 'expense': 0.0}
                    if acct.startswith('Acct.Rev'):
                        monthly[ym]['income'] = round(monthly[ym]['income'] + amt, 2)
                    elif acct.startswith('Acct.Exp'):
                        monthly[ym]['expense'] = round(monthly[ym]['expense'] + amt, 2)

                _ABBR = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                         'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                chart_data = []
                for ym in sorted(monthly.keys()):
                    parts = ym.split('.')
                    try:
                        lbl = _ABBR[int(parts[1])] if len(parts) >= 2 else ym
                    except (ValueError, IndexError):
                        lbl = ym
                    chart_data.append({'label': lbl,
                                       'income':  monthly[ym]['income'],
                                       'expense': monthly[ym]['expense']})

                return jsonify({
                    'ok':             True,
                    'total_income':   is_agg.get('total_income', 0),
                    'total_expenses': is_agg.get('total_expenses', 0),
                    'net_income':     is_agg.get('net_income', 0),
                    'total_equity':   bs_agg.get('total_equity', 0),
                    'earned_pnl':     is_agg.get('net_income', 0),
                    'monthly':        chart_data,
                })
            except Exception as exc:
                app.logger.exception("api_home_snapshot error")
                return jsonify({'ok': False, 'error': str(exc)}), 500

        # ── Switch Year ───────────────────────────────────────────────────────
        @app.route("/switch_year", methods=["POST"])
        def switch_year():
            from util.utilEditSession import utilEditSession as _UES
            year = request.form.get("year", type=int)
            if not year:
                return redirect(url_for("home"))
            llc_nm = self.app.config.get("_llc_name")
            try:
                new_es = _UES(llcName=llc_nm, year=year)
                self.eSession = new_es
                self.app.config["_esession"] = new_es
                self._rebuild_objects()
                session["year"] = year
            except Exception as exc:
                app.logger.error("Switch Year failed: %s", exc)
            return redirect(url_for("home"))

        # ── LLC Admin ─────────────────────────────────────────────────────────
        @app.route("/admin")
        def llc_admin():
            # Compute YTD RetainedEarning per owner from IS (net_income × pct)
            owner_re: Dict[str, float] = {}
            try:
                is_mgr = self.objects.get("stmtIncomeStmt")
                if is_mgr:
                    owners_raw = self.objects.get("llcOwners")
                    owners_list = owners_raw.load() if owners_raw else []
                    _, _, pm_summary = is_mgr.load_per_member(details=False)
                    ni = float(pm_summary.get("net_income", 0) or 0)
                    for o in owners_list:
                        oid = o.get("oID", "")
                        pct = float(o.get("pct", 0) or 0)
                        owner_re[oid] = round(ni * pct, 2)
            except Exception:
                pass  # leave owner_re empty — display shows — in template

            def _frame(key):
                mgr  = self.objects.get(key)
                rows = list(mgr.load()) if mgr else []
                # Inject computed columns into owner rows
                if key == "llcOwners":
                    for row in rows:
                        oid = row.get("oID", "")
                        if oid in owner_re:
                            row["RetainedEarning"] = owner_re[oid]
                return {
                    "key":           key,
                    "label":         self.VIEW_LABELS.get(key, key),
                    "columns":       self.ADMIN_DISPLAY_COLUMNS.get(key, self.ADMIN_COLUMNS.get(key, [])),
                    "computed_cols": list(self.ADMIN_COMPUTED_COLS),
                    "rows":          rows,
                    "edit_url":      url_for("view_object", obj_type=key),
                }

            frames = [
                _frame("llcOwners"),
                _frame("llcCustomers"),
                _frame("llcMilestones"),
            ]
            return render_template(
                "admin_view.html",
                title=self.title,
                frames=frames,
            )

        # ── View ──────────────────────────────────────────────────────────────
        @app.route("/view/yeFinancialReport")
        def view_ye_financial_report():
            '''Dedicated YE Financial Report viewer page.'''
            from ledger import setup_paths
            data_nm  = getattr(self.eSession.llc, 'objName', 'LLC')
            yr       = getattr(self.eSession.llc, 'yr', '')
            pdf_name = f'{data_nm}_{yr}_YEFinancialReport.pdf'
            pdf_path = setup_paths.IRS_FORMS_DIR / pdf_name
            return render_template(
                "ye_report_view.html",
                title=self.title,
                app_title=self.title,
                pdf_exists=pdf_path.exists(),
                pdf_name=pdf_name,
                year=yr,
            )

        @app.route("/view/<obj_type>")
        def view_object(obj_type: str):
            obj_type = self._canonical_name(obj_type)
            manager  = self.objects.get(obj_type)

            if manager is None:
                # v0.2: for editable record views (Assets / ExpRev / Payables /
                # Receivables) render an empty table with headers instead of
                # the "Under Construction" page, so a fresh A/P or A/R tab
                # always looks like an empty ledger rather than a stub.
                if self._supports_record_views(obj_type):
                    columns = list(self.RECORD_VIEW_OPTIONS["all"])
                    return render_template(
                        "table_view.html",
                        title=self.title,
                        obj_type=obj_type,
                        rows=[],
                        raw_rows=[],
                        columns=columns,
                        stats={"Transactions": 0, "AccountTypes": 0, "Balance": 0.0, "ByAcctType": {}},
                        stats_labels=[],
                        meta={"objectName": obj_type, "workingFile": "", "objectFile": ""},
                        display_scalar=self._display_scalar,
                        view_mode="all",
                        view_by="All",
                        view_by_options=["All"],
                        show_view_options=True,
                        read_only=False,
                    )

                meta = {"objectName": obj_type}
                return render_template(
                    "construction.html",
                    title=self.title,
                    obj_type=obj_type,
                    meta=meta,
                )

            view_mode        = self._normalize_view_mode(request.args.get("viewMode", "all"))
            view_by          = request.args.get("viewBy", "All")
            view_by_options  = self.VIEW_BY_OPTIONS.get(obj_type, [])

            # Income Statement defaults to PerMember view
            if obj_type == 'stmtIncomeStmt' and view_by == 'All':
                view_by = 'PerMember'

            # PDF-embed tax views skip the load() call entirely — the page
            # just renders the FILL.pdf.  We early-return below.
            changed_ids = self._parse_changed_ids()

            if obj_type in self.PDF_VIEWS:
                form_nm  = self.PDF_VIEWS[obj_type]
                mgr_meta = manager.meta()
                # Namespace PDF — check file existence here so all form
                # wrappers benefit without each needing to implement it.
                ns_pdf_url = None
                try:
                    _ns = self.eSession.paths.irs_forms_dir / f"{form_nm}_namespace.pdf"
                    if _ns.exists():
                        ns_pdf_url = url_for("serve_irs_ns_pdf", form_id=form_nm)
                except Exception:
                    pass
                # K-1: ?member=oID auto-selects the member PDF on load
                default_member = ""
                if form_nm == "Sch_K1":
                    default_member = request.args.get("member", "").strip()
                    # Build view title with member name if known
                    if default_member:
                        owners = mgr_meta.get("owners", [])
                        nm = next((o["name"] for o in owners if o["oID"] == default_member), default_member)
                        view_title = f"Schedule K-1 — {nm}"
                    else:
                        view_title = self.VIEW_TITLES.get(obj_type, obj_type)
                else:
                    view_title = self.VIEW_TITLES.get(obj_type, obj_type)
                return render_template(
                    "irs_pdf_view.html",
                    title=self.title,
                    obj_type=obj_type,
                    view_title=view_title,
                    pdf_url=url_for("serve_irs_pdf", form_id=form_nm),
                    ns_pdf_url=ns_pdf_url,
                    stats=manager.stats(),
                    stats_labels=self._stats_labels(manager.stats()),
                    meta=mgr_meta,
                    default_member=default_member,
                )

            if obj_type in self.READ_ONLY_VIEWS and obj_type not in self.BANK_VIEWS:
                rows = manager.load(view_by=view_by)
            else:
                rows = manager.load()

            stats = manager.stats()

            # Editable views: dynamic ViewBy from actual acctTypes + display filter
            if self._supports_record_views(obj_type):
                acct_types = sorted({r.get('acctType', '') for r in rows if r.get('acctType', '')})
                view_by_options = ['All'] + [f'By{t}' for t in acct_types]
                if view_by and view_by != 'All':
                    acct_type_filter = view_by[2:]
                    rows = [r for r in rows if r.get('acctType', '') == acct_type_filter]

            meta         = manager.meta()
            stats_labels = self._stats_labels(stats)

            # ── Bank view ─────────────────────────────────────────────────────
            if obj_type in self.BANK_VIEWS:
                bank_mgr: llcBankView = manager
                return render_template(
                    "bank_view.html",
                    title=self.title,
                    obj_type=obj_type,
                    rows=self._view_rows(rows),
                    raw_rows=rows,
                    stats=stats,
                    stats_labels=stats_labels,
                    meta=meta,
                    bank_dir=bank_mgr.bank_dir_str(),
                    csv_files=bank_mgr.csv_files(),
                    csv_loaded=bank_mgr.csv_loaded(),
                )

            # ── 2-frame General Ledger view (v0.2.3.4) ────────────────────────
            if obj_type in self.GL_VIEWS:
                # Let the wrapper build BOTH frames in one pass under the
                # same view_by.  The template (general_ledger_view.html)
                # reads everything it needs off `frames`.
                frames_bundle = manager.frames(view_by=view_by)
                return render_template(
                    "general_ledger_view.html",
                    title=self.title,
                    obj_type=obj_type,
                    view_title=self.VIEW_TITLES.get(obj_type, obj_type),
                    frames=frames_bundle,
                    stats=stats,
                    stats_labels=stats_labels,
                    meta=meta,
                    view_mode=view_mode,
                )

            # ── Financial Statement views ─────────────────────────────────────
            if obj_type in self.FINANCIAL_VIEWS:

                # ── IS ByProperty / ByPropertyDetails: unstacked property view ──
                if obj_type == "stmtIncomeStmt" and view_by in ("ByProperty", "ByPropertyDetails"):
                    bp_rows, prop_names, bp_summary = manager.load_by_property(view_by=view_by)
                    bp_stats = {
                        'Income':     bp_summary.get('income',     0),
                        'Expense':    bp_summary.get('expense',    0),
                        'Net Income': bp_summary.get('net_income', 0),
                        'Properties': len(prop_names),
                    }
                    return render_template(
                        "is_property_view.html",
                        title=self.title,
                        obj_type=obj_type,
                        view_title=self.VIEW_TITLES.get(obj_type, obj_type),
                        rows=self._view_rows(bp_rows),
                        raw_rows=bp_rows,
                        prop_names=prop_names,
                        stats=bp_stats,
                        stats_labels=self._stats_labels(bp_stats),
                        meta=meta,
                        view_by=view_by,
                        view_by_options=view_by_options,
                    )

                # ── IS Per-Member view: separate template ─────────────────────
                if obj_type == "stmtIncomeStmt" and view_by in ("PerMember", "PerMemberDetails"):
                    is_details = view_by == "PerMemberDetails"
                    pm_rows, owner_names, pm_summary = manager.load_per_member(details=is_details)
                    pm_stats = {
                        'Income':      pm_summary.get('income_subtotal',     0),
                        'Expense':     pm_summary.get('expense_subtotal',    0),
                        'Net Income':  pm_summary.get('net_income',          0),
                        'Depreciation':pm_summary.get('depreciation',        0),
                        'NI w/ Depr':  pm_summary.get('net_income_with_depr',0),
                        'Members':     len(owner_names),
                    }
                    return render_template(
                        "is_member_view.html",
                        title=self.title,
                        obj_type=obj_type,
                        view_title=self.VIEW_TITLES.get(obj_type, obj_type),
                        rows=self._view_rows(pm_rows),
                        raw_rows=pm_rows,
                        owner_names=owner_names,
                        stats=pm_stats,
                        stats_labels=self._stats_labels(pm_stats),
                        meta=meta,
                        view_by=view_by,
                        view_by_options=view_by_options,
                        show_detail=is_details,
                    )

                # For Balance Sheet: also pass the accounting-equation check + open-period flag
                bs_check = None
                if obj_type == "stmtBalanceSheet" and hasattr(manager, "last_check"):
                    bs_check = manager.last_check()
                    if bs_check and bs_check.get('equation_diff') is not None:
                        from ui.llcReportEngine import llcReportEngine as _RE
                        from ledger.auditor     import GLAuditor      as _Aud
                        _gl  = _RE(self.eSession).getGLList(resolve_dups=True, force=True)
                        _eq  = _Aud(self.eSession.llc, _gl).equation_summary()
                        _ni  = _eq.get('net_income', 0)
                        _gap = bs_check['equation_diff']
                        bs_check['gap_is_ni'] = abs(_gap - _ni) < 0.01

                return render_template(
                    "financial_view.html",
                    title=self.title,
                    obj_type=obj_type,
                    view_title=self.VIEW_TITLES.get(obj_type, obj_type),
                    rows=self._view_rows(rows),
                    raw_rows=rows,
                    stats=stats,
                    stats_labels=stats_labels,
                    meta=meta,
                    view_mode=view_mode,
                    view_by=view_by,
                    view_by_options=view_by_options,
                    bs_check=bs_check,
                )

            # ── Property Equity view ──────────────────────────────────────────
            if obj_type in self.PROPERTY_VIEWS:
                return render_template(
                    "property_equity.html",
                    title=self.title,
                    obj_type=obj_type,
                    view_title=self.VIEW_TITLES.get(obj_type, obj_type),
                    rows=self._view_rows(rows),
                    raw_rows=rows,
                    stats=stats,
                    stats_labels=stats_labels,
                    meta=meta,
                    view_by=view_by,
                    view_by_options=view_by_options,
                )

            # ── Standard table view ───────────────────────────────────────────
            columns   = self._get_columns(rows, obj_type, view_mode=view_mode)
            read_only = obj_type in self.READ_ONLY_VIEWS

            return render_template(
                "table_view.html",
                title=self.title,
                obj_type=obj_type,
                rows=self._view_rows(rows, changed_ids),
                raw_rows=rows,
                columns=columns,
                stats=stats,
                stats_labels=stats_labels,
                meta=meta,
                display_scalar=self._display_scalar,
                view_mode=view_mode,
                view_by=view_by,
                view_by_options=view_by_options,
                show_view_options=self._supports_record_views(obj_type),
                read_only=read_only,
            )

        # ── New Session ───────────────────────────────────────────────────────
        @app.route("/api/session/new", methods=["POST"])
        def new_session():
            stamp = self.eSession.push()
            self.eSession.reset()
            return jsonify({"ok": True, "snapshot": stamp})

        # ── Logoff (quit the LLC editor app) ──────────────────────────────────
        # v0.2: graceful shutdown triggered from the UI.  Returns JSON first,
        # then terminates the Flask process (and its daemon thread in notebook
        # mode) ~500 ms later so the client has time to receive the response.
        @app.route("/api/logoff", methods=["POST"])
        def logoff():
            import os as _os
            import threading as _threading

            def _shutdown():
                # os._exit() is intentional: it stops the Flask dev server /
                # notebook-mode daemon thread without waiting on werkzeug's
                # deprecated shutdown hook.
                _os._exit(0)

            _threading.Timer(0.5, _shutdown).start()
            return jsonify({
                "ok": True,
                "message": "LLC editor shutting down. You may close this tab.",
            })

        # ── COA lookup ────────────────────────────────────────────────────────
        @app.route("/api/coa/get")
        def coa_get():
            acct = request.args.get("acct", "").strip()
            if not acct:
                return jsonify({"ok": False, "error": "acct param required"}), 400
            # Find any computed view that has an engine with coa_lookup
            engine = None
            for obj in self.objects.values():
                if hasattr(obj, "engine") and hasattr(obj.engine, "coa_lookup"):
                    engine = obj.engine
                    break
            if engine is None:
                return jsonify({"ok": False, "error": "COA engine not available"}), 500
            entry = engine.coa_lookup(acct)
            if entry is None:
                return jsonify({"ok": False, "found": False, "acct": acct})
            return jsonify({"ok": True, "found": True, "entry": self._sanitize(entry)})

        @app.route("/api/coa/all")
        def coa_all():
            engine = None
            for obj in self.objects.values():
                if hasattr(obj, "engine") and hasattr(obj.engine, "coa_all"):
                    engine = obj.engine
                    break
            if engine is None:
                return jsonify({"ok": False, "error": "COA engine not available"}), 500
            return jsonify({"ok": True, "data": self._sanitize(engine.coa_all())})

        # ── Bank CSV upload ───────────────────────────────────────────────────
        @app.route("/api/llcBank/upload_csv", methods=["POST"])
        def upload_bank_csv():
            bank_mgr: llcBankView = self.objects.get("llcBank")
            if bank_mgr is None:
                return jsonify({"ok": False, "error": "llcBank view not initialised"}), 404

            if "csv_file" not in request.files:
                return jsonify({"ok": False, "error": "No csv_file in request"}), 400

            f = request.files["csv_file"]
            csv_data = f.read().decode("utf-8", errors="replace")
            new_rows = bank_mgr.load_from_csv_data(csv_data)
            return jsonify({"ok": True, "newTransactions": len(new_rows)})

        # ── Generic API command ───────────────────────────────────────────────
        @app.route("/api/<obj_type>/cmd", methods=["GET", "POST"])
        def api_cmd(obj_type: str):
            obj_type = self._canonical_name(obj_type)
            manager  = self.objects.get(obj_type)

            if manager is None:
                return jsonify({"ok": False, "error": f"Unknown object type: {obj_type}"}), 404

            cmd = request.values.get("cmd", "load")
            s   = self._sanitize

            if cmd == "load":
                return jsonify({"ok": True, "data": s(manager.load())})

            if cmd == "list":
                return jsonify({"ok": True, "data": s(manager.list())})

            if cmd == "stats":
                return jsonify({"ok": True, "data": s(manager.stats())})

            if cmd == "meta":
                return jsonify({"ok": True, "data": s(manager.meta())})

            if cmd == "save":
                payload = self._parse_payload(request.values.get("payload", "[]"), [])
                # Use merge-save so a filtered view never silently drops
                # records that were not visible in that view.
                return jsonify({"ok": True, "data": s(self._merge_save(manager, payload))})

            if cmd == "save_object":
                payload = request.values.get("payload")
                payload = self._parse_payload(payload, manager.load()) if payload is not None else manager.load()
                return jsonify({"ok": True, "data": s(manager.save_object(payload))})

            if cmd == "reset_from_object":
                return jsonify({"ok": True, "data": s(manager.reset_from_object())})

            if obj_type in self.READ_ONLY_VIEWS:
                return jsonify({"ok": False, "error": f"{obj_type} is a read-only computed view"}), 400

            if cmd == "add":
                payload = self._parse_payload(request.values.get("payload", "{}"), {})
                rows = manager.load()
                # System assigns a unique tID — user-supplied tID is ignored.
                payload['tID'] = self._gen_unique_tid(payload, rows)
                rows.append(payload)
                saved  = s(manager.save(rows))
                new_id = self._row_id(saved[-1], len(saved) - 1) if saved else ""
                return jsonify({"ok": True, "data": saved, "changedRecordId": new_id})

            if cmd == "update":
                record_id = request.values.get("id")
                payload   = self._parse_payload(request.values.get("payload", "{}"), {})
                rows = manager.load()
                idx = self._row_index_arg(len(rows))
                updated = False
                if idx is not None:
                    # tID is immutable — preserve the original tID from the stored record.
                    orig_tid = rows[idx].get('tID')
                    payload['tID'] = orig_tid
                    rows[idx] = payload
                    updated = True
                else:
                    for i, row in enumerate(rows):
                        if self._row_id(row, i) == str(record_id):
                            orig_tid = row.get('tID')
                            payload['tID'] = orig_tid
                            rows[i] = payload
                            updated = True
                            break
                if not updated:
                    return jsonify({"ok": False, "error": "Record not found"}), 404
                saved = s(manager.save(rows))
                return jsonify({"ok": True, "data": saved, "changedRecordId": str(record_id)})

            if cmd == "delete":
                record_id = request.values.get("id")
                rows      = manager.load()
                idx = self._row_index_arg(len(rows))
                if idx is not None:
                    new_rows = [row for i, row in enumerate(rows) if i != idx]
                else:
                    new_rows = [row for i, row in enumerate(rows) if self._row_id(row, i) != str(record_id)]
                saved = s(manager.save(new_rows))
                return jsonify({"ok": True, "data": saved})

            if cmd == "batch":
                # Accept JSON body or form-encoded payload
                body = request.get_json(silent=True) or {}
                if not body.get("ops"):
                    raw = request.values.get("payload", "{}")
                    body = self._parse_payload(raw, {})
                ops = body.get("ops", [])
                if not ops:
                    return jsonify({"ok": False, "error": "no ops in batch"}), 400

                rows   = list(manager.load())
                errors = []
                delete_ids: Set[str] = set()
                adds: List[Dict[str, Any]] = []

                for op in ops:
                    sub = op.get("cmd")
                    if sub == "update":
                        idx_raw = op.get("idx")
                        rid     = str(op.get("id", ""))
                        payload = dict(op.get("payload") or {})
                        updated = False
                        if idx_raw is not None:
                            try:
                                i = int(idx_raw)
                                if 0 <= i < len(rows):
                                    payload['tID'] = rows[i].get('tID')
                                    rows[i] = payload
                                    updated = True
                            except (TypeError, ValueError):
                                pass
                        if not updated:
                            for i, row in enumerate(rows):
                                if self._row_id(row, i) == rid:
                                    payload['tID'] = row.get('tID')
                                    rows[i] = payload
                                    updated = True
                                    break
                        if not updated:
                            errors.append(f"update: record not found (id={rid!r})")
                    elif sub == "add":
                        payload = dict(op.get("payload") or {})
                        payload['tID'] = self._gen_unique_tid(payload, rows + adds)
                        adds.append(payload)
                    elif sub == "delete":
                        rid = str(op.get("id", ""))
                        if rid:
                            delete_ids.add(rid)
                    else:
                        errors.append(f"unknown sub-cmd: {sub!r}")

                if errors:
                    return jsonify({"ok": False, "error": "; ".join(errors)}), 400

                if delete_ids:
                    rows = [row for i, row in enumerate(rows)
                            if self._row_id(row, i) not in delete_ids]
                rows.extend(adds)
                saved = s(manager.save(rows))
                return jsonify({"ok": True, "data": saved})

            return jsonify({"ok": False, "error": f"Unknown command: {cmd}"}), 400

        # ── Book→IRS Aid routes (v0.1) ──────────────────────────────────────
        # See docs/LLC_BookToIRS_Aid.md and irs/BookToIRS.py.
        # All write endpoints persist immediately to disk and refresh the
        # service's cached stmt instances.  Custom-map source surgery
        # (M4) returns 501 in v0.1.
        # Per "Tax Bridge" architecture (docs/LLC_AccountingDesign.md §2),
        # calls route through the Form service, which delegates to BookToIRS.
        from irs.BookToIRS import BookToIRS
        from werkzeug.exceptions import HTTPException

        # Forms the Aid is allowed to operate on.  Limited to the
        # ``PDF_VIEWS`` set so a malicious request can't ask the Aid to
        # touch arbitrary file names.  Form1065 stays the default for
        # back-compat with the original v0.1 routes.
        AID_FORMS = {"Form1065", "Sch_K1", "Form8825", "Form4562"}

        def _aid_form_from_request() -> str:
            """Resolve the formNm for this request from query string,
            JSON body, or the Form1065 default.  Validates against
            AID_FORMS so the Aid cannot be coerced into operating on
            an unknown / malicious form name."""
            from flask import request as _req
            formNm = _req.args.get("formNm")
            if not formNm and _req.method in ("POST", "PUT", "DELETE"):
                body = _req.get_json(silent=True) or {}
                if isinstance(body, dict):
                    formNm = body.get("formNm")
            formNm = formNm or "Form1065"
            if formNm not in AID_FORMS:
                abort(400, description=f"Unknown formNm: {formNm!r}. Allowed: {sorted(AID_FORMS)}")
            return formNm

        def _aid() -> "BookToIRS":
            llc = getattr(self.eSession, "llc", None)
            if llc is None:
                abort(404)
            formNm = _aid_form_from_request()
            try:
                import importlib
                mod = importlib.import_module(f"irs.{formNm}")
                form_cls = getattr(mod, formNm)
                form = form_cls(llc)
                return form.aid()
            except Exception as err:
                raise RuntimeError(f"{formNm}: Aid Not Available") from err

        def _aid_err(err: Exception):
            """Translate an exception raised by an Aid route into a JSON
            response.  Re-raises ``HTTPException`` so Flask's normal
            400/404/501 handling fires (rather than swallowing them in a
            generic 500)."""
            if isinstance(err, HTTPException):
                raise err
            return jsonify({"ok": False, "error": str(err)}), 500

        @app.route("/api/aid/sources")
        def aid_sources():
            return jsonify({"sources": _aid().listSources()})

        @app.route("/api/aid/mappings")
        def aid_mappings():
            return jsonify({"mappings": _aid().listMappings()})

        @app.route("/api/aid/mapping/<fid>")
        def aid_mapping(fid):
            try:
                return jsonify(_aid().getMapping(fid))
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        @app.route("/api/aid/fields/<src>")
        def aid_fields(src):
            aid = _aid()
            return jsonify({
                "src":             src,
                "fids":            aid.listFields(src),
                "resolvable_paths": aid.listAllPathsWithValues(src),
            })

        @app.route("/api/aid/preview")
        def aid_preview():
            fid  = request.args.get("fid", "")
            src  = request.args.get("src")
            path = request.args.get("path")
            aid  = _aid()
            return jsonify({
                "fid":   fid,
                "value": aid.previewValue(fid, src, path),
                "chips": aid.adviseChips(fid, src, path),
            })

        @app.route("/api/aid/mapping", methods=["POST"])
        def aid_create():
            data = request.get_json(silent=True) or {}
            fid  = data.get("fid", "");  src = data.get("src", ""); path = data.get("path", "")
            try:
                row = _aid().createMapping(fid, src, path)
                return jsonify({"ok": True, "row": row})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 400

        @app.route("/api/aid/mapping/<fid>", methods=["PUT"])
        def aid_edit(fid):
            data = request.get_json(silent=True) or {}
            src  = data.get("src", ""); path = data.get("path", "")
            try:
                row = _aid().editMapping(fid, src, path)
                return jsonify({"ok": True, "row": row})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 400

        @app.route("/api/aid/mapping/<fid>", methods=["DELETE"])
        def aid_delete(fid):
            try:
                row = _aid().deleteMapping(fid)
                return jsonify({"ok": True, "row": row})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 400

        @app.route("/api/aid/custom", methods=["POST"])
        def aid_custom_create():
            data = request.get_json(silent=True) or {}
            fid  = data.get("fid", ""); src = data.get("src", "")
            note = data.get("note", "")
            try:
                row = _aid().addCustomMap(fid, src, note)
                return jsonify({"ok": True, "row": row})
            except NotImplementedError as err:
                return jsonify({"ok": False, "error": str(err), "todo": "M4"}), 501
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 400

        @app.route("/api/aid/custom/<fid>", methods=["DELETE"])
        def aid_custom_delete(fid):
            data = request.get_json(silent=True) or {}
            src  = data.get("src", "") or request.args.get("src", "")
            try:
                row = _aid().removeCustomMap(fid, src)
                return jsonify({"ok": True, "row": row})
            except NotImplementedError as err:
                return jsonify({"ok": False, "error": str(err), "todo": "M4"}), 501
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 400

        @app.route("/api/aid/custom/<fid>/relink", methods=["POST"])
        def aid_custom_relink(fid):
            data = request.get_json(silent=True) or {}
            src  = data.get("src", "")
            try:
                row = _aid().relinkCustomMap(fid, src)
                return jsonify({"ok": True, "row": row})
            except NotImplementedError as err:
                return jsonify({"ok": False, "error": str(err), "todo": "M4"}), 501
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 400

        @app.route("/api/aid/chk/<fid>/toggle", methods=["POST"])
        def aid_chk_toggle(fid):
            """Toggle ``Profile.<formKey>.chk[]`` membership for ``fid``.

            This is the third source layer (alongside bookNS and
            <form>_CustomMapDict) — see docs/LLC_BookToIRS_Aid.md and
            ui/llcBookToIRSAid.py::loadChkArray for the rationale."""
            try:
                row, action = _aid().toggleChkArray(fid)
                return jsonify({"ok": True, "row": row, "action": action})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 400

        @app.route("/api/aid/literal", methods=["POST"])
        def aid_literal_save():
            """Save a user-defined named literal: {src, path, value}.

            Upserts ``["path", "value"]`` into the ``BookVal`` section of
            ``bookNS_{src}.json``.  The resolver then exposes the value via
            the UAS path ``{src}.BookVal.{path}``, e.g. ``IS.BookVal.full_address``.
            Returns the updated BookVal list for the source.
            """
            try:
                body  = request.get_json(force=True) or {}
                src   = (body.get("src") or "").strip()
                path  = (body.get("path") or "").strip()  # may include src. prefix
                value = body.get("value", "")
                if not src or not path:
                    return jsonify({"ok": False, "error": "src and path are required"}), 400
                # Normalise: strip leading "{src}.BookVal." or "{src}." prefix if the
                # caller sent the full UAS path (e.g. "IS.BookVal.full_address" → "full_address").
                # Priority: check the longer BookVal prefix first so we don't leave
                # "BookVal.full_address" as the suffix.
                bkv_pfx = src + ".BookVal."
                src_pfx = src + "."
                if path.startswith(bkv_pfx):
                    suffix = path[len(bkv_pfx):]
                elif path.startswith(src_pfx):
                    suffix = path[len(src_pfx):]
                else:
                    suffix = path
                if not suffix:
                    return jsonify({"ok": False, "error": "path suffix must not be empty"}), 400
                aid = _aid()
                aid.saveLiteral(src, suffix, str(value))
                return jsonify({"ok": True, "src": src, "suffix": suffix,
                                "value": value, "literals": aid.loadLiterals(src)})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        @app.route("/api/aid/literal", methods=["DELETE"])
        def aid_literal_delete():
            """Delete a named literal from the BookVal section of bookNS_{src}.json.

            Body: {src, key}  where key is the bare path segment (e.g. "full_address").
            Also accepts key as the full UAS path (e.g. "IS.BookVal.full_address") and
            strips the prefix automatically.
            Returns {ok, src, key, found, literals}.
            """
            try:
                body = request.get_json(force=True) or {}
                src  = (body.get("src") or "").strip()
                key  = (body.get("key") or "").strip()
                if not src or not key:
                    return jsonify({"ok": False, "error": "src and key are required"}), 400
                # Normalise: strip any UAS prefix the caller may have included.
                bkv_pfx = src + ".BookVal."
                src_pfx = src + "."
                if key.startswith(bkv_pfx):
                    key = key[len(bkv_pfx):]
                elif key.startswith(src_pfx):
                    key = key[len(src_pfx):]
                if not key:
                    return jsonify({"ok": False, "error": "key must not be empty"}), 400
                aid   = _aid()
                found = aid.deleteLiteral(src, key)
                return jsonify({"ok": True, "src": src, "key": key,
                                "found": found, "literals": aid.loadLiterals(src)})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        @app.route("/api/aid/verify_field", methods=["POST"])
        def aid_verify_field():
            """Pre-commit sanity check: build the merged filldict and confirm
            that the requested fid resolves to a non-blank value.

            Body: {fid, expected_value (optional)}

            Returns:
              {ok, fid, resolved_value, status, sources_checked,
               error (if blank or mismatch)}
            """
            try:
                body     = request.get_json(force=True) or {}
                fid_raw  = (body.get("fid") or "").strip()
                expected = body.get("expected_value")   # None means "any non-blank"
                if not fid_raw:
                    return jsonify({"ok": False, "error": "fid is required"}), 400

                aid  = _aid()
                fid  = aid._normalizeFid(fid_raw)
                sources_detail = []

                for src in ("Profile", "BS", "IS", "GL"):
                    stmt = aid._stmtInstance(src)
                    if stmt is None:
                        continue
                    try:
                        d = stmt.loadFillDict(aid.formNm) or {}
                        v = d.get(fid)
                        sources_detail.append({
                            "src":   src,
                            "value": str(v) if v is not None else None,
                        })
                    except Exception as e:
                        sources_detail.append({"src": src, "value": None, "error": str(e)})

                # Find the first non-blank value (priority order).
                resolved = None
                for s in sources_detail:
                    v = s.get("value")
                    if v is not None and v != "":
                        resolved = v
                        break

                if resolved is None:
                    return jsonify({
                        "ok":              False,
                        "fid":             fid,
                        "resolved_value":  None,
                        "status":          "blank",
                        "sources_checked": sources_detail,
                        "error": (
                            f"Field {fid} is still blank after saving. "
                            "The mapping or literal may not have been written correctly. "
                            "Check bookNS_IS.json → Form mapping and BookVal sections."
                        ),
                    }), 200   # HTTP 200 so aidDone can read the body; ok=False signals failure

                if expected is not None and str(resolved) != str(expected):
                    return jsonify({
                        "ok":              False,
                        "fid":             fid,
                        "resolved_value":  resolved,
                        "status":          "mismatch",
                        "sources_checked": sources_detail,
                        "error": (
                            f"Field {fid} resolved to \"{resolved}\" "
                            f"but expected \"{expected}\". "
                            "Regeneration aborted — check the mapping."
                        ),
                    }), 200

                return jsonify({
                    "ok":              True,
                    "fid":             fid,
                    "resolved_value":  resolved,
                    "status":          "filled",
                    "sources_checked": sources_detail,
                })
            except HTTPException:
                raise
            except Exception as err:
                import traceback
                return jsonify({
                    "ok":        False,
                    "error":     str(err),
                    "traceback": traceback.format_exc(),
                }), 500

        @app.route("/api/aid/regenerate", methods=["POST"])
        def aid_regenerate():
            try:
                summary = _aid().regenerate()
                return jsonify({"ok": True, **summary})
            except HTTPException:
                raise
            except Exception as err:
                import traceback
                return jsonify({
                    "ok":        False,
                    "error":     str(err),
                    "traceback": traceback.format_exc(),
                }), 500

        @app.route("/api/aid/cpa_review")
        def aid_cpa_review():
            '''Return CPA review data for the current form.
            Returns _PART_NOTES (part summaries), _DEPR_RECONCILIATION, and _CPA_NOTES fields.'''
            try:
                form_nm = _aid_form_from_request()
                import importlib
                try:
                    mod = importlib.import_module(f"irs.{form_nm}")
                    form_cls = getattr(mod, form_nm, None)
                    _llc = getattr(self.eSession, "llc", None)
                    form_inst = form_cls(_llc) if (form_cls and _llc) else None
                    cpa_notes  = getattr(form_inst or form_cls, "_CPA_NOTES", {}) if (form_inst or form_cls) else {}
                    part_notes = (form_inst.part_notes()
                                  if form_inst and callable(getattr(form_inst, 'part_notes', None))
                                  else getattr(form_cls, "_PART_NOTES", []) if form_cls else [])
                    depr_notes = (form_inst.depr_reconciliation()
                                  if form_inst and callable(getattr(form_inst, 'depr_reconciliation', None))
                                  else getattr(form_cls, "_DEPR_RECONCILIATION", {}) if form_cls else {})
                except Exception:
                    cpa_notes  = {}
                    part_notes = []
                    depr_notes = {}

                aid = _aid()
                ns  = aid.loadNamespace()

                fields = []
                for lk, note in cpa_notes.items():
                    fid_match = None
                    for fid_key, fmeta in ns.items():
                        if fmeta.get("logicalKey") == lk:
                            fid_match = fid_key
                            break
                    fields.append({
                        "logicalKey": lk,
                        "fid":        fid_match,
                        "note":       note,
                        "location":   ns.get(fid_match, {}).get("location", "") if fid_match else "",
                        "label":      ns.get(fid_match, {}).get("label", lk) if fid_match else lk,
                    })
                return jsonify({
                    "ok":         True,
                    "formNm":     form_nm,
                    "parts":      part_notes,
                    "depr_notes": depr_notes,
                    "fields":     fields,
                })
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        # ── BookToIRS Diagnostic (IRSDiagAgent) ───────────────────────────────

        # form_key → canonical AID form name (handles lowercase agent route keys)
        _FORM_KEY_MAP = {
            "form1065": "Form1065", "form8825": "Form8825",
            "form4562": "Form4562", "schk1":    "Sch_K1",
            "sch_k1":   "Sch_K1",
        }

        @app.route("/api/aid/diagnose")
        def aid_diagnose():
            """Return IRSDiagAgent.diagnose() as JSON for the current form.
            Accepts both canonical (Form4562) and agent-route (form4562) keys."""
            try:
                raw = (request.args.get("formNm") or "").strip()
                form_nm = _FORM_KEY_MAP.get(raw.lower(), raw) or "Form1065"
                if form_nm not in AID_FORMS:
                    return jsonify({"ok": False,
                                    "error": f"Unknown form: {raw!r}"}), 400
                _llc = getattr(self.eSession, "llc", None)
                if _llc is None:
                    return jsonify({"ok": False, "error": "no LLC session"}), 400
                from irs.taxAgents.irsDiagAgent import IRSDiagAgent
                show_all    = request.args.get("showAll", "0") in ("1", "true", "True")
                partner_raw = request.args.get("member", "0")
                # Resolve member: accept oID string or numeric index
                try:
                    partner_idx = int(partner_raw)
                except (ValueError, TypeError):
                    # oID string — find index in llc.owners
                    partner_idx = 0
                    try:
                        raw_owners = _llc.owners
                        owners = raw_owners() if callable(raw_owners) else list(raw_owners or [])
                        for i, o in enumerate(owners):
                            if o.get('oID') == partner_raw:
                                partner_idx = i
                                break
                    except Exception:
                        pass
                data = IRSDiagAgent(_llc, form_nm).diagnose(
                    show_all=show_all, partner_idx=partner_idx)
                return jsonify({"ok": True, **data})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        @app.route("/api/aid/verify_section", methods=["POST"])
        def aid_verify_section():
            """Mark a section VERIFIED in FormXXXX_diagnose_state.json.

            POST body: { "form": "Form4562", "section_id": "Header" }
            Returns: { "ok": true, "section_id": ..., "verified_at": ...,
                       "regressions": [...] }
            """
            try:
                body      = request.get_json(force=True) or {}
                raw_form  = (body.get("form") or "").strip()
                section_id = (body.get("section_id") or "").strip()
                form_nm   = _FORM_KEY_MAP.get(raw_form.lower(), raw_form) or raw_form
                if form_nm not in AID_FORMS:
                    return jsonify({"ok": False,
                                    "error": f"Unknown form: {raw_form!r}"}), 400
                if not section_id:
                    return jsonify({"ok": False, "error": "section_id required"}), 400
                _llc = getattr(self.eSession, "llc", None)
                if _llc is None:
                    return jsonify({"ok": False, "error": "no LLC session"}), 400

                from irs import formDiagState as _fds
                from pathlib import Path

                # Resolve forms_dir (same logic as _save_diagnose_state)
                aid     = _aid()
                stmt_is = aid._stmtInstance("IS")
                if stmt_is and hasattr(stmt_is, "_bkNS_path"):
                    forms_dir = Path(stmt_is._bkNS_path()).parent
                else:
                    from irs.irsForm import irsForm
                    forms_dir = Path(irsForm(llc=_llc).irsDir)

                llc_repo = _fds.get_llc_repo_dir(_llc)
                bus_repo = _fds.get_bus_repo_dir(forms_dir)
                llc_sha  = _fds._git_sha(llc_repo) if llc_repo else "unknown"
                bus_sha  = _fds._git_sha(bus_repo)  if bus_repo else "unknown"

                state = _fds.verify_section(
                    section_id, form_nm, forms_dir, llc_sha, bus_sha)
                sec   = state["sections"].get(section_id, {})
                return jsonify({
                    "ok":           True,
                    "section_id":   section_id,
                    "verified_at":  sec.get("verified_at"),
                    "regressions":  state.get("regressions", []),
                })
            except KeyError as err:
                return jsonify({"ok": False, "error": str(err)}), 404
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        @app.route("/api/aid/diagnose_state")
        def aid_diagnose_state():
            """Return the persisted FormXXXX_diagnose_state.json for a form.

            Query param: formNm (e.g. Form4562 or form4562)
            """
            try:
                raw     = (request.args.get("formNm") or "").strip()
                form_nm = _FORM_KEY_MAP.get(raw.lower(), raw) or "Form1065"
                if form_nm not in AID_FORMS:
                    return jsonify({"ok": False,
                                    "error": f"Unknown form: {raw!r}"}), 400
                _llc = getattr(self.eSession, "llc", None)
                if _llc is None:
                    return jsonify({"ok": False, "error": "no LLC session"}), 400

                from irs import formDiagState as _fds
                from pathlib import Path

                aid     = _aid()
                stmt_is = aid._stmtInstance("IS")
                if stmt_is and hasattr(stmt_is, "_bkNS_path"):
                    forms_dir = Path(stmt_is._bkNS_path()).parent
                else:
                    return jsonify({"ok": False, "error": "cannot resolve forms_dir"}), 500

                state = _fds.load(form_nm, forms_dir)
                return jsonify({"ok": True, "state": state,
                                "form": form_nm, "has_state": bool(state)})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        # ── Form 1065 Agent routes ─────────────────────────────────────────────
        # Pre-import at bind time so a missing file surfaces as a startup error,
        # not a silent 404.  Guarded so a missing taxAgents package degrades
        # gracefully (returns 503) rather than crashing the whole _bind_routes.
        try:
            from irs.taxAgents.Form1065Agent import Form1065Agent as _Form1065Agent
            app.logger.info("Form1065Agent loaded OK")
            _agent_import_err = None
        except Exception as _e:
            _Form1065Agent    = None
            _agent_import_err = str(_e)
            app.logger.error("Form1065Agent import FAILED: %s", _e)

        @app.route("/view/agent/form1065")
        def agent_form1065_view():
            """Guided Tax Review page — full per-section issue list."""
            if _Form1065Agent is None:
                return render_template("construction.html",
                                       obj_type="Form1065 Agent",
                                       meta={"error": _agent_import_err})
            try:
                agent   = _Form1065Agent(self.eSession.llc)
                summary = agent.getSummary()
                return render_template(
                    "agent_form1065_review.html",
                    summary=summary,
                    app_title=self.app.config.get("_llc_name", "LLC Editor"),
                    view_title="Form 1065 — Guided Tax Review",
                )
            except Exception as err:
                app.logger.exception("agent_form1065_view failed")
                return render_template("construction.html",
                                       obj_type="Form1065 Agent",
                                       meta={"error": str(err)})

        @app.route("/api/agent/form1065/status")
        def agent_form1065_get_summary():
            """Return per-section SectionSummary for the Form 1065 status strip."""
            if _Form1065Agent is None:
                return jsonify({'ok': False,
                                'error': f'Form1065Agent unavailable: {_agent_import_err}'}), 503
            try:
                agent = _Form1065Agent(self.eSession.llc)
                data  = agent.getSummary()
                app.logger.debug("agent/status ok — state=%s", data.get('overall_state'))
                return jsonify({'ok': True, 'summary': data})
            except Exception as err:
                app.logger.exception("agent/status failed")
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/api/agent/form1065/start", methods=["POST"])
        def agent_form1065_start():
            """Run Pass 1 + Pass 2 for all section agents; write session state."""
            if _Form1065Agent is None:
                return jsonify({'ok': False,
                                'error': f'Form1065Agent unavailable: {_agent_import_err}'}), 503
            try:
                agent  = _Form1065Agent(self.eSession.llc)
                app.logger.info("agent/start — running Passes 1+2")
                result = agent.run_phases_1_2()
                summary = agent._normalize_summary(result)
                app.logger.info("agent/start done — state=%s", summary.get('overall_state'))
                return jsonify({'ok': True, 'summary': summary})
            except Exception as err:
                app.logger.exception("agent/start failed")
                return jsonify({'ok': False, 'error': str(err)}), 500

        # ── Generic Form Agent routes (Form8825, Form4562, SchK1) ─────────────
        # Route pattern: /view/agent/<form_key>  and  /api/agent/<form_key>/status|start
        # form_key values: 'form8825', 'form4562', 'schk1'
        # Form1065 keeps its own named routes (backward compat); these handle the rest.
        #
        # SchK1 per-member: all routes accept ?member=oID.
        # Without ?member the agent falls back to all-partners aggregate (for LLCTaxAgent).

        _AGENT_REGISTRY = {}
        try:
            from irs.taxAgents.Form8825Agent  import Form8825Agent  as _F8825Agent
            from irs.taxAgents.Form4562Agent  import Form4562Agent  as _F4562Agent
            from irs.taxAgents.FormSchK1Agent import FormSchK1Agent as _FSchK1Agent
            _AGENT_REGISTRY = {
                'form8825': (_F8825Agent,  'Form 8825 — Rental Real Estate',    'llcForm8825'),
                'form4562': (_F4562Agent,  'Form 4562 — Depreciation',          'llcForm4562'),
                'schk1':    (_FSchK1Agent, 'Schedule K-1 — Partners\' Share',   'llcFormK1'),
            }
            app.logger.info("Generic form agents loaded: %s", list(_AGENT_REGISTRY.keys()))
        except Exception as _ae:
            app.logger.error("Generic form agent import failed: %s", _ae)

        def _make_agent(AgentCls, form_key: str, member: str = ""):
            """Instantiate agent; for schk1 pass oID when a member is selected."""
            if form_key == 'schk1' and member:
                return AgentCls(self.eSession.llc, oID=member)
            return AgentCls(self.eSession.llc)

        def _res_key(form_key: str, member: str = "") -> str:
            """Resolution file key — per-member for schk1."""
            return f"{form_key}_{member}" if (form_key == 'schk1' and member) else form_key

        @app.route("/view/agent/<form_key>")
        def agent_generic_view(form_key):
            """Guided Tax Review page for Form8825, Form4562, or SchK1."""
            entry = _AGENT_REGISTRY.get(form_key)
            if not entry:
                return render_template("construction.html",
                                       obj_type=f"{form_key} Agent",
                                       meta={"error": f"Unknown form key: {form_key}"})
            AgentCls, form_label, back_obj = entry

            # SchK1: ?member=oID required — redirect to home if missing
            member = request.args.get("member", "").strip()
            if form_key == 'schk1' and not member:
                return redirect(url_for("home"))

            try:
                agent   = _make_agent(AgentCls, form_key, member)
                summary = agent.getSummary()
                rkey    = _res_key(form_key, member)
                summary = _apply_resolutions(agent, rkey, summary)

                # Build member-aware label and back URL
                if form_key == 'schk1' and member:
                    nm         = summary.get('partner_name', member)
                    view_title = f"Schedule K-1 — {nm} — Guided Tax Review"
                    back_url   = url_for("view_object", obj_type=back_obj) + f"?member={member}"
                else:
                    view_title = f"{form_label} — Guided Tax Review"
                    back_url   = url_for("view_object", obj_type=back_obj)

                return render_template(
                    "agent_generic_review.html",
                    summary=summary,
                    form_key=form_key,
                    form_label=form_label,
                    back_obj=back_obj,
                    back_url=back_url,
                    member=member,
                    app_title=self.app.config.get("_llc_name", "LLC Editor"),
                    view_title=view_title,
                )
            except Exception as err:
                app.logger.exception("agent_generic_view(%s) failed", form_key)
                return render_template("construction.html",
                                       obj_type=f"{form_key} Agent",
                                       meta={"error": str(err)})

        def _normalize_agent_sections(d: dict) -> dict:
            """Flatten sections dict into list for the UI status strip."""
            if isinstance(d.get('sections'), list):
                return d
            d   = dict(d)
            raw = d.get('sections') or {}
            if isinstance(raw, dict):
                d['sections'] = [
                    {'agent': k, 'label': v.get('label', k),
                     'state': v.get('state', 'NOT_STARTED'),
                     'summary': v.get('summary', ''),
                     'halt_count': v.get('halt_count', 0),
                     'resolve_count': v.get('resolve_count', 0),
                     'review_count': v.get('review_count', 0)}
                    for k, v in raw.items()
                ]
            return d

        # ── Issue resolution overlay ────────────────────────────────────────────
        # Bookkeepers close issues directly from the Guided Review WITHOUT the Aid
        # dialog (acknowledge / override / reopen).  Resolutions persist in
        # .agent_work/<res_key>_resolutions.json and overlay onto the agent's
        # session state on every read — so they survive agent re-runs.
        # SchK1 uses res_key = schk1_{oID} to keep per-member resolutions separate.

        def _resolutions_file(agent, res_key):
            try:
                d = agent._agent_work_dir()
            except Exception:
                d = None
            return (Path(d) / f"{res_key}_resolutions.json") if d else None

        def _load_resolutions(agent, res_key):
            p = _resolutions_file(agent, res_key)
            if not p or not p.exists():
                return {}
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                return {}

        def _save_resolutions(agent, res_key, data):
            p = _resolutions_file(agent, res_key)
            if not p:
                return
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, 'w') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                app.logger.exception("save resolutions failed (%s)", res_key)

        def _apply_resolutions(agent, res_key, summary):
            """Overlay resolutions onto a summary; recompute counts + states."""
            if not isinstance(summary, dict):
                return summary
            res  = _load_resolutions(agent, res_key)
            secs = summary.get('sections')
            overall_halt = 0

            def _process(sec_key, sec):
                h = r = v = 0
                for issue in (sec.get('issues') or []):
                    rid = issue.get('rule_id', '')
                    key = f"{sec_key}::{rid}"
                    if key in res:
                        issue['resolved']   = True
                        issue['resolution'] = res[key]
                        continue
                    issue['resolved'] = False
                    sev = issue.get('severity')
                    if sev == 'ERROR':
                        h += 1
                    elif sev == 'WARN':
                        r += 1
                    else:
                        v += 1
                sec['halt_count']    = h
                sec['resolve_count'] = r
                sec['review_count']  = v
                if h == 0 and sec.get('state') == 'NEEDS_FIXING':
                    sec['state'] = 'GO'
                return h

            if isinstance(secs, dict):
                for k, sec in secs.items():
                    sec['agent'] = k
                    overall_halt += _process(k, sec)
            elif isinstance(secs, list):
                for sec in secs:
                    k = sec.get('agent') or sec.get('label') or ''
                    overall_halt += _process(k, sec)
            summary['overall_state'] = 'NEEDS_FIXING' if overall_halt > 0 else 'GO'
            return summary

        @app.route("/api/agent/<form_key>/status")
        def agent_generic_status(form_key):
            """Return SectionSummary for the agent status strip."""
            entry = _AGENT_REGISTRY.get(form_key)
            if not entry:
                return jsonify({'ok': False, 'error': f'Unknown form key: {form_key}'}), 404
            AgentCls, _, _ = entry
            member = request.args.get("member", "").strip()
            try:
                agent   = _make_agent(AgentCls, form_key, member)
                rkey    = _res_key(form_key, member)
                summary = _normalize_agent_sections(
                    _apply_resolutions(agent, rkey, agent.getSummary()))
                return jsonify({'ok': True, 'summary': summary})
            except Exception as err:
                app.logger.exception("agent_generic_status(%s) failed", form_key)
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/api/agent/<form_key>/start", methods=["POST"])
        def agent_generic_start(form_key):
            """Run Passes 1+2 for all section agents; write session state."""
            entry = _AGENT_REGISTRY.get(form_key)
            if not entry:
                return jsonify({'ok': False, 'error': f'Unknown form key: {form_key}'}), 404
            AgentCls, _, _ = entry
            member = request.args.get("member", "").strip()
            try:
                agent  = _make_agent(AgentCls, form_key, member)
                rkey   = _res_key(form_key, member)
                result = _normalize_agent_sections(
                    _apply_resolutions(agent, rkey, agent.run_phases_1_2()))
                return jsonify({'ok': True, 'summary': result})
            except Exception as err:
                app.logger.exception("agent_generic_start(%s) failed", form_key)
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/api/agent/<form_key>/resolve", methods=["POST"])
        def agent_generic_resolve(form_key):
            """Close (or reopen) one issue from the Guided Review — no Aid needed."""
            entry = _AGENT_REGISTRY.get(form_key)
            if not entry:
                return jsonify({'ok': False, 'error': f'Unknown form key: {form_key}'}), 404
            AgentCls, _, _ = entry
            member  = request.args.get("member", "").strip()
            body    = request.get_json(silent=True) or {}
            section = str(body.get('section', '') or '')
            rule_id = str(body.get('rule_id', '') or '')
            action  = str(body.get('action', 'acknowledge') or 'acknowledge')
            note    = str(body.get('note', '') or '')
            if not rule_id:
                return jsonify({'ok': False, 'error': 'rule_id required'}), 400
            try:
                from datetime import datetime, timezone
                agent = _make_agent(AgentCls, form_key, member)
                rkey  = _res_key(form_key, member)
                res   = _load_resolutions(agent, rkey)
                key   = f"{section}::{rule_id}"
                if action == 'reopen':
                    res.pop(key, None)
                else:
                    res[key] = {
                        'action': action,
                        'note':   note,
                        'ts':     datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    }
                _save_resolutions(agent, rkey, res)
                summary = _normalize_agent_sections(
                    _apply_resolutions(agent, rkey, agent.getSummary()))
                return jsonify({'ok': True, 'summary': summary})
            except Exception as err:
                app.logger.exception("agent_generic_resolve(%s) failed", form_key)
                return jsonify({'ok': False, 'error': str(err)}), 500

        # ── GL Audit routes ────────────────────────────────────────────────────

        @app.route("/api/debug/sources")
        def debug_sources():
            '''Show exact file paths and record counts read by the GL engine.'''
            import json as _json
            from pathlib import Path as _Path
            info = {}
            for src in ('llcAssets', 'llcExpRev', 'llcPayables', 'llcReceivables'):
                wk = self.eSession.oDict.get(src)
                if wk is None:
                    info[src] = {'error': 'not in eSession.oDict'}
                    continue
                real_fn   = wk.o.FN()
                temp_fn   = wk.FN()
                real_path = _Path(real_fn)
                temp_path = _Path(temp_fn)
                real_count = None
                if real_path.exists():
                    try:
                        real_count = len(_json.loads(real_path.read_text()))
                    except Exception as e:
                        real_count = f'parse error: {e}'
                info[src] = {
                    'real_path':   real_fn,
                    'real_exists': real_path.exists(),
                    'real_count':  real_count,
                    'temp_path':   temp_fn,
                    'temp_exists': temp_path.exists(),
                }
            return jsonify({'ok': True, 'sources': info,
                            'llc_top': str(self.eSession.llc.TOP),
                            'acct_dir': self.eSession.llc.acctDir()})

        @app.route("/api/debug/tax_trace")
        def debug_tax_trace():
            """Trace the full Tax Prep fill pipeline for a form.

            Query param: ?form=Form4562  (default Form4562)
            Returns every step: paths, bookNS contents, fill dict per source,
            merge result, namespace field count, and PDF output path.
            Use from the PA browser to diagnose empty FILL.pdf issues.
            """
            import json as _j
            from pathlib import Path as _Path
            from irs.BookToIRS import BookToIRS, AID_SOURCES

            form_nm = request.args.get("form", "Form4562")
            llc     = self.eSession.llc
            aid     = BookToIRS(llc, form_nm)
            out     = {"form": form_nm, "steps": {}}

            # ── Step 1: setup_paths globals ─────────────────────────────
            try:
                from ledger import setup_paths as _sp
                out["steps"]["1_setup_paths"] = {
                    "TOP":           str(_sp.TOP),
                    "ACCTS_DIR":     str(_sp.ACCTS_DIR),
                    "IRS_FORMS_DIR": str(_sp.IRS_FORMS_DIR),
                    "YEAR":          _sp.YEAR,
                    "BOOKS_DIR":     _sp.BOOKS_DIR,
                }
            except Exception as e:
                out["steps"]["1_setup_paths"] = {"error": str(e)}

            # ── Step 2: bookNS files ─────────────────────────────────────
            bkns = {}
            for src in AID_SOURCES:
                p = aid._bookNSPath(src)
                exists = p.exists() if p else False
                entries = []
                if exists:
                    try:
                        d = _j.loads(p.read_text())
                        entries = d.get(form_nm, [])
                    except Exception as e:
                        entries = [f"parse error: {e}"]
                bkns[src] = {"path": str(p), "exists": exists,
                             "form_entries": len(entries),
                             "entries": entries[:10]}
            out["steps"]["2_bookNS_files"] = bkns

            # ── Step 3: fill dict per source ─────────────────────────────
            fill_by_src = {}
            for src in AID_SOURCES:
                stmt = aid._stmtInstance(src)
                if stmt is None:
                    fill_by_src[src] = {"error": "no stmt instance"}
                    continue
                try:
                    d = stmt.loadFillDict(form_nm) or {}
                    fill_by_src[src] = {
                        "count":  len(d),
                        "filled": {k: str(v) for k, v in d.items()
                                   if v is not None and v != ""},
                    }
                except Exception as e:
                    fill_by_src[src] = {"error": str(e)}
            out["steps"]["3_fill_dicts"] = fill_by_src

            # ── Step 4: namespace + merge ────────────────────────────────
            try:
                import pandas as _pd
                formClass = aid._formClass()
                form      = formClass(llc=llc)
                df_fields = form.loadFieldsDF()
                ns_path   = getattr(form, "irsDir", None)
                ns_file   = _Path(str(ns_path)) / f"{form_nm}_namespace.json" if ns_path else None

                # Collect all fill entries across sources
                all_rows = []
                for _src, _d in [
                    ("Profile", aid._stmtInstance("Profile")),
                    ("BS",      aid._stmtInstance("BS")),
                    ("IS",      aid._stmtInstance("IS")),
                    ("GL",      aid._stmtInstance("GL")),
                ]:
                    if _d is None: continue
                    try:
                        for _fid, _fval in (_d.loadFillDict(form_nm) or {}).items():
                            all_rows.append({"fid": _fid, "fval": _fval, "source": _src})
                    except Exception: pass
                df_book = _pd.DataFrame(all_rows, columns=["fid","fval","source"]) \
                          if all_rows else _pd.DataFrame(columns=["fid","fval","source"])

                # Intersection diagnostic
                ns_fids   = set(df_fields["fid"].tolist()) if len(df_fields) else set()
                book_fids = set(df_book["fid"].tolist())   if len(df_book)   else set()
                matched   = ns_fids & book_fids

                out["steps"]["4_namespace"] = {
                    "irsDir":         str(ns_path) if ns_path else None,
                    "ns_file":        str(ns_file) if ns_file else None,
                    "ns_file_exists": ns_file.exists() if ns_file else False,
                    "field_count":    len(df_fields),
                    # Fid format samples — show first 8 from each side so we can see format
                    "ns_fid_sample":   sorted(ns_fids)[:8],
                    "book_fid_sample": sorted(book_fids)[:8],
                    "matched_fids":    sorted(matched),
                    "match_count":     len(matched),
                    "ns_fid_dtype":    str(df_fields["fid"].dtype) if len(df_fields) else "empty",
                    "book_fid_dtype":  str(df_book["fid"].dtype)   if len(df_book)   else "empty",
                    # Show actual filled-fid rows from bookNS so we can compare with namespace
                    "book_filled_rows": [
                        {"fid": r["fid"], "fval": str(r["fval"]), "src": r["source"]}
                        for r in all_rows if r.get("fval") not in (None, "", "0", 0)
                    ][:15],
                }
            except Exception as e:
                import traceback as _tb2
                out["steps"]["4_namespace"] = {"error": str(e), "traceback": _tb2.format_exc()}

            # ── Step 4a: data-path diagnostic (shows which ACCTS files + key balances) ──
            try:
                import os as _os4a, json as _j4a
                from ledger import setup_paths as _sp4a
                llc_name = getattr(llc, 'objName', 'WBGroupLLC')
                _data_diag = {
                    "llc_TOP":           str(getattr(llc, 'TOP', '?')),
                    "sp_TOP":            str(_sp4a.TOP),
                    "sp_ACCTS_DIR":      str(_sp4a.ACCTS_DIR),
                    "llc_acctDir":       str(llc.acctDir()),
                    "tops_match":        str(getattr(llc, 'TOP', '?')) == str(_sp4a.TOP),
                }
                for _nm in ('llcExpRev', 'llcAssets'):
                    for _base in (str(_sp4a.ACCTS_DIR), str(getattr(llc, 'TOP', '')) + '/books/Accts'):
                        _fp = _os4a.path.join(_base, f"{_nm}_{llc_name}.json")
                        if _os4a.path.exists(_fp):
                            try:
                                _d = _j4a.loads(open(_fp).read())
                                _entries = _d if isinstance(_d, list) else _d.get('entries', [])
                                _depr = [e for e in _entries if 'Depreciation' in str(e.get('acct',''))]
                                _tang = [e for e in _entries if 'Tangible.InService' in str(e.get('acct',''))]
                                _data_diag[f"{_nm}_via_{_base[-5:]}"] = {
                                    "path": _fp, "total": len(_entries),
                                    "depr_entries": len(_depr), "tang_entries": len(_tang),
                                }
                            except Exception as _ex:
                                _data_diag[f"{_nm}_via_{_base[-5:]}"] = {"error": str(_ex)}
                            break
                out["steps"]["4a_data_paths"] = _data_diag
            except Exception as e:
                import traceback as _tb4a
                out["steps"]["4a_data_paths"] = {"error": str(e), "traceback": _tb4a.format_exc()}

            # ── Step 4b: post-refresh fill check (isolates _refreshStmtInstances bug) ──
            try:
                import os as _os4b
                aid._refreshStmtInstances()   # mirrors what regenerate() does first
                post_refresh = {}
                for _src in ["Profile", "BS", "IS", "GL"]:
                    _d = aid._stmtInstance(_src)
                    if _d is None:
                        post_refresh[_src] = {"error": "no stmt instance after refresh"}
                        continue
                    bkns_p = _d._bkNS_path() if hasattr(_d, '_bkNS_path') else None
                    try:
                        _fd = _d.loadFillDict(form_nm) or {}
                        post_refresh[_src] = {
                            "count":     len(_fd),
                            "bkNS_path": bkns_p,
                            "bkNS_exists": _os4b.path.exists(bkns_p) if bkns_p else False,
                            "filled": {k: str(v) for k, v in _fd.items()
                                       if v is not None and v != ""},
                        }
                    except Exception as _ex:
                        post_refresh[_src] = {"error": str(_ex), "bkNS_path": bkns_p}
                out["steps"]["4b_post_refresh"] = post_refresh
            except Exception as e:
                import traceback as _tb3
                out["steps"]["4b_post_refresh"] = {"error": str(e), "traceback": _tb3.format_exc()}

            # ── Step 5: full regenerate ──────────────────────────────────
            try:
                result = aid.regenerate()
                out["steps"]["5_regenerate"] = result
            except Exception as e:
                import traceback as _tb
                out["steps"]["5_regenerate"] = {
                    "error": str(e),
                    "traceback": _tb.format_exc()
                }

            return jsonify({"ok": True, **out})

        @app.route("/api/audit/gl")
        def audit_gl():
            '''Run all GL audit checks and return structured findings + equation breakdown.'''
            try:
                from ledger.auditor import GLAuditor
                from ui.llcReportEngine import llcReportEngine
                llc        = self.eSession.llc
                engine     = llcReportEngine(self.eSession)
                gl_records = engine.getGLList(resolve_dups=True, force=True)
                auditor    = GLAuditor(llc, gl_records)
                result     = auditor.audit()
                result['equation'] = auditor.equation_summary()
                return jsonify({"ok": True, **result})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        @app.route("/api/audit/apply", methods=["POST"])
        def audit_apply():
            '''Apply operator-approved auto-applicable corrections.'''
            try:
                from ledger.auditor import GLAuditor
                from ui.llcReportEngine import llcReportEngine
                data        = request.get_json(force=True) or {}
                corrections = data.get("corrections", [])
                llc         = self.eSession.llc
                engine      = llcReportEngine(self.eSession)
                gl_records  = engine.getGLList(resolve_dups=True, force=True)
                result      = GLAuditor(llc, gl_records).apply_corrections(corrections)
                return jsonify({"ok": True, **result})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        # ── YE Financial Report ────────────────────────────────────────────────

        @app.route("/api/stmtGeneralLedger/ye_report")
        def ye_financial_report():
            '''Generate YE Financial Report PDF → books/{year}/Forms/'''
            try:
                from ledger.yeFinancialReport import YEFinancialReportAgent
                agent   = YEFinancialReportAgent(self.eSession)
                out     = agent.generate()
                rel     = str(out).replace(str(self.eSession.llc.TOP), '').lstrip('/')
                return jsonify({"ok": True, "path": str(out), "rel": rel,
                                "filename": out.name})
            except HTTPException:
                raise
            except Exception as err:
                import traceback
                return jsonify({"ok": False, "error": str(err),
                                "trace": traceback.format_exc()}), 500

        @app.route("/api/stmtGeneralLedger/ye_report/view")
        def ye_report_view():
            '''Inline-display the last-generated YE Financial Report PDF (for iframe embed).'''
            try:
                from ledger import setup_paths
                data_nm = getattr(self.eSession.llc, 'objName', 'LLC')
                yr      = getattr(self.eSession.llc, 'yr', '')
                out     = (setup_paths.IRS_FORMS_DIR /
                           f'{data_nm}_{yr}_YEFinancialReport.pdf')
                if not out.exists():
                    return jsonify({"error": "Report not found — generate it first."}), 404
                return send_file(str(out), as_attachment=False, mimetype='application/pdf')
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"error": str(err)}), 500

        @app.route("/api/stmtGeneralLedger/ye_report/download")
        def ye_report_download():
            '''Stream the last-generated YE Financial Report PDF as a download.'''
            try:
                from ledger.yeFinancialReport import YEFinancialReportAgent
                from ledger import setup_paths
                data_nm = getattr(self.eSession.llc, 'objName', 'LLC')
                yr      = getattr(self.eSession.llc, 'yr', '')
                out     = (setup_paths.IRS_FORMS_DIR /
                           f'{data_nm}_{yr}_YEFinancialReport.pdf')
                if not out.exists():
                    return jsonify({"error": "Report not found — generate it first."}), 404
                return send_file(str(out), as_attachment=True,
                                 download_name=out.name,
                                 mimetype='application/pdf')
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"error": str(err)}), 500

        # ── Balance Sheet Audit ────────────────────────────────────────────────

        @app.route("/api/stmtBalanceSheet/audit")
        def bs_audit():
            '''Forensic BS audit: equation analysis + full GL audit via GLAuditor.'''
            try:
                from ui.llcReportEngine import llcReportEngine as _RE
                from ledger.auditor     import GLAuditor      as _Aud

                engine     = _RE(self.eSession)
                gl_records = engine.getGLList(resolve_dups=True, force=True)
                auditor    = _Aud(self.eSession.llc, gl_records)

                # ── Equation summary ──────────────────────────────────────────
                eq      = auditor.equation_summary()
                assets  = eq['assets']
                liabs   = eq['liabilities']
                equity  = eq['equity']
                ni      = eq['net_income']
                le_gap  = eq['le_gap']              # A − (L+E), signed D-C convention

                open_gap     = round(assets - (liabs + equity + ni), 2)
                open_balanced = abs(open_gap) < 0.01
                gap_is_ni    = abs(le_gap - ni) < 0.01   # BS gap explained by NI

                # ── Verdict ───────────────────────────────────────────────────
                if abs(le_gap) < 0.01:
                    verdict = 'balanced'
                    summary = 'Balance Sheet is fully balanced — Assets = Liabilities + Equity.'
                elif gap_is_ni and open_balanced:
                    verdict = 'open_period_ni'
                    direction = 'Net Loss' if ni < 0 else 'Net Income'
                    summary  = (
                        f"BS gap (${abs(le_gap):,.2f}) equals the period {direction}. "
                        f"This is expected in an open-period system: revenue/expense accounts "
                        f"remain open; the GL is balanced under A = L + E + NI. "
                        f"No corrective action needed — the books are correct."
                    )
                else:
                    verdict = 'error'
                    summary = (
                        f"BS gap (${abs(le_gap):,.2f}) is NOT explained by Net Income alone — "
                        f"there may be mis-classified accounts or missing double-entry. "
                        f"Review the issues below."
                    )

                # ── NI breakdown (income + expense accounts) ──────────────────
                ni_rows: dict = {}
                for r in gl_records:
                    at = r.get('acctType', '') or ''
                    if at not in ('Income', 'Expense'):
                        continue
                    acct = r.get('acct', '')
                    amt  = float(r.get('amt', 0) or 0)
                    atyp = (r.get('aType', '') or '').strip().lower()
                    if acct not in ni_rows:
                        ni_rows[acct] = {'acct': acct, 'acctType': at, 'balance': 0.0}
                    if at == 'Income':
                        ni_rows[acct]['balance'] += (amt if 'credit' in atyp else -amt)
                    else:
                        ni_rows[acct]['balance'] += (amt if 'debit' in atyp else -amt)
                ni_breakdown = sorted(
                    [{'acct': v['acct'], 'acctType': v['acctType'],
                      'balance': round(v['balance'], 2)} for v in ni_rows.values()],
                    key=lambda x: (x['acctType'], x['acct'])
                )

                # ── Full GL audit ─────────────────────────────────────────────
                full_audit  = auditor.audit()
                issues      = full_audit.get('issues', [])
                audit_sum   = full_audit.get('summary', {})

                return jsonify({
                    "ok": True,
                    "equation": {
                        "assets":        assets,
                        "liabilities":   liabs,
                        "equity":        equity,
                        "net_income":    ni,
                        "le_gap":        le_gap,
                        "open_balanced": open_balanced,
                        "open_gap":      open_gap,
                        "gap_is_ni":     gap_is_ni,
                    },
                    "verdict":      verdict,
                    "summary":      summary,
                    "ni_breakdown": ni_breakdown,
                    "issues":       issues,
                    "audit_summary": audit_sum,
                })
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        # ── YE Posting routes ──────────────────────────────────────────────────

        @app.route("/api/llcAssets/ye/preview")
        def ye_preview():
            '''Scan llcAssets for InService properties and return YE posting status.'''
            try:
                import datetime as _dt, json as _json
                from pathlib import Path as _Path

                mgr = self.objects.get('llcAssets')
                if mgr is None:
                    return jsonify({"ok": False, "error": "llcAssets not available"}), 500

                year  = getattr(getattr(self.eSession, 'llc', None), 'yr', None) \
                        or _dt.date.today().year
                ye_dt = f"{year}.12.31"

                # Read real file directly (bypasses in-memory llcAssets.df cache)
                wk_assets = self.eSession.oDict.get('llcAssets')
                real_fn   = _Path(wk_assets.o.FN()) if wk_assets else None
                records   = _json.loads(real_fn.read_text()) if real_fn and real_fn.exists() else []

                # ── Net Income from GL ──────────────────────────────────────
                from ui.llcReportEngine import llcReportEngine as _RE
                from ledger.auditor import GLAuditor as _Aud
                _engine    = _RE(self.eSession)
                _gl        = _engine.getGLList(resolve_dups=True, force=True)
                _eq        = _Aud(self.eSession.llc, _gl).equation_summary()
                net_income = _eq.get('net_income', 0.0)   # positive = profit, negative = loss

                # ── Owner lookup (oID → name) ───────────────────────────────
                owners_list = _engine.load_owners()
                def _normalize_oid(oid):
                    # propOwners stores "020250801_1" (digit zero); llcOwners stores
                    # "o20250801_1" (letter o).  Normalise both to the letter-o form.
                    s = str(oid)
                    if s and s[0] == '0' and len(s) > 1 and s[1].isdigit():
                        return 'o' + s[1:]
                    return s

                def _owner_name(oID):
                    norm = _normalize_oid(oID)
                    for o in owners_list:
                        if _normalize_oid(o.get('oID', '')) == norm:
                            nm = o.get('nm', [])
                            return ', '.join(nm) if isinstance(nm, list) else str(nm)
                    return oID

                def _parse_prop_owners(raw):
                    '''Return dict {oID: pct_int} handling both dict and JSON-string forms.'''
                    if isinstance(raw, dict):
                        return {k: float(v) for k, v in raw.items()}
                    if isinstance(raw, str):
                        try:
                            return {k: float(v) for k, v in _json.loads(raw).items()}
                        except Exception:
                            pass
                    return {}

                # ── Property groups ─────────────────────────────────────────
                DEPR_ACCT = 'Acct.Fixed.Tangible.InService'
                props = {}  # propNm → {cost_rows, all_rows}
                for r in records:
                    pnm = r.get('propNm') or 'Unknown'
                    if pnm not in props:
                        props[pnm] = {'cost_rows': [], 'all_rows': []}
                    props[pnm]['all_rows'].append(r)
                    acct = r.get('acct', '') or ''
                    if acct == DEPR_ACCT and not r.get('_is_depr'):
                        props[pnm]['cost_rows'].append(r)

                # Keep only properties that have InService cost rows
                props = {k: v for k, v in props.items() if v['cost_rows']}

                # ── Existing YE depr per propNm ─────────────────────────────
                existing_depr_rows = {}   # propNm → list of _is_depr records this year
                for r in records:
                    if r.get('_is_depr') and str(r.get('dt', '')).startswith(str(year)):
                        pnm = r.get('propNm', '')
                        existing_depr_rows.setdefault(pnm, []).append(r)

                # ── Existing YE retained-earnings per propNm+owner ──────────
                existing_re = set()   # (propNm, oID) pairs already posted
                for r in records:
                    if (r.get('acctSub') == 'YE Net Income'
                            and str(r.get('dt', '')).startswith(str(year))):
                        pnm = r.get('propNm', '')
                        po  = _parse_prop_owners(r.get('propOwners', {}))
                        for oID in po:
                            existing_re.add((pnm, oID))

                result_props = []
                for pnm, pdata in props.items():
                    cost_rows = pdata['cost_rows']

                    # Depreciable cost: net Debits − Credits on Acct.Fixed.Tangible.InService
                    total_cost = 0.0
                    for r in cost_rows:
                        amt = float(r.get('amt', 0) or 0)
                        if (r.get('aType', '') or '').strip().lower() in ('debit', 'dr', 'd'):
                            total_cost += amt
                        else:
                            total_cost -= amt
                    total_cost = round(total_cost, 2)

                    asset_type = next((
                        r.get('assetType', '') for r in cost_rows if r.get('assetType')
                    ), 'Residential')
                    useful_life = 39.0 if asset_type == 'Commercial' else 27.5

                    placement_dt = next((
                        r.get('dt', '') for r in sorted(cost_rows, key=lambda x: x.get('dt', ''))
                        if r.get('dt')
                    ), None)

                    depr_amt = 0.0
                    note = ''
                    if placement_dt:
                        try:
                            from irs.irsDepreciation import (
                                macrs_residential_year1 as _macrs_yr1,
                            )
                            parts = placement_dt.replace('-', '.').replace('/', '.').split('.')
                            place_year  = int(parts[0])
                            place_month = int(parts[1])
                            if place_year == year:
                                # IRS MACRS mid-month convention via shared irs.irsDepreciation
                                # service (IRC §168(d)(2)).  Formula: basis/life × (12.5-M)/12.
                                depr_amt = _macrs_yr1(total_cost, place_month, useful_life)
                                frac     = round(12.5 - place_month, 1)
                                mon_name = _dt.date(year, place_month, 1).strftime('%b')
                                note = (f"GL basis ${total_cost:,.2f} ÷ {useful_life}yr "
                                        f"× {frac}/12 months "
                                        f"({mon_name} mid-month, first year)")
                            else:
                                depr_amt = round(total_cost / useful_life, 2)
                                note = f"GL basis ${total_cost:,.2f} ÷ {useful_life}yr (full year)"
                        except Exception:
                            depr_amt = round(total_cost / useful_life, 2)
                            note = f"GL basis ${total_cost:,.2f} ÷ {useful_life}yr"

                    # ── Depreciation discrepancy analysis ─────────────────
                    ex_depr_list  = existing_depr_rows.get(pnm, [])
                    depr_exists   = bool(ex_depr_list)
                    discrepancy   = None
                    existing_amt  = None
                    # Use UNIQUE amounts (deduplicate duplicate postings); flag if dups present
                    _unique_amts  = list({round(float(r.get('amt', 0) or 0), 2) for r in ex_depr_list})
                    _has_dup_depr = len(ex_depr_list) > len(_unique_amts) or len(ex_depr_list) > 1
                    if depr_exists and ex_depr_list:
                        existing_amt = _unique_amts[0] if len(_unique_amts) == 1 \
                                       else round(sum(_unique_amts) / len(_unique_amts), 2)
                        diff = round(existing_amt - depr_amt, 2)
                        if abs(diff) > 0.01:
                            # Infer the implied cost basis from the existing posting
                            try:
                                parts = placement_dt.replace('-','.').split('.')
                                pm    = int(parts[1])
                                py    = int(parts[0])
                                if py == year:
                                    # Reverse: existing_amt = cost/life × (25−2M)/24
                                    # → implied cost = existing_amt × life × 24 / (25−2M)
                                    hm = 25 - 2 * pm
                                    implied = round(existing_amt * useful_life * 24.0 / hm, 2)
                                else:
                                    implied = round(existing_amt * useful_life, 2)
                            except Exception:
                                implied = None
                            discrepancy = {
                                "existing_amt": existing_amt,
                                "computed_amt": depr_amt,
                                "diff":         diff,
                                "implied_basis": implied,
                                "dup_records": _has_dup_depr,
                                "dup_count":   len(ex_depr_list),
                                "explanation": (
                                    (f"⚠ {len(ex_depr_list)} duplicate depreciation records found "
                                     f"— delete extras before filing.  " if _has_dup_depr else "") +
                                    f"Posted ${existing_amt:,.2f} (PropAgent, closing-statement basis"
                                    + (f" ≈ ${implied:,.2f}" if implied else "") + "). "
                                    f"GL-computed ${depr_amt:,.2f} uses only "
                                    f"Acct.Fixed.Tangible.InService net (${total_cost:,.2f}) — "
                                    f"may exclude closing costs capitalised into basis "
                                    f"(title fees, legal, transfer taxes). "
                                    f"PropAgent amount is likely correct; "
                                    f"verify against Form 4562 / closing statement."
                                ),
                            }

                    prop_addr   = cost_rows[0].get('propAddr', '') if cost_rows else ''
                    prop_owners_raw = cost_rows[0].get('propOwners', {}) if cost_rows else {}
                    prop_owners = _parse_prop_owners(prop_owners_raw)
                    pnm_slug    = pnm.replace(' ', '_').replace('/', '-')

                    depr_record = {
                        "dt": ye_dt, "desc": f"YE Depreciation - {pnm}",
                        "amt": depr_amt, "aType": "Debit",
                        "acct": "Acct.Exp.Depreciation",
                        "Ledger": "Acct.Fixed.Depreciation.Accum",
                        "propNm": pnm, "propAddr": prop_addr,
                        "propOwners": prop_owners_raw, "tDB": "llcAssets",
                        "acctSub": "YE:Acct.Exp.Depreciation",
                        "assetType": asset_type, "_is_depr": True,
                        "tID": f"{year}.12.31_depr_{pnm_slug}",
                    }

                    # ── Adjusted NI for RE: if depr is new in this batch, subtract it now
                    # so RE amounts are based on post-depr NI in a one-shot apply.
                    depr_pending = not depr_exists and depr_amt != 0
                    adjusted_ni  = round(net_income - (depr_amt if depr_pending else 0.0), 2)

                    # ── YE Retained Earnings — split by llcOwners pct, not propOwners ─
                    # Closing entry: Acct.Equity.Earnings.PnL (P&L clearing, 3100)
                    #                → Acct.Equity.Owner.Capital.Funds (member capital, 3010)
                    # gain: Dr PnL / Cr Capital — clears credit P&L balance, builds capital
                    # loss: Cr PnL / Dr Capital — records loss, reduces capital
                    re_members = []
                    re_atype = 'Debit' if adjusted_ni >= 0 else 'Credit'
                    for o in owners_list:
                        oID  = o.get('oID', '')
                        pct  = float(o.get('pct', 0) or 0) * 100  # llcOwners.pct is 0–1
                        if pct <= 0:
                            continue
                        member_share = round(abs(adjusted_ni) * pct / 100.0, 2)
                        oname  = _owner_name(oID)
                        re_exists = (pnm, oID) in existing_re
                        re_record = {
                            "dt":         ye_dt,
                            "desc":       f"YE Net Income - {pnm} - {oname} ({pct:.0f}%)",
                            "amt":        member_share,
                            "aType":      re_atype,
                            "acct":       "Acct.Equity.Earnings.PnL",
                            "Ledger":     "Acct.Equity.Owner.Capital.Funds",  # double-entry: keeps A=L+E+NI balanced
                            "acctOwner":  oID,   # per-member equity tracking (Phase 2)
                            "propNm":     pnm,
                            "propAddr":   prop_addr,
                            "propOwners": {oID: pct},
                            "tDB":        "llcAsset",
                            "acctSub":    "YE Net Income",
                            "refDB":      f"General Ledger - {ye_dt}",
                            "tID":        f"{ye_dt}_re_{oID}_{pnm_slug}",
                        }
                        re_members.append({
                            "oID":    oID,
                            "name":   oname,
                            "pct":    pct,
                            "amount": member_share,
                            "atype":  re_atype,
                            "status": "exists" if re_exists else "new",
                            "record": re_record if not re_exists else None,
                        })

                    # ── Depreciation item — include replacement record when discrepancy exists
                    depr_status = "exists" if depr_exists else "new"
                    depr_record_out = None
                    if not depr_exists:
                        depr_record_out = depr_record
                    elif discrepancy:
                        # Replacement: _replace_tID tells ye_apply to delete the old record first
                        replace_rec = dict(depr_record)
                        replace_rec["_replace_tID"] = ex_depr_list[0].get("tID", "") if ex_depr_list else ""
                        depr_record_out = replace_rec
                        depr_status = "replace"

                    items = [
                        {
                            "item":          "depreciation",
                            "label":         "Depreciation & Amortization",
                            "status":        depr_status,
                            "amount":        existing_amt if depr_exists else depr_amt,
                            "note":          note,
                            "discrepancy":   discrepancy,
                            "record":        depr_record_out,
                        },
                        {
                            "item":    "retained_earnings",
                            "label":   "YE Retained Earnings (Net Income → Member Capital)",
                            "status":  "new" if any(m['status'] == 'new' for m in re_members)
                                       else ("exists" if re_members else "review"),
                            "amount":  adjusted_ni,
                            "note":    (f"Net {'Income' if adjusted_ni >= 0 else 'Loss'} "
                                        f"${abs(adjusted_ni):,.2f} split per ownership %"
                                        + (" (incl. pending depr)" if depr_pending else "")),
                            "members": re_members,
                            "record":  None,
                        },
                        {
                            "item":   "loan_amortization",
                            "label":  "Loan Amortization",
                            "status": "review", "amount": None, "record": None,
                            "note":   "Check llcPayables for annual interest/principal split",
                        },
                        {
                            "item":   "accrued_rent",
                            "label":  "Accrued / Prepaid Rent",
                            "status": "review", "amount": None, "record": None,
                            "note":   "Check if Dec 28–31 rent received applies to Jan",
                        },
                        {
                            "item":   "security_deposits",
                            "label":  "Security Deposits",
                            "status": "review", "amount": None, "record": None,
                            "note":   "Confirm deposits classified as Liability in llcPayables",
                        },
                    ]

                    result_props.append({
                        "propNm": pnm, "propAddr": prop_addr, "items": items,
                    })

                return jsonify({
                    "ok": True, "year": year,
                    "net_income": net_income,
                    "properties": result_props,
                })
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        @app.route("/api/llcAssets/ye/apply", methods=["POST"])
        def ye_apply():
            '''Append approved YE posting records to llcAssets (no double-posting).'''
            try:
                data     = request.get_json(force=True) or {}
                new_recs = data.get("records", [])  # flat list of record dicts
                mgr      = self.objects.get('llcAssets')
                if mgr is None:
                    return jsonify({"ok": False, "error": "llcAssets not available"}), 500

                existing = mgr.load() or []

                # Strip _replace_tID from each record, collect tIDs to delete first
                replace_tids = set()
                clean_recs   = []
                for r in new_recs:
                    if not r or not isinstance(r, dict):
                        continue
                    rid = r.pop('_replace_tID', None)
                    if rid:
                        replace_tids.add(rid)
                    clean_recs.append(r)

                # Remove old records targeted for replacement
                if replace_tids:
                    existing = [r for r in existing if r.get('tID') not in replace_tids]

                existing_tids = {r.get('tID') for r in existing if r.get('tID')}
                to_add   = [r for r in clean_recs if r.get('tID') not in existing_tids]
                replaced = len(replace_tids)

                if not to_add and not replaced:
                    return jsonify({"ok": True, "added": 0, "replaced": 0, "skipped": len(clean_recs)})

                mgr.save(existing + to_add)
                return jsonify({"ok": True, "added": len(to_add), "replaced": replaced,
                                "skipped": len(clean_recs) - len(to_add)})
            except HTTPException:
                raise
            except Exception as err:
                return jsonify({"ok": False, "error": str(err)}), 500

        # ── LLCTaxAgent (Phase 3 + 4) routes ─────────────────────────────────

        try:
            from irs.taxAgents.LLCTaxAgent import LLCTaxAgent as _LLCTaxAgent
            _tax_agent_import_err = None
        except Exception as _te:
            _LLCTaxAgent       = None
            _tax_agent_import_err = str(_te)
            app.logger.error("LLCTaxAgent import FAILED: %s", _te)

        def _tax_agent():
            return _LLCTaxAgent(self.eSession.llc)

        @app.route("/view/tax_prep")
        def view_tax_prep():
            """IRS Submission Dashboard — Phase 3 + 4 status + checklist."""
            if _LLCTaxAgent is None:
                return render_template("construction.html",
                                       obj_type="IRS Submission",
                                       meta={"error": _tax_agent_import_err})
            try:
                agent     = _tax_agent()
                session_s = agent.getSummary()
                manifest  = agent.load_manifest()
                phase4    = agent.phase4_submit()
                owners    = agent._get_owners()
                entity, f1065_data = agent._load_profile_data()
                letter_path = agent._accountant_letter_path()
                year = agent.tax_year
                return render_template(
                    "tax_prep.html",
                    app_title=self.app.config.get("_llc_name", "LLC Editor"),
                    view_title="IRS Submission Dashboard",
                    tax_year=year,
                    session_summary=session_s,
                    manifest=manifest,
                    phase4=phase4,
                    owners=owners,
                    entity=entity,
                    f1065_data=f1065_data,
                    letter_exists=bool(letter_path and letter_path.exists()),
                    letter_filename=letter_path.name if letter_path else '',
                    filing_deadline=f'{year + 1}-03-15',
                )
            except Exception as err:
                app.logger.exception("view_tax_prep failed")
                return render_template("construction.html",
                                       obj_type="IRS Submission",
                                       meta={"error": str(err)})

        @app.route("/api/tax/status")
        def api_tax_status():
            """Return LLCTaxAgent session summary + manifest status."""
            if _LLCTaxAgent is None:
                return jsonify({'ok': False, 'error': _tax_agent_import_err}), 503
            try:
                agent    = _tax_agent()
                summary  = agent.getSummary()
                manifest = agent.load_manifest()
                phase4   = agent.phase4_submit()
                return jsonify({'ok': True,
                                'summary':  summary,
                                'manifest': manifest,
                                'phase4':   phase4})
            except Exception as err:
                app.logger.exception("api_tax_status failed")
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/api/tax/prepare", methods=["POST"])
        def api_tax_prepare():
            """Run LLCTaxAgent Phase 1 + Phase 2 (all form agents + XF audit)."""
            if _LLCTaxAgent is None:
                return jsonify({'ok': False, 'error': _tax_agent_import_err}), 503
            try:
                result = _tax_agent().run_phases_1_2()
                return jsonify({'ok': True, 'result': result})
            except Exception as err:
                app.logger.exception("api_tax_prepare failed")
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/api/tax/package", methods=["POST"])
        def api_tax_package():
            """Assemble IRS_Submission_{year}/ directory and write manifest.json."""
            if _LLCTaxAgent is None:
                return jsonify({'ok': False, 'error': _tax_agent_import_err}), 503
            try:
                manifest = _tax_agent().phase3_package()
                return jsonify({'ok': True, 'manifest': manifest})
            except Exception as err:
                app.logger.exception("api_tax_package failed")
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/api/tax/report")
        def api_tax_report():
            """Return the last assembled manifest.json."""
            if _LLCTaxAgent is None:
                return jsonify({'ok': False, 'error': _tax_agent_import_err}), 503
            try:
                manifest = _tax_agent().load_manifest()
                return jsonify({'ok': manifest is not None, 'manifest': manifest})
            except Exception as err:
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/api/tax/accountant_letter", methods=["POST"])
        def api_tax_accountant_letter():
            """Generate AccountantLetter_{year}.pdf and return filename."""
            if _LLCTaxAgent is None:
                return jsonify({'ok': False, 'error': _tax_agent_import_err}), 503
            try:
                out = _tax_agent().generate_accountant_letter()
                if out is None:
                    return jsonify({'ok': False, 'error': 'reportlab unavailable or path error'}), 500
                return jsonify({'ok': True, 'filename': out.name, 'path': str(out)})
            except Exception as err:
                app.logger.exception("api_tax_accountant_letter failed")
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/api/tax/submission/update", methods=["POST"])
        def api_tax_submission_update():
            """Persist filed_date, filed_method, tracking_number, k1_delivered."""
            if _LLCTaxAgent is None:
                return jsonify({'ok': False, 'error': _tax_agent_import_err}), 503
            try:
                body    = request.get_json(silent=True) or {}
                updated = _tax_agent().update_submission_status(body)
                return jsonify({'ok': True, 'status': updated})
            except Exception as err:
                app.logger.exception("api_tax_submission_update failed")
                return jsonify({'ok': False, 'error': str(err)}), 500

        @app.route("/forms/AccountantLetter_<int:year>.pdf")
        def serve_accountant_letter(year):
            """Serve the AccountantLetter PDF from the forms directory."""
            from flask import send_from_directory
            forms_dir = self._get_forms_dir()
            if forms_dir is None:
                return ('Forms directory not found', 404)
            fname = f'AccountantLetter_{year}.pdf'
            return send_from_directory(str(forms_dir), fname,
                                       mimetype='application/pdf')

        bind_propAgent_routes(app, self.objects, self._sanitize)
        bind_expAgent_routes(app, self.objects, self._sanitize)

    def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False, notebook: bool = False):
        if notebook:
            thread = threading.Thread(
                target=self.app.run,
                kwargs={"host": host, "port": port, "debug": debug, "use_reloader": False},
                daemon=True,
            )
            thread.start()
            print(f"Running in notebook mode at http://{host}:{port}")
            return thread

        self.app.run(host=host, port=port, debug=debug)
