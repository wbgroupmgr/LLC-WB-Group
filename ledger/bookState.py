"""
ledger/bookState.py — BookState: a comparable fingerprint of the RealDB
accounting files, per issue #53.

Two BookState snapshots — RealDB "right now" vs. a BookView's cached "source
state" from whenever it was last built — are structurally identical and can
be diffed directly. This replaces the ad hoc single-file mtime check in
utilWorkingDB.load() with one reusable, inspectable object, mirroring the
pattern irs/bookNS_integrity.json already uses one layer further downstream
(bookNS -> FILL.pdf): SHA256 at last-known-good state, compared on access.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

RECORD_OBJECTS = ("llcAssets", "llcExpRev", "llcPayables", "llcReceivables")


def _records_of(raw: Any) -> list:
    """Both flat-array and {"records": [...], "LogHistory": [...]} schemas are in use."""
    if isinstance(raw, dict):
        return raw.get("records", [])
    return raw if isinstance(raw, list) else []


def _file_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"sha256": None, "mtime": None, "recordCount": 0, "exists": False}
    data = path.read_bytes()
    try:
        record_count = len(_records_of(json.loads(data)))
    except Exception:
        record_count = None
    return {
        "sha256":      hashlib.sha256(data).hexdigest(),
        "mtime":       datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "recordCount": record_count,
        "exists":      True,
    }


def compute(llc) -> Dict[str, Any]:
    """Compute a BookState snapshot from the RealDB files as they exist right now."""
    from ledger import setup_paths as _sp
    accts_dir = Path(_sp.ACCTS_DIR)
    obj_name  = getattr(llc, "objName", "")
    objects: Dict[str, Any] = {}
    for oid in RECORD_OBJECTS:
        objects[oid] = _file_state(accts_dir / f"{oid}_{obj_name}.json")
    return {
        "objects":    objects,
        "computedAt": datetime.datetime.now().isoformat(),
    }


def diff(a: Dict[str, Any] | None, b: Dict[str, Any] | None) -> List[str]:
    """Return object names whose sha256 differs between two BookStates."""
    if a is None or b is None:
        return list(RECORD_OBJECTS) if a is not b else []
    a_objs, b_objs = a.get("objects", {}), b.get("objects", {})
    return [oid for oid in RECORD_OBJECTS
            if a_objs.get(oid, {}).get("sha256") != b_objs.get(oid, {}).get("sha256")]


# ── Append-only log (issue #57 — periodic / monthly reconciliation checkpoint) ──

def log_path() -> Path:
    from ledger import setup_paths as _sp
    return Path(_sp.ACCTS_DIR) / "bookState_log.json"


def append_log(state: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    """Append a BookState snapshot to the append-only log. Returns the entry written."""
    p = log_path()
    try:
        log = json.loads(p.read_text()) if p.exists() else []
    except Exception:
        log = []
    entry = dict(state)
    entry["note"] = note
    log.append(entry)
    p.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return entry


def load_log() -> List[Dict[str, Any]]:
    p = log_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def last_logged() -> Dict[str, Any] | None:
    log = load_log()
    return log[-1] if log else None
