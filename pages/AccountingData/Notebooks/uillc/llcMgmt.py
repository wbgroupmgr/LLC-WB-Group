'''
llcMgmt — Flask app wiring all LLC editor views.

Views:
  Transactions:
    llcAssets       — Asset records (editable, table_view.html)
    llcExpRev       — Expense/Revenue records (editable, table_view.html)
    llcGeneralLedger— Merged GL computed view (read-only, table_view.html)
    llcBank         — Bank CSV reconciliation (read-only, bank_view.html)

  Financial Statements:
    llcBalanceSheet — Balance Sheet (read-only, financial_view.html)
    llcIncomeStmt   — Income Statement (read-only, financial_view.html)
    llcOwnerEquity  — Owner / Member Equity (read-only, financial_view.html)

  IRS Tax Aids:
    llcForm1065     — Form 1065 summary (read-only, tax_view.html)
    llcFormK1       — Schedule K-1 per partner (read-only, tax_view.html)
    llcFormSchedL   — Schedule L Balance Sheet per books (read-only, tax_view.html)
    llcFormSchedM1  — Schedule M-1 income reconciliation (read-only, tax_view.html)
    llcFormSchedM2  — Schedule M-2 partners' capital (read-only, tax_view.html)

Timestamp of last change: 2026.04.14
'''

import json
import math
import threading
from pathlib import Path
from typing import Any, Dict, List, Set

from flask import Flask, jsonify, render_template, request

from uillc.llcAssets          import llcAssets
from uillc.llcExpRev          import llcExpRev
from uillc.llcPayables        import llcPayables
from uillc.llcReceivables     import llcReceivables
from uillc.llcGeneralLedger   import llcGeneralLedger
from uillc.llcBalanceSheet     import llcBalanceSheet
from uillc.llcIncomeStmt       import llcIncomeStmt
from uillc.llcOwnerEquity      import llcOwnerEquity
from uillc.llcBankView         import llcBankView
from uillc.llcPropertyEquity   import llcPropertyEquity
from uillc.llcForm1065         import llcForm1065
from uillc.llcFormK1           import llcFormK1
from uillc.llcFormSchedL       import llcFormSchedL
from uillc.llcFormSchedM1      import llcFormSchedM1
from uillc.llcFormSchedM2      import llcFormSchedM2
from uillc.llcForm1065SchBPg2  import llcForm1065SchBPg2
from uillc.llcForm1065SchBPg3  import llcForm1065SchBPg3
from uillc.llcForm1065SchBPg4  import llcForm1065SchBPg4
from uillc.llcForm1065SchKPg5  import llcForm1065SchKPg5
from uillc.llcForm1065Pg6      import llcForm1065Pg6


