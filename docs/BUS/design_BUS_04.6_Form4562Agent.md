# Form4562Agent — Design Document

**Status:** v1.0 — 2026-06-03
**Owner:** Francisco Rojas (W&B Group, LLC)
**Baseline docs:**
- `docs/design_BUS_04.0-LLCTaxAgent.md` — master compliance coordinator
- `docs/design_BUS_04.0-Form1065Agent.md` — gold-standard agent template
- IRS Form 4562 Instructions (2024), IRC §168, §167, §179, Pub 946 (How to Depreciate Property)

---

## 0. Architectural Invariant — Books-First Data Rule

> **This rule is non-negotiable. Any implementation that violates it is incorrect by design, regardless of whether the numbers happen to match.**

### 0.1 The Rule

Every value placed on Form 4562 MUST be sourced exclusively from the Financial Books. No Form 4562 field may be derived from or linked to Form 8825 or any other IRS form's values.

| IRS Form 4562 Field | Book Source | Key |
|---|---|---|
| Part I Line 1 — §179 statutory limit | IRS statute (fixed by law) | $1,220,000 (2024) |
| Part I Line 12 — §179 deduction | N/A ($0 for residential rental) | $0 per IRC §179(d)(1) |
| Part III Line 19h Col (b) — Placed in service | `llcAssets` — placed-in-service date | 8/25 (August 2025) |
| Part III Line 19h Col (c) — Depreciable basis | `llcAssets` — cost minus land | Tangible.InService − Land |
| Part III Line 19h Col (d) — Recovery period | IRS statute (MACRS residential) | 27.5 years |
| Part III Line 19h Col (e) — Convention | IRS statute (residential MACRS) | MM (mid-month) |
| Part III Line 19h Col (f) — Method | IRS statute (residential MACRS) | S/L (straight-line) |
| Part III Line 19h Col (g) — Depreciation | `Acct.Exp.Depreciation` in GL | `IS.depreciation` |
| Part IV Line 22 — Total | Sum of Part III | `IS.depreciation` |

### 0.2 Books-First in MACRS Context

The MACRS statutory method (IRC §168) determines the *formula* and *parameters* (recovery period, convention, method). However, the actual depreciation **dollar amount** that goes on Form 4562 Part III Line 19h Col (g) and Part IV Line 22 MUST equal `IS.depreciation` from the books (IRC §446).

The agent's role is to:
1. Verify the books contain a depreciation entry (Acct.Exp.Depreciation).
2. Verify that the MACRS formula applied to the books' depreciable basis and placed-in-service date produces an amount consistent with the books value.
3. Place `IS.depreciation` on Form 4562 — not a freshly calculated amount.

If the formula-computed amount differs materially from IS.depreciation, it is a **books error** (not a form error), and must be corrected in the ledger before filing.

---

## 1. Purpose and Scope

### 1.1 What Form 4562 Is

IRS Form 4562, *Depreciation and Amortization*, is filed with Form 1065 to disclose and claim depreciation/amortization deductions. For a rental LLC, it captures the MACRS depreciation on real property placed in service during or before the tax year.

**Key parts for W&B Group:**
- **Part I (Section 179):** Not applicable to residential rental buildings (IRC §179(d)(1) explicit exclusion). All lines = $0.
- **Part II (Special/Bonus depreciation):** Not applicable to 27.5-yr residential rental property (IRC §168(k) — bonus depreciation applies to 5-yr, 7-yr, 15-yr property, not 27.5-yr residential). All lines = $0 for this LLC.
- **Part III (MACRS):** Primary section. Line 19h = Residential rental property.
- **Part IV (Summary):** Line 22 = total depreciation = IS.depreciation.

### 1.2 Cross-Form Audit Anchor

Form 4562 Part IV Line 22 is the **anchor** for the LLCTaxAgent cross-form audit:

```
XF-R01: Form 4562 Line 22 == Form 8825 Line 14 == IS.depreciation
```

Both forms are independently populated from books. The LLCTaxAgent verifies they agree after the fact.

