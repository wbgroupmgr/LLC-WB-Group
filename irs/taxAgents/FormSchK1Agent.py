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


def _gl_capital_rows(llc) -> List[dict]:
    """
    All Capital.Funds/Reinvestment/Dist rows from the FULL double-entry stmtGL,
    scoped to llc.yr's period activity only (current year's contributions/
    distributions — IRC §705/§722 Box L L2/L5, and issue #66's capital
    rollforward "this period" lines).

    Raw source loaders (_gl_load_all) only find Capital accounts when they are
    the PRIMARY account on a record.  When Capital.Funds is the CONTRA (credit
    side) — e.g. DR Fixed.Asset / CR Capital.Funds for a property contribution —
    the raw loader misses it.  stmtGL expands every source record to two rows so
    both sides are visible.  This is the correct source for Box L (IRC §705/722).

    stmtGL treats Capital.Funds/Dist/Reinvestment as cumulative-to-date (issue
    #54 — correct for the Balance Sheet's Schedule L total), so this function
    applies its own explicit year filter on top — these callers need "this
    year's" contributions/distributions specifically, not the running total.
    """
    from ledger.stmtGL import stmtGL
    _TRACKED = {
        'Acct.Equity.Owner.Capital.Funds',
        'Acct.Equity.Owner.Capital.Reinvestment',
        'Acct.Equity.Owner.Capital.Dist',
    }
    yr = str(getattr(llc, 'yr', '') or '')
    try:
        rows = [r for r in stmtGL(llc).load() if str(r.get('acct', '')) in _TRACKED]
        if yr:
            rows = [r for r in rows if str(r.get('dt', '')).startswith(yr)]
        return rows
    except Exception:
        return []


def gl_contributions(llc, oID: str) -> tuple:
    """
    Box L L2 (f40) — capital contributed during the year.

    Uses stmtGL (full double-entry) so property-contribution entries where
    Capital.Funds is the CONTRA (credit) side are captured.

    Returns (attributed, untagged) where:
      attributed — sum of credits to Capital.Funds/Reinvestment with explicit
                   propOwners referencing oID.
      untagged   — sum of credits to Capital.Funds/Reinvestment where propOwners
                   is null/empty (cannot be attributed without a data fix).

    Null-propOwners rows are NOT silently allocated by ownership pct — doing so
    would give 2%-members false contributions equal to 2% of the property value.
    The caller (section agent) surfaces these as a separate WARN.

    YE income-closing entries ("YE Net Income" in desc) are excluded.
    IRC §722: partner's outside basis = cash + FMV of property contributed.
    """
    attributed = 0.0
    untagged   = 0.0
    _FUND = {'Acct.Equity.Owner.Capital.Funds', 'Acct.Equity.Owner.Capital.Reinvestment'}
    for r in _gl_capital_rows(llc):
        if str(r.get('acct', '')) not in _FUND:
            continue
        if str(r.get('aType', '')).lower() not in ('credit', 'cr', 'c'):
            continue
        if 'YE Net Income' in str(r.get('desc', '')):
            continue
        amt = float(r.get('amt', 0) or 0)
        po  = _parse_prop_owners_gl(r.get('propOwners'))
        if po:
            pct = po.get(oID, 0.0)
            if pct > 0:
                attributed += amt * pct
        else:
            untagged += amt
    return round(attributed, 2), round(untagged, 2)


def gl_distributions(llc, oID: str) -> float:
    """
    Box L L5 (f43) — withdrawals and distributions, GL-sourced via stmtGL.

    Counts two types of outflows:
      1. Debits to Capital.Funds/Reinvestment with explicit propOwners for oID
         (non-YE entries) — return-of-capital / withdrawal transactions.
      2. Credits to Capital.Dist with explicit propOwners for oID — formal
         distribution entries.

    Null-propOwners rows excluded (no silent allocation).
    NOT equal to allocated income — distributions are actual cash paid out.
    """
    total = 0.0
    for r in _gl_capital_rows(llc):
        acct  = str(r.get('acct', ''))
        atype = str(r.get('aType', '')).lower()
        amt   = float(r.get('amt', 0) or 0)
        if 'YE Net Income' in str(r.get('desc', '')):
            continue
        po  = _parse_prop_owners_gl(r.get('propOwners'))
        if not po:
            continue  # skip untagged rows
        pct = po.get(oID, 0.0)
        if pct <= 0:
            continue
        # Debits to Capital.Funds = withdrawals / return of capital
        if acct in {'Acct.Equity.Owner.Capital.Funds',
                    'Acct.Equity.Owner.Capital.Reinvestment'}:
            if atype in ('debit', 'dr', 'd'):
                total += amt * pct
        # Credits to Capital.Dist = formal distributions
        elif acct == 'Acct.Equity.Owner.Capital.Dist':
            if atype in ('credit', 'cr', 'c'):
                total += amt * pct
    return round(total, 2)


