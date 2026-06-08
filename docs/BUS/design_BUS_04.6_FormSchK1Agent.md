# FormSchK1Agent — Design Document

**Status:** v1.0 — 2026-06-03
**Owner:** Francisco Rojas (W&B Group, LLC)
**Baseline docs:**
- `docs/design_BUS_04.0-LLCTaxAgent.md` — master compliance coordinator
- `docs/design_BUS_04.0-Form1065Agent.md` — gold-standard agent template
- IRS Schedule K-1 Instructions (Form 1065, 2024), IRC §702, §704, §705, §1402, Pub 541

---

## 0. Architectural Invariant — Books-First Data Rule

> **This rule is non-negotiable. Any implementation that violates it is incorrect by design, regardless of whether the numbers happen to match.**

### 0.1 The Rule

Every value placed on each partner's Schedule K-1 MUST be sourced exclusively from the Financial Books and the partner roster (llcOwners). No K-1 field may be derived from or linked to another K-1 or to a partially-completed form.

| K-1 Field | Book Source | Formula |
|---|---|---|
| Box 1 — Ordinary income | $0 per IRC §469 | $0 (never non-zero for rental LLC) |
| Box 2 — Net rental income | `IS.net_rental` × partner.pct | Books-First |
| Box 5 — Interest income | `IS.interest_income` × partner.pct | Books-First |
| Box 14 — SE income | $0 per IRC §1402 | $0 (never non-zero for rental LLC) |
| Box 19 — Distributions | `llcOwners[partner].distributions` | Per-partner record |
| Box L — Capital account | Tax basis method (contributions + income − losses − distributions) | IRC §705 |

### 0.2 Per-Partner Computation

Each partner's K-1 values are independently derived from the books and the partner's ownership percentage. There are no cross-K-1 dependencies. The sum of all partners' Box 2 allocations must equal Schedule K Line 2 (= IS.net_rental) — this is verified by LLCTaxAgent XF-R03 and XF-R04 after all K-1s are independently produced.

---

## 1. Purpose and Scope

### 1.1 What Schedule K-1 Is

Schedule K-1 (Form 1065) is the per-partner tax statement. The partnership files one K-1 per partner with Form 1065, and each partner receives a copy to file with their individual return (Form 1040, Schedule E).

**IRC §702(a):** Each partner's distributive share of partnership income, gain, loss, deduction, or credit retains its character as determined at the partnership level. Partners are taxed on their allocated share of each separately stated item, regardless of whether a distribution was made.

**IRC §6226(a):** Partners report K-1 items on their individual returns.

### 1.2 Key IRS Rules for W&B Group (Rental LLC)

**Box 1 (Ordinary business income) = $0:**
- IRC §469(c)(2) classifies all rental activity as passive, not ordinary.
- Rental income never flows to Box 1 (which is for ordinary business income, e.g., a manufacturing partnership).
- Form 1065 Page 1 Line 23 = $0 → Box 1 = $0.

**Box 2 (Net rental real estate income/loss):**
- IRS K-1 Instructions: "The amount in Box 2 is the partner's distributive share of net rental real estate income or loss from Schedule K, Line 2."
- Books-First: Box 2 = IS.net_rental × partner.pct (from llcOwners).
- W&B Group 2025: IS.net_rental = −$393.50. Three equal partners (each 1/3): Box 2 ≈ −$131.17 each.

**Box 14 (Self-employment income) = $0:**
- IRC §1402(a)(1): Rental income is not "net earnings from self-employment."
- IRC §1402(a)(13): Limited partners' distributive shares are excluded from SE tax.
- Any non-zero Box 14 for a rental LLC incorrectly triggers ~15.3% SE tax on partners' returns.

