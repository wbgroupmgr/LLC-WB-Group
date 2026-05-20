# Closing Aid Services Design 

Module Owner: Business Accountant & app developer
Status: Draft
Target System: llcRentalTracker 

------------------------------
## 1. Executive Summary & Core Objective

The `ClosingAid` service is an automated accounting bridge designed to streamline the onboarding of newly acquired rental properties. The service ingests unstructured real estate closing documents (ALTA, HUD-1, or settlement statement table images/PDFs), extracts the line items using Optical Character Recognition (OCR), and maps them into a balanced, structured Draft Manual Journal Entry.

Furthermore, the system isolates capitalized acquisition costs to
- calculate the property's Adjusted Cost Basis,
- automatically calculates the depreciable Building vs. Land Split,
- accurately attributes both cash-to-close requirements and
- external member-paid escrow deposits to individual partner capital accounts within a Multi-Member LLC structure.

------------------------------
## 2. Document Ingestion & Verification
To maintain strict internal controls, the system must enforce asset isolation before processing data.

* **Property Mapping**: The user must select or create a specific Property Rental LLC asset profile before uploading the document.
* **Document Support**: Accepts high-resolution images (PNG, JPEG) or PDFs of settlement sheets.
* **Control Totals Extraction**:
    - The service must locate and log the final cash reconciliation line item (e.g., "Net To Seller" or "Cash From Buyer") to use as the mathematical anchor for ledger balancing.

------------------------------
## 3. Extraction, Mapping, & Basis Engine
The system processes the text via a specialized financial OCR engine and applies a standardized, multi-tiered accounting logic rule set.

## 3.1 Line-by-Line Tax Classification Rules
Every settlement line item must be categorized into one of three regulatory tax buckets:

   1. **Capitalized Acquisition Costs**
        - Adds to Basis
        - Purchase price, title insurance, legal fees, recording fees, and transfer taxes. These costs directly increase the property's asset valuation.
   3. **Loan Costs**
        - Amortizable Liabilities:
        - Loan origination fees, points, and appraisal fees. These do not add to property basis; they are placed in a contra-liability or asset account to be amortized over the life of the loan.
   4. **Current Expenses**
       - Deductible Immediate
       - Prorated property taxes, prepaid interest, and homeowner association (HOA) dues or transfer fees. These bypass the balance sheet and hit the Profit & Loss statement immediately.

------------------------------
## 4. Multi-Member LLC Equity Tracking & Out-of-Pocket Escrow Module
To properly account for transactions within a Multi-Member LLC, the system must trace the capital origins of all funding mechanisms. This includes scenarios where an individual partner pays the initial Earnest Money Deposit/Escrow out of personal funds outside the LLC bank account.

## Equity Structuring & Escrow Treatment Rules

* Member Isolation: The UI must fetch the current roster of LLC Members from the company profile.
* Sub-Account Routing: All funds brought to the table—whether through LLC banking channels or personal partner accounts—must route directly to individual Equity: Member Capital Contribution sub-ledgers.
* Out-of-Pocket Escrow Attribution: If a member pays the escrow deposit personally, that deposit is recognized on the statement as a credit toward the purchase, but must be booked in the ledger as an equity contribution from that specific member. The asset (the escrow credit) is effectively transferred into the LLC books at the moment of closing.
* Contribution Splitting: The system allows the user to allocate both the initial Escrow Deposit and the final Cash-to-Close to specific members via an absolute dollar amount or percentage split, ensuring total funding matches the settlement requirements.

------------------------------
## 5. User Interface UI Layout (The ClosingAid Screen)

````

[ SOURCE IMAGE RECONCILIATION: settlement.png ]
--------------------------------------------------------------------------------------------------
Line Item Description          | Amount    | Dr/Cr  | Suggested GL Account         | Tax Treatment
--------------------------------------------------------------------------------------------------
101. Contract Sales Price      | $300,000  | Debit  | 1200 - Property Basis        | Capitalize
103. Settlement Charges (Title)| $1,500    | Debit  | 1200 - Property Basis        | Capitalize
201. Earnest Money / Escrow    | $10,000   | Credit | [Map Personal Equity ↓]      | Escrow Credit
801. Loan Origination Fee      | $2,000    | Debit  | 1400 - Amortizable Loan Fees | Amortize
905. HOA Transfer Fee          | $200      | Debit  | 6300 - HOA Expense           | Expense
211. Tax Prorations (Seller Cr)| $450      | Credit | 6200 - Tax Expense           | Expense
[+] Add / Split Line Item Row
--------------------------------------------------------------------------------------------------
CASH RECONCILIATION TOTAL:     | $83,250   | Credit | [Calculate Partner Equity ↓] | Cash-to-Close
--------------------------------------------------------------------------------------------------
CONTROL TOTAL RECONCILIATION:  Total Debits: $303,700  |  Total Credits: $303,700  |  [ BALANCED ]

