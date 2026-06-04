# Form8825Agent — Design Document

**Status:** v1.0 — 2026-06-03
**Owner:** Francisco Rojas (W&B Group, LLC)
**Baseline docs:**
- `docs/design_BUS_04.0-LLCTaxAgent.md` — master compliance coordinator
- `docs/design_BUS_04.0-Form1065Agent.md` — gold-standard agent template
- IRS Form 8825 Instructions (2024), IRC §469(c)(2), Pub 527 (Residential Rental Property)

---

## 0. Architectural Invariant — Books-First Data Rule

> **This rule is non-negotiable. Any implementation that violates it is incorrect by design, regardless of whether the numbers happen to match.**

### 0.1 The Rule

Every value placed on Form 8825 MUST be sourced exclusively from the Financial Books (`stmtIS.taxAggregates()` and the asset/expense ledger DBs). No Form 8825 field may be derived from, copied from, or linked to Form 4562 or any other IRS form's values.

| IRS Form 8825 Field | Book Source | Key |
|---|---|---|
| Line 2a — Gross rents | `Acct.Rev.Rent.{propNm}` in IS | `IS.rent_income` |
| Line 2b — Other income | `Acct.Rev.Other.{propNm}` in IS | `IS.other_income` |
| Line 11 — Repairs | `Acct.Exp.Repair.{propNm}` | IS row |
| Line 12 — Utilities | `Acct.Exp.Util.{propNm}` | IS row |
| Line 14 — Depreciation | `Acct.Exp.Depreciation` in GL | `IS.depreciation` |
| Line 16 — Taxes | `Acct.Exp.Taxes.{propNm}` | IS row |
| Line 17 — Other | `Acct.Exp.Operating + Acct.Exp.Other` | IS rows |
| Line 18 — Total expenses | Sum of Lines 5–17 | Computed |
| Line 19a — Net per property | Line 2c − Line 18 | Computed |
| Line 21 — Total net | Sum of all Line 19a | `IS.net_rental` |

### 0.2 Critical: Line 14 Depreciation Source

**Form 8825 Line 14 must NOT come from Form 4562.** Both forms are independently populated from `IS.depreciation` (books). The cross-form audit rule XF-R01 (run by `LLCTaxAgent`) verifies that:

```
Form 4562 Line 22 == Form 8825 Line 14 == IS.depreciation
```

This equality is the **expected outcome** of both forms being correctly sourced from books. It is not a wiring dependency.

**IRC §446 + §703:** Books are the authoritative source for all form values.

---

## 1. Purpose and Scope

### 1.1 What Form 8825 Is

IRS Form 8825, *Rental Real Estate Income and Expenses of a Partnership or an S Corporation*, is a supplemental schedule that accompanies Form 1065. It itemizes income and expense by rental property (one column per property) and computes the net rental income/loss for the partnership.

**IRS authority:** Form 8825 is filed with Form 1065 whenever the partnership owns rental real estate. It is not optional. IRC §469(c)(2) classifies all rental activity as passive — this activity belongs on Form 8825, not on Form 1065 Page 1.

### 1.2 Key IRS Flow for W&B Group

```
Books (Acct.Rev.Rent.H_805HighMesa) ─── Form 8825 Line 2a (Col A)
Books (Acct.Exp.Depreciation)        ─── Form 8825 Line 14 (Col A)   ← Books-First
Books (IS.net_rental)                ─── Form 8825 Line 21           ← total net
Form 8825 Line 21                    ─── Schedule K Line 2           ← IRS flow
Schedule K Line 2 × partner%        ─── K-1 Box 2 (per partner)
```

**Not this (incorrect):**
```
Form 4562 Line 22 ──→ Form 8825 Line 14   ← Books-First violation
```

### 1.3 Scope for W&B Group (2025)

- **One property:** H_805HighMesa (placed in service August 2025)
- **One page (cols A–D):** property fits in column A
- **IRC §469(c)(2):** rental activity is passive; net loss flows to Schedule K Line 2 as a passive loss
- **Pub 527:** Residential Rental Property rules apply (27.5-yr MACRS, mid-month convention)

---

## 2. Architecture

### 2.1 4-Tier Structure

```
Tier 0  LLCTaxAgent         — cross-form audit + submission (IRS_Submission package)
Tier 1  Form8825Agent       — orchestrates 4 section agents; persists session state
Tier 2  AgentF8825_*        — one per Form 8825 section (this file)
Tier 3  IRSFormsAgent       — common services (format_issue, state_from_issues, _forms_dir)
```

### 2.2 Section Agents

