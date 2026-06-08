"""
irs/formDiagState.py
---------------------
Pipeline integrity record for the BookToIRS pipeline.

Manages FormXXXX_diagnose_state.json — one file per form per year, stored at:
  books/{year}/Forms/FormXXXX_diagnose_state.json

Schema (top-level):
  form, llc, year, generated_at, llc_sha, bus_sha
  sections: { section_id → SectionState }
  regressions: [ section_id, ... ]   # ids where verify_state == REGRESSION

SectionState:
  id, name, agent_state   (UNKNOWN | GO | NEEDS_FIXING | NOT_STARTED)
  verify_state            (UNCONFIRMED | VERIFIED | REGRESSION)
  verified_at             (ISO timestamp or null)
  verified_sha            ({llc, bus} or null)
  fields_hash             (sha256 of sorted fid+value pairs)
  fields                  ([{fid, uas, value}, ...])

verify_state logic:
  UNCONFIRMED  — default; section has not been human-verified
  VERIFIED     — bookkeeper clicked VERIFY; field values match stored hash
  REGRESSION   — was VERIFIED; next regenerate() found a different fields_hash

Key public API:
  load(form_name, forms_dir)        → dict (empty if no file)
  save(state, forms_dir)            → None
  build_state(diag_data, llc_sha, bus_sha, prev_state) → new state dict
  verify_section(section_id, forms_dir, form_name, llc_sha, bus_sha) → saved state
  get_regression_report(state)      → list of {section_id, name, old_fields, new_fields}
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── verify_state constants ─────────────────────────────────────────────────────
VS_UNCONFIRMED = "UNCONFIRMED"
VS_VERIFIED    = "VERIFIED"
VS_REGRESSION  = "REGRESSION"


# ── helpers ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _git_sha(repo_dir: Any) -> str:
    """Return the short HEAD SHA for the git repo at repo_dir, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True, text=True, timeout=5,
        )
        sha = result.stdout.strip()
        return sha if sha else "unknown"
    except Exception:
        return "unknown"


