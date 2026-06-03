"""
IRSFormsAgent — Tier 3 common services base class.

Inherited by all section agents and Form1065Agent.
No form-specific knowledge lives here.
"""
from __future__ import annotations
from pathlib import Path
from typing  import Any, Dict, List, Optional


class IRSFormsAgent:
    """Common services reused by every form agent and section agent."""

    # ── State constants ──────────────────────────────────────────────────────
    GO           = 'GO'
    NEEDS_FIXING = 'NEEDS_FIXING'
    NOT_STARTED  = 'NOT_STARTED'
    DRAFT        = 'DRAFT'

    # ── Severity constants ───────────────────────────────────────────────────
    ERROR = 'ERROR'
    WARN  = 'WARN'
    INFO  = 'INFO'

    def __init__(self, llc, tax_year: Optional[int] = None):
        self.llc      = llc
        self.tax_year = tax_year or self._detect_year()

    def _detect_year(self) -> int:
        try:
            return int(getattr(self.llc, 'F1065', {}).get('tax_year', 2025))
        except Exception:
            return 2025

    # ── Completeness ─────────────────────────────────────────────────────────

    def audit_fill_completeness(self, fill_dict: Dict[str, Any],
                                key_prefixes: List[str]) -> Dict[str, int]:
        """Count filled/blank/complex for the given logical-key prefixes."""
        filled = blank = complex_ = 0
        for k, v in fill_dict.items():
            if not any(k.startswith(p) for p in key_prefixes):
                continue
            if v is None or v == '':
                blank += 1
            elif str(v).strip().lower() == 'complex':
                complex_ += 1
            else:
                filled += 1
        return {'filled': filled, 'blank': blank, 'complex': complex_,
                'total': filled + blank + complex_}

    # ── Issue builder ────────────────────────────────────────────────────────

    def format_issue(self, rule_id: str, severity: str, message: str,
                     irs_cite: str, action: str,
                     auto_fix: bool = False,
                     fids: list = None,
                     suggested_mapping: dict = None) -> Dict[str, Any]:
        """
        fids: logical key(s) in Form1065_namespace, e.g. ['B_PR_1', 'B_PR_2']
        suggested_mapping: {fid, src, path} — pre-fill hint for the Aid dialog
        """
        return {
            'rule_id':           rule_id,
            'severity':          severity,
            'message':           message,
            'irs_cite':          irs_cite,
            'action':            action,
            'auto_fix':          auto_fix,
            'fids':              fids or [],
            'suggested_mapping': suggested_mapping or {},
        }

    # ── Session builder ──────────────────────────────────────────────────────

    def build_bookkeeper_session(self, issue_list: List[Dict]) -> Dict[str, Any]:
        halt    = [i for i in issue_list if i['severity'] == self.ERROR]
        resolve = [i for i in issue_list if i['severity'] == self.WARN]
        review  = [i for i in issue_list if i['severity'] == self.INFO]
        return {
            'halt':          halt,
            'resolve':       resolve,
            'review':        review,
            'halt_count':    len(halt),
            'resolve_count': len(resolve),
            'review_count':  len(review),
        }

    # ── State from issue list ────────────────────────────────────────────────

    def state_from_issues(self, issue_list: List[Dict]) -> str:
        if any(i['severity'] == self.ERROR for i in issue_list):
            return self.NEEDS_FIXING
        return self.GO

    # ── Path helpers ─────────────────────────────────────────────────────────

    def _forms_dir(self) -> Optional[Path]:
        try:
            from ledger.setup_paths import IRS_FORMS_DIR
            if IRS_FORMS_DIR:
                return Path(IRS_FORMS_DIR)
        except Exception:
            pass
        return None

    def _agent_work_dir(self) -> Optional[Path]:
        d = self._forms_dir()
        if d is None:
            return None
        p = d / '.agent_work'
        p.mkdir(parents=True, exist_ok=True)
        return p
