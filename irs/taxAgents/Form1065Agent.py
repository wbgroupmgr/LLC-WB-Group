"""
Form1065Agent — Tier 1 orchestrator for IRS Form 1065 (5-page return only).

Architecture (4-tier):
  Tier 0  LLCTaxAgent        (future — cross-form audit + submission)
  Tier 1  Form1065Agent       — this file; orchestrates 6 section agents
  Tier 2  AgentF1065_*        — one per Form 1065 section (also this file)
           AgentForm_Ext       — Pass 0 inventory + extension advice
  Tier 3  IRSFormsAgent       — common services base class

Form1065Agent produces:
  * Form1065_FILL.pdf  (5-page form — via existing irs.Form1065 pipeline)
  * FormPackage with ext_artifacts advice for extension forms (8825/4562/K-1)
  * IRS_Form1065_{year}_Summary.pdf  (Phase 3 — future)

Session state stored at:
  books/{year}/Forms/.agent_work/Form1065_session_state.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib  import Path
from typing   import Any, Dict, List, Optional

from irs.taxAgents.IRSFormsAgent import IRSFormsAgent


# ────────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────────

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ════════════════════════════════════════════════════════════════════════════
#  SECTION AGENTS  (Tier 2)
# ════════════════════════════════════════════════════════════════════════════

class _SectionAgent(IRSFormsAgent):
    """Common base for all Form 1065 section agents."""

    LABEL        = ''   # human label shown in status strip
    AGENT_KEY    = ''   # key used in session state dict
    LOGICAL_PREFIXES: List[str] = []  # logical-key prefixes this section owns

    def __init__(self, llc, tax_year: int):
        super().__init__(llc, tax_year)
        self._profile = None
        self._is_data = None
        self._bs_data = None
        self._owners  = None

    # ── Data loaders (lazy) ──────────────────────────────────────────────────

    def _get_profile(self):
        if self._profile is not None:
            return self._profile
        try:
            from ledger.stmtProfile import stmtProfile
            self._profile = stmtProfile(self.llc)
        except Exception:
            self._profile = {}
        return self._profile

    def _ev(self, field: str, default: str = '') -> str:
        """Entity profile value."""
        p = self._get_profile()
        if hasattr(p, 'entity_value'):
            return str(p.entity_value(field) or default)
        return str(getattr(self.llc, 'entity', {}).get(field, default))

    def _fv(self, field: str, default: str = '') -> str:
        """F1065 profile value."""
        p = self._get_profile()
        if hasattr(p, 'f1065_value'):
            return str(p.f1065_value(field) or default)
        return str(getattr(self.llc, 'F1065', {}).get(field, default))

    def _get_is(self) -> Dict[str, float]:
        """Return flat IS totals: {acct_name: balance}."""
        if self._is_data is not None:
            return self._is_data
        try:
            from ledger.stmtIS import stmtIS
            stmt = stmtIS(self.llc)
            rows = stmt.load()
            self._is_data = {r.get('acctName', ''): _safe_float(r.get('Balance'))
                             for r in rows}
        except Exception:
            self._is_data = {}
        return self._is_data

    def _get_bs(self) -> Dict[str, float]:
        """Return flat BS totals: {acct_name: balance}."""
        if self._bs_data is not None:
            return self._bs_data
        try:
            from ledger.stmtBS import stmtBS
            stmt = stmtBS(self.llc)
            rows = stmt.load()
            self._bs_data = {r.get('acctName', ''): _safe_float(r.get('Balance'))
                             for r in rows}
        except Exception:
            self._bs_data = {}
        return self._bs_data

    def _get_owners(self) -> List[Dict]:
        if self._owners is not None:
            return self._owners
        try:
            self._owners = list(getattr(self.llc, 'owners', []) or [])
        except Exception:
            self._owners = []
        return self._owners

    def _get_is_total(self, category: str) -> float:
        """Sum IS rows where acctType == category."""
        total = 0.0
        try:
            from ledger.stmtIS import stmtIS
            for r in stmtIS(self.llc).load():
                if str(r.get('acctType', '')) == category:
                    total += _safe_float(r.get('Balance'))
        except Exception:
            pass
        return total

    def _get_bs_total_assets(self) -> float:
        try:
            from ledger.stmtBS import stmtBS
            stmt = stmtBS(self.llc)
            v = stmt.get('TOTAL', 'Balance')
            return _safe_float(v)
        except Exception:
            return 0.0

    # ── Pass interface (overridden per section) ───────────────────────────────

    def pass1_auto_fill(self) -> Dict[str, Any]:
        """Pull existing fill dict; report completeness for this section's slice."""
        fill_dict = self._load_fill_dict()
        completeness = self.audit_fill_completeness(fill_dict, self.LOGICAL_PREFIXES)
        return {
            'section':  self.AGENT_KEY,
            'tax_year': self.tax_year,
            **completeness,
            'fill_dict': {k: v for k, v in fill_dict.items()
                          if any(k.startswith(p) for p in self.LOGICAL_PREFIXES)},
        }

    def pass2_audit(self) -> Dict[str, Any]:
        """Override in each subclass to return IssueList."""
        return {
            'section':       self.AGENT_KEY,
            'halt_count':    0,
            'resolve_count': 0,
            'review_count':  0,
            'issue_list':    [],
            'ready_state':   self.GO,
        }

    def pass4_finalize(self) -> Dict[str, Any]:
        """Return this section's fillDict slice (or ExtAdvice for AgentForm_Ext)."""
        fill_dict = self._load_fill_dict()
        return {k: v for k, v in fill_dict.items()
                if any(k.startswith(p) for p in self.LOGICAL_PREFIXES)}

    def pass5_summarize(self) -> str:
        return f"{self.LABEL}: complete."

    # ── Shared helper ────────────────────────────────────────────────────────

    def _load_fill_dict(self) -> Dict[str, Any]:
        """Load cached Form1065_fillDict.json if it exists; else {}."""
        forms_dir = self._forms_dir()
        if forms_dir is None:
            return {}
        p = forms_dir / 'Form1065_fillDict.json'
        if not p.exists():
            return {}
        try:
            with open(p) as f:
                data = json.load(f)
            fields = data.get('fields', data) if isinstance(data, dict) else {}
            # Normalize: each field entry may be a dict with 'logicalKey' / 'value'
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

    def _run_audit(self, rules: List[callable]) -> Dict[str, Any]:
        """Run a list of rule functions; each returns a issue dict or None."""
        issues = []
        for rule_fn in rules:
            try:
                issue = rule_fn()
                if issue:
                    issues.append(issue)
            except Exception:
                pass
        session = self.build_bookkeeper_session(issues)
        state   = self.state_from_issues(issues)
        return {
            'section':       self.AGENT_KEY,
            'halt_count':    session['halt_count'],
            'resolve_count': session['resolve_count'],
            'review_count':  session['review_count'],
            'issue_list':    issues,
            'ready_state':   state,
        }


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_Info — General Information (Page 1, Items A–I)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_Info(_SectionAgent):
    LABEL             = 'General Information'
    AGENT_KEY         = 'AgentF1065_Info'
    LOGICAL_PREFIXES  = ['P1_Hdr', 'P1_A', 'P1_B', 'P1_C', 'P1_D',
                         'P1_E', 'P1_F', 'P1_G', 'P1_H', 'P1_I',
                         'P1_J', 'P1_K']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_ein,
            self._rule_entity_name,
            self._rule_acctg_method,
            self._rule_partnership_rep,
            self._rule_initial_final,
        ])

    def pass5_summarize(self) -> str:
        name = self._ev('entity_name') or 'LLC'
        ein  = self._ev('ein') or 'EIN not set'
        yr   = self._fv('tax_year') or str(self.tax_year)
        return f"{name} — EIN {ein}, TY {yr}"

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_ein(self):
        ein = self._ev('ein', '').replace('-', '').strip()
        if not ein or len(ein) != 9 or not ein.isdigit():
            return self.format_issue(
                'IF-R01', self.ERROR,
                f"EIN missing or malformed (found: '{self._ev('ein')}')",
                'Every Form 1065 requires a valid 9-digit EIN',
                "Enter EIN in llcProfile under entity.ein")

    def _rule_entity_name(self):
        name = self._ev('entity_name', '').strip()
        if not name:
            return self.format_issue(
                'IF-R02', self.ERROR,
                "Entity name is blank",
                'Form 1065 Page 1 header requires the legal partnership name',
                "Set entity.entity_name in llcProfile")

    def _rule_acctg_method(self):
        method = self._fv('acctg_method', '').strip()
        if not method:
            return self.format_issue(
                'IF-R03', self.WARN,
                "Accounting method not set (Cash or Accrual)",
                'Form 1065 Page 1 Item F requires one checkbox',
                "Set F1065.acctg_method to 'Cash' or 'Accrual' in llcProfile")

    def _rule_partnership_rep(self):
        pr = self._fv('partnership_rep', '').strip()
        if not pr:
            return self.format_issue(
                'IF-R04', self.ERROR,
                "Partnership Representative (PR) not named",
                'IRC §6223 — all BBA partnerships must designate a PR on Form 1065',
                "Set F1065.partnership_rep in llcProfile")

    def _rule_initial_final(self):
        # If no checkbox is set for initial/final/amended, warn
        f1065 = getattr(self.llc, 'F1065', {}) or {}
        chks  = f1065.get('chk', [])
        if not any(chks):
            return self.format_issue(
                'IF-R05', self.WARN,
                "No filing type checkbox set (Initial / Final / Amended)",
                'At least one filing indicator should be checked',
                "Set the appropriate checkbox in F1065.chk in llcProfile")


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_IncStmt — Income & Deductions (Page 1, Lines 1–23)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_IncStmt(_SectionAgent):
    LABEL             = 'Income & Deductions'
    AGENT_KEY         = 'AgentF1065_IncStmt'
    LOGICAL_PREFIXES  = ['P1_1', 'P1_2', 'P1_3', 'P1_4', 'P1_5', 'P1_6',
                         'P1_7', 'P1_8', 'P1_9', 'P1_10', 'P1_11', 'P1_12',
                         'P1_13', 'P1_14', 'P1_15', 'P1_16', 'P1_17', 'P1_18',
                         'P1_19', 'P1_20', 'P1_21', 'P1_22', 'P1_23']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_no_rent_on_pg1,
            self._rule_line23_arithmetic,
        ])

    def pass5_summarize(self) -> str:
        # For a pure rental LLC, Pg1 should be $0 ordinary business income
        return "No ordinary business income on Page 1; all rental activity passive (§469)"

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_no_rent_on_pg1(self):
        """Rental income must NOT be on Form 1065 Page 1 Lines 1–8."""
        is_data = self._get_is()
        rent_keys = [k for k in is_data if 'Rent' in k or 'Rev.Rent' in k or 'Acct.Rev' in k]
        rent_total = sum(abs(is_data[k]) for k in rent_keys)
        if rent_total > 0:
            # Check if it's mapped to Pg1 via fill dict
            fill = self._load_fill_dict()
            pg1_income = _safe_float(fill.get('P1_1a')) + _safe_float(fill.get('P1_2'))
            if pg1_income > 0:
                return self.format_issue(
                    'IS-R01', self.ERROR,
                    f"Rental income (${rent_total:,.2f}) appears on Form 1065 Page 1. "
                    f"It must flow through Form 8825 → Schedule K (§469 passive rule)",
                    'IRC §469(c)(2); Pub 925 §1',
                    "Remap Acct.Rev.Rent to Form 8825 via BookToIRS Aid (not to P1_1a)")

    def _rule_line23_arithmetic(self):
        """Line 23 = Line 8 − Line 22 (spot check via fill dict)."""
        fill = self._load_fill_dict()
        l8   = _safe_float(fill.get('P1_8'))
        l22  = _safe_float(fill.get('P1_22'))
        l23  = _safe_float(fill.get('P1_23'))
        if l8 == 0 and l22 == 0 and l23 == 0:
            return None  # nothing to check yet
        expected = round(l8 - l22, 2)
        if abs(expected - l23) > 0.01:
            return self.format_issue(
                'IS-R03', self.WARN,
                f"Line 23 arithmetic: Line 8 (${l8:,.2f}) − Line 22 (${l22:,.2f}) "
                f"= ${expected:,.2f}, but Line 23 shows ${l23:,.2f}",
                'Form 1065 Instructions, Line 23',
                "Re-run BookToIRS pipeline to recompute Line 23",
                auto_fix=True)


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_Other — Schedule B (Pages 2–3)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_Other(_SectionAgent):
    LABEL             = 'Schedule B'
    AGENT_KEY         = 'AgentF1065_Other'
    LOGICAL_PREFIXES  = ['B_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_schedule_threshold,
            self._rule_pr_named,
            self._rule_ownership_questions,
        ])

    def pass5_summarize(self) -> str:
        l_req = self._schedules_required()
        sched = "Schedules L/M-1/M-2 required" if l_req else "Schedules L/M-1/M-2 not required (below threshold)"
        return f"Schedule B complete. {sched}"

    # ── Threshold helper ─────────────────────────────────────────────────────

    def _schedules_required(self) -> bool:
        gross = abs(self._get_is_total('Income'))
        assets = self._get_bs_total_assets()
        return gross >= 250_000 and assets >= 1_000_000

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_schedule_threshold(self):
        gross  = abs(self._get_is_total('Income'))
        assets = self._get_bs_total_assets()
        required = gross >= 250_000 and assets >= 1_000_000
        if not required:
            return self.format_issue(
                'OT-R01', self.INFO,
                f"Schedules L/M-1/M-2 NOT required "
                f"(IS total income: ${gross:,.0f} < $250K and/or BS assets: ${assets:,.0f} < $1M). "
                f"Schedule B Q4 should answer 'Yes' (skip schedules).",
                'Form 1065 Instructions, Schedule B Q4',
                "Auto-apply: confirm Schedule B Q4 = Yes in BookToIRS Aid",
                auto_fix=True)

    def _rule_pr_named(self):
        pr = self._fv('partnership_rep', '').strip()
        if not pr:
            return self.format_issue(
                'OT-R02', self.ERROR,
                "Partnership Representative not named on Schedule B",
                'IRC §6223; Treas. Reg. §301.6223-1',
                "Set F1065.partnership_rep in llcProfile, then map to Schedule B fields via Aid")

    def _rule_ownership_questions(self):
        owners = self._get_owners()
        majority = [o for o in owners if _safe_float(o.get('ownership_pct', 0)) > 50]
        if majority:
            return self.format_issue(
                'OT-R05', self.INFO,
                f"Schedule B Q2/Q3: {len(majority)} partner(s) own >50% — "
                f"ownership disclosure questions must be answered",
                'Form 1065 Instructions, Schedule B Q2-3',
                "Confirm Schedule B Q2/Q3 answers in BookToIRS Aid")


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_Distr — Schedule K (Page 4)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_Distr(_SectionAgent):
    LABEL             = 'Schedule K'
    AGENT_KEY         = 'AgentF1065_Distr'
    LOGICAL_PREFIXES  = ['K_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_k_line2_populated,
            self._rule_partner_alloc_100,
            self._rule_no_se_income,
        ])

    def pass5_summarize(self) -> str:
        is_data  = self._get_is()
        net_rent = abs(is_data.get('Acct.Rev.Rent', 0) or
                       sum(v for k, v in is_data.items() if 'Rent' in k and v < 0))
        return (f"Net rental income per books: ${net_rent:,.2f} "
                f"— allocated per §704(b) partnership percentages")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_k_line2_populated(self):
        fill = self._load_fill_dict()
        k2   = fill.get('K_2')
        if k2 is None or k2 == '':
            return self.format_issue(
                'KD-R01', self.WARN,
                "Schedule K Line 2 (net rental real estate income) is blank",
                'Form 1065 Instructions, Schedule K',
                "Map IS.net_rental to K_2 via BookToIRS Aid")

    def _rule_partner_alloc_100(self):
        owners = self._get_owners()
        if not owners:
            return None
        total = sum(_safe_float(o.get('ownership_pct', 0)) for o in owners)
        if abs(total - 100.0) > 0.01:
            return self.format_issue(
                'KD-R03', self.ERROR,
                f"Partner ownership percentages sum to {total:.2f}% (must be exactly 100%)",
                'IRC §704(b) — all items must be allocated 100%',
                "Correct ownership_pct values in llcOwners DB")

    def _rule_no_se_income(self):
        fill = self._load_fill_dict()
        k14  = _safe_float(fill.get('K_14a') or fill.get('K_14'))
        if k14 != 0:
            return self.format_issue(
                'KD-R05', self.WARN,
                f"Schedule K Line 14 shows ${k14:,.2f} self-employment income. "
                f"Passive rental LLCs should have $0 here.",
                'IRC §1402(a)(13); Pub 541',
                "Verify K_14 mapping — rental income is not SE income")


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_Reconcile — Schedules L, M-1, M-2 (Page 5)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_Reconcile(_SectionAgent):
    LABEL             = 'Schedules L / M-1 / M-2'
    AGENT_KEY         = 'AgentF1065_Reconcile'
    LOGICAL_PREFIXES  = ['L_', 'M1_', 'M2_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_schedules_required_check,
            self._rule_sched_l_balance,
            self._rule_m1_book_income,
        ])

    def pass5_summarize(self) -> str:
        required = self._schedules_required()
        if not required:
            return "Schedules L/M-1/M-2 not required (Schedule B Q4 = Yes)"
        total_assets = self._get_bs_total_assets()
        return f"Schedule L: total assets ${total_assets:,.2f}; M-1/M-2 complete"

    def _schedules_required(self) -> bool:
        gross  = abs(self._get_is_total('Income'))
        assets = self._get_bs_total_assets()
        return gross >= 250_000 and assets >= 1_000_000

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_schedules_required_check(self):
        if not self._schedules_required():
            return self.format_issue(
                'RC-R01', self.INFO,
                "Schedules L/M-1/M-2 are not required for this LLC (below §250K/$1M threshold). "
                "These sections will be left blank — consistent with Schedule B Q4.",
                'Form 1065 Instructions, Schedule B Q4',
                "No action needed — Schedule B Q4 handles this")

    def _rule_sched_l_balance(self):
        if not self._schedules_required():
            return None
        fill         = self._load_fill_dict()
        l14_end      = _safe_float(fill.get('L_14_2'))  # end-of-year
        bs_assets    = self._get_bs_total_assets()
        if bs_assets > 0 and abs(l14_end - bs_assets) > 1.00:
            return self.format_issue(
                'RC-R02', self.ERROR,
                f"Schedule L Line 14 (end) = ${l14_end:,.2f} but BS total assets = ${bs_assets:,.2f}. "
                f"Discrepancy: ${abs(l14_end - bs_assets):,.2f}",
                'Form 1065 Instructions, Schedule L',
                "Remap BS.total_assets to L_14_2 and rerun BookToIRS pipeline")

    def _rule_m1_book_income(self):
        if not self._schedules_required():
            return None
        fill     = self._load_fill_dict()
        m1_line1 = _safe_float(fill.get('M1_1'))
        try:
            from ledger.stmtIS import stmtIS
            ni = _safe_float(stmtIS(self.llc).get('TOTAL', 'Balance'))
        except Exception:
            return None
        if ni != 0 and abs(m1_line1 - ni) > 1.00:
            return self.format_issue(
                'RC-R05', self.WARN,
                f"M-1 Line 1 (${m1_line1:,.2f}) differs from IS net income (${ni:,.2f}). "
                f"These must match.",
                'Form 1065 Instructions, Schedule M-1',
                "Map IS.net_income to M1_1 via BookToIRS Aid")