def fields_hash(fields: List[Dict]) -> str:
    """Stable sha256 of sorted (fid, str(value)) pairs.  Blank values excluded."""
    pairs = sorted(
        (f["fid"], str(f.get("value") or ""))
        for f in fields
        if f.get("value") is not None and str(f.get("value", "")).strip() != ""
    )
    payload = json.dumps(pairs, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _state_path(form_name: str, forms_dir: Any) -> Path:
    return Path(forms_dir) / f"{form_name}_diagnose_state.json"


# ── I/O ────────────────────────────────────────────────────────────────────────

def load(form_name: str, forms_dir: Any) -> Dict:
    p = _state_path(form_name, forms_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(state: Dict, forms_dir: Any) -> None:
    p = _state_path(state["form"], forms_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ── BUS / LLC repo path resolution ─────────────────────────────────────────────

def get_llc_repo_dir(llc: Any) -> Optional[Path]:
    """Resolve the llcRentalTracker repo root from the llc object."""
    try:
        from ledger import setup_paths as sp
        top = getattr(sp, "TOP", None)
        if top:
            return Path(str(top))
    except Exception:
        pass
    return None


def get_bus_repo_dir(forms_dir: Any) -> Optional[Path]:
    """Walk up from forms_dir to find the BUS git repo root."""
    p = Path(str(forms_dir)).resolve()
    for _ in range(6):
        if (p / ".git").exists():
            return p
        p = p.parent
    return None


# ── State builder ──────────────────────────────────────────────────────────────

def build_state(
    diag_data: Dict,
    llc_sha:   str,
    bus_sha:   str,
    prev_state: Dict,
) -> Dict:
    """
    Build a fresh diagnose_state dict from IRSDiagAgent.diagnose() output.

    Preserves VERIFIED state for sections whose fields_hash is unchanged.
    Sets REGRESSION for VERIFIED sections whose fields_hash changed.
    All other sections → UNCONFIRMED.

    Returns the new state dict (caller must call save() to persist).
    """
    prev_sections: Dict[str, Dict] = (prev_state or {}).get("sections", {})
    new_sections:  Dict[str, Dict] = {}
    regressions:   List[str]       = []

    for sec in diag_data.get("sections", []):
        sec_id = sec["id"]
        cur_fields = [
            {"fid": f["fid"], "uas": f.get("uas", ""), "value": f.get("value")}
            for f in sec.get("fields", [])
        ]
        cur_hash = fields_hash(cur_fields)
        prev_sec = prev_sections.get(sec_id, {})
        prev_vs  = prev_sec.get("verify_state", VS_UNCONFIRMED)
        prev_hash = prev_sec.get("fields_hash", "")

        if prev_vs == VS_VERIFIED:
            if cur_hash == prev_hash:
                # Still matches — carry forward VERIFIED
                vs = VS_VERIFIED
                verified_at  = prev_sec.get("verified_at")
                verified_sha = prev_sec.get("verified_sha")
            else:
                # Previously verified but values changed → REGRESSION
                vs = VS_REGRESSION
                verified_at  = prev_sec.get("verified_at")
                verified_sha = prev_sec.get("verified_sha")
                regressions.append(sec_id)
        else:
            vs = VS_UNCONFIRMED
            verified_at  = None
            verified_sha = None

        new_sections[sec_id] = {
            "id":           sec_id,
            "name":         sec.get("name", sec_id),
            "agent_state":  "UNKNOWN",
            "verify_state": vs,
            "verified_at":  verified_at,
            "verified_sha": verified_sha,
            "fields_hash":  cur_hash,
            "fields":       cur_fields,
        }

    return {
        "form":        diag_data.get("form", ""),
        "llc":         diag_data.get("llc", ""),
        "year":        diag_data.get("year"),
        "generated_at": _now_iso(),
        "llc_sha":     llc_sha,
        "bus_sha":     bus_sha,
        "sections":    new_sections,
        "regressions": regressions,
    }


# ── Bookkeeper verify ──────────────────────────────────────────────────────────

def verify_section(
    section_id: str,
    form_name:  str,
    forms_dir:  Any,
    llc_sha:    str = "unknown",
    bus_sha:    str = "unknown",
) -> Dict:
    """
    Mark section_id as VERIFIED in the saved diagnose_state.

    Loads the current state, updates the section, saves, and returns the state.
    Raises KeyError if section_id is not found.
    """
    state = load(form_name, forms_dir)
    if not state:
        raise ValueError(f"No diagnose_state found for {form_name} at {forms_dir}")
    sections = state.get("sections", {})
    if section_id not in sections:
        raise KeyError(f"Section '{section_id}' not found in {form_name} diagnose_state")

    sec = sections[section_id]
    sec["verify_state"] = VS_VERIFIED
    sec["verified_at"]  = _now_iso()
    sec["verified_sha"] = {"llc": llc_sha, "bus": bus_sha}

    # Remove from regressions list if it was there
    state["regressions"] = [r for r in state.get("regressions", []) if r != section_id]

    save(state, forms_dir)

    # Update bookNS integrity record so future checks reflect this verified state
    try:
        update_integrity(form_name, forms_dir, bus_sha)
    except Exception:
        pass

    return state


# ── Regression report ─────────────────────────────────────────────────────────

# ── bookNS integrity ──────────────────────────────────────────────────────────
#
# bookNS_integrity.json lives in the LLC repo at irs/bookNS_integrity.json.
# It records the SHA256 of each bookNS_{src}.json Form{N} section at the time
# the section was last VERIFIED by the bookkeeper.
#
# Purpose: detect when BUS bookNS data diverges from LLC Python code expectations
# without running the full pipeline.  Checked on every regenerate() call.
#
# Schema: { "Form4562": { "bookNS_IS": "sha256...", "bookNS_BS": "...",
#                          "verified_at": "...", "bus_sha": "..." } }

_INTEGRITY_FILE = Path(__file__).parent / "bookNS_integrity.json"


def _bookns_section_hash(bookns_path: Any, form_name: str) -> str:
    """SHA256 of the Form{N} section list in a bookNS JSON file."""
    try:
        d = json.loads(Path(str(bookns_path)).read_text(encoding="utf-8"))
        section = d.get(form_name, [])
        payload = json.dumps(section, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
    except Exception:
        return "error"


def load_integrity() -> Dict:
    if not _INTEGRITY_FILE.exists():
        return {}
    try:
        return json.loads(_INTEGRITY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_integrity(data: Dict) -> None:
    _INTEGRITY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def update_integrity(form_name: str, forms_dir: Any, bus_sha: str) -> Dict:
    """Record current bookNS section hashes for form_name.
    Called by verify_section() so the integrity record reflects a verified state."""
    forms_path = Path(str(forms_dir))
    integrity  = load_integrity()
    record: Dict[str, str] = {}
    for src in ("IS", "BS", "Profile", "GL"):
        p = forms_path / f"bookNS_{src}.json"
        record[f"bookNS_{src}"] = _bookns_section_hash(p, form_name)
    record["verified_at"] = _now_iso()
    record["bus_sha"]     = bus_sha
    integrity[form_name]  = record
    save_integrity(integrity)
    return integrity


def check_integrity(form_name: str, forms_dir: Any) -> List[str]:
    """Compare current bookNS section hashes vs the saved integrity record.
    Returns list of source names that differ (empty = all match or no record)."""
    integrity = load_integrity()
    record    = integrity.get(form_name)
    if not record:
        return []
    forms_path = Path(str(forms_dir))
    mismatches: List[str] = []
    for src in ("IS", "BS", "Profile", "GL"):
        key = f"bookNS_{src}"
        expected = record.get(key, "")
        if not expected:
            continue
        p = forms_path / f"bookNS_{src}.json"
        actual = _bookns_section_hash(p, form_name)
        if actual != expected:
            mismatches.append(src)
    return mismatches


def get_regression_report(state: Dict) -> List[Dict]:
    """Return list of {section_id, name, verified_at, verified_sha} for REGRESSION sections."""
    out = []
    for sec_id, sec in (state.get("sections") or {}).items():
        if sec.get("verify_state") == VS_REGRESSION:
            out.append({
                "section_id":    sec_id,
                "name":          sec.get("name", sec_id),
                "verified_at":   sec.get("verified_at"),
                "verified_sha":  sec.get("verified_sha"),
                "fields_hash":   sec.get("fields_hash"),
                "fields":        sec.get("fields", []),
            })
    return out
