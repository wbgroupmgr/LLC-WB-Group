# NewPropertyAgent — Business Accounting Design

Module Owner: Business Accountant  
Status: Production (v0.3)  
System: llcRentalTracker / W&B Group, LLC  
Related Issue: [#6 LLC Property List Mgmt](https://github.com/wbgroupmgr/llcRentalTracker/issues/6)

---

## 1. Executive Summary

The **NewPropertyAgent** (formerly ClosingAid) is the accounting skill embedded in the llcRentalTracker app that onboards a newly acquired rental property from a settlement statement directly into the LLC's asset ledger. It replaces manual data entry with a structured, IRS-compliant workflow that:

- Classifies every settlement line item into the correct tax bucket (Capitalize / Amortize / Expense)
- Constructs a balanced compound journal entry for the llcAssets ledger
- Computes the property's adjusted cost basis per IRS Pub 551
- Splits the total basis into depreciable Building and non-depreciable Land components
- Attributes member capital contributions (including out-of-pocket escrow) to individual equity sub-accounts
- Writes `manualJournal` entries to `llcAssets_WBGroupLLC.json` and (Phase 1, Issue #6) registers the property in `assetList`

**Fundamental accounting principle**: Each settlement line item is posted as a one-sided GL entry (`Ledger = 'nan'`). The collection of all rows forms a balanced compound journal entry (ΣDebits = ΣCredits). No individual row carries a dual account.

---

## 2. Acceptable Document Formats

The agent accepts real estate settlement statements in two layouts:

| Format | Columns | Notes |
|---|---|---|
| Standard | `Description`, `Debit`, `Credit` | HUD-1 style |
| ALTA Buyer/Seller | `Description`, `Buyer`, `Seller` | Buyer = charges to buyer (Debit in LLC books); Seller = credits to buyer (Credit in LLC books) |

Input is pasted as CSV or tab-delimited text into the Step 1 dialog. Null/zero rows and the "Totals" summary row are automatically dropped.

**Control total**: The final cash reconciliation line (e.g. "Cash From Buyer" or "Balance Due") serves as the mathematical anchor for confirming the compound entry is balanced.

---

## 3. IRS Tax Classification — Three-Bucket System

Every line item is assigned to exactly one of three tax buckets per IRS Publication 551 (Basis of Assets) and the Internal Revenue Code.

### 3.1 Capitalize — Adds to Property Basis

These costs are added to the property's adjusted cost basis and recovered through depreciation over the asset's useful life. They do **not** hit the income statement in the year of closing.

**Authority**: IRS Pub 551, §Real Property — "The basis of property you buy is generally its cost."

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

> Note: Property tax prorations credited by the seller reduce the buyer's net cost and are therefore included in basis per IRS Pub 551.

### 3.2 Amortize — Loan Acquisition Costs

Loan origination costs are not added to property basis. Under IRC §163 and IRS Pub 535 they are capitalized to a contra-liability account and amortized (straight-line) over the life of the loan.

| Line Item Type | Example | GL Account |
|---|---|---|
| Loan principal | `New Loan Amount`, `Principal Amount` | `Acct.Liab.Morgage` (Credit) |
| Origination fee / points | `Loan Origination Fee`, `Loan Points` | `Acct.Liab.Morgage` |
| Appraisal fee | `Appraisal Fee` | `Acct.Liab.Morgage` |

### 3.3 Expense — Immediate Deductible

These items bypass the balance sheet and are deducted in the current tax year as operating expenses on Schedule E (IRC §162).

| Line Item Type | Example | GL Account |
|---|---|---|
| HOA dues / transfer fees | `HOA Transfer Fees`, `Homeowners Association Dues` | `Acct.Exp.Operating` |
| Home warranty | `Home Warranty` | `Acct.Exp.Operating` |
| Inspection fee | `Inspection` | `Acct.Exp.Operating` |
| Wire fee | `Wire Fee` | `Acct.Exp.Operating` |

---

## 4. Property Basis Calculation

### 4.1 Gross Adjusted Cost Basis

Gross Basis = sum of all **Capitalize + Debit** rows after classification.

```
Gross Basis = Sale Price + Title/Closing Fees + Recording Fees + Transfer Tax + Survey + ...
```

Credits within the Capitalize bucket (seller tax proration, earnest money applied) are NOT subtracted from basis — they represent separate funding flows (equity contributions, bank draws), not basis reductions.

### 4.2 Land / Building Split

IRS regulations require separating land (non-depreciable) from improvements (depreciable) for residential rental property. The split is determined by the **current-year tax assessor's ratio**:

```
Land Basis    = Gross Basis × (Assessor Land Value / Total Assessed Value)
Building Basis = Gross Basis × (Assessor Improvement Value / Total Assessed Value)
```

The assessor ratio (`landPct`) is entered in the Step 0 Preface form. When `landPct > 0`, the agent consolidates all Capitalize-Debit-InService rows into two asset records:

- `Acct.Fixed.Land` — non-depreciable
- `Acct.Fixed.Tangible.InService` — depreciable building basis

**Example (805 High Mesa, Wimberley TX):**
- Gross Basis: $303,700
- Assessor Land %: 20% → Land Basis: $60,740
- Assessor Improvement %: 80% → Building Basis: $242,960

### 4.3 Annual Depreciation (Reference)

Residential rental property is depreciated straight-line over **27.5 years** (IRC §168(c)).

```
Annual Depreciation = Building Basis / 27.5
```

For the above example: $242,960 / 27.5 = **$8,835 / year**.

This figure feeds the `Form 4562` depreciation schedule and flows to Schedule E of Form 1065.

---

## 5. Multi-Member LLC Equity Tracking

### 5.1 Funding Flows at Closing

A typical LLC property acquisition involves three funding channels:

1. **LLC bank account** — wire transfer for the balance due at closing; recorded as a draw on `Acct.Cash.Bank`
2. **Member personal escrow** — earnest money or option fees paid out-of-pocket by a specific member before the LLC bank received funds; routed to that member's `Acct.Equity.Owner.Capital.Funds` sub-account
3. **Mortgage / new loan** — principal advanced by the lender; recorded as `Acct.Liab.Morgage` (Credit)

### 5.2 Equity Attribution Rules

- **Member isolation**: The LLC profile (`llcProfile_WBGroupLLC.json`) holds the authoritative member roster with oIDs.
- **Sub-account routing**: All member funding — whether via LLC bank or personal out-of-pocket — routes to individual `Acct.Equity.Owner.Capital.Funds` sub-ledgers.
- **Out-of-pocket escrow**: When a member pays earnest/option money personally (bypassing the LLC bank account), the closing statement shows it as a Credit applied toward the purchase price. In the LLC books, this is a capital contribution from that specific member.
- **Contribution split**: The total member equity assigned (escrow + cash-to-close) must equal the total non-debt Credits on the settlement statement.

### 5.3 Capital Contribution Validation

The compound entry is considered balanced when:

```
ΣDebits = ΣCredits  (tolerance: ±$0.01)
```

The dialog blocks the Commit action until this condition is satisfied.

### 5.4 Future: Structured Ownership Entry (Issue #6)

The current implementation accepts `propOwners` as a free-text JSON string in Step 0. Per [Issue #6](https://github.com/wbgroupmgr/llcRentalTracker/issues/6) Phase 1 / Case 1, this will be replaced by a structured table that loads the LLC member roster from `/api/closing/get_owners`, presents one row per member with a `%` input, and validates that percentages sum to 100 before the dialog advances.

---

## 6. One-Sided GL Posting (Accounting Principle)

Settlement line items are posted with `Ledger = 'nan'` — a deliberate single-sided entry. The rationale:

- The settlement statement **as a whole** is the compound journal entry. ΣDebits = ΣCredits across all rows.
- Each individual row does NOT have a meaningful dual account — the "other side" is distributed across multiple equity, liability, and expense accounts within the same closing batch.
- Posting one-sided prevents phantom duplicate GL entries while preserving the full audit trail.
- This is materially equivalent to a compound journal entry in traditional double-entry bookkeeping.

The `toGL()` and `toDoubleEntry()` functions in the ledger engine skip the second side when `Ledger == 'nan'`, preserving correct GL totals.

---

## 7. Audit Trail & Internal Controls

- Every committed record carries `refDoc = f"{propNm}, Closing Docs, {tax_bucket}, {closingDoc}"` — embedding the tax bucket classification and source document name in the audit trail.
- `refDB = 'closingAid'` and `tDB = 'llcAssets'` identify the origin of every record.
- The system must not post directly to the general ledger; all entries are written to the `llcAssets` manual journal pending CPA review.
- The original settlement statement PDF should be stored alongside the closing records in the business repo (`LLC-WBGroup/books/YYYY/`) for IRS audit purposes.

---

## 8. Property Registry (Issue #6)

The NewPropertyAgent is also the **primary entry point for registering a new property** in the `assetList` registry (Phase 1 of [Issue #6](https://github.com/wbgroupmgr/llcRentalTracker/issues/6)). On commit, `toAssetRecords()` will additionally call `save_asset_list()` to write a property metadata entry:

```json
{
  "propNm":      "H_805HighMesa",
  "propAddr":    "805 High Mesa Dr, Wimberley TX",
  "assetType":   "Residential",
  "assetState":  "InService",
  "closingDate": "2025.08.26",
  "tID_Prefix":  "p20250826-Mesa",
  "closingDoc":  "ALTA_2025.pdf",
  "landPct":     20.0,
  "bldgPct":     80.0,
  "grossBasis":  303700.0,
  "landBasis":   60740.0,
  "bldgBasis":   242960.0,
  "propOwners":  { "o20250801_1": 50, "o20250801_2": 50 }
}
```

Until Issue #6 is implemented, `propOwners` is stored as a string and the `assetList` registry does not yet exist.

---

## 9. Compound Journal Entry — Example Output

From the 805 High Mesa closing (Wimberley TX, 2025-08-26):

| GL Account | Debit | Credit | Tax Bucket | Notes |
|---|---|---|---|---|
| `Acct.Fixed.Land` | $60,740 | | Capitalize | 20% land split of $303,700 basis |
| `Acct.Fixed.Tangible.InService` | $242,960 | | Capitalize | 80% building split |
| `Acct.Exp.Operating` | $135 | | Expense | HOA dues + HOA transfer fee |
| `Acct.Equity.Owner.Capital.Funds` | | $5,300 | Capitalize | Member escrow (option + earnest, out-of-pocket) |
| `Acct.Cash.Bank` | | $1,661 | Capitalize | County tax proration credit from seller |
| `Acct.Cash.Bank` | | $296,874 | Capitalize | Cash to close from LLC bank |
| **TOTALS** | **$303,835** | **$303,835** | | Balanced ✓ |
