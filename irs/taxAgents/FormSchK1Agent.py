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
  Box K1 = QNR financing × pct (IRC §752; §465(b)(6))

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
    v = _safe_float(owner.get('pct', owner.get('ownership_pct', owner.get('ownerPct', 0))))
    return v if v <= 1.5 else v / 100.0


def _owner_name(owner: Dict) -> str:
    nm = owner.get('nm', owner.get('name', owner.get('oID', 'Partner')))
    return ' '.join(nm) if isinstance(nm, list) else str(nm)


# ════════════════════════════════════════════════════════════════════════════
#  SECTION AGENT BASE
# ════════════════════════════════════════════════════════════════════════════

class _SectionAgent(IRSFormsAgent):
    """Common base for all Schedule K-1 section agents (per-partner)."""

    LABEL        = ''
    AGENT_KEY    = ''
    LOGICAL_PREFIXES: List[str] = []

    def __init__(self, llc, tax_year: int):
        super().__init__(llc, tax_year)
        self._is_data  = None
        self._profile  = None

    # ── Data loaders (lazy) ──────────────────────────────────────────────────

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

    def _get_profile(self) -> Dict:
        if self._profile is not None:
            return self._profile
        try:
            from irs.Sch_K1 import Sch_K1
            k1 = Sch_K1(llc=self.llc)
            entity, f1065 = k1._loadProfile()
            self._profile = {'entity': entity, 'F1065': f1065}
        except Exception:
            self._profile = {'entity': {}, 'F1065': {}}
        return self._profile

    # ── Pass interface ───────────────────────────────────────────────────────

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
        return f"{self.LABEL}: {_owner_name(owner)} — complete."

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


# ════════════════════════════════════════════════════════════════════════════
#  AgentSchK1_PartnershipInfo — Part I: f1–f13
# ════════════════════════════════════════════════════════════════════════════

