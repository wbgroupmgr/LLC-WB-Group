"""
Form4562Agent — Tier 1 orchestrator for IRS Form 4562 (Depreciation and Amortization).

Architecture (4-tier):
  Tier 0  LLCTaxAgent        — cross-form audit + submission
  Tier 1  Form4562Agent       — this file; orchestrates 3 section agents
  Tier 2  AgentF4562_*        — one per Form 4562 Part (also this file)
  Tier 3  IRSFormsAgent       — common services base class

Form 4562 Parts covered:
  Part I   (§179)  — $0 for residential rental; IRC §179(d)(1) explicit exclusion
  Part III (MACRS) — Line 19h residential rental; 27.5-yr, MM conv, S/L method
  Part IV  (Summary Line 22) — cross-form audit anchor: must = IS.depreciation

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
        """Return the month number (1-12) from the placed-in-service date."""
        d = self._get_placed_in_service()
        if not d:
            return None
        # Expect formats: 'YYYY-MM-DD', 'MM/DD/YYYY', 'M/YYYY', '8/25', 'August 2025'
        import re
        # ISO
        m = re.match(r'(\d{4})-(\d{2})-\d{2}', d)
        if m:
            return int(m.group(2))
        # MM/DD/YYYY or M/D/YYYY
        m = re.match(r'(\d{1,2})/(\d{1,2})/\d{4}', d)
        if m:
            return int(m.group(1))
        # M/YY short form (e.g. "8/25")
        m = re.match(r'(\d{1,2})/\d{2,4}$', d)
        if m:
            return int(m.group(1))
        # Month name
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
            f"Form 4562 Part I Line 12 (§179 Deduction) = $0 for W&B Group. "
            f"IRC §179(d)(1) explicitly excludes residential rental property. "
            f"IRC §50(b)(2): property used to furnish lodging is ineligible for §179. "
            f"Part I Line 1 shows ${self._SEC179_LIMIT_2024:,.0f} statutory limit "
            f"(Rev. Proc. 2023-34) — informational only; Line 12 = $0.",
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
                f"Form 4562 Line 12 (§179 Deduction) = ${line12:,.2f}. "
                f"Must be $0 for residential rental property. "
                f"IRC §179(d)(1): residential rental buildings are categorically excluded from §179. "
                f"IRC §6662: accuracy-related penalty (20%) applies to disallowed §179 deductions.",
                'IRC §179(d)(1); IRC §50(b)(2); IRC §6662',
                "Remove the §179 deduction from Line 12. Set to $0. "
                "The building depreciates under MACRS Part III (27.5-yr S/L) only.",
                fids=['F4562_P1_L12'])


# ────────────────────────────────────────────────────────────────────────────
#  AgentF4562_MACRS — Part III: MACRS Depreciation (Line 19h)
# ────────────────────────────────────────────────────────────────────────────

class AgentF4562_MACRS(_SectionAgent):
    """
    IRS Knowledge Base — Form 4562 Part III Section A: MACRS (Line 19h)

    Line 19h: Residential rental property
      Col (b): Month/year placed in service (e.g., "8/25" for August 2025)
      Col (c): Depreciable basis = building cost ONLY (land excluded — never depreciable)
      Col (d): Recovery period = 27.5 years (IRC §168(c))
      Col (e): Convention = MM (mid-month) — IRC §168(d)(2)
      Col (f): Method = S/L (straight-line) — IRC §168(b)(3)(B)
      Col (g): Depreciation amount = IS.depreciation from books (Books-First)

    Depreciable basis (CRITICAL — land exclusion):
      IRS rule: land is never depreciable (IRC §167; Reg. §1.167(a)-2).
      The depreciable basis = total acquisition cost − land value − non-depreciable items.
      For H_805HighMesa: llcAssets Acct.Fixed.Land = $79,438.41 is excluded.
      Depreciable basis ≈ Acct.Fixed.Tangible.InService = $142,884.48.

    MACRS Year 1 formula (mid-month convention):
      Annual depreciation = depreciable_basis / 27.5
      Year 1 = annual × ((12.5 − placed_month) / 12)
      For August 2025 (month=8): Year 1 = (basis/27.5) × (4.5/12)

    Books-First: Col (g) MUST equal IS.depreciation from books.
    The formula is used for verification only — if formula ≠ books, the books
    have an error that must be corrected BEFORE filing.
    """

    LABEL            = 'MACRS Depreciation (Part III Line 19h)'
    AGENT_KEY        = 'AgentF4562_MACRS'
    LOGICAL_PREFIXES = ['F45M_']

    _RECOVERY_PERIOD  = 27.5  # residential rental, IRC §168(c)
    _CONVENTION       = 'MM'   # mid-month, IRC §168(d)(2)
    _METHOD           = 'S/L'  # straight-line, IRC §168(b)(3)(B)

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
        basis  = sum(_safe_float(r.get('amt', r.get('amount', 0)))
                     for r in self._get_tangible_inservice())
        return (f"MACRS Line 19h: H_805HighMesa placed {placed}, "
                f"basis ≈ ${basis:,.2f}, 27.5yr S/L MM, "
                f"Col (g) = ${depr:,.2f} (= IS.depreciation, Books-First).")

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
                f"No Acct.Fixed.Tangible.InService records found in llcAssets, "
                f"but IS.depreciation = ${depr:,.2f}. "
                f"Form 4562 Part III Line 19h requires a depreciable asset record. "
                f"IRC §168(a): MACRS requires property 'placed in service' — "
                f"verify the llcAssets entry has acctSub = Acct.Fixed.Tangible.InService.",
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
                "Placed-in-service date not found in llcAssets for any tangible property. "
                "Form 4562 Part III Line 19h Col (b) requires the month and year placed in service. "
                "IRC §168(a): MACRS begins on the placed-in-service date. "
                "Without it, Year 1 depreciation (including mid-month convention) cannot be computed.",
                'IRC §168(a); Form 4562 Instructions Part III Col (b)',
                "Set dateInService (or placed_in_service) in the llcAssets record for H_805HighMesa. "
                "Format: 'YYYY-MM-DD' or 'MM/DD/YYYY'. August 2025 → Col (b) = '8/25'.")

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
            land_total = sum(_safe_float(r.get('amt', r.get('amount', 0))) for r in land_rows)
            tang_total = sum(_safe_float(r.get('amt', r.get('amount', 0))) for r in tang_rows)
            return self.format_issue(
                'F45M-R03', self.WARN,
                f"Land records found in llcAssets (Acct.Fixed.Land = ${land_total:,.2f}). "
                f"Verify Form 4562 Col (c) uses ONLY the tangible depreciable basis "
                f"(Acct.Fixed.Tangible.InService = ${tang_total:,.2f}) and NOT the land value. "
                f"IRC §167; Reg. §1.167(a)-2: land is never depreciable. "
                f"Correct Col (c) = ${tang_total:,.2f} (excludes land ${land_total:,.2f}).",
                'IRC §167; Treas. Reg. §1.167(a)-2; Form 4562 Instructions Col (c)',
                f"Confirm Form 4562 Part III Line 19h Col (c) = ${tang_total:,.2f} "
                f"(tangible basis only). Land ${land_total:,.2f} is never depreciable.",
                fids=['F4562_L19h_c'])

    def _rule_column_g_mismatch(self):
        """
        F45M-R04: Column (g) depreciation amount ≠ IS.depreciation — Books-First violation.
        IRC §446 + §703: books are the authoritative source for all form dollar amounts.
        Column (g) MUST equal IS.depreciation from the books.
        If the fill dict shows a different amount (e.g., because someone entered a
        manually computed MACRS figure), it must be corrected to match IS.depreciation.
        The MACRS formula in F45M-R05 is a verification check — it does not override
        the books value.
        """
        fill = self._load_fill_dict()
        depr = self._get_is_agg('depreciation')
        col_g = _safe_float(fill.get('F4562_L19h_g') or fill.get('F4562_ColG')
                            or fill.get('MACRS_depr') or 0)
        if col_g > 0.01 and abs(col_g - depr) > 1.00:
            return self.format_issue(
                'F45M-R04', self.ERROR,
                f"Form 4562 Part III Line 19h Col (g) = ${col_g:,.2f} but "
                f"IS.depreciation = ${depr:,.2f}. Discrepancy: ${abs(col_g - depr):,.2f}. "
                f"Books-First violation (IRC §446): Col (g) must equal IS.depreciation from books. "
                f"The MACRS formula is a verification tool — it does not override the books value.",
                'IRC §446; IRC §703; Form 4562 Instructions Col (g)',
                "Fix the fill dict: Form 4562 Line 19h Col (g) must map to IS.depreciation "
                f"(${depr:,.2f}). If the formula gives a different amount, the books entry "
                "may have an error — correct the ledger before filing.",
                fids=['F4562_L19h_g'])

    def _rule_macrs_formula_check(self):
        """
        F45M-R05: MACRS Year 1 formula verification.
        Compute expected depreciation using the IRS mid-month convention formula
        and compare against IS.depreciation. If they differ by > $10, flag for CPA review.

        Formula (IRC §168; Pub 946 Table A-6):
          Annual = depreciable_basis / 27.5
          Year 1 = Annual × ((12.5 - placed_month) / 12)

        For August 2025 (month=8):
          Year 1 = (basis / 27.5) × ((12.5 - 8) / 12) = (basis / 27.5) × (4.5 / 12)

        This is a verification rule — it does not modify the books or the fill dict.
        A difference > $10 may indicate: (a) wrong placed-in-service month in llcAssets,
        (b) wrong depreciable basis (land not excluded), or (c) a books entry error.
        """
        depr = self._get_is_agg('depreciation')
        if depr < 0.01:
            return None

        tang_rows = self._get_tangible_inservice()
        if not tang_rows:
            return None

        basis = sum(_safe_float(r.get('amt', r.get('amount', 0))) for r in tang_rows)
        month = self._get_placed_month()

        if not basis or not month:
            return None

        # Mid-month convention: property placed in month M gets (12.5 - M)/12 of annual depr
        annual   = basis / self._RECOVERY_PERIOD
        expected = round(annual * ((12.5 - month) / 12), 2)

        if abs(expected - depr) > 10.00:
            return self.format_issue(
                'F45M-R05', self.INFO,
                f"MACRS Year 1 formula verification: "
                f"basis ${basis:,.2f} / 27.5 × ((12.5-{month})/12) = ${expected:,.2f}. "
                f"IS.depreciation = ${depr:,.2f}. Difference = ${abs(expected - depr):,.2f}. "
                f"If difference > $10, possible causes: wrong placed-in-service month, "
                f"land not excluded from basis, or a books entry error. CPA review recommended.",
                'IRC §168; Pub 946 Appendix A Table A-6; Rev. Proc. 87-57',
                f"Verify: (1) placed-in-service date is month {month} (correct?), "
                f"(2) depreciable basis ${basis:,.2f} excludes land, "
                f"(3) IS.depreciation entry in llcAssets is ${depr:,.2f}. "
                "If books are correct, the small difference may be due to rounding — "
                "file with IS.depreciation (Books-First).",
                fids=['F4562_L19h_g', 'F4562_L19h_b', 'F4562_L19h_c'])


# ────────────────────────────────────────────────────────────────────────────
#  AgentF4562_Summary — Part IV Line 22
# ────────────────────────────────────────────────────────────────────────────

class AgentF4562_Summary(_SectionAgent):
    """
    IRS Knowledge Base — Form 4562 Part IV: Summary (Line 22)

    Part IV Line 22: Total depreciation claimed.
    For this LLC: Line 22 = Part III MACRS amounts = IS.depreciation.

    Line 22 is the CROSS-FORM AUDIT ANCHOR:
      LLCTaxAgent XF-R01 verifies:
        Form 4562 Line 22 == Form 8825 Line 14 == IS.depreciation

    Both Form 4562 Line 22 and Form 8825 Line 14 are independently sourced
    from IS.depreciation (Books-First). The XF-R01 audit confirms they agree.
    If they don't agree, at least one form has a books-mapping error.

    IRC §446: all form values must derive from books.
    Form 4562 Instructions Part IV: "Line 22. Total. Add amounts from Lines
    12, 14 and 17. See instructions for where to report this amount."
    """

    LABEL            = 'Summary Line 22 (Part IV)'
    AGENT_KEY        = 'AgentF4562_Summary'
    LOGICAL_PREFIXES = ['F45L_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_line22_blank,
            self._rule_line22_mismatch,
            self._rule_line22_confirmed,
        ])

    def pass5_summarize(self) -> str:
        depr = self._get_is_agg('depreciation')
        return (f"Part IV Line 22 = ${depr:,.2f} (= IS.depreciation, Books-First). "
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
        """
        fill   = self._load_fill_dict()
        depr   = self._get_is_agg('depreciation')
        # F153 = bookNS Form4562 fid for Line 22 (Acct.Exp.Depreciation)
        # F074 = Col (g) for Line 19h; both should equal IS.depreciation
        line22 = _safe_float(fill.get('F153') or fill.get('F074') or 0)
        if depr > 0.01 and line22 < 0.01:
            return self.format_issue(
                'F45L-R01', self.ERROR,
                f"Form 4562 Part IV Line 22 (F153) is blank but IS.depreciation = ${depr:,.2f}. "
                f"Line 22 must equal IS.depreciation (Books-First: IRC §446). "
                f"CAUTION: IRC §1016(a)(2) requires basis reduction by the amount ALLOWABLE "
                f"even if not claimed — failing to report depreciation now causes a double "
                f"deduction problem at disposition.",
                'IRC §168; IRC §1016(a)(2); IRC §446; Form 4562 Part IV Line 22',
                "Verify bookNS_IS.json maps IS.depreciation → Form 4562 Line 22. "
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
        """
        fill   = self._load_fill_dict()
        depr   = self._get_is_agg('depreciation')
        line22 = _safe_float(fill.get('F153') or fill.get('F074') or 0)
        if line22 > 0.01 and abs(line22 - depr) > 1.00:
            return self.format_issue(
                'F45L-R02', self.ERROR,
                f"Form 4562 Line 22 (F153) = ${line22:,.2f} but IS.depreciation = ${depr:,.2f}. "
                f"Discrepancy: ${abs(line22 - depr):,.2f}. Books-First violation (IRC §446). "
                f"Line 22 is the XF-R01 cross-form audit anchor — if it doesn't match "
                f"IS.depreciation, the cross-form audit will flag an inconsistency with "
                f"Form 8825 Line 14 (also sourced from IS.depreciation).",
                'IRC §446; IRC §703; Form 4562 Line 22; LLCTaxAgent XF-R01',
                "Fix bookNS_IS.json Form4562 section: f153 must map to Acct.Exp.Depreciation. "
                "Re-run BookToIRS pipeline.")

    def _rule_line22_confirmed(self):
        """
        F45L-R03: Line 22 = IS.depreciation confirmed — XF-R01 anchor is set.
        F153 (Line 22) and F074 (Col g) both = IS.depreciation.
        LLCTaxAgent XF-R01 will cross-check: F4562 F153 == Form 8825 F079 == IS.depreciation.
        """
        fill   = self._load_fill_dict()
        depr   = self._get_is_agg('depreciation')
        line22 = _safe_float(fill.get('F153') or fill.get('F074') or 0)
        if depr > 0.01 and abs(line22 - depr) <= 1.00:
            return self.format_issue(
                'F45L-R03', self.INFO,
                f"Form 4562 Part IV Line 22 = ${line22:,.2f} = IS.depreciation confirmed. "
                f"Cross-form audit anchor (XF-R01) is set. "
                f"LLCTaxAgent will verify: F4562 L22 == F8825 L14 == IS.depreciation = ${depr:,.2f}.",
                'Form 4562 Part IV; LLCTaxAgent XF-R01; IRC §446',
                "No action required. XF-R01 runs in LLCTaxAgent.phase2_xf_audit().")


# ════════════════════════════════════════════════════════════════════════════
#  FORM4562AGENT  (Tier 1 orchestrator)
# ════════════════════════════════════════════════════════════════════════════

class Form4562Agent(IRSFormsAgent):
    """
    Tier 1 orchestrator — sequences 3 section agents through pass 1+2.
    Books-First: IS.depreciation is the canonical source for all dollar values.
    §179 = $0 (IRC §179(d)(1)). MACRS Part III Line 19h: 27.5yr, MM, S/L.
    """

    _SECTION_ORDER = [
        AgentF4562_Sec179,
        AgentF4562_MACRS,
        AgentF4562_Summary,
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

    @staticmethod
    def _first_halt_message(issues: List[Dict]) -> str:
        for i in issues:
            if i.get('severity') == 'ERROR':
                return i.get('message', 'Error — see Guided Review')
        return issues[0]['message'] if issues else ''
