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
#  Module-level GL capital helpers (importable by Sch_K1.py and any other
#  IRS form builder that needs per-partner capital account values).
#
#  These implement the COA Standard Mapping Practice (Golden Rule §1):
#    f40 (L2) — Credits to Acct.Equity.Owner.Capital.Funds per owner
#    f43 (L5) — Credits to Acct.Equity.Owner.Capital.Dist per owner
#    f44 (L6) — L2 + IS.net_rental×pct − L5  (IRC §705 formula)
# ────────────────────────────────────────────────────────────────────────────

# COA accounts for GL capital computation
_GL_CONTRIB_ACCTS = frozenset({
    'Acct.Equity.Owner.Capital.Funds',
    'Acct.Equity.Owner.Capital.Reinvestment',
})
_GL_DISTRIB_ACCTS = frozenset({
    'Acct.Equity.Owner.Capital.Dist',
})


def _parse_prop_owners_gl(raw) -> Dict[str, float]:
    """
    Parse propOwners into {oID: pct_decimal}.  Handles:
      dict          : {"o20250801_1": 100}      → {o20250801_1: 1.0}
      JSON string   : '{"020250801_1": 100}'    → {o20250801_1: 1.0}
      colon string  : "o20250801_1:100%"        → {o20250801_1: 1.0}
      null/empty    : None / ''                 → {}
    Integer percent > 1 divided by 100.
    Leading '0' instead of 'o' normalised (common oID typo).
    """
    if not raw:
        return {}
    import re as _re, json as _json

    def _norm(oid_str: str, pct_str: str):
        oid = str(oid_str).strip()
        if oid and not oid.startswith('o') and oid[0] == '0':
            oid = 'o' + oid[1:]   # "020250801_1" → "o20250801_1"
        elif oid and not oid.startswith('o') and oid[0].isdigit():
            oid = 'o' + oid
        try:
            v = float(str(pct_str).replace('%', '').strip())
            return oid, (v / 100.0 if v > 1.5 else v)
        except (TypeError, ValueError):
            return None

    result: Dict[str, float] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            pair = _norm(k, v)
            if pair:
                result[pair[0]] = pair[1]
    elif isinstance(raw, str):
        s = raw.strip()
        if s.startswith('{'):
            try:
                d = _json.loads(s)
                for k, v in d.items():
                    pair = _norm(k, v)
                    if pair:
                        result[pair[0]] = pair[1]
                return result
            except Exception:
                pass
        for part in s.split(','):
            part = part.strip()
            m = _re.match(r'^([^:]+):([0-9.]+)', part)
            if m:
                pair = _norm(m.group(1), m.group(2))
                if pair:
                    result[pair[0]] = pair[1]
    return result


_GL_ALL_LOADERS = ('llcAssets', 'llcExpRev', 'llcPayables', 'llcReceivables')


def _gl_load_all(llc) -> List[dict]:
    """Load all raw GL records from all four tables, filtered to current year."""
    import importlib
    yr       = str(getattr(llc, 'yr', '') or '')
    all_recs: List[dict] = []
    for name in _GL_ALL_LOADERS:
        try:
            mod  = importlib.import_module(f'ledger.{name}')
            cls  = getattr(mod, name)
            data = cls(llc).load()
            if yr:
                data = [r for r in data if str(r.get('dt', '')).startswith(yr)]
            all_recs.extend(data)
        except Exception:
            pass
    return all_recs


def gl_contributions(llc, oID: str) -> float:
    """
    Box L L2 (f40) — capital contributed during the year, GL-sourced.
    Credits to Acct.Equity.Owner.Capital.Funds / Reinvestment across ALL GL tables.
    Scans llcAssets + llcExpRev + llcPayables + llcReceivables — contributions
    may be recorded in any table depending on how they were entered.
    IRC §722: partner's initial outside basis = cash contributed.
    """
    total = 0.0
    for r in _gl_load_all(llc):
        if str(r.get('acct', '')).strip() not in _GL_CONTRIB_ACCTS:
            continue
        if str(r.get('aType', '')).strip().lower() not in ('credit', 'cr', 'c'):
            continue
        po  = _parse_prop_owners_gl(r.get('propOwners'))
        pct = po.get(oID, 0.0)
        if pct > 0:
            try:
                total += float(r.get('amt', 0) or 0) * pct
            except (TypeError, ValueError):
                pass
    return round(total, 2)


def gl_distributions(llc, oID: str) -> float:
    """
    Box L L5 (f43) — withdrawals and distributions, GL-sourced.
    Credits to Acct.Equity.Owner.Capital.Dist across ALL GL tables.
    NOT equal to allocated income — these are actual cash payments to partners.
    """
    total = 0.0
    for r in _gl_load_all(llc):
        if str(r.get('acct', '')).strip() not in _GL_DISTRIB_ACCTS:
            continue
        if str(r.get('aType', '')).strip().lower() not in ('credit', 'cr', 'c'):
            continue
        po  = _parse_prop_owners_gl(r.get('propOwners'))
        pct = po.get(oID, 0.0)
        if pct > 0:
            try:
                total += float(r.get('amt', 0) or 0) * pct
            except (TypeError, ValueError):
                pass
    return round(total, 2)