**The IRS instruction that says "enter the depreciation from Form 4562 on Form 8825 Line 14" is a data flow instruction for manual preparation.** In our Books-First system, both forms are populated independently from the same books source (`IS.depreciation`), and the cross-form audit serves as the verification step.

---

## 2. Architecture

### 2.1 4-Tier Structure

```
Tier 0  LLCTaxAgent         — cross-form audit + submission
Tier 1  Form4562Agent       — orchestrates 3 section agents; persists session state
Tier 2  AgentF4562_*        — one per Form 4562 major section
Tier 3  IRSFormsAgent       — common services
```

### 2.2 Section Agents

| Section Agent | Form 4562 Section | IRS Authority |
|---|---|---|
| `AgentF4562_Sec179` | Part I — Section 179 Deduction | IRC §179(d)(1) |
| `AgentF4562_MACRS` | Part III — MACRS (Line 19h) | IRC §168; Pub 946 |
| `AgentF4562_Summary` | Part IV Line 22 — Total Depreciation | IRC §446 Books-First |

---

## 3. IRS Expert Knowledge — Section Agents

### 3.1 AgentF4562_Sec179

**IRS Authority:** IRC §179(d)(1); Form 4562 Part I; Pub 946 Chapter 2

**IRC §179(d)(1) states explicitly:**
> "The term 'section 179 property' means any tangible property... to which section 168 applies... **except that such term shall not include... any property described in section 50(b)**."

IRC §50(b)(2) excludes property used predominantly in a rental activity. Residential rental buildings (27.5-yr MACRS) are categorically excluded from the §179 deduction.

**Form 4562 Part I, Line 1:** Statutory limit — $1,220,000 (2024 inflation-adjusted). This is a fixed statutory value, not a books value. It appears on the form but does not represent a deduction for this LLC.

**Form 4562 Part I, Line 12:** Section 179 deduction = **$0** for W&B Group. Any non-zero §179 deduction claimed for a residential rental building is an IRS violation.

**2024 statutory limit:** $1,220,000 (Rev. Proc. 2023-34).

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| F45S-R01 | INFO | IRC §179(d)(1); Pub 946 Ch.2 | §179 = $0 confirmed for residential rental buildings |
| F45S-R02 | ERROR | IRC §179(d)(1) | Any §179 deduction claimed for residential building |

### 3.2 AgentF4562_MACRS

**IRS Authority:** IRC §168; Pub 946 (MACRS Tables); Form 4562 Instructions Part III Section A

**MACRS parameters for residential rental property (IRC §168(c)):**
- **Recovery period:** 27.5 years (GDS — General Depreciation System)
- **Convention:** Mid-month (MM) — IRC §168(d)(2): "In the case of any residential rental property... the applicable convention is the mid-month convention."
- **Method:** Straight-line (S/L) — IRC §168(b)(3)(B): residential rental property uses the straight-line method.

**Depreciable basis computation (critical — land exclusion):**
IRS rule: Land is never depreciable. The depreciable basis for MACRS is:

```
Depreciable basis = Total acquisition cost − Land value − Non-depreciable items
```

For H_805HighMesa:
- Total property cost = llcAssets (all transactions)
- Land value = `Acct.Fixed.Land` in llcAssets ($79,438.41)
- Depreciable tangible basis = `Acct.Fixed.Tangible.InService` ($141,223.84 + $1,660.64 = $142,884.48)
- This goes in Form 4562 Part III Line 19h Column (c).

**Form 4562 Instructions:** "Enter the depreciable basis... Do not include the cost of land."

**MACRS Year 1 formula with mid-month convention:**
```
Annual depreciation = Depreciable basis / Recovery period
Year 1 (partial year) = Annual depreciation × ((12.5 - month_placed_in_service) / 12)
```

For August 2025 (month = 8):
```
Year 1 depr = (basis / 27.5) × ((12.5 - 8) / 12) = (basis / 27.5) × (4.5 / 12)
```

Mid-month convention: property placed in service in August is treated as placed in service on August 15 — giving 4.5 months of depreciation (Aug 15 through Dec 31 = 4.5 months).

