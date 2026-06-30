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

    # Form1065 namespace has no keys PDF → logicalKeys are empty strings.
    # Map shortName → logicalKey for every field checked by audit rules.
    _SHORT_TO_LK: Dict[str, str] = {
        'f5_01': 'K_1',   # Schedule K Line 1: ordinary business income
        'f5_02': 'K_2',   # Schedule K Line 2: net rental real estate income
        'f5_49': 'K_19a', # Schedule K Line 19a: cash distributions to partners
    }

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
        """Load Form1065_fillDict.json if it exists; else fall back to FILL.pdf."""
        forms_dir = self._forms_dir()
        if forms_dir is None:
            return {}
        p = forms_dir / 'Form1065_fillDict.json'
        if p.exists():
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
                if result:
                    return result
            except Exception:
                pass
        # Fallback: read FILL.pdf directly using _SHORT_TO_LK (namespace has no logicalKeys)
        fill_path = forms_dir / 'Form1065_FILL.pdf'
        if not fill_path.exists():
            return {}
        try:
            from pypdf import PdfReader
            rdr = PdfReader(str(fill_path))
            pdf_fields = rdr.get_fields() or {}
            result = {}
            for fobj in pdf_fields.values():
                if not isinstance(fobj, dict):
                    continue
                sn = fobj.get('/T', '')
                if sn.endswith('[0]'):
                    sn = sn[:-3]
                lk = self._SHORT_TO_LK.get(sn)
                if lk:
                    val = fobj.get('/V', '')
                    if val and val not in ('/Off', '/No', ''):
                        result[lk] = val
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
                f"⚠ Form 1065: the LLC's EIN (tax ID number) is missing or invalid (found: '{self._ev('ein')}').\n"
                f"  • A valid 9-digit EIN is required on every Form 1065 — without it, the IRS will reject the filing.",
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
                "⚠ Form 1065: the LLC's legal name is blank on Page 1.\n"
                "  • The exact legal name is required — the IRS uses name + EIN together to match tax filings.",
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
                "Form 1065 Line H (Accounting Method) is blank — either 'Cash' or 'Accrual' must be checked.\n"
                "  • For W&B Group: Accrual is appropriate (the LLC tracks depreciation and assets over time).",
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
                f"Form 1065 Line I (Number of K-1s) shows {int(fd_count) if fd_count else 'blank'}, but the LLC has {live_count} partner(s).\n"
                f"  • Line I must match the actual number of partners — one K-1 is required for each.",
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
            "Form 1065 Line K (At-Risk): For a rental LLC funded by partner cash contributions, all partners are generally 'at risk'.\n"
            "  • This checkbox needs to be confirmed and checked — the default is usually 'Yes' for a small LLC without unusual financing.",
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
                "⚠ Form 1065: the Partnership Representative (the person who acts on behalf of the LLC in any IRS audit) is not named.\n"
                "  • Every LLC filing Form 1065 must designate a Partnership Representative on Schedule B.\n"
                "  • For W&B Group, this is typically the managing member (Francis).",
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
                "Form 1065: no filing type is checked (Initial Return / Final Return / Amended Return).\n"
                "  • For W&B Group's first tax year, 'Initial Return' should be checked.",
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
                f"⚠ The field mapping file (bookNS_IS) is sending rental income/expense data to Form 1065 Page 1 (Lines 1–23) — this is incorrect.\n"
                f"  • Rental LLC income belongs on Form 8825, not Form 1065 Page 1. Page 1 must show $0 for all income/deduction lines.\n"
                f"  • Affected mappings: {lst}.",
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
            f"✓ Form 1065 Page 1 (Lines 1–23) is correctly blank — no rental income or expenses appear here.\n"
            f"  • Net rental {sign} of ${abs(net):,.2f} flows through Form 8825 → Schedule K Line 2 → each partner's K-1 Box 2.",
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
                f"⚠ Rental income is appearing on Form 1065 Page 1 Lines 1–8 — this is wrong for a rental LLC.\n"
                f"  • Rental income belongs on Form 8825 (per-property) → Schedule K Line 2, NOT on Page 1.\n"
                f"  • Affected lines: {lines}.",
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
                f"⚠ Rental expenses are appearing on Form 1065 Page 1 Lines 9–22 — this is wrong for a rental LLC.\n"
                f"  • All rental expenses (including depreciation) belong on Form 8825, not Form 1065 Page 1.\n"
                f"  • Affected lines: {lines}.",
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
                f"⚠ Depreciation of ${p1_16a:,.2f} is showing on Form 1065 Page 1 Line 16a — this is wrong for a rental property.\n"
                f"  • Rental property depreciation goes on Form 8825 Line 14, not Form 1065 Page 1.\n"
                f"  • The IRS instructions for Line 16a explicitly say: 'Do not include rental real estate activities.'",
                'Form 1065 Instructions Line 16a; IRC §168; Form 8825 Instructions Line 14',
                "Remove P1_16a mapping from BookToIRS Aid. "
                "Verify Form 8825 Line 14 mapping uses IS.depreciation from books.",
                fids=['P1_16a', 'P1_16c'])
        if book_depr > 0.01 and p1_16a < 0.01:
            return self.format_issue(
                'IS-R04', self.INFO,
                f"✓ Form 1065 Page 1 Line 16a = $0 (correct — rental depreciation doesn't go here).\n"
                f"  • The books show ${book_depr:,.2f} of depreciation — verify it appears on Form 8825 Line 14.",
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
                "The books show $0 rental income and $0 expenses for the year.\n"
                "  • If the property was rented during 2025, income and expense transactions may be missing from the books.\n"
                "  • A blank Income Statement will produce a blank Form 8825 and empty Schedule K-1s.",
                'IRC §6031 — partnership must report all income/loss',
                "Verify Acct.Rev.Rent.* entries exist in llcExpRev for the tax year. "
                "Check llcAssets for the property's placed-in-service date.")
        if rent > 0.01 and depr < 0.01:
            return self.format_issue(
                'IS-R06', self.WARN,
                f"The books show rental income of ${rent:,.2f} but $0 depreciation.\n"
                f"  • A residential rental property should have a depreciation entry each year it is in service (27.5-year schedule).\n"
                f"  • Missing depreciation means partners are paying more taxes than required.",
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
                f"⚠ Form 1065 Line 23 (Ordinary Business Income) = ${l23:,.2f} — must be $0 for a rental LLC.\n"
                f"  • Rental income is PASSIVE — it flows to Schedule K Line 2, not to Page 1 Line 23.\n"
                f"  • A non-zero Line 23 means Page 1 income or expense lines were filled incorrectly.",
                'IRC §469(c)(2); Form 1065 Instructions Line 23',
                "Remove P1_23 mapping from BookToIRS Aid. Line 23 auto-derives "
                "from Line 8 − Line 22; both must be $0.",
                fids=['P1_23'],
                auto_fix=True)
        if l8 != 0 or l22 != 0:
            return self.format_issue(
                'IS-R08', self.WARN,
                f"Form 1065 Page 1 arithmetic doesn't add up: Line 8 (${l8:,.2f}) − Line 22 (${l22:,.2f}) ≠ Line 23 (${l23:,.2f}).\n"
                f"  • For a rental LLC, all three lines should be $0.",
                'Form 1065 Instructions Line 23',
                "Re-run pipeline; verify no expense or income mappings exist for "
                "Page 1 lines.",
                auto_fix=True)


