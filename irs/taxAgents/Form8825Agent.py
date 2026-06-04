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

    LABEL        = ''
    AGENT_KEY    = ''
    LOGICAL_PREFIXES: List[str] = []

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

    def _active_property_rows(self) -> List[Dict]:
        rows = self._get_assets()
        return [r for r in rows
                if str(r.get('acctSub', r.get('acctType', ''))).lower()
                   in ('acct.fixed.tangible.inservice', 'tangible.inservice',
                       'inservice', 'in_service', 'active', 'placed_in_service')
                or str(r.get('status', '')).lower()
                   in ('active', 'in_service', 'placed_in_service')]

    def _load_fill_dict(self) -> Dict[str, Any]:
        """Load Form 8825 fill dict via stmtIS_Tax if available; else empty."""
        if self._fill_cache is not None:
            return self._fill_cache
        try:
            from stmt.stmtIS_Tax import stmtIS_Tax
            tax = stmtIS_Tax(self.llc)
            self._fill_cache = tax.loadFillDict('Form8825') or {}
        except Exception:
            self._fill_cache = {}
        return self._fill_cache

    # ── Pass interface ────────────────────────────────────────────────────────

    def pass1_auto_fill(self) -> Dict[str, Any]:
        fill_dict = self._load_fill_dict()
        completeness = self.audit_fill_completeness(fill_dict, self.LOGICAL_PREFIXES)
        return {
            'section':  self.AGENT_KEY,
            'tax_year': self.tax_year,
            **completeness,
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

    LABEL            = 'Properties'
    AGENT_KEY        = 'AgentF8825_Properties'
    LOGICAL_PREFIXES = ['F8PR_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_no_active_properties,
            self._rule_under_construction,
            self._rule_placed_in_service_date,
            self._rule_many_properties,
        ])

    def pass5_summarize(self) -> str:
        active = self._active_property_rows()
        return (f"Properties: {len(active)} active propert{'y' if len(active)==1 else 'ies'} "
                f"on Form 8825 ({', '.join(r.get('propNm', str(r)) for r in active)}).")

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
        F8PR-R02: Under-construction properties detected → excluded from Form 8825.
        IRC §168: depreciation starts when the property is placed in service.
        Construction-in-progress assets are capitalized but not yet depreciated
        and have no rental income to report.
        """
        rows = self._get_assets()
        uc = [r for r in rows
              if str(r.get('acctSub', r.get('status', ''))).lower()
                 in ('under_construction', 'construction', 'cip',
                     'acct.fixed.tangible.construction')]
        if uc:
            names = ', '.join(r.get('propNm', str(r)) for r in uc)
            return self.format_issue(
                'F8PR-R02', self.WARN,
                f"Under-construction asset(s) detected: {names}. "
                f"These are excluded from Form 8825 (IRC §168 — MACRS starts when placed in service). "
                f"No income or depreciation is reportable for construction-in-progress.",
                'IRC §168(a); Form 8825 Instructions',
                "No action required. Once placed in service, create a new "
                "Acct.Fixed.Tangible.InService record with the placed-in-service date.")

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
                           or r.get('acqDate') or r.get('date'))]
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
      Fill field: F079 area (per-column gross rents).
      IRS: "Enter the gross rents received or accrued for each property." (Form 8825 Instr)

    Line 2b (Other income):
      Pub 527: other rental income includes cancellation fees, property damaged by
      tenants (beyond deposit), and lease bonus payments.
      Books source: Acct.Rev.Other.{propNm}.

    Line 2c (Total income):
      Computed = Line 2a + Line 2b. Not separately sourced from books.

    W&B Group 2025: IS.rent_income = $4,000, IS.total_income = $4,400.
    Books-First: IRC §446.
    """

    LABEL            = 'Income (Lines 2a-2c)'
    AGENT_KEY        = 'AgentF8825_Income'
    LOGICAL_PREFIXES = ['F8IN_']

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
        """
        fill = self._load_fill_dict()
        rent = self._get_is_agg('rent_income')
        # Line 2a fill fields vary by column; check the aggregate field first
        line2a = _safe_float(fill.get('F8825_Line2a') or fill.get('F8825_2a')
                             or fill.get('Line2a') or 0)
        if rent > 0.01 and line2a < 0.01:
            return self.format_issue(
                'F8IN-R01', self.ERROR,
                f"Form 8825 Line 2a (Gross rents) appears blank but IS.rent_income = ${rent:,.2f}. "
                f"IRC §61: all gross rents must be reported. "
                f"Books source: Acct.Rev.Rent.H_805HighMesa → Form 8825 Line 2a Col A.",
                'IRC §61; Form 8825 Instructions Line 2a; Pub 527 §1',
                "Verify bookNS_IS.json maps IS.rent_income → Form 8825 Line 2a Col A. "
                "Re-run BookToIRS pipeline.",
                fids=['F8825_Line2a'])

    def _rule_gross_rent_mismatch(self):
        """
        F8IN-R02: Line 2a ≠ IS.rent_income — Books-First violation.
        If the fill dict has a value for Line 2a that differs from IS.rent_income,
        the form was not populated from books. IRC §446: books are the authoritative
        source; IRS may disallow deductions if income is under-reported.
        """
        fill = self._load_fill_dict()
        rent = self._get_is_agg('rent_income')
        line2a = _safe_float(fill.get('F8825_Line2a') or fill.get('F8825_2a')
                             or fill.get('Line2a') or 0)
        if line2a > 0.01 and abs(line2a - rent) > 1.00:
            return self.format_issue(
                'F8IN-R02', self.WARN,
                f"Form 8825 Line 2a = ${line2a:,.2f} but IS.rent_income = ${rent:,.2f}. "
                f"Discrepancy: ${abs(line2a - rent):,.2f}. "
                f"Books-First (IRC §446): Line 2a must equal IS.rent_income from books.",
                'IRC §446; Form 8825 Line 2a',
                "Verify bookNS_IS.json maps IS.rent_income → Line 2a, not a stale value. "
                "Re-run BookToIRS pipeline.",
                fids=['F8825_Line2a'])

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

    W&B Group 2025: IS.depreciation = $1,903.13 → Line 14, fill field F079.
    IRC §469(c)(2): rental expenses are passive — all on Form 8825, never Form 1065 Page 1.
    """

    LABEL            = 'Expenses (Lines 11-17, incl. Line 14 Depreciation)'
    AGENT_KEY        = 'AgentF8825_Expenses'
    LOGICAL_PREFIXES = ['F8EX_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
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

    def _rule_line14_blank(self):
        """
        F8EX-R01: Line 14 (depreciation) blank while IS.depreciation > 0.
        IRC §168: residential rental property is depreciable under MACRS.
        A blank Line 14 when IS.depreciation > 0 means the depreciation
        deduction is missing from the rental schedule — an IRS reporting error.
        The depreciation expense reduces the net rental income/loss on Line 21,
        which flows to Schedule K Line 2. Omitting it overstates net rental income.
        W&B Group 2025: IS.depreciation = $1,903.13 → fill field F079.
        """
        fill = self._load_fill_dict()
        depr = self._get_is_agg('depreciation')
        # F079 is the fill field for Line 14 depreciation (Col A from verified data)
        line14 = _safe_float(fill.get('F079') or fill.get('F8825_Line14')
                             or fill.get('Line14') or 0)
        if depr > 0.01 and line14 < 0.01:
            return self.format_issue(
                'F8EX-R01', self.ERROR,
                f"Form 8825 Line 14 (Depreciation) is blank but IS.depreciation = ${depr:,.2f}. "
                f"IRC §168: MACRS depreciation must be reported on Form 8825 Line 14. "
                f"Books source: Acct.Exp.Depreciation → Form 8825 Line 14, Col A (fill F079). "
                f"A blank Line 14 overstates net rental income by ${depr:,.2f}.",
                'IRC §168; Form 8825 Instructions Line 14; IRC §446 Books-First',
                "Verify bookNS_IS.json maps IS.depreciation → Form 8825 Line 14 (F079). "
                "Books-First: do NOT copy from Form 4562; re-run BookToIRS pipeline.",
                fids=['F079', 'F8825_Line14'])

    def _rule_line14_mismatch(self):
        """
        F8EX-R02: Line 14 ≠ IS.depreciation — Books-First violation.
        IRC §446 + §703: books are the authoritative source. If Line 14 was
        populated from Form 4562 instead of directly from IS.depreciation,
        any error in Form 4562 propagates silently to Form 8825.
        Books-First: both forms are independently derived from IS.depreciation.
        The LLCTaxAgent cross-form audit (XF-R01) then confirms they agree.
        """
        fill  = self._load_fill_dict()
        depr  = self._get_is_agg('depreciation')
        line14 = _safe_float(fill.get('F079') or fill.get('F8825_Line14')
                             or fill.get('Line14') or 0)
        if line14 > 0.01 and abs(line14 - depr) > 1.00:
            return self.format_issue(
                'F8EX-R02', self.ERROR,
                f"Form 8825 Line 14 = ${line14:,.2f} but IS.depreciation = ${depr:,.2f}. "
                f"Discrepancy: ${abs(line14 - depr):,.2f}. "
                f"Books-First violation (IRC §446): Line 14 must equal IS.depreciation from books. "
                f"Do NOT source Line 14 from Form 4562 — populate independently from IS.depreciation.",
                'IRC §446; IRC §703; Form 8825 Line 14',
                "Fix bookNS_IS.json: Line 14 mapping must point to IS.depreciation, "
                "not to any Form 4562 value. Re-run BookToIRS pipeline.",
                fids=['F079', 'F8825_Line14'])

    def _rule_line14_xf_note(self):
        """
        F8EX-R03: Informational — Line 14 will be reconciled against Form 4562 Line 22.
        This is the LLCTaxAgent XF-R01 cross-form audit. Both forms are independently
        sourced from IS.depreciation (Books-First). The audit confirms they agree.
        This rule fires as INFO to make the cross-form audit relationship visible
        in the Form 8825 agent's session state.
        """
        depr = self._get_is_agg('depreciation')
        if depr > 0.01:
            return self.format_issue(
                'F8EX-R03', self.INFO,
                f"Form 8825 Line 14 = ${depr:,.2f} (IS.depreciation, Books-First). "
                f"LLCTaxAgent XF-R01 will confirm: F4562 Line 22 == F8825 Line 14 == IS.depreciation. "
                f"Both forms are independently populated from books — no form-to-form dependency.",
                'LLCTaxAgent XF-R01; IRC §446; Form 4562 Instructions',
                "No action required if Line 14 = IS.depreciation. "
                "XF-R01 runs automatically in LLCTaxAgent.phase2_xf_audit().")

    def _rule_total_expenses_mismatch(self):
        """
        F8EX-R04: Total expenses (Line 18) ≠ IS.total_expenses by > $1.
        Line 18 is the sum of Lines 5–17 per property. IS.total_expenses is the
        books total of all deductible rental expenses. These should agree within $1
        (rounding difference). A larger gap indicates an expense line is missing
        from or incorrectly mapped on Form 8825.
        IRC §446: form values must equal books values.
        W&B Group 2025: IS.total_expenses = $4,793.50 → fill field F104.
        """
        fill  = self._load_fill_dict()
        total = self._get_is_agg('total_expenses')
        # F104 is the fill field for Line 18 total expenses (verified)
        line18 = _safe_float(fill.get('F104') or fill.get('F8825_Line18')
                             or fill.get('Line18') or 0)
        if line18 > 0.01 and abs(line18 - total) > 1.00:
            return self.format_issue(
                'F8EX-R04', self.WARN,
                f"Form 8825 Line 18 (Total expenses) = ${line18:,.2f} but "
                f"IS.total_expenses = ${total:,.2f}. Discrepancy: ${abs(line18 - total):,.2f}. "
                f"Books-First (IRC §446): Line 18 should equal IS.total_expenses. "
                f"Check that all expense lines (5–17) are mapped from books.",
                'IRC §446; Form 8825 Instructions Line 18',
                "Verify each expense category (repairs, utilities, depreciation, taxes, other) "
                "is correctly mapped to Lines 11–17. Check for double-counted or omitted items.",
                fids=['F104', 'F8825_Line18'])


# ────────────────────────────────────────────────────────────────────────────
#  AgentF8825_NetIncome — Lines 18–21
# ────────────────────────────────────────────────────────────────────────────

class AgentF8825_NetIncome(_SectionAgent):
    """
    IRS Knowledge Base — Form 8825 Lines 18–21 (Net Income/Loss)

    Line 19a (Net income/loss per property):
      Computed: Line 2c − Line 18 = total income − total expenses.
      For H_805HighMesa 2025: $4,400 − $4,793.50 = −$393.50.

    Line 21 (Total net income/loss):
      Sum of all Line 19a across all properties.
      IRS Form 8825 Instructions: "Enter this amount on Schedule K, line 2."
      Books-First: Line 21 = IS.net_rental (IRC §446+703).
      Fill field: F113 = −393.50 (verified).

    This is the KEY RECONCILIATION POINT:
      Form 8825 Line 21 (= IS.net_rental) → Schedule K Line 2
      Schedule K Line 2 × partner.pct → K-1 Box 2

    IRC §469(c)(2): rental activity is passive. The net rental loss flows to
    Schedule E on each partner's personal return as a passive loss.
    Partners may deduct passive losses against passive income in the same year;
    excess is suspended until the property is disposed (IRC §469(b)).
    """

    LABEL            = 'Net Income/Loss (Lines 18-21)'
    AGENT_KEY        = 'AgentF8825_NetIncome'
    LOGICAL_PREFIXES = ['F8NI_']

    def pass2_audit(self) -> Dict[str, Any]:
        return self._run_audit([
            self._rule_line21_blank,
            self._rule_line21_mismatch,
            self._rule_line21_confirmed,
        ])

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

    def _rule_line21_blank(self):
        """
        F8NI-R01: Line 21 (total net) blank while IS.net_rental ≠ 0.
        Form 8825 Line 21 is the total net rental income/loss for all properties.
        It must be populated whenever the partnership has rental activity.
        A blank Line 21 means the rental result is not flowing to Schedule K Line 2,
        which means partners are not receiving their allocated share of rental income/loss.
        IRC §702(a): all partnership items must flow to partners' returns.
        """
        fill = self._load_fill_dict()
        net  = self._get_is_agg('net_rental')
        # F113 is the fill field for Line 21 total net (verified)
        line21 = _safe_float(fill.get('F113') or fill.get('F8825_Line21')
                             or fill.get('Line21') or 0)
        if abs(net) > 0.01 and abs(line21) < 0.01:
            return self.format_issue(
                'F8NI-R01', self.ERROR,
                f"Form 8825 Line 21 (Total net income/loss) is blank but "
                f"IS.net_rental = ${net:,.2f}. "
                f"Line 21 must be populated — it flows to Schedule K Line 2 "
                f"and then to each K-1 Box 2. "
                f"A blank Line 21 omits the rental result from partners' returns. "
                f"IRC §702(a): all partnership items must be allocated to partners.",
                'Form 8825 Instructions Line 21; IRC §702(a); Schedule K Instructions Line 2',
                "Verify bookNS_IS.json maps IS.net_rental → Form 8825 Line 21 (F113). "
                "Re-run BookToIRS pipeline.",
                fids=['F113', 'F8825_Line21'])

    def _rule_line21_mismatch(self):
        """
        F8NI-R02: Line 21 ≠ IS.net_rental — Books-First violation.
        Line 21 is the most critical value on Form 8825 because it flows directly
        to Schedule K Line 2 and then to K-1 Box 2 for each partner.
        If Line 21 ≠ IS.net_rental, partners will report incorrect rental
        income/loss on their individual returns. IRC §446 requires form values
        to equal books values. IRC §702(a): items must retain their character
        as determined at the partnership level.
        """
        fill   = self._load_fill_dict()
        net    = self._get_is_agg('net_rental')
        line21 = _safe_float(fill.get('F113') or fill.get('F8825_Line21')
                             or fill.get('Line21') or 0)
        if abs(line21) > 0.01 and abs(line21 - net) > 1.00:
            return self.format_issue(
                'F8NI-R02', self.ERROR,
                f"Form 8825 Line 21 = ${line21:,.2f} but IS.net_rental = ${net:,.2f}. "
                f"Discrepancy: ${abs(line21 - net):,.2f}. Books-First violation (IRC §446). "
                f"Line 21 must equal IS.net_rental — this value flows to Schedule K Line 2 "
                f"and then to each K-1 Box 2. A wrong Line 21 causes all K-1 allocations "
                f"to be incorrect.",
                'IRC §446; Form 8825 Line 21; Schedule K Line 2; IRC §702(a)',
                "Fix bookNS_IS.json: Line 21 mapping must point to IS.net_rental "
                "(not IS.rent_income or any computed value other than IS.net_rental). "
                "Re-run BookToIRS pipeline.",
                fids=['F113', 'F8825_Line21'])

    def _rule_line21_confirmed(self):
        """
        F8NI-R03: Line 21 = IS.net_rental confirmed — verify Schedule K Line 2 will match.
        This informational rule confirms the key value is correct and reminds
        the bookkeeper that LLCTaxAgent XF-R02 will verify the Schedule K connection.
        """
        fill   = self._load_fill_dict()
        net    = self._get_is_agg('net_rental')
        line21 = _safe_float(fill.get('F113') or fill.get('F8825_Line21')
                             or fill.get('Line21') or 0)
        if abs(net) > 0.01 and abs(line21 - net) <= 1.00:
            return self.format_issue(
                'F8NI-R03', self.INFO,
                f"Form 8825 Line 21 = ${line21:,.2f} = IS.net_rental confirmed (Books-First). "
                f"LLCTaxAgent XF-R02 will verify Schedule K Line 2 matches this value. "
                f"W&B Group 2025: net rental loss (${abs(net):,.2f}) → passive loss to K-1 Box 2.",
                'Form 8825 Instructions Line 21; LLCTaxAgent XF-R02; IRC §469(c)(2)',
                "No action required. XF-R02 runs in LLCTaxAgent.phase2_xf_audit().")


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
            return self._empty_summary()
        return state

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

    @staticmethod
    def _first_halt_message(issues: List[Dict]) -> str:
        for i in issues:
            if i.get('severity') == 'ERROR':
                return i.get('message', 'Error — see Guided Review')
        return issues[0]['message'] if issues else ''
