"""
Form4562Agent — Tier 1 orchestrator for IRS Form 4562 (Depreciation and Amortization).

Architecture (4-tier):
  Tier 0  LLCTaxAgent        — cross-form audit + submission
  Tier 1  Form4562Agent       — this file; orchestrates 6 section agents (one per Part)
  Tier 2  AgentF4562_*        — one per Form 4562 Part I–VI (also this file)
  Tier 3  IRSFormsAgent       — common services base class

Form 4562 has 6 Parts — one section agent per Part:
  Part I   AgentF4562_Sec179       — §179 deduction; $0 (buildings excluded per §179(d)(1))
  Part II  AgentF4562_SpecialDepr  — Bonus/special depreciation; $0 (27.5-yr not eligible)
  Part III AgentF4562_MACRS        — MACRS Line 19h residential rental; books-verified
  Part IV  AgentF4562_Summary      — Line 22 total = IS.depreciation; XF-R01 anchor
  Part V   AgentF4562_ListedProp   — §280F listed property; $0 (no vehicles/§280F assets)
  Part VI  AgentF4562_Amortization — §197/§195 amortization; advisory (check closing costs)

Even Parts II, V, VI with $0 values have expert section agents that explicitly
declare why $0 is correct, advise on what WOULD require entries, and confirm
IRS compliance. Bookkeeper dialog shows all 6 Parts.

Books-First rule (IRC §446+703): column (g) and Line 22 sourced from IS.depreciation.
The agent VERIFIES the MACRS formula is consistent with books — it does NOT compute
and override the books value.

Session state stored at:
  books/{year}/Forms/.agent_work/Form4562_session_state.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib  import Path
from typing   import Any, Dict, List, Optional

from irs.taxAgents.IRSFormsAgent import IRSFormsAgent
from irs.irsDepreciation import (
    net_tangible_basis, macrs_residential_year1, verify_depreciation,
    MACRS_RECOVERY_YEARS, FORMULA_TOLERANCE,
)


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
    """Common base for all Form 4562 section agents."""

    LABEL        = ''
    AGENT_KEY    = ''
    LOGICAL_PREFIXES: List[str] = []

    def __init__(self, llc, tax_year: int):
        super().__init__(llc, tax_year)
        self._is_data    = None
        self._fill_cache = None
        self._assets_raw = None

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

    def _get_assets(self) -> List[Dict]:
        """Load all llcAssets rows."""
        if self._assets_raw is not None:
            return self._assets_raw
        try:
            from ledger.llcAssets import llcAssets
            assets_obj = llcAssets(self.llc)
            self._assets_raw = assets_obj.load() if hasattr(assets_obj, 'load') else []
        except Exception:
            self._assets_raw = []
        return self._assets_raw

    def _get_tangible_inservice(self) -> List[Dict]:
        """Return rows where acct = Acct.Fixed.Tangible.InService."""
        rows = self._get_assets()
        return [r for r in rows
                if 'tangible.inservice' in str(r.get('acct', '')).lower()
                or 'tangible.inservice' in str(r.get('acctSub', '')).lower()]

    def _get_land_rows(self) -> List[Dict]:
        """Return rows where acct = Acct.Fixed.Land (excluded from depreciable basis)."""
        rows = self._get_assets()
        return [r for r in rows
                if str(r.get('acct', '')).lower() == 'acct.fixed.land'
                or 'fixed.land' in str(r.get('acct', '')).lower()]

    def _get_placed_in_service(self) -> Optional[str]:
        """Return placed-in-service date from llcAssets tangible rows.
        Checks dateInService, placed_in_service, acqDate, date, and dt fields.
        """
        for row in self._get_tangible_inservice():
            d = (row.get('dateInService') or row.get('placed_in_service')
                 or row.get('acqDate') or row.get('date') or row.get('dt') or '')
            if d:
                return str(d)
        return None

    def _get_placed_month(self) -> Optional[int]:
        """Return the month number (1-12) from the placed-in-service date.

        Handles all date formats used in llcAssets:
          'YYYY.MM.DD'   — books standard (dt field)  e.g. '2025.08.20'
          'YYYY-MM-DD'   — ISO                         e.g. '2025-08-20'
          'MM/DD/YYYY'   — US format                   e.g. '08/20/2025'
          'M/YY'         — form short form              e.g. '8/25'
          'August 2025'  — month-name form
        """
        d = self._get_placed_in_service()
        if not d:
            return None
        import re
        # YYYY.MM.DD — books standard (dt field uses dots)
        m = re.match(r'\d{4}\.(\d{2})\.\d{2}', d)
        if m:
            return int(m.group(1))
        # YYYY-MM-DD — ISO
        m = re.match(r'\d{4}-(\d{2})-\d{2}', d)
        if m:
            return int(m.group(1))
        # MM/DD/YYYY or M/D/YYYY
        m = re.match(r'(\d{1,2})/(\d{1,2})/\d{4}', d)
        if m:
            return int(m.group(1))
        # M/YY short form (e.g. "8/25")
        m = re.match(r'(\d{1,2})/\d{2,4}$', d)
        if m:
            return int(m.group(1))
        # Month name (e.g. 'August 2025')
        months = {'january': 1, 'february': 2, 'march': 3, 'april': 4,
                  'may': 5, 'june': 6, 'july': 7, 'august': 8,
                  'september': 9, 'october': 10, 'november': 11, 'december': 12}
        dl = d.lower()
        for nm, num in months.items():
            if nm in dl:
                return num
        return None

    def _load_fill_dict(self) -> Dict[str, Any]:
        """Load Form 4562 fill dict via stmtIS_Tax if available; else empty."""
        if self._fill_cache is not None:
            return self._fill_cache
        try:
            from ledger.stmtIS import stmtIS_Tax
            tax = stmtIS_Tax(self.llc)
            self._fill_cache = tax.loadFillDict('Form4562') or {}
        except Exception:
            self._fill_cache = {}
        return self._fill_cache

    # ── Pass interface ────────────────────────────────────────────────────────

    def pass1_auto_fill(self) -> Dict[str, Any]:
        fill_dict = self._load_fill_dict()
        completeness = self.audit_fill_completeness(fill_dict, self.LOGICAL_PREFIXES)
        return {'section': self.AGENT_KEY, 'tax_year': self.tax_year, **completeness}

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
        return {k: v for k, v in fill.items()
                if any(k.startswith(p) for p in self.LOGICAL_PREFIXES)}

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
#  AgentF4562_Sec179 — Part I: Section 179 Deduction
# ────────────────────────────────────────────────────────────────────────────

class AgentF4562_Sec179(_SectionAgent):
    """
    IRS Knowledge Base — Form 4562 Part I: Section 179 Deduction

    IRC §179(d)(1): The term 'section 179 property' explicitly EXCLUDES property
    described in IRC §50(b). IRC §50(b)(2) excludes property used predominantly
    in a rental activity. Residential rental buildings are therefore categorically
    ineligible for the §179 deduction.

    Form 4562 Part I:
      Line 1:  §179 dollar limit = $1,220,000 (2024, Rev. Proc. 2023-34).
               This is a statutory number — not a deduction, just the cap.
      Line 12: §179 deduction = $0 for W&B Group.
               Any non-zero value on Line 12 is an IRS violation for residential rental.

    Note: The 2024 §179 limit is $1,220,000 (indexed annually for inflation).
    Even if W&B Group had eligible personal property (furniture, appliances),
    the §179 deduction for rental property held for investment (as opposed to
    active trade or business) is generally disallowed. The safer, correct position
    for this LLC is $0 §179 on all items.
    """

    LABEL            = 'Section 179 (Part I)'
    AGENT_KEY        = 'AgentF4562_Sec179'
    DIAG_SEC_ID      = 'PartI'
    LOGICAL_PREFIXES = ['F45S_']

    # 2024 statutory limit (Rev. Proc. 2023-34)
    _SEC179_LIMIT_2024 = 1_220_000.0

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_sec179_confirmed_zero,
            self._rule_sec179_violation,
        ])

    def pass5_summarize(self) -> str:
        return ("Part I (§179): $0 deduction — correct per IRC §179(d)(1). "
                f"Statutory limit ${self._SEC179_LIMIT_2024:,.0f} shown on Line 1 (informational).")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_sec179_confirmed_zero(self):
        """
        F45S-R01: §179 = $0 — confirmed correct for residential rental buildings.
        IRC §179(d)(1) explicitly excludes property described in IRC §50(b).
        IRC §50(b)(2) excludes property "used predominantly to furnish lodging or
        in connection with the furnishing of lodging." Residential rental = $0 §179.
        This is a statutory prohibition, not a CPA judgment call.
        """
        return self.format_issue(
            'F45S-R01', self.INFO,
            f"✓ $0 §179 deduction — correct for a residential rental building.\n"
            f"  • Residential rental property cannot use the §179 immediate write-off (excluded by statute).\n"
            f"  • Line 12 = $0. Line 1 shows the ${self._SEC179_LIMIT_2024:,.0f} annual cap (informational only).",
            'IRC §179(d)(1); IRC §50(b)(2); Rev. Proc. 2023-34; Form 4562 Part I',
            "No action required. Confirm Line 12 = $0 and Line 1 = "
            f"${self._SEC179_LIMIT_2024:,.0f} in the fill dict.",
            fids=['F4562_P1_L1', 'F4562_P1_L12'])

    def _rule_sec179_violation(self):
        """
        F45S-R02: Any §179 deduction claimed for residential building → IRS violation.
        If a non-zero §179 amount appears in the fill dict for Line 12, it must be
        removed. IRS will disallow it and may assess accuracy-related penalties
        under IRC §6662 (20% of underpayment). The building is categorically ineligible.
        """
        fill   = self._load_fill_dict()
        line12 = _safe_float(fill.get('F4562_P1_L12') or fill.get('F4562_L12')
                             or fill.get('Sec179') or 0)
        if line12 > 0.01:
            return self.format_issue(
                'F45S-R02', self.ERROR,
                f"⚠ Form 4562 Line 12 shows a §179 deduction of ${line12:,.2f} — this is NOT allowed for a residential rental building.\n"
                f"  • Residential rental property is excluded from the §179 immediate write-off.\n"
                f"  • The IRS will disallow this deduction and can add a 20% accuracy penalty.\n"
                f"  • Line 12 must be set to $0.",
                'IRC §179(d)(1); IRC §50(b)(2); IRC §6662',
                "Remove the §179 deduction from Line 12. Set to $0. "
                "The building depreciates under MACRS Part III (27.5-yr S/L) only.",
                fids=['F4562_P1_L12'])


# ────────────────────────────────────────────────────────────────────────────
#  AgentF4562_MACRS — Part III: MACRS Depreciation (Line 19h)
# ────────────────────────────────────────────────────────────────────────────

class AgentF4562_MACRS(_SectionAgent):
    """
    IRS Knowledge Base — Form 4562 Part III Section B: MACRS Residential Rental

    2025 FORM CHANGE (verified from IRS XFA accessibility labels):
      Line 19h is now "50-year property" (new class in 2025 form).
      Residential rental (27.5yr) moved to Line 19i (XFA: Line19i_1/Line19i_2).
      Line 19j is nonresidential real property (39yr, was Line 19i in prior forms).

    Line 19i (Residential rental property) — columns filled:
      Col (b): Month/year placed in service — f75 (f1_74) — FILLABLE
      Col (c): Depreciable basis = net tangible, land excluded — f76 (f1_75) — FILLABLE
      Col (d): "27.5 yrs." — pre-printed readOnly by IRS in XFA (do NOT fill f77)
      Col (e): "MM"       — pre-printed readOnly by IRS in XFA (do NOT fill f78)
      Col (f): "S/L"      — pre-printed readOnly by IRS in XFA (do NOT fill f79)
      Col (g): Depreciation amount = IS.depreciation — f80 (f1_79) — FILLABLE

    Why cols (d)/(e)/(f) are NOT filled:
      The 2025 IRS XFA marks f77/f78/f79 with access="readOnly" and pre-populates
      "27.5 yrs. / MM / S/L" as caption text. Attempting to fill them overwrites nothing
      visible — the pre-printed values always show. This is by IRS design: residential
      rental always uses 27.5yr GDS, MM, S/L; the IRS hardcodes it in the form.

    Depreciable basis (CRITICAL — land exclusion):
      IRC §167; Treas. Reg. §1.167(a)-2: land is never depreciable.
      Depreciable basis = net Acct.Fixed.Tangible.InService (Debit − Credit entries).
      For H_805HighMesa: Acct.Fixed.Land ($79,438.41) is EXCLUDED from col (c).
      Col (c) (f76) = net tangible InService balance only.

    MACRS Year 1 formula — 27.5yr, MM convention (IRC §168(d)(2)):
      Annual depreciation = depreciable_basis / 27.5
      Year 1 partial = annual × ((12.5 − placed_month) / 12)
      August 2025 (month=8): Year 1 = (basis/27.5) × (4.5/12)

    Books-First (IRC §446+703): Col (g) MUST equal IS.depreciation from books.
    Formula is verification only — if formula ≠ books, books have an error.

    fid mapping (bookNS):
      f75 = Line19i_1 col (b) — placed in service date
      f76 = Line19i_1 col (c) — depreciable basis
      f80 = Line19i_1 col (g) — current-year MACRS deduction
      f129 = Part IV Line 22 — total depreciation (equals f80 for W&B Group)
    """

    LABEL            = 'MACRS Depreciation (Part III Line 19i — Residential Rental)'
    AGENT_KEY        = 'AgentF4562_MACRS'
    DIAG_SEC_ID      = 'PartIII-19i'
    LOGICAL_PREFIXES = ['F45M_']

    _RECOVERY_PERIOD  = 27.5  # residential rental, IRC §168(c)(1)
    _CONVENTION       = 'MM'   # mid-month, IRC §168(d)(2) — pre-printed by IRS, readOnly
    _METHOD           = 'S/L'  # straight-line, IRC §168(b)(3)(B) — pre-printed by IRS, readOnly

    # fids for Line 19i col (b), (c), (g) — the three FILLABLE columns.
    # IMPORTANT: loadFillDict() normalizes all fids to uppercase "F###" format.
    # These constants must match that format for fill.get() lookups to work.
    _FID_DATE   = 'F075'   # Line19i_1 col (b): placed in service
    _FID_BASIS  = 'F076'   # Line19i_1 col (c): depreciable basis
    _FID_DEPR   = 'F080'   # Line19i_1 col (g): current-year deduction

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_no_tangible_inservice,
            self._rule_no_placed_in_service_date,
            self._rule_land_not_excluded,
            self._rule_column_g_mismatch,
            self._rule_macrs_formula_check,
        ])

    def pass5_summarize(self) -> str:
        depr   = self._get_is_agg('depreciation')
        placed = self._get_placed_in_service() or 'unknown'
        basis  = net_tangible_basis(self._get_tangible_inservice())
        return (f"MACRS Line 19i (2025 form): H_805HighMesa placed {placed}, "
                f"net basis ${basis:,.2f}, 27.5yr S/L MM (pre-printed), "
                f"f80 col (g) = ${depr:,.2f} (= IS.depreciation, Books-First).")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_no_tangible_inservice(self):
        """
        F45M-R01: No Acct.Fixed.Tangible.InService in llcAssets → MACRS cannot be computed.
        Form 4562 Part III requires at least one depreciable asset. If the ledger
        has no tangible property placed in service, the agent cannot populate
        Part III Line 19h — and if IS.depreciation > 0, there is a books inconsistency.
        IRC §168(a): MACRS applies to "recovery property" — tangible property
        placed in service after 1986.
        """
        rows = self._get_tangible_inservice()
        depr = self._get_is_agg('depreciation')
        if not rows and depr > 0.01:
            return self.format_issue(
                'F45M-R01', self.ERROR,
                f"⚠ The books show ${depr:,.2f} in depreciation but no property is recorded as 'placed in service' in the asset list.\n"
                f"  • Depreciation can only be claimed for property that has a placed-in-service record in llcAssets.\n"
                f"  • Without this record, Form 4562 Part III (Line 19i) cannot be filled.",
                'IRC §168(a); Form 4562 Instructions Part III',
                "Add or correct the llcAssets record for H_805HighMesa with "
                "acctSub = Acct.Fixed.Tangible.InService and a placed-in-service date.")

    def _rule_no_placed_in_service_date(self):
        """
        F45M-R02: Placed-in-service date missing → Form 4562 Col (b) cannot be filled.
        IRC §168(a): MACRS depreciation begins on the placed-in-service date.
        Form 4562 Instructions: Col (b) requires the month and year placed in service.
        Without this date, the Year 1 partial-year computation (mid-month convention)
        cannot be performed, and Col (b) on the form will be blank — causing IRS rejection.
        """
        placed = self._get_placed_in_service()
        if not placed:
            return self.format_issue(
                'F45M-R02', self.ERROR,
                "⚠ No placed-in-service date is recorded for the rental property.\n"
                "  • The IRS requires the exact month and year the property was first placed in rental service (Form 4562, Column b).\n"
                "  • Without this date, the Year 1 depreciation amount cannot be calculated.",
                'IRC §168(a); Form 4562 Instructions Part III Col (b)',
                "Check that the Acct.Fixed.Tangible.InService record in llcAssets_WBGroupLLC.json "
                "exists and has a non-empty date. The 'dt' field (e.g. '2025.08.20') is accepted. "
                "If missing, add: dateInService='2025-08-20' (or 'placed_in_service'). "
                "August 2025 → Form 4562 Col (b) = '8/25'.")

    def _rule_land_not_excluded(self):
        """
        F45M-R03: Depreciable basis may include land — MACRS violation.
        IRS rule: land is never depreciable (IRC §167; Reg. §1.167(a)-2).
        Form 4562 Instructions Col (c): "Enter the basis for depreciation.
        Do not include the cost of land."
        If llcAssets shows both Acct.Fixed.Land and Acct.Fixed.Tangible.InService,
        the depreciable basis in Col (c) must use only the tangible amount.
        Failure to exclude land overstates the depreciable basis, inflates depreciation,
        and may be challenged by IRS as an overstatement of deductions.
        """
        land_rows = self._get_land_rows()
        tang_rows = self._get_tangible_inservice()
        if land_rows and tang_rows:
            land_total = net_tangible_basis(land_rows)    # net land balance
            tang_total = net_tangible_basis(tang_rows)    # net depreciable basis
            return self.format_issue(
                'F45M-R03', self.WARN,
                f"Land (${land_total:,.2f}) is in the books — confirm it is NOT included in the depreciation basis on Form 4562.\n"
                f"  • Land is never depreciable; only the building structure can be written off.\n"
                f"  • Correct depreciable basis (Column c) = ${tang_total:,.2f} (building only, land excluded).",
                'IRC §167; Treas. Reg. §1.167(a)-2; Form 4562 Instructions Col (c)',
                f"Confirm Form 4562 Part III Line 19h Col (c) = ${tang_total:,.2f} "
                f"(net tangible basis: Debit − Credit entries). Land ${land_total:,.2f} never depreciable.",
                fids=['F4562_L19h_c'])

    def _rule_column_g_mismatch(self):
        """
        F45M-R04: Column (g) depreciation amount ≠ IS.depreciation — Books-First violation.
        IRC §446 + §703: books are the authoritative source for all form dollar amounts.
        Col (g) of Line 19i (f80) MUST equal IS.depreciation from the books.
        The MACRS formula in F45M-R05 is a verification check — it does not override
        the books value.
        """
        fill = self._load_fill_dict()
        depr = self._get_is_agg('depreciation')
        col_g = _safe_float(fill.get(self._FID_DEPR) or 0)
        if col_g > 0.01 and abs(col_g - depr) > 1.00:
            return self.format_issue(
                'F45M-R04', self.ERROR,
                f"⚠ Mismatch: Form 4562 depreciation (${col_g:,.2f}) doesn't match the books (${depr:,.2f}) — ${abs(col_g - depr):,.2f} difference.\n"
                f"  • The depreciation on this form must come directly from the books, not from a formula or manual entry.",
                'IRC §446; IRC §703; Form 4562 Instructions Col (g)',
                f"Fix bookNS_IS.json: {self._FID_DEPR} must map to Acct.Exp.Depreciation "
                f"(${depr:,.2f}). If the formula gives a different amount, correct the ledger.",
                fids=['F4562_L19i_g'])

    def _rule_macrs_formula_check(self):
        """
        F45M-R05: MACRS Year 1 formula verification (via irs.irsDepreciation service).

        Uses net_tangible_basis() (Debit − Credit) as the depreciable basis — NOT
        sum(all amt). This matches the GL balance computation and correctly excludes
        closing-cost credits from the depreciable cost.

        Formula (IRC §168; Pub 946 Table A-6 reproduced by irsDepreciation.macrs_residential_year1):
          net_basis  = sum(Debit amt) − sum(Credit amt) for Acct.Fixed.Tangible.InService
          annual     = net_basis / 27.5
          year1      = annual × ((12.5 − placed_month) / 12)  ← mid-month convention

        Books-First (IRC §446): IS.depreciation is the filing value. This rule verifies
        that the books entry is consistent with MACRS parameters. A discrepancy indicates
        an accounting reconciliation issue — NOT a BookToIRS mapping issue.

        Bookkeeper action: confirm that books are correct (not a "fix the mapping" issue).
        """
        depr = self._get_is_agg('depreciation')
        if depr < 0.01:
            return None

        tang_rows = self._get_tangible_inservice()
        if not tang_rows:
            return None

        basis = net_tangible_basis(tang_rows)   # Debit − Credit; matches GL balance
        month = self._get_placed_month()

        if not basis or not month:
            return None

        result = verify_depreciation(depr, basis, month, self._RECOVERY_PERIOD)
        diff   = result['diff']

        if diff <= FORMULA_TOLERANCE:
            return None  # within $1.00 rounding tolerance — no issue

        if diff > 10.00:
            severity = self.ERROR if depr > 100.0 else self.WARN
        else:
            severity = self.INFO   # $1–$10: mention but not blocking

        expected = result['expected']
        return self.format_issue(
            'F45M-R05', severity,
            f"Depreciation check: the IRS formula gives ${expected:,.2f} but the books show ${depr:,.2f} — ${diff:,.2f} difference.\n"
            f"  • Formula: ${basis:,.2f} ÷ 27.5 years × (12.5 − month {month}) ÷ 12 (partial Year 1)\n"
            f"  • This is a books accounting question — if the books are correct, file the books amount.\n"
            f"  • If the books entry was made incorrectly, fix the year-end closing entry first.",
            'IRC §168(c)(1); Pub 946 Table A-6; IRC §446 Books-First',
            f"Confirm: Is IS.depreciation = ${depr:,.2f} the correct MACRS amount for this property? "
            f"If YES → books are correct; proceed with filing IS.depreciation. "
            f"If NO → correct the YE closing entry in llcAssets (Acct.Exp.Depreciation) "
            f"to the MACRS formula result ${expected:,.2f}, then Refresh FILL.pdf.",
            fids=['F4562_L19i_g', 'F4562_L19i_b', 'F4562_L19i_c'],
            suggested_mapping={'confirm_required': True,
                               'confirm_yes': f'Books correct — file IS.depreciation ${depr:,.2f}',
                               'confirm_no':  f'Books wrong — correct to MACRS ${expected:,.2f}'})


# ────────────────────────────────────────────────────────────────────────────
#  AgentF4562_Summary — Part IV Line 22
# ────────────────────────────────────────────────────────────────────────────

class AgentF4562_Summary(_SectionAgent):
    """
    IRS Knowledge Base — Form 4562 Part IV: Summary (Line 22)

    Part IV Line 22: Total depreciation claimed.
    For this LLC: Line 22 = Part III MACRS amounts = IS.depreciation.

    Field mapping:
      f129 (shortName f2_1, page 2 first standalone field) = Part IV Line 22.
      f74  (shortName f1_73, page 1 Line19h col g)         = Part III Line 19h deduction.
      Both must equal IS.depreciation (Books-First, IRC §446).

    IMPORTANT — f153 is NOT Line 22:
      f153 (shortName f2_18) is inside Table_Ln26 BodyRow2 — this is a row in the
      Part V Listed Property table, NOT the Part IV Summary. Mapping IS.depreciation
      to f153 puts the value in Part V (Listed Property) instead of Part IV (Summary),
      leaving Line 22 blank and incorrectly filling a listed property cell.
      bookNS_IS.json uses f129 for Line 22 (corrected from the prior f153 mapping).

    Line 22 is the CROSS-FORM AUDIT ANCHOR:
      LLCTaxAgent XF-R01 verifies:
        Form 4562 Line 22 (f129) == Form 8825 Line 14 == IS.depreciation

    Both Form 4562 Line 22 and Form 8825 Line 14 are independently sourced
    from IS.depreciation (Books-First). The XF-R01 audit confirms they agree.
    If they don't agree, at least one form has a books-mapping error.

    IRC §446: all form values must derive from books.
    Form 4562 Instructions Part IV: "Line 22. Total. Add amounts from Lines
    12, 14 and 17. See instructions for where to report this amount."
    """

    LABEL            = 'Summary Line 22 (Part IV)'
    AGENT_KEY        = 'AgentF4562_Summary'
    DIAG_SEC_ID      = 'PartIV'
    LOGICAL_PREFIXES = ['F45L_']

    # Correct fid for Part IV Line 22 (first standalone text field on page 2, f2_1).
    # f153 (f2_18, Table_Ln26 BodyRow2) is in the Part V Listed Property table — NOT Line 22.
    # IMPORTANT: loadFillDict() normalizes all fids to uppercase "F###" format.
    # These constants must match that format for fill.get() lookups to work.
    # Page 2 standalone fields: f2_1(F129)=Line21 listed-property (blank for W&B Group),
    # f2_2(F130)=Line22 total depreciation — the one to fill.
    _LINE22_FID = 'F130'   # Part IV Line 22 total depreciation (page 2, f2_2)
    _COL_G_FID  = 'F080'   # Line 19i_1 col (g) depreciation deduction — same value

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_line22_blank,
            self._rule_line22_mismatch,
            self._rule_line22_confirmed,
        ])

    def pass5_summarize(self) -> str:
        depr = self._get_is_agg('depreciation')
        return (f"Part IV Line 22 (f129) = ${depr:,.2f} (= IS.depreciation, Books-First). "
                f"Cross-form audit anchor: LLCTaxAgent XF-R01 will verify "
                f"F4562 L22 == F8825 L14 == IS.depreciation.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_line22_blank(self):
        """
        F45L-R01: Line 22 blank while IS.depreciation > 0 — required field missing.
        Part IV Line 22 summarizes total depreciation. If the partnership placed
        depreciable property in service, Line 22 must be non-zero.
        A blank Line 22 means depreciation is not being claimed, which
        understates deductions and overstates taxable rental income.
        IRS: failure to claim depreciation does not allow a larger deduction
        in later years — the basis must be reduced by the amount allowable
        even if not claimed (IRC §1016(a)(2)).

        fid: f129 (shortName f2_1) = first standalone text field on page 2 = Line 22.
        bookNS_IS.json maps Acct.Exp.Depreciation → f129. Check that mapping is present.
        """
        fill   = self._load_fill_dict()
        depr   = self._get_is_agg('depreciation')
        line22 = _safe_float(fill.get(self._LINE22_FID) or fill.get(self._COL_G_FID) or 0)
        if depr > 0.01 and line22 < 0.01:
            return self.format_issue(
                'F45L-R01', self.ERROR,
                f"⚠ Form 4562 Line 22 (Total Depreciation) is blank, but the books show ${depr:,.2f} of depreciation.\n"
                f"  • Skipping depreciation doesn't save it for later — the IRS requires the property's basis be reduced even if the deduction isn't claimed.\n"
                f"  • This will result in a larger taxable gain when the property is eventually sold.",
                'IRC §168; IRC §1016(a)(2); IRC §446; Form 4562 Part IV Line 22',
                "Verify bookNS_IS.json Form4562 section maps Acct.Exp.Depreciation → f129. "
                "Re-run BookToIRS pipeline.",
                fids=['F4562_L22'])

    def _rule_line22_mismatch(self):
        """
        F45L-R02: Line 22 ≠ IS.depreciation — Books-First violation.
        This is the most critical check for Form 4562 because Line 22 is the
        cross-form audit anchor for LLCTaxAgent XF-R01.
        If Line 22 ≠ IS.depreciation, the cross-form audit will fail even if
        Form 8825 Line 14 is correct (which it should be, independently).
        A discrepancy here always indicates a books-mapping error — the fix is
        always to correct the mapping, not to adjust the form value manually.

        fid: f129 (shortName f2_1, page 2 Part IV Line 22).
        """
        fill   = self._load_fill_dict()
        depr   = self._get_is_agg('depreciation')
        line22 = _safe_float(fill.get(self._LINE22_FID) or fill.get(self._COL_G_FID) or 0)
        if line22 > 0.01 and abs(line22 - depr) > 1.00:
            return self.format_issue(
                'F45L-R02', self.ERROR,
                f"⚠ Mismatch: Form 4562 Line 22 (${line22:,.2f}) doesn't match the books (${depr:,.2f}) — ${abs(line22 - depr):,.2f} difference.\n"
                f"  • Line 22 is the total depreciation for the year and must match the books exactly.\n"
                f"  • This discrepancy also breaks the cross-check between Form 4562 and Form 8825 Line 14.",
                'IRC §446; IRC §703; Form 4562 Line 22; LLCTaxAgent XF-R01',
                "Fix bookNS_IS.json Form4562 section: f129 must map to Acct.Exp.Depreciation. "
                "Re-run BookToIRS pipeline.")

    def _rule_line22_confirmed(self):
        """
        F45L-R03: Line 22 = IS.depreciation confirmed — XF-R01 anchor is set.
        f129 (Line 22) and f74 (Col g Line 19h) both = IS.depreciation.
        LLCTaxAgent XF-R01 will cross-check: F4562 f129 == Form8825 F079 == IS.depreciation.
        """
        fill   = self._load_fill_dict()
        depr   = self._get_is_agg('depreciation')
        line22 = _safe_float(fill.get(self._LINE22_FID) or fill.get(self._COL_G_FID) or 0)
        if depr > 0.01 and abs(line22 - depr) <= 1.00:
            return self.format_issue(
                'F45L-R03', self.INFO,
                f"✓ Form 4562 Line 22 (Total Depreciation) = ${line22:,.2f} — matches the books.\n"
                f"  • Depreciation will be cross-checked against Form 8825 Line 14 to confirm both forms agree.",
                'Form 4562 Part IV; LLCTaxAgent XF-R01; IRC §446',
                "No action required. XF-R01 runs in LLCTaxAgent.phase2_xf_audit().")


# ────────────────────────────────────────────────────────────────────────────
#  AgentF4562_SpecialDepr — Part II: Special Depreciation Allowance
# ────────────────────────────────────────────────────────────────────────────

class AgentF4562_SpecialDepr(_SectionAgent):
    """
    IRS Knowledge Base — Form 4562 Part II: Special Depreciation Allowance (Lines 14–16)

    IRC §168(k): Bonus/special depreciation for qualified property.
    2025 rate: 40% (TCJA phase-down: 100%→80%→60%→40%→20%→0%).

    Eligible (IRC §168(k)(2)(A)(i)): MACRS property with recovery period ≤ 20 years.
      5-yr: appliances, carpet, furniture used in rental activity
      15-yr: land improvements (driveways, fences, landscaping)

    NOT eligible: 27.5-yr residential rental buildings (recovery period > 20 years).

    W&B Group 2025: $0 on Part II — building structure only, no 5-yr/15-yr assets.
    """

    LABEL            = 'Special Depreciation (Part II)'
    AGENT_KEY        = 'AgentF4562_SpecialDepr'
    DIAG_SEC_ID      = ''
    LOGICAL_PREFIXES = ['F45D_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_residential_not_eligible,
            self._rule_check_short_life_assets,
        ])

    def pass5_summarize(self) -> str:
        return ("Part II Special Depreciation = $0. "
                "IRC §168(k): 27.5-yr residential rental is NOT qualified property "
                "(recovery period exceeds 20-year limit). No 5-yr/15-yr assets tracked.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_residential_not_eligible(self):
        """
        F45D-R01: 27.5-yr residential rental excluded from bonus depreciation.
        IRC §168(k)(2)(A)(i): qualified property = MACRS with recovery period ≤ 20 years.
        27.5-yr exceeds the limit. Part II = $0 for the building structure.
        """
        return self.format_issue(
            'F45D-R01', self.INFO,
            "✓ $0 bonus depreciation — correct for a residential rental building.\n"
            "  • Bonus/special depreciation (40% in 2025) only applies to assets with a 20-year life or shorter.\n"
            "  • Residential rental buildings use a 27.5-year life and are not eligible.",
            'IRC §168(k)(2)(A)(i); Form 4562 Instructions Part II; TCJA 2017',
            "No action required. If W&B Group purchases 5-yr appliances or "
            "15-yr land improvements, consult CPA for Part II eligibility.")

    def _rule_check_short_life_assets(self):
        """
        F45D-R02: Advisory — 5-yr/15-yr assets would trigger Part II.
        5-yr (appliances, carpet) and 15-yr (driveways, fences) ARE eligible.
        Cost segregation studies can reclassify building components.
        """
        assets = self._get_assets()
        short_life = [r for r in assets
                      if any(kw in str(r.get('acct', '') or r.get('desc', '')).lower()
                             for kw in ('appliance', 'carpet', 'fence', 'driveway',
                                        'landscap', '5-year', '15-year', '5yr', '15yr'))]
        if short_life:
            names = ', '.join(r.get('propNm', str(r)) for r in short_life[:3])
            return self.format_issue(
                'F45D-R02', self.WARN,
                f"Possible short-lived assets found in the books: {names}.\n"
                f"  • Appliances, carpet, fences, and driveways may qualify for the 40% bonus depreciation (2025).\n"
                f"  • A CPA review is needed to confirm eligibility and calculate the Part II amount.",
                'IRC §168(k); Form 4562 Part II Lines 14-16',
                "Identify 5-yr (appliances) and 15-yr (improvements) assets. "
                "Compute 40% × eligible basis. Enter on Part II Line 14.")


# ────────────────────────────────────────────────────────────────────────────
#  AgentF4562_ListedProp — Part V: Listed Property
# ────────────────────────────────────────────────────────────────────────────

class AgentF4562_ListedProp(_SectionAgent):
    """
    IRS Knowledge Base — Form 4562 Part V: Listed Property (Lines 25–36)

    IRC §280F: Listed property = subject to extra limits due to personal/business mix.

    Listed property types (IRC §280F(d)(4)):
      - Passenger automobiles and other transportation property
      - Entertainment, recreation, amusement property
      NOTE: Computers removed from listed property by TCJA 2017 (post-12/31/2017).

    Key restrictions: §280F(a) luxury auto caps; §280F(b) ADS if business use ≤ 50%;
    §274(d) contemporaneous documentation required.

    W&B Group 2025: $0 — no vehicles or §280F property in rental business.
    """

    LABEL            = 'Listed Property (Part V)'
    AGENT_KEY        = 'AgentF4562_ListedProp'
    DIAG_SEC_ID      = ''
    LOGICAL_PREFIXES = ['F45P_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_no_listed_property,
            self._rule_check_vehicles,
        ])

    def pass5_summarize(self) -> str:
        return ("Part V (Listed Property) = $0. "
                "No vehicles or §280F property used in the rental business. "
                "Computers not listed property post-TCJA 2017.")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_no_listed_property(self):
        """
        F45P-R01: No listed property — Part V = $0.
        No vehicles, entertainment property, or other §280F listed property detected.
        TCJA 2017 removed computers from listed property (effective 2018+).
        """
        return self.format_issue(
            'F45P-R01', self.INFO,
            "✓ $0 listed property — correct for W&B Group.\n"
            "  • No vehicles or other listed property (cars, trucks) are used in the rental business.\n"
            "  • Part V is correctly blank.",
            'IRC §280F; Form 4562 Part V; TCJA 2017 §280F(d)(4) amendment',
            "No action required. If a vehicle is ever used for rental business, "
            "complete Part V and maintain a contemporaneous mileage log (§274(d)).")

    def _rule_check_vehicles(self):
        """
        F45P-R02: Vehicles in llcAssets require Part V completion.
        §280F(a) luxury auto caps limit depreciation on passenger vehicles.
        §280F(b): business use ≤ 50% requires ADS straight-line method.
        """
        assets = self._get_assets()
        vehicles = [r for r in assets
                    if any(kw in str(r.get('acct', '') or r.get('desc', '')).lower()
                           for kw in ('vehicle', 'auto', 'car', 'truck', 'van', 'suv'))]
        if vehicles:
            names = ', '.join(r.get('propNm', r.get('desc', 'unknown')) for r in vehicles[:3])
            return self.format_issue(
                'F45P-R02', self.ERROR,
                f"⚠ Vehicle(s) found in the asset list: {names}.\n"
                f"  • Vehicles are 'listed property' — the IRS imposes special limits and requires a mileage log.\n"
                f"  • Part V of Form 4562 must be completed, and annual dollar caps on the deduction apply.",
                'IRC §280F(a); §280F(b); §274(d); Form 4562 Part V',
                "Complete Part V. Document business use % with contemporaneous mileage log. "
                "Apply annual luxury auto limits from IRS Rev. Proc. updates.",
                fids=['F4562_PartV'])


# ────────────────────────────────────────────────────────────────────────────
#  AgentF4562_Amortization — Part VI: Amortization
# ────────────────────────────────────────────────────────────────────────────

class AgentF4562_Amortization(_SectionAgent):
    """
    IRS Knowledge Base — Form 4562 Part VI: Amortization (Lines 42–43)

    Common amortizable items for a rental LLC:

    IRC §709(b) — Partnership organization costs:
      Formation fees (attorney, state filing). Up to $5,000 deductible in Year 1;
      excess amortized 180 months from formation date.

    IRC §195(b) — Startup costs:
      Pre-rental expenses before business begins. Same $5,000/180-month rule.

    IRC §461(g)(2) — Loan origination points:
      Points on rental property mortgage CANNOT be immediately deducted.
      Must be amortized over the loan term. Annual amount → Form 8825 Line 12.
      This differs from primary residence rules.

    W&B Group 2025 (first year):
      No amortizable intangibles tracked in llcAssets.
      CPA should verify closing statement for points/startup/organization costs.
    """

    LABEL            = 'Amortization (Part VI)'
    AGENT_KEY        = 'AgentF4562_Amortization'
    DIAG_SEC_ID      = ''
    LOGICAL_PREFIXES = ['F45A_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_first_year_advisory,
            self._rule_closing_costs_check,
            self._rule_loan_points_advisory,
        ])

    def pass5_summarize(self) -> str:
        return ("Part VI (Amortization) = $0 per current books. "
                "First-year LLC: CPA should verify closing statement for "
                "§709/§195 costs and loan origination points (§461(g)(2)).")

    # ── Rules ────────────────────────────────────────────────────────────────

    def _rule_first_year_advisory(self):
        """
        F45A-R01: First-year LLC — organization costs may be amortizable.
        IRC §709(b): partnership formation costs (attorney, state fees) →
        up to $5,000 deductible Year 1; balance amortized 180 months.
        Currently: no Acct.Intangible.* entries in llcAssets.
        """
        assets = self._get_assets()
        has_intangible = any('intangible' in str(r.get('acct', '')).lower() or
                             'startup' in str(r.get('acct', '')).lower() or
                             'orgcost' in str(r.get('acct', '')).lower()
                             for r in assets)
        if not has_intangible:
            return self.format_issue(
                'F45A-R01', self.INFO,
                "$0 amortization — no intangible costs recorded in the books.\n"
                "  • W&B Group is in its first year — a CPA should confirm whether formation or startup costs were paid.\n"
                "  • Attorney fees and state filing fees for forming the LLC may be partially deductible (up to $5,000), with the rest spread over 15 years.\n"
                "  • Costs incurred before the property opened for rental may also qualify as startup costs under the same rules.",
                'IRC §709(b); IRC §195(b); Form 4562 Part VI Lines 42-43',
                "Review formation documents. If organization/startup costs exist, "
                "capitalize in llcAssets and complete Part VI Lines 42-43.")

    def _rule_closing_costs_check(self):
        """
        F45A-R02: Closing costs need CPA review for amortizable items.
        Closing statement may include: loan origination points (amortize over loan term),
        prepaid interest (deductible when accrued), title insurance (add to basis),
        transfer taxes (add to basis), attorney fees (may be §195 startup costs).
        Currently classified as Acct.Exp.Operating — treatment needs CPA verification.
        """
        assets = self._get_assets()
        closing_rows = [r for r in assets if 'closing' in str(r.get('acctSub', '')).lower()]
        if closing_rows:
            total = sum(_safe_float(r.get('amt', 0)) for r in closing_rows)
            return self.format_issue(
                'F45A-R02', self.WARN,
                f"${total:,.2f} in closing costs found in the books — a CPA review is needed to classify each item correctly.\n"
                f"  • Loan origination points: must be spread over the life of the loan (not a one-time deduction)\n"
                f"  • Prepaid interest: deductible in the year it accrues\n"
                f"  • Title and transfer taxes: added to the property's cost basis (increases future depreciation deduction)",
                'IRC §461(g)(2); IRC §195; IRC §263; Form 4562 Part VI; Pub 527',
                "Review closing statement line by line. Identify loan origination points. "
                "Amortize points over loan term — annual amount to Form 8825 Line 12.",
                fids=['F4562_PartVI'])

    def _rule_loan_points_advisory(self):
        """
        F45A-R03: Loan origination points on rental mortgage must be amortized.
        IRC §461(g)(2): points on non-primary-residence property cannot be
        immediately deducted. Must be amortized over the loan term.
        Annual amortization → Form 8825 Line 12 (mortgage interest/points).
        This is a structural advisory: verify with CPA at closing.
        """
        return self.format_issue(
            'F45A-R03', self.INFO,
            "Reminder: Points paid on a rental mortgage must be spread over the loan term — not deducted all at once.\n"
            "  • This is different from a primary residence, where points are often immediately deductible.\n"
            "  • The annual portion of points flows to Form 8825 Line 12 (mortgage interest).\n"
            "  • Check the H_805HighMesa closing statement to see if any origination points were paid.",
            'IRC §461(g)(2); Pub 527; Form 8825 Line 12',
            "Review H_805HighMesa closing statement for origination fees/points. "
            "If present: amortize over loan term; add annual amount to Form 8825 Line 12.")


# ════════════════════════════════════════════════════════════════════════════
#  FORM4562AGENT  (Tier 1 orchestrator)
# ════════════════════════════════════════════════════════════════════════════

class Form4562Agent(IRSFormsAgent):
    """
    Tier 1 orchestrator for Form 4562 — sequences 6 section agents (one per Part).
    Books-First: IS.depreciation is the canonical source for all dollar values.
    §179 = $0 (IRC §179(d)(1)). MACRS Part III Line 19h: 27.5yr, MM, S/L.
    Parts II, V, VI declare $0 with full IRS knowledge of why and what would change it.
    """

    _SECTION_ORDER = [
        AgentF4562_Sec179,
        AgentF4562_SpecialDepr,
        AgentF4562_MACRS,
        AgentF4562_Summary,
        AgentF4562_ListedProp,
        AgentF4562_Amortization,
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
                'section_id':    agent.AGENT_KEY,
                'diag_sec_id':   getattr(agent, 'DIAG_SEC_ID', ''),
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
            return self._empty_summary()
        return state

    # ── Session state persistence ─────────────────────────────────────────────

    def _session_state_path(self) -> Optional[Path]:
        d = self._agent_work_dir()
        if d is None:
            return None
        return d / 'Form4562_session_state.json'

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
        '''Full agent cycle: audit → (if GO) generate Form4562_FILL.pdf.'''
        session = self.run_phases_1_2()
        if session.get('overall_state') == self.GO:
            try:
                from irs.BookToIRS import BookToIRS
                pdf_result = BookToIRS(self.llc, 'Form4562').regenerate()
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
