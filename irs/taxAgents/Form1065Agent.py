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
        """Return IS taxAggregates (Books-First; IRC §446/703 — books are authoritative)."""
        if self._is_data is not None:
            return self._is_data
        try:
            from ledger.stmtIS import stmtIS
            self._is_data = stmtIS(self.llc).taxAggregates()
        except Exception:
            self._is_data = {}
        return self._is_data

    def _get_is_agg(self, key: str, default: float = 0.0) -> float:
        """Safe accessor for a single IS aggregate key."""
        return _safe_float(self._get_is().get(key, default))

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
            raw = self.llc.owners  # may be a method or a list
            self._owners = raw() if callable(raw) else list(raw or [])
        except Exception:
            self._owners = []
        return self._owners

    def _get_is_total(self, category: str) -> float:
        """Return IS aggregate for a broad category ('Income' or 'Expense')."""
        agg = self._get_is()
        if category == 'Income':
            return abs(_safe_float(agg.get('total_income', 0)))
        if category == 'Expense':
            return abs(_safe_float(agg.get('total_expenses', 0)))
        return 0.0

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

    def _load_bookns_is(self) -> Dict[str, Any]:
        """Load the operator-authored bookNS_IS.json (Income-Statement mappings)."""
        forms_dir = self._forms_dir()
        if forms_dir is None:
            return {}
        p = forms_dir / 'bookNS_IS.json'
        if not p.exists():
            return {}
        try:
            with open(p) as f:
                return json.load(f)
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
    """
    IRS Knowledge Base — Form 1065 Page 1: General Information (Items A–K)

    Every partnership return must include accurate entity identification.
    Errors here are the most common reason IRS rejects returns.

    EIN (Item D): Employer Identification Number — 9 digits, no dashes on form.
      IRC §6109: taxpayer identification number required on every return.
      Wrong EIN = return processed under wrong entity = penalties + corrections.

    Partnership Representative (Schedule B Section): IRC §6223 (post-TCJA 2018).
      The BBA (Bipartisan Budget Act) centralized audit regime requires a
      designated Partnership Representative (PR). The PR has sole authority
      to act on behalf of the partnership in IRS proceedings. Required on
      every Form 1065 for tax years beginning 2018+.
      Treas. Reg. §301.6223-1: PR must be named with name, address, phone, TIN.

    Accounting Method (Item H): Cash or Accrual (or other).
      IRC §446(c): permissible methods include cash, accrual, or combination.
      W&B Group books depreciation and capitalizes assets → Accrual method.
      The method filed must match how the books are actually kept (IRC §446(a)).

    Number of K-1s (Item I): Must equal the number of partners in llcOwners.
      IRS uses this to verify every partner filed their K-1.

    Initial/Final return (Items G/H checkboxes): Required for first-year returns.
      W&B Group 2025 = initial return year (first Form 1065 ever filed).
    """

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
            self._rule_k1_count,
            self._rule_at_risk_checkbox,
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
                f"EIN missing or malformed (found: '{self._ev('ein')}'). "
                f"Form field: P1_B (EIN box, Page 1 Item B)",
                'Every Form 1065 requires a valid 9-digit EIN',
                "Set entity.ein in llcProfile",
                fids=['P1_B'],
                suggested_mapping={'fid': 'P1_B', 'src': 'Profile',
                                   'path': 'Profile.entity.ein'})

    def _rule_entity_name(self):
        name = self._ev('entity_name', '').strip()
        if not name:
            return self.format_issue(
                'IF-R02', self.ERROR,
                "Entity name is blank — Form field P1_Hdr_4 (Page 1 Name line)",
                'Form 1065 Page 1 header requires the legal partnership name',
                "Set entity.entity_name in llcProfile",
                fids=['P1_Hdr_4'],
                suggested_mapping={'fid': 'P1_Hdr_4', 'src': 'Profile',
                                   'path': 'Profile.entity.entity_name'})

    def _rule_acctg_method(self):
        # P1_H is in _CPA_NOTES (manual) — not auto-mapped. Check fill dict directly.
        fill   = self._load_fill_dict()
        p1h    = str(fill.get('P1_H', '')).strip()
        method = self._fv('acctg_method', '').strip()  # may not exist in profile
        if not p1h and not method:
            return self.format_issue(
                'IF-R03', self.WARN,
                "Line H (Accounting Method) checkbox is blank — Cash or Accrual must be checked. "
                "For W&B Group (tracks depreciation/assets on accrual basis): Accrual is appropriate.",
                'Form 1065 Page 1 Item H requires one checkbox',
                "In llcProfile set F1065.acctg_method = 'Accrual'; "
                "then map Profile.F1065.acctg_method → P1_H via the Aid dialog",
                fids=['P1_H'],
                suggested_mapping={'fid': 'P1_H', 'src': 'Profile',
                                   'path': 'Profile.F1065.acctg_method'})

    def _rule_k1_count(self):
        # Line I: Number of Schedules K-1 = number of partners
        owners     = self._get_owners()
        live_count = len(owners)
        fill       = self._load_fill_dict()
        fd_count   = _safe_float(fill.get('P1_I') or fill.get('B_25Fm'))
        if live_count > 0 and fd_count != live_count:
            return self.format_issue(
                'IF-R07', self.WARN,
                f"Line I (Number of Schedules K-1): fill dict shows {int(fd_count) if fd_count else 'blank'} "
                f"but llcOwners has {live_count} partner(s). "
                f"These must match (one K-1 per partner).",
                'Form 1065 Instructions, Page 1 Item I',
                "Re-run the BookToIRS pipeline so P1_I auto-fills from live owner count; "
                "or map Profile.owners.count → P1_I via Aid",
                fids=['P1_I', 'B_25Fm'],
                suggested_mapping={'fid': 'P1_I', 'src': 'Profile',
                                   'path': 'owners.count'})

    def _rule_at_risk_checkbox(self):
        # §465 at-risk rules: any partner personally at-risk for LLC debts?
        # This is a bookkeeper judgment — cannot be auto-computed.
        # Always raise as INFO requiring explicit confirmation.
        return self.format_issue(
            'IF-R08', self.INFO,
            "Line K (§465 At-Risk): For rental LLCs, partners are generally considered "
            "'at risk' for their capital contributions. Bookkeeper must explicitly confirm "
            "whether to check this box. Default for a cash-invested rental LLC: Yes (at risk).",
            'IRC §465; Form 1065 Instructions, Page 1 Item K',
            "Confirm with CPA: are all partners at-risk under §465 for this LLC? "
            "If yes, set the P1_K checkbox via Aid. "
            "Typically 'Yes' for a small LLC with no non-recourse financing beyond mortgages.",
            fids=['P1_K'])

    def _rule_partnership_rep(self):
        # Actual keys: F1065.B_PRDI_FirstNm + B_PRDI_Last → logical keys B_PR_1, B_PR_2
        first = self._fv('B_PRDI_FirstNm', '').strip()
        last  = self._fv('B_PRDI_Last', '').strip()
        if not first and not last:
            # Try to deduce from other profile fields
            deduced = self._deduce_pr()
            action_msg = (
                f"Books have '{deduced['found']}' — "
                f"map Profile.F1065.{deduced['src_key']} → Form field {deduced['fid']}"
                if deduced else
                "Set F1065.B_PRDI_FirstNm and B_PRDI_Last in llcProfile, "
                "then map to B_PR_1 / B_PR_2 via the Aid dialog"
            )
            return self.format_issue(
                'IF-R04', self.ERROR,
                "Partnership Representative (PR) first/last name is blank "
                "(Form 1065 Schedule B, Partnership Representative section)",
                'IRC §6223; Treas. Reg. §301.6223-1',
                action_msg,
                fids=['B_PR_1', 'B_PR_2'],
                suggested_mapping=deduced.get('mapping') if deduced else None)

    def _deduce_pr(self) -> Dict[str, Any]:
        """Try to infer Partnership Representative from existing profile data."""
        f1065 = getattr(self.llc, 'F1065', {}) or {}
        entity = getattr(self.llc, 'entity', {}) or {}
        # Check if there's name data in F1065 under any key
        for key in ('B_PRDI_FirstNm', 'prdi_first', 'PR_first', 'pr_first_nm'):
            v = str(f1065.get(key, '')).strip()
            if v:
                return {'found': v, 'src_key': key, 'fid': 'B_PR_1',
                        'mapping': {'fid': 'B_PR_1', 'src': 'Profile', 'path': f'Profile.F1065.{key}'}}
        # Fall back: check entity for owner names
        owners = self._get_owners()
        if owners:
            nm = owners[0].get('nm', [])
            name = ' '.join(nm) if isinstance(nm, list) else str(nm)
            if name.strip():
                return {'found': name,
                        'src_key': 'owners[0].nm (deduced — confirm correct partner)',
                        'fid': 'B_PR_1',
                        'mapping': None}  # can't auto-map owners; needs manual Aid
        return {}

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
    """
    IRS Knowledge Base — Form 1065 Page 1: Income & Deductions (Lines 1–23)

    Core IRS rule for W&B Group (pure rental LLC):
      IRC §469(c)(2): Rental activity is PASSIVE by definition.
      Passive rental income/loss does NOT belong on Form 1065 Page 1.
      Page 1 Lines 1–23 report ORDINARY business income only.
      For a pure rental LLC: every line on Page 1 must be $0.

    Correct IRS flow for rental income:
      Books (Acct.Rev.Rent.*) → Form 8825 (per-property detail)
        → Form 8825 Line 21 (net total) → Schedule K Line 2
        → Schedule K-1 Box 2 (per partner × ownership %)

    Incorrect flow (what this agent guards against):
      Books → Form 1065 Page 1 Lines 1a/3/8 ← IRS violation
      Books → Form 1065 Page 1 Line 16a (depreciation) ← IRS violation
        (IRS Instructions Line 16a: "Do not include rental real estate
         depreciation — that amount is reported on Form 8825 Line 14")

    Books-First (IRC §446 + §703): all values sourced from stmtIS.taxAggregates().
    """

    LABEL             = 'Income & Deductions'
    AGENT_KEY         = 'AgentF1065_IncStmt'
    LOGICAL_PREFIXES  = ['P1_1', 'P1_2', 'P1_3', 'P1_4', 'P1_5', 'P1_6',
                         'P1_7', 'P1_8', 'P1_9', 'P1_10', 'P1_11', 'P1_12',
                         'P1_13', 'P1_14', 'P1_15', 'P1_16', 'P1_17', 'P1_18',
                         'P1_19', 'P1_20', 'P1_21', 'P1_22', 'P1_23']

    # Page 1 income and deduction logical keys that MUST be $0 for rental LLC
    _PG1_INCOME_KEYS     = ['P1_1a', 'P1_1c', 'P1_3', 'P1_7', 'P1_8']
    _PG1_DEDUCTION_KEYS  = ['P1_9', 'P1_11', 'P1_14', 'P1_15',
                             'P1_16a', 'P1_16c', 'P1_21', 'P1_22', 'P1_23']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_no_pg1_bookns_mappings,
            self._rule_pg1_income_must_be_zero,
            self._rule_pg1_deductions_must_be_zero,
            self._rule_rental_depr_not_on_pg1,
            self._rule_books_have_rental_activity,
            self._rule_line23_must_be_zero,
        ])

    def pass5_summarize(self) -> str:
        rent   = self._get_is_agg('rent_income')
        net    = self._get_is_agg('net_rental')
        sign   = 'income' if net >= 0 else 'loss'
        return (f"Page 1 Lines 1–23: $0 (IRS §469 — all rental activity passive). "
                f"Books: gross rent ${rent:,.2f}, net rental {sign} ${abs(net):,.2f} "
                f"→ Schedule K Line 2 via Form 8825.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_no_pg1_bookns_mappings(self):
        """
        Scope rule — the agent's primary guard, evaluated against the REAL fids.

        The bookNS_IS.json Form1065 section is authored by hand and was historically
        populated WITHOUT the ordinary-vs-rental distinction. This rule reads the
        actual mappings and flags ANY mapping whose fid lands on the Page 1
        Income/Deductions slice (F033–F078). For a pure rental LLC every such fid
        must be UNMAPPED ($0): rental income/expense is passive (IRC §469(c)(2))
        and belongs on Form 8825 → Schedule K Line 2 — never on Page 1.

        This is what makes the section agent scope-aware: bookNS_IS is primarily a
        Form 8825 (rental) model; it must NOT feed Form 1065 Page 1 (ordinary).

        On a clean books-state it emits a positive 'verified $0' review item so the
        bookkeeper sees explicit confirmation, not silence.
        """
        import re as _re
        from irs.taxAgents.irsRefAgent import _F1065_INCSTMT_FIDS

        def _norm(x):
            s = str(x).strip()
            m = _re.match(r'^[fF]?(\d+)$', s)
            return f"F{int(m.group(1)):03d}" if m else s

        pg1_slice = set(_F1065_INCSTMT_FIDS)
        mappings  = self._load_bookns_is().get('Form1065', []) or []
        offenders = []
        for pair in mappings:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            fid, uas = _norm(pair[0]), str(pair[1])
            if fid in pg1_slice and (uas.startswith('IS.') or uas.startswith('Acct.')):
                offenders.append((fid, uas))

        if offenders:
            lst = ', '.join(f"{f}→{u}" for f, u in offenders)
            return self.format_issue(
                'IS-R09', self.ERROR,
                f"bookNS_IS maps rental Income-Statement values onto Form 1065 Page 1 "
                f"(Lines 1–23) — IRS violation. Offending mappings: {lst}. "
                f"For a pure rental LLC, Page 1 must be entirely $0: rental income and "
                f"expenses are passive (IRC §469(c)(2)) and are reported on Form 8825, "
                f"flowing to Schedule K Line 2. bookNS_IS is a Form 8825 model — it must "
                f"NOT feed Form 1065 Page 1.",
                'IRC §469(c)(2); Form 1065 Instructions Lines 1–23; bookNS_IS.json',
                "Remove the listed fid→IS.* entries from the bookNS_IS.json \"Form1065\" "
                "section (these belong to Form 8825). Re-run the FILL.pdf pipeline. "
                "Page 1 should then show all-blank income/deduction lines.",
                fids=[f for f, _ in offenders])

        # Positive verification — clean state.
        net  = self._get_is_agg('net_rental')
        sign = 'income' if net >= 0 else 'loss'
        return self.format_issue(
            'IS-R10', self.INFO,
            f"Verified: Form 1065 Page 1 Lines 1–23 carry no bookNS_IS mappings — "
            f"all ordinary income/deduction lines are correctly $0 for this rental LLC "
            f"(IRC §469(c)(2)). Net rental {sign} of ${abs(net):,.2f} flows via Form 8825 "
            f"→ Schedule K Line 2 → K-1 Box 2, not through Page 1.",
            'IRC §469(c)(2); Form 1065 Instructions Lines 1–23',
            "No action — Page 1 ordinary section is correctly empty. Confirm the same "
            "net rental amount appears on Form 8825 Line 23 and Schedule K Line 2.")

    def _rule_pg1_income_must_be_zero(self):
        """
        IRS Rule: IRC §469(c)(2) — rental activity is passive.
        Form 1065 Instructions, Lines 1–8: "Do not include income from
        rental real estate activities. Report that income on Form 8825."
        Page 1 Lines 1a, 1c, 3, 7, 8 must be blank/$0 for a rental LLC.
        Verify the fill dict has no positive values on these lines.
        """
        fill = self._load_fill_dict()
        bad  = {k: _safe_float(fill.get(k)) for k in self._PG1_INCOME_KEYS
                if abs(_safe_float(fill.get(k))) > 0.01}
        if bad:
            lines = ', '.join(f"{k}=${v:,.2f}" for k, v in bad.items())
            return self.format_issue(
                'IS-R01', self.ERROR,
                f"Income appears on Form 1065 Page 1 — IRS violation. "
                f"Rental income must NOT be on Page 1 Lines 1–8. Affected: {lines}. "
                f"IRC §469(c)(2): rental activity is passive; it flows "
                f"Books → Form 8825 → Schedule K Line 2, never to Page 1.",
                'IRC §469(c)(2); Form 1065 Instructions Lines 1–8; Pub 925 §1',
                "Remove all mappings from Acct.Rev.* to P1_1a/P1_3/P1_7/P1_8 "
                "in BookToIRS Aid; re-run pipeline",
                fids=list(bad.keys()))

    def _rule_pg1_deductions_must_be_zero(self):
        """
        IRS Rule: Form 1065 Instructions Lines 9–22 apply to ORDINARY
        business deductions only. Rental expenses (repairs, mortgage interest,
        property taxes, utilities, depreciation) are deducted on Form 8825
        Lines 5–17, not on Form 1065 Page 1.
        Specifically: Line 16a — "Enter depreciation and cost recovery EXCEPT
        for rental real estate activities. Rental depreciation → Form 8825 Line 14."
        """
        fill = self._load_fill_dict()
        bad  = {k: _safe_float(fill.get(k)) for k in self._PG1_DEDUCTION_KEYS
                if abs(_safe_float(fill.get(k))) > 0.01}
        if bad:
            lines = ', '.join(f"{k}=${v:,.2f}" for k, v in bad.items())
            return self.format_issue(
                'IS-R02', self.ERROR,
                f"Deductions appear on Form 1065 Page 1 — IRS violation. "
                f"Rental expenses must NOT be on Page 1 Lines 9–22. Affected: {lines}. "
                f"All rental expenses (including depreciation on Line 16a) belong on "
                f"Form 8825 Lines 5–17; rental depr specifically on Form 8825 Line 14.",
                'Form 1065 Instructions Lines 9–22 and Line 16a; IRC §469',
                "Remove all rental expense mappings from P1_9/11/14/15/16a/21/22 "
                "in BookToIRS Aid. Re-run pipeline.",
                fids=list(bad.keys()))

    def _rule_rental_depr_not_on_pg1(self):
        """
        IRS Rule: Form 1065 Instructions Line 16a explicitly states:
        "Enter the depreciation... EXCEPT for rental real estate activities.
        Rental real estate depreciation is reported on Form 8825, Line 14."
        Books source: IS.depreciation (Acct.Exp.Depreciation).
        Correct path: IS.depreciation → Form 4562 Part III → Form 8825 Line 14
                      → Schedule K Line 2 (via net rental calculation).
        P1_16a must always be $0 for a pure rental LLC.
        """
        fill = self._load_fill_dict()
        p1_16a = _safe_float(fill.get('P1_16a'))
        book_depr = self._get_is_agg('depreciation')
        if p1_16a > 0.01:
            return self.format_issue(
                'IS-R03', self.ERROR,
                f"Depreciation ${p1_16a:,.2f} appears on Page 1 Line 16a — IRS violation. "
                f"Rental property depreciation is NEVER on Form 1065 Page 1. "
                f"IRS Instructions Line 16a: 'Do not include rental real estate activities.' "
                f"Books show ${book_depr:,.2f} depreciation → correct path: "
                f"Form 4562 Part III Line 19h → Form 8825 Line 14 → Schedule K Line 2.",
                'Form 1065 Instructions Line 16a; IRC §168; Form 8825 Instructions Line 14',
                "Remove P1_16a mapping from BookToIRS Aid. "
                "Verify Form 8825 Line 14 mapping uses IS.depreciation from books.",
                fids=['P1_16a', 'P1_16c'])
        if book_depr > 0.01 and p1_16a < 0.01:
            return self.format_issue(
                'IS-R04', self.INFO,
                f"Page 1 Line 16a = $0 (correct for rental LLC). "
                f"Books show ${book_depr:,.2f} depreciation → verify it appears on "
                f"Form 8825 Line 14 and Form 4562 Part III Line 19h.",
                'Form 1065 Instructions Line 16a; Form 8825 Line 14',
                "Confirm Form 8825 and Form 4562 are generated with the correct "
                f"IS.depreciation value (${book_depr:,.2f}) from books.")

    def _rule_books_have_rental_activity(self):
        """
        Positive verification: confirm books contain rental income/expense.
        If books show $0 for all rental activity, something is wrong with
        the ledger data — flag before the filing is produced.
        IRS expects Form 8825 to be filed when rental activity exists.
        Books source: IS.rent_income (Acct.Rev.Rent.*), IS.total_expenses.
        """
        agg       = self._get_is()
        rent      = abs(_safe_float(agg.get('rent_income', 0)))
        expenses  = abs(_safe_float(agg.get('total_expenses', 0)))
        depr      = abs(_safe_float(agg.get('depreciation', 0)))
        if rent < 0.01 and expenses < 0.01:
            return self.format_issue(
                'IS-R05', self.WARN,
                "Books show $0 rental income and $0 expenses. "
                "If the property was active during the year, ledger entries may be "
                "missing from llcExpRev (Acct.Rev.Rent.*) or llcAssets. "
                "An empty IS will produce a blank Form 8825 and Schedule K.",
                'IRC §6031 — partnership must report all income/loss',
                "Verify Acct.Rev.Rent.* entries exist in llcExpRev for the tax year. "
                "Check llcAssets for the property's placed-in-service date.")
        if rent > 0.01 and depr < 0.01:
            return self.format_issue(
                'IS-R06', self.WARN,
                f"Books show rental income ${rent:,.2f} but $0 depreciation. "
                f"A residential rental property (27.5-yr MACRS) should have a "
                f"depreciation entry (Acct.Exp.Depreciation) for each tax year "
                f"the property is in service.",
                'IRC §168; Form 4562 Instructions Part III; Pub 946',
                "Verify YE depreciation entry exists in llcAssets "
                "(Acct.Exp.Depreciation with YE:Acct.Exp.Depreciation acctSub). "
                "MACRS Year 1: ~5/12 of annual rate if placed in service mid-year.")

    def _rule_line23_must_be_zero(self):
        """
        IRS Rule: For a pure rental LLC, Form 1065 Page 1 Line 23
        (Ordinary Business Income/Loss) = $0.
        Line 23 = Line 8 − Line 22. Since both Lines 8 and 22 are $0
        for a rental LLC, Line 23 must also be $0.
        All rental income/loss flows to Schedule K Line 2 (net rental),
        not to Line 23 (ordinary income).
        """
        fill = self._load_fill_dict()
        l23  = _safe_float(fill.get('P1_23'))
        l8   = _safe_float(fill.get('P1_8'))
        l22  = _safe_float(fill.get('P1_22'))
        if abs(l23) > 0.01:
            return self.format_issue(
                'IS-R07', self.ERROR,
                f"Line 23 (Ordinary Business Income) = ${l23:,.2f} — must be $0 "
                f"for a pure rental LLC. Rental income/loss flows to Schedule K "
                f"Line 2 (net rental), not to Page 1 Line 23 (ordinary income). "
                f"IRS: IRC §469(c)(2) — rental = passive, never ordinary.",
                'IRC §469(c)(2); Form 1065 Instructions Line 23',
                "Remove P1_23 mapping from BookToIRS Aid. Line 23 auto-derives "
                "from Line 8 − Line 22; both must be $0.",
                fids=['P1_23'],
                auto_fix=True)
        if l8 != 0 or l22 != 0:
            return self.format_issue(
                'IS-R08', self.WARN,
                f"Line 23 arithmetic inconsistency: Line 8 (${l8:,.2f}) − "
                f"Line 22 (${l22:,.2f}) ≠ Line 23 (${l23:,.2f}). "
                f"For rental LLC, all three should be $0.",
                'Form 1065 Instructions Line 23',
                "Re-run pipeline; verify no expense or income mappings exist for "
                "Page 1 lines.",
                auto_fix=True)


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_Other — Schedule B (Pages 2–3)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_Other(_SectionAgent):
    """
    IRS Knowledge Base — Form 1065 Schedule B: Other Information (Pages 2–3)

    Schedule B is a series of Yes/No compliance disclosures. The IRS uses
    these answers to determine: (a) what additional forms/schedules apply,
    (b) ownership structure for related-party rules, (c) BBA audit regime.

    Key questions for W&B Group:

    Q1 (Partnership type): Small domestic partnership? → Affects audit regime.

    Q3a (Individual majority owner): Does any individual/estate/trust own >50%?
      Must be answered. Affects §267 related-party rules and audit complexity.

    Q3b (Entity majority owner): Any corporation/partnership/trust own >50%?
      If Yes, additional disclosure may be needed under §267(b)/(c).

    Q4(c) (Schedule L/M-1/M-2 not required): The MOST IMPORTANT question.
      Gross receipts < $250K OR total assets < $1M → answer "Yes" → skip
      Schedules L, M-1, M-2 entirely. This is mandatory, not optional.
      Getting this wrong (filing empty schedules unnecessarily) creates
      IRS automated audit triggers.

    Q4d (Distributions): Did the partnership distribute money or property?
      Must be answered Yes if any partner received any cash distribution.
      Links to K-1 Box 19 and Schedule M-2 capital account analysis.

    Q21 (BBA opt-out): IRC §6221(b) — partnerships with ≤100 qualifying
      partners may elect out of the centralized partnership audit regime.
      This is a one-time annual election. Default = in the BBA regime.
      Electing out means IRS audits each partner separately (complex).

    Partnership Representative (Section): Required for all BBA partnerships.
      IRC §6223 + Treas. Reg. §301.6223-1. See AgentF1065_Info docstring.
    """

    LABEL             = 'Schedule B'
    AGENT_KEY         = 'AgentF1065_Other'
    LOGICAL_PREFIXES  = ['B_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_schedule_threshold,
            self._rule_pr_named,
            self._rule_ownership_questions,
            self._rule_sched_b_q3_ownership_pct,
            self._rule_sched_b_q4d_distributions,
            self._rule_sched_b_review_blanks,
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
        first = self._fv('B_PRDI_FirstNm', '').strip()
        last  = self._fv('B_PRDI_Last', '').strip()
        if not first and not last:
            return self.format_issue(
                'OT-R02', self.ERROR,
                "Partnership Representative not named on Schedule B "
                "(B_PR_1=First Name, B_PR_2=Last Name are blank in the fill dict)",
                'IRC §6223; Treas. Reg. §301.6223-1',
                "Set F1065.B_PRDI_FirstNm and B_PRDI_Last in llcProfile, "
                "then use Aid to map Profile.F1065.B_PRDI_FirstNm → B_PR_1",
                fids=['B_PR_1', 'B_PR_2', 'B_PR_7'],
                suggested_mapping={'fid': 'B_PR_1', 'src': 'Profile',
                                   'path': 'Profile.F1065.B_PRDI_FirstNm'})

    def _rule_ownership_questions(self):
        owners = self._get_owners()
        def _pct(o):
            v = _safe_float(o.get('pct', o.get('ownership_pct', 0)))
            return v if v <= 1.5 else v / 100
        majority = [o for o in owners if _pct(o) > 0.5]
        if majority:
            return self.format_issue(
                'OT-R05', self.INFO,
                f"Schedule B Q2/Q3: {len(majority)} partner(s) own >50% — "
                f"ownership disclosure questions must be answered",
                'Form 1065 Instructions, Schedule B Q2-3',
                "Confirm Schedule B Q2/Q3 answers in BookToIRS Aid")

    def _rule_sched_b_q3_ownership_pct(self):
        """
        Sched B Q3a: At end of year, any individual/estate/trust own >50%?
        Sched B Q3b: Any corporation/partnership/trust own >50%?
        These must be explicitly answered Yes or No — defaulting to No is not safe.
        """
        owners = self._get_owners()
        def _pct(o):
            v = _safe_float(o.get('pct', o.get('ownership_pct', 0)))
            return v if v <= 1.5 else v / 100
        indiv_majority = any(_pct(o) > 0.5 and
                             str(o.get('memType','')).lower() in
                             ('individual','person','estate','trust','') for o in owners)
        return self.format_issue(
            'OT-R06', self.WARN,
            f"Schedule B Q3a (individual >50% owner) must be explicitly answered. "
            f"Based on llcOwners: {'YES — an individual holds >50%' if indiv_majority else 'NO — no individual holds >50%'}. "
            f"Verify this matches what is filed.",
            'Form 1065 Instructions, Schedule B Q3a-3b',
            "Confirm Q3a Yes/No in the form. If Yes: answer Q3a; "
            "if any corp/partnership/trust holds >50%, also answer Q3b.",
            fids=['B_3a', 'B_3b'])

    def _rule_sched_b_q4d_distributions(self):
        """
        Sched B Q4d: Did the partnership distribute money or property to any partner?
        Must be Yes or No explicitly. Auto-detect from owners distributions.
        """
        owners = self._get_owners()
        has_distrib = any(_safe_float(o.get('distributions',
                         o.get('distrib', o.get('cash_out', 0)))) > 0 for o in owners)
        if has_distrib:
            return self.format_issue(
                'OT-R07', self.WARN,
                "Schedule B Q4d: Distributions detected in llcOwners — "
                "Q4d 'Did the partnership distribute money or property?' must be answered Yes.",
                'Form 1065 Instructions, Schedule B Q4d',
                "Confirm Q4d = Yes in form. Map to B_4d checkbox via Aid.",
                fids=['B_4d'])
        else:
            return self.format_issue(
                'OT-R07', self.INFO,
                "Schedule B Q4d: No distributions found in llcOwners — "
                "confirm Q4d = No is correct before filing.",
                'Form 1065 Instructions, Schedule B Q4d',
                "Verify Q4d answer against actual cash distributions during the year.",
                fids=['B_4d'])

    def _rule_sched_b_review_blanks(self):
        """
        General: Sched B defaults all Yes/No to 'No' — bookkeeper must confirm key questions.
        Flag as WARN to prompt a review pass on Schedule B.
        """
        return self.format_issue(
            'OT-R08', self.WARN,
            "Schedule B Yes/No questions default to 'No' in the fill dict. "
            "Key questions requiring explicit bookkeeper review: "
            "Q3a (individual >50% owner), Q3b (entity >50% owner), "
            "Q4a (did partnership dispose of property?), "
            "Q4d (distributions made?), Q21 (BBA opt-out election).",
            'Form 1065 Instructions, Schedule B',
            "Review each Schedule B question in the FILL.pdf and use Aid to override "
            "any 'No' that should be 'Yes' for this LLC's specific situation.",
            fids=['B_3a', 'B_3b', 'B_4a', 'B_4d', 'B_21'])


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_Distr — Schedule K (Page 4)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_Distr(_SectionAgent):
    """
    IRS Knowledge Base — Form 1065 Schedule K: Partners' Distributive Share

    Schedule K collects ALL partnership-level items that flow to partners'
    individual returns via Schedule K-1. It is NOT another income statement —
    it is a structured allocation register.

    Key IRS rules for W&B Group (rental LLC):

    Line 1 (Ordinary Business Income): Must be $0.
      IRC §469(c)(2) — rental activity is passive; it never produces ordinary
      income. Line 1 = Form 1065 Page 1 Line 23 = $0 for rental LLC.

    Line 2 (Net Rental Real Estate Income/Loss): The central line.
      This is the NET from all rental properties after all rental expenses.
      IRS: Derived from Form 8825 Line 21 (sum of all properties' net).
      Books-First: Schedule K Line 2 = IS.net_rental (total_income − total_expenses).
      It is NET, not gross. IS.rent_income (gross) ≠ Schedule K Line 2.

    Lines 1–11 (income/loss items): Each sourced from books independently.
      IRC §702(a): partners are taxed on their distributive share of each
      separately stated item. The partnership must report each item separately.

    IRC §704(b) allocation: All Schedule K totals must sum to 100% across
      all K-1s. The allocation mechanism (pro-rata or special) must match
      the LLC's operating agreement.

    Line 14 (Self-Employment Income): Must be $0.
      IRC §1402(a)(13): limited partners and members of rental LLCs are
      not subject to self-employment tax on rental income. Rental income
      is not "net earnings from self-employment" by statute.

    Books-First (IRC §446 + §703): all values from stmtIS.taxAggregates().
    """

    LABEL             = 'Schedule K'
    AGENT_KEY         = 'AgentF1065_Distr'
    LOGICAL_PREFIXES  = ['K_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_k1_must_be_zero,
            self._rule_k2_matches_books,
            self._rule_k2_is_net_not_gross,
            self._rule_partner_alloc_100,
            self._rule_no_se_income,
        ])

    def pass5_summarize(self) -> str:
        net_rental = self._get_is_agg('net_rental')
        sign       = 'income' if net_rental >= 0 else 'loss'
        owners     = self._get_owners()
        n          = len(owners)
        fill       = self._load_fill_dict()
        k2_filed   = _safe_float(fill.get('K_2'))
        return (f"Schedule K Line 2 = ${k2_filed:,.2f} (net rental {sign} per books: "
                f"${net_rental:,.2f}). Line 1 = $0. "
                f"Allocates to {n} partner{'s' if n != 1 else ''} per §704(b).")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_k1_must_be_zero(self):
        """
        IRS Rule: Schedule K Line 1 (Ordinary Business Income/Loss) = $0.
        Line 1 carries Form 1065 Page 1 Line 23 — which is $0 for rental LLC
        because IRC §469(c)(2) classifies all rental activity as passive.
        Passive activity income is never "ordinary business income."
        If K_1 is non-zero, it means either Page 1 was filled incorrectly
        or a non-rental activity exists that the bookkeeper must explain.
        """
        fill = self._load_fill_dict()
        k1   = _safe_float(fill.get('K_1'))
        if abs(k1) > 0.01:
            return self.format_issue(
                'KD-R01', self.ERROR,
                f"Schedule K Line 1 (Ordinary Business Income) = ${k1:,.2f}. "
                f"Must be $0 for a pure rental LLC. "
                f"IRC §469(c)(2): all rental income is passive — it belongs on "
                f"Schedule K Line 2, not Line 1. "
                f"A non-zero K_1 indicates Page 1 Lines 1–23 were filled incorrectly.",
                'IRC §469(c)(2); Form 1065 Instructions Schedule K Line 1',
                "Verify Page 1 Lines 1–23 are all $0; remove K_1 mapping from BookToIRS Aid.",
                fids=['K_1'])

    def _rule_k2_matches_books(self):
        """
        IRS Rule: Schedule K Line 2 = net rental real estate income/loss.
        IRS Instructions: "Enter the net income or loss from rental real
        estate activities. Use the amounts from Form 8825, Line 21."
        Books-First: Form 8825 Line 21 is itself IS.net_rental from books.
        Therefore K_2 = IS.net_rental = IS.total_income − IS.total_expenses.
        Verify the fill dict K_2 matches this books value within $1.00.
        """
        fill       = self._load_fill_dict()
        k2_filed   = _safe_float(fill.get('K_2'))
        net_rental = self._get_is_agg('net_rental')

        if k2_filed == 0 and abs(net_rental) < 0.01:
            return None  # both $0, no rental activity to verify

        if k2_filed == 0 and abs(net_rental) > 0.01:
            return self.format_issue(
                'KD-R02', self.ERROR,
                f"Schedule K Line 2 is blank but books show net rental "
                f"{'income' if net_rental >= 0 else 'loss'} ${net_rental:,.2f}. "
                f"K_2 must equal IS.net_rental (Books-First: IRC §446/703). "
                f"A blank K_2 means rental activity is NOT flowing to partners.",
                'Form 1065 Instructions Schedule K Line 2; IRC §702(a)',
                "Map IS.net_rental → K_2 in bookNS_IS.json; re-run BookToIRS pipeline.",
                fids=['K_2'])

        if abs(k2_filed - net_rental) > 1.00:
            return self.format_issue(
                'KD-R03', self.WARN,
                f"Schedule K Line 2 = ${k2_filed:,.2f} but books (IS.net_rental) "
                f"= ${net_rental:,.2f}. Discrepancy: ${abs(k2_filed - net_rental):,.2f}. "
                f"Books-First (IRC §446): K_2 must derive from IS.net_rental, "
                f"not from any other form's value.",
                'IRC §446; Form 1065 Instructions Schedule K Line 2',
                "Re-run BookToIRS pipeline. Verify bookNS_IS.json maps "
                "K_2 → IS.net_rental (not IS.rent_income or any form-sourced value).",
                fids=['K_2'])

    def _rule_k2_is_net_not_gross(self):
        """
        IRS Rule: Schedule K Line 2 = NET rental income, not gross rent.
        IRS Instructions: "net income or loss" — meaning after all deductions.
        Gross rental receipts (IS.rent_income) ≠ Schedule K Line 2.
        Correct: IS.net_rental = IS.total_income − IS.total_expenses.
        Common mistake: mapping IS.rent_income (gross) to K_2.
        This under-states deductions to partners and over-states taxable income.
        """
        fill       = self._load_fill_dict()
        k2_filed   = _safe_float(fill.get('K_2'))
        gross_rent = self._get_is_agg('rent_income')
        net_rental = self._get_is_agg('net_rental')
        if abs(gross_rent) < 0.01:
            return None
        if abs(k2_filed - gross_rent) < 0.01 and abs(gross_rent - net_rental) > 0.01:
            return self.format_issue(
                'KD-R04', self.ERROR,
                f"Schedule K Line 2 = ${k2_filed:,.2f} appears to be GROSS rent "
                f"(IS.rent_income = ${gross_rent:,.2f}), not NET rental income "
                f"(IS.net_rental = ${net_rental:,.2f}). "
                f"IRS Instructions: Line 2 = net income AFTER all rental expenses. "
                f"Filing gross rent on K_2 omits ${abs(gross_rent - net_rental):,.2f} "
                f"of deductions from partners' returns.",
                'Form 1065 Instructions Schedule K Line 2; IRC §702(a)',
                "Change bookNS_IS.json K_2 mapping from IS.rent_income → IS.net_rental. "
                "Re-run BookToIRS pipeline.",
                fids=['K_2'])

    def _rule_partner_alloc_100(self):
        """
        IRS Rule: IRC §704(b) — all partnership items must be allocated 100%.
        The sum of all partners' ownership percentages must equal exactly 1.0 (100%).
        If percentages don't sum to 100%, the K-1 allocations will be incorrect
        and IRS automated matching will flag the discrepancy.
        """
        owners = self._get_owners()
        if not owners:
            return None
        total    = sum(_safe_float(o.get('pct', o.get('ownership_pct', 0))) for o in owners)
        expected = 1.0 if total <= 1.5 else 100.0
        if abs(total - expected) > 0.01:
            pct_str = f"{total*100:.2f}%" if expected == 1.0 else f"{total:.2f}%"
            return self.format_issue(
                'KD-R05', self.ERROR,
                f"Partner ownership percentages sum to {pct_str} (must be exactly 100%). "
                f"IRC §704(b): all partnership items must be allocated in full. "
                f"K-1 amounts will be under/over-allocated until this is corrected.",
                'IRC §704(b); Form 1065 Instructions Schedule K-1',
                "Correct pct values in llcOwners DB so they sum to exactly 1.0 (or 100).")

    def _rule_no_se_income(self):
        """
        IRS Rule: IRC §1402(a)(13) — limited partners are NOT subject to
        self-employment tax on their distributive share of partnership income.
        For a rental LLC: IRC §1402(a)(1) additionally excludes rental income
        from net earnings from self-employment.
        Schedule K Line 14 (SE income) must be $0 for a pure rental LLC.
        Filing non-zero SE income here would incorrectly trigger SE tax
        (~15.3%) on partners' personal returns.
        """
        fill = self._load_fill_dict()
        k14  = _safe_float(fill.get('K_14a') or fill.get('K_14'))
        if abs(k14) > 0.01:
            return self.format_issue(
                'KD-R06', self.ERROR,
                f"Schedule K Line 14 (SE income) = ${k14:,.2f}. "
                f"Must be $0 for rental LLC. "
                f"IRC §1402(a)(1): rental income is not 'net earnings from self-employment.' "
                f"IRC §1402(a)(13): limited partners are exempt from SE tax. "
                f"Filing non-zero K_14 will incorrectly trigger 15.3% SE tax on partners.",
                'IRC §1402(a)(1); IRC §1402(a)(13); Pub 541 (Partnerships)',
                "Remove any mapping to K_14; verify it is blank in the fill dict.",
                fids=['K_14', 'K_14a'])


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_Reconcile — Schedules L, M-1, M-2 (Page 5)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_Reconcile(_SectionAgent):
    """
    IRS Knowledge Base — Schedules L, M-1, M-2 (Form 1065 Page 5)

    These three schedules are an IRS audit trail — they tie the tax return
    to the books and explain every dollar of difference.

    Schedule L (Balance Sheet per Books):
      Required if Schedule B Q4 threshold is crossed (gross receipts ≥ $250K
      AND total assets ≥ $1M; see Treas. Reg. §1.6031(a)-1(b)(4)).
      Must match the BS exactly. Line 14 = BS.total_assets (Books-First).
      If Schedule L doesn't tie to the books, it signals to IRS auditors
      that the books are unreliable.

    Schedule M-1 (Reconciliation of Income per Books with Return):
      Explains every difference between book net income and taxable income.
      Required at same threshold as Schedule L.
      M-1 Line 1 = IS.net_income (book basis, from stmtIS.taxAggregates()).
      M-1 Line 9 = Schedule K Line 1 = $0 for rental LLC.
      For rental LLC: M-1 reconciliation shows that book net income (which
      includes rental activity) = $0 ordinary income, because rental income
      passes through Schedule K Line 2, not Line 1.

    Schedule M-2 (Analysis of Partners' Capital Accounts):
      Required at same threshold as Schedule L.
      Must use tax basis method (post-2020 IRS requirement).
      Per IRC §705: each partner's basis = contributions + income − losses − distributions.
      Schedule M-2 is the aggregate view; K-1 Box L is the per-partner view.

    Below-threshold behavior (this LLC): Schedules L/M-1/M-2 are NOT required.
      Answer "Yes" to Schedule B Q4(c): "Is the partnership not required to
      file Schedules L, M-1, and M-2?" This completely skips these pages.

    Books-First (IRC §446 + §703): all values from stmtIS/stmtBS.taxAggregates().
    """

    LABEL             = 'Schedules L / M-1 / M-2'
    AGENT_KEY         = 'AgentF1065_Reconcile'
    LOGICAL_PREFIXES  = ['L_', 'M1_', 'M2_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_schedules_required_check,
            self._rule_sched_l_balance,
            self._rule_m1_book_income,
            self._rule_m1_line9_zero_for_rental,
            self._rule_m2_capital_basis_method,
        ])

    def pass5_summarize(self) -> str:
        required = self._schedules_required()
        if not required:
            gross  = self._get_is_total('Income')
            assets = self._get_bs_total_assets()
            return (f"Schedules L/M-1/M-2 NOT required (Schedule B Q4 = Yes). "
                    f"LLC is below both thresholds: "
                    f"gross income ${gross:,.0f} < $250K and/or "
                    f"total assets ${assets:,.0f} < $1M.")
        total_assets = self._get_bs_total_assets()
        book_ni      = self._get_is_agg('net_income')
        return (f"Schedule L: total assets ${total_assets:,.2f}. "
                f"M-1 Line 1 = ${book_ni:,.2f} (book net income). "
                f"M-1 Line 9 = $0 (ordinary return income = $0 for rental LLC). "
                f"M-2: tax basis method per post-2020 IRS requirement.")

    def _schedules_required(self) -> bool:
        gross  = self._get_is_total('Income')
        assets = self._get_bs_total_assets()
        return gross >= 250_000 and assets >= 1_000_000

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_schedules_required_check(self):
        """
        IRS Rule: Form 1065 Instructions, Schedule B Question 4(c).
        Schedules L, M-1, and M-2 are ONLY required if BOTH:
          (a) total gross receipts for the year ≥ $250,000, AND
          (b) total assets at year-end ≥ $1,000,000.
        If either threshold is not met, answer 'Yes' to Q4(c) and skip
        these schedules entirely. Filing empty or zero schedules when not
        required wastes space and creates IRS matching noise.
        """
        gross  = self._get_is_total('Income')
        assets = self._get_bs_total_assets()
        if not (gross >= 250_000 and assets >= 1_000_000):
            return self.format_issue(
                'RC-R01', self.INFO,
                f"Schedules L/M-1/M-2 NOT required. "
                f"Gross receipts ${gross:,.0f} {'≥' if gross >= 250_000 else '<'} $250K threshold; "
                f"total assets ${assets:,.0f} {'≥' if assets >= 1_000_000 else '<'} $1M threshold. "
                f"Schedule B Q4(c) should answer 'Yes' to skip these schedules.",
                'Form 1065 Instructions, Schedule B Q4(c); Treas. Reg. §1.6031(a)-1(b)(4)',
                "Confirm Schedule B Q4(c) = Yes in the form. "
                "Leave Schedules L/M-1/M-2 entirely blank.")

    def _rule_sched_l_balance(self):
        """
        IRS Rule: Schedule L (Balance Sheet per Books) must agree exactly
        with the partnership's books (Books-First — IRC §446/703).
        Schedule L Line 14 (total assets, end of year) = BS.total_assets.
        If L_14_2 ≠ BS.total_assets, the IRS balance sheet does not reconcile
        to the accounting balance sheet — a red flag in any IRS audit.
        """
        if not self._schedules_required():
            return None
        fill      = self._load_fill_dict()
        l14_end   = _safe_float(fill.get('L_14_2'))
        bs_assets = self._get_bs_total_assets()
        if bs_assets > 0 and abs(l14_end - bs_assets) > 1.00:
            return self.format_issue(
                'RC-R02', self.ERROR,
                f"Schedule L Line 14 (total assets, end) = ${l14_end:,.2f} "
                f"but BS.total_assets = ${bs_assets:,.2f}. "
                f"Discrepancy: ${abs(l14_end - bs_assets):,.2f}. "
                f"Schedule L must equal the books (IRC §446 Books-First rule). "
                f"IRS: a balance sheet that doesn't tie to books is an audit trigger.",
                'Form 1065 Instructions Schedule L; IRC §446',
                "Verify L_14_2 mapping uses BS.total_assets from books. "
                "Re-run BookToIRS pipeline.",
                fids=['L_14_2'])

    def _rule_m1_book_income(self):
        """
        IRS Rule: Schedule M-1 Line 1 = net income (loss) per books.
        This is the STARTING POINT of the book-to-tax reconciliation.
        Books-First: M-1 Line 1 = IS.net_income from stmtIS.taxAggregates().
        If M-1 Line 1 doesn't match the books, the entire M-1 reconciliation
        is built on a wrong foundation.
        """
        if not self._schedules_required():
            return None
        fill      = self._load_fill_dict()
        m1_line1  = _safe_float(fill.get('M1_1'))
        book_ni   = self._get_is_agg('net_income')
        if abs(book_ni) < 0.01:
            return None
        if abs(m1_line1 - book_ni) > 1.00:
            return self.format_issue(
                'RC-R03', self.WARN,
                f"M-1 Line 1 (net income per books) = ${m1_line1:,.2f} "
                f"but IS.net_income from books = ${book_ni:,.2f}. "
                f"M-1 Line 1 must equal the books (Books-First: IRC §446). "
                f"M-1 reconciliation is invalid if Line 1 doesn't start from the correct book income.",
                'Form 1065 Instructions Schedule M-1 Line 1; IRC §446; IRC §703',
                "Verify M1_1 maps to IS.net_income in bookNS_IS.json. Re-run pipeline.",
                fids=['M1_1'])

    def _rule_m1_line9_zero_for_rental(self):
        """
        IRS Rule: Schedule M-1 Line 9 = income (loss) per return.
        For a rental LLC, "income per return" = Schedule K Line 1 = $0.
        All rental income/loss is on Schedule K Line 2 (passive rental),
        not Line 1 (ordinary business income).
        Therefore M-1 Line 9 must be $0 for a pure rental LLC.
        Common error: mapping IS.net_income to M1_9, which would incorrectly
        show the rental loss as ordinary income on the return.
        """
        if not self._schedules_required():
            return None
        fill   = self._load_fill_dict()
        m1_l9  = _safe_float(fill.get('M1_9'))
        if abs(m1_l9) > 0.01:
            return self.format_issue(
                'RC-R04', self.ERROR,
                f"M-1 Line 9 (income per return) = ${m1_l9:,.2f}. "
                f"Must be $0 for rental LLC. "
                f"Line 9 = Schedule K Line 1 (ordinary income) = $0 for rental LLC. "
                f"Rental income/loss is on Schedule K Line 2, never on Line 1. "
                f"A non-zero M-1 Line 9 indicates IS.net_income was incorrectly mapped here.",
                'Form 1065 Instructions Schedule M-1 Line 9; IRC §469(c)(2)',
                "Remove M1_9 mapping from bookNS_IS.json. "
                "M-1 Line 9 should be blank/$0 for rental LLC.",
                fids=['M1_9'])

    def _rule_m2_capital_basis_method(self):
        """
        IRS Rule: Post-2020 requirement — Schedule M-2 and K-1 Box L must
        use the TAX BASIS METHOD of capital reporting.
        Previous methods (§704(b) book value, GAAP, or other) are no longer
        accepted on Form 1065 for tax years ending 2020 and later.
        Rev. Proc. 2020-13; TD 9902; Form 1065 Instructions M-2.
        Tax basis = actual amounts contributed + taxable income allocated
                    − deductions allocated − actual distributions.
        Only needs audit if Schedule L/M-1/M-2 are required.
        """
        if not self._schedules_required():
            return None
        return self.format_issue(
            'RC-R05', self.INFO,
            "Schedule M-2 must use the TAX BASIS METHOD of capital reporting "
            "(IRS requirement for tax years 2020+). "
            "Verify: partner capital accounts reflect actual tax basis "
            "(contributions + taxable income − deductions − distributions), "
            "NOT §704(b) book value or GAAP basis. "
            "K-1 Box L must use the same tax basis method.",
            'Rev. Proc. 2020-13; TD 9902; Form 1065 Instructions Schedule M-2',
            "Confirm with CPA that M-2 uses tax basis. "
            "If partners' capital accounts were previously tracked on a different "
            "basis, a conversion computation may be needed.")


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
        Always returns sections as an ordered list (safe for JS forEach).
        """
        state = self._load_session_state()
        if state is None:
            return self._empty_summary()
        return self._normalize_summary(state)

    def _normalize_summary(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Convert sections dict (from session JSON) to ordered list for the UI."""
        raw = state.get('sections', {})
        if isinstance(raw, list):
            sections_list = raw
        else:
            sections_list = []
            for cls in self._SECTION_ORDER:
                key = cls.AGENT_KEY
                s   = raw.get(key, {})
                sections_list.append({
                    'agent':         key,
                    'label':         s.get('label', cls.LABEL),
                    'state':         s.get('state', self.NOT_STARTED),
                    'summary':       s.get('summary', 'Not yet run'),
                    'halt_count':    s.get('halt_count', 0),
                    'resolve_count': s.get('resolve_count', 0),
                    'review_count':  s.get('review_count', 0),
                })
        return {
            'tax_year':      state.get('tax_year', self.tax_year),
            'last_run':      state.get('last_run'),
            'overall_state': state.get('overall_state', self.NOT_STARTED),
            'sections':      sections_list,
            'ext_advice':    state.get('ext_advice', ''),
        }

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