def gl_untagged_contributions(llc) -> List[dict]:
    """
    Capital.Funds/Reinvestment credit rows with null/empty propOwners.
    Returned as brief dicts for display in the section agent WARN.
    """
    _FUND = {'Acct.Equity.Owner.Capital.Funds', 'Acct.Equity.Owner.Capital.Reinvestment'}
    result = []
    for r in _gl_capital_rows(llc):
        if str(r.get('acct', '')) not in _FUND:
            continue
        if str(r.get('aType', '')).lower() not in ('credit', 'cr', 'c'):
            continue
        if 'YE Net Income' in str(r.get('desc', '')):
            continue
        po = _parse_prop_owners_gl(r.get('propOwners'))
        if not po:
            result.append({
                'dt':   r.get('dt', ''),
                'amt':  float(r.get('amt', 0) or 0),
                'desc': str(r.get('desc', ''))[:80],
            })
    return result


def gl_beginning_capital(llc, oID: str, owner_pct: float) -> float:
    """
    Beginning-of-year capital account — the prior year's Ending Capital.

    Statement of Partners' Capital roll-forward (IRC §705): <prior period
    ending> -> <this period beginning>, then this period's GL activity
    (contributions + income share − distributions) aggregates into the
    period's capital delta. Recurses back through every earlier registered
    year; returns 0.0 once there's no year before the earliest one (the
    LLC's first fiscal year genuinely has no beginning capital).
    """
    from ledger import setup_paths as _sp
    llc_name = getattr(llc, 'objName', '')
    try:
        this_year = int(getattr(llc, 'yr', 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    prior_years = sorted((y for y in _sp.available_years(llc_name) if y < this_year),
                         reverse=True)
    if not prior_years:
        return 0.0
    prior_year = prior_years[0]
    from ledger.LLC import LLC
    prior_llc = LLC(llc_name, debug=False, year=prior_year)
    return gl_ending_capital(prior_llc, oID, owner_pct)


def gl_ending_capital(llc, oID: str, owner_pct: float,
                      net_rental: float = None) -> float:
    """
    Box L L6 (f44) — ending capital account, GL-sourced (IRC §705).
    Formula: L1(beginning, prior year's ending) + L2(attributed contributions)
    + L3(IS.net_rental × pct) − L5(distributions).
    Untagged contributions are excluded from the ending balance (surfaced as WARN).
    """
    if net_rental is None:
        try:
            from ledger.stmtIS import stmtIS
            net_rental = float(stmtIS(llc).taxAggregates().get('net_rental', 0))
        except Exception:
            net_rental = 0.0
    beginning     = gl_beginning_capital(llc, oID, owner_pct)
    attributed, _ = gl_contributions(llc, oID)
    distrib       = gl_distributions(llc, oID)
    income        = round(net_rental * owner_pct, 2)
    return round(beginning + attributed + income - distrib, 2)


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
        """Box L L2 attributed total. See gl_contributions() for full tuple."""
        attributed, _ = gl_contributions(self.llc, oID)
        return attributed

    def _gl_contributions_full(self, oID: str) -> tuple:
        """Returns (attributed, untagged). Use when the WARN note is needed."""
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
            self._rule_k1_layout_orientation,
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

    def _rule_k1_layout_orientation(self, owner: Dict):
        """
        SK1A-R00: K-1 layout orientation — two-part structure (Part I vs Part II).

        Schedule K-1 is divided into two independent sections:

          PART I  (f1–f13) — PARTNERSHIP information (the LLC itself, same on every K-1):
            f1–f5  = Tax year (beginning/ending month, day, 2-digit year)
            f6     = Final K-1 checkbox
            f7     = Amended K-1 checkbox
            f8     = LLC EIN (Line A)
            f9     = LLC name (Line B — name part)
            f10    = LLC street address (Line B — '177 Kingsway Dr')
            f11    = PTP checkbox (Line D — publicly traded partnership)
            f12    = LLC city/state/ZIP (Line B — 'Wimberley, Tx 78676')  ← NOT the partner's SSN
            f13    = IRS Service Center where Form 1065 was filed (Line C)

          PART II (f14–f48) — PARTNER information (different on each partner's K-1):
            f14/f15 = Partner type: GP/manager (f14) or LP/other (f15)
            f16/f17 = Domestic (f16) or foreign (f17)
            f18     = Disregarded entity (Line H2) — for SMLLC/trust partners ONLY
            f19     = Partner's SSN or EIN (Line E) ← THIS is where partner SSN lives
            f20     = Partner's name (Line F)
            f21     = Partner's address (Line F)
            f22     = Retirement plan checkbox (Line I)
            f23–f28 = Ownership % Profit/Loss/Capital (Box J)
            f29–f36 = Partner's share of liabilities (Box K1)
            f37–f48 = Capital account (Box L)

        COMMON CONFUSION: f12 shows the LLC's city/state/ZIP ('Wimberley, Tx 78676').
        This is CORRECT — it is Part I (LLC info), not Part II (partner info).
        The partner's SSN is in f19 (Part II, Line E) — a completely separate field.
        """
        pr     = self._get_profile()
        entity = pr.get('entity', {})
        csz    = entity.get('city_state_zip', f"{pr.get('F1065', {}).get('C_city', '')} "
                            f"{pr.get('F1065', {}).get('C_state', '')} "
                            f"{pr.get('F1065', {}).get('C_zip', '')}")
        oID    = owner.get('oID', '')
        return self.format_issue(
            'SK1A-R00', self.INFO,
            f"✓ K-1 for {oID}: layout orientation — Part I (LLC info) and Part II (partner info) are separate.\n"
            f"  • Part I (f1–f13): same on every K-1 — shows the LLC's EIN, name, address, and IRS center.\n"
            f"    f12 = LLC city/state/ZIP = '{csz}' — this is CORRECT (LLC address, NOT the partner's SSN).\n"
            f"    f13 = IRS Service Center (Line C) — where Form 1065 was filed.\n"
            f"  • Part II (f14–f48): partner-specific — SSN is f19, name is f20, address is f21.\n"
            f"    f18 (Disregarded Entity) is NOT related to f19/f20 — SSN and name are ALWAYS required.",
            'Form 1065 Instructions (Schedule K-1, Parts I and II overview)',
            "No action needed for this rule — it is informational only. "
            "Subsequent rules check each Part I/II field individually.")

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
                f"⚠ K-1 header for {oID}: tax year is missing in llcProfile.\n"
                f"  • The K-1 must show the accounting period (e.g. 01/01/2025 – 12/31/2025).\n"
                f"  • Set F1065.tax_year to '25' in llcProfile to fill the K-1 year field.",
                'IRC §441; IRC §706; Form 1065 Instructions (K-1 header fields f1–f5)',
                "Set tax_year='25' (or '2025') in llcProfile_WBGroupLLC.json → F1065 section.")

        jan = dfrom.lower().startswith('jan') or dfrom.startswith('01')
        dec = dto.lower().startswith('dec') or dto.startswith('12')
        if dfrom and dto and (not jan or not dec):
            return self.format_issue(
                'SK1A-R01', self.WARN,
                f"K-1 for {oID}: tax period appears non-calendar (date_from='{dfrom}', date_to='{dto}').\n"
                f"  • W&B Group must use a January–December calendar year (required when the majority partner uses a calendar year).\n"
                f"  • A different tax year requires IRS approval — confirm this is intentional.",
                'IRC §441; IRC §706(b)(1)(B); IRC §444',
                "Verify the LLC's accounting period. Calendar year → correct date_from to "
                "'Jan. 01' and date_to to 'Dec. 31' in llcProfile_WBGroupLLC.json.")

        # All good — show what's in the fields
        return self.format_issue(
            'SK1A-R01', self.INFO,
            f"✓ K-1 for {oID}: tax year header is correct — calendar year Jan 1 – Dec 31, {str(ty)[-2:]}.",
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
                f"⚠ K-1 for {oID}: Partnership EIN '{ein}' is missing or invalid.\n"
                f"  • A valid 9-digit EIN (XX-XXXXXXX) is required on every K-1.\n"
                f"  • A bad EIN causes the IRS to reject the entire Form 1065 return, including all K-1s.",
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
                f"⚠ K-1 for {oID}: Partnership name is blank.\n"
                f"  • The LLC name must match Form 1065 exactly — the IRS uses name + EIN together for matching.\n"
                f"  • A missing name will cause matching errors with the IRS.",
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
            f"✓ K-1 for {oID}: header flags — Final K-1 = {'SET ⚠' if is_final else 'Not set (correct — LLC is ongoing)'}; Amended K-1 = {'SET ⚠ verify prior filing' if is_amended else 'Not set (correct — this is the first K-1 for 2025)'}.\n"
            f"  • Neither box needs to be checked for an active, first-year LLC with no partner exits.",
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
                f"K-1 for {oID}: IRS Service Center (Line C) is blank.\n"
                f"  • This field tells each partner WHERE the Form 1065 was filed.\n"
                f"  • For e-filed returns (most filers): set to 'E-File'.\n"
                f"  • For paper-filed Texas LLC: set to 'Ogden, UT 84201'.\n"
                f"  • Note: this is a separate field from the LLC's street address.",
                'Form 1065 Instructions (K-1 Line C / field f13)',
                "Set F1065.irs_center in llcProfile_WBGroupLLC.json → 'E-File' for e-filers.")
        else:
            return self.format_issue(
                'SK1A-R04b', self.INFO,
                f"✓ K-1 for {oID}: IRS Service Center (Line C) = '{center}'.\n"
                f"  • Verify this matches how Form 1065 was filed: E-filed → 'E-File'; paper Texas LLC → 'Ogden, UT 84201'.",
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
                f"⚠ K-1 for {oID}: the 'Publicly Traded Partnership' (PTP) box is marked.\n"
                f"  • W&B Group is a private LLC — it is not publicly traded on any securities market.\n"
                f"  • Checking this box changes the tax treatment for ALL partners and is incorrect.\n"
                f"  • PTP status is reserved for partnerships whose interests trade on stock exchanges.",
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
                f"K-1 for {oID}: 'Final K-1' box is checked.\n"
                f"  • Confirm this partner is leaving the LLC (or the LLC is closing) this tax year.\n"
                f"  • A Final K-1 means the partner must settle up any remaining gains or losses on their personal return.",
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
                f"K-1 for {oID}: 'Amended K-1' box is checked.\n"
                f"  • Confirm the original K-1 was previously filed with the IRS before sending this corrected version.\n"
                f"  • An amended K-1 must be sent to the partner AND filed with the IRS (usually with an amended Form 1065).",
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
            lambda o=owner: self._rule_capital_unattributed(o),
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
                f"⚠ K-1 for {nm} ({oID}): Social Security Number is missing or invalid.\n"
                f"  • Current SSN value: '{ssn}' — not a valid 9-digit SSN.\n"
                f"  • The IRS requires each partner's SSN on their K-1 (Line E) for tax matching.\n"
                f"  • Without a valid SSN, the IRS will reject the K-1 and may issue penalty notices.\n"
                f"  • Note: the LLC's address (Part I) is a different field — this is the PARTNER'S personal SSN.",
                'IRC §6109; Treas. Reg. §301.6109-1; Form 1065 Instructions (K-1 Line E)',
                f"Add SSN to llcOwners for '{oID}' in llcOwners_WBGroupLLC.json. "
                f"Format: 'SSN': 'XXX-XX-XXXX'.")

        # Check f21 address includes a 2-letter state abbreviation (e.g. TX)
        has_state = bool(_re.search(r',\s*[A-Z]{2}\b', addr))
        if addr and not has_state:
            return self.format_issue(
                'SK1B-R00', self.WARN,
                f"K-1 for {nm} ({oID}): partner address (Line F) is missing the state abbreviation.\n"
                f"  • Current address: '{addr}'\n"
                f"  • A complete address is required: street, city, 2-letter state, ZIP (e.g., '177 Kingsway Dr, Wimberley, TX 78676').\n"
                f"  • SSN (last 4): {'*'*3+'-'+'*'*2+'-'+ssn[-4:]} ✓  Name: '{nm}' ✓",
                'Form 1065 Instructions (K-1 Line F — partner address)',
                f"Update 'addr' for '{oID}' in llcOwners_WBGroupLLC.json to include state: "
                f"e.g. 'addr': '177 Kingsway Dr, Wimberley, TX 78676'.")

        return self.format_issue(
            'SK1B-R00', self.INFO,
            f"✓ K-1 for {nm} ({oID}): Part II identification fields look good.\n"
            f"  • f19 (Line E — Partner SSN): ***-**-{ssn[-4:]} ✓  (not the LLC's EIN — this is {nm}'s personal SSN)\n"
            f"  • f20 (Line F — Partner name): '{nm}' ✓\n"
            f"  • f21 (Line F — Partner address): '{addr or '(not set)'}'\n"
            f"  • f18 (Line H2 — Disregarded Entity): NOT checked ✓ — correct for an individual person.\n"
            f"    Note: f18 unchecked does NOT suppress f19/f20 — SSN and name are required on every K-1.",
            'IRC §6109; Form 1065 Instructions (K-1 Lines E, F, H2)',
            f"Verify SSN matches '{nm}' Form 1040. Confirm address is complete "
            f"(street, city, 2-letter state abbrev., ZIP).")

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
                f"K-1 for {nm} ({oID}): partner role (status) is blank.\n"
                f"  • The K-1 needs to know if this partner is a manager (check 'GP/manager' box) or a passive member ('LP/other' box).\n"
                f"  • For W&B Group: Francis = manager (GP box); Alexandra and Nicola = passive members (LP box).\n"
                f"  • All W&B partners are domestic U.S. individuals.",
                'IRC §761(b); IRC §1402; Form 1065 Instructions (K-1 Lines G, H1, H2)',
                f"Set status='Manager' for managing members, or 'Member'/'non_active member' "
                f"for passive members in llcOwners for '{oID}'.")

        type_label = 'GP/member-manager (f14)' if is_manager else 'LP/other LLC member (f15)'
        entity_label = 'Individual' if has_ssn else (mem_type or 'unknown')
        return self.format_issue(
            'SK1B-R01', self.INFO,
            f"✓ K-1 for {nm} ({oID}): partner type = {type_label} (status='{status}').\n"
            f"  • Entity type: {entity_label} — reports K-1 Box 2 on Schedule E (page 2) of their personal Form 1040.\n"
            f"  • Domestic partner ✓ (SSN on file). Not a disregarded entity ✓ (individual person).",
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
                f"K-1 for {nm} ({oID}): has a business EIN on file but no Social Security Number.\n"
                f"  • If this partner is a foreign person or foreign company, the LLC may owe withholding tax (up to 37%) on their share of income.\n"
                f"  • Confirm whether '{nm}' is a U.S. person or a foreign entity — this affects withholding requirements.",
                'IRC §1441; IRC §1446; Forms 8804, 8805',
                f"Confirm citizenship/residency of partner '{oID}'. "
                f"If foreign: engage CPA for §1446 withholding. "
                f"If domestic: add SSN to llcOwners.")

    def _rule_disregarded_entity(self, owner: Dict):
        """
        SK1B-R03: Disregarded entity check — Treas. Reg. §301.7701-3.

        K-1 Line H2 field f18 = 'Disregarded Entity' (DE) checkbox.

        A disregarded entity is a single-member LLC (SMLLC) or grantor trust that has NOT
        elected corporate tax treatment (Form 8832). The SMLLC is 'disregarded' — the IRS
        treats it as if it doesn't exist, taxing the underlying owner directly.

        CRITICAL: f18 (Line H2 DE checkbox) is COMPLETELY INDEPENDENT of f19 (SSN) and f20 (name).
          f18 unchecked = 'This partner is NOT a disregarded entity.'
          f18 unchecked does NOT mean f19/f20 are blank — partner SSN and name are ALWAYS required
          on every K-1 regardless of the DRE status. A K-1 without f19 (SSN) is missing the
          primary tax matching key and will cause IRS matching failures.

        For W&B Group 2025:
          ALL partners are individual human beings (not LLCs or trusts).
          Individual humans are NEVER disregarded entities → f18 = NoCheck for all W&B partners.
          This is CORRECT. f19 (SSN) and f20 (name) are still filled in — as always required.

        Detection heuristic: partner name contains LLC/TRUST/CORP/INC/LTD AND has a tID (EIN).
        """
        nm   = _owner_name(owner)
        tID  = str(owner.get('tID', '') or '').strip()
        oID  = owner.get('oID', '')
        nm_upper = nm.upper()
        is_entity_nm = any(kw in nm_upper for kw in ('LLC', 'TRUST', 'CORP', 'INC', 'LTD'))
        if tID and is_entity_nm:
            return self.format_issue(
                'SK1B-R03', self.INFO,
                f"K-1 for {nm} ({oID}): this partner appears to be an LLC or Trust (not an individual).\n"
                f"  • If it's a single-member LLC that hasn't elected corporate tax treatment, the K-1 should note it as a 'disregarded entity' (Line H2, f18).\n"
                f"  • The K-1 is issued to the LLC entity, but the underlying owner's SSN goes in Line E (f19).\n"
                f"  • Note: f18 checked/unchecked has NO effect on whether f19 (SSN) or f20 (name) must be filled — those are always required.",
                'Treas. Reg. §301.7701-3; Form 1065 Instructions (K-1 Line H2)',
                f"Verify the legal structure of '{nm}'. If DE: check K1_PtDE checkbox. "
                f"Ensure Line E (K1_PtEIN) contains the beneficial owner's SSN, not the LLC EIN.")
        # Individual human partner — explicit confirmation that f18 unchecked is correct
        return self.format_issue(
            'SK1B-R03', self.INFO,
            f"✓ K-1 for {nm} ({oID}): Disregarded Entity (Line H2, f18) = NOT checked — correct.\n"
            f"  • {nm} is an individual person, not an LLC or trust — 'Disregarded Entity' does not apply.\n"
            f"  • f18 unchecked does NOT mean f19 (SSN) or f20 (name) should be blank.\n"
            f"    Those are required on EVERY K-1 regardless of f18's value — and they are filled.",
            'Treas. Reg. §301.7701-3; Form 1065 Instructions (K-1 Line H2)',
            "No action needed. f18 is correctly left unchecked for all W&B individual partners.")

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
                f"⚠ K-1 for {nm} ({oID}): ownership percentage is missing or zero.\n"
                f"  • Without an ownership percentage, this partner gets $0 on every K-1 line — their entire share of rental income is omitted.\n"
                f"  • All partners' ownership percentages must add up to 100%.",
                'IRC §704(b); IRC §706; Form 1065 Instructions (K-1 Box J f23–f28)',
                f"Set pct for partner '{oID}' in llcOwners. "
                f"Sum of all partners' pct must equal 1.0 (100%).")
        return self.format_issue(
            'SK1B-R04', self.INFO,
            f"✓ K-1 for {nm} ({oID}): ownership percentage = {pct*100:.1f}% (Profit / Loss / Capital — all the same).\n"
            f"  • No ownership change during 2025, so beginning and ending percentages are equal.\n"
            f"  • Allocation matches the LLC Operating Agreement.",
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
                f"✓ K-1 for {nm} ({oID}): share of the LLC's mortgage = ${partner_qnr:,.2f}.\n"
                f"  • Total LLC mortgage: ${mortgage:,.2f} × {pct*100:.2f}% ownership = ${partner_qnr:,.2f}.\n"
                f"  • This is 'Qualified Nonrecourse Financing' (a bank loan secured by real property, no personal guarantee).\n"
                f"  • This mortgage share increases {nm}'s ability to deduct rental losses — it counts toward their 'at-risk' basis.\n"
                f"  • Beginning-of-year debt = $0 (LLC was formed in 2025; no debt existed at January 1).",
                'IRC §752; §465(b)(6); Treas. Reg. §1.752-3(a)(3)',
                f"Confirm mortgage is from a commercial lender (bank/S&L/govt agency) and "
                f"no partner personally guaranteed repayment. If so, classify as QNR. "
                f"f34 = ${partner_qnr:,.2f}. f31/f33/f35 (BOY) = $0 (first year).")
        else:
            return self.format_issue(
                'SK1B-R05', self.WARN,
                f"K-1 for {nm} ({oID}): no mortgage found in the books — Box K1 (liabilities) = $0.\n"
                f"  • If the LLC has a mortgage on the property, it must be recorded in llcAssets as a liability.\n"
                f"  • Without the mortgage recorded, each partner's 'at-risk' basis is understated, which can limit their ability to deduct rental losses.",
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
                f"K-1 for {nm} ({oID}): capital account method is set to '{method}'.\n"
                f"  • The IRS now requires ALL partnerships to use the 'Tax Basis' method (since 2020).\n"
                f"  • Other methods (book value, GAAP) are no longer accepted.\n"
                f"  • The 'Tax basis' checkbox must be checked on the K-1.",
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

        # GL-sourced values (Books-First, IRC §446/703) — stmtGL full double-entry
        contrib, untagged = self._gl_contributions_full(oID)
        distrib           = self._gl_distributions(oID)
        ending            = self._gl_ending_capital(oID, pct)

        untagged_note = ''
        if untagged > 0.01:
            untagged_note = (
                f"\n  ⚠ ${untagged:,.2f} in Capital.Funds entries have no propOwners tag "
                f"(see SK1B-R07u below). These are excluded from Box L until tagged."
            )

        is_manager = 'manager' in str(owner.get('status', '')).lower()

        if contrib == 0 and untagged == 0:
            if is_manager:
                # Managing member with $0 contributions is likely a data gap
                return self.format_issue(
                    'SK1B-R07', self.WARN,
                    f"⚠ K-1 for {nm} ({oID}): no capital contributions recorded (Box L, Line 2 = $0).\n"
                    f"  • The managing member typically contributes cash or property when the LLC is formed.\n"
                    f"  • Without it, {nm}'s ownership basis is $0, which limits their ability to claim losses.\n"
                    f"  • Box L: Contributed=$0 | Income=${box2:,.2f} | Ending=${ending:,.2f}.",
                    'IRC §705; §722; Rev. Proc. 2020-13',
                    f"Record the capital contribution for '{nm}' in the books "
                    f"(DR Cash → CR Acct.Equity.Owner.Capital.Funds, with propOwners set).")
            else:
                # Passive/minor member with $0 contributions is normal
                return self.format_issue(
                    'SK1B-R07', self.INFO,
                    f"✓ K-1 for {nm} ({oID}) capital account (Box L, tax basis):\n"
                    f"  • Capital contributed: $0 (no cash contribution recorded — expected for this member)\n"
                    f"  • Share of {self.tax_year} income: ${box2:,.2f}\n"
                    f"  • End of year balance: ${ending:,.2f}",
                    'IRC §705; Rev. Proc. 2020-13',
                    f"Box L: L2=$0, L3=${box2:,.2f}, L5=$0, L6=${ending:,.2f}.")
        else:
            has_warn = untagged > 0.01
            # Only show "(tagged)" label when there are still untagged entries to distinguish from
            contrib_label = "Capital contributed (tagged)" if has_warn else "Capital contributed"
            return self.format_issue(
                'SK1B-R07', self.WARN if has_warn else self.INFO,
                f"{'⚠' if has_warn else '✓'} K-1 for {nm} ({oID}) capital account (Box L, tax basis):\n"
                f"  • {contrib_label}: ${contrib:,.2f}\n"
                f"  • Share of {self.tax_year} income: ${box2:,.2f}\n"
                f"  • Distributions paid out: ${distrib:,.2f}\n"
                f"  • End of year balance: ${ending:,.2f}"
                + untagged_note,
                'IRC §705; Rev. Proc. 2020-13; Form 1065 Instructions (K-1 Box L)',
                f"Verify Box L in PDF for '{nm}': "
                f"L2=${contrib:,.2f}, L3=${box2:,.2f}, L5=${distrib:,.2f}, L6=${ending:,.2f}."
                + (f" Fix untagged contributions (SK1B-R07u) to complete Box L."
                   if has_warn else ""))

    def _rule_capital_unattributed(self, owner: Dict):
        """
        SK1B-R07u: Capital.Funds credit entries with no propOwners tag.

        These contributions cannot be attributed to a specific member without
        a propOwners field.  Silently allocating by ownership pct would give
        2%-members false contribution amounts (e.g. 2% × $219K = $4,380 for
        a member who contributed nothing).  Per the no-silent-fallback rule
        these are surfaced as a WARN so the operator can tag them in the books.

        FIX: open the transaction in the web editor and add
             propOwners = {"<oID>": 100}  for the contributing member.
        """
        untagged_rows = gl_untagged_contributions(self.llc)
        if not untagged_rows:
            return None
        total = sum(r['amt'] for r in untagged_rows)
        lines = '\n'.join(
            f"  • {r['dt']} | ${r['amt']:,.2f} | {r['desc']}"
            for r in untagged_rows
        )
        # Identify the managing member — untagged contributions most likely belong to them
        try:
            all_owners = self.llc.owners()
        except Exception:
            all_owners = [owner]
        mgr = next(
            (o for o in all_owners
             if 'manager' in str(o.get('status', '')).lower()),
            owner   # fall back to current owner if no manager found
        )
        mgr_nm  = _owner_name(mgr)
        mgr_oID = mgr.get('oID', owner.get('oID', ''))
        return self.format_issue(
            'SK1B-R07u', self.WARN,
            f"Capital.Funds: {len(untagged_rows)} contribution(s) totaling ${total:,.2f} "
            f"have no propOwners tag — excluded from all members' Box L until fixed.\n"
            f"  • These are almost certainly {mgr_nm}'s contributions (property + closing funds).\n"
            + lines,
            'IRC §722; IRC §705; Books-First (propOwners required for per-member attribution)',
            f"For each entry, open the transaction in the web editor and add "
            f"propOwners = {{\"{mgr_oID}\": 100}}. "
            f"After tagging, regenerate to update Box L.")

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
                f"✓ K-1 for {nm} ({oID}): capital contributions = ${contrib:,.2f}.\n"
                f"  • If all contributions were cash (the typical case), Line N (§704(c) built-in gain) = $0.\n"
                f"  • If a partner contributed property instead of cash, a CPA must calculate any built-in gain and disclose it on Line N.",
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
        manager_note = (
            f"\n  • {nm} is listed as managing member — but managing an investment LLC does NOT"
            f"\n    make {nm} a Real Estate Professional. That requires real estate as a primary"
            f"\n    full-time career (>750 hrs/year in real estate trades). Most likely: {nm}'s"
            f"\n    rental income stays PASSIVE, same as all other partners."
        ) if is_manager else ""
        return self.format_issue(
            'SK1C-R00', self.INFO,
            f"W&B Group is a rental LLC — by tax law, ALL rental income is PASSIVE income.\n"
            f"  • {nm} ({oID}): Box 2 income is classified PASSIVE.{manager_note}\n"
            f"  • Each partner reports their K-1 Box 2 amount on Schedule E (page 2) of their personal Form 1040.\n"
            f"  • Passive losses can only offset other passive income (not wages or business income).\n"
            f"  • Rental income is subject to 3.8% Net Investment Income Tax (NIIT) → K-1 Box 20 Code Z.",
            'IRC §469(c)(2); §469(c)(7); §1411',
            f"{'Ask ' + nm + ' to confirm with their CPA whether they qualify as a full-time Real Estate Professional. ' if is_manager else ''}"
            f"All partners: report Box 2 on Schedule E Part II of their personal Form 1040.")

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
                f"⚠ K-1 for {oID}: the books show ordinary income = ${ord_inc:,.2f}, which would make K-1 Box 1 non-zero.\n"
                f"  • Box 1 must be $0 for a rental LLC — rental income belongs in Box 2 (passive rental), not Box 1 (ordinary business income).\n"
                f"  • Box 1 is for partnerships like restaurants or service businesses, not real estate rentals.",
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
            # Books have the answer — confirmed, not a warning.
            # The only open question is whether the FILL.pdf was regenerated.
            return self.format_issue(
                'SK1C-R02', self.INFO,
                f"✓ K-1 for {nm} ({oID}): Box 2 (net rental income) = ${expected:,.2f}.\n"
                f"  • Source: IS.net_rental ${net:,.2f} × {pct*100:.2f}% ownership = ${expected:,.2f}.\n"
                f"  • Box 2 is the only income box for a rental LLC. If the PDF shows blank, regenerate the K-1.",
                'IRC §446; IRC §702(a); IRC §703; Books-First rule',
                f"Regenerate the K-1 PDF if Box 2 is blank in the FILL.pdf.")
        elif abs(net) < 0.01:
            return self.format_issue(
                'SK1C-R02', self.WARN,
                f"K-1 for {nm} ({oID}): net rental income in the books = $0, so Box 2 will be blank.\n"
                f"  • If the property had rental activity this year, check that all income and expenses are recorded correctly.",
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
                f"K-1 for {oID}: the books show 'other rental income' of ${other:,.2f}.\n"
                f"  • Box 3 is for non-real-estate rentals (equipment, vehicles) — not real property.\n"
                f"  • If this is rental income from the property, it belongs in Box 2, not Box 3.",
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
                f"K-1 for {oID}: the books show management fees or guaranteed payments of ${gp:,.2f}.\n"
                f"  • 'Guaranteed payments' are fees paid to a partner regardless of LLC profits — they are taxable to the recipient as ordinary income (not passive rental).\n"
                f"  • If W&B's Operating Agreement does not specifically authorize guaranteed payments, these amounts should be recorded as distributions (Box 19a) instead.",
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
                f"✓ K-1 for {nm} ({oID}): Box 5 (Interest Income) = ${box5:,.2f}.\n"
                f"  • The LLC earned ${interest:,.2f} in bank interest; {nm}'s share ({pct*100:.2f}%) = ${box5:,.2f}.\n"
                f"  • Each partner reports this interest income on Schedule B of their personal Form 1040.",
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
                    f"K-1 for {oID}: the books show {key} = ${val:,.2f} → {label} would be non-zero.\n"
                    f"  • W&B holds real property — investment income (dividends, royalties, capital gains) is unexpected unless a property was sold this year.\n"
                    f"  • If a property was sold, a CPA must calculate the gain and complete Form 4797 (sales of business property).",
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
                f"✓ K-1 for {nm} ({oID}): Box 12 (§179 Deduction) = ${box12:,.2f}.\n"
                f"  • {nm}'s share of the §179 deduction: ${sec179:,.2f} × {pct*100:.2f}% = ${box12:,.2f}.\n"
                f"  • Important: this deduction is limited by {nm}'s passive income from the LLC. Any excess carries forward to future years.\n"
                f"  • §179 cannot be used for the building itself or land — only for qualifying personal property (appliances, equipment).",
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
                f"⚠ K-1 for {nm} ({oID}): the books show self-employment income = ${se:,.2f}, which would make Box 14a non-zero.\n"
                f"  • Box 14a MUST be $0 for ALL rental LLC partners — including the managing member.\n"
                f"  • Rental income from real estate is NOT subject to self-employment tax, regardless of who manages the LLC.\n"
                f"  • A non-zero Box 14a would incorrectly trigger ~15.3% SE tax — a significant overcharge to the partners.",
                'IRC §1402(a)(1); Pub 541 (Partnerships)',
                "Remove any IS.se_income/self_employment mapping from the K-1 pipeline. "
                "Box 14a must be blank/$0 for ALL rental LLC partners.")
        _mgr_note = ('• Note: managing the LLC is investment management — not the same as providing personal services that would trigger SE tax.\n  '
                     if is_manager else '')
        return self.format_issue(
            'SK1C-R09', self.INFO,
            f"✓ K-1 for {nm} ({oID}): Box 14a (Self-Employment Income) = $0 — correct.\n"
            f"  • Rental real estate income is NOT subject to self-employment tax for any partner, including the managing member.\n"
            f"  {_mgr_note}"
            f"• The 'Real Estate Professional' question (50%+ time in real estate) only affects whether losses are passive — it does not create SE tax.",
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
                f"K-1 for {nm} ({oID}): Box 2 = ${box2:,.2f} (a loss this year).\n"
                f"  • Each partner can only deduct this loss up to the amount they have invested (their 'basis') in the LLC.\n"
                f"  • Basis = capital contributed + share of LLC mortgage. This calculation is done on the partner's individual tax return.\n"
                f"  • The K-1 always reports the full allocated loss — the deductible portion depends on each partner's personal situation.",
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
                f"K-1 for {oID}: the books show miscellaneous income of ${other:,.2f} → Box 11 would be ${other*pct:,.2f}.\n"
                f"  • For a rental LLC, this is unexpected. Confirm whether this income belongs in Box 2 (rental), Box 5 (interest), or Box 11 (other).",
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
            f"✓ K-1 for {oID}: Box 13 (Other Deductions) = $0 — correct for W&B Group in 2025.\n"
            f"  • No charitable contributions, investment interest, or unusual deductions expected for a first-year rental LLC.\n"
            f"  • Interest expense deduction rules (§163(j)) generally don't apply to small LLCs — W&B should be exempt given first-year revenue.",
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
            f"✓ K-1 for {oID}: Box 18 (Tax-Exempt Income / Nondeductible Expenses) = $0 — correct.\n"
            f"  • No municipal bonds, tax-exempt income, or nondeductible expenses for W&B in 2025.\n"
            f"  • Worth noting: if the LLC ever earns tax-exempt income in future years, it still counts toward each partner's ownership basis.",
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
            f"✓ K-1 for {nm} ({oID}): Box 19a (Cash Distributions) = ${distrib:,.2f}.\n"
            f"  • This is actual cash paid to {nm} from the LLC (sourced from the books).\n"
            f"  • Note: distributions (${distrib:,.2f}) may differ from allocated income (${box2:,.2f}) — one is cash out, the other is income on paper.\n"
            f"  • Distributions up to {nm}'s ownership basis are not taxable. Amounts above basis trigger a capital gain.",
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
                f"✓ K-1 for {nm} ({oID}): Box 20 Code Z (Net Investment Income) = ${box2:,.2f}.\n"
                f"  • This equals Box 2 — passive rental income is subject to the 3.8% Net Investment Income Tax (NIIT).\n"
                f"  • NIIT applies if your total income (AGI) exceeds: $200,000 (single/HOH) or $250,000 (married filing jointly).\n"
                f"  • If {nm}'s AGI is above that threshold, report Box 20Z on Form 8960 Line 4a of your personal return.\n"
                f"  • Exception: qualifies as full-time Real Estate Professional (§469(c)(7)) → rental income is not NII.",
                'IRC §1411(c)(1)(A)(i); IRC §1411(b); Form 8960 Line 4a; K-1 Box 20 Code Z',
                f"Have {nm} confirm their AGI with their CPA. "
                f"If AGI exceeds the NIIT threshold, report Box 20 Code Z = ${box2:,.2f} on Form 8960 Line 4a.")
        return self.format_issue(
            'SK1C-R20', self.INFO,
            f"✓ K-1 for {nm} ({oID}): Box 20 Code Z (Net Investment Income) = $0.\n"
            f"  • No NIIT exposure this year — net rental income is $0.",
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
