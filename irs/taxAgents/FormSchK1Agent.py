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

    def _get_raw_assets(self) -> List[Dict]:
        """Raw llcAssets records for the LLC's tax year (propOwners as dicts)."""
        if self._raw_assets is not None:
            return self._raw_assets
        try:
            from ledger.llcAssets import llcAssets
            data = llcAssets(self.llc).load()
            yr = str(getattr(self.llc, 'yr', '') or '')
            if yr:
                data = [r for r in data if str(r.get('dt', '')).startswith(yr)]
            self._raw_assets = data if isinstance(data, list) else []
        except Exception:
            self._raw_assets = []
        return self._raw_assets

    @staticmethod
    def _parse_prop_owners(raw) -> Dict[str, float]:
        """
        Parse propOwners into {oID: pct_decimal}.  Handles these formats:
          dict          : {"o20250801_1": 100}      → {o20250801_1: 1.0}
          JSON string   : '{"020250801_1": 100}'    → {o20250801_1: 1.0}
          colon string  : "o20250801_1:100%"        → {o20250801_1: 1.0}
          null/empty    : None / ''                 → {}
        Integer percent > 1 is divided by 100.  oID missing leading 'o' is
        normalised (data-entry convention: "020250801_1" → "o20250801_1").
        """
        if not raw:
            return {}
        import re as _re, json as _json

        def _normalise(oid_str: str, pct_str: str) -> Optional[tuple]:
            oid = str(oid_str).strip()
            # Common typo: leading '0' instead of 'o' (e.g. "020250801_1" → "o20250801_1")
            if oid and not oid.startswith('o') and oid[0] == '0':
                oid = 'o' + oid[1:]   # replace leading '0' with 'o'
            elif oid and not oid.startswith('o') and oid[0].isdigit():
                oid = 'o' + oid       # genuine digit prefix — prepend 'o'
            try:
                pct_val = float(str(pct_str).replace('%', '').strip())
                return oid, (pct_val / 100.0 if pct_val > 1.5 else pct_val)
            except (TypeError, ValueError):
                return None

        result: Dict[str, float] = {}

        if isinstance(raw, dict):
            for oid, pct in raw.items():
                pair = _normalise(oid, pct)
                if pair:
                    result[pair[0]] = pair[1]

        elif isinstance(raw, str):
            raw_s = raw.strip()
            # Try JSON-encoded dict first: '{"020250801_1": 100}'
            if raw_s.startswith('{'):
                try:
                    d = _json.loads(raw_s)
                    for oid, pct in d.items():
                        pair = _normalise(oid, pct)
                        if pair:
                            result[pair[0]] = pair[1]
                    return result
                except Exception:
                    pass
            # Colon-separated pairs: "oID1:pct1%, oID2:pct2%"
            for part in raw_s.split(','):
                part = part.strip()
                m = _re.match(r'^([^:]+):([0-9.]+)', part)
                if m:
                    pair = _normalise(m.group(1), m.group(2))
                    if pair:
                        result[pair[0]] = pair[1]

        return result

    def _gl_contributions(self, oID: str) -> float:
        """
        Box L L2 — capital contributed during the year (f40).

        COA Standard Mapping (Books-First, IRC §446/703):
          Source: Acct.Equity.Owner.Capital.Funds  (acctID 3010) — Credit entries
                  Acct.Equity.Owner.Capital.Reinvestment (acctID 3025) — Credit entries
          Double-entry: DR Cash/Escrow → CR Equity.Owner.Capital.Funds
            Credit to the equity account = owner contributing funds into the LLC.
          Per-partner: weighted by propOwners dict in each GL record.
          Tax year filter: records with dt starting with self.llc.yr.

        IRC §722: partner's initial outside basis equals cash + FMV of property
        contributed.  Box L L2 is the direct source for the partner's §722 basis.
        """
        total = 0.0
        for r in self._get_raw_assets():
            if str(r.get('acct', '')).strip() not in self._CONTRIB_ACCTS:
                continue
            if str(r.get('aType', '')).strip().lower() not in ('credit', 'cr', 'c'):
                continue
            po = self._parse_prop_owners(r.get('propOwners'))
            pct = po.get(oID, 0.0)
            if pct > 0:
                try:
                    total += float(r.get('amt', 0) or 0) * pct
                except (TypeError, ValueError):
                    pass
        return round(total, 2)

    def _gl_distributions(self, oID: str) -> float:
        """
        Box L L5 — withdrawals and distributions (f43).

        COA Standard Mapping:
          Source: Acct.Equity.Owner.Capital.Dist (acctID 3020) — Credit entries
            Credit to the distribution account = cash paid out to partner.
          Per-partner: weighted by propOwners.

        NOTE: Distributions are NOT equal to allocated income (Box 2).  They
        are actual cash payments.  Do not derive from IS.net_rental × pct.
        """
        total = 0.0
        for r in self._get_raw_assets():
            if str(r.get('acct', '')).strip() not in self._DISTRIB_ACCTS:
                continue
            if str(r.get('aType', '')).strip().lower() not in ('credit', 'cr', 'c'):
                continue
            po = self._parse_prop_owners(r.get('propOwners'))
            pct = po.get(oID, 0.0)
            if pct > 0:
                try:
                    total += float(r.get('amt', 0) or 0) * pct
                except (TypeError, ValueError):
                    pass
        return round(total, 2)

    def _gl_ending_capital(self, oID: str, owner_pct: float) -> float:
        """
        Box L L6 — ending capital account (f44).

        COA Standard Mapping (Books-First):
          Source: YE balance of all Acct.Equity.Owner.* accounts minus Fiscal
          Start balance (= $0 for first-year LLC).

          Balance convention (BS: Balance = Debit − Credit):
            Normal equity balance is Credit → Balance is negative in the BS
            convention.  Ending capital for Box L = −(BS balance) per owner.

          Per-partner computation:
            Credits to equity owner accounts (positive for ending capital):
              Acct.Equity.Owner.Capital.Funds — contributions
              Acct.Equity.Owner.Capital.Reinvestment — reinvestment
            Debits to equity owner accounts (negative for ending capital):
              Acct.Equity.Owner.Capital.Dist — distributions
            Income allocation entries (Debit to Capital.Funds from PnL close):
              Increase ending capital (add to contributions).

          Fallback formula when GL data is sparse:
            L6 = L2 (contributions) + L3 (IS.net_rental × pct) − L5 (distributions)
            This satisfies IRC §705 and matches the Books-First requirement.
        """
        contrib = self._gl_contributions(oID)
        distrib = self._gl_distributions(oID)
        net_rental = self._get_is_agg('net_rental')
        income_alloc = round(net_rental * owner_pct, 2)
        return round(contrib + income_alloc - distrib, 2)

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

    def _rule_irs_center(self, owner: Dict):
        """
        SK1A-R04: IRS Service Center (K-1 field f13) — Form 1065 Instructions (Line C).

        K-1 Line C tells each partner WHERE the partnership return was filed —
        the partner may need this to respond to IRS notices. The value depends
        entirely on HOW (not where) W&B Group filed Form 1065:

          E-filed returns  → write 'E-File'  (most modern filers use this)
          Paper returns    → filing center determined by state:
            Texas partnerships → 'Ogden, UT 84201' (IRS Pub 15 2025 instructions)
            (Same Ogden address applies for most states in 2025)

        DO NOT try to auto-derive this from the LLC's street address — the IRS
        service center is a function of the FILING METHOD, not the LLC's location.
        """
        pr     = self._get_profile()
        center = str(pr.get('F1065', {}).get('irs_center', '') or '').strip()
        oID    = owner.get('oID', '')
        if not center:
            return self.format_issue(
                'SK1A-R04', self.WARN,
                f"Partner {oID}: F1065.irs_center is blank (K-1 field f13). "
                f"K-1 Line C must show where Form 1065 was filed. "
                f"E-filed Form 1065 → set to 'E-File'. "
                f"Paper Form 1065 from Texas → set to 'Ogden, UT 84201'. "
                f"This value is informational for partners — it helps them route "
                f"any correspondence or notice responses to the correct IRS campus.",
                'Form 1065 Instructions (K-1 Line C / field f13)',
                "Set F1065.irs_center in llcProfile_WBGroupLLC.json. "
                "For almost all 2025 partnerships: use 'E-File'.")
        else:
            return self.format_issue(
                'SK1A-R04', self.INFO,
                f"Partner {oID}: K-1 field f13 IRS center = '{center}'. "
                f"Verify this matches how Form 1065 was actually filed "
                f"(e-filed → 'E-File'; paper → 'Ogden, UT 84201' for Texas LLCs).",
                'Form 1065 Instructions (K-1 Line C)',
                "No action if filing method matches. Update llcProfile if wrong.")

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
        oID     = owner.get('oID', '')
        contrib = self._gl_contributions(oID)
        distrib = self._gl_distributions(oID)
        ending  = self._gl_ending_capital(oID, pct)
        nm      = _owner_name(owner)
        return (f"Capital (Box L): {nm} — "
                f"Beg=$0 + Contrib(GL)=${contrib:,.2f} + Box2=${box2:,.2f} "
                f"− Distrib(GL)=${distrib:,.2f} = Ending=${ending:,.2f} (tax basis).")

    # ── Rules ────────────────────────────────────────────────────────────────

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
                f"f45 Tax basis checkbox: Check (Rev. Proc. 2020-13 mandatory). "
                f"f46 Non-tax basis checkbox: NoCheck.",
                'IRC §705; §722; Rev. Proc. 2020-13; Form 1065 Instructions (K-1 Box L)',
                f"Record contribution transaction in llcAssets for '{oID}'. "
                f"Verify distributions reflect actual cash paid out (not income allocation).")
        else:
            return self.format_issue(
                'SK1B-R07', self.INFO,
                f"Partner '{nm}' ({oID}) Box L (tax basis, first year, GL-sourced): "
                f"L1(f39)=$0 + L2(f40)=${contrib:,.2f} + L3(f41)=${box2:,.2f} "
                f"− L5(f43)=${distrib:,.2f} = L6(f44)=${ending:,.2f}. "
                f"IRC §705 formula confirmed. "
                f"f40 sourced from GL Credits to Acct.Equity.Owner.Capital.Funds. "
                f"f44 = L2+L3−L5 (Books-First, IRC §446). "
                f"f45 Tax basis checkbox: Check (Rev. Proc. 2020-13). "
                f"f46 Non-tax basis checkbox: NoCheck.",
                'IRC §705; Rev. Proc. 2020-13; Form 1065 Instructions (K-1 Box L)',
                f"Verify all Box L values for '{nm}': "
                f"L1=$0, L2=${contrib:,.2f}, L3=${box2:,.2f}, L5=${distrib:,.2f}, L6=${ending:,.2f}. "
                f"Source: GL Credits to Acct.Equity.Owner.Capital.Funds weighted by propOwners.")

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