def gl_ending_capital(llc, oID: str, owner_pct: float,
                      net_rental: float = None) -> float:
    """
    Box L L6 (f44) — ending capital account, GL-sourced (IRC §705).
    Formula: L2(contributions) + L3(IS.net_rental × pct) − L5(distributions).
    """
    if net_rental is None:
        try:
            from ledger.stmtIS import stmtIS
            net_rental = float(stmtIS(llc).taxAggregates().get('net_rental', 0))
        except Exception:
            net_rental = 0.0
    contrib = gl_contributions(llc, oID)
    distrib = gl_distributions(llc, oID)
    income  = round(net_rental * owner_pct, 2)
    return round(contrib + income - distrib, 2)


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
    """
    Common base for all Schedule K-1 section agents (per-partner).

    ──────────────────────────────────────────────────────────────────────────
    GOLDEN RULE — BROADER KNOWLEDGE INJECTION (applies to every field in
    every section agent, in every IRS form agent in this codebase):
    ──────────────────────────────────────────────────────────────────────────

    1. COA STANDARD MAPPING PRACTICE (Books-First, IRC §446/703):
       For every IRS form field, the section agent MUST resolve the mapping
       from COA accounts → IRS field value. Never leave a field unresolved
       ("Cplx" / "TODO" / $0 default) without explicit IRS reasoning.
       Standard practice:
         a. Identify which COA account(s) are the source for this field.
         b. State the double-entry direction (Debit/Credit normal balance).
         c. Apply the pct allocation (partner.pct) when the field is per-partner.
         d. Cross-reference the IRS instruction for the line item.
       All financial values must originate from the BOOKS (GL/IS/BS), never
       from another IRS form (Books-First rule, IRC §446/703; CLAUDE.md §1.1).

    2. CHECKBOX FIELDS — BINARY KNOWLEDGE DECISION:
       Every checkbox field is a binary Check / NoCheck decision.
       a. Research the CONDITION that makes "Check" correct (IRS instruction,
          IRC section, or operational fact about W&B Group).
       b. If the condition is NOT met → NoCheck (default). Never leave
          a checkbox as "unknown" — absence of the condition = NoCheck.
       c. For YES/NO checkbox pairs: exactly one is Check, the other is NoCheck.
          Never check both; never leave both blank.
       d. Document the condition explicitly in the rule docstring so future
          reviewers can verify without re-reading the IRS instructions.

    These two rules are the standard for ALL section agents.  Violations
    (punting, leaving fields unresolved, skipping checkboxes) are bugs.
    ──────────────────────────────────────────────────────────────────────────
    """

    LABEL        = ''
    AGENT_KEY    = ''
    LOGICAL_PREFIXES: List[str] = []

    # COA accounts that represent owner capital contributions (Box L L2)
    _CONTRIB_ACCTS = frozenset({
        'Acct.Equity.Owner.Capital.Funds',
        'Acct.Equity.Owner.Capital.Reinvestment',
    })
    # COA accounts that represent owner distributions/withdrawals (Box L L5)
    _DISTRIB_ACCTS = frozenset({
        'Acct.Equity.Owner.Capital.Dist',
    })

    def __init__(self, llc, tax_year: int):
        super().__init__(llc, tax_year)
        self._is_data      = None
        self._profile      = None
        self._raw_assets   = None   # lazy-loaded raw llcAssets records

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

    # ── GL-sourced capital helpers (Books-First, IRC §446/703) ───────────────

    # ── GL capital helpers — delegate to module-level functions ─────────────

    def _gl_contributions(self, oID: str) -> float:
        """Box L L2 (f40) — GL-sourced. See module-level gl_contributions()."""
        return gl_contributions(self.llc, oID)

    def _gl_distributions(self, oID: str) -> float:
        """Box L L5 (f43) — GL-sourced. See module-level gl_distributions()."""
        return gl_distributions(self.llc, oID)

    def _gl_ending_capital(self, oID: str, owner_pct: float) -> float:
        """Box L L6 (f44) — GL-sourced. See module-level gl_ending_capital()."""
        net_rental = self._get_is_agg('net_rental')
        return gl_ending_capital(self.llc, oID, owner_pct, net_rental=net_rental)

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
            self._rule_header_checkboxes,
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

        K-1 header fields f1–f5:
          f1 = beginning month (MM, e.g. '01' for Jan)
          f2 = beginning day   (DD, e.g. '01' for 1st)
          f3 = ending month    (MM, e.g. '12' for Dec)
          f4 = ending day      (DD, e.g. '31' for 31st)
          f5 = 2-digit tax year (e.g. '25' for 2025)

        IRC §706(b)(1)(B): partnership must use the same tax year as its majority
        partners unless it can establish a valid business purpose for a different year.
        For W&B Group: majority partner (96%) uses a calendar year → LLC must use
        calendar year. Expected values: f1=01, f2=01, f3=12, f4=31, f5=25.
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
                f"The 2-digit tax year (e.g. '25') is required for K-1 header field f5. "
                f"IRC §441: taxable income is computed for the annual accounting period. "
                f"Expected K-1 header: f1=01, f2=01, f3=12, f4=31, f5=25 (calendar year 2025).",
                'IRC §441; IRC §706; Form 1065 Instructions (K-1 header fields f1–f5)',
                "Set tax_year='25' (or '2025') in llcProfile_WBGroupLLC.json → F1065 section.")

        jan = dfrom.lower().startswith('jan') or dfrom.startswith('01')
        dec = dto.lower().startswith('dec') or dto.startswith('12')
        if dfrom and dto and (not jan or not dec):
            return self.format_issue(
                'SK1A-R01', self.WARN,
                f"Partner {oID}: Tax year appears non-calendar (date_from='{dfrom}', "
                f"date_to='{dto}'). "
                f"IRC §706(b)(1)(B): W&B Group must use calendar year because the majority "
                f"partner holds 96% and uses a calendar year. Non-calendar year requires "
                f"IRS approval or a §444 election. "
                f"Expected: f1=01, f2=01, f3=12, f4=31, f5=25.",
                'IRC §441; IRC §706(b)(1)(B); IRC §444',
                "Verify the LLC's accounting period. Calendar year → correct date_from to "
                "'Jan. 01' and date_to to 'Dec. 31' in llcProfile_WBGroupLLC.json.")

        # All good — show what's in the fields
        return self.format_issue(
            'SK1A-R01', self.INFO,
            f"Partner {oID}: Tax year header OK. "
            f"K-1 fields: f1=01 f2=01 (begin Jan 1) | f3=12 f4=31 (end Dec 31) | "
            f"f5={str(ty)[-2:]} (tax year). "
            f"IRC §441 calendar year confirmed for W&B Group LLC.",
            'IRC §441; IRC §706(b)(1)(B)',
            "No action needed — tax year header fields f1–f5 are correctly populated.")

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

    def _rule_header_checkboxes(self, owner: Dict):
        """
        SK1A-R04a: Header checkboxes f6 (Final K-1) and f7 (Amended K-1).

        FIELD MAP:
          f6 = 'Final K-1'   checkbox — check ONLY in the year a partner exits
                              the LLC or the LLC dissolves.
          f7 = 'Amended K-1' checkbox — check ONLY when issuing a correction to
                              a previously filed K-1 for this partner and tax year.

        BINARY KNOWLEDGE DECISION (Golden Rule §2 — Checkbox Practice):
          Condition for f6 (Check): partner is leaving LLC OR LLC is dissolving this year.
          Condition for f7 (Check): a K-1 was previously filed for this partner/year
                                    and this document corrects it.
          DEFAULT: BOTH unchecked (NoCheck) — this is correct for an ongoing LLC
          in its FIRST tax year with NO partner exits and NO prior filing.

        For W&B Group 2025:
          f6 NoCheck — LLC formed 2025, all partners remain, LLC is ongoing.
          f7 NoCheck — 2025 is the FIRST K-1 issued; no prior filing to amend.
          NEITHER checkbox is required for an ongoing, first-year, non-amended K-1.
          The section agent in SK1A-R06/R07 warns if either flag is incorrectly set.
        """
        pr         = self._get_profile()
        f1065      = pr.get('F1065', {})
        is_final   = f1065.get('is_final_k1', False)
        is_amended = f1065.get('is_amended_k1', False)
        oID        = owner.get('oID', '')
        return self.format_issue(
            'SK1A-R04a', self.INFO,
            f"Partner {oID}: f6 Final K-1 = {'CHECK' if is_final else 'NoCheck (correct for ongoing LLC)'}. "
            f"f7 Amended K-1 = {'CHECK ⚠ verify prior filing' if is_amended else 'NoCheck (correct — first K-1 for 2025)'}. "
            f"Both NoCheck is the CORRECT default for an ongoing, first-year LLC "
            f"with no partner exits and no prior filing to correct. "
            f"There is NO requirement that one of f6/f7 must be checked — they are "
            f"situational flags only (Form 1065 Instructions, K-1 header).",
            'Form 1065 Instructions (K-1 header — Final K-1, Amended K-1)',
            "No action needed. If a partner exits in a future year, set is_final_k1=True "
            "for that partner. If issuing a corrected K-1, set is_amended_k1=True.")

    def _rule_irs_center(self, owner: Dict):
        """
        SK1A-R04b: IRS Service Center (K-1 field f13, Line C).

        FIELD MAP:
          f8  = Partnership EIN (Line A)
          f9  = Partnership name (Line B — name portion)
          f10 = Partnership street address (Line B — street, e.g. '177 Kingsway Dr')
          f11 = PTP checkbox (Line D)
          f12 = Partnership city/state/ZIP (Line B — remainder, e.g. 'Wimberley, Tx 78676')
          f13 = IRS Service Center where Form 1065 was FILED (Line C)

        IRS Service Center (f13, Line C) tells each partner WHERE the partnership
        return was filed so they can direct correspondence. The value depends on
        HOW W&B Group filed Form 1065:

          E-filed returns  → 'E-File'  (most modern filers; recommended)
          Paper returns    → filing center by LLC's HOME STATE (not property state):
            Texas LLC (home state) → 'Ogden, UT 84201' (IRS 2025 Partnership Instructions)

        NOTE: f10 is the LLC's registered STREET ADDRESS — this is CORRECT data.
        f13 (IRS center) is a SEPARATE field — it is NOT the LLC's address.
        Do not confuse f10 (LLC street address) with f13 (IRS Service Center city).
        The IRS center is determined by FILING METHOD, not the LLC's physical location.
        """
        pr     = self._get_profile()
        center = str(pr.get('F1065', {}).get('irs_center', '') or '').strip()
        oID    = owner.get('oID', '')
        if not center:
            return self.format_issue(
                'SK1A-R04b', self.WARN,
                f"Partner {oID}: K-1 f13 (Line C, IRS Service Center) is BLANK. "
                f"This field must show WHERE Form 1065 was filed. "
                f"For e-filed returns (most filers) → set to 'E-File'. "
                f"For paper returns from a Texas LLC → set to 'Ogden, UT 84201'. "
                f"Field map: f10=LLC street address (correct), f12=LLC city/state/zip (correct), "
                f"f13=IRS Service Center (blank — needs to be set). "
                f"These are SEPARATE fields. f13 is informational for partners.",
                'Form 1065 Instructions (K-1 Line C / field f13)',
                "Set F1065.irs_center in llcProfile_WBGroupLLC.json → 'E-File' for e-filers.")
        else:
            return self.format_issue(
                'SK1A-R04b', self.INFO,
                f"Partner {oID}: K-1 f13 IRS Service Center = '{center}'. "
                f"f10=LLC street address, f12=LLC city/state/zip (both correct per Line B). "
                f"f13=IRS center (Line C) — verify this matches how Form 1065 was filed. "
                f"E-filed → 'E-File'. Paper Texas LLC → 'Ogden, UT 84201'.",
                'Form 1065 Instructions (K-1 Line C)',
                "No action if filing method matches. Update F1065.irs_center in llcProfile if wrong.")

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
            lambda o=owner: self._rule_partner_id_fields(o),
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
        oID     = owner.get('oID', '')
        contrib = self._gl_contributions(oID)
        distrib = self._gl_distributions(oID)
        ending  = self._gl_ending_capital(oID, pct)
        nm      = _owner_name(owner)
        return (f"Capital (Box L): {nm} — "
                f"Beg=$0 + Contrib(GL)=${contrib:,.2f} + Box2=${box2:,.2f} "
                f"− Distrib(GL)=${distrib:,.2f} = Ending=${ending:,.2f} (tax basis).")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_partner_id_fields(self, owner: Dict):
        """
        SK1B-R00: Partner identification fields coverage — Form 1065 K-1 Instructions Lines E/F.

        FIELD MAP (Part II — per-partner identification):
          f14 = Line G checkbox: GP / LLC member-manager
          f15 = Line G checkbox: LP / other LLC member
          f16 = Line H1 checkbox: Domestic partner
          f17 = Line H1 checkbox: Foreign partner
          f18 = Line H2 checkbox: Disregarded entity (DE) — NOT for individual humans;
                 check ONLY if partner is an SMLLC or grantor trust without corp election.
                 For W&B Group: all partners are individual humans → f18 = NoCheck (correct).
          f19 = Line E: Partner's identifying number (SSN or EIN)
                 CRITICAL: f19 must contain the PARTNER'S SSN, NOT the LLC's EIN.
                 Source: llcOwners[partner].SSN formatted as XXX-XX-XXXX.
                 IRC §6109: TIN is required on every K-1. Wrong TIN = IRS matching failure.
          f20 = Line F: Partner's name (from llcOwners[partner].nm[0])
          f21 = Line F: Partner's address (from llcOwners[partner].addr)
          f22 = Line I checkbox: Partner is IRA/Roth/other retirement plan

        NOTE: f12 is the LLC's city/state/ZIP (Part I, Line B — NOT the partner's SSN).
              f19 is the partner's SSN/EIN (Part II, Line E).
              f18 (Disregarded Entity) applies ONLY to entity partners (SMLLC, trust).
              Multi-member LLCs are NEVER disregarded entities — only SMLLCs can be DREs.
              Individual human partners are NEVER DREs → f18 NoCheck for all W&B partners.
        """
        import re as _re
        ssn  = str(owner.get('SSN', owner.get('ssn', owner.get('tin', '')))).replace('-','').strip()
        nm   = _owner_name(owner)
        oID  = owner.get('oID', '')
        addr = str(owner.get('addr', '') or '').strip()

        has_ssn = len(ssn) == 9 and ssn.isdigit()
        if not has_ssn:
            return self.format_issue(
                'SK1B-R00', self.ERROR,
                f"Partner '{nm}' ({oID}): SSN missing or invalid in llcOwners (f19 = Line E). "
                f"Current SSN field: '{ssn}'. "
                f"f19 (Line E) must contain the partner's 9-digit SSN. "
                f"IRC §6109: TIN required on every K-1. "
                f"IRS matching fails without a valid TIN → CP2000 notices and §6721/§6722 penalties. "
                f"NOTE: f12 = LLC city/state/ZIP (Part I, Line B). f19 = PARTNER SSN (Part II, Line E). "
                f"These are DIFFERENT fields. f18 (Disregarded Entity) = NoCheck for individuals.",
                'IRC §6109; Treas. Reg. §301.6109-1; Form 1065 Instructions (K-1 Line E)',
                f"Add SSN to llcOwners for '{oID}' in llcOwners_WBGroupLLC.json. "
                f"Format: 'SSN': 'XXX-XX-XXXX'.")

        # Check f21 address includes a 2-letter state abbreviation (e.g. TX)
        has_state = bool(_re.search(r',\s*[A-Z]{2}\b', addr))
        if addr and not has_state:
            return self.format_issue(
                'SK1B-R00', self.WARN,
                f"Partner '{nm}' ({oID}): f21 (Line F, partner address) is missing the "
                f"state abbreviation. Current value: '{addr}'. "
                f"IRS K-1 instructions require full address: street, city, 2-letter STATE, ZIP. "
                f"Example: '177 Kingsway Dr, Wimberley, TX 78676'. "
                f"f19 (SSN): {'*'*3+'-'+'*'*2+'-'+ssn[-4:]} ✓  "
                f"f20 (name): '{nm}' ✓  "
                f"f18 (DE): NoCheck ✓ (individual partner). "
                f"f12 = LLC city/state/ZIP (Part I). f19 = PARTNER SSN (Part II). Separate fields.",
                'Form 1065 Instructions (K-1 Line F — partner address)',
                f"Update 'addr' for '{oID}' in llcOwners_WBGroupLLC.json to include state: "
                f"e.g. 'addr': '177 Kingsway Dr, Wimberley, TX 78676'.")

        return self.format_issue(
            'SK1B-R00', self.INFO,
            f"Partner '{nm}' ({oID}): identification fields OK. "
            f"f19 (Line E, partner SSN): {'*'*3+'-'+'*'*2+'-'+ssn[-4:]} (9-digit SSN present). "
            f"f20 (Line F, partner name): '{nm}'. "
            f"f21 (Line F, partner address): '{addr or '(not set)'}'. "
            f"f18 (Line H2, Disregarded Entity): NoCheck — correct for individual human partners. "
            f"f22 (Line I, Retirement Plan): NoCheck. "
            f"f12 = LLC city/state/ZIP (Part I Line B) — separate field, not partner address.",
            'IRC §6109; Form 1065 Instructions (K-1 Lines E, F, H2)',
            f"Verify SSN matches '{nm}' Form 1040. Confirm f21 address is complete "
            f"(street, city, state, ZIP).")

    def _rule_partner_type(self, owner: Dict):
        """
        SK1B-R01: Partner type classification — IRC §761(b); Form 1065 Instructions Line G/H.

        K-1 checkboxes:
          f14 = GP / LLC member-manager  (checked if partner participates in management)
          f15 = LP / other LLC member    (checked if partner is passive member only)
          f16 = Domestic partner         (checked if US person — SSN present)
          f17 = Foreign partner          (checked if non-US person)
          f18 = Disregarded entity       (checked if partner is a single-member LLC or
                                          grantor trust that hasn't elected corp treatment)
          f21 = Partner's entity type    (Individual | C-Corp | S-Corp | Partnership | Trust/Estate)

        IRC §761(b): a "general partner" (or LLC member-manager) is actively involved in
        management. An LP (or other LLC member) has no management rights and is passive.

        CRITICAL for W&B Group — W&B is a MEMBER-MANAGED LLC:
          • Francis (status='Manager'): participates in management → f14 (GP/manager) checked
          • Other members (passive, status≠Manager): → f15 (LP/other member) checked
          • ALL members are Domestic (US persons with SSNs) → f16 checked
          • NO member is a disregarded entity (all are individuals) → f18 left blank

        ENTITY TYPE (f21 advisory): The K-1 form has a field identifying what kind of entity
        the partner is. For W&B Group: all partners are Individuals. This affects how each
        partner reports K-1 income on their own return:
          Individual  → Schedule E Part II (passive income from rental)
          C-Corp      → Form 1120 (partnership income flows to corp income)
          S-Corp      → Form 1120S Schedule K (separate rules for S-corps as partners)
          Trust/Estate → Form 1041 Schedule K-1 (complex basis rules)
        """
        status   = str(owner.get('status', '') or '').strip()
        mem_type = str(owner.get('memType', owner.get('entityType', '')) or '').strip()
        oID      = owner.get('oID', '')
        nm       = _owner_name(owner)
        ssn      = str(owner.get('SSN', owner.get('ssn', ''))).replace('-', '').strip()
        is_manager = 'manager' in status.lower()
        has_ssn    = len(ssn) == 9 and ssn.isdigit()

        if not status:
            return self.format_issue(
                'SK1B-R01', self.WARN,
                f"Partner '{nm}' ({oID}): status field is blank. "
                f"Cannot determine whether to check f14 (GP/manager) or f15 (LP/member). "
                f"IRC §761(b): member-managers check f14; passive members check f15. "
                f"For W&B: Francis (management role) → f14. Alexandra, Nicola (passive) → f15. "
                f"All members are Domestic Individuals → f16 checked, f18 blank.",
                'IRC §761(b); IRC §1402; Form 1065 Instructions (K-1 Lines G, H1, H2)',
                f"Set status='Manager' for managing members, or 'Member'/'non_active member' "
                f"for passive members in llcOwners for '{oID}'.")

        type_label = 'GP/member-manager (f14)' if is_manager else 'LP/other LLC member (f15)'
        entity_label = 'Individual' if has_ssn else (mem_type or 'unknown')
        return self.format_issue(
            'SK1B-R01', self.INFO,
            f"Partner '{nm}' ({oID}): {type_label} — status='{status}'. "
            f"Entity type: {entity_label} (reports Box 2 on Schedule E Part II). "
            f"f16 Domestic checked (SSN on file). f18 DE: blank (individual, not an LLC). "
            f"IRC §761(b): member-managed LLC — managers check f14, passive members check f15.",
            'IRC §761(b); IRC §1402(a)(13); Form 1065 Instructions (K-1 Lines G, H1, H2)',
            "Verify checkboxes match partner role. Passive members who become managers "
            "(or vice versa) must update K-1 in the year the role changes.")

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
        SK1B-R04: Ownership percentage — IRC §704(b), §706; Form 1065 Instructions Box J.

        Box J fields (f23–f28):
          f23 = Profit %  beginning of year    f24 = Profit %  end of year
          f25 = Loss %    beginning of year    f26 = Loss %    end of year
          f27 = Capital % beginning of year    f28 = Capital % end of year

        IRS K-1 Instructions: "If there was no change in the partners' shares of profit,
        loss, and capital during the year, enter the end-of-year percentages in both
        beginning and ending columns (you may leave the beginning column blank)."

        For W&B Group 2025:
          • Ownership did NOT change during the year → beginning = ending (no change rule).
          • All three allocations (profit/loss/capital) use the SAME pct for W&B:
            Francis=96%, Alexandra=2%, Nicola=2%.
          • IRS requires all three rows sum to 100% across all partners.
          • IRC §704(b): allocations must have substantial economic effect (SEE).
            Using the same pct for profit/loss/capital is the simplest SEE-compliant structure.
        """
        pct  = _owner_pct(owner)
        oID  = owner.get('oID', '')
        nm   = _owner_name(owner)
        if pct < 0.001:
            return self.format_issue(
                'SK1B-R04', self.ERROR,
                f"Partner '{nm}' ({oID}): ownership percentage is {pct:.4f} (zero or missing). "
                f"IRC §704(b): all K-1 Box amounts (Box 2, Box 5, Box L) = $0 if pct = 0, "
                f"omitting this partner's entire share of rental income/loss from their return. "
                f"Box J (f23–f28) requires Profit/Loss/Capital % each summing to 100%.",
                'IRC §704(b); IRC §706; Form 1065 Instructions (K-1 Box J f23–f28)',
                f"Set pct for partner '{oID}' in llcOwners. "
                f"Sum of all partners' pct must equal 1.0 (100%).")
        return self.format_issue(
            'SK1B-R04', self.INFO,
            f"Partner '{nm}' ({oID}): Box J = {pct*100:.1f}% for all three rows "
            f"(Profit/Loss/Capital). "
            f"Beginning = Ending (no ownership change during 2025). "
            f"IRC §704(b) SEE satisfied: uniform pct allocation matches Operating Agreement.",
            'IRC §704(b); Form 1065 Instructions (K-1 Box J)',
            "No action needed. If ownership % changes mid-year in a future year, "
            "update beginning and ending percentages separately in llcOwners.")

    def _rule_box_k1_liabilities(self, owner: Dict):
        """
        SK1B-R05: Box K1 — partner's share of liabilities — IRC §752; Treas. Reg. §1.752-3.

        Box K1 fields (f31–f36):
          f31 = Nonrecourse beginning     f32 = Nonrecourse end
          f33 = QNR (Qualified Nonrecourse Financing) beginning    f34 = QNR end
          f35 = Recourse beginning        f36 = Recourse end

        THREE LIABILITY CATEGORIES (IRC §752; Treas. Reg. §1.752-2/3):

        1. NONRECOURSE (f31/f32): lender's ONLY recourse is the property. No personal
           guarantees by any partner. Partners share this based on profit % (Treas. Reg.
           §1.752-3(a)(3)). HOWEVER: for real property with commercial mortgage, this is
           usually classified as QNR (see below), not plain nonrecourse.

        2. QUALIFIED NONRECOURSE FINANCING / QNR (f33/f34): [IRC §465(b)(6)]
           Nonrecourse debt FROM A QUALIFIED PERSON (bank/savings institution/government
           agency) secured by real property used in the activity. For W&B Group, any
           commercial mortgage from a bank on the rental property qualifies as QNR.
           QNR increases each partner's AT-RISK AMOUNT, allowing them to deduct their
           allocated losses up to the amount of their at-risk basis.
           Formula: QNR end-of-year = BS.mortgage × partner.pct

        3. RECOURSE (f35/f36): partner personally guarantees repayment. Very unusual
           for commercial RE. In W&B Group's situation: $0 (no personal guarantees).

        BEGINNING-OF-YEAR VALUES (f31/f33/f35):
           FIRST YEAR LLC (formed 2025): property was purchased DURING the year.
           Therefore ALL beginning-of-year liabilities = $0.
           The debt only arose at the property acquisition closing date.

        WHY QNR MATTERS (partner outside basis):
           Each partner's outside basis = capital contribution + QNR share + prior income − distributions.
           Zero QNR = lower outside basis = possible loss limitation under §704(d).
        """
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
                f"Partner '{nm}' ({oID}): Box K1 liabilities — "
                f"BOY (f31/f33/f35) = $0/$0/$0 (first year, no debt at Jan 1). "
                f"EOY QNR (f34) = BS.mortgage ${mortgage:,.2f} × {pct*100:.2f}% = ${partner_qnr:,.2f}. "
                f"Classification: QNR (§465(b)(6)) — commercial mortgage, real-property "
                f"collateral, no personal guarantees. "
                f"This QNR share increases '{nm}'s at-risk amount by ${partner_qnr:,.2f}, "
                f"enabling deduction of their proportionate share of rental losses.",
                'IRC §752; §465(b)(6); Treas. Reg. §1.752-3(a)(3)',
                f"Confirm mortgage is from a commercial lender (bank/S&L/govt agency) and "
                f"no partner personally guaranteed repayment. If so, classify as QNR. "
                f"f34 = ${partner_qnr:,.2f}. f31/f33/f35 (BOY) = $0 (first year).")
        else:
            return self.format_issue(
                'SK1B-R05', self.WARN,
                f"Partner '{nm}' ({oID}): Box K1 QNR = $0 (no mortgage found in BS). "
                f"BOY fields f31/f33/f35 = $0 (first year, correct). "
                f"EOY fields f32/f34/f36 = $0. "
                f"If the LLC has a mortgage, verify stmtBS_Tax.taxAggregates() returns "
                f"a 'mortgage' key, and that the mortgage balance is recorded in llcAssets "
                f"as a liability transaction. "
                f"Partners' outside at-risk basis is understated without the QNR allocation.",
                'IRC §752; §465(b)(6); Treas. Reg. §1.752-3',
                "Check llcAssets for mortgage liability entries. "
                "Ensure BS.taxAggregates()['mortgage'] returns the correct year-end balance.")

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
        SK1B-R07: Box L capital account analysis — IRC §705; §722; Rev. Proc. 2020-13.

        Box L fields (f39–f46):
          f39 = L1: Beginning capital account (Jan 1)
          f40 = L2: Capital contributed during year (cash + property at FMV)
          f41 = L3: Current year net income (loss)  [= IS.net_rental × pct]
          f42 = L4: Other increases (unusual — blank for W&B)
          f43 = L5: Withdrawals and distributions   [actual cash out to partner]
          f44 = L6: Ending capital account          [L1 + L2 + L3 + L4 − L5]
          f45 = Tax basis method checkbox            [MUST be checked — mandatory 2020+]
          f46 = Non-tax basis checkbox               [leave blank]

        COA STANDARD MAPPING (Broader Knowledge Injection / Books-First):

          f40 (L2 — contributions):
            Source: GL Credits to Acct.Equity.Owner.Capital.Funds (acctID 3010)
                    + GL Credits to Acct.Equity.Owner.Capital.Reinvestment (acctID 3025)
            Pattern: DR Acct.Cash.Bank / Acct.Cash.Escrow → CR Acct.Equity.Owner.Capital.Funds
            Per-partner: propOwners dict in each GL record, weighted by oID.
            IRC §722: partner's outside basis = cash contributed.

          f44 (L6 — ending capital):
            Formula: L1($0) + L2(GL contributions) + L3(IS.net_rental × pct)
                     + L4($0) − L5(GL distributions)
            Per-partner: _gl_ending_capital(oID, pct).
            IRC §705: partner's basis adjusted for contributions, income, distributions.

        CHECKBOXES (Binary Knowledge Decisions per Golden Rule):
          f45 (Tax basis — Check):   Rev. Proc. 2020-13 / TD 9902 mandate tax basis
                                     for ALL partnerships 2020+. ALWAYS Check.
          f46 (Non-tax basis — NoCheck): All other methods eliminated for 2020+. ALWAYS NoCheck.

        MANDATORY TAX BASIS METHOD (Rev. Proc. 2020-13; TD 9902):
           f45 MUST be checked. IRS automated systems validate this.

        IRC §705 FORMULA (tax basis capital account):
           Ending = Beginning + Contributions + Allocated Net Income + Other − Distributions

        NOTE: L3 (current income) ≠ L5 (distributions). Do NOT set distributions =
           net_income × pct. Distributions are actual cash paid out; income is allocated
           on paper. A common bookkeeping error to watch for.
        """
        pct     = _owner_pct(owner)
        net     = self._get_is_agg('net_rental')
        box2    = round(net * pct, 2)
        oID     = owner.get('oID', '')
        nm      = _owner_name(owner)

        # GL-sourced values (Books-First, IRC §446/703)
        contrib = self._gl_contributions(oID)
        distrib = self._gl_distributions(oID)
        ending  = self._gl_ending_capital(oID, pct)

        # Cross-check: GL contributions vs BS property acquisition cost.
        # If the LLC acquired real property entirely with partner cash (no mortgage),
        # total GL contributions should approximate total BS property value.
        # A large gap means contribution entries are missing — outside basis understated.
        _gap_note = ''
        try:
            from ledger.stmtBS import stmtBS_Tax
            bs_agg   = stmtBS_Tax(self.llc).taxAggregates()
            bldg     = _safe_float(bs_agg.get('buildings', 0))
            land     = _safe_float(bs_agg.get('land', 0))
            mortgage = _safe_float(bs_agg.get('mortgage', 0))
            total_prop = bldg + land
            total_contrib_all = round(contrib / pct, 2) if pct > 0.001 else contrib
            gap = total_prop - (total_contrib_all + mortgage)
            if gap > 5_000:
                _gap_note = (
                    f" ⚠ CONTRIBUTION MISMATCH: BS property ${total_prop:,.2f} "
                    f"(bldg ${bldg:,.2f} + land ${land:,.2f}) vs "
                    f"total GL contributions ${total_contrib_all:,.2f} + mortgage ${mortgage:,.2f}. "
                    f"Unexplained gap ≈ ${gap:,.2f}. "
                    f"Likely cause: property acquisition journal entries were not recorded as "
                    f"Credits to Acct.Equity.Owner.Capital.Funds. "
                    f"IRC §722: understated contributions = understated outside basis for all partners."
                )
        except Exception:
            pass

        if contrib == 0:
            return self.format_issue(
                'SK1B-R07', self.WARN,
                f"Partner '{nm}' ({oID}): Box L f40 (L2) contributions = $0 from GL. "
                f"GL source: Credits to Acct.Equity.Owner.Capital.Funds in llcAssets "
                f"(DR Cash → CR Equity.Capital.Funds pattern, weighted by propOwners). "
                f"If '{nm}' contributed cash at LLC formation (2025), record the transaction "
                f"in llcAssets with acct=Acct.Equity.Owner.Capital.Funds, aType=Credit, "
                f"propOwners={{'{oID}': pct×100}}. "
                f"IRC §722: missing contributions = understated outside basis for '{nm}'. "
                f"Box L: L1=$0 | L2(f40)=$0 ⚠ | L3(f41)=${box2:,.2f} | L5(f43)=${distrib:,.2f} | "
                f"L6(f44)=${ending:,.2f}. "
                f"f45 Tax basis: Check (Rev. Proc. 2020-13). f46 Non-tax basis: NoCheck."
                + _gap_note,
                'IRC §705; §722; Rev. Proc. 2020-13; Form 1065 Instructions (K-1 Box L)',
                f"Record contribution transaction in llcAssets for '{oID}'. "
                f"Verify distributions reflect actual cash paid out (not income allocation).")
        else:
            return self.format_issue(
                'SK1B-R07', self.WARN if _gap_note else self.INFO,
                f"Partner '{nm}' ({oID}) Box L (tax basis, GL-sourced): "
                f"L1(f39)=$0 + L2(f40)=${contrib:,.2f} + L3(f41)=${box2:,.2f} "
                f"− L5(f43)=${distrib:,.2f} = L6(f44)=${ending:,.2f}. "
                f"IRC §705 formula. "
                f"f40: GL Credits → Acct.Equity.Owner.Capital.Funds (propOwners-weighted). "
                f"f41 (L3): IS.net_rental × pct = ${box2:,.2f} — MUST be filled in PDF "
                f"(regenerate if blank). "
                f"f44 (L6): computed = ${ending:,.2f} — verify PDF shows this value. "
                f"f45 Tax basis: Check (Rev. Proc. 2020-13). f46 Non-tax basis: NoCheck."
                + _gap_note,
                'IRC §705; Rev. Proc. 2020-13; Form 1065 Instructions (K-1 Box L)',
                f"Verify Box L in PDF for '{nm}': "
                f"L2=${contrib:,.2f}, L3=${box2:,.2f}, L5=${distrib:,.2f}, L6=${ending:,.2f}. "
                + (f"INVESTIGATE contribution gap: record missing capital entries in llcAssets."
                   if _gap_note else
                   f"Source: GL Credits to Acct.Equity.Owner.Capital.Funds weighted by propOwners."))

    def _rule_sec704c(self, owner: Dict):
        """
        SK1B-R08: §704(c) allocated gain — IRC §704(c); Treas. Reg. §1.704-3.

        §704(c) applies when a partner contributes PROPERTY with built-in gain/loss
        (property FMV ≠ tax basis at contribution). Line N discloses this amount.
        For cash-only contributions → §704(c) = $0 → Line N = blank.

        COA STANDARD MAPPING:
          f40 (contributions) sourced from GL Credits to Acct.Equity.Owner.Capital.Funds.
          Cash contributions: counterpart is Acct.Cash.Bank or Acct.Cash.Escrow → §704(c) = $0.
          Property contributions: counterpart is Acct.Asset.* → §704(c) may apply.

        CHECKBOX (Line N): This is an amount field, not a checkbox.  §704(c) = $0 for
        W&B Group (all contributions are cash from bank/escrow, no property contributed).
        """
        oID    = owner.get('oID', '')
        nm     = _owner_name(owner)
        contrib = self._gl_contributions(oID)
        if contrib > 0:
            return self.format_issue(
                'SK1B-R08', self.INFO,
                f"Partner '{nm}' ({oID}): GL contributions = ${contrib:,.2f} "
                f"(Acct.Equity.Owner.Capital.Funds Credits, propOwners-weighted). "
                f"IRC §704(c): if all contributions were cash (counterpart = Acct.Cash.*), "
                f"Line N (§704(c) gain/loss) = $0. "
                f"If property was contributed (not cash), CPA must compute built-in "
                f"gain/loss under Treas. Reg. §1.704-3 and disclose it on Line N.",
                'IRC §704(c); Treas. Reg. §1.704-3; Form 1065 Instructions (K-1 Line N)',
                f"Confirm: were all contributions cash (Ledger = Acct.Cash.*)? "
                f"If yes, Line N is blank (§704(c) = $0). "
                f"If property was contributed, engage CPA to compute §704(c) amounts.")


