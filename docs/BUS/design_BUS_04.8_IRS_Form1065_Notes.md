# IRS Form 1065 — BookToIRS Mapping Notes (Property Rental LLC)

**Status:** v1.0 — 2026-06-09 (IRS compliance audit; bookNS Form1065 violations corrected)  
**Owner:** Francisco Rojas (W&B Group, LLC)  
**Authority hierarchy:** IRC > Treasury Regulations > IRS Instructions > GAAP > Design > User  
**Related docs:** `design_BUS_04.0_TaxPrep.md`, `design_BUS_04.6_Form1065Agent.md`, `docs/FlowSchematics/IRS_LLC_Forms.mmd`

---

## 1. The Core Rule — IRC §469(c)(2)

**For a pure rental LLC, Form 1065 Page 1 Lines 1–23 must ALL be $0.**

IRC §469(c)(2): *Rental activity is passive by statute.* Passive rental income is not ordinary business income. It is therefore never reported on Form 1065 Page 1 (which is the ordinary income/deduction section for the trade or business). Any non-zero value on Lines 1–8 (income) or Lines 9–22 (deductions) is an IRS compliance violation for this LLC.

```
WRONG (prior bookNS_IS.json — IRS VIOLATION):
  F042 → IS.repairs           ← rental repairs on Page 1 Line 11
  F047 → IS.depreciation      ← rental depr on Page 1 Line 16a  [explicitly forbidden]
  F056 → IS.net_income        ← rental net income on Line 23

CORRECT (after 2026-06-09 fix):
  F038–F056 range: NO MAPPINGS → all fields blank → all $0
  F230 → IS.net_rental        ← Schedule K Line 2 (the correct location)
```

---

## 2. The Correct Flow for a Rental LLC

```
Financial Books (IRC §446 + §703 — sole source of truth)
        │
        ├─── Form 8825 (per property, per propNm)
        │      Line 2a  Gross rents        ← IS.rent_income per property
        │      Line 14  Depreciation       ← IS.depreciation  [Books-First: NOT from Form 4562]
        │      Line 23  Net rental         ← IS.net_rental (income − expenses)
        │
        ├─── Form 4562 (depreciation schedule)
        │      Part III Line 19i col(g)    ← IS.depreciation  [Books-First: NOT from Form 8825]
        │      Part IV  Line 22 Total      ← IS.depreciation
        │
        ├─── Form 1065
        │      Page 1 Lines 1–23:  ALL $0   [IRC §469(c)(2) — rental is passive]
        │      Schedule B:         compliance questions (entity facts from Profile)
        │      Schedule K Line 2:  IS.net_rental  [Books-First: NOT copied from Form 8825]
        │      Schedule K Line 19a: IS.distributions_cash
        │      Schedule L:         BS.* (only if gross ≥ $250K AND assets ≥ $1M)
        │      Schedule M-1:       IS.net_income (Line 1 book income)
        │      Schedule M-2:       IRC §705 tax basis capital accounts
        │
        └─── Schedule K-1 (per partner × ownership %)
               Box 1  = $0          [IRC §469(c)(2) — rental is passive]
               Box 2  = IS.net_rental × partner%
               Box 14 = $0          [IRC §1402(a)(1)+(13) — rental not SE income]
               Box L  = tax basis   [Rev. Proc. 2020-13 — mandatory post-2020]
```

**Books-First invariant (IRC §446 + §703):** Schedule K Line 2, Form 8825 Line 23, and Form 4562 Line 22 each derive their value independently from the same Financial Books. None of these forms reads data from another IRS form. The LLCTaxAgent cross-form audit (Phase 2) verifies that these independently-computed values agree after the fact.

---

## 3. Form 1065 — Page-by-Page BookToIRS Mapping

### 3.1 Page 1 — General Information (Items A–K)

All values from `bookNS_Profile.json` / `stmtProfile`:

