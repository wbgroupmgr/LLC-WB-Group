"""Flask route bindings for the ExpenseAgent service."""
from flask import jsonify, request

from ledger.expenseAgent import ExpenseAgent

_agent = ExpenseAgent()


def bind_expAgent_routes(app, objects, sanitize):

    @app.route("/api/expAgent/normalize", methods=["POST"])
    def expAgent_normalize():
        try:
            body = request.get_json(force=True) or {}
            rows = body.get("rows", [])
            normalized, summary = _agent.normalize(rows)
            return jsonify({"ok": True, "rows": normalized, "summary": summary})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
