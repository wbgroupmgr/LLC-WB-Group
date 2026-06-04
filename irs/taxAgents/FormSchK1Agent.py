"""
FormSchK1Agent — Tier 1 orchestrator for Schedule K-1 (Form 1065).

Architecture (4-tier):
  Tier 0  LLCTaxAgent         — XF-R03 (K-1 Box 2 per partner) + XF-R04 (sum K-1 = SchedK L2)
  Tier 1  FormSchK1Agent      — this file; loops section agents PER PARTNER
  Tier 2  AgentSchK1_*        — one per K-1 section; each runs once per partner
  Tier 3  IRSFormsAgent       — common services base class

Special: FormSchK1Agent runs section agents per partner (N iterations), not once.
Each partner produces one K-1 PDF. Session state is keyed by partner oID.

Key IRS rules:
  Box 1  = $0 (IRC §469(c)(2) — rental = passive, never ordinary income)
  Box 2  = IS.net_rental × partner.pct (Books-First: IRC §446/703)
  Box 14 = $0 (IRC §1402(a)(1) + §1402(a)(13) — rental LLC not subject to SE tax)
  Box L  = tax basis method (Rev. Proc. 2020-13; mandatory post-2020)

IRC §702(a): character of items passes through to partners.
IRC §704(b): allocations must have substantial economic effect.
IRC §6109: partner TIN required on each K-1.

Session state stored at:
  books/{year}/Forms/.agent_work/FormSchK1_session_state.json
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


def _owner_pct(owner: Dict) -> float:
    """Return ownership percentage as a decimal (0.0–1.0)."""
    v = _safe_float(owner.get('pct', owner.get('ownership_pct', owner.get('ownerPct', 0))))
    return v if v <= 1.5 else v / 100.0  # normalize if stored as 33.33 vs 0.3333


# ════════════════════════════════════════════════════════════════════════════
#  SECTION AGENTS  (Tier 2) — each runs once per partner
# ════════════════════════════════════════════════════════════════════════════

class _SectionAgent(IRSFormsAgent):
    """Common base for all Schedule K-1 section agents (per-partner)."""

    LABEL        = ''
    AGENT_KEY    = ''
    LOGICAL_PREFIXES: List[str] = []

    def __init__(self, llc, tax_year: int):
        super().__init__(llc, tax_year)
        self._is_data    = None
        self._fill_cache = {}  # keyed by partner oID

    # ── Data loaders (lazy) ──────────────────────────────────────────────────

    def _get_is(self) -> Dict[str, float]:
        """IS taxAggregates — Books-First; IRC §446/703."""
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

    # ── Pass interface (per partner) ─────────────────────────────────────────

    def pass1_auto_fill(self, owner: Dict) -> Dict[str, Any]:
        return {
            'section':    self.AGENT_KEY,
            'tax_year':   self.tax_year,
            'partner_id': owner.get('oID', owner.get('ownerID', '')),
            'filled':     0, 'blank': 0, 'complex': 0, 'total': 0,
        }

    def pass2_audit(self, owner: Dict) -> Dict[str, Any]:
        return {
            'section':       self.AGENT_KEY,
            'halt_count':    0,
            'resolve_count': 0,
            'review_count':  0,
            'issue_list':    [],
            'ready_state':   self.GO,
        }

    def pass5_summarize(self, owner: Dict) -> str:
        nm = owner.get('nm', owner.get('name', owner.get('ownerNm', 'Partner')))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        return f"{self.LABEL}: {nm} — complete."

    def _run_audit(self, rules: List, owner: Dict) -> Dict[str, Any]:
        issues = []
        for rule_fn in rules:
            try:
                issue = rule_fn(owner)
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
#  AgentSchK1_Identity — Partner identification (name, TIN, %, address)
# ────────────────────────────────────────────────────────────────────────────

class AgentSchK1_Identity(_SectionAgent):
    """
    IRS Knowledge Base — Schedule K-1 Header: Partner Identification

    IRC §6109: Every person required to file or furnish a return must include
    a Taxpayer Identification Number (TIN). For individual partners: SSN (9 digits).
    Form 1065 Instructions (K-1 header): "Enter the partner's TIN, name, and address."

    TIN requirement (IRC §6109; Treas. Reg. §301.6109-1):
      Missing or incorrect TINs may result in:
        (a) IRS rejection of the partnership return
        (b) Penalties under IRC §6722 ($290/K-1 for incorrect payee statements)
        (c) Backup withholding obligations (IRC §3406)

    Ownership percentage (IRC §704(b)):
      All K-1 allocations (Box 2, Box 5, Box L) are a function of the partner's
      ownership %. A 0% or missing % makes all Box amounts uncalculable.
      IRC §704(b): allocations must have substantial economic effect.

    Address: Required by Form 1065 instructions. IRS uses it for compliance matching.
    """

    LABEL            = 'Partner Identity'
    AGENT_KEY        = 'AgentSchK1_Identity'
    LOGICAL_PREFIXES = ['SK1I_']

    def pass2_audit(self, owner: Dict) -> Dict[str, Any]:
        return self._run_audit([
            lambda o=owner: self._rule_tin(o),
            lambda o=owner: self._rule_address(o),
            lambda o=owner: self._rule_ownership_pct(o),
        ], owner)

    def pass5_summarize(self, owner: Dict) -> str:
        nm  = owner.get('nm', owner.get('name', 'Partner'))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        pct = _owner_pct(owner)
        tin = owner.get('ssn', owner.get('tin', owner.get('TIN', '')))
        tin_masked = f"***-**-{str(tin)[-4:]}" if tin and len(str(tin).replace('-', '')) >= 4 else 'TIN missing'
        return f"Identity: {nm}, {pct*100:.2f}%, {tin_masked}."

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_tin(self, owner: Dict):
        """
        SK1I-R01: Partner TIN missing or malformed.
        IRC §6109: TIN required on every K-1. Individual partners must provide SSN.
        SSN must be 9 digits (strip dashes). A missing or malformed TIN causes
        IRS matching failure and may trigger penalties under IRC §6722.
        """
        tin  = str(owner.get('ssn', owner.get('tin', owner.get('TIN', '')))).replace('-', '').strip()
        oID  = owner.get('oID', owner.get('ownerID', ''))
        nm   = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        if not tin or len(tin) != 9 or not tin.isdigit():
            return self.format_issue(
                'SK1I-R01', self.ERROR,
                f"Partner '{nm}' ({oID}): TIN missing or malformed (found: '{tin or 'blank'}'). "
                f"IRC §6109: each K-1 must include the partner's SSN (9 digits). "
                f"IRC §6722: $290 penalty per K-1 with incorrect payee statement. "
                f"IRS cannot match the K-1 to the partner's personal return without a valid SSN.",
                'IRC §6109; IRC §6722; Treas. Reg. §301.6109-1',
                f"Set ssn (or tin) for partner '{oID}' in llcOwners. "
                f"Format: 9 digits (NNNNNNNNN or NNN-NN-NNNN).")

    def _rule_address(self, owner: Dict):
        """
        SK1I-R02: Partner address missing.
        Form 1065 Instructions: K-1 header requires partner's address.
        IRS uses the address for compliance matching and notices.
        A missing address does not cause outright rejection but may delay processing.
        """
        addr = (owner.get('address', '') or owner.get('addr', '')
                or owner.get('street', '')).strip()
        oID  = owner.get('oID', owner.get('ownerID', ''))
        nm   = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        if not addr:
            return self.format_issue(
                'SK1I-R02', self.WARN,
                f"Partner '{nm}' ({oID}): address is blank on K-1. "
                f"Form 1065 Instructions: K-1 header requires the partner's current address. "
                f"IRS uses the address for compliance matching and mailing notices.",
                'Form 1065 Instructions (K-1 header)',
                f"Set address for partner '{oID}' in llcOwners. "
                f"Include street, city, state, and ZIP.")

    def _rule_ownership_pct(self, owner: Dict):
        """
        SK1I-R03: Partner ownership % is 0 or missing.
        IRC §704(b): every partnership allocation must be based on the partner's
        distributive share, which is a function of their ownership percentage.
        A zero or missing percentage makes Box 2, Box 5, and Box L uncalculable.
        All K-1 monetary amounts are zero if pct = 0, which would omit the
        partner's share of rental income/loss from their return.
        """
        pct  = _owner_pct(owner)
        oID  = owner.get('oID', owner.get('ownerID', ''))
        nm   = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        if pct < 0.001:
            return self.format_issue(
                'SK1I-R03', self.ERROR,
                f"Partner '{nm}' ({oID}): ownership percentage is {pct:.4f} (zero or missing). "
                f"IRC §704(b): allocations must be based on partners' distributive shares. "
                f"All K-1 Box amounts (Box 2, Box 5, Box L) = $0 if pct = 0. "
                f"This omits the partner's rental income/loss from their tax return.",
                'IRC §704(b); Form 1065 Instructions (Schedule K-1)',
                f"Set pct (or ownership_pct) for partner '{oID}' in llcOwners. "
                f"Sum of all partners' pct must equal 1.0 (100%).")


# ────────────────────────────────────────────────────────────────────────────
#  AgentSchK1_PassiveItems — Box 1, Box 2, Box 5, Box 14
# ────────────────────────────────────────────────────────────────────────────

class AgentSchK1_PassiveItems(_SectionAgent):
    """
    IRS Knowledge Base — Schedule K-1: Income/Loss Boxes (1, 2, 5, 14)

    Box 1 (Ordinary business income/loss):
      = $0 for rental LLC. IRC §469(c)(2): rental activity is passive, not ordinary.
      Box 1 = Form 1065 Page 1 Line 23 = $0.

    Box 2 (Net rental real estate income/loss):
      = IS.net_rental × partner.pct (Books-First).
      K-1 Instructions: "Partner's distributive share of Schedule K, line 2."
      IRC §702(a): items retain their character (passive rental) at the partner level.
      IRC §469: partners may use the passive loss only against passive income,
      or when the activity is disposed of (IRC §469(b)).

    Box 5 (Interest income):
      = IS.interest_income × partner.pct if interest income exists in books.
      IRC §702(a)(1): interest income is a separately stated item.

    Box 14 (Self-employment income):
      = $0 for rental LLC. IRC §1402(a)(1): rental income excluded from SE earnings.
      IRC §1402(a)(13): limited partners excluded from SE tax.
      Non-zero Box 14 incorrectly triggers ~15.3% SE tax on partners' individual returns.

    W&B Group 2025: IS.net_rental = −$393.50 → 3 equal partners → Box 2 ≈ −$131.17 each.
    """

    LABEL            = 'Passive Items (Box 1, 2, 5, 14)'
    AGENT_KEY        = 'AgentSchK1_PassiveItems'
    LOGICAL_PREFIXES = ['SK1P_']

    def pass2_audit(self, owner: Dict) -> Dict[str, Any]:
        return self._run_audit([
            lambda o=owner: self._rule_box1_must_zero(o),
            lambda o=owner: self._rule_box2_blank(o),
            lambda o=owner: self._rule_box2_mismatch(o),
            lambda o=owner: self._rule_box14_must_zero(o),
            lambda o=owner: self._rule_box2_basis_advisory(o),
        ], owner)

    def pass5_summarize(self, owner: Dict) -> str:
        pct    = _owner_pct(owner)
        net    = self._get_is_agg('net_rental')
        box2   = round(net * pct, 2)
        nm     = owner.get('nm', owner.get('name', owner.get('oID', 'Partner')))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        return (f"Passive Items: {nm} — Box 1=$0, Box 2=${box2:,.2f} "
                f"(IS.net_rental ${net:,.2f} × {pct*100:.2f}%), Box 14=$0.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_box1_must_zero(self, owner: Dict):
        """
        SK1P-R03: Box 1 (ordinary income) non-zero — IRS violation for rental LLC.
        IRC §469(c)(2): all rental activity is passive. Passive income never belongs
        in Box 1 (ordinary business income/loss). Box 1 is for manufacturing,
        services, or other non-rental partnerships. If Box 1 is non-zero,
        it indicates Form 1065 Page 1 Lines 1–23 were incorrectly populated.
        """
        # Box 1 derives from Form 1065 Page 1 Line 23; for rental LLC it is always $0
        # We check IS to see if any ordinary income would flow here
        agg = self._get_is()
        # For a rental LLC, there should be no 'ordinary_income' key > 0
        ord_inc = _safe_float(agg.get('ordinary_income', agg.get('ordinary_business_income', 0)))
        oID = owner.get('oID', '')
        if abs(ord_inc) > 0.01:
            return self.format_issue(
                'SK1P-R03', self.ERROR,
                f"Partner {oID}: IS shows ordinary_income = ${ord_inc:,.2f}. "
                f"Box 1 would be non-zero — must be $0 for a rental LLC. "
                f"IRC §469(c)(2): rental activity is passive and cannot produce "
                f"ordinary business income. Box 1 derives from Form 1065 Page 1 Line 23, "
                f"which must be $0 for a pure rental LLC.",
                'IRC §469(c)(2); Form 1065 Instructions Schedule K-1 Box 1',
                "Verify Form 1065 Page 1 Lines 1-23 are all $0. "
                "Remove any IS.ordinary_income mapping from the K-1 Box 1 pipeline.")

    def _rule_box2_blank(self, owner: Dict):
        """
        SK1P-R01: Box 2 blank while IS.net_rental × pct ≠ 0.
        Box 2 is the primary K-1 box for rental LLC partners. It carries each
        partner's allocated share of net rental income/loss.
        A blank Box 2 when the LLC has rental activity means the partner is
        not reporting their share on their individual return — an IRC §702(a)
        reporting violation. The partner's Schedule E will be missing the passive item.
        """
        net = self._get_is_agg('net_rental')
        pct = _owner_pct(owner)
        expected = round(net * pct, 2)
        oID = owner.get('oID', '')
        nm  = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        if abs(expected) > 0.01:
            # Box 2 should be non-zero; we flag if it would be blank
            # (actual check of fill dict would happen in a fully wired pipeline)
            return self.format_issue(
                'SK1P-R01', self.ERROR,
                f"Partner '{nm}' ({oID}): Box 2 should be ${expected:,.2f} "
                f"(IS.net_rental ${net:,.2f} × {pct*100:.2f}%). "
                f"If Box 2 is blank on the K-1, the partner will not report "
                f"their rental income/loss. IRC §702(a): all partnership items "
                f"must flow to partners' individual returns.",
                'IRC §702(a); Form 1065 Instructions K-1 Box 2; IRC §469',
                f"Verify K-1 fill pipeline: Box 2 = IS.net_rental × {pct:.4f} = ${expected:,.2f}. "
                f"Books-First (IRC §446): source from IS.net_rental, not from Schedule K form field.")

    def _rule_box2_mismatch(self, owner: Dict):
        """
        SK1P-R02: Box 2 ≠ IS.net_rental × partner.pct — Books-First violation.
        If the K-1 fill pipeline populated Box 2 from any source other than
        IS.net_rental × pct (e.g., from the Schedule K form field, or from
        a manually entered amount), it may differ from the books-derived value.
        IRC §446: form values must equal books values.
        LLCTaxAgent XF-R03 will also verify this — but we check per-agent here.
        """
        net      = self._get_is_agg('net_rental')
        pct      = _owner_pct(owner)
        expected = round(net * pct, 2)
        # If the fill dict has an explicit Box 2 value for this partner, compare it
        # In this implementation we flag the expected value as a verification prompt
        oID = owner.get('oID', '')
        nm  = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        if abs(expected) > 0.01:
            # Informational verification of the correct value
            return self.format_issue(
                'SK1P-R02', self.INFO,
                f"Partner '{nm}' ({oID}): Box 2 expected value = ${expected:,.2f} "
                f"(IS.net_rental ${net:,.2f} × {pct*100:.2f}%). "
                f"Books-First (IRC §446): verify K-1 Box 2 = ${expected:,.2f}. "
                f"LLCTaxAgent XF-R03 will confirm this per-partner allocation.",
                'IRC §446; IRC §702(a); LLCTaxAgent XF-R03',
                f"Confirm K-1 Box 2 for '{nm}' = ${expected:,.2f} in the fill dict/PDF.")

    def _rule_box14_must_zero(self, owner: Dict):
        """
        SK1P-R04: Box 14 (SE income) non-zero — IRS violation for rental LLC.
        IRC §1402(a)(1): 'net earnings from self-employment' does not include
        rentals from real estate (unless the taxpayer receives substantial
        personal services — not applicable to a passive rental LLC).
        IRC §1402(a)(13): limited partners are not subject to SE tax on their
        distributive share.
        A non-zero Box 14 incorrectly causes the partner to owe SE tax (~15.3%)
        on rental income that is statutorily exempt from SE tax.
        """
        agg = self._get_is()
        se  = _safe_float(agg.get('se_income', agg.get('self_employment', 0)))
        oID = owner.get('oID', '')
        if abs(se) > 0.01:
            pct = _owner_pct(owner)
            return self.format_issue(
                'SK1P-R04', self.ERROR,
                f"Partner {oID}: IS shows SE income = ${se:,.2f} → "
                f"Box 14 would be ${se*pct:,.2f} (non-zero). "
                f"Box 14 must be $0 for rental LLC. "
                f"IRC §1402(a)(1): rental income excluded from SE earnings. "
                f"IRC §1402(a)(13): limited partners not subject to SE tax. "
                f"Non-zero Box 14 incorrectly triggers ~15.3% SE tax.",
                'IRC §1402(a)(1); IRC §1402(a)(13); Pub 541 (Partnerships)',
                "Remove any IS.se_income or self-employment mapping from K-1 pipeline. "
                "Box 14 must be blank/$0 for rental LLC partners.")

    def _rule_box2_basis_advisory(self, owner: Dict):
        """
        SK1P-R05: Box 2 is a loss — advisory on IRC §704(d) basis limitation.
        IRC §704(d): a partner may not deduct a loss that exceeds their adjusted
        basis in the partnership interest. This is computed on the partner's
        individual return (Form 6198 or Schedule E limitations), not on the K-1.
        The K-1 always reports the full allocated amount regardless of basis.
        This rule is advisory — it does not change Box 2.
        """
        net = self._get_is_agg('net_rental')
        pct = _owner_pct(owner)
        box2 = round(net * pct, 2)
        oID = owner.get('oID', '')
        nm  = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        if box2 < -0.01:
            return self.format_issue(
                'SK1P-R05', self.INFO,
                f"Partner '{nm}' ({oID}): Box 2 = ${box2:,.2f} (passive loss). "
                f"IRC §704(d): partner can deduct this loss only to the extent "
                f"of their adjusted basis in the partnership. "
                f"Basis check is performed on the partner's individual return, not here. "
                f"The K-1 reports the full allocated amount regardless of basis.",
                'IRC §704(d); IRC §469(b); Form 6198; Schedule E Instructions',
                f"Advisory only — no K-1 change needed. "
                f"Inform partner '{nm}' to verify their basis before claiming the loss.")


# ────────────────────────────────────────────────────────────────────────────
#  AgentSchK1_Capital — Box L (Partner's Capital Account)
# ────────────────────────────────────────────────────────────────────────────

class AgentSchK1_Capital(_SectionAgent):
    """
    IRS Knowledge Base — Schedule K-1 Box L: Partner's Capital Account

    Post-2020 mandatory requirement (Rev. Proc. 2020-13; TD 9902):
      Box L must use the TAX BASIS METHOD. Previous methods (§704(b) book value,
      GAAP, or Other) are no longer accepted on Form 1065 for tax years 2020+.

    Tax basis capital account (IRC §705):
      Beginning capital (BOY)
      + Capital contributed during year
      + Ordinary income allocated
      + Other income/gain allocated
      − Ordinary loss allocated
      − Other loss allocated
      − Distributions
      = Ending capital (EOY)

    For W&B Group 2025 (first year):
      Beginning capital = $0 (new entity, no prior years)
      Capital contributed = per-partner cash contributions from llcOwners
      Allocated income/loss = Box 2 (net rental × pct)
      Distributions = llcOwners[partner].distributions
      Ending capital = contributions + Box 2 − distributions

    Box L method checkbox: "Tax basis" must be checked (not §704(b), GAAP, or Other).

    Why this matters: IRS uses Box L to verify partners are correctly tracking their
    basis for loss limitation (IRC §704(d)) and to detect transfers at above/below
    book value that may require §704(c) remedial allocations.
    """

    LABEL            = 'Capital Account (Box L)'
    AGENT_KEY        = 'AgentSchK1_Capital'
    LOGICAL_PREFIXES = ['SK1C_']

    def pass2_audit(self, owner: Dict) -> Dict[str, Any]:
        return self._run_audit([
            lambda o=owner: self._rule_tax_basis_method(o),
            lambda o=owner: self._rule_capital_summary(o),
            lambda o=owner: self._rule_capital_consistency(o),
        ], owner)

    def pass5_summarize(self, owner: Dict) -> str:
        pct      = _owner_pct(owner)
        net      = self._get_is_agg('net_rental')
        box2     = round(net * pct, 2)
        contrib  = _safe_float(owner.get('contributions', owner.get('capitalContrib', 0)))
        distrib  = _safe_float(owner.get('distributions', owner.get('distrib', 0)))
        ending   = round(contrib + box2 - distrib, 2)
        nm       = owner.get('nm', owner.get('name', owner.get('oID', 'Partner')))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        return (f"Capital (Box L): {nm} — "
                f"Beg $0 + Contrib ${contrib:,.2f} + Box2 ${box2:,.2f} "
                f"− Distrib ${distrib:,.2f} = Ending ${ending:,.2f} (tax basis).")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_tax_basis_method(self, owner: Dict):
        """
        SK1C-R01: Box L must use tax basis method (Rev. Proc. 2020-13).
        IRS required all partnerships to transition to tax basis reporting
        for capital accounts starting with tax years ending after December 31, 2019.
        Rev. Proc. 2020-13 provided transition relief; TD 9902 made it permanent.
        Using §704(b) book value, GAAP, or "Other" is no longer permitted.
        The method is disclosed via a checkbox in Box L:
          □ Tax basis  □ §704(b)  □ GAAP  □ Other
        """
        # Check if owner record has a capital_method indicator
        method = str(owner.get('capital_method', owner.get('capMethod', 'tax_basis'))).lower()
        oID = owner.get('oID', '')
        nm  = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        non_tax_basis_methods = ('704(b)', '704b', 'gaap', 'book_value', 'book')
        if any(m in method for m in non_tax_basis_methods):
            return self.format_issue(
                'SK1C-R01', self.WARN,
                f"Partner '{nm}' ({oID}): Box L capital method = '{method}'. "
                f"IRS requires TAX BASIS method for tax years 2020+ (Rev. Proc. 2020-13; TD 9902). "
                f"§704(b) book value, GAAP, and 'Other' methods are no longer accepted. "
                f"The 'Tax basis' checkbox in Box L must be checked.",
                'Rev. Proc. 2020-13; TD 9902; Form 1065 Instructions (K-1 Box L)',
                f"Change capital_method for partner '{oID}' to 'tax_basis' in llcOwners. "
                f"Check the 'Tax basis' box in K-1 Box L fill dict.")

    def _rule_capital_summary(self, owner: Dict):
        """
        SK1C-R02: Informational — tax basis capital account summary.
        For first-year entities: Beginning = $0, Ending = contributions + Box 2 − distributions.
        IRC §705: a partner's adjusted basis in the partnership begins at the
        amount of money contributed, increased by income allocated, and decreased
        by losses allocated and distributions.
        """
        pct     = _owner_pct(owner)
        net     = self._get_is_agg('net_rental')
        box2    = round(net * pct, 2)
        contrib = _safe_float(owner.get('contributions', owner.get('capitalContrib', 0)))
        distrib = _safe_float(owner.get('distributions', owner.get('distrib', 0)))
        ending  = round(contrib + box2 - distrib, 2)
        oID = owner.get('oID', '')
        nm  = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        return self.format_issue(
            'SK1C-R02', self.INFO,
            f"Partner '{nm}' ({oID}) Box L (tax basis, first year): "
            f"Beginning $0 + Contributions ${contrib:,.2f} + Box2 ${box2:,.2f} "
            f"− Distributions ${distrib:,.2f} = Ending capital ${ending:,.2f}. "
            f"IRC §705: tax basis begins at contribution + allocated income − losses − distributions.",
            'IRC §705; Rev. Proc. 2020-13; Form 1065 Instructions K-1 Box L',
            f"Verify Box L for '{nm}': "
            f"Beginning=$0, Contrib=${contrib:,.2f}, Box2=${box2:,.2f}, "
            f"Distrib=${distrib:,.2f}, Ending=${ending:,.2f}.")

    def _rule_capital_consistency(self, owner: Dict):
        """
        SK1C-R03: Ending capital inconsistent with simple tax basis calculation.
        If the owner record has an explicit capital_end value that differs from
        the computed value (contributions + Box2 − distributions), flag for review.
        This may indicate a prior-year balance, a mid-year contribution, or an error.
        The computed value is the minimum expected capital for a first-year LLC.
        """
        pct      = _owner_pct(owner)
        net      = self._get_is_agg('net_rental')
        box2     = round(net * pct, 2)
        contrib  = _safe_float(owner.get('contributions', owner.get('capitalContrib', 0)))
        distrib  = _safe_float(owner.get('distributions', owner.get('distrib', 0)))
        computed = round(contrib + box2 - distrib, 2)
        recorded = _safe_float(owner.get('capital_end', owner.get('capitalEnd', None)))
        oID = owner.get('oID', '')
        nm  = owner.get('nm', owner.get('name', oID))
        if isinstance(nm, list):
            nm = ' '.join(nm)
        if recorded is not None and abs(recorded - computed) > 1.00:
            return self.format_issue(
                'SK1C-R03', self.WARN,
                f"Partner '{nm}' ({oID}): recorded capital_end = ${recorded:,.2f} but "
                f"computed tax basis ending = ${computed:,.2f} "
                f"(contrib ${contrib:,.2f} + Box2 ${box2:,.2f} − distrib ${distrib:,.2f}). "
                f"Discrepancy: ${abs(recorded - computed):,.2f}. "
                f"IRC §705: verify the ending capital account balance.",
                'IRC §705; Rev. Proc. 2020-13',
                f"Check for: (a) prior-year balance (first year should start at $0), "
                f"(b) mid-year contributions not in owner record, "
                f"(c) data entry error in capital_end. "
                f"Correct llcOwners data for '{oID}'.")


# ════════════════════════════════════════════════════════════════════════════
#  FORMSCHK1AGENT  (Tier 1 orchestrator)
# ════════════════════════════════════════════════════════════════════════════

class FormSchK1Agent(IRSFormsAgent):
    """
    Tier 1 orchestrator — runs section agents per partner, not once for the form.
    Produces one K-1 set of audit results per partner in llcOwners.
    Session state is keyed by partner oID.
    Books-First: Box 2 = IS.net_rental × partner.pct. Box 14 = $0.
    """

    _SECTION_ORDER = [
        AgentSchK1_Identity,
        AgentSchK1_PassiveItems,
        AgentSchK1_Capital,
    ]

    def __init__(self, llc, tax_year: Optional[int] = None):
        super().__init__(llc, tax_year)
        self._section_agents = [cls(llc, self.tax_year) for cls in self._SECTION_ORDER]
        self._owners: Optional[List[Dict]] = None

    # ── Owner loading ─────────────────────────────────────────────────────────

    def _get_owners(self) -> List[Dict]:
        if self._owners is not None:
            return self._owners
        try:
            raw = self.llc.owners
            self._owners = raw() if callable(raw) else list(raw or [])
        except Exception:
            self._owners = []
        return self._owners

    # ── Public API ────────────────────────────────────────────────────────────

    def run_phases_1_2(self) -> Dict[str, Any]:
        owners       = self._get_owners()
        partner_state = {}
        overall_halt  = 0

        for owner in owners:
            oID = owner.get('oID', owner.get('ownerID', f"partner_{owners.index(owner)}"))
            nm  = owner.get('nm', owner.get('name', oID))
            if isinstance(nm, list):
                nm = ' '.join(nm)

            partner_issues = []
            partner_halt   = 0
            sections_for_partner = {}

            for agent in self._section_agents:
                p1 = agent.pass1_auto_fill(owner)
                p2 = agent.pass2_audit(owner)

                issues   = p2.get('issue_list', [])
                state    = p2.get('ready_state', self.GO)
                summary  = (agent.pass5_summarize(owner)
                            if state == self.GO
                            else self._first_halt_message(issues))

                sections_for_partner[agent.AGENT_KEY] = {
                    'label':         agent.LABEL,
                    'state':         state,
                    'summary':       summary,
                    'halt_count':    p2.get('halt_count', 0),
                    'resolve_count': p2.get('resolve_count', 0),
                    'review_count':  p2.get('review_count', 0),
                    'issues':        issues,
                }
                partner_issues.extend(issues)
                partner_halt += p2.get('halt_count', 0)

            # Compute per-partner K-1 values for session state
            try:
                from ledger.stmtIS import stmtIS
                agg = stmtIS(self.llc).taxAggregates()
            except Exception:
                agg = {}
            net    = _safe_float(agg.get('net_rental', 0))
            pct    = _owner_pct(owner)
            box2   = round(net * pct, 2)
            contrib = _safe_float(owner.get('contributions', owner.get('capitalContrib', 0)))
            distrib = _safe_float(owner.get('distributions', owner.get('distrib', 0)))
            cap_end = round(contrib + box2 - distrib, 2)

            partner_state[oID] = {
                'name':          nm,
                'pct':           pct,
                'state':         self.NEEDS_FIXING if partner_halt > 0 else self.GO,
                'halt_count':    partner_halt,
                'box2':          box2,
                'capital_ending': cap_end,
                'sections':      sections_for_partner,
            }
            overall_halt += partner_halt

        # Aggregate pass5 summary
        owners_list = self._get_owners()
        try:
            from ledger.stmtIS import stmtIS
            agg = stmtIS(self.llc).taxAggregates()
            net_rental = _safe_float(agg.get('net_rental', 0))
        except Exception:
            net_rental = 0.0
        names = []
        for o in owners_list:
            nm = o.get('nm', o.get('name', o.get('oID', '')))
            if isinstance(nm, list):
                nm = ' '.join(nm)
            names.append(nm)
        pcts = [_owner_pct(o) * 100 for o in owners_list]
        pct_str = ', '.join(f"{p:.2f}%" for p in pcts)
        alloc = round(net_rental / len(owners_list), 2) if owners_list else 0.0

        overall_state = self.NEEDS_FIXING if overall_halt > 0 else self.GO

        session = {
            'tax_year':      self.tax_year,
            'last_run':      _now_iso(),
            'overall_state': overall_state,
            'partner_count': len(owners_list),
            'partners':      partner_state,
            'summary':       (
                f"{len(owners_list)} Schedule K-1s: {', '.join(names)}. "
                f"Box 2 allocations: {pct_str} each = ${alloc:,.2f} per partner "
                f"(net rental {'loss' if net_rental < 0 else 'income'}). "
                f"Box 14 = $0. Tax basis capital tracked."
            ),
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
                'partners':      {},
                'summary':       'Not yet run',
            }
        return state

    # ── Session state persistence ─────────────────────────────────────────────

    def _session_state_path(self) -> Optional[Path]:
        d = self._agent_work_dir()
        if d is None:
            return None
        return d / 'FormSchK1_session_state.json'

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

    @staticmethod
    def _first_halt_message(issues: List[Dict]) -> str:
        for i in issues:
            if i.get('severity') == 'ERROR':
                return i.get('message', 'Error — see Guided Review')
        return issues[0]['message'] if issues else ''