# ────────────────────────────────────────────────────────────────────────────
#  AgentForm_Ext — Pass 0 inventory + extension form advice (no fids filled)
# ────────────────────────────────────────────────────────────────────────────

class AgentForm_Ext(_SectionAgent):
    LABEL            = 'Next Steps (Extensions)'
    AGENT_KEY        = 'AgentForm_Ext'
    LOGICAL_PREFIXES = []  # no fid ownership in Form 1065 namespace

    def inventory(self) -> Dict[str, Any]:
        """
        Top-down (IRS rules) + bottom-up (books scan) → FormInventory.
        Called by Form1065Agent before phase1_prepare().
        """
        assets  = self._active_properties()
        owners  = self._get_owners()
        has_dep = self._has_depreciation()

        required_forms = ['Form1065']
        if assets:
            required_forms.append('Form8825')
        if has_dep:
            required_forms.append('Form4562')

        return {
            'required_forms':     required_forms,
            'required_k1_count':  len(owners),
            'active_properties':  [a.get('propNm', str(a)) for a in assets],
            'under_construction': [a.get('propNm', str(a))
                                   for a in self._under_construction_assets()],
            'schedules_required': {
                'L':  False,  # computed by AgentF1065_Other / AgentF1065_Reconcile
                'M1': False,
                'M2': False,
            },
            'notes': self._inventory_notes(assets, owners, has_dep),
        }

    def pass1_auto_fill(self) -> Dict[str, Any]:
        inv = self.inventory()
        return {'section': self.AGENT_KEY, 'tax_year': self.tax_year,
                'inventory': inv, 'filled': 0, 'blank': 0, 'complex': 0, 'total': 0}

    def pass2_audit(self) -> Dict[str, Any]:
        inv    = self.inventory()
        issues = []
        props  = inv['active_properties']
        k1_cnt = inv['required_k1_count']
        has_dep = self._has_depreciation()

        if props:
            issues.append(self.format_issue(
                'EX-R05', self.INFO,
                f"Form 8825 required: {len(props)} active propert{'y' if len(props)==1 else 'ies'} "
                f"({', '.join(props)})",
                'Form 8825 Instructions',
                "Prepare Form 8825 via Form8825Agent (future) or manually"))
        if has_dep:
            issues.append(self.format_issue(
                'EX-R07', self.INFO,
                "Form 4562 required: depreciation entries found in GL",
                'Form 4562 Instructions; IRC §168',
                "Prepare Form 4562 via Form4562Agent (future) or manually"))
        if k1_cnt:
            issues.append(self.format_issue(
                'EX-R01', self.INFO,
                f"{k1_cnt} Schedule K-1{'s' if k1_cnt > 1 else ''} required (one per partner)",
                'Form 1065 Instructions, §563',
                f"Prepare {k1_cnt} K-1s via SchK1Agent (future) or manually"))
        for uc in inv['under_construction']:
            issues.append(self.format_issue(
                'EX-R06', self.INFO,
                f"{uc} is under construction — excluded from Form 8825 (§168 not-yet-in-service)",
                'IRC §168',
                "No action required until asset is placed in service"))

        session = self.build_bookkeeper_session(issues)
        return {
            'section':       self.AGENT_KEY,
            'halt_count':    0,
            'resolve_count': 0,
            'review_count':  len(issues),
            'issue_list':    issues,
            'ready_state':   self.GO,
        }

    def pass4_finalize(self) -> Dict[str, Any]:
        """Return ExtAdvice (no fillDict — no fids owned)."""
        inv = self.inventory()
        parts = []
        if inv['active_properties']:
            parts.append(f"Form 8825 ({len(inv['active_properties'])} propert{'y' if len(inv['active_properties'])==1 else 'ies'})")
        if self._has_depreciation():
            parts.append("Form 4562")
        k1 = inv['required_k1_count']
        if k1:
            parts.append(f"{k1} Schedule K-1{'s' if k1>1 else ''}")
        advice = "Prepare: " + ", ".join(parts) if parts else "No extension forms required"
        return {'ext_advice': advice, 'inventory': inv}

    def pass5_summarize(self) -> str:
        inv   = self.inventory()
        parts = []
        if inv['active_properties']:
            parts.append(f"Form 8825 ({', '.join(inv['active_properties'])})")
        if self._has_depreciation():
            parts.append("Form 4562")
        k1 = inv['required_k1_count']
        if k1:
            parts.append(f"{k1} K-1{'s' if k1>1 else ''}")
        if inv['under_construction']:
            parts.append(f"{', '.join(inv['under_construction'])} excluded (under construction)")
        return "Next Steps: Prepare " + "; ".join(parts) if parts else "No extension forms required"

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _active_properties(self) -> List[Dict]:
        try:
            from ledger.llcAssets import llcAssets
            assets_obj = llcAssets(self.llc)
            rows = assets_obj.load() if hasattr(assets_obj, 'load') else []
            return [r for r in rows
                    if str(r.get('status', '')).lower() in ('active', 'in_service', 'placed_in_service')
                    and str(r.get('acctType', '')).lower() in ('property', 'asset', 'real_estate', 'realestate')]
        except Exception:
            return []

    def _under_construction_assets(self) -> List[Dict]:
        try:
            from ledger.llcAssets import llcAssets
            assets_obj = llcAssets(self.llc)
            rows = assets_obj.load() if hasattr(assets_obj, 'load') else []
            return [r for r in rows
                    if str(r.get('status', '')).lower() in ('under_construction', 'construction')]
        except Exception:
            return []

    def _has_depreciation(self) -> bool:
        try:
            from ledger.stmtIS import stmtIS
            for r in stmtIS(self.llc).load():
                if 'Depr' in str(r.get('acctName', '')) or 'Depr' in str(r.get('acctSub', '')):
                    return True
        except Exception:
            pass
        return False

    def _inventory_notes(self, assets, owners, has_dep) -> List[str]:
        notes = []
        if not assets:
            notes.append("No active properties found — Form 8825 may not be required")
        if not has_dep:
            notes.append("No depreciation entries in GL — Form 4562 may not be required")
        if not owners:
            notes.append("No partners found in llcOwners — K-1 count cannot be determined")
        return notes