==================================================================================================
[ MULTI-MEMBER LLC CAPITAL CONTRIBUTIONS ]
==================================================================================================
Escrow Deposit Funding ($10,000 Total Credit):
  - [X] Funded Out-of-Pocket (Bypassed LLC Bank Account)
  - Paid By: Member A (Jane Doe)         [ 100.00 % ] --> $10,000 (Route to: 3101 - Cap. Contrib: Jane)

Final Cash-To-Close Funding ($73,250 Total Due):
  - Funded By: Member A (Jane Doe)       [ 54.38 % ]  --> $39,830 (Route to: 3101 - Cap. Contrib: Jane)
  - Funded By: Member B (John Smith)     [ 45.62 % ]  --> $33,420 (Route to: 3102 - Cap. Contrib: John)
  
Aggregate Deal Contribution Summary:
  * Total Capital Contributed Jane Doe:   $49,830 (59.86% of Net Cash Injected)
  * Total Capital Contributed John Smith: $33,420 (40.14% of Net Cash Injected)

  [X] Auto-verify matches funding requirements  |  [STATUS: EQUITY MATCHED]
================================================================================================--

==================================================================================================
[ PROPERTY BASIS, LAND SPLIT & DEPRECIATION ENGINE ]
==================================================================================================
Gross Capitalized Acquisition Cost (Calculated Basis): $301,500

Tax Assessor Valuation Ratio Input:
  - Assessor Land Value:        $60,000  (20.00%)
  - Assessor Improvement Value: $240,000 (80.00%)

Final Asset Account Allocation:
  -> [ GL Account 1201 - Land Basis ]     ====================================> $60,300
  -> [ GL Account 1202 - Building Basis ] ====================================> $241,200

*Estimated Annual IRS Depreciation (27.5-year Residential Alternative): $8,771 / Year
==================================================================================================

[ BUTTON: GENERATE DRAFT MANUAL JOURNAL ]

````

## UI Interaction Rules

* Confidence Scoring: Highlight any OCR text or suggested mapping with an accuracy score under 95% in orange/red for human review.
* Split-Row Functionality: Allow users to split a single line item into two separate lines to handle mixed-use escrow fees.
* Allocation Validation: The Land % and Building % fields must dynamically update to always equal exactly 100.00% before exporting.
* Equity Validation: The combined inputs for out-of-pocket escrow and cash-to-close must reconcile completely with the total non-debt credits on the settlement sheet. The journal entry will block export unless the total member equity assigned perfectly accounts for both the personal escrow payment and any funds cleared through LLC cash accounts.

------------------------------
## 6. Ledger Integration & Compound Journal Entry Output
The system must never post directly to the general ledger. It exports a pending compound entry into the llcAssets ledger (ie. manual journal) for final CPA sign-off.

## System Validation Constraints
The application will block the export unless the Golden Rule of Bookkeeping is met:
$$\sum \text{Debits} = \sum \text{Credits}$$ 

## Generated Compound Journal Entry Blueprint

| GL Account | Debit | Credit | Description / Audit Trail Note |
|---|---|---|---|
| 1201 - Land Basis                  | $60,300  |          | Allocated cost of non-depreciable land |
| 1202 - Building Basis              | $241,200 |          | Allocated cost of depreciable building structure |
| 1400 - Amortizable Loan Fees       | $2,000   |.         | Financing fees to be amortized over loan term |
| 6300 - HOA Expense                 | $200     |          | HOA fee paid at settlement (Immediate Expense) |
| 6200 - Property Tax Expense        |          | $450     | Seller credit offset for prorated property taxes |
| 2100 - Mortgage Payable            |.         | $220,000 | Principal loan liability from lender |
| 3101 - Equity: Cap. Contrib (Jane) |          | $49,830  | Jane Doe equity ($10k escrow + $39.83k cash-to-close) |
| 3102 - Equity: Cap. Contrib (John) |          | $33,420  | John Smith cash-to-close funding contribution |
| TOTALS                             | $303,700 | $303,700 | [System Status: Validated & Balanced] |

## Audit Trail Compliance
The finalized manual journal entry must automatically bind the original settlement statement image or PDF file to the ledger transaction as permanent, un-editable source documentation for future IRS audits.

