# NewPropertyAgent — Business Accounting Design

Module Owner: Business Accountant  
Status: Production (v0.3)  
System: llcRentalTracker / W&B Group, LLC  
Related Issue: [#6 LLC Property List Mgmt](https://github.com/wbgroupmgr/llcRentalTracker/issues/6)  
Last Updated: 2026-05-25

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Acceptable Document Formats](#2-acceptable-document-formats)
3. [IRS Tax Classification — Three-Bucket System](#3-irs-tax-classification--three-bucket-system)
   - 3.1 Capitalize — Adds to Property Basis
   - 3.2 Amortize — Loan Acquisition Costs
   - 3.3 Expense — Immediate Deductible
4. [Property Basis Calculation](#4-property-basis-calculation)
   - 4.1 Gross Adjusted Cost Basis
   - 4.2 Land / Building Split — Real Property Only
   - 4.3 Depreciation Schedule by Asset Type
   - 4.4 MACRS Mid-Month First-Year Estimate
   - 4.5 Year-End Depreciation Staging Entry
5. [COA Account Map at Purchase — Journaling Instructions](#5-coa-account-map-at-purchase--journaling-instructions)
   - 5.1 Real Property — ALTA/HUD-1 (House Rental)
   - 5.2 Personal Property — Bill of Sale (RV Rental)
   - 5.3 Resulting Balance Sheet Impact
6. [Escrow Clearing Account — Design Principle](#6-escrow-clearing-account--design-principle)
   - 6.1 Why Every Row Posts Through Acct.Cash.Escrow
   - 6.2 Escrow Balance as Balance Indicator
7. [Member Equity Flow — Funds from Outside to Asset](#7-member-equity-flow--funds-from-outside-to-asset)
   - 7.1 Overview
   - 7.2 Step-by-Step Fund Flow
   - 7.3 Out-of-Pocket Escrow (Member Bypasses LLC Bank)
   - 7.4 Bill of Sale — Simple Cash Purchase (RV)
   - 7.5 Member Ownership Percentages per Property
8. [Compound Journal Entry — Accounting Principle](#8-compound-journal-entry--accounting-principle)
9. [Audit Trail & Internal Controls](#9-audit-trail--internal-controls)
10. [Property Registry (Issue #6)](#10-property-registry-issue-6)
11. [Compound Journal Entry — Example Output](#11-compound-journal-entry--example-output)

---

## 1. Executive Summary

The **NewPropertyAgent** (formerly ClosingAid) is the accounting skill embedded in the llcRentalTracker app that onboards a newly acquired rental property into the LLC's asset ledger. It supports two acquisition document types:

- **ALTA / HUD-1 Settlement Statement** — real property (residential rental house) with a title company, mortgage lender, and multi-line closing statement
- **Bill of Sale** — personal property (RV, vehicle, equipment) purchased directly from a seller with a simple sales document

Both paths follow the same workflow (paste rows → classify → balance → commit) but differ in classification rules, depreciation method, and whether a land/building split applies.

The agent replaces manual data entry with a structured, IRS-compliant workflow that:

- Classifies every line item into the correct tax bucket (Capitalize / Amortize / Expense)
- Constructs a balanced compound journal entry for the `llcAssets` ledger
- Computes the property's adjusted cost basis per IRS Pub 551
- Applies land/building split for real property; skips it for personal property
- Estimates first-year MACRS depreciation (FY + YTD) at purchase time
- Optionally queues a Year-End scheduled depreciation staging entry
- Generates a PDF closing report filed alongside the source documents
- Attributes member capital contributions to individual equity sub-accounts
- Writes entries to `llcAssets_WBGroupLLC.json`

**Fundamental accounting principle**: All closing entries clear through `Acct.Cash.Escrow`
(the Ledger counter-account on every row). This single clearing account nets to **$0** when the
journal is balanced — confirming no residual liability has been recorded. No individual row
carries a dual contra account from the classification rules.

---

## 2. Acceptable Document Formats

| Format | Document Type | Columns | Typical Use |
|---|---|---|---|
| Standard | HUD-1 settlement | `Description`, `Debit`, `Credit` | Real property, older closings |
| ALTA Buyer/Seller | ALTA settlement | `Description`, `Buyer`, `Seller` | Real property, modern title companies |
| Bill of Sale | Personal property purchase | `Description`, `Amount` | RV, vehicle, equipment |

`Buyer` = charges to buyer → Debit in LLC books.  
`Seller` = credits to buyer → Credit in LLC books.  
`Amount` on a Bill of Sale is always a Debit (cost to LLC) unless it is a trade-in credit.

Input is pasted as a JSON array into the Step 1 dialog. Null/zero rows and "Totals" summary rows are automatically dropped.

**Control total (ALTA/HUD-1)**: The final cash reconciliation line (e.g. "Cash From Buyer") anchors the balance check.  
**Control total (Bill of Sale)**: Total Amount = purchase price + fees. A single Credit row for the payment from `Acct.Cash.Bank` balances the entry.

---

## 3. IRS Tax Classification — Three-Bucket System

Every line item is assigned to exactly one of three tax buckets per IRS Publication 551 (Basis of Assets) and the Internal Revenue Code.

### 3.1 Capitalize — Adds to Property Basis

These costs are added to the property's adjusted cost basis and recovered through depreciation over the asset's useful life. They do **not** hit the income statement in the year of purchase.

**Authority**: IRS Pub 551 — "The basis of property you buy is generally its cost."

**Real property (ALTA/HUD-1):**

| Line Item Type | Example | GL Account |
|---|---|---|
| Contract / sale price | `Sale Price of Property` | `Acct.Fixed.Tangible.InService` |
| Title / settlement / closing fee | `Title - Settlement or closing fee` | `Acct.Fixed.Tangible.InService` |
| E-recording / recording fees | `Recording fees: Deed`, `E-Recording Service Fee` | `Acct.Fixed.Tangible.InService` |
| Government recording / transfer charges | `Government Recording and Transfer Charges` | `Acct.Fixed.Tangible.InService` |
| Transfer tax | `Transfer Tax` | `Acct.Fixed.Tangible.InService` |
| Survey / notary | `Survey`, `Notary` | `Acct.Fixed.Tangible.InService` |
| Seller-paid tax proration credit | `County taxes 1/1 to 8/25` *(Credit)* | `Acct.Fixed.Tangible.InService` |
| Earnest / deposit (direct member funds) | `Deposit or Earnest Money from Buyer` | `Acct.Equity.Owner.Capital.Funds` |
| Option money (member personal funds) | `Option Money from W&B Group` | `Acct.Equity.Owner.Capital.Funds` |
| Cash to close / balance due | `Balance Due from Buyer`, `Cash to Close` | `Acct.Cash.Bank` |

> **Property tax proration note**: Seller tax credits (e.g. "County taxes 1/1 to 8/25") reduce the buyer's
> net cash outlay but are included in property basis per IRS Pub 551 — classified as Capitalize /
> `Acct.Fixed.Tangible.InService`. They are **not** posted to a liability account.

> **Earnest / Deposit note**: Personal member funds paid directly at closing (not through the LLC bank)
> are recorded as equity contributions (`Acct.Equity.Owner.Capital.Funds`), not as a clearing
> through `Acct.Cash.Escrow`. The escrow account was only relevant if the LLC bank pre-funded the
> deposit separately.

**Personal property — Bill of Sale (RV, vehicle, equipment):**

| Line Item Type | Example | GL Account |
|---|---|---|
| Purchase price | `Sale Price`, `Vehicle Purchase Price` | `Acct.Fixed.Tangible.InService` |
| Sales tax | `TX State Sales Tax` | `Acct.Fixed.Tangible.InService` |
| Title / registration fees | `Title Fee`, `Registration Fee` | `Acct.Fixed.Tangible.InService` |
| Delivery / transport fee | `Delivery Fee` | `Acct.Fixed.Tangible.InService` |
| Cash payment (funding credit) | `Payment from LLC Bank` | `Acct.Cash.Bank` (Credit) |

> Sales tax and registration fees are part of the cost of the property per IRS Pub 551 and are capitalized into basis — not expensed.

### 3.2 Amortize — Loan Acquisition Costs

Loan origination costs are capitalized to a contra-liability account and amortized straight-line over the life of the loan (IRC §163, IRS Pub 535). Applies to real property with a mortgage; rarely applies to a Bill of Sale purchase.

| Line Item Type | Example | GL Account |
|---|---|---|
| Loan principal | `New Loan Amount`, `Principal Amount` | `Acct.Liab.Morgage` (Credit) |
| Origination fee / points | `Loan Origination Fee`, `Loan Points` | `Acct.Liab.Morgage` |
| Appraisal fee | `Appraisal Fee` | `Acct.Liab.Morgage` |

### 3.3 Expense — Immediate Deductible

These items bypass the balance sheet and are deducted in the current tax year as ordinary and necessary business expenses on Schedule E (IRC §162).

| Line Item Type | Applies To | Example | GL Account |
|---|---|---|---|
| HOA dues / transfer fees | Real property | `HOA Transfer Fees` | `Acct.Exp.Operating` |
| Home warranty | Real property | `Home Warranty` | `Acct.Exp.Operating` |
| Inspection fee | Either | `Inspection` | `Acct.Exp.Operating` |
| Wire fee | Either | `Wire Fee` | `Acct.Exp.Operating` |
| Insurance premium (first year) | Personal property | `RV Insurance — 1yr Premium` | `Acct.Exp.Operating` |

---

## 4. Property Basis Calculation

### 4.1 Gross Adjusted Cost Basis

Gross Basis = sum of all **Capitalize + Debit** rows after classification.

```
Gross Basis = Sale Price + Capitalized Fees + Sales Tax + ...
```

Credits within the Capitalize bucket (seller tax proration, earnest money applied) represent
funding flows (equity contributions, bank draws) — they do not reduce the gross basis.

### 4.2 Land / Building Split — Real Property Only

IRS regulations require separating non-depreciable land from depreciable improvements for real property. The split is determined by the **current-year tax assessor's ratio**:

```
Land Basis     = Gross Basis × (Assessor Land Value / Total Assessed Value)
Building Basis = Gross Basis × (Assessor Improvement Value / Total Assessed Value)
```

The assessor ratio (`landPct`) is entered in Step 0. When `landPct > 0`, the agent consolidates all Capitalize-Debit-InService rows into **two** asset records:

- `Acct.Fixed.Land` — non-depreciable; no depreciation deduction ever
- `Acct.Fixed.Tangible.InService` — depreciable building basis

**Bill of Sale purchases set `landPct = 0`** — personal property (RV, vehicle) has no land component; no split is applied; the full basis stays in `Acct.Fixed.Tangible.InService`.

**Example (805 High Mesa, Wimberley TX — residential rental):**
- Gross Basis: $220,825
- Assessor Land %: 20% → Land Basis: $44,165
- Assessor Improvement %: 80% → Building Basis: $176,660

### 4.3 Depreciation Schedule by Asset Type

| Asset Type | IRS Class Life | Method | Recovery Period | Authority |
|---|---|---|---|---|
| Residential rental (house) | Real property | Straight-line, mid-month | **27.5 years** | IRC §168(c) |
| Non-residential rental (commercial) | Real property | Straight-line, mid-month | 39 years | IRC §168(c) |
| RV / trailer | Personal property | MACRS, half-year convention | **5 years** | Rev. Proc. 87-56, Asset Class 00.22 |
| Automobile / light truck | Personal property | MACRS, half-year | 5 years | Asset Class 00.22 |
| Furniture / fixtures | Personal property | MACRS | 7 years | Asset Class 00.11 |

**Section 179 / Bonus Depreciation**: Personal property (RV, vehicle) may qualify for full immediate expensing in the year placed in service. This is a tax-time election — the NewPropertyAgent always records at full capitalized cost; the depreciation election is made on Form 4562.

### 4.4 MACRS Mid-Month First-Year Estimate

For residential real property, the system computes an estimated first-year depreciation at purchase time using the **MACRS mid-month convention** (IRS Rev. Proc. 87-57, Table A-6):

```
Full-Year Depreciation  = Building Basis / 27.5
Months in Service (YTD) = 12 − closing_month + 0.5   (mid-month: placed in service mid-month)
YTD Depreciation        = Full-Year × (Months in Service / 12)
```

**Example** — closing month August (month 8):
```
Months in service = 12 − 8 + 0.5 = 4.5 months
Full-Year  = $176,660 / 27.5 = $6,423.64
YTD        = $6,423.64 × (4.5 / 12) = $2,408.87
```

This estimate is **informational only** at purchase time — the authoritative depreciation deduction is computed on Form 4562 at year-end. The Step 3 dialog displays both amounts and optionally queues a YE staging entry (see §4.5).

### 4.5 Year-End Depreciation Staging Entry (`Acct.Recurring.Exp`)

If the user clicks **"YE Post?"** in Step 3, a scheduled staging entry is appended to the commit:

| Field | Value |
|---|---|
| `acct` | `Acct.Recurring.Exp` |
| `Ledger` | `Acct.Recurring.Exp` (self-clearing staging account) |
| `aType` | `Debit` |
| `amt` | YTD depreciation estimate |
| `acctSub` | `YE:Acct.Exp.Depreciation-Acct.Fixed.Depreciation.Accum` |
| `tID` | `{tID_Prefix}_depr_ytd` |

`Acct.Recurring.Exp` (9010) is a **staging / pass-through account** — it does not appear on the final Balance Sheet. The `acctSub` field encodes the actual year-end posting targets:
- **Debit**: `Acct.Exp.Depreciation` (P&L expense — flows to Schedule E)
- **Credit**: `Acct.Fixed.Depreciation.Accum` (contra-asset — reduces book value of building)

The YE processor reads all `Acct.Recurring.Exp` staging records and posts them to their target accounts at fiscal year-end.

> **Why stage instead of direct post?** The YTD amount at purchase is an estimate. The CPA may adjust the
> final depreciation figure on Form 4562. Staging allows the estimate to be recorded now without
> locking in the final tax entry — the YE processor can override the amount before final posting.

---

## 5. COA Account Map at Purchase — Journaling Instructions

Every committed entry uses `Ledger = 'Acct.Cash.Escrow'` as the counter-account (see §6). The collection of all rows forms a balanced compound journal entry (ΣDebits = ΣCredits).

### 5.1 Real Property — ALTA/HUD-1 (House Rental)

| Side | COA Account | Description | Condition |
|---|---|---|---|
| **DR** | `Acct.Fixed.Land` | Non-depreciable land component | `landPct > 0` |
| **DR** | `Acct.Fixed.Tangible.InService` | Depreciable building basis | Always (consolidated after land split) |
| **DR** | `Acct.Exp.Operating` | HOA, warranty, inspection, wire fee | If present |
| **CR** | `Acct.Cash.Bank` | LLC bank funds used at closing | Cash-to-close rows |
| **CR** | `Acct.Equity.Owner.Capital.Funds` | Member personal funds (earnest, option, deposit) | If member-funded |
| **CR** | `Acct.Liab.Morgage` | New loan principal from lender | If financed |

*All rows carry `Ledger = 'Acct.Cash.Escrow'`* — the escrow clears to $0 when ΣDebits = ΣCredits.

**Compound balance invariant**: ΣDebits = ΣCredits ± $0.01 before Commit is allowed.

### 5.2 Personal Property — Bill of Sale (RV Rental)

| Side | COA Account | Description | Condition |
|---|---|---|---|
| **DR** | `Acct.Fixed.Tangible.InService` | Full purchase price + sales tax + title fees | Always |
| **DR** | `Acct.Exp.Operating` | Insurance premium, inspection fee | If present |
| **CR** | `Acct.Cash.Bank` | LLC bank funds used for purchase | Always |

### 5.3 Resulting Balance Sheet Impact

After commit, the LLC balance sheet reflects:

| Account | Direction | Effect |
|---|---|---|
| `Acct.Fixed.Land` | Increases | Land asset on books |
| `Acct.Fixed.Tangible.InService` | Increases | Depreciable asset on books |
| `Acct.Cash.Bank` | Decreases | LLC cash deployed |
| `Acct.Equity.Owner.Capital.Funds` | Increases | Member equity recorded |
| `Acct.Liab.Morgage` | Increases | Liability for loan principal |
| `Acct.Exp.Operating` | Increases | P&L expense in period |
| `Acct.Cash.Escrow` | **$0 net** | Clears to zero — confirms balanced journal |

---

## 6. Escrow Clearing Account — Design Principle

### 6.1 Why Every Row Posts Through Acct.Cash.Escrow

`Acct.Cash.Escrow` (1025) is the **Ledger counter-account** on every row produced by `toAssetRecords()`.

**Purpose**: Property purchases flow through an escrow/title company before closing. The escrow account models this real-world holding:
- Earnest money, option fees, and lender proceeds all enter escrow before the deal closes
- At closing, the escrow disburses funds to the seller, pays fees, and remits net proceeds

In the GL, posting every closing entry as `Ledger = 'Acct.Cash.Escrow'` means:
- Each Debit row increases the escrow balance (money leaving escrow for an asset or expense)
- Each Credit row decreases the escrow balance (funding entering escrow)
- When the journal is balanced, the escrow net = $0 — all funds in equal all funds out

This avoids the previous design of `Ledger = 'nan'` (single-sided entry) while keeping the compound journal semantics intact. The escrow account is a transient clearing account — it should net to $0 at all times after a completed purchase.

### 6.2 Escrow Balance as Balance Indicator

The Step 3 Balance panel shows **"🏦 Escrow Holding Balance"**:

```
Escrow Balance = ΣDebits − ΣCredits
```

- **$0.00 (green)** → Journal balanced; commit is allowed
- **Non-zero (red)** → Journal unbalanced; delta displayed; Balance Assist suggests a correcting entry

This is identical to a traditional debit/credit balance check but surfaced through the clearing account lens — making it intuitive for property purchase workflows.

---

## 7. Member Equity Flow — Funds from Outside to Asset

### 7.1 Overview

```
Member Personal Bank
        │ wire / transfer
        ▼
LLC Bank Account (Acct.Cash.Bank)
        │ recorded in llcExpRev
        │  DR Acct.Cash.Bank
        │  CR Acct.Equity.Owner.Capital.Funds.{oID}
        │
        ▼
NewPropertyAgent — Purchase Commit (llcAssets)
        │  DR Acct.Fixed.Tangible.InService    Ledger=Acct.Cash.Escrow
        │  DR Acct.Fixed.Land                  Ledger=Acct.Cash.Escrow
        │  CR Acct.Cash.Bank                   Ledger=Acct.Cash.Escrow
        │
        ▼
Net Compound Journal (across both books):
   DR Acct.Fixed.Tangible.InService
   CR Acct.Equity.Owner.Capital.Funds.{oID}
   → Member equity becomes a fixed asset
```

`Acct.Cash.Bank` is the **pass-through account** linking the two books. It increments in `llcExpRev` and decrements in `llcAssets`. In the merged GL, the cash entries net to zero if all transferred funds were used for the purchase.

### 7.2 Step-by-Step Fund Flow

**Step 1 — Member transfers funds to LLC bank** (recorded in `llcExpRev`)

```
Date:  2025-08-15
DR  Acct.Cash.Bank                              $50,000   [LLC bank balance increases]
  CR  Acct.Equity.Owner.Capital.Funds.o_Frank   $50,000   [Frank's equity increases]
```

**Step 2 — NPAgent commits purchase to llcAssets** (all rows `Ledger=Acct.Cash.Escrow`)

```
Date:  2025-08-20  (closing date)

DR  Acct.Fixed.Tangible.InService   $141,223   [building 80%]    Ledger=Acct.Cash.Escrow
DR  Acct.Fixed.Land                  $79,438   [land 20%]        Ledger=Acct.Cash.Escrow
DR  Acct.Exp.Operating                  $135   [HOA fee]         Ledger=Acct.Cash.Escrow
  CR  Acct.Cash.Bank                $213,837   [LLC bank pays]   Ledger=Acct.Cash.Escrow
  CR  Acct.Equity.Owner.Capital.Funds $5,000   [earnest deposit] Ledger=Acct.Cash.Escrow
  CR  Acct.Liab.Morgage             ...        [loan proceeds]   Ledger=Acct.Cash.Escrow

Escrow Net = $0  ✓
```

**Step 3 — GL merges both books**

| Account | llcExpRev | llcAssets | Net |
|---|---|---|---|
| `Acct.Cash.Bank` | +$50,000 DR | −$213,837 CR | Net negative (cash deployed) |
| `Acct.Equity.Owner.Capital.Funds` | +$50,000 CR | +$5,000 CR | Total equity contributed |
| `Acct.Fixed.Tangible.InService` | — | +$141,223 DR | Asset on books |
| `Acct.Fixed.Land` | — | +$79,438 DR | Land on books |

### 7.3 Out-of-Pocket Escrow (Member Bypasses LLC Bank)

When a member pays earnest money or option fees **before** the LLC bank received funds:

- The closing statement shows the payment as a Credit (applied against purchase price)
- In the LLC books, this is a **direct equity contribution** from that specific member
- No `llcExpRev` entry exists — it never passed through the LLC bank
- The NPAgent captures it as: Credit row → `Acct.Equity.Owner.Capital.Funds`
- The Balance Assist feature (Step 3) searches the GL for prior `Acct.Equity.Owner.Capital.Funds` credits to surface the full funding chain

### 7.4 Bill of Sale — Simple Cash Purchase (RV)

**Step 1** — Member had previously transferred funds to LLC bank (in `llcExpRev`):
```
DR  Acct.Cash.Bank                             $XX,XXX
  CR  Acct.Equity.Owner.Capital.Funds.{oID}   $XX,XXX
```

**Step 2** — NPAgent commits purchase (2 rows in llcAssets, `Ledger=Acct.Cash.Escrow`):
```
DR  Acct.Fixed.Tangible.InService              $XX,XXX   [full purchase price + taxes + fees]
  CR  Acct.Cash.Bank                           $XX,XXX   [LLC bank pays seller]
```

**Net**: Member equity → fixed asset. Cash nets to zero.

### 7.5 Member Ownership Percentages per Property

Each property carries a `propOwners` dict mapping member oIDs to ownership percentages:

```json
"propOwners": { "o_Frank": 60, "o_Will": 40 }
```

This drives:
- **Schedule K-1**: profit/loss allocated in ownership ratio
- **Form 8825**: rental income/expense per property per member
- **Owner Equity statements**: each member's equity in each property

Until Issue #6 Phase 1 is implemented, `propOwners` is entered as a free-text string in Step 0 Preface.

---

## 8. Compound Journal Entry — Accounting Principle

Purchase entries are posted with `Ledger = 'Acct.Cash.Escrow'` — every row uses the escrow clearing account as its counter-entry. The rationale:

- The full purchase document (ALTA or Bill of Sale) **as a whole** is the compound journal entry. ΣDebits = ΣCredits across all rows.
- The escrow account models the real-world title escrow through which all closing funds flow.
- When ΣDebits = ΣCredits, the escrow nets to **$0** — confirming no residual holding liability.
- This is materially equivalent to a compound journal entry in traditional double-entry bookkeeping.

The `toGL()` and `toDoubleEntry()` functions in the ledger engine handle `Ledger = 'Acct.Cash.Escrow'` by generating a paired GL row for each closing entry. The escrow rows net to zero in the merged GL.

**Historical note**: Prior to v0.3, propAgent used `Ledger = 'nan'` (single-sided entries). The design was changed to `Acct.Cash.Escrow` to make the clearing account explicit and auditable.

---

## 9. Audit Trail & Internal Controls

- Every committed record carries `refDoc = f"{propNm}, Closing Docs, {tax_bucket}, {closingDoc}"` — embedding tax bucket and source document in the audit trail per row.
- `refDB` (user-entered, Step 0) identifies the source DB or document folder reference; stored on every record.
- `tDB = 'llcAssets'` identifies the target ledger of every record.
- The system must not post directly to the general ledger; all entries write to the `llcAssets` manual journal pending CPA review.
- The original settlement statement PDF or Bill of Sale scan must be stored in the business repo under `LLC-WBGroup/Assets/{propNm}/Docs/` for IRS audit purposes.
- **PDF Report**: On every commit, the agent auto-generates a PDF report (`{date}_PurchaseNewProp_{propNm}.pdf`) filed in the same folder as `refDoc`. The report contains: closing info, original settlement lines, property basis, depreciation estimate, committed journal, and accounting guide.

---

## 10. Property Registry (Issue #6)

The NewPropertyAgent is the **primary entry point for registering a new property** in the `assetList` registry (Phase 1 of [Issue #6](https://github.com/wbgroupmgr/llcRentalTracker/issues/6)). On commit, `toAssetRecords()` will additionally call `save_asset_list()` to write:

**Real property example:**
```json
{
  "propNm":      "H_805HighMesa",
  "propAddr":    "805 High Mesa Dr, Wimberley TX",
  "assetType":   "Residential",
  "assetState":  "InService",
  "closingDate": "2025.08.20",
  "tID_Prefix":  "r20250825_220000",
  "closingDoc":  "Final Closing Package (Buyer or Borrower)_2.pdf",
  "landPct":     20.0,  "bldgPct": 80.0,
  "grossBasis":  220825.0,
  "landBasis":   44165.0,  "bldgBasis": 176660.0,
  "propOwners":  { "o_Frank": 50, "o_Will": 50 }
}
```

Until Issue #6 is implemented, `propOwners` is stored as a string and the `assetList` registry does not yet exist.

---

## 11. Compound Journal Entry — Example Output

### 11.1 Real Property — 805 High Mesa (Wimberley TX, 2025-08-20)

All rows: `Ledger = Acct.Cash.Escrow`

| GL Account | Debit | Credit | Tax Bucket | Notes |
|---|---|---|---|---|
| `Acct.Fixed.Land` | $44,165 | | Capitalize | 20% land split |
| `Acct.Fixed.Tangible.InService` | $176,660 | | Capitalize | 80% building split |
| `Acct.Exp.Operating` | $35 | | Expense | HOA dues |
| `Acct.Exp.Operating` | $100 | | Expense | HOA transfer fee |
| `Acct.Equity.Owner.Capital.Funds` | | $5,000 | Capitalize | Earnest deposit (member funds) |
| `Acct.Equity.Owner.Capital.Funds` | | $300 | Capitalize | Option money (member funds) |
| `Acct.Fixed.Tangible.InService` | | $1,661 | Capitalize | County tax proration (seller credit, reduces basis) |
| `Acct.Cash.Bank` | | $213,999 | Capitalize | Cash to close from LLC bank |
| **TOTALS** | **$220,960** | **$220,960** | | Balanced ✓ — Escrow = $0 |

*YE Depreciation Staging (if "YE Post?" selected in Step 3):*

| GL Account | Dr/Cr | Amount | acctSub |
|---|---|---|---|
| `Acct.Recurring.Exp` | Debit | $2,409 (YTD est.) | `YE:Acct.Exp.Depreciation-Acct.Fixed.Depreciation.Accum` |

*MACRS mid-month: closing Aug (month 8) → 4.5 months in service → $176,660/27.5 × 4.5/12 = $2,409*

### 11.2 Personal Property — RV Airstream (Bill of Sale, 2025-06-01)

All rows: `Ledger = Acct.Cash.Escrow`

| GL Account | Debit | Credit | Tax Bucket | Notes |
|---|---|---|---|---|
| `Acct.Fixed.Tangible.InService` | $43,500 | | Capitalize | Purchase price |
| `Acct.Fixed.Tangible.InService` | $1,200 | | Capitalize | TX sales tax (part of basis) |
| `Acct.Fixed.Tangible.InService` | $300 | | Capitalize | Title + registration fees |
| `Acct.Exp.Operating` | $800 | | Expense | First-year insurance premium |
| `Acct.Cash.Bank` | | $45,800 | Capitalize | LLC bank pays seller |
| **TOTALS** | **$45,800** | **$45,800** | | Balanced ✓ — Escrow = $0 |

> Depreciation for the RV: Year 1 MACRS = $45,000 × 20% = $9,000 (insurance $800 already expensed). Recorded on Form 4562.
