"""
irs/startupCheck.py
-------------------
Startup artifact integrity sweep.

Called by wsCmd.py before Flask accepts requests.  Four ordered checks:

  1. Clear transient session-state files (.agent_work/*_session_state.json).
     These are meaningless after a server restart; stale state here caused
     FormSchK1 and Form8825 wrong-value incidents.

  2. Check namespace JSON vs IRS template PDF.
     If *_namespace.json is older than *_IRS.pdf, the PDF template was
     replaced after the namespace was generated — warn loudly.

  3. Check FILL.pdf vs bookNS files.
     If any bookNS_*.json is newer than a form's FILL.pdf, the mappings
     changed and the PDF output is stale — warn loudly.  This is the
     most common stale-artifact failure mode (Form1065, f279, etc.).

  4. Check bookNS integrity hashes (extends formDiagState.check_integrity).
     Detects cross-repo bookNS drift without running the full pipeline.

Working temp files (/tmp/*_temp.json) are NOT handled here: utilWorkingDB.load()
already auto-refreshes them when the real DB is newer (commit 6585d6e).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple


_KNOWN_FORMS   = ("Form1065", "Form8825", "Form4562", "Sch_K1")
_BOOKNS_SRCS   = ("IS", "BS", "GL", "Profile")
_SESSION_GLOB  = "*_session_state.json"
_GRACE_SECS    = 60   # ignore mtime deltas smaller than this (same-run writes)


# ── internal helpers ──────────────────────────────────────────────────────────

def _age_str(newer_mtime: float, older_mtime: float) -> str:
    """Human-readable age delta, e.g. '3d 14h'."""
    secs = int(newer_mtime - older_mtime)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m      = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


# ── Check 1: clear session-state files ───────────────────────────────────────

def _clear_session_states(forms_dir: Path) -> List[str]:
    """Delete .agent_work/*_session_state.json files.

    Session state is only valid for the browser session that created it.
    After any server restart these files are stale by definition.
    """
    agent_work = forms_dir / ".agent_work"
    if not agent_work.is_dir():
        return ["[OK]      session-state: .agent_work dir not found — nothing to clear"]

    cleared = []
    for p in sorted(agent_work.glob(_SESSION_GLOB)):
        try:
            p.unlink()
            cleared.append(p.name)
        except OSError as exc:
            cleared.append(f"WARN: could not delete {p.name}: {exc}")

    if cleared:
        names = ", ".join(cleared)
        return [f"[CLEARED] session-state: {names}"]
    return ["[OK]      session-state: no stale session files found"]


# ── Check 2: namespace JSON vs IRS PDF template ───────────────────────────────

def _check_namespaces(forms_dir: Path) -> List[str]:
    """Warn if any *_namespace.json is older than its *_IRS.pdf template."""
    lines = []
    all_ok = True
    for form in _KNOWN_FORMS:
        ns_path  = forms_dir / f"{form}_namespace.json"
        irs_path = forms_dir / f"{form}_IRS.pdf"
        if not irs_path.exists():
            continue
        if not ns_path.exists():
            lines.append(f"[WARN]    namespace {form}: missing — will be rebuilt on first regenerate")
            all_ok = False
            continue
        ns_mt  = _mtime(ns_path)
        irs_mt = _mtime(irs_path)
        if irs_mt > ns_mt:
            age = _age_str(irs_mt, ns_mt)
            lines.append(
                f"[WARN]    namespace {form}: IRS template is {age} newer than namespace JSON"
                f" — run Aid → namespace to rebuild"
            )
            all_ok = False
    if all_ok:
        lines.append("[OK]      namespace: all current vs IRS templates")
    return lines


# ── Check 3: FILL.pdf vs bookNS files ────────────────────────────────────────

def _check_fill_staleness(forms_dir: Path) -> List[str]:
    """Warn if any bookNS_*.json is newer than a form's FILL.pdf."""
    lines = []
    all_ok = True

    # bookNS files affect ALL forms; find the newest one per source
    bookns_mtimes: List[Tuple[str, float]] = []
    for src in _BOOKNS_SRCS:
        p = forms_dir / f"bookNS_{src}.json"
        if p.exists():
            bookns_mtimes.append((f"bookNS_{src}.json", _mtime(p)))

    if not bookns_mtimes:
        return ["[OK]      FILL.pdf: no bookNS files found — skipping staleness check"]

    for form in _KNOWN_FORMS:
        # Sch_K1 produces per-member FILLs; check the base one
        fill_path = forms_dir / f"{form}_FILL.pdf"
        if not fill_path.exists():
            continue
        fill_mt = _mtime(fill_path)
        stale_src: List[str] = []
        for src_name, src_mt in bookns_mtimes:
            if src_mt - fill_mt > _GRACE_SECS:
                age = _age_str(src_mt, fill_mt)
                stale_src.append(f"{src_name} ({age} newer)")
        if stale_src:
            lines.append(
                f"[WARN]    FILL.pdf {form}: STALE — {', '.join(stale_src)}"
                f" — run Guided Review → REGENERATE"
            )
            all_ok = False

    if all_ok:
        lines.append("[OK]      FILL.pdf: all current vs bookNS files")
    return lines


# ── Check 4: bookNS integrity hashes ─────────────────────────────────────────

def _check_bookns_integrity(forms_dir: Path) -> List[str]:
    """Run formDiagState.check_integrity_at_startup() for all known forms."""
    try:
        from irs.formDiagState import check_integrity_at_startup
    except ImportError:
        return ["[SKIP]    bookNS integrity: formDiagState not importable"]

    lines = []
    results = check_integrity_at_startup(forms_dir)
    for form, mismatches in results.items():
        lines.append(
            f"[WARN]    bookNS integrity {form}: {', '.join(mismatches)} differ"
            f" from last VERIFIED state — cross-repo bookNS may be out of sync"
        )
    if not results:
        lines.append("[OK]      bookNS integrity: all forms match verified state")
    return lines


# ── Public entry point ────────────────────────────────────────────────────────

def startup_integrity_sweep(forms_dir) -> None:
    """
    Run all four startup integrity checks and print results to stdout.

    Call this from wsCmd.py before Flask starts accepting requests.
    ``forms_dir`` is typically setup_paths.IRS_FORMS_DIR (books/{year}/Forms/).
    """
    forms_path = Path(str(forms_dir))

    lines: List[str] = []
    lines += _clear_session_states(forms_path)
    lines += _check_namespaces(forms_path)
    lines += _check_fill_staleness(forms_path)
    lines += _check_bookns_integrity(forms_path)

    _BAR = "─" * 62
    print()
    print(f"── STARTUP INTEGRITY SWEEP {_BAR}")
    for ln in lines:
        print(f"   {ln}")
    print(f"   {_BAR}")
    print()