# ════════════════════════════════════════════════════════════════════════════
#  AgentSchK1_PassiveItems — Part III: f49–f77
# ════════════════════════════════════════════════════════════════════════════

class AgentSchK1_PassiveItems(_SectionAgent):
    """
    IRS Expert — Schedule K-1 Part III: Partner's Share of Income, Deductions,
    Credits & Other Items (f49–f111)

    Per-partner: all dollar amounts = IS.value × pct (Books-First, IRC §446/703).

    PASSIVE INCOME CLASSIFICATION (IRC §469 — critical for W&B Group):
      IRC §469(c)(2): ALL rental activity is PASSIVE by statutory definition.
      EXCEPTION — IRC §469(c)(7) Real Estate Professional (REP) test:
        • >50% of ALL personal services during the year are in real property trades/businesses
          in which the taxpayer materially participates, AND
        • >750 hours per year of services in those real property trades/businesses.
        If Francis (96% managing member) qualifies as a REP AND materially participates
        in W&B Group's rental activities, his rental income becomes NON-PASSIVE
        (deductible against ordinary income without passive activity limitation).
        Determination: W&B is a PART-TIME investment LLC. Unless Francis's PRIMARY
        occupation is real estate (CPA, contractor, property manager, etc.), he does NOT
        qualify as a REP. Default classification: PASSIVE for ALL partners.
        See RULE SK1C-R00 advisory below.

    IRC §702(a) — separately stated items (Box 2, Box 5) retain character
    IRC §707(c) — guaranteed payments → Box 4 = $0 for W&B
    IRC §1402(a)(1)/(13) — rental excluded from SE earnings → Box 14a = $0
    IRC §179; §469(j)(1) — §179 passive limitation (Box 12)
    IRC §704(d) — basis limitation on partner's loss deduction
    IRC §1411 — Net Investment Income Tax (NIIT): rental from passive activity IS NII →
                 partners must report Box 2 on Form 8960 Line 4a; Box 20 Code Z.
    """

    LABEL     = "Part III: Partner's Share of Income, Deductions, Credits & Other Items"
    AGENT_KEY = 'AgentSchK1_PassiveItems'

    def pass2_audit(self, owner: Dict) -> Dict[str, Any]:
        return self._run_audit([
            lambda o=owner: self._rule_passive_classification(o),
            lambda o=owner: self._rule_box1_must_zero(o),
            lambda o=owner: self._rule_box2_net_rental(o),
            lambda o=owner: self._rule_box3_other_rental(o),
            lambda o=owner: self._rule_box4_guaranteed_payments(o),
            lambda o=owner: self._rule_box5_interest(o),
            lambda o=owner: self._rule_boxes_6_10_investment(o),
            lambda o=owner: self._rule_box11_other_income(o),
            lambda o=owner: self._rule_box12_sec179(o),
            lambda o=owner: self._rule_box13_other_deductions(o),
            lambda o=owner: self._rule_box14_must_zero(o),
            lambda o=owner: self._rule_box18_tax_exempt(o),
            lambda o=owner: self._rule_box19_distributions(o),
            lambda o=owner: self._rule_box20_niit(o),
            lambda o=owner: self._rule_box2_basis_advisory(o),
        ], owner)

    def pass5_summarize(self, owner: Dict) -> str:
        pct   = _owner_pct(owner)
        net   = self._get_is_agg('net_rental')
        box2  = round(net * pct, 2)
        nm    = _owner_name(owner)
        intr  = round(self._get_is_agg('interest_income') * pct, 2)
        return (f"Partner's Share: {nm} — "
                f"Box 1=$0 (passive rental), Box 2=${box2:,.2f} "
                f"(IS.net_rental ${net:,.2f} × {pct*100:.2f}% — PASSIVE per §469(c)(2)), "
                f"Box 5=${intr:,.2f}, Box 14a=$0, Box 20Z=NII advisory.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_passive_classification(self, owner: Dict):
        """
        SK1C-R00: Passive vs. non-passive classification advisory — IRC §469.

        GOVERNING LAW:
          IRC §469(c)(2): rental activity is ALWAYS passive.
          IRC §469(c)(7): EXCEPTION for real estate professionals (REPs):
            (A) >50% of the taxpayer's personal services during the year are in
                real property trades/businesses in which the taxpayer materially
                participates, AND
            (B) the taxpayer performs >750 hours of services during the year in
                those real property trades/businesses.

        APPLICATION TO W&B GROUP:
          Francis (96%, managing member): Active manager who selects properties,
          signs documents, and oversees operations. However:
          • "Active" in LLC management ≠ REP status under §469(c)(7).
          • REP requires that real estate activities constitute MORE THAN HALF of ALL
            personal services. If Francis has a primary non-real-estate job, REP fails.
          • W&B Group is an INVESTMENT LLC — typical part-time engagement (reviewing
            statements, signing documents) falls far short of 750 hours/year.
          • DEFAULT: Francis's rental income is PASSIVE (same as Alexandra and Nicola).

          Alexandra (2%), Nicola (2%): Passive members. Rental income is PASSIVE.

        IMPLICATIONS OF PASSIVE STATUS:
          • Box 2 income → partners report on Schedule E Part II (passive income)
          • Losses limited by §469 passive activity rules (can only offset other passive income)
          • Income IS subject to Net Investment Income Tax (NIIT) under §1411 → Box 20 Code Z
          • Partners should NOT report Box 2 on Schedule C or subject it to SE tax

        CPA ACTION: Francis must determine if he meets IRC §469(c)(7) REP criteria.
        If REP, he may elect to treat all rental real estate as a single activity
        (Treas. Reg. §1.469-9(g)) and deduct losses against ordinary income.
        This is a significant individual-return planning issue.
        """
        status = str(owner.get('status', '') or '').lower()
        nm     = _owner_name(owner)
        oID    = owner.get('oID', '')
        is_manager = 'manager' in status
        return self.format_issue(
            'SK1C-R00', self.INFO,
            f"Partner '{nm}' ({oID}): rental income classification = PASSIVE (§469(c)(2)). "
            f"{'Manager role noted — see REP advisory below.' if is_manager else 'Passive member.'} "
            f"IRC §469(c)(2) makes ALL rental activity passive by statute. "
            f"{'ADVISORY (active manager): Francis qualifies as REP under §469(c)(7) ONLY if ' if is_manager else ''}"
            f"{'real estate services >50% of all personal services AND >750 hours/year. ' if is_manager else ''}"
            f"{'W&B is a part-time investment LLC — REP test likely NOT met without a primary real estate profession. ' if is_manager else ''}"
            f"ALL W&B partners: Box 2 is PASSIVE → Schedule E Part II. "
            f"Box 20 Code Z (NIIT): rental income IS net investment income under §1411.",
            'IRC §469(c)(2); §469(c)(7); §1411; Treas. Reg. §1.469-9',
            f"CPA advisory: {'Verify Francis does not meet §469(c)(7) REP criteria. ' if is_manager else ''}"
            f"All partners: report Box 2 on Schedule E Part II. "
            f"Ensure Form 8960 (NIIT) reflects Box 2 as net investment income.")

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
                'SK1C-R02', self.WARN,
                f"Partner '{nm}' ({oID}): Box 2 (F050) MUST be filled. "
                f"IS.net_rental ${net:,.2f} × {pct*100:.2f}% = ${expected:,.2f}. "
                f"Books-First (IRC §446/703): this is the ONLY income box for a rental LLC. "
                f"If Box 2 is blank in the PDF, the K-1 is incomplete — regenerate the PDF. "
                f"LLCTaxAgent XF-R03 verifies sum of all partners' Box 2 = Schedule K Line 2.",
                'IRC §446; IRC §702(a); IRC §703; Books-First rule',
                f"Regenerate the K-1 PDF if Box 2 is blank. "
                f"Verify Box 2 = ${expected:,.2f} for '{nm}' in the FILL.pdf after generation.")
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
        SK1C-R09: Box 14a (SE earnings) MUST be $0 — IRC §1402(a)(1).

        IRC §1402(a)(1) EXPLICITLY EXCLUDES rental income from real estate from
        'net earnings from self-employment'. This exclusion is based on the NATURE
        of the income (rental), NOT on the partner's management role.

        CRITICAL DISTINCTION:
          • Active manager (Francis, 96%): manages the LLC, signs documents, makes
            decisions. This is INVESTMENT MANAGEMENT, not 'services' that override
            the rental exclusion. IRC §1402(a)(1) excludes rental income EVEN for
            the managing member — management of a rental investment ≠ provision of
            substantial personal services to tenants.
          • Passive members (Alexandra, Nicola): definitively not subject to SE tax.
          • The '50% manager' question applies to §469(c)(7) Real Estate Professional
            status — that is a PASSIVE LOSS question, not a SE tax question.
            REP status may allow Francis to deduct rental losses against ordinary income,
            but it does NOT expose him to SE tax on rental income.

        EXCEPTION (extremely narrow): SE tax applies to rentals ONLY if the LLC
        provides substantial personal services to occupants (e.g., hotel-style daily
        maid service). W&B Group provides standard residential rental services →
        exception does not apply.

        Non-zero Box 14a incorrectly triggers ~15.3% SE tax on rental income.
        """
        agg  = self._get_is()
        se   = _safe_float(agg.get('se_income', agg.get('self_employment', 0)))
        oID  = owner.get('oID', '')
        nm   = _owner_name(owner)
        status = str(owner.get('status', '') or '').lower()
        is_manager = 'manager' in status
        if abs(se) > 0.01:
            pct = _owner_pct(owner)
            return self.format_issue(
                'SK1C-R09', self.ERROR,
                f"Partner '{nm}' ({oID}): IS shows SE income = ${se:,.2f} → "
                f"Box 14a would be ${se*pct:,.2f} (non-zero). "
                f"Box 14a MUST be $0 for ALL rental LLC partners including managing members. "
                f"IRC §1402(a)(1): rental income from real estate is excluded from SE earnings "
                f"regardless of management role. SE exclusion = income type, not partner role. "
                f"Non-zero Box 14 incorrectly triggers ~15.3% SE tax — major penalty exposure.",
                'IRC §1402(a)(1); Pub 541 (Partnerships)',
                "Remove any IS.se_income/self_employment mapping from the K-1 pipeline. "
                "Box 14a must be blank/$0 for ALL rental LLC partners.")
        return self.format_issue(
            'SK1C-R09', self.INFO,
            f"Partner '{nm}' ({oID}): Box 14a (SE earnings) = $0 ✓. "
            f"{'Managing member (Francis): active management of a rental investment is NOT ' if is_manager else ''}"
            f"{'substantial personal services under §1402(a)(1). ' if is_manager else ''}"
            f"IRC §1402(a)(1): rental real estate income excluded from SE earnings for ALL partners. "
            f"The SE exclusion is based on income type (rental), not management role. "
            f"The >50% time test is §469(c)(7) REP status — a passive-loss question, "
            f"not a SE tax question. Box 14a = $0 for every W&B partner.",
            'IRC §1402(a)(1); §469(c)(7); Pub 541',
            "No action. Box 14a is correctly $0. Advisory: if Francis believes he qualifies "
            "as a Real Estate Professional (§469(c)(7)) for passive-loss purposes, "
            "that analysis is separate and does not change Box 14a.")

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

    def _rule_box11_other_income(self, owner: Dict):
        """
        SK1C-R11: Box 11 (Other Income) = $0 for W&B Group — IRC §702(a).
        Box 11 carries other partnership income items not classified in Boxes 1-10.
        W&B Group is a pure rental LLC — no cancellation of debt, no §1231 recapture,
        no gambling winnings, no other unusual income items expected.
        COA MAPPING: Would source from IS accounts not covered by Boxes 1-10.
        DEFAULT: $0 (blank) for W&B Group 2025.
        """
        oID = owner.get('oID', '')
        agg = self._get_is()
        other = _safe_float(agg.get('other_income', agg.get('misc_income', 0)))
        if abs(other) > 0.01:
            pct = _owner_pct(owner)
            return self.format_issue(
                'SK1C-R11', self.WARN,
                f"Partner {oID}: IS shows other_income = ${other:,.2f} → "
                f"Box 11 would be ${other*pct:,.2f}. "
                f"Verify classification: does this belong in Box 11 (Other Income) "
                f"or in another box (e.g., Box 2, Box 5, Box 10)?",
                'IRC §702(a); Form 1065 Instructions (K-1 Box 11)',
                "Review IS.other_income. Reclassify to correct box if needed.")

    def _rule_box13_other_deductions(self, owner: Dict):
        """
        SK1C-R13: Box 13 (Other Deductions) — IRC §702(a) separately stated items.

        Box 13 carries deductions not in Boxes 12 or 14a. Common codes:
          13A = Cash contributions (charitable)
          13B = Investment interest expense (from passive activity)
          13W = Deductions — portfolio (formerly 2% floor expenses under §67)
          13K = Excess business interest expense (IRC §163(j))
          13L = Deductions — royalty income

        For W&B Group 2025 (pure rental, first year):
          • No charitable contributions through the LLC → Code A = $0
          • No investment interest → Code B = $0
          • §163(j) business interest limitation applies to partnerships. However, small
            business exception (§163(j)(3)): exempt if average annual gross receipts
            ≤ $30M for prior 3 years. W&B Group (first year) likely exempt.
            If NOT exempt: excess business interest = mortgage interest × pct.
          • Box 13 = blank/$0 for W&B Group 2025 absent unusual deduction items.
        """
        oID = owner.get('oID', '')
        return self.format_issue(
            'SK1C-R13', self.INFO,
            f"Partner {oID}: Box 13 (Other Deductions) = $0 for W&B Group 2025. "
            f"No charitable contributions, investment interest, or portfolio deductions "
            f"are expected for a pure rental LLC in its first year. "
            f"IRC §163(j) business interest limitation: W&B likely qualifies for the "
            f"small business exception (§163(j)(3)) — avg gross receipts ≤ $30M. "
            f"If §163(j) applies, excess interest = IS.mortgage_interest × pct → Code 13K.",
            'IRC §702(a); IRC §163(j); Form 1065 Instructions (K-1 Box 13)',
            "No action needed unless the LLC has unusual deduction items. "
            "Verify §163(j) small business exception with CPA if mortgage interest is large.")

    def _rule_box18_tax_exempt(self, owner: Dict):
        """
        SK1C-R18: Box 18 (Tax-Exempt Income and Nondeductible Expenses) — IRC §705(a)(1)(B).
        Box 18A = tax-exempt interest (e.g., from municipal bonds).
        Box 18B = other tax-exempt income.
        Box 18C = nondeductible expenses.
        For W&B Group: no municipal bonds, no tax-exempt income, no expected
        nondeductible expenses → Box 18 = blank/$0.
        IRC §705(a)(1)(B): tax-exempt income INCREASES partner's outside basis even though
        it's not taxable — partners need this for basis tracking.
        """
        oID = owner.get('oID', '')
        return self.format_issue(
            'SK1C-R18', self.INFO,
            f"Partner {oID}: Box 18 (Tax-Exempt / Nondeductible) = $0 for W&B Group 2025. "
            f"No municipal bond interest, tax-exempt income, or nondeductible expenses expected. "
            f"IRC §705(a)(1)(B): tax-exempt income increases outside basis — important for "
            f"future years if any tax-exempt income is earned.",
            'IRC §705(a)(1)(B); Form 1065 Instructions (K-1 Box 18)',
            "No action needed. If LLC invests in municipal bonds in future years, "
            "map tax-exempt interest to Box 18A.")

    def _rule_box19_distributions(self, owner: Dict):
        """
        SK1C-R19: Box 19 (Distributions) — IRC §731; Form 1065 Instructions.

        Box 19a = Cash and marketable securities distributed to partner during year.
        Box 19b = Distribution of property (non-cash, FMV basis).
        Box 19c = Other distributions.

        COA STANDARD MAPPING:
          Box 19a: Credits to Acct.Equity.Owner.Capital.Dist in GL, per propOwners.
                   Same GL source as Box L L5 (f43). Must equal GL distributions.
                   IRC §731: cash distributions NOT exceeding outside basis are NOT taxable.
                   Excess distributions over basis → §731(a) capital gain.

        NOTE: Box 19a ≠ Box 2 × pct. Box 19a = actual cash paid. Box 2 = income allocated.
        For W&B Group 2025 (first year): distributions likely $0 or equal to net income.
        """
        oID    = owner.get('oID', '')
        nm     = _owner_name(owner)
        distrib = self._gl_distributions(oID)
        pct     = _owner_pct(owner)
        net     = self._get_is_agg('net_rental')
        box2    = round(net * pct, 2)
        return self.format_issue(
            'SK1C-R19', self.INFO,
            f"Partner '{nm}' ({oID}): Box 19a (Cash Distributions, GL-sourced) = "
            f"${distrib:,.2f}. "
            f"Source: GL Credits to Acct.Equity.Owner.Capital.Dist (all tables). "
            f"Box 2 (income allocated) = ${box2:,.2f} — distributions may differ from income. "
            f"IRC §731: distributions ≤ outside basis → not taxable. "
            f"Excess distributions over basis → §731(a) capital gain event.",
            'IRC §731; Form 1065 Instructions (K-1 Box 19)',
            f"Verify: actual cash transferred to '{nm}' = ${distrib:,.2f}. "
            f"If $0 (no cash distributions made), leave Box 19a blank.")

    def _rule_box20_niit(self, owner: Dict):
        """
        SK1C-R20: Box 20 Code Z — Net Investment Income (NII) — IRC §1411.

        IRC §1411 (Net Investment Income Tax): 3.8% NIIT applies to passive income
        for taxpayers above the threshold ($200k single / $250k married filing jointly).

        RENTAL INCOME AND NIIT:
          Passive rental income from a passive activity IS net investment income
          under IRC §1411(c)(1)(A)(i). W&B Group's rental income (Box 2) flows through
          to partners as NII — each partner must report it on Form 8960.

          W&B partners should receive Box 20, Code Z = Box 2 amount (their share of
          net rental income that is NII subject to the 3.8% surcharge).

          EXCEPTION: If a partner qualifies as a Real Estate Professional (§469(c)(7))
          AND materially participates, rental income is NOT passive → NOT NII.
          For W&B Group: default assumption = all rental income is NII.

        COA MAPPING: Box 20Z = IS.net_rental × pct (same as Box 2).

        Form 8960 connection: partners copy Box 20Z amount to Form 8960 Line 4a (net
        rental income from partnerships). This is a SEPARATELY STATED ITEM per §702(a).
        """
        pct    = _owner_pct(owner)
        net    = self._get_is_agg('net_rental')
        box2   = round(net * pct, 2)
        oID    = owner.get('oID', '')
        nm     = _owner_name(owner)
        if abs(box2) > 0.01:
            return self.format_issue(
                'SK1C-R20', self.INFO,
                f"Partner '{nm}' ({oID}): Box 20 Code Z (NII) = ${box2:,.2f} "
                f"(= Box 2, IS.net_rental ${net:,.2f} × {pct*100:.2f}%). "
                f"IRC §1411: passive rental income IS net investment income. "
                f"Partners above NIIT threshold (>$200k single / $250k MFJ) "
                f"owe 3.8% NIIT on Box 20Z on Form 8960 Line 4a. "
                f"EXCEPTION: if partner qualifies as REP (§469(c)(7)), rental is NOT NII.",
                'IRC §1411(c)(1)(A)(i); Form 8960; Form 1065 Instructions (K-1 Box 20 Code Z)',
                f"MAP Box 20Z in _FILL_MAP_K1 → IS.net_rental × pct. "
                f"Inform '{nm}': if Box 2 > $0 and income exceeds NIIT threshold, "
                f"report Box 20Z on Form 8960 Line 4a.")
        return self.format_issue(
            'SK1C-R20', self.INFO,
            f"Partner '{nm}' ({oID}): Box 20 Code Z (NII) = $0 (Box 2 = $0). "
            f"No NIIT exposure on rental income for this tax year.",
            'IRC §1411; Form 8960',
            "No action needed. NII = $0 when net rental income = $0.")


# ════════════════════════════════════════════════════════════════════════════
#  FORMSCHK1AGENT  (Tier 1 orchestrator)
# ════════════════════════════════════════════════════════════════════════════

class FormSchK1Agent(IRSFormsAgent):
    """
    Tier 1 orchestrator — runs section agents per partner.

    Per-member mode: FormSchK1Agent(llc, oID='FrancisRojas')
      • _get_owners() returns only that partner
      • session state stored as FormSchK1_{oID}_session_state.json
      • getSummary() / run_phases_1_2() return flat 'sections' dict (no 'partners' nesting)

    All-partners mode: FormSchK1Agent(llc)  — used by LLCTaxAgent phase1_prepare
      • runs all partners, stores FormSchK1_session_state.json (aggregate)
      • getSummary() returns {'partners': {...}} as before
    """

    _SECTION_ORDER = [
        AgentSchK1_PartnershipInfo,
        AgentSchK1_PartnerCapital,
        AgentSchK1_PassiveItems,
    ]

    def __init__(self, llc, tax_year: Optional[int] = None, oID: Optional[str] = None):
        super().__init__(llc, tax_year)
        self._section_agents = [cls(llc, self.tax_year) for cls in self._SECTION_ORDER]
        self._owners: Optional[List[Dict]] = None
        self._oID = oID  # None = all partners; str = single-partner mode

    # ── Owner loading ─────────────────────────────────────────────────────────

    def _get_owners(self) -> List[Dict]:
        if self._owners is not None:
            return self._owners
        try:
            raw = self.llc.owners
            all_owners = raw() if callable(raw) else list(raw or [])
        except Exception:
            all_owners = []
        if self._oID:
            self._owners = [o for o in all_owners if o.get('oID') == self._oID]
            if not self._owners:
                self._owners = all_owners[:1]   # fallback to first if oID not found
        else:
            self._owners = all_owners
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

            # Per-partner K-1 computed values (GL-sourced for capital fields)
            try:
                from ledger.stmtIS import stmtIS
                agg = stmtIS(self.llc).taxAggregates()
            except Exception:
                agg = {}
            net     = _safe_float(agg.get('net_rental', 0))
            pct     = _owner_pct(owner)
            box2    = round(net * pct, 2)
            # Use a capital section agent instance for GL-sourced values
            _cap_agent = next(
                (a for a in self._section_agents
                 if isinstance(a, AgentSchK1_PartnerCapital)), None
            )
            if _cap_agent:
                contrib  = _cap_agent._gl_contributions(oID)
                distrib  = _cap_agent._gl_distributions(oID)
                cap_end  = _cap_agent._gl_ending_capital(oID, pct)
            else:
                contrib = distrib = 0.0
                cap_end = round(box2, 2)

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

        if self._oID and len(owners) == 1:
            # Per-member mode: flatten sections to top-level (no 'partners' nesting)
            owner      = owners[0]
            oID        = owner.get('oID', self._oID)
            pdata      = partner_state.get(oID, {})
            nm         = pdata.get('name', oID)
            pct        = pdata.get('pct', 0.0)
            box2       = pdata.get('box2', 0.0)
            cap_end    = pdata.get('capital_ending', 0.0)
            session = {
                'tax_year':      self.tax_year,
                'last_run':      _now_iso(),
                'overall_state': overall_state,
                'partner_oID':   oID,
                'partner_name':  nm,
                'pct':           pct,
                'box2':          box2,
                'capital_ending': cap_end,
                'sections':      pdata.get('sections', {}),
                'summary':       (
                    f"K-1 for {nm} ({pct*100:.2f}%): Box 2=${box2:,.2f}, "
                    f"Ending Capital=${cap_end:,.2f}. "
                    f"Box 1=$0 (§469), Box 14a=$0 (§1402). "
                    f"Tax basis capital (Rev. Proc. 2020-13)."
                ),
            }
        else:
            # All-partners aggregate (LLCTaxAgent uses this)
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
            base = {
                'tax_year':      self.tax_year,
                'last_run':      None,
                'overall_state': self.NOT_STARTED,
                'summary':       'Not yet run',
            }
            if self._oID:
                base['sections'] = {}
                base['partner_oID'] = self._oID
            else:
                base['partners'] = {}
            return base
        return state

    # ── Session state persistence ─────────────────────────────────────────────

    def _session_state_path(self) -> Optional[Path]:
        d = self._agent_work_dir()
        if d is None:
            return None
        # Per-member: separate file so LLCTaxAgent aggregate is never clobbered
        fname = f'FormSchK1_{self._oID}_session_state.json' if self._oID else 'FormSchK1_session_state.json'
        return d / fname

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
