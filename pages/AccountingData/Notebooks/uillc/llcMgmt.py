import json
import threading
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request

from uillc.llcAssets import llcAssets
from uillc.llcExpRev import llcExpRev
from uillc.llcIncomeStmt import llcIncomeStmt
from uillc.llcBalanceSheet import llcBalanceSheet


class llcMgmt:
    VIEW_ORDER = ["llcAssets", "llcExpRev", "llcIncomeStmt", "llcBalanceSheet"]
    VIEW_LABELS = {
        "llcAssets": "Views.llcAssets",
        "llcExpRev": "View.llcExpRev",
        "llcIncomeStmt": "View.llcIncomeStmt",
        "llcBalanceSheet": "View.llcBalanceSheet",
    }

    RECORD_VIEW_OPTIONS = {
        "account": [
            "dt", "amt", "aType", "acct", "Ledger", "acctMajor",
            "acctMinor", "acctSub", "desc",
        ],
        "property": [
            "dt", "amt", "aType", "acct", "Ledger",
            "propNm", "propID", "propAddr", "propOwners",
        ],
        "all": [
            "dt", "desc", "amt", "aType", "acct", "Ledger", "acctMajor",
            "acctMinor", "acctSub", "propNm", "propID", "propAddr", "propOwners",
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
            "llcAsset": "llcAssets",
            "llcAssets": "llcAssets",
            "llcExpRev": "llcExpRev",
            "llcIncomeStmt": "llcIncomeStmt",
            "llcBalanceSheet": "llcBalanceSheet",
        }
        return aliases.get(name, name)

    def _build_objects(self) -> Dict[str, Any]:
        objects: Dict[str, Any] = {}
        for wk in self.eSession.oDict.values():
            obj_name = self._canonical_name(getattr(getattr(wk, "o", None), "oID", ""))
            if obj_name in objects:
                continue

            if obj_name == "llcAssets":
                mgr = llcAssets(wk)
            elif obj_name == "llcExpRev":
                mgr = llcExpRev(wk)
            elif obj_name == "llcIncomeStmt":
                mgr = llcIncomeStmt(wk)
            elif obj_name == "llcBalanceSheet":
                mgr = llcBalanceSheet(wk)
            else:
                continue

            if hasattr(mgr, "bind_session"):
                mgr.bind_session(self.eSession)

            objects[obj_name] = mgr

        return objects

    def available_views(self) -> List[Dict[str, Any]]:
        items = []
        for name in self.VIEW_ORDER:
            items.append({
                "name": name,
                "label": self.VIEW_LABELS.get(name, name),
                "present": name in self.objects,
                "under_construction": name in ("llcIncomeStmt", "llcBalanceSheet"),
            })
        return items

    def _under_construction(self, obj_type: str) -> bool:
        return obj_type in ("llcIncomeStmt", "llcBalanceSheet")

    def _default_columns(self, obj_type: str) -> List[str]:
        defaults = {
            "llcAssets": ["acctType", "oID", "name", "desc", "category", "amount", "date", "notes"],
            "llcExpRev": ["acctType", "oID", "date", "desc", "type", "amount", "notes"],
        }
        return defaults.get(obj_type, ["oID", "name"])

    def _supports_record_views(self, obj_type: str) -> bool:
        return obj_type in ("llcAssets", "llcExpRev")

    def _normalize_view_mode(self, value: str) -> str:
        value = (value or "all").strip().lower()
        alias_map = {
            "by account": "account",
            "account": "account",
            "acct": "account",
            "by property": "property",
            "property": "property",
            "prop": "property",
            "by all": "all",
            "all": "all",
        }
        return alias_map.get(value, "all")

    def _get_columns(self, rows: List[Dict[str, Any]], obj_type: str, view_mode: str = "all") -> List[str]:
        if self._supports_record_views(obj_type):
            mode = self._normalize_view_mode(view_mode)
            return list(self.RECORD_VIEW_OPTIONS[mode])

        cols = set()
        for row in rows:
            if isinstance(row, dict):
                cols.update(row.keys())

        if not cols:
            return self._default_columns(obj_type)

        ordered = sorted(cols)
        if "acctType" in ordered:
            ordered.remove("acctType")
            ordered = ["acctType"] + ordered
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
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        if value is None:
            return ""
        return str(value)

    def _stats_rows(self, stats: Dict[str, Any]) -> List[Dict[str, str]]:
        rows = []
        for key, value in (stats or {}).items():
            rows.append({
                "key": str(key),
                "value": self._format_stat_value(value),
            })
        return rows

    def _parse_payload(self, payload, default):
        if payload is None or payload == "":
            return default
        if isinstance(payload, (dict, list)):
            return payload
        return json.loads(payload)

    def _row_id(self, row: Dict[str, Any], index: int) -> str:
        return str(row.get("id", row.get("oID", index)))

    def _view_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for idx, row in enumerate(rows):
            result.append({
                "_row_index": idx,
                "_record_id": self._row_id(row, idx),
                "data": row,
            })
        return result

    def _bind_routes(self):
        app = self.app

        @app.route("/")
        def home():
            session_views = []
            seen = set()
            for key, wk in self.eSession.oDict.items():
                obj_name = self._canonical_name(getattr(getattr(wk, "o", None), "oID", key))
                stamp = (obj_name, wk.FN(), wk.o.FN())
                if stamp in seen:
                    continue
                seen.add(stamp)
                session_views.append({
                    "name": obj_name,
                    "raw_name": key,
                    "working_file": wk.FN(),
                    "object_file": wk.o.FN(),
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

            if manager is None or self._under_construction(obj_type):
                meta = manager.meta() if manager else {"objectName": obj_type}
                return render_template(
                    "construction.html",
                    title=obj_type,
                    obj_type=obj_type,
                    meta=meta
                )

            view_mode = self._normalize_view_mode(request.args.get("viewMode", "all"))
            rows = manager.load()
            columns = self._get_columns(rows, obj_type, view_mode=view_mode)
            stats = manager.stats()

            return render_template(
                "table_view.html",
                title=self.title,
                obj_type=obj_type,
                rows=self._view_rows(rows),
                raw_rows=rows,
                columns=columns,
                stats=stats,
                stats_rows=self._stats_rows(stats),
                meta=manager.meta(),
                display_scalar=self._display_scalar,
                view_mode=view_mode,
                show_view_options=self._supports_record_views(obj_type),
            )

        @app.route("/api/<obj_type>/cmd", methods=["GET", "POST"])
        def api_cmd(obj_type: str):
            obj_type = self._canonical_name(obj_type)
            manager = self.objects.get(obj_type)

            if manager is None:
                return jsonify({"ok": False, "error": f"Unknown object type: {obj_type}"}), 404

            cmd = request.values.get("cmd", "load")

            if cmd == "load":
                return jsonify({"ok": True, "data": manager.load()})

            if cmd == "list":
                return jsonify({"ok": True, "data": manager.list()})

            if cmd == "stats":
                return jsonify({"ok": True, "data": manager.stats()})

            if cmd == "meta":
                return jsonify({"ok": True, "data": manager.meta()})

            if cmd == "save":
                payload = self._parse_payload(request.values.get("payload", "[]"), [])
                return jsonify({"ok": True, "data": manager.save(payload)})

            if cmd == "save_object":
                payload = request.values.get("payload")
                payload = self._parse_payload(payload, manager.load()) if payload is not None else manager.load()
                return jsonify({"ok": True, "data": manager.save_object(payload)})

            if cmd == "reset_from_object":
                return jsonify({"ok": True, "data": manager.reset_from_object()})

            if self._under_construction(obj_type):
                return jsonify({"ok": False, "error": "View Under Construction"}), 400

            if cmd == "add":
                payload = self._parse_payload(request.values.get("payload", "{}"), {})
                rows = manager.load()
                rows.append(payload)
                saved = manager.save(rows)
                return jsonify({"ok": True, "data": saved})

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

                saved = manager.save(rows)
                return jsonify({"ok": True, "data": saved})

            if cmd == "delete":
                record_id = request.values.get("id")
                rows = manager.load()
                new_rows = []
                for i, row in enumerate(rows):
                    if self._row_id(row, i) != str(record_id):
                        new_rows.append(row)
                saved = manager.save(new_rows)
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