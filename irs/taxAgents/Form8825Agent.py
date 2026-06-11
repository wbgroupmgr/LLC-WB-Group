"""
Form8825Agent — Tier 1 orchestrator for IRS Form 8825 (Rental Real Estate).

Architecture (4-tier):
  Tier 0  LLCTaxAgent        — cross-form audit + submission
  Tier 1  Form8825Agent       — this file; orchestrates 4 section agents
  Tier 2  AgentF8825_*        — one per Form 8825 section (also this file)
  Tier 3  IRSFormsAgent       — common services base class

Form 8825 = Rental Real Estate Income and Expenses of a Partnership.
Books-First rule (IRC §446+703): ALL values from stmtIS.taxAggregates().
Line 14 depreciation MUST NOT come from Form 4562 — sourced from IS.depreciation.
Cross-form audit (LLCTaxAgent XF-R01): F4562 L22 == F8825 L14 == IS.depreciation.

Session state stored at:
  books/{year}/Forms/.agent_work/Form8825_session_state.json
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
    """Common base for all Form 8825 section agents."""

    LABEL      = ''
    AGENT_KEY  = ''
    # Numeric fid ranges owned by this section: list of (lo, hi) inclusive int pairs.
    # Replaces string LOGICAL_PREFIXES — Form 8825 fids are numeric (F001, F023, …)
    # and cannot be reliably distinguished by string prefix within the fill dict.
    _FID_RANGES: List[tuple] = []

    def __init__(self, llc, tax_year: int):
        super().__init__(llc, tax_year)
        self._is_data    = None
        self._fill_cache = None
        self._assets     = None
        self._owners     = None

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

    def _get_owners(self) -> List[Dict]:
        if self._owners is not None:
            return self._owners
        try:
            raw = self.llc.owners
            self._owners = raw() if callable(raw) else list(raw or [])
        except Exception:
            self._owners = []
        return self._owners

    def _get_assets(self) -> List[Dict]:
        """Load llcAssets rows."""
        if self._assets is not None:
            return self._assets
        try:
            from ledger.llcAssets import llcAssets
            assets_obj = llcAssets(self.llc)
            self._assets = assets_obj.load() if hasattr(assets_obj, 'load') else []
        except Exception:
            self._assets = []
        return self._assets

    def _get_cip_propNms(self) -> set:
        """Return propNm values that are truly InConstruction (not yet placed in service).

        A property is CIP iff it has ≥1 Acct.Fixed.Tangible.InConstruction entry
        AND has NO Acct.Fixed.Tangible.InService entry in the GL.
        Properties that have BOTH (e.g., a misclassified legacy entry + real InService
        records) are considered placed-in-service and excluded from the CIP set.

        Source: GL rows (authoritative — merges llcAssets + llcExpRev + all DBs).
        RV_RV1: InConstruction entries in llcExpRev, no InService → CIP.
        H_805HighMesa: one misclassified InConstruction + real InService → NOT CIP.
        """
        has_cip: set     = set()
        has_inservice: set = set()
        try:
            from ledger.stmtGL import stmtGL
            gl = stmtGL(self.llc)
            for r in (gl._rows or []):
                prop  = r.get('propNm', '')
                if not prop:
                    continue
                acct_ = str(r.get('acct', '') or '').lower()
                if 'inconstruction' in acct_:
                    has_cip.add(prop)
                elif 'inservice' in acct_:
                    has_inservice.add(prop)
        except Exception:
            pass
        return has_cip - has_inservice

    # ── GL access + forensic helpers ──────────────────────────────────────────

    def _gl_rows(self) -> List[Dict[str, Any]]:
        """All merged GL rows (llcAssets + llcExpRev + payables + receivables)."""
        try:
            from ledger.stmtGL import stmtGL
            return list(stmtGL(self.llc)._rows or [])
        except Exception:
            return []

    @staticmethod
    def _fix_obj_for(r: Dict[str, Any]) -> str:
        """Which ledger editor view can fix this transaction (for the Fix link)."""
        tdb = str(r.get('tDB', '') or '')
        if tdb == 'llcAssets':
            return 'llcAssets'
        accts = str(r.get('acct', '') or '') + str(r.get('Ledger', '') or '')
        # Fixed-asset manual entries live in llcAssets; bank-sourced exp/rev in llcExpRev.
        if 'Acct.Fixed' in accts and tdb not in ('llcBank', 'llcExpRev'):
            return 'llcAssets'
        return 'llcExpRev'

    def _txn_brief(self, r: Dict[str, Any]) -> Dict[str, Any]:
        """Compact, UI-ready view of a GL transaction incl. tID + fix target."""
        try:
            amt = round(abs(float(r.get('amt', 0) or 0)), 2)
        except Exception:
            amt = 0.0
        acct  = str(r.get('acct', '') or '')
        atype = str(r.get('aType', '') or '')
        # Cash direction: a credit to the bank = money OUT (purchase/payment);
        # a debit to the bank = money IN (return/refund/deposit).
        cash_dir = ''
        if acct == 'Acct.Cash.Bank':
            cash_dir = 'out' if atype == 'Credit' else 'in'
        return {
            'tID':      r.get('tID', ''),
            'tDB':      r.get('tDB', ''),
            'dt':       r.get('dt', ''),
            'prop':     r.get('propNm', ''),
            'aType':    atype,
            'acct':     acct,
            'contra':   str(r.get('Ledger', '') or ''),
            'desc':     (r.get('desc') or '')[:60],
            'amt':      amt,
            'cash_dir': cash_dir,
            'fix_obj':  self._fix_obj_for(r),
        }

    def _forensic_amount_day_clusters(self) -> List[Dict[str, Any]]:
        """
        Forensic — same-amount + same-day transaction clusters.

        Catches the classic bank-ingestion mis-tag: a PURCHASE and its RETURN
        posted under different propNm (or a duplicate double-post). A refund must
        carry the SAME propNm as its purchase; if not, one property's expense is
        understated and the other's basis is overstated.

        Ground truth is always the bank statement (books/<yr>/BankStmts/*.csv).
        """
        from collections import defaultdict
        groups: Dict[tuple, List[Dict]] = defaultdict(list)
        for r in self._gl_rows():
            try:
                amt = round(abs(float(r.get('amt', 0) or 0)), 2)
            except Exception:
                amt = 0.0
            if amt <= 0:
                continue
            groups[(str(r.get('dt', '')), amt)].append(r)

        findings: List[Dict[str, Any]] = []
        for (dt, amt), rs in groups.items():
            if len(rs) < 2:
                continue
            briefs = [self._txn_brief(r) for r in rs]
            props  = {b['prop'] for b in briefs if b['prop']}
            # Owner-contribution clusters: if ANY row in the cluster carries an
            # Equity account (either as primary acct or contra), the cash flows
            # are explained by an owner funding a same-day asset purchase —
            # not a purchase+refund error.  Skip the has_return check entirely.
            has_equity = any(
                'Equity' in b['acct'] or 'Equity' in b['contra']
                for b in briefs
            )
            # Exclude owner-contribution legs from dirs; if all remaining cash
            # flows collapse to one direction, has_return stays False.
            dirs   = {b['cash_dir'] for b in briefs
                      if b['cash_dir']
                      and 'Equity' not in b['contra']
                      and 'Equity' not in b['acct']}
            has_return = (not has_equity) and ('in' in dirs and 'out' in dirs)
            multi_prop = len(props) > 1
            seen, dup = set(), False
            for b in briefs:
                sig = (b['prop'], b['acct'], b['contra'], b['aType'])
                if sig in seen:
                    dup = True
                seen.add(sig)
            if not (multi_prop or has_return or dup):
                continue
            findings.append({
                'dt': dt, 'amt': amt, 'count': len(rs),
                'props': sorted(props),
                'multi_prop': multi_prop, 'has_return': has_return,
                'duplicate': dup, 'txns': briefs,
            })
        findings.sort(key=lambda f: (-f['amt'], f['dt']))
        return findings

    def _active_property_rows(self) -> List[Dict]:
        """Return one representative row per active rental property from llcAssets.
        Active = has Acct.Fixed.Tangible.InService entry (placed in service).
        InConstruction properties are explicitly excluded — they have no rental activity.
        """
        rows    = self._get_assets()
        cip     = self._get_cip_propNms()
        seen_props: set = set()
        result = []
        for r in rows:
            acct = str(r.get('acct', '')).lower()
            prop = r.get('propNm', '')
            # Only InService (not InConstruction) properties appear on Form 8825
            if 'tangible.inservice' in acct and prop and prop not in cip:
                if prop not in seen_props:
                    seen_props.add(prop)
                    result.append(r)
        # Fallback: rent_income > 0 but no InService asset record
        if not result and self._get_is_agg('rent_income') > 0:
            for r in rows:
                acct = str(r.get('acct', '')).lower()
                prop = r.get('propNm', '')
                if ('fixed' in acct and 'inconstruction' not in acct
                        and prop and prop not in cip and prop not in seen_props):
                    seen_props.add(prop)
                    result.append(r)
        return result

    def _load_fill_dict(self) -> Dict[str, Any]:
        """Load Form 8825 fill dict from stmtIS_Tax. Keys are fids like F023, F079, F113."""
        if self._fill_cache is not None:
            return self._fill_cache
        try:
            from ledger.stmtIS import stmtIS_Tax
            tax = stmtIS_Tax(self.llc)
            self._fill_cache = tax.loadFillDict('Form8825') or {}
        except Exception:
            self._fill_cache = {}
        return self._fill_cache

    # Form 8825 canonical fid constants (from stmtIS._build_f8825_filldict _P1 + totals)
    _FID_GROSS_RENTS  = 'F023'   # Line 2a col A
    _FID_OTHER_INCOME = 'F027'   # Line 2b col A
    _FID_DEPR         = 'F079'   # Line 14 col A  (depreciation)
    _FID_EXP_TOTAL    = 'F104'   # Line 18 total expenses (all columns summed)
    _FID_NET_TOTAL    = 'F113'   # Line 21 total net income/loss (all columns)

    # ── Fid ownership ─────────────────────────────────────────────────────────

    def _owns_fid(self, fid: str) -> bool:
        """True if fid (e.g. 'F023') falls within this section's _FID_RANGES."""
        try:
            n = int(str(fid).lstrip('Ff'))
        except (ValueError, AttributeError):
            return False
        return any(lo <= n <= hi for lo, hi in self._FID_RANGES)

    # ── Pass interface ────────────────────────────────────────────────────────

    def pass1_auto_fill(self) -> Dict[str, Any]:
        fill_dict = self._load_fill_dict()
        filled = blank = complex_ = 0
        for k, v in fill_dict.items():
            if not self._owns_fid(k):
                continue
            s = str(v).strip().lower() if v is not None else ''
            if v is None or s == '':
                blank += 1
            elif s == 'complex':
                complex_ += 1
            else:
                filled += 1
        return {
            'section':  self.AGENT_KEY,
            'tax_year': self.tax_year,
            'filled':   filled,
            'blank':    blank,
            'complex':  complex_,
            'total':    filled + blank + complex_,
        }

    def pass2_audit(self) -> Dict[str, Any]:
        return {
            'section':       self.AGENT_KEY,
            'halt_count':    0,
            'resolve_count': 0,
            'review_count':  0,
            'issue_list':    [],
            'ready_state':   self.GO,
        }

    def pass4_finalize(self) -> Dict[str, Any]:
        fill = self._load_fill_dict()
        return {k: v for k, v in fill.items() if self._owns_fid(k)}

    def pass5_summarize(self) -> str:
        return f"{self.LABEL}: complete."

    def _run_audit(self, rules: List) -> Dict[str, Any]:
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
#  AgentF8825_Properties — Property identification and placed-in-service dates
# ────────────────────────────────────────────────────────────────────────────

class AgentF8825_Properties(_SectionAgent):
    """
    IRS Knowledge Base — Form 8825 Property Columns (Column headers)

    Form 8825 uses one column per rental property (up to 4 on page 1 = cols A-D;
    4 on page 2 = cols E-H). Each column header includes the property address,
    property type (e.g., "1-family residential"), and placed-in-service date.

    Placed-in-service date (IRC §168(a)):
      MACRS depreciation begins on the date the property is ready and available
      for use in the rental activity — not the purchase date. For H_805HighMesa,
      the placed-in-service date is August 2025.

    Under-construction exclusion (IRC §168):
      Property not yet placed in service cannot be depreciated and is excluded
      from Form 8825 entirely. It has no income or expense to report.

    IRS Form 8825 Instructions: "For each property, enter the type of property
    in the first row and the date the property was placed in service."
    """

    LABEL       = 'Properties'
    AGENT_KEY   = 'AgentF8825_Properties'
    _FID_RANGES = [(1, 22), (115, 137)]    # Property headers cols A-D + E-H

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_no_active_properties,
            self._rule_under_construction,
            self._rule_placed_in_service_date,
            self._rule_many_properties,
        ])

    def pass5_summarize(self) -> str:
        active = self._active_property_rows()
        cip    = self._get_cip_propNms()
        cip_note = (f" {len(cip)} CIP excluded ({', '.join(sorted(cip))})." if cip else "")
        return (f"Properties: {len(active)} active propert{'y' if len(active)==1 else 'ies'} "
                f"on Form 8825 ({', '.join(r.get('propNm', str(r)) for r in active)})."
                + cip_note)

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_no_active_properties(self):
        """
        F8PR-R01: No active properties → Form 8825 cannot be generated.
        If the partnership owns no rental property placed in service during the year,
        Form 8825 is not required. But if IS.rent_income > 0, the absence of an
        active property record is a data error.
        """
        active = self._active_property_rows()
        rent = self._get_is_agg('rent_income')
        if not active and rent > 0.01:
            return self.format_issue(
                'F8PR-R01', self.ERROR,
                f"No active properties found in llcAssets but IS.rent_income = ${rent:,.2f}. "
                f"Form 8825 requires at least one property column. "
                f"IRC §168: property must be placed in service to appear on Form 8825.",
                'IRC §168; Form 8825 Instructions (Column A)',
                "Verify llcAssets has a record with acctSub=Acct.Fixed.Tangible.InService "
                "for the rental property. Check placed-in-service date is set.")

    def _rule_under_construction(self):
        """
        F8PR-R02: Under-construction (CIP) properties detected → excluded from Form 8825.

        IRC §168(a): MACRS depreciation begins when property is placed in service.
        CIP assets have no placed-in-service date → no Form 8825 column, no Line 2a
        income, no Line 14 depreciation.

        CRITICAL — Pre-placed-in-service expenses (IRC §263):
          Expenses incurred before a CIP asset is placed in service are NOT deductible
          as current rental expenses. They must be CAPITALIZED (IRC §263(a) + Treasury
          Reg. §1.263(a)-2(a)): amounts paid to produce tangible property must be
          capitalized as part of the asset's depreciable basis. This includes:
            - Construction materials (Lowe's, Wimberley Ace, Harbor Freight)
            - Fabrication costs (Rodco Steel, Laird Plastics)
            - Installation supplies (Amazon construction items)
          Books fix required: reclassify Acct.Exp.Repair + Acct.Exp.Other entries for
          CIP properties → Acct.Fixed.Tangible.InConstruction.{propNm}.

          Exception: IRC §195 start-up costs (organizational/pre-opening fees such as
          permits or professional fees) may be deductible via a §195 election on Form
          1065 page 1 (NOT Form 8825). Construction materials do not qualify.

        W&B Group 2025 — RV_RV1:
          Status: Acct.Fixed.Tangible.InConstruction (Bill of Sale 2025-12-29).
          Excluded from Form 8825 entirely.
          Pre-service expenses in Acct.Exp.Repair / Acct.Exp.Other → must be
          capitalized. F8EX-R05 will flag the dollar impact on IS totals.

        Detection: checks Ledger field (asset account) for 'InConstruction' —
        the CIP pattern is Ledger='Acct.Fixed.Tangible.InConstruction'.
        """
        cip = self._get_cip_propNms()
        if cip:
            names = ', '.join(sorted(cip))
            return self.format_issue(
                'F8PR-R02', self.WARN,
                f"Under-construction (CIP) asset(s) detected: {names}. "
                f"IRC §168(a): excluded from Form 8825 (no placed-in-service date). "
                f"No Form 8825 column, no income, no depreciation for CIP property. "
                f"IMPORTANT: pre-service expenses for {names} booked to Acct.Exp.* "
                f"must be capitalized under IRC §263(a) — see F8EX-R05 for dollar impact.",
                'IRC §168(a); IRC §263(a); Reg. §1.263(a)-2(a); Form 8825 Instructions',
                f"No Form 8825 action. Fix books: reclassify Acct.Exp.Repair + "
                f"Acct.Exp.Other for {names} → Acct.Fixed.Tangible.InConstruction.{{propNm}}. "
                f"Once placed in service, create Acct.Fixed.Tangible.InService record "
                f"with placed-in-service date.")

    def _rule_placed_in_service_date(self):
        """
        F8PR-R03: Property has no placed-in-service date → MACRS cannot start.
        IRC §168(a): the applicable depreciation method applies to property
        placed in service during the taxable year. Without a placed-in-service date,
        the MACRS year-1 computation (including mid-month convention) cannot be made.
        """
        active = self._active_property_rows()
        missing = [r for r in active
                   if not (r.get('dateInService') or r.get('placed_in_service')
                           or r.get('acqDate') or r.get('date') or r.get('dt'))]
        for row in missing:
            nm = row.get('propNm', row.get('acctNm', 'Unknown property'))
            return self.format_issue(
                'F8PR-R03', self.ERROR,
                f"Property '{nm}' has no placed-in-service date. "
                f"IRC §168(a): MACRS depreciation requires a placed-in-service date. "
                f"Without it, Form 4562 Part III Line 19h Col (b) cannot be completed "
                f"and Year 1 MACRS cannot be computed.",
                'IRC §168(a); Form 4562 Instructions Part III',
                f"Set dateInService (or placed_in_service) for '{nm}' in llcAssets. "
                f"For H_805HighMesa: August 2025 → '8/25' on Form 4562.")

    def _rule_many_properties(self):
        """
        F8PR-R04: > 4 properties → page 2 (cols E-H) will be used.
        Form 8825 page 1 accommodates cols A–D (4 properties). With 5+ properties,
        page 2 is required. This is informational — the pipeline must handle it.
        """
        active = self._active_property_rows()
        if len(active) > 4:
            return self.format_issue(
                'F8PR-R04', self.INFO,
                f"{len(active)} active properties detected — Form 8825 page 2 "
                f"(columns E–H) will be required for properties 5+. "
                f"Verify the PDF pipeline generates both pages.",
                'Form 8825 Instructions (Page 2)',
                "Ensure Form8825 PDF fill pipeline handles columns E–H. "
                "W&B Group currently has 1 property (no page 2 needed).")


# ────────────────────────────────────────────────────────────────────────────
#  AgentF8825_Income — Lines 2a–2c per property
# ────────────────────────────────────────────────────────────────────────────

class AgentF8825_Income(_SectionAgent):
    """
    IRS Knowledge Base — Form 8825 Lines 2a–2c (Income per Property)

    Line 2a (Gross rents received):
      IRC §61: gross income includes compensation for services, rents, gains, etc.
      Pub 527 §1: rental income = rent received plus advance rent, security deposits
      applied to rent, services provided instead of rent.
      Books source: Acct.Rev.Rent.{propNm} in IS.
      Fill field: F023 (per-column gross rents, col A).
      IRS: "Enter the gross rents received or accrued for each property." (Form 8825 Instr)

    Line 2b (Other income):
      Pub 527: other rental income includes cancellation fees, property damaged by
      tenants (beyond deposit), and lease bonus payments.
      Books source: Acct.Rev.Fees.Other.{propNm}.

    Line 2c (Total income):
      Computed = Line 2a + Line 2b. Not separately sourced from books.

    CIP property (RV_RV1) — income section:
      Under-construction properties have ZERO income on Form 8825. They are excluded
      from Form 8825 entirely (IRC §168 — no column, no lines). No income section
      action required for CIP properties. The absence of income is not an error.
      IRS Form 8825 Instructions: only placed-in-service properties have columns.

    W&B Group 2025: IS.rent_income = $4,000, IS.total_income = $4,400 (H_805HighMesa only).
    RV_RV1: $0 income — excluded from Form 8825, no Line 2a/2b entry.
    Books-First: IRC §446.
    """

    LABEL       = 'Income (Lines 2a-2c)'
    AGENT_KEY   = 'AgentF8825_Income'
    _FID_RANGES = [(23, 34), (142, 153)]   # Income lines cols A-D + E-H

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_gross_rent_blank,
            self._rule_gross_rent_mismatch,
            self._rule_other_income_note,
        ])

    def pass5_summarize(self) -> str:
        rent  = self._get_is_agg('rent_income')
        total = self._get_is_agg('total_income')
        other = _safe_float(total - rent)
        return (f"Income: Gross rents (Line 2a) = ${rent:,.2f}. "
                f"Other income (Line 2b) = ${other:,.2f}. "
                f"Total income (Line 2c) = ${total:,.2f}.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_gross_rent_blank(self):
        """
        F8IN-R01: Line 2a blank while IS.rent_income > 0 — required field missing.
        Form 8825 Line 2a must show gross rents when the partnership received rental
        income. A blank Line 2a with non-zero books rent_income means the income
        is not flowing to the form — an IRS reporting violation.
        IRC §61: all rental income must be reported.
        Fill dict fid: F023 (col A gross rents).
        """
        fill   = self._load_fill_dict()
        rent   = self._get_is_agg('rent_income')
        line2a = _safe_float(fill.get(self._FID_GROSS_RENTS, 0))
        if rent > 0.01 and line2a < 0.01:
            return self.format_issue(
                'F8IN-R01', self.ERROR,
                f"Form 8825 Line 2a (Gross rents, fid {self._FID_GROSS_RENTS}) is blank "
                f"but IS.rent_income = ${rent:,.2f}. "
                f"IRC §61: all gross rents must be reported. "
                f"Books source: Acct.Rev.Rent.* → Form 8825 Line 2a.",
                'IRC §61; Form 8825 Instructions Line 2a; Pub 527 §1',
                "Re-run BookToIRS pipeline (BookToIRS.regenerate('Form8825')).")

    def _rule_gross_rent_mismatch(self):
        """
        F8IN-R02: Line 2a ≠ IS.rent_income — Books-First violation.
        IRC §446: books are the authoritative source.
        Fill dict fid F023 must equal IS.rent_income.
        """
        fill   = self._load_fill_dict()
        rent   = self._get_is_agg('rent_income')
        line2a = _safe_float(fill.get(self._FID_GROSS_RENTS, 0))
        if line2a > 0.01 and abs(line2a - rent) > 1.00:
            return self.format_issue(
                'F8IN-R02', self.WARN,
                f"Form 8825 Line 2a ({self._FID_GROSS_RENTS}) = ${line2a:,.2f} "
                f"but IS.rent_income = ${rent:,.2f}. "
                f"Discrepancy: ${abs(line2a - rent):,.2f}. "
                f"Books-First (IRC §446): Line 2a must equal IS.rent_income from books.",
                'IRC §446; Form 8825 Line 2a',
                "Re-run BookToIRS pipeline.")

    def _rule_other_income_note(self):
        """
        F8IN-R03: Other income (Line 2b) populated — confirm rental-related.
        Line 2b includes only income that is rental-related (security deposits
        applied to rent, lease cancellation fees, etc.). Non-rental income
        does not belong on Form 8825 (it flows to Schedule K Line 6 or other lines).
        Pub 527 defines what constitutes rental income.
        """
        total = self._get_is_agg('total_income')
        rent  = self._get_is_agg('rent_income')
        other = _safe_float(total - rent)
        if other > 0.01:
            return self.format_issue(
                'F8IN-R03', self.INFO,
                f"IS.total_income (${total:,.2f}) − IS.rent_income (${rent:,.2f}) "
                f"= ${other:,.2f} other income detected. "
                f"Pub 527: Form 8825 Line 2b is only for rental-related other income "
                f"(security deposits applied to rent, lease cancellation fees). "
                f"Non-rental income belongs on Schedule K, not Form 8825.",
                'Pub 527 §1; Form 8825 Instructions Line 2b',
                "Confirm the ${:,.2f} other income is rental-related before including "
                "it on Form 8825 Line 2b. If non-rental, route to Schedule K.".format(other),
                fids=['F8825_Line2b'])


# ────────────────────────────────────────────────────────────────────────────
#  AgentF8825_Expenses — Lines 5–17 per property
# ────────────────────────────────────────────────────────────────────────────

class AgentF8825_Expenses(_SectionAgent):
    """
    IRS Knowledge Base — Form 8825 Lines 5–17 (Expenses per Property)

    Key expense lines:
      Line 11 (Repairs): IRC §162 — deductible if maintenance, not capital improvement.
      Line 12 (Utilities): IRC §162.
      Line 14 (Depreciation): CRITICAL — see below.
      Line 16 (Taxes): IRC §164 — property taxes only, not income taxes.
      Line 17 (Other): IRC §162 — operating expenses not captured in Lines 5-16.

    CRITICAL — Line 14 Depreciation (Books-First exception):
      Form 8825 instructions say to "use Form 4562 to figure depreciation."
      In our Books-First system:
        - Line 14 = IS.depreciation from books (IRC §446+703)
        - Form 4562 is ALSO populated from IS.depreciation independently
        - LLCTaxAgent XF-R01 verifies F4562 L22 == F8825 L14 == IS.depreciation
      This means both forms are independently correct from books, and the
      cross-form audit confirms their consistency. No form-to-form data dependency.

    CIP property expenses — what goes on Form 8825 Lines 11-17 (F8EX-R05):
      Under-construction properties have NO deductible expenses on Form 8825.
      IRC §263(a) + Reg. §1.263(a)-2(a): all pre-placed-in-service costs must be
      CAPITALIZED (not expensed). They add to the asset's depreciable basis.
      Form 8825 column for CIP: NONE. No Lines 11–17 entries for CIP property.

      Specifically for RV_RV1 (2025):
        - All Acct.Exp.Repair entries (construction materials, tools, fabrication)
          → must be capitalized to Acct.Fixed.Tangible.InConstruction.RV_RV1
        - All Acct.Exp.Other entries (supplies, hardware, permits/fees)
          → capitalize (IRC §263), EXCEPT Hays County permit fees may qualify as
            IRC §195 start-up costs (deductible via §195 election on Form 1065).
        - Zero depreciation (IRC §168 — not yet placed in service).
      If these expenses remain in Acct.Exp.* in the books, IS.total_expenses is
      overstated and IS.net_rental (Form 8825 Line 21) is wrong → ERROR condition.

    Line 18 (Total Expenses, Form-Level F104):
      Correct value = sum of active-property expense subtotals only.
      If CIP expenses remain in books: F104 (via IS.total_expenses) is overstated.
      Books correction required before Form 8825 can be filed.

    W&B Group 2025: IS.depreciation = $1,903.13 → Line 14, fill field F079.
    IRC §469(c)(2): rental expenses are passive — all on Form 8825, never Form 1065 Page 1.
    """

    LABEL       = 'Expenses (Lines 5-19a, incl. Line 14 Depreciation)'
    AGENT_KEY   = 'AgentF8825_Expenses'
    _FID_RANGES = [(35, 102), (154, 221)]  # Expense lines cols A-D + E-H

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_pre_service_expenses,
            self._rule_line14_blank,
            self._rule_line14_mismatch,
            self._rule_line14_xf_note,
            self._rule_total_expenses_mismatch,
        ])

    def pass5_summarize(self) -> str:
        depr   = self._get_is_agg('depreciation')
        total  = self._get_is_agg('total_expenses')
        return (f"Expenses: Line 14 depreciation = ${depr:,.2f} (= IS.depreciation, Books-First). "
                f"Total expenses (Line 18 preview) = ${total:,.2f}.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_pre_service_expenses(self):
        """
        F8EX-R05: Pre-placed-in-service expenses in GL for CIP property.
        IRC §263(a): construction costs must be capitalized, not expensed.
        If still in Acct.Exp.*, Line 20b overstated; Line 21 understated.
        """
        cip = self._get_cip_propNms()
        if not cip:
            return None

        total_exp_books = self._get_is_agg('total_expenses')
        fill = self._load_fill_dict()
        active_col_exp = 0.0
        for col in range(4):
            active_col_exp += _safe_float(fill.get(f'F{95 + col:03d}', 0))
        for col in range(4):
            active_col_exp += _safe_float(fill.get(f'F{95 + 119 + col:03d}', 0))
        active_col_exp = round(active_col_exp, 2)

        cip_exp  = round(total_exp_books - active_col_exp, 2)
        cip_names = ', '.join(sorted(cip))

        if cip_exp > 1.00:
            return self.format_issue(
                'F8EX-R05', self.ERROR,
                f"Under-construction property {cip_names} has ~${cip_exp:,.2f} in expenses "
                f"still booked to Acct.Exp.* accounts (IRC §263 violation). "
                f"Pre-service costs must be capitalized — they are not deductible on Form 8825. "
                f"Impact: Line 20b (Total Rental Expenses) is overstated ~${cip_exp:,.2f}; "
                f"Line 21 (Net Rental Income) is understated by the same amount, "
                f"flowing incorrectly to Schedule K Line 2 and each partner's K-1 Box 2.",
                'IRC §263(a); IRC §168(a); IRC §446',
                f"Fix GL — reclassify Acct.Exp.Repair + Acct.Exp.Other entries for "
                f"propNm='{cip_names}' to Acct.Fixed.Tangible.InConstruction.",
                suggested_mapping={
                    'resolve_available': True,
                    'resolve_label':     'Mark Resolved — expenses capitalized in GL',
                    'resolve_note':      f'Confirm all {cip_names} construction costs are '
                                         f'now in Acct.Fixed.Tangible.InConstruction.',
                })
        elif cip:
            return self.format_issue(
                'F8EX-R05', self.INFO,
                f"Under-construction property {cip_names}: no pre-service expenses "
                f"found in active GL — correctly capitalized or zero.",
                'IRC §263(a); IRC §168(a)',
                "No action required.")

    def _rule_line14_blank(self):
        """F8EX-R01: Line 14 (Depreciation) is blank but books show depreciation."""
        fill   = self._load_fill_dict()
        depr   = self._get_is_agg('depreciation')
        line14 = _safe_float(fill.get('F079') or 0)
        if depr > 0.01 and line14 < 0.01:
            return self.format_issue(
                'F8EX-R01', self.ERROR,
                f"Line 14 (Depreciation) is blank, but the GL shows ${depr:,.2f} "
                f"in depreciation expense for the year (IRC §168 MACRS). "
                f"A missing Line 14 overstates net rental income on Line 21 by ${depr:,.2f}, "
                f"which flows to Schedule K Line 2 and each partner's K-1 Box 2.",
                'IRC §168; Form 8825 Line 14; IRC §446',
                "Fix GL — ensure the depreciation entry in llcAssets has propNm set "
                "to the property name (e.g. 'H_805HighMesa'). "
                "Form 8825 uses per-property GL aggregation; propNm is required.",
                fids=['F079'])

    def _rule_line14_mismatch(self):
        """F8EX-R02: Line 14 (Depreciation) does not match the GL depreciation amount."""
        fill   = self._load_fill_dict()
        depr   = self._get_is_agg('depreciation')
        line14 = _safe_float(fill.get('F079') or 0)
        if line14 > 0.01 and abs(line14 - depr) > 1.00:
            return self.format_issue(
                'F8EX-R02', self.ERROR,
                f"Line 14 (Depreciation) = ${line14:,.2f} but GL shows ${depr:,.2f}. "
                f"Discrepancy of ${abs(line14 - depr):,.2f} (IRC §446 Books-First violation). "
                f"Line 14 must be sourced from the books (IS.depreciation), "
                f"not from Form 4562.",
                'IRC §446; IRC §703; Form 8825 Line 14',
                "Update bookNS — verify Line 14 maps to IS.depreciation "
                "(not to any Form 4562 value).",
                fids=['F079'])

    def _rule_line14_xf_note(self):
        """F8EX-R03: Line 14 (Depreciation) confirmed — cross-form check pending."""
        depr = self._get_is_agg('depreciation')
        if depr > 0.01:
            return self.format_issue(
                'F8EX-R03', self.INFO,
                f"Line 14 (Depreciation) = ${depr:,.2f} — matches GL books (IRC §446). "
                f"Cross-form audit (XF-R01) will confirm Line 14 equals Form 4562 Line 22.",
                'IRC §446; LLCTaxAgent XF-R01',
                "No action required.")

    def _rule_total_expenses_mismatch(self):
        """F8EX-R04: Line 20b (Total Rental Expenses) on form differs from GL total expenses."""
        fill  = self._load_fill_dict()
        total = self._get_is_agg('total_expenses')
        line20b = _safe_float(fill.get('F104') or 0)
        if line20b > 0.01 and abs(line20b - total) > 1.00:
            gap = abs(line20b - total)
            return self.format_issue(
                'F8EX-R04', self.WARN,
                f"Line 20b (Total Rental Expenses) = ${line20b:,.2f} but "
                f"GL total expenses = ${total:,.2f}. "
                f"Gap of ${gap:,.2f} — one or more expense lines may be missing "
                f"from the form or double-counted in the GL (IRC §446).",
                'IRC §446; Form 8825 Instructions Lines 5–18',
                "Audit GL — open the Income Statement by Property view to see "
                "expense totals per property and identify the unaccounted amount.",
                fids=['F104'],
                suggested_mapping={
                    'audit_link':  'stmtIncomeStmt?view_by=ByProperty',
                    'audit_label': 'Open IS by Property',
                })


# ────────────────────────────────────────────────────────────────────────────
#  AgentF8825_NetIncome — Lines 18–21
# ────────────────────────────────────────────────────────────────────────────

class AgentF8825_NetIncome(_SectionAgent):
    """
    IRS Knowledge Base — Form 8825 Lines 18–21 (Net Income/Loss)

    Line 19a (Net income/loss per property):
      Computed: Line 2c − Line 18 = total income − total expenses per column.
      For H_805HighMesa 2025: $4,400 − $4,793.50 = −$393.50.
      CIP properties (RV_RV1): NO column → NO Line 19a entry.

    Line 20a (Total rental income, all columns, F103):
      Sum of all column Line 2c values. Should equal IS.subtotal_rental_income.
      For W&B Group 2025: $4,400 (H_805HighMesa only; RV_RV1 excluded).

    Line 20b (Total rental expenses, all columns, F104):
      Sum of all column Line 18 values. Should equal IS.subtotal_rental_expense
      for ACTIVE (placed-in-service) properties ONLY.
      RECONCILIATION: IS.total_expenses includes ALL Acct.Exp.* entries from all
      properties. If CIP property expenses are NOT capitalized (remain in
      Acct.Exp.*), IS.total_expenses > active-property expenses → F104 is overstated.
      Books correction (IRC §263) required to bring IS.total_expenses in line.

    Line 21 (Total net income/loss, F113):
      Sum of all Line 19a across all active properties.
      IRS Form 8825 Instructions: "Enter this amount on Schedule K, line 2."
      Books-First: Line 21 = IS.net_rental for active properties only (IRC §446+703).
      If CIP expenses remain in books: IS.net_rental is understated (more negative),
      and F113 carries that error to Schedule K Line 2 → all K-1 Box 2 wrong.
      W&B Group correct value (after books fix): H_805HighMesa net only = −$393.50.

    This is the KEY RECONCILIATION POINT:
      Form 8825 Line 21 (= IS.net_rental, active props) → Schedule K Line 2
      Schedule K Line 2 × partner.pct → K-1 Box 2

    IRC §469(c)(2): rental activity is passive. The net rental loss flows to
    Schedule E on each partner's personal return as a passive loss.
    Partners may deduct passive losses against passive income in the same year;
    excess is suspended until the property is disposed (IRC §469(b)).
    """

    LABEL       = 'Summary (Lines 20a-23)'
    AGENT_KEY   = 'AgentF8825_NetIncome'
    _FID_RANGES = [(103, 113)]             # Form-level totals

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_forensic_clusters,
            self._rule_cip_in_totals,
            self._rule_line21_blank,
            self._rule_line21_mismatch,
            self._rule_line21_confirmed,
        ])

    def _rule_forensic_clusters(self):
        """
        F8NI-R05 (forensic): same-amount + same-day clusters.

        The classic signature is a PURCHASE and its RETURN posted under different
        propNm during bank ingestion. Example caught here: $14.06 on 2025-10-09 —
        two RV_RV1 purchases plus one refund mis-tagged to H_805HighMesa. The
        mis-tagged refund understates H_805 expense and overstates RV_RV1 basis.
        Truth: books/<yr>/BankStmts/*.csv (WIMBERLEY ACE purchase + return).
        """
        findings = self._forensic_amount_day_clusters()
        sus = [f for f in findings if f['multi_prop'] or f['has_return']]
        if not sus:
            return None
        # Most-suspicious first: multi-prop refund pairs lead, then by amount.
        sus.sort(key=lambda f: (-(f['multi_prop'] and f['has_return']),
                                -f['multi_prop'], -f['amt'], f['dt']))

        txns: List[Dict[str, Any]] = []
        for f in sus:
            tags = []
            if f['multi_prop']:
                tags.append('MULTI-PROP')
            if f['has_return']:
                tags.append('PURCHASE+RETURN')
            if f['duplicate']:
                tags.append('DUPLICATE')
            flag = ' / '.join(tags)
            for b in f['txns']:
                bb = dict(b)
                bb['flag'] = flag
                txns.append(bb)

        lead     = sus[0]
        critical = any(f['multi_prop'] and f['has_return'] for f in sus)
        return self.format_issue(
            'F8NI-R05', self.ERROR if critical else self.WARN,
            f"Forensic anomaly: {len(sus)} same-amount/same-day cluster(s). "
            f"Highest concern — ${lead['amt']:,.2f} on {lead['dt']} spanning "
            f"{', '.join(lead['props']) or 'one property'} ({lead['count']} transactions, "
            f"mixed purchase/return). A purchase and its refund must carry the SAME propNm; "
            f"a refund booked to a different property understates that property's expense "
            f"and overstates the other property's basis — distorting Form 8825 Line 21, "
            f"Schedule K Line 2, and each partner's K-1 Box 2.",
            'IRC §263(a); IRC §446 (Books-First); bank statement = source of truth',
            f"Verify against the bank statement (books/{self.tax_year}/BankStmts/), then "
            f"correct the mis-tagged transaction's propNm/account in the ledger — "
            f"use the Fix links on the transactions below.",
            fids=['F104', 'F113'],
            suggested_mapping={
                'txns':              txns,
                'source_doc':        f'books/{self.tax_year}/BankStmts/',
                'resolve_available': True,
                'resolve_label':     'Mark Resolved — cluster verified against bank statement',
                'resolve_note':      'Confirm each purchase/return pair shares the correct propNm.',
            })

    def pass5_summarize(self) -> str:
        net = self._get_is_agg('net_rental')
        sign = 'income' if net >= 0 else 'loss'
        return (f"Form 8825: 1 property (H_805HighMesa). "
                f"Gross rents ${self._get_is_agg('rent_income'):,.2f} → "
                f"Net rental {sign} (${abs(net):,.2f}). "
                f"Line 21 = IS.net_rental. "
                f"Line 14 depreciation = IS.depreciation "
                f"(${self._get_is_agg('depreciation'):,.2f}).")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_cip_in_totals(self):
        """F8NI-R04: GL has expense entries for under-construction property that must be capitalized."""
        cip = self._get_cip_propNms()
        if not cip:
            return None

        fill = self._load_fill_dict()
        total_exp_books = self._get_is_agg('total_expenses')
        active_col_exp  = 0.0
        for col in range(4):
            active_col_exp += _safe_float(fill.get(f'F{95 + col:03d}', 0))
        for col in range(4):
            active_col_exp += _safe_float(fill.get(f'F{95 + 119 + col:03d}', 0))
        active_col_exp = round(active_col_exp, 2)
        cip_gap   = round(total_exp_books - active_col_exp, 2)
        cip_names = ', '.join(sorted(cip))

        if cip_gap <= 1.00:
            return None

        # Build the list of offending GL transactions (with tID + Fix link target)
        cip_txns: List[Dict[str, Any]] = []
        for r in self._gl_rows():
            if r.get('propNm') not in cip or r.get('acctType') != 'Expense':
                continue
            b = self._txn_brief(r)
            if b['amt'] <= 0:
                continue
            cip_txns.append(b)

        # If the math gap exists but NO GL expense rows are found for CIP properties,
        # the gap is a stale-IS or rounding artifact — the books are likely correct.
        # Downgrade to INFO so the user isn't alarmed by a phantom ERROR.
        if not cip_txns:
            return self.format_issue(
                'F8NI-R04', self.INFO,
                f"Under-construction property {cip_names}: IS.total_expenses vs "
                f"active-column expense sum gap = ${cip_gap:,.2f}, but no GL expense "
                f"rows found for {cip_names} — books appear correctly capitalized. "
                f"Re-run the analysis after any recent GL edits to confirm.",
                'IRC §263(a); IRC §446',
                "No action required if CIP expenses are already in "
                "Acct.Fixed.Tangible.InConstruction. Re-run to confirm.")

        return self.format_issue(
            'F8NI-R04', self.ERROR,
            f"Under-construction property {cip_names} has ${cip_gap:,.2f} in GL expense entries "
            f"that must be capitalized (IRC §263). "
            f"These inflate Line 20b (Total Rental Expenses) by ${cip_gap:,.2f} and "
            f"understate Line 21 (Net Rental Income) by the same amount, "
            f"causing incorrect Schedule K Line 2 and partner K-1 Box 2 allocations.",
            'IRC §263(a); IRC §446; Form 8825 Lines 20b, 21; IRC §702(a)',
            f"Fix GL — reclassify the {len(cip_txns)} transaction(s) listed below "
            f"from Acct.Exp.* to Acct.Fixed.Tangible.InConstruction for propNm='{cip_names}' "
            f"(use the Fix links).",
            fids=['F104', 'F113'],
            suggested_mapping={
                'txns':              cip_txns,
                'resolve_available': True,
                'resolve_label':     'Mark Resolved — all CIP expenses reclassified',
                'resolve_note':      f'Confirm every {cip_names} expense entry has been '
                                      f'moved to Acct.Fixed.Tangible.InConstruction.',
            })

    def _rule_line21_blank(self):
        """F8NI-R01: Line 21 (Net Rental Income/Loss) is blank — rental activity exists."""
        fill   = self._load_fill_dict()
        line21 = _safe_float(fill.get('F113') or 0)
        rent   = self._get_is_agg('rent_income')
        if rent > 0.01 and abs(line21) < 0.01:
            return self.format_issue(
                'F8NI-R01', self.ERROR,
                f"Line 21 (Net Rental Income/Loss) is blank, but the LLC received "
                f"${rent:,.2f} in rental income. Line 21 flows to Schedule K Line 2 "
                f"and each partner's K-1 Box 2. A blank Line 21 omits the rental "
                f"result from all partners' returns (IRC §702(a)).",
                'Form 8825 Instructions Line 21; IRC §702(a); Schedule K Line 2',
                "Update bookNS — confirm IS.net_rental is mapped and the GL has "
                "propNm set on all income/expense entries.",
                fids=['F113'])

    def _rule_line21_mismatch(self):
        """
        F8NI-R02: Line 21 (Net Rental Income/Loss) differs from GL net rental.

        ACCOUNTING NOTE — Year-End Closing Entries:
        Standard double-entry practice closes all Income/Expense accounts to
        Partners' Capital at year-end, leaving IS balances at $0. After closing,
        IS.net_rental from taxAggregates() = $0, but Form 8825 Line 21 must still
        report the ANNUAL net rental income/loss (the pre-close activity).

        This rule accounts for three cases:
        1. IS.net_rental = 0 (year-end closed): Line 21 from per-property GL
           aggregation is correct; fire INFO only (not an error).
        2. Discrepancy equals CIP expense gap: already reported by F8NI-R04;
           skip to avoid duplicate alerts.
        3. Unexplained discrepancy: true Books-First violation; fire ERROR.
        """
        fill   = self._load_fill_dict()
        net    = self._get_is_agg('net_rental')
        line21 = _safe_float(fill.get('F113') or 0)

        if abs(line21) < 0.01:
            return None     # handled by F8NI-R01

        gap = round(abs(line21 - net), 2)
        if gap <= 1.00:
            return None     # within rounding — handled by F8NI-R03

        # Case 1: IS.net_rental = 0 — year-end closing entries zeroed IS accounts
        if abs(net) < 0.01:
            return self.format_issue(
                'F8NI-R02', self.INFO,
                f"Line 21 (Net Rental Income/Loss) = ${line21:,.2f} (from per-property GL). "
                f"IS.net_rental = $0.00 — year-end closing entries have zeroed IS accounts, "
                f"which is standard accounting practice. "
                f"Line 21 correctly reflects the annual pre-close activity.",
                'IRC §446; double-entry closing procedure; Form 8825 Line 21',
                "No action required — year-end close is expected.")

        # Case 2: Gap explained by CIP expenses (already flagged by F8NI-R04)
        total_exp  = self._get_is_agg('total_expenses')
        active_col = 0.0
        for col in range(4):
            active_col += _safe_float(fill.get(f'F{95 + col:03d}', 0))
        cip_gap = round(total_exp - active_col, 2)
        if abs(gap - cip_gap) <= 1.00:
            return None     # discrepancy is the CIP gap; F8NI-R04 covers it

        # Case 3: Unexplained discrepancy
        return self.format_issue(
            'F8NI-R02', self.ERROR,
            f"Line 21 (Net Rental Income/Loss) = ${line21:,.2f} but "
            f"GL net rental = ${net:,.2f}. "
            f"Unexplained gap of ${gap:,.2f} — this flows to Schedule K Line 2 "
            f"and each partner's K-1 Box 2 (IRC §446, §702).",
            'IRC §446; Form 8825 Line 21; Schedule K Line 2; IRC §702(a)',
            "Audit GL — compare per-property income and expenses to identify "
            "the unaccounted amount.",
            fids=['F113'])

    def _rule_line21_confirmed(self):
        """F8NI-R03: Line 21 (Net Rental Income/Loss) confirmed — ready for Schedule K."""
        fill   = self._load_fill_dict()
        line21 = _safe_float(fill.get('F113') or 0)
        net    = self._get_is_agg('net_rental')
        # Confirmed if: Line 21 is non-zero AND (matches IS.net_rental OR IS is YE-closed)
        ye_closed = abs(net) < 0.01
        matches   = abs(line21 - net) <= 1.00
        if abs(line21) > 0.01 and (matches or ye_closed):
            label = 'net rental income' if line21 >= 0 else 'net rental loss'
            return self.format_issue(
                'F8NI-R03', self.INFO,
                f"Line 21 (Net Rental Income/Loss) = ${line21:,.2f} ({label}). "
                f"Flows to Schedule K Line 2, then each partner's K-1 Box 2 "
                f"(IRC §469(c)(2) passive activity).",
                'Form 8825 Line 21; Schedule K Line 2; IRC §469(c)(2)',
                "No action required.")


# ════════════════════════════════════════════════════════════════════════════
#  FORM8825AGENT  (Tier 1 orchestrator)
# ════════════════════════════════════════════════════════════════════════════

class Form8825Agent(IRSFormsAgent):
    """
    Tier 1 orchestrator — sequences 4 section agents through pass 1+2.
    Books-First: all values from stmtIS.taxAggregates(); Line 14 from IS.depreciation.
    """

    _SECTION_ORDER = [
        AgentF8825_Properties,
        AgentF8825_Income,
        AgentF8825_Expenses,
        AgentF8825_NetIncome,
    ]

    def __init__(self, llc, tax_year: Optional[int] = None):
        super().__init__(llc, tax_year)
        self._agents: List[_SectionAgent] = [
            cls(llc, self.tax_year) for cls in self._SECTION_ORDER
        ]

    # ── Public API ────────────────────────────────────────────────────────────

    def run_phases_1_2(self) -> Dict[str, Any]:
        sections_state = {}
        overall_halt   = 0

        for agent in self._agents:
            p1 = agent.pass1_auto_fill()
            p2 = agent.pass2_audit()

            issues  = p2.get('issue_list', [])
            state   = p2.get('ready_state', self.GO)
            summary = (agent.pass5_summarize()
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

        overall_state = self.NEEDS_FIXING if overall_halt > 0 else self.GO

        session = {
            'tax_year':      self.tax_year,
            'last_run':      _now_iso(),
            'overall_state': overall_state,
            'sections':      sections_state,
        }
        self._save_session_state(session)
        return session

    def getSummary(self) -> Dict[str, Any]:
        state = self._load_session_state()
        if state is None:
            return self.run_phases_1_2()   # no cache → run fresh
        # Auto-refresh: if any source data file is newer than the session state,
        # re-run so the UI never shows stale results after a GL edit.
        if self._session_is_stale(state):
            return self.run_phases_1_2()
        return state

    def _session_is_stale(self, state: Dict[str, Any]) -> bool:
        """True if any ledger source file is newer than the saved session state."""
        last_run_str = state.get('last_run')
        if not last_run_str:
            return True
        try:
            last_run_ts = datetime.fromisoformat(
                last_run_str.replace('Z', '+00:00')).timestamp()
        except Exception:
            return True
        # Instantiate the canonical source DBs and check their file mtimes.
        try:
            from ledger.llcExpRev import llcExpRev
            from ledger.llcAssets import llcAssets
            for db_cls in (llcExpRev, llcAssets):
                try:
                    db_path = Path(db_cls(self.llc).FN())
                    if db_path.exists() and db_path.stat().st_mtime > last_run_ts:
                        return True
                except Exception:
                    pass
        except ImportError:
            pass
        return False

    # ── Session state persistence ─────────────────────────────────────────────

    def _session_state_path(self) -> Optional[Path]:
        d = self._agent_work_dir()
        if d is None:
            return None
        return d / 'Form8825_session_state.json'

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

    def _empty_summary(self) -> Dict[str, Any]:
        sections = []
        for cls in self._SECTION_ORDER:
            sections.append({
                'agent':         cls.AGENT_KEY,
                'label':         cls.LABEL,
                'state':         self.NOT_STARTED,
                'summary':       'Not yet run',
                'halt_count':    0,
                'resolve_count': 0,
                'review_count':  0,
            })
        return {
            'tax_year':      self.tax_year,
            'last_run':      None,
            'overall_state': self.NOT_STARTED,
            'sections':      sections,
        }

    def run_agent(self) -> Dict[str, Any]:
        '''
        Full agent cycle: audit → (if GO) generate FILL.pdf.

        Returns the run_phases_1_2 session dict with an optional 'pdf' key
        added when generation succeeds.  Callers check overall_state:
          GO           → FILL.pdf written; pdf dict present
          NEEDS_FIXING → audit issues must be resolved; pdf key absent
        '''
        session = self.run_phases_1_2()
        if session.get('overall_state') == self.GO:
            try:
                from irs.BookToIRS import BookToIRS
                pdf_result = BookToIRS(self.llc, 'Form8825').regenerate()
                session['pdf'] = pdf_result
            except Exception as exc:
                session['pdf'] = {'error': str(exc)}
        return session

    @staticmethod
    def _first_halt_message(issues: List[Dict]) -> str:
        for i in issues:
            if i.get('severity') == 'ERROR':
                return i.get('message', 'Error — see Guided Review')
        return issues[0]['message'] if issues else ''