| Section Agent | Form 8825 Section | IRS Authority |
|---|---|---|
| `AgentF8825_Properties` | Property identification & placed-in-service dates | IRC §168 |
| `AgentF8825_Income` | Lines 2a–2c (gross rents + other income per property) | IRC §61, Pub 527 |
| `AgentF8825_Expenses` | Lines 5–17 (expenses per property, incl. Line 14 depreciation) | IRC §162, §168 |
| `AgentF8825_NetIncome` | Lines 18–21 (total expenses, net per property, total net) | IRC §469(c)(2) |

### 2.3 Data Sources (Books-First)

```
stmtIS.taxAggregates()   → IS.rent_income, IS.depreciation, IS.net_rental, IS.total_expenses
stmtIS_Tax(llc).loadFillDict('Form8825') → per-field fill dict (F113, F079, F104, ...)
llcAssets.load()          → property status, placed-in-service date, propNm
llcProfile / stmtProfile  → entity info (not used directly for Line values)
```

---

## 3. IRS Expert Knowledge — Section Agents

### 3.1 AgentF8825_Properties

**IRS Authority:** IRC §168 (MACRS); Form 8825 Instructions (Column headings)

Form 8825 devotes one column per rental property (columns A–D on page 1; columns E–H on page 2). Each column header requires the property address, property type (e.g., residential), and placed-in-service date.

**Placed-in-service date (IRC §168(a)):** MACRS depreciation begins when the property is *placed in service* — the date the property is ready and available for use in the rental activity. This is not the purchase date. For H_805HighMesa: August 2025.

**IRS Instructions (Form 8825, Column heading):** "Enter the type of property in the first row (for example, 1-family residential, commercial). Enter the date placed in service."

**Under-construction exclusion (IRC §168):** Property not yet placed in service cannot be depreciated. It is excluded from Form 8825.

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| F8PR-R01 | ERROR | IRC §168; Form 8825 Instr | No active properties in llcAssets → cannot generate Form 8825 |
| F8PR-R02 | WARN | IRC §168 | Under-construction property present → excluded from Form 8825 |
| F8PR-R03 | ERROR | IRC §168(a) | Property has no placed-in-service date → MACRS cannot start |
| F8PR-R04 | INFO | Form 8825 Instr | > 4 properties → page 2 (cols E–H) required |

### 3.2 AgentF8825_Income

**IRS Authority:** IRC §61 (gross income); Pub 527 §1 (What Rental Income Is)

**Form 8825 Lines:**
- **Line 2a (Gross rents):** All rent received or accrued from tenants. Books source: `Acct.Rev.Rent.{propNm}`. IRS: "Enter the gross rents received or accrued for each property." (Form 8825 Instructions, Line 2a)
- **Line 2b (Other income):** Security deposits applied to rent, cancellation fees, services received instead of rent. Books source: `Acct.Rev.Other.{propNm}`.
- **Line 2c (Total income):** Computed = Line 2a + Line 2b.

**W&B Group 2025:** IS.rent_income = $4,000; IS.total_income = $4,400 (includes $400 other income).

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| F8IN-R01 | ERROR | IRC §61; Form 8825 Line 2a | Line 2a blank while IS.rent_income > 0 |
| F8IN-R02 | WARN | IRC §446 Books-First | Fill dict Line 2a ≠ IS.rent_income |
| F8IN-R03 | INFO | Pub 527 §1 | Other income (Line 2b) populated — confirm rental-related |

### 3.3 AgentF8825_Expenses

**IRS Authority:** IRC §162 (ordinary business expenses); IRC §168 (MACRS depreciation); Form 8825 Lines 5–17

**Key IRS rules per expense line:**
- **Line 11 (Repairs):** IRC §162; deductible if they maintain the property in its current condition (not capital improvements). Books: `Acct.Exp.Repair.{propNm}`.
- **Line 12 (Utilities):** IRC §162. Books: `Acct.Exp.Util.{propNm}`.
- **Line 14 (Depreciation — CRITICAL):**
  - IRS Instructions (Form 8825 Line 14): "Enter the depreciation on property for which you are not claiming a §179 deduction or special depreciation allowance. Use Form 4562 to figure the depreciation."
  - **Books-First exception:** Despite the Form 8825 instruction saying "use Form 4562," the actual dollar amount placed on Line 14 MUST equal `IS.depreciation` from books (IRC §446 + §703). The LLCTaxAgent cross-form audit (XF-R01) verifies that Form 4562 Line 22 agrees with this books value after the fact.
  - W&B Group 2025: Line 14 = $1,903.13 (IS.depreciation from books).
