'''
llcMgmt — Flask app wiring all LLC editor views.

Views:
  llcAssets       — Asset records (editable, table_view.html)
  llcExpRev       — Expense/Revenue records (editable, table_view.html)
  llcGeneralLedger— Merged GL computed view (read-only, table_view.html)
  llcBalanceSheet — Balance Sheet computed view (read-only, financial_view.html)
  llcIncomeStmt   — Income Statement computed view (read-only, financial_view.html)
  llcBank         — Bank CSV reconciliation (read-only, bank_view.html)

Timestamp of last change: 2026.04.13
'''

import json
import math
import threading
from pathlib import Path
from typing import Any, Dict, List, Set

from flask import Flask, jsonify, render_template, request

from uillc.llcAssets import llcAssets
from uillc.llcExpRev import llcExpRev
from uillc.llcGeneralLedger import llcGeneralLedger
from uillc.llcBalanceSheet import llcBalanceSheet
from uillc.llcIncomeStmt import llcIncomeStmt
from uillc.llcBankView import llcBankView


class llcMgmt:
    VIEW_ORDER = [
        "llcAssets",
        "llcExpRev",
        "llcGeneralLedger",
        "llcBalanceSheet",
        "llcIncomeStmt",
        "llcBank",
    ]
    VIEW_LABELS = {
        "llcAssets":        "Assets",
        "llcExpRev":        "Exp / Revenue",
        "llcGeneralLedger": "General Ledger",
        "llcBalanceSheet":  "Balance Sheet",
        "llcIncomeStmt":    "Income Statement",
        "llcBank":          "Bank Reconciliation",
    }
    VIEW_TITLES = {
        "llcBalanceSheet": "Balance Sheet",
        "llcIncomeStmt":   "Income Statement",
    }

    # Views that use financial_view.html
    FINANCIAL_VIEWS = {"llcBalanceSheet", "llcIncomeStmt"}
    # Views that use bank_view.html
    BANK_VIEWS = {"llcBank"}
    # All computed (read-only) views
    READ_ONLY_VIEWS = {"llcGeneralLedger", "llcBalanceSheet", "llcIncomeStmt", "llcBank"}

    # Preferred column sets for computed views
    GL_COLUMNS = ['Status', 'dt', 'acctType', 'acct', 'aType', 'amt', 'desc', 'acctSub', 'refDB']

    # ViewBy options per computed view (empty = no dropdown shown)
    VIEW_BY_OPTIONS: Dict[str, List[str]] = {
        'llcGeneralLedger': ['All', 'By Dups', 'ByAsset', 'ByLiability', 'ByEquity', 'ByIncome', 'ByExpense'],
        'llcBalanceSheet':  ['All', 'ByAsset', 'ByLiability', 'ByEquity'],
        'llcIncomeStmt':    ['All', 'ByIncome', 'ByExpense'],
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
        self.title = title or session_title or "LLC Management App"

        template_dir = Path(__file__).resolve().parent / "templates"
        self.app = Flask(__name__, template_folder=str(template_dir))

        self.objects = self._build_objects()

        @self.app.context_processor
        def inject_globals():
            return {
                "app_title": self.title,
                "available_views": self.available_views(),
            }

        self._bind_routes()

    def _canonical_name(self, name: str) -> str:
        aliases = {
            "llcAsset":          "llcAssets",
            "llcAssets":         "llcAssets",
            "llcExpRev":         "llcExpRev",
            "llcGeneralLedger":  "llcGeneralLedger",
            "llcIncomeStmt":     "llcIncomeStmt",
            "llcBalanceSheet":   "llcBalanceSheet",
            "llcBank":           "llcBank",
        }
        return aliases.get(name, name)

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
            # Skip old stub classes for llcIncomeStmt / llcBalanceSheet
            # (they are now computed views built below from eSession)

            if mgr is not None:
                if hasattr(mgr, "bind_session"):
                    mgr.bind_session(self.eSession)
                objects[obj_name] = mgr

        # ── computed (read-only) views: always built from eSession ────────────
        objects["llcGeneralLedger"] = llcGeneralLedger(self.eSession)
        objects["llcBalanceSheet"]  = llcBalanceSheet(self.eSession)
        objects["llcIncomeStmt"]    = llcIncomeStmt(self.eSession)
        objects["llcBank"]          = llcBankView(self.eSession)

        return objects

    def available_views(self) -> List[Dict[str, Any]]:
        items = []
        for name in self.VIEW_ORDER:
            items.append({
                "name": name,
                "label": self.VIEW_LABELS.get(name, name),
                "present": name in self.objects,
                "under_construction": False,
            })
        return items

    def _supports_record_views(self, obj_type: str) -> bool:
        return obj_type in ("llcAssets", "llcExpRev")

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
        # Editable views use predefined column sets
        if self._supports_record_views(obj_type):
            mode = self._normalize_view_mode(view_mode)
            return list(self.RECORD_VIEW_OPTIONS[mode])

        # GL view: use fixed preferred set
        if obj_type == "llcGeneralLedger":
            return list(self.GL_COLUMNS)

        # Balance Sheet / Income Statement / Bank: columns derived from data
        cols: Set[str] = set()
        for row in rows:
            if isinstance(row, dict):
                cols.update(row.keys())

        if not cols:
            return ["acctType", "acct"]

        # Priority ordering for financial rows
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
                        "text": str(sub_key),
                        "group": str(key),
                    })
            else:
                labels.append({
                    "value": self._format_stat_value(value),
                    "text": str(key),
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
        # Must match JS rowIdFor(): (row.id ?? row.oID) ?? index
        # Do NOT include tID — JS doesn't know about it and the mismatch
        # causes "Record not found" for records that lack id/oID.
        return str(row.get("id", row.get("oID", index)))

    @staticmethod
    def _sanitize(obj: Any) -> Any:
        '''Recursively replace float NaN/Inf with None so Flask jsonify stays valid JSON.
        COA pandas lookups (e.g. acctSub) can inject NaN into record dicts.'''
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
                "_changed": record_id in changed_ids,
                "data": row,
            })
        return result

    def _bind_routes(self):
        app = self.app

        # Chrome DevTools automatically probes this path on every navigation.
        # Return an empty JSON array so Flask doesn't log a 404 for it.
        @app.route("/.well-known/appspecific/com.chrome.devtools.json")
        def chrome_devtools_json():
            return jsonify([])

        @app.route("/")
        def home():
            session_views = []
            seen = set()
            for key, wk in self.eSession.oDict.items():
                obj_name = self._canonical_name(getattr(getattr(wk, "o", None), "oID", key))
                fn = wk.FN() if hasattr(wk, 'FN') else ''
                ofn = wk.o.FN() if hasattr(wk, 'o') and hasattr(wk.o, 'FN') else ''
                stamp = (obj_name, fn, ofn)
                if stamp in seen:
                    continue
                seen.add(stamp)
                session_views.append({
                    "name": obj_name,
                    "raw_name": key,
                    "working_file": fn,
                    "object_file": ofn,
                })

            return render_template(
                "home.html",
                title=self.title,
                session_views=session_views
            )

        @app.route("/view/<obj_type>")
        def view_object(obj_type: str):
            obj_type = self._canonical_name(obj_type)
            manager = self.objects.get(obj_type)

            if manager is None:
                meta = {"objectName": obj_type}
                return render_template(
                    "construction.html",
                    title=self.title,
                    obj_type=obj_type,
                    meta=meta
                )

            view_mode = self._normalize_view_mode(request.args.get("viewMode", "all"))
            view_by = request.args.get("viewBy", "All")
            view_by_options = self.VIEW_BY_OPTIONS.get(obj_type, [])
            changed_ids = self._parse_changed_ids()
            # Computed views support view_by filtering via their own load()
            if obj_type in self.READ_ONLY_VIEWS and obj_type not in self.BANK_VIEWS:
                rows = manager.load(view_by=view_by)
            else:
                rows = manager.load()
            stats = manager.stats()

            # Editable views: build ViewBy options from actual acctTypes in data,
            # then apply display-only filter.  Edit/delete API calls use the full
            # unfiltered load() so no data is lost.
            if self._supports_record_views(obj_type):
                acct_types = sorted({r.get('acctType', '') for r in rows if r.get('acctType', '')})
                view_by_options = ['All'] + [f'By{t}' for t in acct_types]
                if view_by and view_by != 'All':
                    acct_type_filter = view_by[2:]   # 'ByAsset' → 'Asset'
                    rows = [r for r in rows if r.get('acctType', '') == acct_type_filter]
            meta = manager.meta()
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
                )

            # ── Standard table view ───────────────────────────────────────────
            columns = self._get_columns(rows, obj_type, view_mode=view_mode)
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

        # ── New Session endpoint ──────────────────────────────────────────────
        @app.route("/api/session/new", methods=["POST"])
        def new_session():
            '''
            Snapshot working files (push) then reset each wk back to its DB object.
            Client should redirect to "/" after a successful response.
            '''
            stamp = self.eSession.push()
            self.eSession.reset()
            return jsonify({"ok": True, "snapshot": stamp})

        # ── Bank CSV upload endpoint ──────────────────────────────────────────
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

        # ── Generic API command endpoint ──────────────────────────────────────
        @app.route("/api/<obj_type>/cmd", methods=["GET", "POST"])
        def api_cmd(obj_type: str):
            obj_type = self._canonical_name(obj_type)
            manager = self.objects.get(obj_type)

            if manager is None:
                return jsonify({"ok": False, "error": f"Unknown object type: {obj_type}"}), 404

            cmd = request.values.get("cmd", "load")

            s = self._sanitize  # shorthand

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
                return jsonify({"ok": True, "data": s(manager.save(payload))})

            if cmd == "save_object":
                payload = request.values.get("payload")
                payload = self._parse_payload(payload, manager.load()) if payload is not None else manager.load()
                return jsonify({"ok": True, "data": s(manager.save_object(payload))})

            if cmd == "reset_from_object":
                return jsonify({"ok": True, "data": s(manager.reset_from_object())})

            # Mutation commands — read-only views return graceful error
            if obj_type in self.READ_ONLY_VIEWS:
                return jsonify({"ok": False, "error": f"{obj_type} is a read-only computed view"}), 400

            if cmd == "add":
                payload = self._parse_payload(request.values.get("payload", "{}"), {})
                rows = manager.load()
                rows.append(payload)
                saved = s(manager.save(rows))
                new_id = self._row_id(saved[-1], len(saved) - 1) if saved else ""
                return jsonify({"ok": True, "data": saved, "changedRecordId": new_id})

            if cmd == "update":
                record_id = request.values.get("id")
                payload = self._parse_payload(request.values.get("payload", "{}"), {})
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
                rows = manager.load()
                new_rows = [row for i, row in enumerate(rows) if self._row_id(row, i) != str(record_id)]
                saved = s(manager.save(new_rows))
                return jsonify({"ok": True, "data": saved})

            return jsonify({"ok": False, "error": f"Unknown command: {cmd}"}), 400

    def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False, notebook: bool = False):
        if notebook:
            thread = threading.Thread(
                target=self.app.run,
                kwargs={"host": host, "port": port, "debug": debug, "use_reloader": False},
                daemon=True
            )
            thread.start()
            print(f"Running in notebook mode at http://{host}:{port}")
            return thread

        self.app.run(host=host, port=port, debug=debug)