| Field | IRS Item | Source | Notes |
|---|---|---|---|
| Entity name | Item B | `Profile.entity.entity_name` | |
| EIN | Item D | `Profile.entity.ein` | IRC §6109 — required |
| Address | Item E | `Profile.entity.address_*` | |
| Accounting method | Item H | `Profile.F1065.acctg_method` | IRC §446(a) — must match books |
| # K-1s | Item I | count of `llcOwners` partners | IRS verifies every partner filed |
| Initial return | checkbox | `Profile.F1065.chk` list | 2025 = first year → checked |
| Partnership Rep | Sched B | `Profile.F1065.partnership_rep` | IRC §6223 — required post-2018 |

### 3.2 Page 1 — Income & Deductions (Lines 1–23)

**All fields blank ($0) for a pure rental LLC.**

| Lines | IRS Content | BookNS mapping | IRS Rule |
|---|---|---|---|
| Lines 1a–8 | Gross receipts, income | **NONE — $0** | IRC §469(c)(2): rental income is passive |
| Lines 9–22 | All deductions | **NONE — $0** | IRC §469(c)(2): rental expenses are passive |
| Line 16a | Depreciation | **NONE — $0** | Form 1065 Instructions Line 16a: *"Do not include rental real estate activities — report that depreciation on Form 8825 Line 14."* |
| Line 23 | Ordinary Business Income | **NONE — $0** | Must be $0; non-zero is an IRS violation |

**Audit rules (AgentF1065_IncStmt):**
- IS-R01 ERROR: Any non-zero income on Lines 1–8
- IS-R02 ERROR: Any non-zero deduction on Lines 9–22
- IS-R03 ERROR: Line 16a depreciation non-zero
- IS-R07 ERROR: Line 23 non-zero

### 3.3 Schedule B — Other Information (Pages 2–3)

Source: `bookNS_Profile.json` + runtime IS/BS value comparisons

| Question | Source | IRS Rule |
|---|---|---|
| Q3a: individual >50% owner? | `llcOwners.pct` | Answer explicitly — §267 related-party rules |
| Q4(c): skip Sched L/M-1/M-2? | `IS.total_income < $250K OR BS.total_assets < $1M` | Treas. Reg. §1.6031(a)-1(b)(4) |
| Q4d: any distributions? | `IS.distributions_cash > 0` | Must be Yes if any partner received cash |
| Q21: BBA opt-out? | `Profile.F1065.bba_opt_out` | IRC §6221(b) — significant decision; default = IN the regime |
| Partnership Rep | `Profile.F1065.partnership_rep` | IRC §6223; Treas. Reg. §301.6223-1 |

### 3.4 Schedule K — Partners' Distributive Share (Page 4)

| Line | Content | BookNS Source | Notes |
|---|---|---|---|
| Line 1 | Ordinary Business Income | **$0** | IRC §469(c)(2) |
| **Line 2** | **Net Rental Real Estate Income** | **`IS.net_rental`** | ★ The central K line for rental LLC |
| Line 5 | Interest income | `IS.interest_income` | Portfolio income, separately stated |
| Line 14 | Self-Employment | **$0** | IRC §1402(a)(1)+(13) |
| Line 16d | AMT depreciation adj | `IS.depreciation` | Verify with CPA — AMT adjustment |
| Line 19a | Distributions | `IS.distributions_cash` | Actual cash per llcOwners |

**CRITICAL — Line 2 must be NET, not gross:**  
Line 2 = IS.net_rental = total_income − total_expenses.  
Filing gross rent (IS.rent_income) on Line 2 omits all rental expense deductions from every partner's K-1 Box 2.  
**Rule KD-R04 (AgentF1065_Distr):** fires ERROR if K_2 ≈ IS.rent_income instead of IS.net_rental.

### 3.5 Schedule L — Balance Sheet (Page 5)

Only required if Q4(c) = "No" (gross receipts ≥ $250K AND total assets ≥ $1M).  
Source: `bookNS_BS.json` / `stmtBS.taxAggregates()`.

| Line | Content | Source |
|---|---|---|
| Line 14 (end) | Total assets | `BS.total_assets` |
| Line 22 (end) | Total liabilities + capital | `BS.total_liab_capital` |
| Capital accounts | Per-partner capital | `BS.partner_capital` |

### 3.6 Schedule M-1 — Book-to-Tax Reconciliation (Page 5)

Only required with Schedule L (same threshold as above).