class AgentSchK1_PartnershipInfo(_SectionAgent):
    """
    IRS Expert — Schedule K-1 Part I: Partnership Identification (f1–f13)

    Runs once per K-1 pass (partnership info is identical on every partner's K-1).
    Validates: tax year accounting period, EIN, name, IRS center, PTP, Final/Amended flags.

    IRC §441, §706 — accounting period
    IRC §6109; Treas. Reg. §301.6109-1 — EIN requirement
    IRC §7704(b) — PTP definition
    Form 1065 Instructions (K-1 header) — IRS center, Final K-1, Amended K-1
    """

    LABEL     = 'Part I: Partnership Identification'
    AGENT_KEY = 'AgentSchK1_PartnershipInfo'

    def pass2_audit(self, owner: Dict) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_tax_year,
            self._rule_ein,
            self._rule_name,
            self._rule_irs_center,
            self._rule_ptp_flag,
            self._rule_final_k1,
            self._rule_amended_k1,
        ], owner)

    def pass5_summarize(self, owner: Dict) -> str:
        pr = self._get_profile()
        entity = pr.get('entity', {})
        f1065  = pr.get('F1065', {})
        nm = entity.get('entity_name', 'W&B Group, LLC')
        ein = entity.get('ein', '?')
        dfrom = f1065.get('date_from', '?')
        dto   = f1065.get('date_to', '?')
        return (f"Partnership Info: {nm} EIN={ein} "
                f"Tax year {dfrom} – {dto}. "
                f"IRS center='{f1065.get('irs_center', '(not set)')}'.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_tax_year(self, owner: Dict):
        """
        SK1A-R01: Tax year accounting period — IRC §441, §706.
        §706(b)(1)(B): partnership must use calendar year unless majority partners
        use a different year. Verify F1065.date_from parses to 01/01 and
        date_to to 12/31. Also verify tax_year is not null.
        """
        pr    = self._get_profile()
        f1065 = pr.get('F1065', {})
        dfrom = str(f1065.get('date_from', '') or '')
        dto   = str(f1065.get('date_to', '') or '')
        ty    = f1065.get('tax_year')
        oID   = owner.get('oID', '')

        if not ty:
            return self.format_issue(
                'SK1A-R01', self.ERROR,
                f"Partner {oID}: F1065.tax_year is null/missing in llcProfile. "
                f"The 2-digit tax year (e.g. '25') is required for K-1 header (f5). "
                f"IRC §441: partnerships must file for the tax year defined in their books.",
                'IRC §441; IRC §706; Form 1065 Instructions (K-1 header)',
                "Set tax_year (e.g. '25') in llcProfile_WBGroupLLC.json → F1065 section.")

        # Warn if looks like non-calendar year (optional soft check)
        jan = dfrom.lower().startswith('jan') or dfrom.startswith('01')
        dec = dto.lower().startswith('dec') or dto.startswith('12')
        if dfrom and dto and (not jan or not dec):
            return self.format_issue(
                'SK1A-R01', self.WARN,
                f"Partner {oID}: Tax year appears non-calendar ({dfrom} – {dto}). "
                f"IRC §706(b)(1)(B): W&B Group must use the calendar year unless "
                f"majority partners have a different tax year. Confirm §706 applies.",
                'IRC §441; IRC §706(b)(1)(B)',
                "Verify the LLC's accounting period. If calendar year, correct date_from/'to.")

    def _rule_ein(self, owner: Dict):
        """
        SK1A-R02: Partnership EIN format — IRC §6109; Treas. Reg. §301.6109-1.
        EIN must be exactly 9 digits (XX-XXXXXXX). Missing or malformed EIN causes
        IRS rejection of the entire Form 1065 return.
        """
        pr   = self._get_profile()
        ein  = str(pr.get('entity', {}).get('ein', '') or '').replace('-', '').strip()
        oID  = owner.get('oID', '')
        if not ein or len(ein) != 9 or not ein.isdigit():
            return self.format_issue(
                'SK1A-R02', self.ERROR,
                f"Partner {oID}: Partnership EIN '{ein}' is missing or malformed. "
                f"IRC §6109: EIN must be 9 digits (XX-XXXXXXX format). "
                f"A bad EIN causes IRS rejection of the entire Form 1065 return — "
                f"including all K-1s attached to it.",
                'IRC §6109; Treas. Reg. §301.6109-1',
                "Set entity.ein to a valid 9-digit EIN in llcProfile_WBGroupLLC.json.")

    def _rule_name(self, owner: Dict):
        """
        SK1A-R03: Partnership name must match Form 1065 page 1 exactly.
        IRS uses computer matching — a name typo or abbreviation may cause matching failure.
        """
        pr   = self._get_profile()
        nm   = str(pr.get('entity', {}).get('entity_name', '') or '').strip()
        oID  = owner.get('oID', '')
        if not nm:
            return self.format_issue(
                'SK1A-R03', self.ERROR,
                f"Partner {oID}: Partnership entity_name is blank. "
                f"The name on each K-1 must match Form 1065 page 1 line 1 exactly. "
                f"IRS computer matching uses name + EIN; a missing name causes matching failure.",
                'Form 1065 Instructions (K-1 Line B)',
                "Set entity.entity_name in llcProfile_WBGroupLLC.json.")

    def _rule_irs_center(self, owner: Dict):
        """
        SK1A-R04: IRS Service Center — Form 1065 Instructions (K-1 Line C).
        K-1 Line C shows where the partnership filed. For e-filed returns: 'E-File'.
        For paper: typically 'Ogden, UT 84201' for most partnerships in 2025.
        Blank is allowed but a WARN is appropriate.
        """
        pr     = self._get_profile()
        center = str(pr.get('F1065', {}).get('irs_center', '') or '').strip()
        oID    = owner.get('oID', '')
        if not center:
            return self.format_issue(
                'SK1A-R04', self.WARN,
                f"Partner {oID}: F1065.irs_center is blank. "
                f"K-1 Line C should show where Form 1065 was filed. "
                f"For e-filed returns: write 'E-File'. For paper: 'Ogden, UT 84201'.",
                'Form 1065 Instructions (K-1 Line C)',
                "Set F1065.irs_center in llcProfile_WBGroupLLC.json. "
                "E-filed returns: use 'E-File'.")

    def _rule_ptp_flag(self, owner: Dict):
        """
        SK1A-R05: PTP (publicly traded partnership) flag must be unchecked — IRC §7704.
        W&B Group is a private LLC with individual members — categorically NOT a PTP.
        §7704(b): PTP requires interests traded on an established market.
        """
        pr    = self._get_profile()
        is_ptp = pr.get('F1065', {}).get('is_ptp', False)
        oID   = owner.get('oID', '')
        if is_ptp:
            return self.format_issue(
                'SK1A-R05', self.ERROR,
                f"Partner {oID}: F1065.is_ptp = True. "
                f"W&B Group is a private LLC — it does not meet IRC §7704(b) PTP criteria. "
                f"§7704(b): partnership interests must be traded on an established securities market. "
                f"Checking this box changes tax treatment of ALL partners.",
                'IRC §7704(b)',
                "Set is_ptp = False in llcProfile F1065 section.")

    def _rule_final_k1(self, owner: Dict):
        """
        SK1A-R06: Final K-1 flag — Form 1065 Instructions.
        Check 'Final K-1' only if this partner is leaving the LLC or the LLC is liquidating.
        A Final K-1 triggers basis recognition events on the partner's individual return.
        """
        pr        = self._get_profile()
        is_final  = pr.get('F1065', {}).get('is_final_k1', False)
        oID       = owner.get('oID', '')
        if is_final:
            return self.format_issue(
                'SK1A-R06', self.INFO,
                f"Partner {oID}: Final K-1 flag is set. "
                f"Confirm this partner exited the LLC or the LLC was liquidated this tax year. "
                f"A Final K-1 means the partner must recognize any remaining "
                f"outside basis gain/loss on their individual return.",
                'Form 1065 Instructions (K-1 header — Final K-1)',
                f"If '{oID}' is NOT leaving the LLC, clear is_final_k1 in llcProfile.")

    def _rule_amended_k1(self, owner: Dict):
        """
        SK1A-R07: Amended K-1 flag — Form 1065 Instructions.
        Check 'Amended K-1' only if issuing a corrected K-1 after the original was filed.
        An amended K-1 must be provided to the partner AND filed with IRS.
        """
        pr          = self._get_profile()
        is_amended  = pr.get('F1065', {}).get('is_amended_k1', False)
        oID         = owner.get('oID', '')
        if is_amended:
            return self.format_issue(
                'SK1A-R07', self.INFO,
                f"Partner {oID}: Amended K-1 flag is set. "
                f"Confirm the original K-1 was previously filed with IRS. "
                f"An amended K-1 must be furnished to the partner AND attached to "
                f"an amended Form 1065 (if the partnership return is also being amended).",
                'Form 1065 Instructions (K-1 header — Amended K-1)',
                "If this is the original (not amended) K-1, clear is_amended_k1 in llcProfile.")


# ════════════════════════════════════════════════════════════════════════════
#  AgentSchK1_PartnerCapital — Part II: f14–f48
# ════════════════════════════════════════════════════════════════════════════

class AgentSchK1_PartnerCapital(_SectionAgent):
    """
    IRS Expert — Schedule K-1 Part II: Partner Capital & Liabilities (f14–f48)

    Per-partner: partner type, domestic/foreign, ownership %, liabilities, capital account.

    IRC §761(b) — partner type (GP vs LP)
    IRC §705, §722 — capital account computation
    IRC §752; Treas. Reg. §1.752-2/3 — liability sharing
    IRC §465(b)(6) — qualified nonrecourse financing
    Rev. Proc. 2020-13; TD 9902 — mandatory tax basis capital accounts (Box L)
    IRC §704(b) — substantial economic effect
    Treas. Reg. §301.7701-3 — disregarded entity
    IRC §704(c); Treas. Reg. §1.704-3 — contributed property built-in gain
    """

    LABEL     = 'Part II: Partner Capital & Liabilities'
    AGENT_KEY = 'AgentSchK1_PartnerCapital'

    def pass2_audit(self, owner: Dict) -> Dict[str, Any]:
        return self._run_audit([
            lambda o=owner: self._rule_partner_type(o),
            lambda o=owner: self._rule_domestic_foreign(o),
            lambda o=owner: self._rule_disregarded_entity(o),
            lambda o=owner: self._rule_ownership_pct(o),
            lambda o=owner: self._rule_box_k1_liabilities(o),
            lambda o=owner: self._rule_tax_basis_method(o),
            lambda o=owner: self._rule_capital_account_summary(o),
            lambda o=owner: self._rule_sec704c(o),
        ], owner)

    def pass5_summarize(self, owner: Dict) -> str:
        pct     = _owner_pct(owner)
        net     = self._get_is_agg('net_rental')
        box2    = round(net * pct, 2)
        contrib = _safe_float(owner.get('contributions', owner.get('capitalContrib', 0)))
        distrib = _safe_float(owner.get('distributions', owner.get('distrib', 0)))
        ending  = round(contrib + box2 - distrib, 2)
        nm      = _owner_name(owner)
        return (f"Capital (Box L): {nm} — "
                f"Beg=$0 + Contrib=${contrib:,.2f} + Box2=${box2:,.2f} "
                f"− Distrib=${distrib:,.2f} = Ending=${ending:,.2f} (tax basis).")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_partner_type(self, owner: Dict):
        """
        SK1B-R01: Partner type classification — IRC §761(b); Form 1065 Instructions Line G.
        W&B is member-managed. 'Manager' status → Line G checkbox: GP/member-manager.
        All others → LP/other LLC member. Blank status → WARN (can't determine type).
        This affects SE tax analysis (§1402) — though ALL rental income is passive (§469).
        """
        status = str(owner.get('status', '') or '').strip()
        oID    = owner.get('oID', '')
        nm     = _owner_name(owner)
        if not status:
            return self.format_issue(
                'SK1B-R01', self.WARN,
                f"Partner '{nm}' ({oID}): status field is blank — cannot determine "
                f"whether this partner is a GP/member-manager or LP/other member. "
                f"IRC §761(b): partner type affects SE tax analysis under §1402. "
                f"For W&B rental LLC: all income is passive (§469(c)(2)) regardless of type.",
                'IRC §761(b); IRC §1402; Form 1065 Instructions (K-1 Line G)',
                f"Set status='Manager' for managing members, or leave blank/set 'Member' "
                f"for passive members in llcOwners for partner '{oID}'.")

    def _rule_domestic_foreign(self, owner: Dict):
        """
        SK1B-R02: Domestic vs. foreign partner — IRC §1441, §1446.
        Foreign partner requires 37% withholding on ECTI (§1446(a)) and Forms 8804/8805.
        Infer domestic if partner has a 9-digit SSN (US SSN format).
        """
        ssn  = str(owner.get('SSN', owner.get('ssn', owner.get('tin', '')))).replace('-', '').strip()
        tID  = str(owner.get('tID', '') or '').strip()
        nm   = _owner_name(owner)
        oID  = owner.get('oID', '')
        # Heuristic: has 9-digit SSN → domestic US person
        has_ssn = len(ssn) == 9 and ssn.isdigit()
        has_ein = len(tID.replace('-', '')) == 9 and tID.replace('-', '').isdigit() and not has_ssn
        if has_ein and not has_ssn:
            return self.format_issue(
                'SK1B-R02', self.WARN,
                f"Partner '{nm}' ({oID}): has an EIN (tID={tID}) but no SSN. "
                f"If this partner is a foreign entity, IRC §1446 requires the partnership "
                f"to withhold 37% of ECTI and file Forms 8804/8805. "
                f"Verify: is this partner a domestic or foreign entity?",
                'IRC §1441; IRC §1446; Forms 8804, 8805',
                f"Confirm citizenship/residency of partner '{oID}'. "
                f"If foreign: engage CPA for §1446 withholding. "
                f"If domestic: add SSN to llcOwners.")

    def _rule_disregarded_entity(self, owner: Dict):
        """
        SK1B-R03: Disregarded entity check — Treas. Reg. §301.7701-3.
        A single-member LLC (SMLLC) that hasn't elected corporate treatment is a DRE.
        Individual humans are NEVER disregarded entities.
        Detect: tID set AND name contains 'LLC' or 'Trust'.
        """
        nm   = _owner_name(owner)
        tID  = str(owner.get('tID', '') or '').strip()
        oID  = owner.get('oID', '')
        nm_upper = nm.upper()
        is_entity_nm = any(kw in nm_upper for kw in ('LLC', 'TRUST', 'CORP', 'INC', 'LTD'))
        if tID and is_entity_nm:
            return self.format_issue(
                'SK1B-R03', self.INFO,
                f"Partner '{nm}' ({oID}): may be a disregarded entity (SMLLC or Trust). "
                f"Treas. Reg. §301.7701-3: if this partner is an SMLLC that hasn't elected "
                f"corporate treatment, check Line H2 on the K-1. "
                f"The K-1 is issued to the LLC, but the beneficial owner's SSN goes in Line E.",
                'Treas. Reg. §301.7701-3; Form 1065 Instructions (K-1 Line H2)',
                f"Verify the legal structure of '{nm}'. If DE: check K1_PtDE checkbox. "
                f"Ensure Line E (K1_PtEIN) contains the beneficial owner's SSN, not the LLC EIN.")

    def _rule_ownership_pct(self, owner: Dict):
        """
        SK1B-R04: Ownership percentage — IRC §704(b), §706.
        All three (profit/loss/capital) must equal partner's pct (uniform allocation).
        Sum of all partners' pct must = 1.000 (100%). Zero pct → all Box amounts = $0.
        """
        pct  = _owner_pct(owner)
        oID  = owner.get('oID', '')
        nm   = _owner_name(owner)
        if pct < 0.001:
            return self.format_issue(
                'SK1B-R04', self.ERROR,
                f"Partner '{nm}' ({oID}): ownership percentage is {pct:.4f} (zero or missing). "
                f"IRC §704(b): allocations must be based on partners' distributive shares. "
                f"All K-1 Box amounts (Box 2, Box 5, Box L) = $0 if pct = 0, "
                f"omitting this partner's rental income/loss from their tax return.",
                'IRC §704(b); IRC §706; Form 1065 Instructions (K-1 Box J)',
                f"Set pct for partner '{oID}' in llcOwners. "
                f"Sum of all partners' pct must equal 1.0 (100%).")

    def _rule_box_k1_liabilities(self, owner: Dict):
        """
        SK1B-R05: Box K1 — partner's share of liabilities — IRC §752; Treas. Reg. §1.752-3.
        W&B real estate mortgage → Qualified Nonrecourse Financing (§465(b)(6)):
          commercial lender, no personal guarantees, lender's only recourse is the property.
        Shared in same ratio as profits (Treas. Reg. §1.752-3(a)(3)).
        Box K1 QNR = BS.mortgage × pct. This affects each partner's outside basis.
        """
        # Get mortgage from BS if available
        mortgage = 0.0
        try:
            from ledger.stmtBS import stmtBS_Tax
            mortgage = _safe_float(stmtBS_Tax(self.llc).taxAggregates().get('mortgage', 0))
        except Exception:
            pass

        pct  = _owner_pct(owner)
        oID  = owner.get('oID', '')
        nm   = _owner_name(owner)
        partner_qnr = round(mortgage * pct, 2)

        if mortgage > 0:
            return self.format_issue(
                'SK1B-R05', self.INFO,
                f"Partner '{nm}' ({oID}): Box K1 QNR financing = "
                f"${mortgage:,.2f} × {pct*100:.2f}% = ${partner_qnr:,.2f}. "
                f"IRC §752; §465(b)(6): W&B mortgage classified as Qualified Nonrecourse "
                f"(commercial lender, no personal guarantees, RE collateral only). "
                f"This increases each partner's outside basis by their QNR share.",
                'IRC §752; §465(b)(6); Treas. Reg. §1.752-3(a)(3)',
                f"Confirm mortgage type: commercial lender, no personal guarantees = QNRF. "
                f"Box K1 f34 should show ${partner_qnr:,.2f} for '{nm}'.")
        else:
            return self.format_issue(
                'SK1B-R05', self.WARN,
                f"Partner '{nm}' ({oID}): Box K1 QNR = $0 (no mortgage found in BS). "
                f"If the LLC has a mortgage, verify the BS stmtBalanceSheet.taxAggregates() "
                f"returns a 'mortgage' key. Partners' outside basis is understated without it.",
                'IRC §752; Treas. Reg. §1.752-3',
                "Verify mortgage balance in llcAssets and ensure BS.mortgage key is populated.")

    def _rule_tax_basis_method(self, owner: Dict):
        """
        SK1B-R06: Box L method must be Tax Basis — Rev. Proc. 2020-13; TD 9902.
        IRS mandated tax basis capital accounts for all partnerships starting 2020.
        §704(b) book value, GAAP, and 'Other' methods are no longer accepted.
        The 'Tax basis' checkbox in Box L (f45) must be checked.
        """
        method = str(owner.get('capital_method', owner.get('capMethod', 'tax_basis'))).lower()
        oID    = owner.get('oID', '')
        nm     = _owner_name(owner)
        non_tax = ('704(b)', '704b', 'gaap', 'book_value', 'book')
        if any(m in method for m in non_tax):
            return self.format_issue(
                'SK1B-R06', self.WARN,
                f"Partner '{nm}' ({oID}): Box L capital method = '{method}'. "
                f"Rev. Proc. 2020-13; TD 9902: all partnerships must use TAX BASIS method "
                f"for capital accounts for tax years 2020+. "
                f"§704(b) book value, GAAP, and 'Other' are no longer accepted. "
                f"The 'Tax basis' checkbox (f45) must be checked.",
                'Rev. Proc. 2020-13; TD 9902; Form 1065 Instructions (K-1 Box L)',
                f"Change capital_method for '{oID}' to 'tax_basis' in llcOwners. "
                f"K1_L_TaxBasis checkbox will be checked automatically.")

    def _rule_capital_account_summary(self, owner: Dict):
        """
        SK1B-R07: Box L capital account computation — IRC §705; §722.
        Tax basis capital = contributions + net income − losses − distributions.
        Formula: $0 + contributions + Box2 − distributions = ending capital.
        IRC §705: adjusted basis in partnership begins at money contributed,
        increased by income, decreased by losses and distributions.
        """
        pct     = _owner_pct(owner)
        net     = self._get_is_agg('net_rental')
        box2    = round(net * pct, 2)
        contrib = _safe_float(owner.get('contributions', owner.get('capitalContrib', 0)))
        distrib = _safe_float(owner.get('distributions', owner.get('distrib', 0)))
        ending  = round(contrib + box2 - distrib, 2)
        oID     = owner.get('oID', '')
        nm      = _owner_name(owner)

        # Flag missing contribution data
        if contrib == 0:
            return self.format_issue(
                'SK1B-R07', self.WARN,
                f"Partner '{nm}' ({oID}): contributions = $0. "
                f"Box L Line 2 (K1_L2) will be $0. "
                f"If this partner contributed cash at LLC formation, "
                f"add a 'contributions' key to their owner record or "
                f"record a CapitalContrib transaction in llcAssets tagged to oID={oID}. "
                f"IRC §722: partner's initial basis = money contributed.",
                'IRC §705; §722; Form 1065 Instructions (K-1 Box L)',
                f"Add contributions key for '{oID}' in llcOwners OR "
                f"record ledger CapitalContrib entry. "
                f"Box L: Beg=$0, Contrib=$0, Box2=${box2:,.2f}, "
                f"Distrib=${distrib:,.2f}, Ending=${ending:,.2f}.")
        else:
            return self.format_issue(
                'SK1B-R07', self.INFO,
                f"Partner '{nm}' ({oID}) Box L (tax basis, first year): "
                f"Beginning=$0 + Contributions=${contrib:,.2f} + Box2=${box2:,.2f} "
                f"− Distributions=${distrib:,.2f} = Ending=${ending:,.2f}. "
                f"IRC §705: tax basis begins at contribution + allocated income − distributions.",
                'IRC §705; Rev. Proc. 2020-13; Form 1065 Instructions (K-1 Box L)',
                f"Verify Box L for '{nm}': all five fields are correctly populated.")

    def _rule_sec704c(self, owner: Dict):
        """
        SK1B-R08: §704(c) allocated gain — IRC §704(c); Treas. Reg. §1.704-3.
        §704(c) applies when a partner contributes property with built-in gain/loss
        (property FMV ≠ tax basis at contribution). Line N discloses this amount.
        For cash-only contributions → §704(c) = $0 → Line N = blank.
        """
        contrib = _safe_float(owner.get('contributions', owner.get('capitalContrib', 0)))
        oID     = owner.get('oID', '')
        nm      = _owner_name(owner)
        # If all contributions are cash (no property contributed), §704(c) = $0
        if contrib > 0:
            return self.format_issue(
                'SK1B-R08', self.INFO,
                f"Partner '{nm}' ({oID}): contributions = ${contrib:,.2f}. "
                f"IRC §704(c): if all contributions were cash, Line N (§704(c) gain) = $0 "
                f"(K1_N_Beg and K1_N_End both blank). "
                f"If property was contributed (not cash), a CPA must calculate the "
                f"built-in gain/loss under Treas. Reg. §1.704-3 and disclose it on Line N.",
                'IRC §704(c); Treas. Reg. §1.704-3; Form 1065 Instructions (K-1 Line N)',
                f"Confirm: were all contributions cash? If yes, Line N is blank (correct). "
                f"If property was contributed, engage CPA to compute §704(c) amounts.")


# ════════════════════════════════════════════════════════════════════════════
#  AgentSchK1_PassiveItems — Part III: f49–f77
# ════════════════════════════════════════════════════════════════════════════

class AgentSchK1_PassiveItems(_SectionAgent):
    """
    IRS Expert — Schedule K-1 Part III: Passive Income & Deductions (f49–f77)

    Per-partner: all dollar amounts = IS.value × pct (Books-First, IRC §446/703).

    IRC §469(c)(2) — rental activity is always passive → Box 1 = $0
    IRC §702(a) — separately stated items (Box 2, Box 5) retain character
    IRC §707(c) — guaranteed payments → Box 4 = $0 for W&B
    IRC §1402(a)(1)/(13) — rental excluded from SE earnings → Box 14a = $0
    IRC §179; §469(j)(1) — §179 passive limitation (Box 12)
    IRC §704(d) — basis limitation on partner's loss deduction
    """

    LABEL     = 'Part III: Passive Income & Deductions'
    AGENT_KEY = 'AgentSchK1_PassiveItems'

    def pass2_audit(self, owner: Dict) -> Dict[str, Any]:
        return self._run_audit([
            lambda o=owner: self._rule_box1_must_zero(o),
            lambda o=owner: self._rule_box2_net_rental(o),
            lambda o=owner: self._rule_box3_other_rental(o),
            lambda o=owner: self._rule_box4_guaranteed_payments(o),
            lambda o=owner: self._rule_box5_interest(o),
            lambda o=owner: self._rule_boxes_6_10_investment(o),
            lambda o=owner: self._rule_box12_sec179(o),
            lambda o=owner: self._rule_box14_must_zero(o),
            lambda o=owner: self._rule_box2_basis_advisory(o),
        ], owner)

    def pass5_summarize(self, owner: Dict) -> str:
        pct   = _owner_pct(owner)
        net   = self._get_is_agg('net_rental')
        box2  = round(net * pct, 2)
        nm    = _owner_name(owner)
        intr  = round(self._get_is_agg('interest_income') * pct, 2)
        return (f"Passive Items: {nm} — "
                f"Box 1=$0, Box 2=${box2:,.2f} "
                f"(IS.net_rental ${net:,.2f} × {pct*100:.2f}%), "
                f"Box 5=${intr:,.2f}, Box 14a=$0.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_box1_must_zero(self, owner: Dict):
        """
        SK1C-R01: Box 1 (ordinary income) MUST be $0 — IRC §469(c)(2).
        §469(c)(2): 'The term rental activity means any activity where payments are
        principally for the use of tangible property.' ALL rental activity is passive.
        Box 1 derives from Form 1065 Page 1 Lines 3–22 — all $0 for pure rental LLC.
        Non-zero Box 1 on a rental LLC is a fundamental IRS reporting error.
        """
        agg     = self._get_is()
        ord_inc = _safe_float(agg.get('ordinary_income', agg.get('ordinary_business_income', 0)))
        oID     = owner.get('oID', '')
        if abs(ord_inc) > 0.01:
            return self.format_issue(
                'SK1C-R01', self.ERROR,
                f"Partner {oID}: IS shows ordinary_income = ${ord_inc:,.2f}. "
                f"Box 1 would be non-zero — must be $0 for a rental LLC. "
                f"IRC §469(c)(2): all rental activity is passive. Box 1 is for non-rental "
                f"partnerships (manufacturing, services). Box 1 = Form 1065 Page 1 Line 23 = $0.",
                'IRC §469(c)(2); Form 1065 Instructions (K-1 Box 1)',
                "Remove any IS.ordinary_income mapping from the K-1 Box 1 pipeline. "
                "Verify Form 1065 Page 1 Lines 1-23 are all $0.")

    def _rule_box2_net_rental(self, owner: Dict):
        """
        SK1C-R02: Box 2 = IS.net_rental × pct — Books-First (IRC §446/703).
        IRC §702(a): rental income retains passive character through to partners' returns.
        Cross-form sourcing (from Schedule K form field) violates Books-First rule.
        If Box 2 < 0 (loss), each partner applies IRC §469 passive activity rules
        on their individual return to determine deductibility.
        """
        net      = self._get_is_agg('net_rental')
        pct      = _owner_pct(owner)
        expected = round(net * pct, 2)
        oID      = owner.get('oID', '')
        nm       = _owner_name(owner)
        if abs(expected) > 0.01:
            return self.format_issue(
                'SK1C-R02', self.INFO,
                f"Partner '{nm}' ({oID}): Box 2 = IS.net_rental ${net:,.2f} × "
                f"{pct*100:.2f}% = ${expected:,.2f}. "
                f"Books-First (IRC §446): K-1 Box 2 must equal this computed value. "
                f"LLCTaxAgent XF-R03 verifies sum of all partners' Box 2 = Schedule K Line 2.",
                'IRC §446; IRC §702(a); IRC §703; Books-First rule',
                f"Confirm K-1 Box 2 for '{nm}' = ${expected:,.2f} in the fill dict/PDF.")
        elif abs(net) < 0.01:
            return self.format_issue(
                'SK1C-R02', self.WARN,
                f"Partner '{nm}' ({oID}): IS.net_rental = $0. "
                f"Box 2 will be blank. If the LLC has rental activity, "
                f"verify all rental income and expenses are recorded in the books.",
                'IRC §702(a); IRC §446',
                "Check IS income/expense accounts. Net rental should reflect "
                "gross rent minus all rental expenses.")

    def _rule_box3_other_rental(self, owner: Dict):
        """
        SK1C-R03: Box 3 (other net rental income) = $0 — IRC §469(c)(2).
        Box 3 is for non-real-estate rental (equipment, vehicles, etc.).
        W&B Group rents real property ONLY → Box 3 must be $0.
        If Box 3 is non-zero, the LLC may be misclassifying real estate rental income.
        """
        agg = self._get_is()
        other = _safe_float(agg.get('other_rental', agg.get('equipment_rental', 0)))
        oID  = owner.get('oID', '')
        if abs(other) > 0.01:
            return self.format_issue(
                'SK1C-R03', self.WARN,
                f"Partner {oID}: IS shows other rental income = ${other:,.2f}. "
                f"Box 3 is for non-real-estate rental (equipment, vehicles). "
                f"IRC §469(c)(2): real property rental income belongs in Box 2, not Box 3. "
                f"If this is real estate rental income, reclassify to IS.net_rental.",
                'IRC §469(c)(2); Form 1065 Instructions (K-1 Box 3)',
                "Review the COA accounts contributing to IS.other_rental. "
                "Real estate rental → Box 2 (K1_2). Equipment rental → Box 3 (K1_3).")

    def _rule_box4_guaranteed_payments(self, owner: Dict):
        """
        SK1C-R04: Box 4 (guaranteed payments) = $0 — IRC §707(c).
        Guaranteed payments are amounts paid to partners without regard to partnership income.
        W&B Operating Agreement has no guaranteed payments.
        Payments to partners should be distributions (Box 19), not deductions.
        """
        agg  = self._get_is()
        gp   = _safe_float(agg.get('guaranteed_payments', agg.get('management_fees', 0)))
        oID  = owner.get('oID', '')
        if abs(gp) > 0.01:
            return self.format_issue(
                'SK1C-R04', self.WARN,
                f"Partner {oID}: IS shows management_fees/guaranteed_payments = ${gp:,.2f}. "
                f"IRC §707(c): guaranteed payments are deducted by the partnership and "
                f"are ordinary income to the recipient partner (Boxes 4a/4b/4c). "
                f"If W&B's operating agreement does not provide for guaranteed payments, "
                f"these should be classified as distributions (Box 19a), not deductions.",
                'IRC §707(c); Form 1065 Instructions (K-1 Box 4)',
                "Review management_fees in COA. If paid to a partner as guaranteed payment, "
                "use Box 4 (K1_4a/4b/4c). If profit distribution, use Box 19a (K1_19a).")

    def _rule_box5_interest(self, owner: Dict):
        """
        SK1C-R05: Box 5 (interest income) — IRC §702(a)(1) separately stated item.
        Interest income retains its character at the partner level (Schedule B income).
        Box 5 = IS.interest_income × pct. $0 is correct if no bank interest earned.
        """
        interest = self._get_is_agg('interest_income')
        pct      = _owner_pct(owner)
        box5     = round(interest * pct, 2)
        oID      = owner.get('oID', '')
        nm       = _owner_name(owner)
        if abs(box5) > 0.01:
            return self.format_issue(
                'SK1C-R05', self.INFO,
                f"Partner '{nm}' ({oID}): Box 5 = IS.interest_income ${interest:,.2f} × "
                f"{pct*100:.2f}% = ${box5:,.2f}. "
                f"IRC §702(a)(1): interest income is a separately stated item — "
                f"partners report it on their individual Schedule B.",
                'IRC §702(a)(1); Form 1065 Instructions (K-1 Box 5)',
                f"Verify Box 5 = ${box5:,.2f} for '{nm}'. "
                f"Source: IS.interest_income from bank interest accounts in COA.")

    def _rule_boxes_6_10_investment(self, owner: Dict):
        """
        SK1C-R06: Boxes 6-10 (dividends, royalties, capital gains) = $0.
        W&B holds real property, not investment securities. These boxes only become
        non-zero if property is sold during the tax year (triggering §1231, §1250 recapture).
        """
        agg = self._get_is()
        investment_keys = {
            'dividends': 'Box 6a (dividends)',
            'ordinary_dividends': 'Box 6a (dividends)',
            'royalties': 'Box 7 (royalties)',
            'short_term_cap_gain': 'Box 8 (ST cap gain)',
            'long_term_cap_gain': 'Box 9a (LT cap gain)',
            'sec1231_gain': 'Box 10 (§1231 gain)',
        }
        oID = owner.get('oID', '')
        for key, label in investment_keys.items():
            val = _safe_float(agg.get(key, 0))
            if abs(val) > 0.01:
                return self.format_issue(
                    'SK1C-R06', self.WARN,
                    f"Partner {oID}: IS shows {key} = ${val:,.2f} → {label} would be non-zero. "
                    f"W&B Group holds real property — investment income (dividends, royalties, "
                    f"capital gains) is unexpected unless a property was sold this year. "
                    f"If property was sold: §1231 gain (Box 10) and §1250 recapture (Box 9c) "
                    f"apply. Engage CPA for Form 4797 (property sales) computation.",
                    'IRC §702(a); IRC §1231; IRC §1250; Form 4797',
                    f"Review IS.{key}. If from property sale, run Form 4797. "
                    f"If data entry error, correct the COA account classification.")

    def _rule_box12_sec179(self, owner: Dict):
        """
        SK1C-R07: Box 12 (§179 deduction) — IRC §179; §469(j)(1).
        §179 from passive rental LLC is subject to passive activity limitations.
        IRC §469(j)(1): §179 deduction from passive activity limited by passive income.
        Suspended §179 carries forward to years with passive income from this activity.
        NOT eligible: buildings (§1250 real property), land (§179(b)(5)(B)).
        """
        agg   = self._get_is()
        sec179 = _safe_float(agg.get('depreciation_sec179', 0))
        pct    = _owner_pct(owner)
        box12  = round(sec179 * pct, 2)
        oID    = owner.get('oID', '')
        nm     = _owner_name(owner)
        if abs(box12) > 0.01:
            return self.format_issue(
                'SK1C-R07', self.INFO,
                f"Partner '{nm}' ({oID}): Box 12 §179 = ${box12:,.2f} "
                f"(IS.depreciation_sec179 ${sec179:,.2f} × {pct*100:.2f}%). "
                f"IRC §469(j)(1): §179 from passive rental LLC is limited by the "
                f"partner's passive income from this activity. "
                f"Excess §179 is suspended and carries forward. "
                f"§179 is NOT allowed on buildings (§179(b)(5)(B)) or land.",
                'IRC §179; §179(b)(5)(B); §469(j)(1); Form 4562',
                f"Inform '{nm}': verify passive income covers the ${box12:,.2f} §179 deduction. "
                f"If insufficient passive income, suspended §179 carries forward.")

    def _rule_box14_must_zero(self, owner: Dict):
        """
        SK1C-R09: Box 14a (SE earnings) MUST be $0 — IRC §1402(a)(1); §1402(a)(13).
        §1402(a)(1): 'net earnings from self-employment' explicitly EXCLUDES rentals
        from real estate unless the taxpayer provides substantial personal services
        (not applicable to a passive rental LLC).
        §1402(a)(13): limited partners not subject to SE tax on distributive share.
        Non-zero Box 14a incorrectly triggers ~15.3% SE tax on rental income.
        """
        agg  = self._get_is()
        se   = _safe_float(agg.get('se_income', agg.get('self_employment', 0)))
        oID  = owner.get('oID', '')
        if abs(se) > 0.01:
            pct = _owner_pct(owner)
            return self.format_issue(
                'SK1C-R09', self.ERROR,
                f"Partner {oID}: IS shows SE income = ${se:,.2f} → "
                f"Box 14a would be ${se*pct:,.2f} (non-zero). "
                f"Box 14a MUST be $0 for rental LLC. "
                f"IRC §1402(a)(1): rental income excluded from SE earnings. "
                f"IRC §1402(a)(13): limited partners not subject to SE tax. "
                f"Non-zero Box 14 triggers ~15.3% SE tax — a significant IRS penalty exposure.",
                'IRC §1402(a)(1); §1402(a)(13); Pub 541 (Partnerships)',
                "Remove any IS.se_income or self-employment mapping from the K-1 pipeline. "
                "Box 14a must be blank/$0 for ALL rental LLC partners.")

    def _rule_box2_basis_advisory(self, owner: Dict):
        """
        SK1C-R10: Box 2 is a loss — IRC §704(d) basis limitation advisory.
        IRC §704(d): a partner may not deduct a loss exceeding their adjusted basis.
        Outside basis = capital account + share of debt (Box K1 QNR).
        K-1 always reports the FULL allocated amount — basis check is on the
        partner's individual return (Form 6198, Schedule E).
        """
        net  = self._get_is_agg('net_rental')
        pct  = _owner_pct(owner)
        box2 = round(net * pct, 2)
        oID  = owner.get('oID', '')
        nm   = _owner_name(owner)
        if box2 < -0.01:
            return self.format_issue(
                'SK1C-R10', self.INFO,
                f"Partner '{nm}' ({oID}): Box 2 = ${box2:,.2f} (passive loss). "
                f"IRC §704(d): partner can deduct this loss only to the extent "
                f"of their adjusted outside basis (capital account + share of debt). "
                f"Outside basis must be computed on the partner's individual return — "
                f"not on the K-1. The K-1 reports the full allocated amount.",
                'IRC §704(d); IRC §469(b); Form 6198; Schedule E Instructions',
                f"Advisory only — no K-1 change needed. "
                f"Inform '{nm}' to verify their outside basis before claiming the loss.")


# ════════════════════════════════════════════════════════════════════════════
#  FORMSCHK1AGENT  (Tier 1 orchestrator)
# ════════════════════════════════════════════════════════════════════════════

class FormSchK1Agent(IRSFormsAgent):
    """
    Tier 1 orchestrator — runs section agents per partner.
    Produces one K-1 set of audit results per partner in llcOwners.
    Session state is keyed by partner oID.
    Books-First: Box 2 = IS.net_rental × partner.pct. Box 14a = $0.
    """

    _SECTION_ORDER = [
        AgentSchK1_PartnershipInfo,
        AgentSchK1_PartnerCapital,
        AgentSchK1_PassiveItems,
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
        owners        = self._get_owners()
        partner_state = {}
        overall_halt  = 0

        for owner in owners:
            oID = owner.get('oID', owner.get('ownerID', f"partner_{owners.index(owner)}"))
            nm  = _owner_name(owner)

            partner_issues = []
            partner_halt   = 0
            sections_for_partner = {}

            for agent in self._section_agents:
                agent.pass1_auto_fill(owner)
                p2 = agent.pass2_audit(owner)

                issues  = p2.get('issue_list', [])
                state   = p2.get('ready_state', self.GO)
                summary = (agent.pass5_summarize(owner)
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

            # Per-partner K-1 computed values
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
                'name':           nm,
                'pct':            pct,
                'state':          self.NEEDS_FIXING if partner_halt > 0 else self.GO,
                'halt_count':     partner_halt,
                'box2':           box2,
                'capital_ending': cap_end,
                'sections':       sections_for_partner,
            }
            overall_halt += partner_halt

        # Aggregate summary
        owners_list = self._get_owners()
        try:
            from ledger.stmtIS import stmtIS
            agg = stmtIS(self.llc).taxAggregates()
            net_rental = _safe_float(agg.get('net_rental', 0))
        except Exception:
            net_rental = 0.0
        names   = [_owner_name(o) for o in owners_list]
        pcts    = [_owner_pct(o) * 100 for o in owners_list]
        pct_str = ', '.join(f"{p:.2f}%" for p in pcts)

        overall_state = self.NEEDS_FIXING if overall_halt > 0 else self.GO

        session = {
            'tax_year':      self.tax_year,
            'last_run':      _now_iso(),
            'overall_state': overall_state,
            'partner_count': len(owners_list),
            'partners':      partner_state,
            'summary':       (
                f"{len(owners_list)} Schedule K-1s: {', '.join(names)}. "
                f"Box 2 allocations ({pct_str}): IS.net_rental ${net_rental:,.2f}. "
                f"Box 1=$0 (§469), Box 14a=$0 (§1402). Tax basis capital (Rev. Proc. 2020-13)."
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
        return (d / 'FormSchK1_session_state.json') if d else None

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