**Box L (Partner's capital account — tax basis method):**
- Mandatory post-2020: Rev. Proc. 2020-13; TD 9902; Form 1065 Instructions (M-2 and K-1 Box L).
- Tax basis = cash contributed + taxable income allocated − losses allocated − distributions received.
- For first-year filing (2025): Beginning capital = $0; Ending capital = contributions + Box 2 (negative for a loss year) − distributions.
- Previous methods (§704(b) book value, GAAP) are no longer accepted.

**No K-2/K-3 (foreign schedules):**
- K-2 (Partners' Distributive Share Items — International) and K-3 (per-partner K-2) are required only if the partnership has foreign partners, foreign income, or foreign tax credits.
- W&B Group: all partners are domestic individuals, no foreign activity. K-2/K-3 are not required.

### 1.3 Partner Identification

Each K-1 requires:
- Partner's legal name and address
- Partner's TIN (SSN for individuals — 9 digits; IRC §6109)
- Partnership's EIN
- Partner's ownership percentage
- Tax year of the K-1

**IRC §6109:** Every person required to file a return must include a TIN. A missing or malformed SSN is grounds for IRS rejection and penalties.

### 1.4 Scope for W&B Group (2025)

- **3 partners:** o20250801_1, o20250801_2, o20250801_3
- **Equal ownership:** each approximately 33.33%
- **First filing year:** Beginning capital = $0 for all partners
- **Box 2 per partner:** IS.net_rental × partner.pct ≈ −$131.17 each

---

## 2. Architecture

### 2.1 4-Tier Structure

```
Tier 0  LLCTaxAgent         — cross-form audit (XF-R03/R04: sum of K-1 Box 2 = Schedule K Line 2)
Tier 1  FormSchK1Agent      — orchestrates section agents PER PARTNER; aggregates results
Tier 2  AgentSchK1_*        — section agents, each runs once per partner (N iterations)
Tier 3  IRSFormsAgent       — common services
```

### 2.2 Special: Per-Partner Loop

Unlike Form 1065/8825/4562, the K-1 agent runs each section agent **once per partner**, not once for the whole form. `FormSchK1Agent.run_phases_1_2()` iterates over all partners in llcOwners, producing one set of section-agent results per partner.

### 2.3 Section Agents

| Section Agent | K-1 Section | IRS Authority |
|---|---|---|
| `AgentSchK1_Identity` | Partner identification (name, TIN, %, address) | IRC §6109 |
| `AgentSchK1_PassiveItems` | Box 1, Box 2, Box 5, Box 14 | IRC §469, §702, §1402 |
| `AgentSchK1_Capital` | Box L (Partner's capital account) | IRC §705; Rev. Proc. 2020-13 |

---

## 3. IRS Expert Knowledge — Section Agents

### 3.1 AgentSchK1_Identity (per partner)

**IRS Authority:** IRC §6109; Form 1065 Instructions (Schedule K-1 header); Treas. Reg. §301.6109-1

Each K-1 must correctly identify the partner. Errors here are the most common cause of IRS rejection.

**TIN requirement:** Partners who are individuals must provide their SSN (9 digits). IRC §6724: penalties for incorrect or missing TINs. The partnership may be subject to backup withholding requirements if a partner's TIN is missing or incorrect.

**Ownership percentage:** Must match the LLC operating agreement. IRC §704(b): allocations must have substantial economic effect. Ownership % determines all Box 2, Box 5, and capital allocations.

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| SK1I-R01 | ERROR | IRC §6109 | Partner TIN missing or not 9 digits |
| SK1I-R02 | WARN | Form 1065 Instr (K-1 header) | Partner address missing |
| SK1I-R03 | ERROR | IRC §704(b) | Partner ownership % is 0 or missing |

### 3.2 AgentSchK1_PassiveItems (per partner)

**IRS Authority:** IRC §469(c)(2), §702(a), §704(b), §1402(a)(1), §1402(a)(13)

**Box 2 (Net rental real estate income/loss):**
- IRS Instructions: "From Schedule K, line 2, enter the partner's distributive share."
- Books-First: IS.net_rental × partner.pct.
- For a loss (IS.net_rental < 0): the allocated loss flows to the partner's Schedule E.
- IRC §704(d) basis limitation: a partner can deduct a loss only to the extent of their adjusted basis in the partnership. This is advisory — the K-1 always shows the full allocated amount regardless of the partner's basis limitation on their individual return. The Box 2 value is the correct books-derived allocation.

**Box 1 (Ordinary business income) = $0:**
- Rental LLC: $0 always. A non-zero Box 1 means Form 1065 Page 1 was filled incorrectly.

**Box 5 (Interest income):**
- If IS.interest_income > 0: Box 5 = IS.interest_income × partner.pct.
- Interest income (e.g., on LLC bank accounts) is separately stated per IRC §702(a)(1).

**Box 14 (Self-employment income) = $0:**
- IRC §1402(a)(1): rental income excluded from SE earnings.
- IRC §1402(a)(13): limited partners excluded from SE tax.
- Non-zero Box 14 incorrectly triggers 15.3% SE tax (~$60 SE tax per $393 of income).

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| SK1P-R01 | ERROR | IRC §702(a); §469 | Box 2 blank while IS.net_rental × pct ≠ 0 |
| SK1P-R02 | ERROR | IRC §446 Books-First | Box 2 ≠ IS.net_rental × partner.pct |
| SK1P-R03 | ERROR | IRC §469(c)(2) | Box 1 non-zero (must be $0 for rental LLC) |
| SK1P-R04 | ERROR | IRC §1402(a)(1), (a)(13) | Box 14 non-zero (must be $0 for rental LLC) |
| SK1P-R05 | INFO | IRC §704(d) | Box 2 is a loss — advisory: partner needs sufficient basis to deduct |

### 3.3 AgentSchK1_Capital (per partner)

**IRS Authority:** IRC §705; Rev. Proc. 2020-13; TD 9902; Form 1065 Instructions (K-1 Box L)

**Tax Basis Method (mandatory post-2020):**

Box L requires the partnership to track and report partner capital using the **tax basis method**:

```
Beginning capital (BOY) + Capital contributed + Ordinary income/loss + Other increases
− Withdrawals/distributions − Losses − Other decreases = Ending capital (EOY)
```

For W&B Group 2025 (first year):
- Beginning capital = $0 (new entity)
- Capital contributed = per-partner cash contributions (from llcOwners)
- Allocated income/loss = Box 2 allocated amount
- Distributions = llcOwners[partner].distributions
- Ending capital = contributions + Box 2 − distributions

**Why tax basis method:** Previous IRS guidance allowed §704(b) book value or GAAP basis. Starting with tax years ending December 31, 2020 (Rev. Proc. 2020-13), the IRS requires tax basis reporting. The change was made because the IRS needs to verify partners are tracking their basis correctly for loss limitation purposes (IRC §704(d)).

**Method checkbox (Box L):** Must check "Tax basis" (not "§704(b)," "GAAP," or "Other").

**Audit Rules:**
| Rule ID | Severity | IRS Citation | Condition |
|---|---|---|---|
| SK1C-R01 | WARN | Rev. Proc. 2020-13; TD 9902 | Box L uses non-tax-basis method |
| SK1C-R02 | INFO | IRC §705; Rev. Proc. 2020-13 | Tax basis capital summary (first year = contributions + Box 2 allocation) |
| SK1C-R03 | WARN | IRC §705 | Ending capital inconsistent with simple tax basis calculation |

---

## 4. 5-Pass Pipeline

| Pass | Name | What Happens |
|---|---|---|
| Pass 0 | Inventory | Load llcOwners; enumerate partners; detect first-year filing |
| Pass 1 | Auto-Fill | Per partner: load K-1 fill dict section; report completeness |
| Pass 2 | Audit | Per partner: run section agents (Identity, PassiveItems, Capital) |
| Pass 4 | Finalize | Per partner: return complete K-1 fill dict; pass to PDF pipeline |
| Pass 5 | Summarize | Aggregate: N partners, Box 2 per partner, total Box 2 = IS.net_rental |

---

## 5. Orchestration (FormSchK1Agent)

```
FormSchK1Agent.run_phases_1_2()
  → load llcOwners (all partners)
  → for each partner (oID in llcOwners):
      ├── AgentSchK1_Identity.pass1_auto_fill(partner) + pass2_audit(partner)
      ├── AgentSchK1_PassiveItems.pass1_auto_fill(partner) + pass2_audit(partner)
      └── AgentSchK1_Capital.pass1_auto_fill(partner) + pass2_audit(partner)
  → aggregate: overall HALT if any partner has ERROR issues
  → session state keyed by partner oID
  → writes FormSchK1_session_state.json to .agent_work/
```

**Session state structure:**
```json
{
  "tax_year": 2025,
  "last_run": "...",
  "overall_state": "GO",
  "partners": {
    "o20250801_1": {"state": "GO", "issues": [], "box2": -131.17, "capital_ending": ...},
    "o20250801_2": {"state": "GO", "issues": [], "box2": -131.17, "capital_ending": ...},
    "o20250801_3": {"state": "GO", "issues": [], "box2": -131.17, "capital_ending": ...}
  }
}
```

**LLCTaxAgent integration:**
- `LLCTaxAgent.phase2_xf_audit()` runs XF-R03: each K-1 Box 2 = IS.net_rental × pct (within $0.02)
- `LLCTaxAgent.phase2_xf_audit()` runs XF-R04: sum of all K-1 Box 2 = Schedule K Line 2 (within $0.02)

---

## 6. Data Sources Summary

| Source | Object | K-1 Use |
|---|---|---|
| IS net rental | `stmtIS.taxAggregates()['net_rental']` | Box 2 base for allocation |
| IS interest income | `stmtIS.taxAggregates()['interest_income']` | Box 5 base |
| Owner records | `llcOwners` (per partner) | TIN, name, pct, address, distributions, contributions |
| Entity profile | `stmtProfile` | LLC name, EIN (for K-1 header) |

**Live W&B Group 2025 values:**
- IS.net_rental = −$393.50 (→ split equally to 3 partners: ≈ −$131.17 each per Box 2)
- 3 partners: o20250801_1, o20250801_2, o20250801_3 (equal ownership ~33.33%)
- Box 1 = $0, Box 14 = $0 (always, by statute)
- Box L: first year, beginning capital = $0; ending = contributions + Box 2 − distributions
- Tax basis method mandatory (Rev. Proc. 2020-13)
- No K-2/K-3 required (domestic partners only, no foreign activity)