- **Line 16 (Taxes):** IRC §164. Property taxes only (not income taxes). Books: `Acct.Exp.Taxes.{propNm}`.
- **Line 17 (Other):** IRC §162. Operating expenses not captured above. Books: `Acct.Exp.Operating + Acct.Exp.Other`.

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| F8EX-R01 | ERROR | IRC §168; Form 8825 Line 14 | Line 14 blank while IS.depreciation > 0 |
| F8EX-R02 | ERROR | IRC §446 Books-First | Line 14 ≠ IS.depreciation |
| F8EX-R03 | INFO | LLCTaxAgent XF-R01 | Confirm Line 14 will be cross-checked against Form 4562 Line 22 |
| F8EX-R04 | WARN | IRC §446 | Total expenses (Line 18) ≠ IS.total_expenses by > $1 |

### 3.4 AgentF8825_NetIncome

**IRS Authority:** IRC §469(c)(2) (rental = passive); Form 8825 Lines 18–21; Schedule K Instructions Line 2

**Form 8825 Lines:**
- **Line 18 (Total expenses):** Computed sum of Lines 5–17.
- **Line 19a (Net income/loss per property):** Computed = Line 2c − Line 18. For H_805HighMesa: $4,400 − $4,793.50 = −$393.50.
- **Line 21 (Total net income/loss):** Sum of all Line 19a across all properties. For W&B Group 2025: −$393.50.

**IRS Instructions (Form 8825 Line 21):** "Enter the combined total of all amounts from line 19a. This amount is the net income or loss from rental real estate activities. Enter this amount on Schedule K, line 2."

**Books-First:** Line 21 = IS.net_rental. This is the **key reconciliation point** — the value that flows from Form 8825 to Schedule K Line 2 to each K-1 Box 2.

**IRC §469(c)(2):** Rental activity is passive per statute. The net rental loss (−$393.50) is a passive loss that flows to each partner's Schedule E, subject to the passive activity loss rules on their individual return.

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| F8NI-R01 | ERROR | Form 8825 Line 21; IRC §469 | Line 21 blank while IS.net_rental ≠ 0 |
| F8NI-R02 | ERROR | IRC §446 Books-First | Line 21 ≠ IS.net_rental |
| F8NI-R03 | INFO | Form 8825 Instr; Schedule K Line 2 | Line 21 = IS.net_rental confirmed; verify Schedule K Line 2 matches |

---

## 4. 5-Pass Pipeline

| Pass | Name | What Happens |
|---|---|---|
| Pass 0 | Inventory | `AgentF8825_Properties` scans llcAssets for active properties, placed-in-service dates |
| Pass 1 | Auto-Fill | Load Form 8825 fill dict (stmtIS_Tax.loadFillDict); report completeness by section |
| Pass 2 | Audit | Each section agent runs IRS compliance rules; issues collected with severity |
| Pass 4 | Finalize | Return merged fill dict slice for Form 8825; pass to PDF pipeline |
| Pass 5 | Summarize | Human-readable one-line summary per section |

---

## 5. Orchestration (Form8825Agent)

```
Form8825Agent.run_phases_1_2()
  ├── AgentF8825_Properties.pass1_auto_fill() + pass2_audit()
  ├── AgentF8825_Income.pass1_auto_fill() + pass2_audit()
  ├── AgentF8825_Expenses.pass1_auto_fill() + pass2_audit()
  └── AgentF8825_NetIncome.pass1_auto_fill() + pass2_audit()
  → overall_state = NEEDS_FIXING if any ERROR; else GO
  → writes Form8825_session_state.json to .agent_work/
```

**LLCTaxAgent integration:**
- `LLCTaxAgent.phase1_prepare()` calls `Form8825Agent.run_phases_1_2()`
- `LLCTaxAgent.phase2_xf_audit()` runs XF-R01: `Form4562 Line 22 == IS.depreciation == Form8825 Line 14`
- `LLCTaxAgent.phase2_xf_audit()` runs XF-R02: `Form8825 Line 21 == IS.net_rental == Schedule K Line 2`

---

## 6. Data Sources Summary

| Source | Object | Form 8825 Use |
|---|---|---|
| IS income/expense | `stmtIS.taxAggregates()` | All dollar values (rent, depr, expenses, net) |
| Form 8825 fill dict | `stmtIS_Tax.loadFillDict('Form8825')` | Existing fill values (F113, F079, F104...) |
| Asset records | `llcAssets.load()` | Property identification, placed-in-service date |
| Entity profile | `stmtProfile` | LLC name, EIN (for form header) |

**Live W&B Group 2025 values:**
- IS.rent_income = $4,000.00
- IS.total_income = $4,400.00
- IS.depreciation = $1,903.13 (→ Form 8825 Line 14, Col A, fill field F079)
- IS.total_expenses = $4,793.50 (→ Form 8825 Line 18, fill field F104)
- IS.net_rental = −$393.50 (→ Form 8825 Line 21, fill field F113)