# ────────────────────────────────────────────────────────────────────────────
#  AgentF1065_Other — Schedule B (Pages 2–3)
# ────────────────────────────────────────────────────────────────────────────

class AgentF1065_Other(_SectionAgent):
    """
    IRS Knowledge Base — Form 1065 Schedule B: Other Information (Pages 2–4)

    Golden Rule: for every Schedule B checkbox, the IRS condition that makes YES
    correct is stated below. If not confirmed from W&B Group's books/profile → NO.
    All Yes/No decisions are hard — no "unknown" or "CPA:pending" punts.

    fid → Schedule B checkbox map (from Form1065_namespace.json, pages 2–4):
      f81  = Q1 domestic LLC (c2_1[2], cv=/3)    → chk
      f87  = Q2a No  (c2_2 checkText, cv=/2)     → chk
      f88  = Q2b Yes (c2_3 checkBox,  cv=/1)     → chk when any individual >50%
      f91  = Q3a No  (c2_4 checkText, cv=/2)     → chk
      f113 = Q3b No  (c2_5 checkText, cv=/2)     → chk
      f140 = Q4 No   (c2_6 checkText, cv=/2)     → chk
      f142 = Q4a No  (c2_7 checkText, cv=/2)     → chk
      f144 = Q4b No  (c2_8 checkText, cv=/2)     → chk
      f145 = Q4c Yes (c2_9 checkBox,  cv=/1)     → chk when below threshold
      f149 = Q4d No  (c2_10 checkText, cv=/2)    → chk when no distributions
      f151 = Q5 No   (c2_11 checkText, cv=/2)    → chk
      f154 = Q6 No   (c2_12 checkText, cv=/2)    → chk
      f158 = Q7 No   (c2_13 checkText, cv=/2)    → chk
      f162 = Q8 No   (c3_1 checkText,  cv=/2)    → chk
      f165 = Q9 No   (c3_2 checkText,  cv=/2)    → chk
      f167 = Q10 No  (c3_3 checkText,  cv=/2)    → chk
      f170 = Q11 No  (c3_5 checkText,  cv=/2)    → chk
      f174 = Q12 No  (c3_6 checkText,  cv=/2)    → chk
      f177 = Q13 No  (c3_7 checkText,  cv=/2)    → chk
      f179 = Q14 No  (c3_8 checkText,  cv=/2)    → chk
      f183 = Q15 No  (c3_9 checkText,  cv=/2)    → chk
      f185 = Q16 No  (c3_10 checkText, cv=/2)    → chk
      f187 = Q17 No  (c3_11 checkText, cv=/2)    → chk
      f189 = Q18 No  (c3_12 checkText, cv=/2)    → chk
      f192 = Q19 No  (c3_13 checkText, cv=/2)    → chk
      f194 = Q20 No  (c3_14 checkText, cv=/2)    → chk
      f196 = Q21 No  (c3_15 checkText, cv=/2)    → chk
      f200 = Q22 No  (c3_16 checkText, cv=/2)    → chk
      f204 = Q23 No  (c4_1 checkText,  cv=/2)    → chk
      f206 = Q24 No  (c4_2 checkText,  cv=/2)    → chk (no interest on Line 5)
      f208 = Q26 No  (c4_3 checkText,  cv=/2)    → chk (no royalties)
      f210 = Q27 No  (c4_4 checkText,  cv=/2)    → chk
      f213 = Q28 No  (c4_6 checkText,  cv=/2)    → chk

    W&B Group definitive Yes/No decisions:
      Q1  = LLC (f81) — domestic LLC per IRC §7701(a)(2)
      Q2a = NO  (f87)  — all owners are individuals, no entity holds 50%+
      Q2b = YES (f88)  — Francis Rojas holds 96% > 50% threshold
      Q3a = NO  (f91)  — W&B holds only real property, no corp interest
      Q3b = NO  (f113) — W&B holds only real property, no other partnership
      Q4  = NO  (f140) — gross receipts < $50M; Schedule M-3 not required
      Q4a = NO  (f142) — 3 partners, not >100
      Q4b = NO  (f144) — no BBA opt-out election made (stay in §6221 audit regime)
      Q4c = YES (f145) — income $4,400 < $250K AND assets $226K < $1M (Treas. Reg. §1.6031(a)-1(b)(4))
      Q4d = NO  (f149) — $0 distributions in books (IS.distributions_cash = 0)
      Q5–Q7   = NO  — domestic LLC, no foreign ops, no foreign partners
      Q8  = NO  — private LLC, not a PTP (IRC §7704)
      Q9–Q22  = NO  — domestic LLC, no material advisor, not under audit, no
                       foreign partners, no PFIC, no Form 8886, no foreign loans,
                       no debt-financed acq., no oil/gas, no §721(c), no §267A
      Q23 = NO  — no CFC partner
      Q24 = NO  — no interest income reported on Form 1065 Line 5
      Q25 = text (3 — count of partners, not a checkbox)
      Q26 = NO  — no royalties paid
      Q27 = NO  — no foreign partner distributive share
      Q28 = NO  — no foreign corp acquisition

    Partnership Representative: Required post-2018 BBA. IRC §6223 + Treas. Reg.
        §301.6223-1. Francis X. Rojas is named PR.
    """

    LABEL             = 'Schedule B'
    AGENT_KEY         = 'AgentF1065_Other'
    LOGICAL_PREFIXES  = ['B_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_schedule_threshold,
            self._rule_pr_named,
            self._rule_sched_b_q1_entity_type,
            self._rule_sched_b_q2a_no_entity_owners,
            self._rule_sched_b_q2b_individual_majority,
            self._rule_sched_b_q3a_no_corp_ownership,
            self._rule_sched_b_q3b_no_partnership_ownership,
            self._rule_sched_b_q4c_schedules_not_required,
            self._rule_sched_b_q4d_distributions,
            self._rule_sched_b_no_foreign_activity,
            self._rule_sched_b_no_ptp,
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

    @staticmethod
    def _owner_pct(o: Dict) -> float:
        v = _safe_float(o.get('pct', o.get('ownership_pct', 0)))
        return v if v <= 1.5 else v / 100

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_schedule_threshold(self):
        gross  = abs(self._get_is_total('Income'))
        assets = self._get_bs_total_assets()
        required = gross >= 250_000 and assets >= 1_000_000
        if not required:
            return self.format_issue(
                'OT-R01', self.INFO,
                f"✓ Schedules L, M-1, and M-2 are NOT required for W&B Group.\n"
                f"  • The LLC is below both IRS thresholds: income ${gross:,.0f} (under $250K) and/or assets ${assets:,.0f} (under $1M).\n"
                f"  • Schedule B Question 4c should be answered 'Yes' to skip these schedules.",
                'Form 1065 Instructions, Schedule B Q4c; Treas. Reg. §1.6031(a)-1(b)(4)',
                "Q4c Yes (f145, c2_9 checkBox) must be in F1065.chk. f146 (No box) must not be.",
                auto_fix=True)

    def _rule_pr_named(self):
        first = self._fv('B_PRDI_FirstNm', '').strip()
        last  = self._fv('B_PRDI_Last', '').strip()
        if not first and not last:
            return self.format_issue(
                'OT-R02', self.ERROR,
                "⚠ Form 1065 Schedule B: the Partnership Representative is not named.\n"
                "  • The Partnership Representative is the person who deals with the IRS on behalf of the LLC (usually the managing member).\n"
                "  • This is required on every Form 1065 since the BBA audit rules took effect.",
                'IRC §6223; Treas. Reg. §301.6223-1',
                "Set F1065.B_PRDI_FirstNm and B_PRDI_Last in llcProfile, "
                "then use Aid to map Profile.F1065.B_PRDI_FirstNm → B_PR_1",
                fids=['B_PR_1', 'B_PR_2', 'B_PR_7'],
                suggested_mapping={'fid': 'B_PR_1', 'src': 'Profile',
                                   'path': 'Profile.F1065.B_PRDI_FirstNm'})

    def _rule_sched_b_q1_entity_type(self):
        """
        OT-R10: Q1 entity type must be 'c. Domestic limited liability company'.
        The chk list must contain f81 (c2_1[2]). Having f80 (limited partnership)
        or f79 (general partnership) is an IRS classification error — W&B Group
        is a domestic LLC taxed as a partnership per IRC §7701(a)(2).
        """
        f1065 = getattr(self.llc, 'F1065', {}) or {}
        chks  = list(f1065.get('chk', []))
        has_llc  = 81 in chks   # c2_1[2] = domestic LLC option
        has_lp   = 80 in chks   # c2_1[1] = limited partnership (wrong)
        has_gp   = 79 in chks   # c2_1[0] = general partnership (wrong)
        if has_lp or has_gp:
            wrong = 'limited partnership (f80)' if has_lp else 'general partnership (f79)'
            return self.format_issue(
                'OT-R10', self.ERROR,
                f"⚠ Form 1065 Question 1: entity type is marked as '{wrong.split(' (')[0]}' — this is incorrect.\n"
                f"  • W&B Group is a domestic LLC, not a {wrong.split(' (')[0]}.\n"
                f"  • The correct option is 'c. Domestic limited liability company'.",
                'IRC §7701(a)(2); Form 1065 Instructions Q1',
                "Remove 79/80 from F1065.chk in llcProfile; add 81 for the LLC option.")
        if not has_llc:
            return self.format_issue(
                'OT-R10', self.WARN,
                "Form 1065 Question 1: entity type (domestic LLC) is not confirmed in the form.\n"
                "  • W&B Group is a domestic limited liability company — this option needs to be checked.",
                'IRC §7701(a)(2); Form 1065 Instructions Q1',
                "Add 81 to F1065.chk to mark 'c. Domestic limited liability company'.")
        return self.format_issue(
            'OT-R10', self.INFO,
            "✓ Form 1065 Question 1: entity type = domestic LLC — correct for W&B Group.",
            'IRC §7701(a)(2); Form 1065 Instructions Q1', '')

    def _rule_sched_b_q2a_no_entity_owners(self):
        """
        OT-R11: Q2a — Did any foreign/domestic corporation, partnership,
        trust, or tax-exempt org own 50%+ of the partnership?
        Golden Rule: YES only if a non-individual entity holds 50%+.
        W&B Group owners are all individual humans → NO.
        fid f87 (c2_2 checkText, cv=/2) in chk sets the No checkbox.
        """
        owners = self._get_owners()
        entity_types = {'corp','corporation','trust','partnership','org','llc','entity'}
        entity_owners = [o for o in owners
                         if str(o.get('memType','')).lower() in entity_types
                         and self._owner_pct(o) >= 0.5]
        if entity_owners:
            names = ', '.join(str(o.get('nm','?')) for o in entity_owners)
            return self.format_issue(
                'OT-R11', self.ERROR,
                f"⚠ Form 1065 Schedule B Question 2a: an entity (not an individual) holds 50%+ of the LLC: {names}.\n"
                f"  • Question 2a must be answered YES — this triggers additional ownership disclosure requirements.",
                'Form 1065 Instructions, Schedule B Q2a; IRC §267(b)',
                "Replace f87 with f86 in F1065.chk (f86=Q2a Yes, cv=/1). "
                "File additional ownership disclosure if required.",
                fids=['f86'])
        return self.format_issue(
            'OT-R11', self.INFO,
            "✓ Form 1065 Question 2a: all W&B Group owners are individuals — NO (f87 in chk sets No checkbox).",
            'Form 1065 Instructions, Schedule B Q2a', '')

    def _rule_sched_b_q2b_individual_majority(self):
        """
        OT-R12: Q2b — Did any individual or estate own 50%+ of the partnership?
        Golden Rule: YES if any individual's ownership % > 50%; else NO.
        W&B Group: Francis Rojas owns 96% → YES.
        fid f88 (c2_3 checkBox, cv=/1) in chk sets the Yes checkbox.
        """
        owners = self._get_owners()
        majority = [o for o in owners if self._owner_pct(o) > 0.5]
        chks = list((getattr(self.llc, 'F1065', {}) or {}).get('chk', []))
        if majority:
            nm = ', '.join(str(o.get('nm', o.get('name', '?'))) for o in majority)
            pcts = ', '.join(f"{self._owner_pct(o)*100:.1f}%" for o in majority)
            has_yes = 88 in chks
            if not has_yes:
                return self.format_issue(
                    'OT-R12', self.ERROR,
                    f"⚠ Form 1065 Schedule B Question 2b: {nm} owns {pcts} — YES checkbox not set.\n"
                    f"  • f88 (Q2b Yes, c2_3 checkBox) must be in F1065.chk.",
                    'Form 1065 Instructions, Schedule B Q2b; IRC §267(b)',
                    "Add 88 to F1065.chk in llcProfile.",
                    fids=['f88'])
            return self.format_issue(
                'OT-R12', self.INFO,
                f"✓ Form 1065 Question 2b: {nm} owns {pcts} — YES (f88 in chk sets Yes checkbox).",
                'Form 1065 Instructions, Schedule B Q2b; IRC §267(b)', '')
        return self.format_issue(
            'OT-R12', self.INFO,
            "✓ Form 1065 Question 2b: no single individual owns more than 50% — NO (f89 should be in chk).",
            'Form 1065 Instructions, Schedule B Q2b', '')

    def _rule_sched_b_q3a_no_corp_ownership(self):
        """
        OT-R13: Q3a — Did the partnership own directly 20%+ of a corp?
        W&B Group holds only real property → NO.
        fid f91 (c2_4 checkText, cv=/2) in chk sets the No checkbox.
        """
        return self.format_issue(
            'OT-R13', self.INFO,
            "✓ Form 1065 Question 3a: W&B Group owns only real property, not shares in any company — NO (f91 in chk).",
            'Form 1065 Instructions, Schedule B Q3a; IRC §267(b)', '')

    def _rule_sched_b_q3b_no_partnership_ownership(self):
        """
        OT-R14: Q3b — Did the partnership own 50%+ of another partnership?
        W&B Group holds only real property → NO.
        fid f113 (c2_5 checkText, cv=/2) in chk sets the No checkbox.
        """
        return self.format_issue(
            'OT-R14', self.INFO,
            "✓ Form 1065 Question 3b: W&B Group owns only real property, not another partnership — NO (f113 in chk).",
            'Form 1065 Instructions, Schedule B Q3b; IRC §267(c)', '')

    def _rule_sched_b_q4c_schedules_not_required(self):
        """
        OT-R15: Q4c — Is the partnership not required to file Schedules L, M-1, M-2?
        Golden Rule: YES when gross receipts < $250K AND assets < $1M.
        fid f145 (c2_9 checkBox, cv=/1) in chk sets the Yes checkbox.
        """
        gross  = abs(self._get_is_total('Income'))
        assets = self._get_bs_total_assets()
        chks   = list((getattr(self.llc, 'F1065', {}) or {}).get('chk', []))
        if gross < 250_000 and assets < 1_000_000:
            has_yes = 145 in chks
            if not has_yes:
                return self.format_issue(
                    'OT-R15', self.ERROR,
                    f"⚠ Form 1065 Question 4c: below thresholds (income ${gross:,.0f} < $250K, assets ${assets:,.0f} < $1M) but YES checkbox not set.\n"
                    f"  • f145 (Q4c Yes, c2_9 checkBox) must be in F1065.chk.",
                    'Form 1065 Instructions, Schedule B Q4c; Treas. Reg. §1.6031(a)-1(b)(4)',
                    "Add 145 to F1065.chk in llcProfile.",
                    auto_fix=True)
            return self.format_issue(
                'OT-R15', self.INFO,
                f"✓ Form 1065 Question 4c: below thresholds (income ${gross:,.0f}, assets ${assets:,.0f}) — YES (f145 in chk). Schedules L/M-1/M-2 NOT required.",
                'Form 1065 Instructions, Schedule B Q4c; Treas. Reg. §1.6031(a)-1(b)(4)', '')
        return self.format_issue(
            'OT-R15', self.INFO,
            f"Form 1065 Question 4c: above threshold (income ${gross:,.0f}, assets ${assets:,.0f}) — Schedules L/M-1/M-2 ARE required.",
            'Form 1065 Instructions, Schedule B Q4c', '')

    def _rule_sched_b_q4d_distributions(self):
        """
        OT-R16: Q4d — Did the partnership distribute money or property to any partner?
        Golden Rule: YES if any distribution appears in llcOwners or books.
        fid f148 (c2_10 checkBox, cv=/1) = Yes; f149 (c2_10 checkText, cv=/2) = No.
        """
        owners = self._get_owners()
        has_distrib = any(_safe_float(o.get('distributions',
                         o.get('distrib', o.get('cash_out', 0)))) > 0 for o in owners)
        if has_distrib:
            return self.format_issue(
                'OT-R16', self.WARN,
                "Form 1065 Question 4d: cash distributions to partners are recorded in the books.\n"
                "  • Question 4d must be answered YES — replace f149 with f148 in F1065.chk.",
                'Form 1065 Instructions, Schedule B Q4d; K-1 Box 19',
                "Remove 149 from F1065.chk; add 148 (Q4d Yes, c2_10 checkBox).",
                fids=['f148'])
        return self.format_issue(
            'OT-R16', self.INFO,
            "✓ Form 1065 Question 4d: no distributions in books — NO (f149 in chk sets No checkbox).",
            'Form 1065 Instructions, Schedule B Q4d', '')

    def _rule_sched_b_no_foreign_activity(self):
        """
        OT-R17: Q5–Q7, Q9–Q28 (foreign / complex activity questions).
        Golden Rule: ALL are NO for W&B Group — domestic LLC, U.S. partners,
        U.S. real property only. No-box fids f151, f154, f158, f165–f213 in chk.
        """
        return self.format_issue(
            'OT-R17', self.INFO,
            "✓ Form 1065 Q5–Q28 (foreign activity, complex transactions): all NO for W&B Group.\n"
            "  • Domestic LLC, U.S. partners, U.S. real property — none of these foreign/complex questions apply.\n"
            "  • No-box fids are in F1065.chk (f151, f154, f158, f162, f165, f167, f170, f174, f177, f179, f183, f185, f187, f189, f192, f194, f196, f200, f204, f206, f208, f210, f213).\n"
            "  • Confirm no unusual transactions occurred in 2025.",
            'Form 1065 Instructions, Schedule B Q5–Q28',
            "If any of these conditions applied in 2025, contact CPA before filing.")

    def _rule_sched_b_no_ptp(self):
        """
        OT-R18: Q8 — Is the partnership a publicly traded partnership (PTP)?
        W&B Group is private → NO. fid f162 (c3_1 checkText, cv=/2) in chk.
        """
        return self.format_issue(
            'OT-R18', self.INFO,
            "✓ Form 1065 Question 8 (PTP): W&B Group is a private LLC — NO (f162 in chk).",
            'IRC §7704; Form 1065 Instructions, Schedule B Q8', '')


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

    Line 2 (Net Rental Real Estate Income/Loss): The ONLY active income line.
      IRS Instructions: "Enter the net income or loss from rental real estate
      activities of the partnership. Use the amounts from Form 8825, Line 21."
      Books-First: Schedule K Line 2 = IS.net_rental (total_income − total_expenses).
      It is NET, not gross. IS.rent_income (gross) ≠ Schedule K Line 2.

    Lines 3–11 (other income/loss items): Must ALL be blank for W&B Group.
      These lines cover income types the LLC does not have:
        Line 3  — net rental income from non-real-estate (equipment, IP)
        Line 4  — net rental income from other activities
        Line 5a — interest income (portfolio)
        Line 5b — ordinary dividends
        Line 5c — qualified dividends
        Line 5d — dividend equivalents
        Line 5e — royalties
        Line 5f — net short-term capital gain/loss
        Line 8  — net long-term capital gain/loss
        Line 9a — collectibles gain/loss
        Line 9b — unrecaptured §1250 gain
        Line 10 — net §1231 gain/loss
        Line 11 — other income (loss)
      Filing a non-zero value here would misrepresent the LLC's income
      character and create a mismatch with partner K-1 reporting.

    Lines 12–13 (deductions): Must be $0 — rental deductions go on Form 8825.

    Line 14 (Self-Employment Income): Must be $0.
      IRC §1402(a)(13): limited partners are not subject to SE tax.
      IRC §1402(a)(1): rental income is not net SE earnings by statute.

    Lines 15–16 (credits/AMT): Must be blank.
      Line 16d (AMT gross income/gain): partnerships do NOT file corporate AMT
      (IRC §55 applies to C-corps and individuals, not pass-through entities).
      Each partner computes their own AMT adjustment on Form 6251 — it is NOT
      reported on the partnership's Schedule K.

    IRC §704(b) allocation: All Schedule K totals must sum to 100% across
      all K-1s. The allocation mechanism must match the LLC's operating agreement.

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
            self._rule_k3_11_must_be_blank,
            self._rule_partner_alloc_100,
            self._rule_no_se_income,
            self._rule_k19a_cash_distributions,
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
                f"⚠ Schedule K Line 1 (Ordinary Business Income) = ${k1:,.2f} — must be $0 for a rental LLC.\n"
                f"  • Rental income is passive — it belongs on Schedule K Line 2, not Line 1.\n"
                f"  • A non-zero Line 1 means Form 1065 Page 1 was filled incorrectly.",
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
                f"⚠ Schedule K Line 2 (Net Rental Income) is blank, but the books show net rental {'income' if net_rental >= 0 else 'loss'} of ${net_rental:,.2f}.\n"
                f"  • A blank Line 2 means the rental income/loss is NOT flowing to the partners' K-1s.\n"
                f"  • This is the most important line on Schedule K for a rental LLC.",
                'Form 1065 Instructions Schedule K Line 2; IRC §702(a)',
                "Map IS.net_rental → K_2 in bookNS_IS.json; re-run BookToIRS pipeline.",
                fids=['K_2'])

        if abs(k2_filed - net_rental) > 1.00:
            return self.format_issue(
                'KD-R03', self.WARN,
                f"Schedule K Line 2 = ${k2_filed:,.2f} but the books show net rental income/loss = ${net_rental:,.2f}.\n"
                f"  • These must match — the form value must come directly from the books (discrepancy: ${abs(k2_filed - net_rental):,.2f}).",
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
                f"⚠ Schedule K Line 2 = ${k2_filed:,.2f} — this looks like GROSS rent, not NET rental income.\n"
                f"  • Gross rent (before expenses): ${gross_rent:,.2f}. Net rental income (after expenses): ${net_rental:,.2f}.\n"
                f"  • The IRS requires the NET amount on Line 2. Using gross rent overstates income by ${abs(gross_rent - net_rental):,.2f} and omits partner deductions.",
                'Form 1065 Instructions Schedule K Line 2; IRC §702(a)',
                "Change bookNS_IS.json K_2 mapping from IS.rent_income → IS.net_rental. "
                "Re-run BookToIRS pipeline.",
                fids=['K_2'])

    def _rule_k3_11_must_be_blank(self):
        """
        IRS Rule: Schedule K Lines 3–11 and Line 16d must be blank for W&B Group.
        W&B Group is a pure rental real estate LLC — it has no portfolio income,
        capital gains, royalties, non-real-estate rentals, or other separately
        stated items.  Filing a value on Lines 3–11 would misrepresent income
        character and create K-1 mismatch issues.
        Line 16d (AMT): partnerships do not file corporate AMT (IRC §55 applies
        to C-corps and individuals). Partner AMT adjustments are computed on each
        partner's Form 6251 — not on the partnership return.
        IRS fid mapping: F247 = Sch K Line 7 (other income); F248 = Sch K Line 16d.
        Both must be blank.
        """
        fill = self._load_fill_dict()
        # fids for Schedule K Lines 3–11 and 16d known from 2025 namespace
        blank_checks = {
            'F247': 'Schedule K Line 7 (Other income/loss)',
            'F248': 'Schedule K Line 16d (AMT gross income/gain)',
        }
        violations = []
        fids_hit = []
        for fid, label in blank_checks.items():
            val = _safe_float(fill.get(fid))
            if abs(val) > 0.01:
                violations.append(f"  • {label} = ${val:,.2f} — must be blank for a rental-only LLC.")
                fids_hit.append(fid)
        if violations:
            return self.format_issue(
                'KD-R07', self.ERROR,
                "⚠ Schedule K Lines 3–11 / 16d contain non-zero values — these must be blank for W&B Group.\n"
                + "\n".join(violations)
                + "\n  • W&B Group has no portfolio income, capital gains, royalties, non-real-estate rentals, or AMT items.\n"
                + "  • Remove the bookNS mappings for F247 and F248 (already removed in bookNS_IS.json 2026-06-30).\n"
                + "  • If the FILL.pdf still shows these values, re-run REGENERATE to pick up the corrected bookNS.",
                'Form 1065 Instructions Schedule K Lines 3–11; IRC §702(a); IRC §55 (AMT)',
                "Verify F247 and F248 are absent from bookNS_IS.json Form1065 section. Re-run REGENERATE.",
                fids=fids_hit)
        return self.format_issue(
            'KD-R07', self.INFO,
            "✓ Schedule K Lines 3–11 and Line 16d are blank — correct for a rental-only LLC with no portfolio income.",
            'Form 1065 Instructions Schedule K Lines 3–11',
            None, fids=list(blank_checks.keys()))

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
                f"⚠ Partner ownership percentages add up to {pct_str} — they must total exactly 100%.\n"
                f"  • Until this is fixed, the K-1 income/loss allocations will be wrong for every partner.",
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
                f"⚠ Schedule K Line 14 (Self-Employment Income) = ${k14:,.2f} — must be $0 for a rental LLC.\n"
                f"  • Rental income is not subject to self-employment tax for any partner.\n"
                f"  • A non-zero Line 14 would incorrectly add ~15.3% SE tax to every partner's return.",
                'IRC §1402(a)(1); IRC §1402(a)(13); Pub 541 (Partnerships)',
                "Remove any mapping to K_14; verify it is blank in the fill dict.",
                fids=['K_14', 'K_14a'])

    def _rule_k19a_cash_distributions(self):
        """
        IRS Rule: Schedule K Line 19a = total cash the LLC actually paid out
        to ALL partners during the year.

        This is NOT the same as allocated income (Schedule K Line 2).
        Distinction:
          - Line 2  (net rental income): paper profit — taxed on partners'
            returns whether or not cash was paid out (IRC §702(a)).
          - Line 19a (cash distributions): actual money transferred to
            partners — generally NOT taxable if ≤ outside basis (IRC §731).

        Source per Books-First (IRC §446): GL Capital.Dist credits and
        Capital.Funds debits tagged to specific partners.  NOT the IS
        "member distribution" row — that row is allocated income, not cash out.

        The filed value flows to each partner's K-1 Box 19a.
        """
        fill      = self._load_fill_dict()
        k19a_filed = _safe_float(fill.get('K_19a'))

        # Compute GL-sourced total distributions across all partners.
        try:
            from irs.taxAgents.FormSchK1Agent import gl_distributions
            owners      = self._get_owners()
            gl_total    = round(sum(gl_distributions(self.llc, o.get('oID', ''))
                                    for o in owners), 2)
        except Exception:
            gl_total = None

        net_rental = self._get_is_agg('net_rental')

        if gl_total is not None and abs(k19a_filed - gl_total) > 1.00:
            if gl_total == 0 and k19a_filed > 0:
                return self.format_issue(
                    'KD-R04', self.WARN,
                    f"Schedule K Line 19a (Cash Distributions) = ${k19a_filed:,.2f} but the books show $0.\n"
                    f"  • Line 19a must equal actual cash sent to partners — money that physically left the LLC bank account.\n"
                    f"  • The IS 'Member distribution' row (${net_rental:,.2f}) is allocated income, not cash out — wrong source for this line.\n"
                    f"  • Books show no Capital.Dist entries. If no cash was distributed, Line 19a must be blank.\n"
                    f"  • The ${k19a_filed:,.2f} appears to be a stale value — not traceable to current books.",
                    'IRC §731; Form 1065 Instructions Schedule K Line 19a',
                    "If no cash was distributed to any partner: remove F279 mapping from bookNS and re-run. "
                    "If cash WAS distributed, add Capital.Dist GL entries tagged to each partner and re-run.",
                    fids=['K_19a'])
            return self.format_issue(
                'KD-R04', self.WARN,
                f"Schedule K Line 19a (Cash Distributions) = ${k19a_filed:,.2f} but GL shows ${gl_total:,.2f}.\n"
                f"  • Line 19a = actual cash sent to partners (bank transfers), not paper income allocation.\n"
                f"  • Difference: ${abs(k19a_filed - gl_total):,.2f} — verify Capital.Dist GL entries match the filed amount.",
                'IRC §731; Form 1065 Instructions Schedule K Line 19a',
                "Re-run after verifying Capital.Dist GL entries match the total cash distributed. "
                "If no cash was distributed, leave Line 19a blank.",
                fids=['K_19a'])

        if k19a_filed > 0 and abs(k19a_filed - net_rental) < 1.00:
            return self.format_issue(
                'KD-R04', self.ERROR,
                f"⚠ Schedule K Line 19a = ${k19a_filed:,.2f} — this matches Line 2 net rental income, which is wrong.\n"
                f"  • Line 19a must be actual cash distributed, not the income allocation.\n"
                f"  • Filing income as a distribution would misrepresent partner basis (IRC §705) and overstate distributions.",
                'IRC §731; IRC §705; Form 1065 Instructions Schedule K Line 19a',
                "Clear Line 19a (remove F279 mapping). If cash was distributed, enter the GL-sourced amount.",
                fids=['K_19a'])

        if k19a_filed == 0 and gl_total is not None and gl_total > 0:
            return self.format_issue(
                'KD-R04', self.WARN,
                f"Schedule K Line 19a (Cash Distributions) is blank but GL shows ${gl_total:,.2f} distributed.\n"
                f"  • Each partner must receive their share on K-1 Box 19a to track outside basis correctly.",
                'IRC §731; Form 1065 Instructions Schedule K Line 19a',
                "Map GL total distributions → K_19a in bookNS and re-run.",
                fids=['K_19a'])

        # Clean — either both $0 or filed matches GL within $1.
        if k19a_filed == 0:
            return self.format_issue(
                'KD-R04', self.INFO,
                f"✓ Schedule K Line 19a (Cash Distributions) is blank — consistent with GL showing no cash distributions.\n"
                f"  • If any cash was paid out to partners during 2025, it must be recorded here and on each K-1 Box 19a.",
                'Form 1065 Instructions Schedule K Line 19a; IRC §731',
                None, fids=['K_19a'])
        return self.format_issue(
            'KD-R04', self.INFO,
            f"✓ Schedule K Line 19a (Cash Distributions) = ${k19a_filed:,.2f} — matches GL-sourced total.",
            'Form 1065 Instructions Schedule K Line 19a; IRC §731',
            None, fids=['K_19a'])


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
                f"✓ Schedules L, M-1, and M-2 are NOT required (income ${gross:,.0f} and/or assets ${assets:,.0f} are below IRS thresholds).\n"
                f"  • Schedule B Question 4(c) should be answered 'Yes' — leave these schedule pages blank.",
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
                f"⚠ Schedule L (Balance Sheet): Line 14 shows ${l14_end:,.2f} total assets, but the books show ${bs_assets:,.2f}.\n"
                f"  • The IRS balance sheet must match the actual books exactly — a ${abs(l14_end - bs_assets):,.2f} gap is an audit red flag.",
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
                f"Schedule M-1 Line 1 (net income per books) = ${m1_line1:,.2f}, but the books show ${book_ni:,.2f}.\n"
                f"  • Line 1 is the starting point of the book-to-tax reconciliation — if it doesn't match the books, the entire M-1 is wrong.",
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
                f"⚠ Schedule M-1 Line 9 (income per return) = ${m1_l9:,.2f} — must be $0 for a rental LLC.\n"
                f"  • Line 9 represents ordinary business income, which is $0 for W&B (all income is passive rental, not ordinary).\n"
                f"  • This means IS.net_income was incorrectly mapped to this line.",
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
            "Schedule M-2 (capital account analysis) must use the 'Tax Basis' method — required by the IRS since 2020.\n"
            "  • Tax basis = what each partner actually contributed + income allocated − deductions − cash received.\n"
            "  • This is different from 'book value' or 'GAAP' — those methods are no longer accepted.\n"
            "  • K-1 Box L must use the same tax basis method.",
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
                f"Form 8825 is required: {len(props)} active rental propert{'y' if len(props)==1 else 'ies'} ({', '.join(props)}) must be reported on Form 8825 (rental income/expense detail).",
                'Form 8825 Instructions',
                "Prepare Form 8825 via Form8825Agent (future) or manually"))
        if has_dep:
            issues.append(self.format_issue(
                'EX-R07', self.INFO,
                "Form 4562 is required: depreciation entries are recorded in the books.",
                'Form 4562 Instructions; IRC §168',
                "Prepare Form 4562 via Form4562Agent (future) or manually"))
        if k1_cnt:
            issues.append(self.format_issue(
                'EX-R01', self.INFO,
                f"{k1_cnt} Schedule K-1{'s' if k1_cnt > 1 else ''} {'are' if k1_cnt > 1 else 'is'} required — one for each partner.",
                'Form 1065 Instructions, §563',
                f"Prepare {k1_cnt} K-1s via SchK1Agent (future) or manually"))
        for uc in inv['under_construction']:
            issues.append(self.format_issue(
                'EX-R06', self.INFO,
                f"{uc} is under construction — not yet reported on Form 8825 (property must be placed in service first).",
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
                    'issues':        s.get('issues', []),
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