class llcMgmt:

    # ── View catalogue ────────────────────────────────────────────────────────
    VIEW_ORDER = [
        # Transactions
        "llcAssets",
        "llcExpRev",
        "llcPayables",
        "llcReceivables",
        "llcGeneralLedger",
        "llcBank",
        # Financial Statements
        "llcBalanceSheet",
        "llcIncomeStmt",
        "llcOwnerEquity",
        "llcPropertyEquity",
        # IRS Tax Aids
        "llcForm1065",
        "llcFormK1",
        "llcFormSchedL",
        "llcFormSchedM1",
        "llcFormSchedM2",
        "llcForm1065SchBPg2",
        "llcForm1065SchBPg3",
        "llcForm1065SchBPg4",
        "llcForm1065SchKPg5",
        "llcForm1065Pg6",
    ]

    VIEW_LABELS = {
        "llcAssets":          "Assets",
        "llcExpRev":          "Exp / Revenue",
        "llcPayables":        "Payables (A/P)",
        "llcReceivables":     "Receivables (A/R)",
        "llcGeneralLedger":   "General Ledger",
        "llcBank":            "Bank Reconciliation",
        "llcBalanceSheet":    "Balance Sheet",
        "llcIncomeStmt":      "Income Statement",
        "llcOwnerEquity":     "Owner Equity",
        "llcPropertyEquity":  "Property Equity",
        "llcForm1065":        "Form 1065",
        "llcFormK1":          "Schedule K-1",
        "llcFormSchedL":      "Schedule L",
        "llcFormSchedM1":     "Schedule M-1",
        "llcFormSchedM2":     "Schedule M-2",
        "llcForm1065SchBPg2": "Sch B — Pg 2",
        "llcForm1065SchBPg3": "Sch B — Pg 3",
        "llcForm1065SchBPg4": "Sch B — Pg 4",
        "llcForm1065SchKPg5": "Sch K — Pg 5",
        "llcForm1065Pg6":     "Form 1065 — Pg 6",
    }

    VIEW_TITLES = {
        "llcBalanceSheet":    "Balance Sheet",
        "llcIncomeStmt":      "Income Statement",
        "llcOwnerEquity":     "Owner / Member Equity",
        "llcPropertyEquity":  "Property Equity Report",
        "llcForm1065":        "Form 1065 – U.S. Return of Partnership Income",
        "llcFormK1":          "Schedule K-1 – Partner's Share of Income",
        "llcFormSchedL":      "Schedule L – Balance Sheet per Books",
        "llcFormSchedM1":     "Schedule M-1 – Reconciliation of Income",
        "llcFormSchedM2":     "Schedule M-2 – Analysis of Partners' Capital Accounts",
        "llcForm1065SchBPg2": "Form 1065 Schedule B (Page 2) – Partnership Info & Elections Q1–12",
        "llcForm1065SchBPg3": "Form 1065 Schedule B (Page 3) – Compliance & Audit Regime Q13–25",
        "llcForm1065SchBPg4": "Form 1065 Schedule B (Page 4) – Partner Rep & Analysis of Net Income",
        "llcForm1065SchKPg5": "Form 1065 Schedule K (Page 5) – Partners' Distributive Share Items",
        "llcForm1065Pg6":     "Form 1065 Page 6 – Schedule L, M-1 & M-2",
    }

    # View groups for the home page
    VIEW_GROUPS = [
        {
            "label": "Transactions",
            "icon":  "📂",
            "views": ["llcAssets", "llcExpRev", "llcPayables", "llcReceivables",
                      "llcGeneralLedger", "llcBank"],
        },
        {
            "label": "Financial Statements",
            "icon":  "📊",
            "views": ["llcBalanceSheet", "llcIncomeStmt", "llcOwnerEquity", "llcPropertyEquity"],
        },
        {
            "label": "IRS Tax Aids",
            "icon":  "🧾",
            "views": ["llcForm1065", "llcFormK1", "llcFormSchedL", "llcFormSchedM1", "llcFormSchedM2"],
        },
        {
            "label": "Form 1065 — Detail Pages",
            "icon":  "📄",
            "views": [
                "llcForm1065SchBPg2",
                "llcForm1065SchBPg3",
                "llcForm1065SchBPg4",
                "llcForm1065SchKPg5",
                "llcForm1065Pg6",
            ],
        },
    ]

    # Views that use financial_view.html
    FINANCIAL_VIEWS = {"llcBalanceSheet", "llcIncomeStmt", "llcOwnerEquity"}
    # Views that use property_equity.html
    PROPERTY_VIEWS = {"llcPropertyEquity"}
    # Views that use tax_view.html
    TAX_VIEWS = {
        "llcForm1065", "llcFormK1", "llcFormSchedL", "llcFormSchedM1", "llcFormSchedM2",
        "llcForm1065SchBPg2", "llcForm1065SchBPg3", "llcForm1065SchBPg4",
        "llcForm1065SchKPg5", "llcForm1065Pg6",
    }
    # Views that use bank_view.html
    BANK_VIEWS = {"llcBank"}
    # All computed (read-only) views
    READ_ONLY_VIEWS = {
        "llcGeneralLedger", "llcBalanceSheet", "llcIncomeStmt", "llcOwnerEquity",
        "llcBank", "llcPropertyEquity",
        "llcForm1065", "llcFormK1", "llcFormSchedL", "llcFormSchedM1", "llcFormSchedM2",
        "llcForm1065SchBPg2", "llcForm1065SchBPg3", "llcForm1065SchBPg4",
        "llcForm1065SchKPg5", "llcForm1065Pg6",
    }

    # Preferred column sets for computed views
    GL_COLUMNS = ['Status', 'dt', 'acctType', 'acct', 'aType', 'amt', 'desc', 'acctSub', 'refDB']

    # ViewBy options per computed view (empty = no dropdown shown)
    VIEW_BY_OPTIONS: Dict[str, List[str]] = {
        'llcGeneralLedger': ['All', 'By Dups', 'ByAsset', 'ByLiability', 'ByEquity', 'ByIncome', 'ByExpense'],
        'llcBalanceSheet':  ['All', 'ByAsset', 'ByLiability', 'ByEquity'],
        'llcIncomeStmt':    ['All', 'ByIncome', 'ByExpense', 'PerMember'],
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
        session_title = getattr(getattr(eSession, "llc", None), "objName", None)
        base_title = title or session_title or "LLC Management App"
        # v0.2: surface the package version in the app title so the running
        # editor is self-identifying in the browser tab and home header.
        try:
            from uillc import __version__ as _uillc_version
        except Exception:
            _uillc_version = None
        self.version = _uillc_version
        self.title = f"{base_title} (uillc {_uillc_version})" if _uillc_version else base_title

        template_dir = Path(__file__).resolve().parent / "templates"
        self.app = Flask(__name__, template_folder=str(template_dir))

        self.objects = self._build_objects()

        @self.app.context_processor
        def inject_globals():
            return {
                "app_title":       self.title,
                "available_views": self.available_views(),
                "view_groups":     self.VIEW_GROUPS,
                "view_labels":     self.VIEW_LABELS,
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
            "llcGeneralLedger":  "llcGeneralLedger",
            "llcIncomeStmt":     "llcIncomeStmt",
            "llcBalanceSheet":   "llcBalanceSheet",
            "llcOwnerEquity":    "llcOwnerEquity",
            "llcBank":           "llcBank",
            "llcPropertyEquity": "llcPropertyEquity",
            "llcForm1065":          "llcForm1065",
            "llcFormK1":            "llcFormK1",
            "llcFormSchedL":        "llcFormSchedL",
            "llcFormSchedM1":       "llcFormSchedM1",
            "llcFormSchedM2":       "llcFormSchedM2",
            "llcForm1065SchBPg2":   "llcForm1065SchBPg2",
            "llcForm1065SchBPg3":   "llcForm1065SchBPg3",
            "llcForm1065SchBPg4":   "llcForm1065SchBPg4",
            "llcForm1065SchKPg5":   "llcForm1065SchKPg5",
            "llcForm1065Pg6":       "llcForm1065Pg6",
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
            from uillc.llcSession import ObjNode, WkNode
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
        for ap_ar, default_filename in (
            ("llcPayables",    "llcPayables_WBGroupLLC.json"),
            ("llcReceivables", "llcReceivables_WBGroupLLC.json"),
        ):
            if ap_ar in objects:
                continue
            wk = self._auto_wknode(ap_ar, default_filename)
            if wk is None:
                continue
            mgr = llcPayables(wk) if ap_ar == "llcPayables" else llcReceivables(wk)
            if hasattr(mgr, "bind_session"):
                mgr.bind_session(self.eSession)
            objects[ap_ar] = mgr
            # Make it visible in the eSession oDict so the home page
            # session-objects table lists it too.
            try:
                self.eSession.oDict.setdefault(ap_ar, wk)
            except Exception:
                pass

        # ── computed (read-only) views ────────────────────────────────────────
        objects["llcGeneralLedger"]  = llcGeneralLedger(self.eSession)
        objects["llcBalanceSheet"]   = llcBalanceSheet(self.eSession)
        objects["llcIncomeStmt"]     = llcIncomeStmt(self.eSession)
        objects["llcOwnerEquity"]    = llcOwnerEquity(self.eSession)
        objects["llcBank"]           = llcBankView(self.eSession)
        objects["llcPropertyEquity"] = llcPropertyEquity(self.eSession)

        # ── IRS tax aid views ─────────────────────────────────────────────────
        objects["llcForm1065"]   = llcForm1065(self.eSession)
        objects["llcFormK1"]     = llcFormK1(self.eSession)
        objects["llcFormSchedL"] = llcFormSchedL(self.eSession)
        objects["llcFormSchedM1"]= llcFormSchedM1(self.eSession)
        objects["llcFormSchedM2"]= llcFormSchedM2(self.eSession)

        # ── Form 1065 detail pages (Pg2–Pg6) ─────────────────────────────────
        objects["llcForm1065SchBPg2"] = llcForm1065SchBPg2(self.eSession)
        objects["llcForm1065SchBPg3"] = llcForm1065SchBPg3(self.eSession)
        objects["llcForm1065SchBPg4"] = llcForm1065SchBPg4(self.eSession)
        objects["llcForm1065SchKPg5"] = llcForm1065SchKPg5(self.eSession)
        objects["llcForm1065Pg6"]     = llcForm1065Pg6(self.eSession)

        return objects

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

    def _get_columns(self, rows: List[Dict[str, Any]], obj_type: str, view_mode: str = "all") -> List[str]:
        if self._supports_record_views(obj_type):
            mode = self._normalize_view_mode(view_mode)
            return list(self.RECORD_VIEW_OPTIONS[mode])

        if obj_type == "llcGeneralLedger":
            return list(self.GL_COLUMNS)

        # Tax views: derive columns from data, respect source order
        if obj_type in self.TAX_VIEWS and rows:
            # Use key order from first non-empty row
            for r in rows:
                if isinstance(r, dict) and r:
                    return list(r.keys())

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

    def _bind_routes(self):
        app = self.app

        @app.route("/.well-known/appspecific/com.chrome.devtools.json")
        def chrome_devtools_json():
            return jsonify([])

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

        # ── View ──────────────────────────────────────────────────────────────
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
            if obj_type == 'llcIncomeStmt' and view_by == 'All':
                view_by = 'PerMember'
            changed_ids      = self._parse_changed_ids()

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

            # ── Financial Statement views ─────────────────────────────────────
            if obj_type in self.FINANCIAL_VIEWS:

                # ── IS Per-Member view: separate template ─────────────────────
                if obj_type == "llcIncomeStmt" and view_by == "PerMember":
                    pm_rows, owner_names, pm_summary = manager.load_per_member()
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
                    )

                # For Balance Sheet: also pass the accounting-equation check
                bs_check = None
                if obj_type == "llcBalanceSheet" and hasattr(manager, "last_check"):
                    bs_check = manager.last_check()

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

            # ── Tax aid views ─────────────────────────────────────────────────
            if obj_type in self.TAX_VIEWS:
                columns = self._get_columns(rows, obj_type, view_mode=view_mode)
                return render_template(
                    "tax_view.html",
                    title=self.title,
                    obj_type=obj_type,
                    view_title=self.VIEW_TITLES.get(obj_type, obj_type),
                    rows=self._view_rows(rows),
                    raw_rows=rows,
                    columns=columns,
                    stats=stats,
                    stats_labels=stats_labels,
                    meta=meta,
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
                rows.append(payload)
                saved  = s(manager.save(rows))
                new_id = self._row_id(saved[-1], len(saved) - 1) if saved else ""
                return jsonify({"ok": True, "data": saved, "changedRecordId": new_id})

            if cmd == "update":
                record_id = request.values.get("id")
                payload   = self._parse_payload(request.values.get("payload", "{}"), {})
                rows = manager.load()
                updated = False
                for i, row in enumerate(rows):
                    if self._row_id(row, i) == str(record_id):
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
                new_rows  = [row for i, row in enumerate(rows) if self._row_id(row, i) != str(record_id)]
                saved     = s(manager.save(new_rows))
                return jsonify({"ok": True, "data": saved})

            return jsonify({"ok": False, "error": f"Unknown command: {cmd}"}), 400

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