# ════════════════════════════════════════════════════════════════════════════
#  FORM1065AGENT  (Tier 1 orchestrator)
# ════════════════════════════════════════════════════════════════════════════

class Form1065Agent(IRSFormsAgent):
    """
    Tier 1 orchestrator — sequences 6 section agents through 3 phases.
    Produces Form1065_FILL.pdf (via existing irs.Form1065 pipeline) and
    persists session state for getSummary().
    """

    _SECTION_ORDER = [
        AgentF1065_Info,
        AgentF1065_IncStmt,
        AgentF1065_Other,
        AgentF1065_Distr,
        AgentF1065_Reconcile,
        AgentForm_Ext,
    ]

    def __init__(self, llc, tax_year: Optional[int] = None):
        super().__init__(llc, tax_year)
        self._agents: List[_SectionAgent] = [
            cls(llc, self.tax_year) for cls in self._SECTION_ORDER
        ]

    # ── Public API ────────────────────────────────────────────────────────────

    def inventory(self) -> Dict[str, Any]:
        """Pass 0: delegate to AgentForm_Ext for top-down/bottom-up FormInventory."""
        ext = self._agent(AgentForm_Ext)
        return ext.inventory()

    def getSummary(self) -> Dict[str, Any]:
        """
        Read persisted session state — never re-runs passes.
        Returns SectionSummary for the Form 1065 View status strip.
        """
        state = self._load_session_state()
        if state is None:
            return self._empty_summary()
        return state

    def run_phases_1_2(self) -> Dict[str, Any]:
        """
        Run Pass 1 (auto-fill) + Pass 2 (audit) for all section agents.
        Writes session state. Returns the SectionSummary.
        """
        sections_state = {}
        overall_halt = 0

        for agent in self._agents:
            # Pass 1 — completeness
            p1 = agent.pass1_auto_fill()
            # Pass 2 — audit
            p2 = agent.pass2_audit()

            issues   = p2.get('issue_list', [])
            state    = p2.get('ready_state', self.GO)
            summary  = (agent.pass5_summarize()
                        if state == self.GO
                        else self._first_halt_message(issues))

            sections_state[agent.AGENT_KEY] = {
                'label':         agent.LABEL,
                'state':         state,
                'summary':       summary,
                'halt_count':    p2.get('halt_count', 0),
                'resolve_count': p2.get('resolve_count', 0),
                'review_count':  p2.get('review_count', 0),
                'issues':        issues,
                'pass1':         p1,
            }
            overall_halt += p2.get('halt_count', 0)

        # Compute ext_advice from AgentForm_Ext pass4
        ext_agent  = self._agent(AgentForm_Ext)
        ext_result = ext_agent.pass4_finalize()
        ext_advice = ext_result.get('ext_advice', '')

        overall_state = self.NEEDS_FIXING if overall_halt > 0 else self.GO

        session = {
            'tax_year':      self.tax_year,
            'last_run':      _now_iso(),
            'overall_state': overall_state,
            'sections':      sections_state,
            'ext_advice':    ext_advice,
        }
        self._save_session_state(session)
        return session

    # ── Session state persistence ─────────────────────────────────────────────

    def _session_state_path(self) -> Optional[Path]:
        d = self._agent_work_dir()
        if d is None:
            return None
        return d / 'Form1065_session_state.json'

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

    # ── Summary builders ─────────────────────────────────────────────────────

    def _empty_summary(self) -> Dict[str, Any]:
        sections = []
        for cls in self._SECTION_ORDER:
            sections.append({
                'agent':         cls.AGENT_KEY,
                'label':         cls.LABEL,
                'state':         self.NOT_STARTED,
                'summary':       'Not yet run — click Run Form Agent to start',
                'halt_count':    0,
                'resolve_count': 0,
                'review_count':  0,
            })
        return {
            'tax_year':      self.tax_year,
            'last_run':      None,
            'overall_state': self.NOT_STARTED,
            'sections':      sections,
            'ext_advice':    '',
        }

    @staticmethod
    def _first_halt_message(issues: List[Dict]) -> str:
        for i in issues:
            if i.get('severity') == 'ERROR':
                return i.get('message', 'Error — see Guided Review')
        return issues[0]['message'] if issues else ''

    def _agent(self, cls) -> _SectionAgent:
        for a in self._agents:
            if isinstance(a, cls):
                return a
        return cls(self.llc, self.tax_year)

    # ── Normalised summary list for template ─────────────────────────────────

    def getSummaryList(self) -> List[Dict[str, Any]]:
        """Return sections as an ordered list (for template rendering)."""
        state = self.getSummary()
        sections_dict = state.get('sections', {})
        result = []
        for cls in self._SECTION_ORDER:
            key   = cls.AGENT_KEY
            label = cls.LABEL
            if key in sections_dict:
                s = sections_dict[key]
                result.append({
                    'agent':         key,
                    'label':         s.get('label', label),
                    'state':         s.get('state', self.NOT_STARTED),
                    'summary':       s.get('summary', ''),
                    'halt_count':    s.get('halt_count', 0),
                    'resolve_count': s.get('resolve_count', 0),
                    'review_count':  s.get('review_count', 0),
                })
            else:
                result.append({
                    'agent':         key,
                    'label':         label,
                    'state':         self.NOT_STARTED,
                    'summary':       'Not yet run',
                    'halt_count':    0,
                    'resolve_count': 0,
                    'review_count':  0,
                })
        return result
