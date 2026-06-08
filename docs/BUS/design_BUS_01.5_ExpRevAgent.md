# ExpRevAgent — Business Accounting Design

Module Owner: Business Accountant  
Status: Production (v0.3)  
System: llcRentalTracker / W&B Group, LLC  
AccountingStage: Booking (01.5)  
Implementation: `ledger/expenseAgent.py` · `ui/llcExpAgent.py`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Why Normalization Is Necessary](#2-why-normalization-is-necessary)
   - 2.1 Source of Dirty Data
   - 2.2 Downstream Impact of Un-normalized Records
3. [Rule 1 — Cash Account Orientation](#3-rule-1--cash-account-orientation)
   - 3.1 Accounting Principle
   - 3.2 The Swap Condition
   - 3.3 Examples
4. [Rule 2 — acctSub Classification](#4-rule-2--acctsubclassification)
   - 4.1 Role of acctSub in Financial Reporting
   - 4.2 Inference Rules
   - 4.3 acctSub Taxonomy for W&B Group
5. [Rule 3 — Property Attribution (propNm)](#5-rule-3--property-attribution-propnm)
   - 5.1 Why Every Transaction Must Have a Property
   - 5.2 Default Value
6. [Execution Order and Idempotency](#6-execution-order-and-idempotency)
7. [Workflow — When to Run ExpRevAgent](#7-workflow--when-to-run-exprevagent)
8. [Relationship to Financial Statements and IRS Forms](#8-relationship-to-financial-statements-and-irs-forms)
9. [Known Limitations & Future Work](#9-known-limitations--future-work)

---

## 1. Executive Summary

The **ExpRevAgent** is an in-app normalization skill that cleans `llcExpRev` records imported from bank CSV files before they flow into the General Ledger, financial statements, and IRS schedules.

Bank-imported expense/revenue records are structurally correct (they balance) but arrive with two systematic orientation problems and one missing-data problem:

1. **Wrong account orientation** — bank imports put the expense account in `acct` and the cash account in `Ledger`. The LLC convention is the reverse: `acct` = the cash/funding account; `Ledger` = the expense or revenue counter account.

2. **Missing `acctSub`** — many records arrive without a sub-category. Without `acctSub`, transactions are invisible in grouped financial reports and cannot be mapped to Schedule E line items.

3. **Missing `propNm`** — some records have no property assignment. Without `propNm`, transactions cannot be allocated to the correct K-1 and cannot appear in per-property profit/loss analysis.

ExpRevAgent fixes all three in a single pass and presents a change summary before committing. It is **non-destructive**: it reads the current working file, applies corrections in memory, and waits for an explicit Commit before writing. Running it on an already-clean dataset produces zero changes.

**Typical first-run result on W&B Group 2025 data:**
- 40 records: cash-side swapped (orientation corrected)
- 17 records: `acctSub` inferred and filled
- 0 records: `propNm` defaulted (all records were already attributed)

---

## 2. Why Normalization Is Necessary

### 2.1 Source of Dirty Data

`llcExpRev` records originate from two sources:

| Source | Arrival State |
|---|---|
| **Bank CSV import** (`llcBank`) | `acct` = expense account, `Ledger` = `Acct.Cash.Bank` — backwards |
| **Manual entry** (web editor) | Entered by the bookkeeper; may have blank `acctSub` or `propNm` |

When the bank reconciliation view writes transactions to `llcExpRev`, it uses the bank's transaction perspective: the LLC spent cash from `Acct.Cash.Bank`, so that account is recorded as the "other side" (`Ledger`). The bookkeeper classifies the transaction to an expense account (`Acct.Exp.*`) which becomes `acct`. This is the bank's frame of reference, not the LLC's GL frame of reference.

### 2.2 Downstream Impact of Un-normalized Records

| Problem | Impact |
|---|---|
| Cash account in `Ledger` instead of `acct` | GL grouping by `acct` is broken — cash appears as a counter account instead of the primary funding source; expense is double-counted in the acct group |
| `acctSub` missing | Grouped Balance Sheet / Income Statement rows for that account collapse to a single unlabeled bucket; Schedule E line-item mapping fails |
| `propNm` missing | Transaction excluded from per-property P&L; K-1 allocator skips it; Form 8825 rental income summary is understated |

---

## 3. Rule 1 — Cash Account Orientation

### 3.1 Accounting Principle

In the W&B Group LLC general ledger, every expense or revenue transaction is recorded as a two-sided entry where:

- `acct` = the **cash / funding account** (`Acct.Cash.Bank` for most operating transactions)
- `Ledger` = the **expense, revenue, or equity counter account** (`Acct.Exp.*`, `Acct.Rev.*`, `Acct.Equity.*`)

This is the **bookkeeper's frame of reference**, not the bank's. It groups all cash movements under `acct = Acct.Cash.Bank`, making it easy to reconcile the GL cash balance against the bank statement.

### 3.2 The Swap Condition

> **If `Acct.Cash.*` appears in the `Ledger` field AND `Acct.Cash` does NOT appear in the `acct` field:**
> - Swap `acct` ↔ `Ledger`
> - Flip `aType`: `Debit` → `Credit`, `Credit` → `Debit`

The `aType` flip preserves balance. If the original entry had:
```
acct=Acct.Exp.Util   Ledger=Acct.Cash.Bank   aType=Debit   amt=$150
```
After the swap:
```
acct=Acct.Cash.Bank   Ledger=Acct.Exp.Util   aType=Credit   amt=$150
```
Both representations are accounting-equivalent (ΣDebits = ΣCredits across the ledger is unchanged), but the second form is consistent with the LLC convention.

**Records that are NOT swapped:**
- `acct` already contains `Acct.Cash` — already correct orientation
- Equity contribution records: `acct=Acct.Cash.Bank`, `Ledger=Acct.Equity.Owner.Capital.Funds` — correct as-is
- Revenue records: `acct=Acct.Cash.Bank`, `Ledger=Acct.Rev.Rent` — correct as-is
- Asset purchase records: `acct=Acct.Cash.Bank`, `Ledger=Acct.Fixed.*` — correct as-is

### 3.3 Examples

**Operating expense — before and after:**

| Field | Before (bank import) | After (ExpRevAgent) |
|---|---|---|
| `acct` | `Acct.Exp.Util` | `Acct.Cash.Bank` |
| `Ledger` | `Acct.Cash.Bank` | `Acct.Exp.Util` |
| `aType` | `Debit` | `Credit` |
| `acctSub` | `Elec` | `Elec` (unchanged) |

**Equity contribution — not swapped (already correct):**

| Field | Value |
|---|---|
| `acct` | `Acct.Cash.Bank` |
| `Ledger` | `Acct.Equity.Owner.Capital.Funds` |
| `aType` | `Debit` |

---

## 4. Rule 2 — acctSub Classification

### 4.1 Role of acctSub in Financial Reporting

`acctSub` is the **sub-category label** used to group transactions within an account on financial statements. It serves three functions:

1. **Income Statement grouping**: Expenses under `Acct.Exp.*` are grouped by `acctSub` to produce the Schedule E expense line items (repairs, utilities, insurance, depreciation, etc.)
2. **Balance Sheet grouping**: Asset and liability accounts use `acctSub` to separate property acquisitions from operating items
3. **IRS mapping**: `mapIRS2LLC.py` uses `(acct, acctSub)` tuples to assign amounts to specific Form 1065 / Schedule E lines

A transaction with a blank `acctSub` is treated as an uncategorized item — it appears in totals but is invisible in grouped views.

### 4.2 Inference Rules

When `acctSub` is empty, null, or `'nan'`, ExpRevAgent infers a value from the **reference account** (the `Ledger` field; or `acct` if Ledger is absent/nan):

| Condition | Assigned `acctSub` | Rationale |
|---|---|---|
| `Acct.Exp` in ref | `"Exp Other"` | Generic expense — bookkeeper should refine later |
| `Depr` in ref | `"Depreciation"` | Depreciation entries are always a distinct Schedule E line item |
| Default | `"{2nd dot-node} Other"` | Broad category from the COA path; e.g., `Acct.Fixed.Tangible.InService` → `"Fixed Other"`; `Acct.Equity.*` → `"Equity Other"` |

The `"Other"` suffix signals that the value was inferred, not explicitly set by a bookkeeper. This provides a useful audit flag in filtered views.

### 4.3 acctSub Taxonomy for W&B Group

Values currently in use across `llcExpRev` (W&B Group 2025):

| acctSub | Account family | Description |
|---|---|---|
| `Elec` | `Acct.Exp.Util` | Electricity |
| `Water` | `Acct.Exp.Util` | Water / sewer |
| `Waste` | `Acct.Exp.Util` | Waste removal |
| `Ins_Home` | `Acct.Exp.Util` | Homeowner's insurance |
| `Repair` | `Acct.Exp.Repair` | General repairs |
| `Maintenance` | `Acct.Exp.Repair` | Preventive maintenance |
| `Const` | `Acct.Exp.Repair` | Construction / improvement labor |
| `Plants` | `Acct.Exp.Other` | Landscaping / plants |
| `Celebration` | `Acct.Exp.Other` | Opening / celebration costs |
| `Income.Rent` | `Acct.Rev.Rent` | Rental income |
| `Invest RV Rental` | `Acct.Rev.Fees.Other` | RV rental investment fees |
| `Closing-805 High Mesa` | `Acct.Cash.Bank` | Cash deployed at property closing |
| `Balance Start` | `Acct.Cash.Bank` | Opening LLC bank balance |
| `Bank` | `Acct.Cash.Bank` | General banking activity |

`"Exp Other"` and other `"* Other"` suffixed values are ExpRevAgent defaults — the bookkeeper should replace them with specific values from the taxonomy above during the next review cycle.

---

## 5. Rule 3 — Property Attribution (propNm)

### 5.1 Why Every Transaction Must Have a Property

The LLC is a **multi-property rental partnership**. All revenue, expense, and capital activity must be attributed to a specific property for:

- **Schedule K-1 allocation**: profit and loss is allocated to members in proportion to their ownership percentage in each property. An unattributed transaction cannot be allocated.
- **Form 8825 (Rental Real Estate Income and Expenses)**: each property has its own column. Unattributed expenses are excluded.
- **Per-property P&L analysis**: the `stmtPropertyEquity` and GL views filter by `propNm`. An unattributed transaction is invisible in these views.
- **Future `assetList` reconciliation** (Issue #6): every GL row will be validated against the authoritative property registry. A `propNm` of `propUnknown` is the explicit sentinel for "needs attribution" and will be surfaced in the audit queue.

### 5.2 Default Value

When `propNm` is empty, null, or `'nan'`:

```
propNm → "propUnknown"
```

`"propUnknown"` is not a silent null — it is a **visible placeholder** that allows the transaction to participate in aggregations while clearly flagging it for the bookkeeper to correct. Any financial report filtering on specific property names will exclude `propUnknown` rows, preventing phantom income or expense from inflating property-level results.

---

## 6. Execution Order and Idempotency

The three rules run sequentially on each record in this order:

```
1. swap_cash_side      (may change acct, Ledger, aType)
2. fill_acct_sub       (reads the post-swap Ledger and acct values)
3. fill_prop_nm        (independent of rules 1 and 2)
```

**Rule 2 reads the post-swap state** because after swapping, the `Ledger` field now holds the meaningful counter account (expense, revenue, etc.) that is the correct reference for `acctSub` inference. If Rule 2 ran before Rule 1, it would infer from `Acct.Cash.Bank` (the pre-swap `acct`) and produce `"Cash Other"` for every swapped row — incorrect.

**Idempotency**: running ExpRevAgent a second time on already-normalized data produces zero changes. Every rule's pre-condition (`Acct.Cash` not in `acct`; `acctSub` is empty; `propNm` is empty) will already be false for all records.

---

## 7. Workflow — When to Run ExpRevAgent

```
Bank CSV reconciliation
        │ llcBank view imports transactions → llcExpRev working file
        ▼
llcExpRev view — Actions ▾ → 🧹 ExpenseAgent
        │ POST /api/expAgent/normalize — preview summary modal
        │
        ├─ 0 changes → already clean, dismiss
        │
        └─ N changes → review summary, click Commit
                │ saves normalized rows to working file
                ▼
        Actions ▾ → 💾 Save-Publish
                │ writes working file to llcExpRev_WBGroupLLC.json (DB)
                ▼
        GL / Financial Statements refresh with correct data
```

**Run ExpRevAgent:**
- After every bank CSV import session
- Before generating any financial statements or IRS PDFs
- Before running the K-1 allocation engine

**Do NOT run ExpRevAgent on:**
- `llcAssets` — asset records use a different orientation convention (propAgent commits them already normalized with `Ledger = 'nan'`)
- `llcPayables` / `llcReceivables` — these use different account conventions and are not currently in scope

---

## 8. Relationship to Financial Statements and IRS Forms

| Statement / Form | ExpRevAgent impact |
|---|---|
| **General Ledger** (`stmtGeneralLedger`) | Correct `acct` grouping — all cash activity consolidates under `Acct.Cash.Bank` |
| **Income Statement** (`stmtIncomeStmt`) | Correct expense/revenue amounts per `acctSub` bucket; Schedule E line items resolve |
| **Balance Sheet** (`stmtBalanceSheet`) | Cash balance accurate — no phantom expense accounts in asset section |
| **Owner Equity** (`stmtOwnerEquity`) | Equity contributions correctly attributed (already oriented; swap rule does not touch them) |
| **Form 8825** | Per-property rental expense lines correct when `propNm` is set |
| **Schedule K-1** | Profit/loss allocation per member per property resolves when `propNm` is set |
| **Form 4562** | Depreciation lines correct when `acctSub = "Depreciation"` is set |

---

## 9. Known Limitations & Future Work

| Limitation | Notes |
|---|---|
| `acctSub` defaults (`"Exp Other"`, `"Fixed Other"`, etc.) require bookkeeper review | ExpRevAgent flags them but does not know the specific sub-category (e.g., `Elec` vs `Water`); bookkeeper must update via the field editor |
| `propNm = "propUnknown"` must be corrected before IRS filing | Any K-1 or Form 8825 containing `propUnknown` amounts must be reviewed |
| No rule for `Acct.Rev.*` orientation check | Revenue records imported from bank are expected to already have `Acct.Cash.Bank` in `acct`; if any arrive inverted, they would be caught by Rule 1 only if `Acct.Cash` is also absent from `acct` |
| `acctSub` inference does not distinguish `Acct.Exp.Util` sub-types | All utilities default to `"Exp Other"` unless `acctSub` was set by the bookkeeper at import time |
| No rule for `tDB` / `refDB` cleanup | Rows imported from `llcBank` carry `tDB = "llcBank"` and `refDB = "llcBank"` — these are informational only and are not modified |
| ExpRevAgent operates on `llcExpRev` only | Other ledger DBs (`llcPayables`, `llcReceivables`) are not in scope |
