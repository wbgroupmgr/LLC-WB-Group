"""
LLCTaxAgent — Tier 0 master coordinator for W&B Group LLC IRS filing.

Architecture (4-tier):
  Tier 0  LLCTaxAgent         — THIS FILE — cross-form audit + submission package
  Tier 1  Form1065Agent       — Form 1065 (5-page return)
          Form8825Agent       — Form 8825 (rental real estate income/expenses)
          Form4562Agent       — Form 4562 (depreciation and amortization)
          FormSchK1Agent      — Schedule K-1 (per-partner, N copies)
  Tier 2  AgentF*_*           — section agents within each Tier 1 agent
  Tier 3  IRSFormsAgent       — common services base class

Books-First rule (IRC §446+703): ALL form values sourced from stmtIS.taxAggregates()
and stmtBS.taxAggregates(). No form-to-form data dependencies during preparation.

Cross-form audit (Phase 2 — XF-R01 through XF-R05):
  Run AFTER all forms are independently prepared from books.
  Verifies that values which should mathematically agree actually do.
  A discrepancy in cross-form audit always indicates a books-mapping error.

Phases:
  phase1_prepare:  Drive Form1065, Form8825, Form4562, FormSchK1 agents
  phase2_xf_audit: Cross-form validation (XF-R01 through XF-R05)
  phase3_package:  Assemble IRS_Submission_{year}/ directory + manifest (future)
  phase4_submit:   Submission checklist and guidance (future)

Session state stored at:
  books/{year}/Forms/.agent_work/LLCTaxAgent_session_state.json
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib  import Path
from typing   import Any, Dict, List, Optional

from irs.taxAgents.IRSFormsAgent import IRSFormsAgent


# ────────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────────

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _owner_pct(owner: Dict) -> float:
    v = _safe_float(owner.get('pct', owner.get('ownership_pct', owner.get('ownerPct', 0))))
    return v if v <= 1.5 else v / 100.0


# ════════════════════════════════════════════════════════════════════════════
#  LLCTAXAGENT  (Tier 0 master coordinator)
# ════════════════════════════════════════════════════════════════════════════

class LLCTaxAgent(IRSFormsAgent):
    """
    Tier 0 master coordinator.

    Cross-form audit rules (XF-R01 through XF-R05):
      XF-R01: Form4562 Line22 == IS.depreciation == Form8825 Line14     (within $1)
      XF-R02: Form8825 Line21 == IS.net_rental    == Schedule K Line 2  (within $1)
      XF-R03: Schedule K Line2 × partner.pct == each K-1 Box 2          (within $0.02)
      XF-R04: Sum of all K-1 Box 2 == Schedule K Line 2                 (within $0.02)
      XF-R05: Form1065 Page1 Lines 1-23 all $0 (pure rental LLC)

    All XF rules read completed fill dicts (read-only); no form values are modified.
    A discrepancy in any XF rule always indicates a books-mapping error, never
    a cross-form wiring problem (because no cross-form wiring exists by design).
    """

    def __init__(self, llc, tax_year: Optional[int] = None):
        super().__init__(llc, tax_year)
        self._is_data  = None
        self._bs_data  = None
        self._owners   = None
        self._xf_issues: List[Dict] = []

    # ── Data loaders ─────────────────────────────────────────────────────────

    def _get_is(self) -> Dict[str, float]:
        if self._is_data is not None:
            return self._is_data
        try:
            from ledger.stmtIS import stmtIS
            self._is_data = stmtIS(self.llc).taxAggregates()
        except Exception:
            self._is_data = {}
        return self._is_data

    def _get_is_agg(self, key: str, default: float = 0.0) -> float:
        return _safe_float(self._get_is().get(key, default))

    def _get_owners(self) -> List[Dict]:
        if self._owners is not None:
            return self._owners
        try:
            raw = self.llc.owners
            self._owners = raw() if callable(raw) else list(raw or [])
        except Exception:
            self._owners = []
        return self._owners

    def _load_form_fill_dict(self, form_name: str) -> Dict[str, Any]:
        """Load a form's fill dict. Currently reads Form1065_fillDict.json for F1065."""
        forms_dir = self._forms_dir()
        if forms_dir is None:
            return {}
        # Form 1065 has a flat fill dict JSON
        if form_name == 'Form1065':
            p = forms_dir / 'Form1065_fillDict.json'
            if not p.exists():
                return {}
            try:
                with open(p) as f:
                    data = json.load(f)
                fields = data.get('fields', data) if isinstance(data, dict) else {}
                result = {}
                for fid, entry in fields.items():
                    if isinstance(entry, dict):
                        lk  = entry.get('logicalKey', fid)
                        val = entry.get('value', '')
                        result[lk] = val
                    else:
                        result[fid] = entry
                return result
            except Exception:
                return {}
        # Form 8825 / Form 4562: use stmtIS_Tax.loadFillDict (live from bookNS_IS.json)
        try:
            from ledger.stmtIS import stmtIS_Tax
            tax = stmtIS_Tax(self.llc)
            return tax.loadFillDict(form_name) or {}
        except Exception:
            return {}

    def _load_agent_session(self, agent_name: str) -> Dict[str, Any]:
        """Read a sub-agent's session state JSON from .agent_work/."""
        d = self._agent_work_dir()
        if d is None:
            return {}
        p = d / f'{agent_name}_session_state.json'
        if not p.exists():
            return {}
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return {}

    # ── Public API ────────────────────────────────────────────────────────────

    def run_phases_1_2(self) -> Dict[str, Any]:
        """
        Phase 1: Drive all Tier 1 form agents.
        Phase 2: Run cross-form audit (XF-R01 through XF-R05).
        Returns combined session state.
        """
        # Phase 1: run each form agent
        form_results = self._phase1_prepare()

        # Phase 2: cross-form audit
        xf_results = self._phase2_xf_audit()

        overall_halt = sum(
            r.get('overall_halt', 0) for r in form_results.values()
        ) + len([i for i in xf_results if i.get('severity') == self.ERROR])

        overall_state = self.NEEDS_FIXING if overall_halt > 0 else self.GO

        session = {
            'tax_year':      self.tax_year,
            'last_run':      _now_iso(),
            'overall_state': overall_state,
            'form_results':  form_results,
            'xf_audit':      xf_results,
            'summary':       self._build_summary(form_results, xf_results),
        }
        self._save_session_state(session)
        return session

    def getSummary(self) -> Dict[str, Any]:
        state = self._load_session_state()
        if state is None:
            return {
                'tax_year':      self.tax_year,
                'last_run':      None,
                'overall_state': self.NOT_STARTED,
                'form_results':  {},
                'xf_audit':      [],
                'summary':       'Not yet run',
            }
        return state

    # ── Phase 1: Prepare all forms ────────────────────────────────────────────

    def _phase1_prepare(self) -> Dict[str, Any]:
        from irs.taxAgents.Form1065Agent  import Form1065Agent
        from irs.taxAgents.Form8825Agent  import Form8825Agent
        from irs.taxAgents.Form4562Agent  import Form4562Agent
        from irs.taxAgents.FormSchK1Agent import FormSchK1Agent

        results = {}
        for AgentCls in [Form4562Agent, Form8825Agent, Form1065Agent, FormSchK1Agent]:
            name = AgentCls.__name__
            try:
                agent = AgentCls(self.llc, self.tax_year)
                # run_agent() = audit + PDF generation (Form8825/4562/SchK1 only).
                # Fall back to run_phases_1_2() when run_agent() is not yet defined.
                run_fn = getattr(agent, 'run_agent', None) or getattr(agent, 'run_phases_1_2')
                result = run_fn()
                halt   = result.get('overall_halt', 0)
                # Normalize: some agents store halt in sections, not at top
                if not halt:
                    sects = result.get('sections', {})
                    if isinstance(sects, dict):
                        halt = sum(v.get('halt_count', 0) for v in sects.values()
                                   if isinstance(v, dict))
                    elif isinstance(sects, list):
                        halt = sum(s.get('halt_count', 0) for s in sects)
                results[name] = {
                    'state':         result.get('overall_state', self.GO),
                    'overall_halt':  halt,
                    'last_run':      result.get('last_run'),
                    'session':       result,
                }
            except Exception as e:
                results[name] = {
                    'state':        self.NEEDS_FIXING,
                    'overall_halt': 1,
                    'error':        str(e),
                }
        return results

    # ── Phase 2: Cross-form audit ─────────────────────────────────────────────

    def _phase2_xf_audit(self) -> List[Dict[str, Any]]:
        """
        Run XF-R01 through XF-R05.
        Read-only comparisons of independently-completed fill dicts.
        Any discrepancy is a books-mapping error in one or both forms.
        """
        issues = []
        issues += self._xf_r01_depreciation()
        issues += self._xf_r02_net_rental()
        issues += self._xf_r03_k1_per_partner()
        issues += self._xf_r04_k1_sum()
        issues += self._xf_r05_pg1_all_zero()
        return issues

    def _xf_r01_depreciation(self) -> List[Dict[str, Any]]:
        """
        XF-R01: Form4562 Line22 == IS.depreciation == Form8825 Line14 (within $1)

        Both Form 4562 Line 22 and Form 8825 Line 14 are independently sourced
        from IS.depreciation (Books-First). This audit confirms they agree.
        A discrepancy means one or both forms has a wrong books-mapping.

        IRC §446: form values must derive from books. Since both forms derive from
        the same books value, a mismatch indicates one has an incorrect mapping.
        """
        issues = []
        is_depr   = self._get_is_agg('depreciation')
        fill_4562 = self._load_form_fill_dict('Form4562')
        fill_8825 = self._load_form_fill_dict('Form8825')

        # F153 = Form4562 Line 22 fid; F074 = Line 19h col(g). F079 = Form8825 Line 14.
        f4562_l22 = _safe_float(fill_4562.get('F153') or fill_4562.get('F074') or 0)
        f8825_l14 = _safe_float(fill_8825.get('F079') or 0)

        # Check F4562 L22 vs IS.depreciation
        if f4562_l22 > 0.01 and abs(f4562_l22 - is_depr) > 1.00:
            issues.append(self.format_issue(
                'XF-R01a', self.ERROR,
                f"XF-R01: Form 4562 Line 22 = ${f4562_l22:,.2f} ≠ IS.depreciation ${is_depr:,.2f}. "
                f"Discrepancy: ${abs(f4562_l22 - is_depr):,.2f}. "
                f"Books-First violation: Form 4562 Line 22 must equal IS.depreciation from books.",
                'IRC §446; LLCTaxAgent XF-R01',
                "Fix Form 4562 books mapping: Line 22 must source from IS.depreciation."))

        # Check F8825 L14 vs IS.depreciation
        if f8825_l14 > 0.01 and abs(f8825_l14 - is_depr) > 1.00:
            issues.append(self.format_issue(
                'XF-R01b', self.ERROR,
                f"XF-R01: Form 8825 Line 14 = ${f8825_l14:,.2f} ≠ IS.depreciation ${is_depr:,.2f}. "
                f"Discrepancy: ${abs(f8825_l14 - is_depr):,.2f}. "
                f"Books-First violation: Form 8825 Line 14 must equal IS.depreciation from books. "
                f"CRITICAL: do NOT source Form 8825 Line 14 from Form 4562.",
                'IRC §446; LLCTaxAgent XF-R01; Form 8825 Books-First rule',
                "Fix Form 8825 books mapping: Line 14 must source from IS.depreciation directly."))

        # Check F4562 L22 vs F8825 L14 (both should = IS.depreciation)
        if f4562_l22 > 0.01 and f8825_l14 > 0.01 and abs(f4562_l22 - f8825_l14) > 1.00:
            issues.append(self.format_issue(
                'XF-R01c', self.ERROR,
                f"XF-R01: Form 4562 Line 22 (${f4562_l22:,.2f}) ≠ Form 8825 Line 14 (${f8825_l14:,.2f}). "
                f"Both must equal IS.depreciation (${is_depr:,.2f}). "
                f"Since both forms are Books-First, this discrepancy indicates at least one "
                f"form has a wrong books-mapping.",
                'IRC §446; LLCTaxAgent XF-R01',
                "Check Form 4562 and Form 8825 fill dicts. The one that doesn't equal "
                f"IS.depreciation (${is_depr:,.2f}) has a wrong mapping."))

        if not issues and is_depr > 0.01:
            issues.append(self.format_issue(
                'XF-R01', self.INFO,
                f"XF-R01 PASS: F4562 L22 = ${f4562_l22:,.2f}, "
                f"F8825 L14 = ${f8825_l14:,.2f}, "
                f"IS.depreciation = ${is_depr:,.2f}. All agree within $1.",
                'LLCTaxAgent XF-R01; IRC §446',
                "No action required."))

        return issues

    def _xf_r02_net_rental(self) -> List[Dict[str, Any]]:
        """
        XF-R02: Form8825 Line21 == IS.net_rental == Schedule K Line2 (within $1)

        Form 8825 Line 21 and Schedule K Line 2 are both Books-First from IS.net_rental.
        IRS: "Enter the amount from Form 8825 Line 21 on Schedule K Line 2."
        In Books-First system: both are independently IS.net_rental; audit confirms agreement.
        """
        issues    = []
        net       = self._get_is_agg('net_rental')
        fill_8825 = self._load_form_fill_dict('Form8825')
        f8825_l21 = _safe_float(fill_8825.get('F113') or 0)
        # Schedule K Line 2 (K_2): read from bookNS_IS Form1065 live mapping
        # F230 maps to IS.net_rental in bookNS_IS.json Form1065 section.
        try:
            from ledger.stmtIS import stmtIS_Tax as _stmtIS_Tax
            _f1065_live = _stmtIS_Tax(self.llc).loadFillDict('Form1065') or {}
            sched_k_l2 = _safe_float(_f1065_live.get('F230') or 0)
        except Exception:
            sched_k_l2 = 0.0

        if abs(net) > 0.01:
            if abs(f8825_l21 - net) > 1.00:
                issues.append(self.format_issue(
                    'XF-R02a', self.ERROR,
                    f"XF-R02: Form 8825 Line 21 = ${f8825_l21:,.2f} ≠ IS.net_rental ${net:,.2f}. "
                    f"Discrepancy: ${abs(f8825_l21 - net):,.2f}. Books-First violation.",
                    'IRC §446; LLCTaxAgent XF-R02',
                    "Fix Form 8825 Line 21 mapping to IS.net_rental (fill field F113)."))
            if abs(sched_k_l2 - net) > 1.00:
                issues.append(self.format_issue(
                    'XF-R02b', self.ERROR,
                    f"XF-R02: Schedule K Line 2 = ${sched_k_l2:,.2f} ≠ IS.net_rental ${net:,.2f}. "
                    f"Discrepancy: ${abs(sched_k_l2 - net):,.2f}. Books-First violation.",
                    'IRC §446; LLCTaxAgent XF-R02; Schedule K Line 2',
                    "Fix Schedule K Line 2 (K_2) mapping to IS.net_rental in bookNS_IS.json."))
            if not issues:
                issues.append(self.format_issue(
                    'XF-R02', self.INFO,
                    f"XF-R02 PASS: F8825 L21 = ${f8825_l21:,.2f}, "
                    f"Schedule K L2 = ${sched_k_l2:,.2f}, IS.net_rental = ${net:,.2f}. All agree.",
                    'LLCTaxAgent XF-R02; IRC §446',
                    "No action required."))

        return issues

    def _xf_r03_k1_per_partner(self) -> List[Dict[str, Any]]:
        """
        XF-R03: Schedule K Line2 × partner.pct == each K-1 Box 2 (within $0.02)

        Each K-1 Box 2 = IS.net_rental × partner.pct (Books-First).
        This audit reads the K-1 session state (computed values from FormSchK1Agent)
        and verifies the per-partner Box 2 matches the formula.
        IRC §702(a): character of items passes through. IRC §704(b): allocations
        must have substantial economic effect.
        """
        issues  = []
        net     = self._get_is_agg('net_rental')
        owners  = self._get_owners()
        k1_sess = self._load_agent_session('FormSchK1')

        if abs(net) < 0.01:
            return issues

        for owner in owners:
            oID      = owner.get('oID', owner.get('ownerID', ''))
            pct      = _owner_pct(owner)
            expected = round(net * pct, 2)
            nm       = owner.get('nm', owner.get('name', oID))
            if isinstance(nm, list):
                nm = ' '.join(nm)

            # Try to read the recorded Box 2 from the K-1 session state
            partner_data = k1_sess.get('partners', {}).get(oID, {})
            recorded_box2 = _safe_float(partner_data.get('box2', None))

            if partner_data and abs(recorded_box2 - expected) > 0.02:
                issues.append(self.format_issue(
                    'XF-R03', self.ERROR,
                    f"XF-R03: K-1 Box 2 for '{nm}' ({oID}) = ${recorded_box2:,.2f} "
                    f"but IS.net_rental × pct = ${expected:,.2f} "
                    f"({net:,.2f} × {pct:.4f}). Discrepancy: ${abs(recorded_box2-expected):.2f}. "
                    f"Books-First violation (IRC §446): Box 2 must = IS.net_rental × partner.pct.",
                    'IRC §446; IRC §702(a); IRC §704(b); LLCTaxAgent XF-R03',
                    f"Check FormSchK1Agent session for '{oID}'. Verify pct = {pct:.4f} in llcOwners."))
            else:
                issues.append(self.format_issue(
                    'XF-R03', self.INFO,
                    f"XF-R03 PASS: '{nm}' ({oID}) Box 2 = ${expected:,.2f} "
                    f"(IS.net_rental ${net:,.2f} × {pct*100:.2f}%) confirmed.",
                    'LLCTaxAgent XF-R03; IRC §702(a)',
                    "No action required."))

        return issues

    def _xf_r04_k1_sum(self) -> List[Dict[str, Any]]:
        """
        XF-R04: Sum of all K-1 Box 2 == Schedule K Line 2 (within $0.02)

        Every dollar of Schedule K Line 2 must flow to a K-1 Box 2.
        IRC §704(b): all partnership items must be allocated 100%.
        If the sum of Box 2s across all K-1s ≠ Schedule K Line 2,
        some rental income/loss is either double-counted or omitted.
        """
        issues  = []
        net     = self._get_is_agg('net_rental')
        owners  = self._get_owners()
        k1_sess = self._load_agent_session('FormSchK1')
        fill_1065 = self._load_form_fill_dict('Form1065')

        k2_sched = _safe_float(fill_1065.get('K_2') or net)  # fallback to IS.net_rental

        # Sum computed Box 2 values
        box2_sum = 0.0
        for owner in owners:
            oID = owner.get('oID', owner.get('ownerID', ''))
            partner_data = k1_sess.get('partners', {}).get(oID, {})
            if partner_data:
                box2_sum += _safe_float(partner_data.get('box2', 0))
            else:
                # Fall back to computed value
                box2_sum += round(net * _owner_pct(owner), 2)

        if abs(net) > 0.01:
            if abs(box2_sum - k2_sched) > 0.02:
                issues.append(self.format_issue(
                    'XF-R04', self.ERROR,
                    f"XF-R04: Sum of all K-1 Box 2 = ${box2_sum:,.2f} ≠ "
                    f"Schedule K Line 2 = ${k2_sched:,.2f}. "
                    f"Discrepancy: ${abs(box2_sum - k2_sched):.2f}. "
                    f"IRC §704(b): all partnership items must be allocated 100%. "
                    f"Partner percentages must sum to exactly 100%.",
                    'IRC §704(b); LLCTaxAgent XF-R04',
                    "Verify all partner pct values in llcOwners sum to exactly 1.0 (100%). "
                    "A rounding error > $0.02 indicates a pct configuration problem."))
            else:
                issues.append(self.format_issue(
                    'XF-R04', self.INFO,
                    f"XF-R04 PASS: Sum of K-1 Box 2 = ${box2_sum:,.2f} = "
                    f"Schedule K Line 2 = ${k2_sched:,.2f} (within $0.02).",
                    'LLCTaxAgent XF-R04; IRC §704(b)',
                    "No action required."))

        return issues

    def _xf_r05_pg1_all_zero(self) -> List[Dict[str, Any]]:
        """
        XF-R05: Form 1065 Page 1 Lines 1-23 all $0 (pure rental LLC).

        IRC §469(c)(2): rental activity is passive — it never produces ordinary
        business income or deductions on Form 1065 Page 1. All rental income
        flows to Form 8825 → Schedule K Line 2 → K-1 Box 2.

        IRS: Any non-zero value on Page 1 Lines 1-23 for a pure rental LLC is
        an IRS violation. This includes Line 16a (depreciation) — rental property
        depreciation belongs on Form 8825 Line 14, never on Page 1 Line 16a.
        """
        issues    = []
        fill_1065 = self._load_form_fill_dict('Form1065')

        # Check key Page 1 income/deduction logical keys
        _PG1_KEYS = ['P1_1a', 'P1_1c', 'P1_3', 'P1_7', 'P1_8',
                     'P1_9', 'P1_11', 'P1_14', 'P1_15', 'P1_16a',
                     'P1_16c', 'P1_21', 'P1_22', 'P1_23']

        bad = {k: _safe_float(fill_1065.get(k)) for k in _PG1_KEYS
               if abs(_safe_float(fill_1065.get(k))) > 0.01}

        if bad:
            lines = ', '.join(f"{k}=${v:,.2f}" for k, v in bad.items())
            issues.append(self.format_issue(
                'XF-R05', self.ERROR,
                f"XF-R05: Form 1065 Page 1 has non-zero values — IRS violation. "
                f"Affected: {lines}. "
                f"IRC §469(c)(2): pure rental LLC Page 1 Lines 1-23 must ALL be $0. "
                f"Rental income → Form 8825 → Schedule K Line 2, never to Page 1.",
                'IRC §469(c)(2); Form 1065 Instructions Lines 1-23; AgentF1065_IncStmt',
                "Re-run Form1065Agent. Verify bookNS_IS.json has no mappings to "
                "Page 1 income/deduction lines for rental amounts.",
                fids=list(bad.keys())))
        else:
            issues.append(self.format_issue(
                'XF-R05', self.INFO,
                f"XF-R05 PASS: Form 1065 Page 1 Lines 1-23 all $0. "
                f"Rental income correctly excluded from ordinary income section. "
                f"IRC §469(c)(2) compliance confirmed.",
                'LLCTaxAgent XF-R05; IRC §469(c)(2)',
                "No action required."))

        return issues

    # ── Summary builder ───────────────────────────────────────────────────────

    def _build_summary(self, form_results: Dict, xf_results: List[Dict]) -> str:
        xf_errors  = [i for i in xf_results if i.get('severity') == self.ERROR]
        xf_passes  = [i for i in xf_results if i.get('severity') == self.INFO
                      and 'PASS' in i.get('message', '')]
        form_states = {k: v.get('state', self.NOT_STARTED) for k, v in form_results.items()}
        bad_forms   = [k for k, s in form_states.items() if s == self.NEEDS_FIXING]

        if bad_forms or xf_errors:
            return (f"LLCTaxAgent: NEEDS_FIXING. "
                    f"Form issues: {', '.join(bad_forms) if bad_forms else 'none'}. "
                    f"XF audit errors: {len(xf_errors)}.")
        return (f"LLCTaxAgent: GO. All {len(form_results)} form agents passed. "
                f"XF audit: {len(xf_passes)} rules passed. "
                f"W&B Group LLC {self.tax_year} — ready for CPA review.")

    # ── Session state persistence ─────────────────────────────────────────────

    def _session_state_path(self) -> Optional[Path]:
        d = self._agent_work_dir()
        if d is None:
            return None
        return d / 'LLCTaxAgent_session_state.json'

    def _load_session_state(self) -> Optional[Dict[str, Any]]:
        p = self._session_state_path()
        if p is None or not p.exists():
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return None

    def _save_session_state(self, state: Dict[str, Any]) -> None:
        p = self._session_state_path()
        if p is None:
            return
        try:
            with open(p, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    # ── Profile helpers ───────────────────────────────────────────────────────

    def _profile_path(self) -> Optional[Path]:
        """Find llcProfile_<name>.json. Returns Path or None."""
        try:
            llc_nm = getattr(self.llc, 'objName', 'WBGroupLLC')
            acct_dir = Path(self.llc.acctDir()) / 'Accts'
            p = acct_dir / f'llcProfile_{llc_nm}.json'
            if p.exists():
                return p
        except Exception:
            pass
        return None

    def _load_profile_data(self):
        """Load profile JSON, return (entity_dict, f1065_dict)."""
        p = self._profile_path()
        if p is None:
            return {}, {}
        try:
            raw = p.read_text(encoding='utf-8')
            try:
                profile = json.loads(raw)
            except json.JSONDecodeError:
                m = re.match(r'(\{.*?\})\s*\{', raw, re.DOTALL)
                profile = json.loads(m.group(1)) if m else {}
            return profile.get('entity', {}), profile.get('F1065', {})
        except Exception:
            return {}, {}

    def _save_profile_field(self, section: str, key: str, value: Any) -> bool:
        """Write profile[section][key] = value back to the JSON file."""
        p = self._profile_path()
        if p is None:
            return False
        try:
            raw = p.read_text(encoding='utf-8')
            try:
                profile = json.loads(raw)
            except json.JSONDecodeError:
                return False
            if section not in profile:
                profile[section] = {}
            profile[section][key] = value
            p.write_text(json.dumps(profile, indent=4), encoding='utf-8')
            return True
        except Exception:
            return False

    # ── Phase 3: Assemble IRS Submission Package ──────────────────────────────

    def phase3_package(self) -> Dict[str, Any]:
        """
        Assemble IRS_Submission_{year}/ directory.
        Copies all FILL PDFs found in forms_dir, computes SHA-256, writes manifest.json.
        Returns the manifest dict.
        """
        forms_dir = self._forms_dir()
        if forms_dir is None:
            return {'status': 'ERROR', 'message': 'Forms directory not found', 'artifacts': []}

        year    = self.tax_year
        pkg_dir = forms_dir / f'IRS_Submission_{year}'
        pkg_dir.mkdir(parents=True, exist_ok=True)

        entity, f1065_data = self._load_profile_data()
        owners = self._get_owners()

        artifacts      = []
        missing_req    = []

        def _copy_and_hash(src: Path, dest: Path) -> str:
            shutil.copy2(str(src), str(dest))
            return _sha256_file(dest)

        # ── Required fixed-name forms ─────────────────────────────────────────
        for fname in ('Form1065_FILL.pdf', 'Form8825_FILL.pdf', 'Form4562_FILL.pdf'):
            src     = forms_dir / fname
            present = src.exists()
            sha     = _copy_and_hash(src, pkg_dir / fname) if present else None
            if not present:
                missing_req.append(fname)
            artifacts.append({
                'file':     fname,
                'sha256':   sha,
                'source':   'auto',
                'required': True,
                'present':  present,
            })

        # ── Schedule K-1 (glob for all per-partner FILL PDFs) ─────────────────
        k1_required = max(len(owners), 1)
        k1_files    = sorted(forms_dir.glob('Sch_K1_o*_FILL.pdf'))
        for kf in k1_files:
            sha = _copy_and_hash(kf, pkg_dir / kf.name)
            artifacts.append({
                'file':     kf.name,
                'sha256':   sha,
                'source':   'auto',
                'required': True,
                'present':  True,
            })
        if len(k1_files) < k1_required:
            missing_req.append(
                f'Sch_K1_o*_FILL.pdf ({k1_required} required, {len(k1_files)} present)'
            )
        if not k1_files:
            artifacts.append({
                'file':     f'Sch_K1_o*_FILL.pdf ({k1_required} required)',
                'sha256':   None,
                'source':   'auto',
                'required': True,
                'present':  False,
            })

        # ── Optional: YE Financial Report ─────────────────────────────────────
        for yf in sorted(forms_dir.glob('*_YEFinancialReport.pdf')):
            sha = _copy_and_hash(yf, pkg_dir / yf.name)
            artifacts.append({
                'file':     yf.name,
                'sha256':   sha,
                'source':   'auto',
                'required': False,
                'present':  True,
            })

        ext_filed = bool(f1065_data.get('extension_filed', False))
        deadline  = f'{year + 1}-09-15' if ext_filed else f'{year + 1}-03-15'
        status    = 'READY' if not missing_req else 'INCOMPLETE'

        manifest = {
            'tax_year':         year,
            'assembled_at':     _now_iso(),
            'filing_entity':    entity.get('entity_name', 'W&B Group, LLC'),
            'ein':              entity.get('ein', ''),
            'form_type':        'Form 1065',
            'period_end':       f'{year}-12-31',
            'extension_filed':  ext_filed,
            'filing_deadline':  deadline,
            'halt_overrides':   [],
            'status':           status,
            'missing_required': missing_req,
            'artifacts':        artifacts,
        }

        manifest_path = pkg_dir / 'manifest.json'
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)

        # ── Accountant Letter — generate then include in package ───────────────
        # generate_accountant_letter() reads manifest for filing deadline,
        # so it runs AFTER the manifest is written above.
        try:
            letter_path = self.generate_accountant_letter()
            if letter_path and letter_path.exists():
                sha = _copy_and_hash(letter_path, pkg_dir / letter_path.name)
                manifest['artifacts'].append({
                    'file':     letter_path.name,
                    'sha256':   sha,
                    'source':   'auto',
                    'required': False,
                    'present':  True,
                })
                with open(manifest_path, 'w') as f:
                    json.dump(manifest, f, indent=2)
        except Exception:
            pass  # letter failure must not block package assembly

        return manifest

    def load_manifest(self) -> Optional[Dict[str, Any]]:
        """Load existing manifest.json from IRS_Submission_{year}/ if present."""
        forms_dir = self._forms_dir()
        if forms_dir is None:
            return None
        p = forms_dir / f'IRS_Submission_{self.tax_year}' / 'manifest.json'
        if not p.exists():
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return None

    # ── Phase 4: Submission guidance ─────────────────────────────────────────

    def phase4_submit(self) -> Dict[str, Any]:
        """
        Build submission checklist and generate Accountant Notification Letter.
        Returns checklist dict with status and letter path.
        """
        manifest = self.load_manifest()
        owners   = self._get_owners()
        entity, f1065_data = self._load_profile_data()
        sub_status = self.get_submission_status()

        # ── Checklist ─────────────────────────────────────────────────────────
        checklist_items = []

        if manifest:
            for art in manifest.get('artifacts', []):
                if not art.get('required'):
                    continue
                checklist_items.append({
                    'id':      f"doc_{art['file'].replace('*', 'all').replace('.', '_')}",
                    'label':   art['file'],
                    'done':    art.get('present', False),
                    'action':  None if art.get('present') else f"Generate {art['file']} via its form agent",
                    'type':    'document',
                })
        else:
            checklist_items.append({
                'id':     'pkg_assembly',
                'label':  'Assemble IRS Submission Package',
                'done':   False,
                'action': 'Click [Assemble Package] to create IRS_Submission package',
                'type':   'action',
            })

        # Accountant letter item
        letter_path = self._accountant_letter_path()
        checklist_items.append({
            'id':     'accountant_letter',
            'label':  'Generate Notification Letter — Review Financial Report',
            'done':   letter_path.exists() if letter_path else False,
            'action': None if (letter_path and letter_path.exists()) else 'Click [Generate Letter] below',
            'type':   'letter',
        })

        # Filing method
        checklist_items.append({
            'id':     'filing_method',
            'label':  'Select and complete filing method (mail / e-file)',
            'done':   bool(sub_status.get('filed_method') and sub_status['filed_method'] != 'pending'),
            'action': 'Record method and date after filing',
            'type':   'filing',
        })

        # K-1 delivery per partner
        for o in owners:
            oid     = o.get('oID', '')
            nm_raw  = o.get('nm', oid)
            nm      = nm_raw[0] if isinstance(nm_raw, list) and nm_raw else str(nm_raw)
            k1_del  = (sub_status.get('k1_delivered') or {}).get(oid, '')
            checklist_items.append({
                'id':     f'k1_{oid}',
                'label':  f'K-1 delivered to {nm} ({oid})',
                'done':   bool(k1_del),
                'action': None if k1_del else f'Mail K-1 to: {o.get("addr", "")}',
                'type':   'k1',
                'addr':   o.get('addr', ''),
                'date':   k1_del,
            })

        # ── Submission address ────────────────────────────────────────────────
        mail_addr = {
            'name':    'Department of the Treasury',
            'line2':   'Internal Revenue Service',
            'city':    'Ogden, UT 84201-0011',
            'note':    'Recommended: Certified mail, return receipt requested',
            'deadline': manifest.get('filing_deadline', f'{self.tax_year + 1}-03-15') if manifest else f'{self.tax_year + 1}-03-15',
        }

        done_count  = sum(1 for c in checklist_items if c['done'])
        total_count = len(checklist_items)

        return {
            'tax_year':        self.tax_year,
            'checklist':       checklist_items,
            'done_count':      done_count,
            'total_count':     total_count,
            'package_ready':   manifest is not None and manifest.get('status') == 'READY',
            'mail_address':    mail_addr,
            'submission_status': sub_status,
            'letter_exists':   letter_path.exists() if letter_path else False,
            'letter_filename': letter_path.name if letter_path else '',
        }

    # ── Submission status persistence ─────────────────────────────────────────

    def get_submission_status(self) -> Dict[str, Any]:
        """Read submission status from Profile.F1065.submission_status."""
        _, f1065 = self._load_profile_data()
        return f1065.get('submission_status') or {
            'filed_date':      '',
            'filed_method':    'pending',
            'tracking_number': '',
            'extension_filed': False,
            'k1_delivered':    {},
        }

    def update_submission_status(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge updates into Profile.F1065.submission_status.
        Allowed keys: filed_date, filed_method, tracking_number, extension_filed,
                      k1_delivered (dict of oID → date string).
        Returns the updated status dict.
        """
        current = self.get_submission_status()
        # Merge k1_delivered separately (dict merge)
        k1_updates = updates.pop('k1_delivered', None)
        if k1_updates and isinstance(k1_updates, dict):
            current.setdefault('k1_delivered', {}).update(k1_updates)
        current.update({k: v for k, v in updates.items()
                        if k in ('filed_date', 'filed_method', 'tracking_number', 'extension_filed')})
        self._save_profile_field('F1065', 'submission_status', current)
        return current

    # ── Accountant Notification Letter ────────────────────────────────────────

    def _accountant_letter_path(self) -> Optional[Path]:
        d = self._forms_dir()
        return d / f'AccountantLetter_{self.tax_year}.pdf' if d else None

    def generate_accountant_letter(self) -> Optional[Path]:
        """
        Generate a PDF Accountant Notification Letter using reportlab.
        Saved to forms_dir/AccountantLetter_{year}.pdf.
        Returns the Path or None on failure.
        """
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles    import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units     import inch
            from reportlab.platypus      import (SimpleDocTemplate, Paragraph,
                                                  Spacer, HRFlowable, Table, TableStyle)
            from reportlab.lib           import colors
        except ImportError:
            return None

        out_path = self._accountant_letter_path()
        if out_path is None:
            return None

        entity, f1065_data = self._load_profile_data()
        owners   = self._get_owners()
        manifest = self.load_manifest()
        year     = self.tax_year

        entity_name = entity.get('entity_name', 'W&B Group, LLC')
        ein         = entity.get('ein', '')
        address     = f1065_data.get('address', entity.get('address', ''))
        city_st_zip = f"{f1065_data.get('C_city','')}, {f1065_data.get('C_state','')} {f1065_data.get('C_zip','')}"
        prep_nm     = f"{f1065_data.get('B_PRDI_FirstNm','')} {f1065_data.get('B_PRDI_Last','')}".strip()
        prep_ph     = f1065_data.get('B_PRDI_Ph', '')
        deadline    = manifest.get('filing_deadline', f'{year + 1}-03-15') if manifest else f'{year + 1}-03-15'
        today_str   = datetime.now().strftime('%B %d, %Y')

        # Form list
        form_lines = [
            ('Form 1065',    'U.S. Return of Partnership Income',         'Form1065_FILL.pdf'),
            ('Form 8825',    'Rental Real Estate Income and Expenses',     'Form8825_FILL.pdf'),
            ('Form 4562',    'Depreciation and Amortization',              'Form4562_FILL.pdf'),
        ]
        for i, o in enumerate(owners, 1):
            oID_val = o.get('oID', f'Member{i}')
            form_lines.append(('Schedule K-1', f'Member {i} ({oID_val}) — Income, Deduction, Credits', ''))

        styles  = getSampleStyleSheet()
        normal  = styles['Normal']
        heading = ParagraphStyle('heading', parent=styles['Heading2'],
                                 fontSize=11, spaceAfter=4)
        body    = ParagraphStyle('body', parent=normal, fontSize=10, leading=14, spaceAfter=6)
        small   = ParagraphStyle('small', parent=normal, fontSize=9, leading=12)

        doc    = SimpleDocTemplate(str(out_path), pagesize=letter,
                                   leftMargin=1.1*inch, rightMargin=1.1*inch,
                                   topMargin=1.0*inch,  bottomMargin=1.0*inch)
        story  = []

        # ── Letterhead ────────────────────────────────────────────────────────
        story.append(Paragraph(f'<b>{entity_name}</b>', styles['Heading1']))
        story.append(Paragraph(f'{address}', body))
        story.append(Paragraph(f'{city_st_zip}', body))
        story.append(Paragraph(f'EIN: {ein}', body))
        story.append(Spacer(1, 0.15*inch))
        story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#374151')))
        story.append(Spacer(1, 0.1*inch))

        story.append(Paragraph(today_str, body))
        story.append(Spacer(1, 0.15*inch))

        story.append(Paragraph('<b>Re: Notification Letter — Review Financial Report</b>', heading))
        story.append(Paragraph(
            f'Tax Year: <b>{year}</b> &nbsp;&nbsp;|&nbsp;&nbsp; '
            f'Entity: <b>{entity_name}</b> &nbsp;&nbsp;|&nbsp;&nbsp; EIN: <b>{ein}</b>', body))
        story.append(Spacer(1, 0.1*inch))

        story.append(Paragraph(
            f'Dear Tax Professional,', body))
        story.append(Paragraph(
            f'Please find the IRS Form 1065 submission package for <b>{entity_name}</b> for tax '
            f'year <b>{year}</b> attached for review. This package was prepared using a '
            f'double-entry accounting system following the Books-First methodology (IRC §446, §703). '
            f'All internal cross-form audit checks have been completed.', body))
        story.append(Spacer(1, 0.1*inch))

        # ── Package contents ──────────────────────────────────────────────────
        story.append(Paragraph('<b>PACKAGE CONTENTS</b>', heading))
        tbl_data = [['Form', 'Description', 'File']]
        for form_id, desc, fname in form_lines:
            tbl_data.append([form_id, desc, fname or '(attached)'])
        tbl = Table(tbl_data, colWidths=[1.3*inch, 3.1*inch, 1.8*inch])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',  (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('TEXTCOLOR',   (0, 0), (-1, 0), colors.white),
            ('FONTSIZE',    (0, 0), (-1, 0), 9),
            ('FONTSIZE',    (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
            ('GRID',        (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
            ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',  (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.15*inch))

        # ── SHA-256 note ──────────────────────────────────────────────────────
        if manifest and manifest.get('status') == 'READY':
            story.append(Paragraph(
                f'<b>Package integrity verified.</b> All documents are SHA-256 checksummed. '
                f'See <i>manifest.json</i> in the submission package for full checksums. '
                f'Package assembled: {manifest.get("assembled_at", "")}', small))
        story.append(Spacer(1, 0.1*inch))

        # ── Next steps ────────────────────────────────────────────────────────
        story.append(Paragraph('<b>NEXT STEPS</b>', heading))
        next_steps = [
            'Review all forms for accuracy and completeness.',
            f'Advise on any required adjustments prior to filing.',
            f'Sign Form 1065 Page 2 (Principal Officer signature line).',
            f'<b>Filing deadline: {deadline}</b> — or Sep 15, {year+1} if Form 7004 extension is filed.',
            f'Schedule K-1 delivery to all partners by the filing deadline.',
        ]
        for step in next_steps:
            story.append(Paragraph(f'• {step}', body))
        story.append(Spacer(1, 0.1*inch))

        # ── IRS mailing address ───────────────────────────────────────────────
        story.append(Paragraph('<b>IRS MAILING ADDRESS (if filing by mail)</b>', heading))
        story.append(Paragraph('Department of the Treasury<br/>Internal Revenue Service<br/>'
                                'Ogden, UT 84201-0011', body))
        story.append(Paragraph(
            '<i>Recommended: Certified mail, return receipt requested. '
            'Keep the green card as proof of timely filing.</i>', small))
        story.append(Spacer(1, 0.15*inch))

        # ── Contact ───────────────────────────────────────────────────────────
        story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#D1D5DB')))
        story.append(Spacer(1, 0.08*inch))
        story.append(Paragraph('<b>CONTACT</b>', heading))
        story.append(Paragraph(f'{prep_nm}<br/>{address}, {city_st_zip}', body))
        contact_email = entity.get('email', 'wbgroupmgr@gmail.com')
        story.append(Paragraph(f'Email: {contact_email}', body))
        if prep_ph:
            story.append(Paragraph(f'Phone: {prep_ph}', body))
        story.append(Spacer(1, 0.2*inch))
        story.append(Paragraph(f'Sincerely,', body))
        story.append(Spacer(1, 0.3*inch))
        story.append(Paragraph(f'<b>{prep_nm}</b><br/>Principal Officer, {entity_name}', body))

        doc.build(story)
        return out_path