| Line | Content | Source | Notes |
|---|---|---|---|
| Line 1 | Net income per books | `IS.net_income` | Starting point: book net income |
| Line 9 | Income per return | **$0** | = Schedule K Line 1 = $0 for rental LLC |

M-1 explains why Line 1 ≠ Line 9: all net income is passive rental (Schedule K Line 2), not ordinary taxable income (Line 9). This is the correct reconciliation.

### 3.7 Schedule M-2 — Partners' Capital Accounts (Page 5)

Only required with Schedules L and M-1 (same threshold).

**Tax basis method is mandatory (Rev. Proc. 2020-13; TD 9902).**

| Component | Source |
|---|---|
| BOY capital balance | Prior-year EOY (or $0 for first-year 2025) |
| Contributions | `llcOwners.contributions` |
| Allocated income | `IS.net_income` × partner% |
| Distributions | `IS.distributions_cash` × partner% |
| EOY capital | BOY + contributions + income − distributions (IRC §705) |

---

## 4. Schedule K-1 — Per-Partner Allocation

One K-1 per partner. All values = partnership-level K value × partner's ownership %.

| Box | Content | Source | Rule |
|---|---|---|---|
| Box 1 | Ordinary Business Income | **$0** | IRC §469(c)(2) |
| **Box 2** | **Net Rental Real Estate Income** | **`IS.net_rental × pct`** | Partners file on Schedule E, Part II |
| Box 5 | Interest Income | `IS.interest_income × pct` | Portfolio income |
| Box 14 | Self-Employment | **$0** | IRC §1402(a)(1)+(13) |
| Box 19 | Cash Distributions | `IS.distributions_cash per llcOwners` | Actual cash, not allocated |
| Box L | Capital Account | Tax basis per IRC §705 | Rev. Proc. 2020-13 mandatory |

**Runtime note:** Sch_K1 entries in `bookNS_IS.json` are documentation-only. The actual K-1 fill dict is built by `stmtIS_TaxMember._build_k1_filldict()` which applies the ownership % multiplication and maps to namespace fids.

**IRC §704(d) basis limitation advisory:** If Box 2 is a loss, each partner can only deduct up to their adjusted basis. The K-1 reports the full allocated loss; basis limitation is computed on the partner's individual return (Schedule E, Form 6198). The partnership is not responsible for tracking each partner's outside basis.

---

## 5. bookNS_IS.json — What Changed (2026-06-09)

### 5.1 Form1065 Section — Violations Removed

The following Form1065 mappings were **removed** because they populated Page 1 lines with rental income/expense values, violating IRC §469(c)(2):

| fid | Was | Why removed |
|---|---|---|
| F038 | `IS.other_income` | Page 1 Line 7 — rental income is passive, must be $0 |
| F039 | `IS.total_income` | Page 1 Line 8 — must be $0 for rental LLC |
| F042 | `IS.repairs` | Page 1 Line 11 — rental repairs belong on Form 8825 |
| F045 | `IS.taxes_licenses` | Page 1 Line 13 — rental taxes belong on Form 8825 |
| F046 | `IS.interest_expense` | Page 1 Line 15 — mortgage interest belongs on Form 8825 |
| F047 | `IS.depreciation` | Page 1 Line 16a — Form 1065 Instructions explicitly forbid this for rental |
| F049 | `IS.depreciation` | Page 1 Line 16c — same rule as 16a |
| F054 | `IS.other_deductions` | Page 1 Line 20 — rental other expenses belong on Form 8825 |
| F055 | `IS.total_expenses` | Page 1 Line 21 — must be $0 for rental LLC |
| F056 | `IS.net_income` | Page 1 Line 23 — must be $0; rental flows to Schedule K Line 2 |

### 5.2 Corrections Made

| fid | Was | Now | Why |
|---|---|---|---|
| F230 | `Cplx.K2_net_rental` | `IS.net_rental` | `Cplx` prefix has no resolver; IS.net_rental is the correct Books-First source for Schedule K Line 2 |
| F035 (Sch_K1 Box 1) | `IS.net_ordinary` | `Val.0` | Box 1 must be $0 for rental LLC; rental income is passive (§469) |
| F029 (Sch_K1) | `IS.net_income` | `Val.0` | Unclear fid assignment; pending namespace verification |