**Books-First:** Column (g) MUST equal IS.depreciation from books, not the agent's independently computed amount. The formula is used for verification only.

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| F45M-R01 | ERROR | IRC §168(a); Form 4562 Part III | No Acct.Fixed.Tangible.InService in llcAssets |
| F45M-R02 | ERROR | IRC §168(a) | Placed-in-service date missing from llcAssets |
| F45M-R03 | WARN | IRS (land never depreciable) | Depreciable basis appears to include land value |
| F45M-R04 | ERROR | IRC §446 Books-First | Column (g) amount ≠ IS.depreciation from books |
| F45M-R05 | INFO | IRC §168; Pub 946 | Formula-computed amount differs from IS.depreciation by > $10 — CPA review |

### 3.3 AgentF4562_Summary

**IRS Authority:** Form 4562 Part IV; IRC §446

**Form 4562 Part IV Line 22:** "Summary — Listed property. Enter the amount from line 28."

For this LLC, all depreciation is in Part III (MACRS residential rental). Part IV Line 22 = sum of all MACRS depreciation amounts = IS.depreciation.

**This is the cross-form audit anchor.** LLCTaxAgent XF-R01 will compare:
- Form 4562 Line 22 (this value)
- Form 8825 Line 14 (Col A value)
- IS.depreciation (books canonical source)

All three must agree within $1.00.

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| F45L-R01 | ERROR | IRC §168; Form 4562 Line 22 | Line 22 blank while IS.depreciation > 0 |
| F45L-R02 | ERROR | IRC §446 Books-First | Line 22 ≠ IS.depreciation |
| F45L-R03 | INFO | LLCTaxAgent XF-R01 | Line 22 = $1,903.13 confirmed; cross-form audit pending |

---

## 4. 5-Pass Pipeline

| Pass | Name | What Happens |
|---|---|---|
| Pass 0 | Inventory | Scan llcAssets for Acct.Fixed.Tangible.InService, land accounts, placed-in-service date |
| Pass 1 | Auto-Fill | Load fill dict values (Form4562 section); report completeness by Part |
| Pass 2 | Audit | Section agents run IRS compliance rules; §179 exclusion verified; MACRS formula checked |
| Pass 4 | Finalize | Return merged fill dict slice; pass to PDF pipeline |
| Pass 5 | Summarize | Human-readable one-line summary per section |

---

## 5. Orchestration (Form4562Agent)

```
Form4562Agent.run_phases_1_2()
  ├── AgentF4562_Sec179.pass1_auto_fill() + pass2_audit()
  ├── AgentF4562_MACRS.pass1_auto_fill() + pass2_audit()
  └── AgentF4562_Summary.pass1_auto_fill() + pass2_audit()
  → overall_state = NEEDS_FIXING if any ERROR; else GO
  → writes Form4562_session_state.json to .agent_work/
```

**LLCTaxAgent integration:**
- `LLCTaxAgent.phase1_prepare()` calls `Form4562Agent.run_phases_1_2()`
- `LLCTaxAgent.phase2_xf_audit()` runs XF-R01: `Form4562 Line 22 == IS.depreciation == Form8825 Line 14`

---

## 6. Data Sources Summary

| Source | Object | Form 4562 Use |
|---|---|---|
| IS depreciation | `stmtIS.taxAggregates()['depreciation']` | Part III Col (g), Part IV Line 22 |
| Asset records | `llcAssets.load()` | Placed-in-service date, depreciable basis |
| Land records | `llcAssets` Acct.Fixed.Land rows | Land exclusion from basis (Col c) |
| IRS statute | IRC §168; Rev. Proc. 2023-34 | §179 limit, recovery period, convention, method |

**Live W&B Group 2025 values:**
- IS.depreciation = $1,903.13 (→ Form 4562 Part III Line 19h Col g, Part IV Line 22)
- H_805HighMesa placed in service: August 2025 (→ Col b = "8/25")
- Depreciable basis ≈ $142,884.48 (Acct.Fixed.Tangible.InService)
- Land value ≈ $79,438.41 (Acct.Fixed.Land — excluded from depreciable basis)
- Recovery period = 27.5 years (residential rental, IRC §168(c))
- Convention = MM (mid-month), Method = S/L (straight-line)
