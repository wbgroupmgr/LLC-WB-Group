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
import math
import threading
from pathlib import Path
from typing import Any, Dict, List, Set

from flask import Flask, abort, jsonify, render_template, request, send_file

from ui.llcAssets          import llcAssets
from ui.llcExpRev          import llcExpRev
from ui.llcPayables        import llcPayables
from ui.llcReceivables     import llcReceivables
from ui.stmtGL_View  import stmtGL_View  as stmtGeneralLedger
from ui.stmtBS_View  import stmtBS_View  as stmtBalanceSheet
from ui.stmtIS_View  import stmtIS_View  as stmtIncomeStmt
from ui.stmtOwnerEquity      import stmtOwnerEquity
from ui.llcBankView         import llcBankView
from ui.stmtPropertyEquity   import stmtPropertyEquity
from ui.llcForm1065         import llcForm1065
from ui.llcFormK1           import llcFormK1
from ui.llcForm8825         import llcForm8825


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
        "llcForm1065":        "Form 1065",
        "llcFormK1":          "Schedule K-1",
        "llcForm8825":        "Form 8825",
    }

    VIEW_TITLES = {
        "stmtBalanceSheet":    "Balance Sheet",
        "stmtIncomeStmt":      "Income Statement",
        "stmtOwnerEquity":     "Owner / Member Equity",
        "stmtPropertyEquity":  "Property Equity Report",
        "llcForm1065":        "Form 1065 – U.S. Return of Partnership Income",
        "llcFormK1":          "Schedule K-1 – Partner's Share of Income",
        "llcForm8825":        "Form 8825 – Rental Real Estate Income and Expenses",
    }

    # View groups for the home page
    VIEW_GROUPS = [
        {
            "label": "Transactions",
            "icon":  "📂",
            "views": ["llcAssets", "llcExpRev", "llcPayables", "llcReceivables",
                      "llcBank"],
        },
        {
            "label": "Financial Statements",
            "icon":  "📊",
            # General Ledger is the first entry here per DataModelGuide § 2
            # ("NOTE: GeneralLedger should be listed under the financial
            # statements Home page").
            "views": ["stmtGeneralLedger", "stmtBalanceSheet", "stmtIncomeStmt",
                      "stmtOwnerEquity", "stmtPropertyEquity"],
        },
        {
            "label": "IRS Tax Aids",
            "icon":  "🧾",
            # v0.2.4.7 — each tax view embeds the canonical FILL.pdf produced
            # by the IRS pipeline (irs.<Form>.saveFILL()).  No constructed
            # row tables, no nSpaceMap detour at the view layer.
            "views": ["llcForm1065", "llcFormK1", "llcForm8825"],
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
        "llcForm1065", "llcFormK1", "llcForm8825",
    }

    # Preferred column sets for computed views
    GL_COLUMNS = ['Status', 'dt', 'acctType', 'acct', 'acctMinor', 'propNm', 'aType', 'amt', 'desc', 'acctSub', 'refDB']

    # ViewBy options per computed view (empty = no dropdown shown)
    VIEW_BY_OPTIONS: Dict[str, List[str]] = {
        'stmtGeneralLedger': ['All', 'By Dups', 'ByAsset', 'ByLiability', 'ByEquity', 'ByIncome', 'ByExpense'],
        'stmtBalanceSheet':  ['All', 'ByAsset', 'ByLiability', 'ByEquity'],
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
        session_title = getattr(getattr(eSession, "llc", None), "objName", None)
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

        # ── IRS FILL.pdf binary route (v0.2.4.7) ──────────────────────────────
        # Serves Forms_IRS/<form_id>_FILL.pdf as application/pdf.  Used by the
        # iframe src in irs_pdf_view.html.  ?download=1 triggers a "Save As"
        # response instead of inline rendering.
        @app.route("/forms/<form_id>.pdf")
        def serve_irs_pdf(form_id: str):
            allowed = set(self.PDF_VIEWS.values())
            if form_id not in allowed:
                abort(404)
            llc = getattr(self.eSession, "llc", None)
            if llc is None:
                abort(404)
            try:
                irs_dir = Path(llc.acctDir(dirName="ye")) / "Forms_IRS"
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
            llc = getattr(self.eSession, "llc", None)
            if llc is None:
                abort(404)
            try:
                irs_dir = Path(llc.acctDir(dirName="ye")) / "Forms_IRS"
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
                    _llc = getattr(self.eSession, "llc", None)
                    if _llc:
                        _ns = (Path(_llc.acctDir(dirName="ye"))
                               / "Forms_IRS" / f"{form_nm}_namespace.pdf")
                        if _ns.exists():
                            ns_pdf_url = f"/forms/{form_nm}_NS.pdf"
                except Exception:
                    pass
                return render_template(
                    "irs_pdf_view.html",
                    title=self.title,
                    obj_type=obj_type,
                    view_title=self.VIEW_TITLES.get(obj_type, obj_type),
                    pdf_url=f"/forms/{form_nm}.pdf",
                    ns_pdf_url=ns_pdf_url,
                    stats=manager.stats(),
                    stats_labels=self._stats_labels(manager.stats()),
                    meta=mgr_meta,
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

                # For Balance Sheet: also pass the accounting-equation check
                bs_check = None
                if obj_type == "stmtBalanceSheet" and hasattr(manager, "last_check"):
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