### 5.3 Retained Mappings (Verified Correct)

| fid | Mapping | Location |
|---|---|---|
| F228 | `IS.net_income` | Schedule M-1 Line 1 (book income — correct starting point) |
| F230 | `IS.net_rental` | Schedule K Line 2 ← CORRECTED |
| F247 | `IS.other_income` | Schedule K Line 7 (other income) |
| F248 | `IS.depreciation` | Schedule K Line 16d (AMT depreciation adjustment) |
| F276 | `IS.interest_income` | Schedule L (interest income asset line) |
| F279 | `IS.distributions_cash` | Schedule K Line 19a (cash distributions) |
| F281 | `IS.interest_income` | Schedule M-1 related |
| F410 | `IS.net_income` | Schedule L end-of-year equity |
| F429 | `IS.net_income` | Schedule M-2 capital analysis |

---

## 6. Cross-Form Audit Rules (LLCTaxAgent Phase 2)

These are verification-only checks run after all forms are independently generated from books. A discrepancy means a books-mapping error in one or both forms — never a missing cross-form link.

| Rule | Check | Expected |
|---|---|---|
| XF-R01 | Form 4562 Line 22 == Form 8825 Line 14 == IS.depreciation | All three = books depreciation |
| XF-R02 | Form 8825 Line 23 == Schedule K Line 2 == IS.net_rental | Both independently = books net rental |
| XF-R03 | Schedule K Line 2 × partner% == each K-1 Box 2 | Per-partner allocation correct |
| XF-R04 | Sum of all K-1 Box 2 == Schedule K Line 2 | 100% allocation across all partners |
| XF-R05 | Form 1065 Page 1 Lines 1–23 all $0 | Rental LLC invariant |

---

## 7. COA Account Classification — Ordinary vs Rental

The `propNm` field on every ledger transaction determines routing:

| `propNm` | `acctType` | Flows to | IRS Form |
|---|---|---|---|
| `H_805HighMesa` | Income/Expense | IS.rent_income, IS.net_rental | Form 8825 (per property column) |
| `H_805HighMesa` | Asset | MACRS depreciation | Form 4562 → Form 8825 Line 14 |
| `LLC` | Income/Expense | IS.other_income (entity-level) | Schedule K Line 7 (other income) |
| `LLC` | Asset | Entity-level assets | Balance Sheet only |
| empty / null | ANY | **SILENT DROP from Form 8825** | propNm REQUIRED on all transactions |

**propNm rule (from `design_BUS_04.0_TaxPrep.md` §0.1):** Every transaction must have a non-empty `propNm`. Missing propNm silently drops the transaction from the Form 8825 FILL.pdf pipeline. The aggregate IS/BS views are propNm-agnostic and will still show the value — creating a hard-to-detect discrepancy.

---

## 8. Checklist — Annual Verification Before Filing

```
□ Form 1065 Page 1 Lines 1–23 all blank (AgentF1065_IncStmt rules IS-R01 through IS-R08)
□ Schedule K Line 2 = IS.net_rental (not IS.rent_income — net, not gross)
□ Schedule K Line 14 = $0 (no SE income — rental is passive)
□ Form 8825 Line 23 = IS.net_rental (AgentF1065_Distr rule KD-R03)
□ Cross-form audit XF-R01: Form 4562 Line 22 == Form 8825 Line 14 == IS.depreciation
□ Cross-form audit XF-R02: Form 8825 Line 23 == Schedule K Line 2
□ K-1 Box 1 = $0 for each partner
□ K-1 Box 2 = IS.net_rental × partner% for each partner
□ K-1 Box 14 = $0 for each partner
□ K-1 Box L uses Tax Basis method (Rev. Proc. 2020-13)
□ Sum of K-1 Box 2 == Schedule K Line 2 (XF-R04)
□ All transactions have propNm set (propNm rule — CLAUDE.md + design_BUS_04.0 §0.1)
```

---

*End of design_BUS_04.8_IRS_Form1065_Notes.md — v1.0, 2026-06-09*
