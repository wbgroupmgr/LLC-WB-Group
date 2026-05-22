# NewPropertyAgent — Business Accounting Design

Module Owner: Business Accountant  
Status: Production (v0.3)  
System: llcRentalTracker / W&B Group, LLC  
Related Issue: [#6 LLC Property List Mgmt](https://github.com/wbgroupmgr/llcRentalTracker/issues/6)

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
5. [COA Account Map at Purchase — Journaling Instructions](#5-coa-account-map-at-purchase--journaling-instructions)
   - 5.1 Real Property — ALTA/HUD-1 (House Rental)
   - 5.2 Personal Property — Bill of Sale (RV Rental)
   - 5.3 Resulting Balance Sheet Impact
6. [Member Equity Flow — Funds from Outside to Asset](#6-member-equity-flow--funds-from-outside-to-asset)
   - 6.1 Overview
   - 6.2 Step-by-Step Fund Flow
   - 6.3 Out-of-Pocket Escrow (Member Bypasses LLC Bank)
   - 6.4 Bill of Sale — Simple Cash Purchase (RV)
   - 6.5 Member Ownership Percentages per Property
7. [One-Sided GL Posting (Accounting Principle)](#7-one-sided-gl-posting-accounting-principle)
8. [Audit Trail & Internal Controls](#8-audit-trail--internal-controls)
9. [Property Registry (Issue #6)](#9-property-registry-issue-6)
10. [Compound Journal Entry — Example Output](#10-compound-journal-entry--example-output)

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
- Attributes member capital contributions to individual equity sub-accounts
- Writes `manualJournal` entries to `llcAssets_WBGroupLLC.json` and (Phase 1, Issue #6) registers the property in `assetList`

**Fundamental accounting principle**: Each line item is posted as a one-sided GL entry (`Ledger = 'nan'`). The collection of all rows forms a balanced compound journal entry (ΣDebits = ΣCredits). No individual row carries a dual account.

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

Input is pasted as CSV or tab-delimited text into the Step 1 dialog. Null/zero rows and "Totals" summary rows are automatically dropped.

**Control total (ALTA/HUD-1)**: The final cash reconciliation line (e.g. "Cash From Buyer" or "Balance Due") anchors the balance check.  
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
| Seller-paid tax proration credit | `County taxes 1/1 to 8/25` (Credit) | `Acct.Fixed.Tangible.InService` |
| Earnest / deposit (LLC bank-funded) | `Deposit or Earnest Money from W&B Group` | `Acct.Cash.Bank` |
| Option money (member personal funds) | `Option Money from W&B Group` | `Acct.Equity.Owner.Capital.Funds` |
| Cash to close / balance due | `Balance Due from Buyer` | `Acct.Cash.Bank` |

> Property tax prorations credited by the seller reduce the buyer's net cost and are included in basis per IRS Pub 551.

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

Credits within the Capitalize bucket (seller tax proration, earnest money applied) are NOT subtracted from basis — they represent separate funding flows (equity contributions, bank draws), not basis reductions.

### 4.2 Land / Building Split — Real Property Only

IRS regulations require separating non-depreciable land from depreciable improvements for real property. The split is determined by the **current-year tax assessor's ratio**:

```
Land Basis     = Gross Basis × (Assessor Land Value / Total Assessed Value)
Building Basis = Gross Basis × (Assessor Improvement Value / Total Assessed Value)
```

The assessor ratio (`landPct`) is entered in Step 0. When `landPct > 0`, the agent consolidates all Capitalize-Debit-InService rows into two asset records:

- `Acct.Fixed.Land` — non-depreciable; no depreciation deduction ever
- `Acct.Fixed.Tangible.InService` — depreciable building basis

**Bill of Sale purchases set `landPct = 0`** — personal property (RV, vehicle) has no land component; no split is applied; the full basis stays in `Acct.Fixed.Tangible.InService`.

**Example (805 High Mesa, Wimberley TX — residential rental):**
- Gross Basis: $303,700
- Assessor Land %: 20% → Land Basis: $60,740
- Assessor Improvement %: 80% → Building Basis: $242,960

### 4.3 Depreciation Schedule by Asset Type

| Asset Type | IRS Class Life | Method | Recovery Period | Authority |
|---|---|---|---|---|
| Residential rental (house) | Real property | Straight-line, mid-month | **27.5 years** | IRC §168(c) |
| Non-residential rental (commercial) | Real property | Straight-line, mid-month | 39 years | IRC §168(c) |
| RV / trailer | Personal property | MACRS, half-year convention | **5 years** | Rev. Proc. 87-56, Asset Class 00.22 |
| Automobile / light truck | Personal property | MACRS, half-year | 5 years | Asset Class 00.22 |
| Furniture / fixtures | Personal property | MACRS | 7 years | Asset Class 00.11 |

**Section 179 / Bonus Depreciation**: Personal property (RV, vehicle) may qualify for full immediate expensing in the year placed in service. This is a tax-time election — the NewPropertyAgent always records at full capitalized cost; the depreciation election is made on Form 4562.

**Residential rental depreciation example (805 High Mesa):**
```
Annual Depreciation = $242,960 / 27.5 = $8,835 / year
```

**RV rental depreciation example (Airstream):**
```
Annual Depreciation (MACRS Yr 1, half-year) = Cost Basis × 20.00%
Annual Depreciation (MACRS Yr 2) = Cost Basis × 32.00%
```

Both feed Form 4562 and flow to Schedule E of Form 1065.

---

## 5. COA Account Map at Purchase — Journaling Instructions

The following tables define exactly which COA accounts the NewPropertyAgent posts to when a purchase is committed. Every entry is **one-sided** (`Ledger = 'nan'`); the collection of rows forms the complete compound journal entry.

### 5.1 Real Property — ALTA/HUD-1 (House Rental)

| Side | COA Account | Description | Condition |
|---|---|---|---|
| **DR** | `Acct.Fixed.Land` | Non-depreciable land component | `landPct > 0` |
| **DR** | `Acct.Fixed.Tangible.InService` | Depreciable building basis | Always |
| **DR** | `Acct.Exp.Operating` | HOA, warranty, inspection, wire fee | If present |
| **CR** | `Acct.Cash.Bank` | LLC bank funds used at closing | Cash-to-close rows |
| **CR** | `Acct.Equity.Owner.Capital.Funds` | Member escrow paid out-of-pocket | If member paid personally |
| **CR** | `Acct.Liab.Morgage` | New loan principal from lender | If financed |

**Compound balance invariant**: ΣDebits = ΣCredits ± $0.01 before Commit is allowed.

### 5.2 Personal Property — Bill of Sale (RV Rental)

| Side | COA Account | Description | Condition |
|---|---|---|---|
| **DR** | `Acct.Fixed.Tangible.InService` | Full purchase price + sales tax + title fees | Always |
| **DR** | `Acct.Exp.Operating` | Insurance premium, inspection fee | If present |
| **CR** | `Acct.Cash.Bank` | LLC bank funds used for purchase | Always |

> For a simple cash purchase from a Bill of Sale, the entry is a two-row compound entry: one DR for the asset cost, one CR for the bank payment. No mortgage, no equity contributions unless a member funded the purchase directly without going through the LLC bank first (see Section 6.3).

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

---

## 6. Member Equity Flow — Funds from Outside to Asset

This section traces the complete path of member funds from a personal bank account into the LLC books and finally into the purchased asset.

### 6.1 Overview

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
NewPropertyAgent — Purchase Commit
        │ recorded in llcAssets
        │  DR Acct.Fixed.Tangible.InService (and/or Land, Expense)
        │  CR Acct.Cash.Bank
        │
        ▼
Net Compound Journal (across both books):
   DR Acct.Fixed.Tangible.InService
   CR Acct.Equity.Owner.Capital.Funds.{oID}
   → Member equity becomes a fixed asset
```

`Acct.Cash.Bank` is the **pass-through account** that links the two books. It increments in `llcExpRev` (Step 1) and decrements in `llcAssets` (Step 2). In the merged GL, the cash entries net to zero if all transferred funds were used for the purchase.

### 6.2 Step-by-Step Fund Flow

**Step 1 — Member transfers funds to LLC bank** (recorded in `llcExpRev`)

Each member wire or transfer into the LLC bank account is entered as a dual-entry transaction in `llcExpRev`:

```
Date:  2025-08-15
DR  Acct.Cash.Bank                              $50,000   [LLC bank balance increases]
  CR  Acct.Equity.Owner.Capital.Funds.o_Frank   $50,000   [Frank's equity increases]
```

This is a standard dual-entry record — `Ledger` field is set to the counter account, not `'nan'`.

**Step 2 — NPAgent commits purchase to llcAssets** (one-sided entries via NewPropertyAgent)

At the moment of property purchase, the NPAgent creates one-sided entries:

```
Date:  2025-08-26  (closing / bill of sale date)

DR  Acct.Fixed.Tangible.InService   $242,960   [building basis]      Ledger='nan'
DR  Acct.Fixed.Land                  $60,740   [land component]      Ledger='nan'
DR  Acct.Exp.Operating                  $135   [HOA fee]             Ledger='nan'
  CR  Acct.Cash.Bank                $296,874   [LLC bank pays]       Ledger='nan'
  CR  Acct.Equity.Owner.Capital.Funds  $5,300  [Frank's personal escrow] Ledger='nan'
  CR  Acct.Liab.Morgage             ...        [loan proceeds]       Ledger='nan'
```

**Step 3 — GL merges both books**

The merged General Ledger (`llcExpRev + llcAssets + llcPayables + llcReceivables`) shows:

| Account | llcExpRev | llcAssets | Net |
|---|---|---|---|
| `Acct.Cash.Bank` | +$50,000 DR | -$296,874 CR | Net negative (cash deployed) |
| `Acct.Equity.Owner.Capital.Funds` | +$50,000 CR | +$5,300 CR | Total equity contributed |
| `Acct.Fixed.Tangible.InService` | — | +$242,960 DR | Asset on books |
| `Acct.Fixed.Land` | — | +$60,740 DR | Land on books |

### 6.3 Out-of-Pocket Escrow (Member Bypasses LLC Bank)

When a member pays earnest money or option fees **before** the LLC bank received funds:

- The closing statement shows the payment as a Credit (applied against purchase price)
- In the LLC books, this is a **direct equity contribution** from that specific member
- No `llcExpRev` entry exists for it — it never passed through the LLC bank
- The NPAgent captures it as a Credit row → `Acct.Equity.Owner.Capital.Funds`
- The Balance Assist feature (Step 3 of dialog) searches the GL for prior `Acct.Equity.Owner.Capital.Funds` credits to surface the full funding chain

### 6.4 Bill of Sale — Simple Cash Purchase (RV)

For a straight-line Bill of Sale purchase funded entirely from the LLC bank:

**Step 1** — Member had previously transferred funds to LLC bank (recorded in `llcExpRev`):
```
DR  Acct.Cash.Bank                             $XX,XXX
  CR  Acct.Equity.Owner.Capital.Funds.{oID}   $XX,XXX
```

**Step 2** — NPAgent commits purchase (2 rows in llcAssets):
```
DR  Acct.Fixed.Tangible.InService              $XX,XXX   [full purchase price + taxes + fees]
  CR  Acct.Cash.Bank                           $XX,XXX   [LLC bank pays seller]
```

**Net**: Member equity → fixed asset. Cash nets to zero.

### 6.5 Member Ownership Percentages per Property

Each property in `assetList` (Issue #6) carries a `propOwners` dict mapping member oIDs to ownership percentages:

```json
"propOwners": { "o_Frank": 60, "o_Will": 40 }
```

This drives:
- **Schedule K-1**: profit/loss allocated in ownership ratio
- **Form 8825**: rental income/expense per property per member
- **Owner Equity statements**: each member's equity in each property

Until Issue #6 Phase 1 is implemented, `propOwners` is entered as a free-text string in Step 0 Preface.

---

## 7. One-Sided GL Posting (Accounting Principle)

Purchase entries are posted with `Ledger = 'nan'` — a deliberate single-sided compound entry. The rationale:

- The full purchase document (ALTA or Bill of Sale) **as a whole** is the compound journal entry. ΣDebits = ΣCredits across all rows.
- Each individual row does NOT have a single meaningful counter account — the "other side" is distributed across equity, liability, expense, and cash accounts within the same batch.
- Posting one-sided prevents phantom duplicate GL entries while preserving the full audit trail.
- This is materially equivalent to a compound journal entry in traditional double-entry bookkeeping.

The `toGL()` and `toDoubleEntry()` functions in the ledger engine skip the second side when `Ledger == 'nan'`, preserving correct GL totals.

---

## 8. Audit Trail & Internal Controls

- Every committed record carries `refDoc = f"{propNm}, Closing Docs, {tax_bucket}, {closingDoc}"` — embedding tax bucket and source document in the audit trail per row.
- `refDB = 'propAgent'` and `tDB = 'llcAssets'` identify the origin of every record.
- The system must not post directly to the general ledger; all entries write to the `llcAssets` manual journal pending CPA review.
- The original settlement statement PDF or Bill of Sale scan must be stored in the business repo (`LLC-WBGroup/books/YYYY/`) for IRS audit purposes.
- **Bill of Sale**: attach scan to the `closingDoc` reference field in the Preface; store under `LLC-WBGroup/Assets/{propNm}/Docs/`.

---

## 9. Property Registry (Issue #6)

The NewPropertyAgent is the **primary entry point for registering a new property** in the `assetList` registry (Phase 1 of [Issue #6](https://github.com/wbgroupmgr/llcRentalTracker/issues/6)). On commit, `toAssetRecords()` will additionally call `save_asset_list()` to write:

**Real property example:**
```json
{
  "propNm":      "H_805HighMesa",
  "propAddr":    "805 High Mesa Dr, Wimberley TX",
  "assetType":   "Residential",
  "assetState":  "InService",
  "closingDate": "2025.08.26",
  "tID_Prefix":  "p20250826-Mesa",
  "closingDoc":  "ALTA_2025.pdf",
  "landPct":     20.0,  "bldgPct": 80.0,
  "grossBasis":  303700.0,
  "landBasis":   60740.0,  "bldgBasis": 242960.0,
  "propOwners":  { "o_Frank": 50, "o_Will": 50 }
}
```

**Personal property example (RV):**
```json
{
  "propNm":      "RV_Airstream",
  "propAddr":    "Mobile — TX",
  "assetType":   "RV",
  "assetState":  "InService",
  "closingDate": "2025.06.01",
  "tID_Prefix":  "rv20250601-Airstream",
  "closingDoc":  "BillOfSale_Airstream.pdf",
  "landPct":     0.0,  "bldgPct": 0.0,
  "grossBasis":  45000.0,
  "landBasis":   0.0,  "bldgBasis": 45000.0,
  "propOwners":  { "o_Frank": 60, "o_Will": 40 }
}
```

Until Issue #6 is implemented, `propOwners` is stored as a string and the `assetList` registry does not yet exist.

---

## 10. Compound Journal Entry — Example Output

### 10.1 Real Property — 805 High Mesa (Wimberley TX, 2025-08-26)

| GL Account | Debit | Credit | Tax Bucket | Notes |
|---|---|---|---|---|
| `Acct.Fixed.Land` | $60,740 | | Capitalize | 20% land split |
| `Acct.Fixed.Tangible.InService` | $242,960 | | Capitalize | 80% building split |
| `Acct.Exp.Operating` | $135 | | Expense | HOA dues + transfer fee |
| `Acct.Equity.Owner.Capital.Funds` | | $5,300 | Capitalize | Frank's escrow (out-of-pocket) |
| `Acct.Cash.Bank` | | $1,661 | Capitalize | Seller county tax proration credit |
| `Acct.Cash.Bank` | | $296,874 | Capitalize | Cash to close from LLC bank |
| **TOTALS** | **$303,835** | **$303,835** | | Balanced ✓ |

### 10.2 Personal Property — RV Airstream (Bill of Sale, 2025-06-01)

| GL Account | Debit | Credit | Tax Bucket | Notes |
|---|---|---|---|---|
| `Acct.Fixed.Tangible.InService` | $43,500 | | Capitalize | Purchase price |
| `Acct.Fixed.Tangible.InService` | $1,200 | | Capitalize | TX sales tax (part of basis) |
| `Acct.Fixed.Tangible.InService` | $300 | | Capitalize | Title + registration fees |
| `Acct.Exp.Operating` | $800 | | Expense | First-year insurance premium |
| `Acct.Cash.Bank` | | $45,800 | Capitalize | LLC bank pays seller |
| **TOTALS** | **$45,800** | **$45,800** | | Balanced ✓ |

> Depreciation for the RV: Year 1 MACRS = $45,000 × 20% = $9,000 (insurance $800 already expensed; not included in depreciable basis). Recorded on Form 4562.
