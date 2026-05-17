# LLC Accounting SOP Documentation: 

GAAP = (Generally Accepted Accounting Principles) 

Real Estate Acquisition Workflow
- **Standard Operating Procedure (SOP) & System Requirements**  
- **Target Audience:** Audit, Accounting, Systems Engineering  
- **Tax Year Compliance:** IRS Publication 527 (Residential Rental Property), Publication 551 (Basis of Assets)

---

# A. General Accounting Guidelines

## 1. Overall Guidelines, Rules, and System Workflow Logic

When developing a system workflow for an automated LLC real estate accounting platform, the logic must enforce rigid internal controls.

### GAAP & IRS System Integrity Rules

*   **Dual-Entry Balancing:**
    - Every transaction block must maintain mathematical equilibrium where $\sum \text{Debits} = \sum \text{Credits}$.
    - The workflow engine must block any transaction entry where the variance is $\neq \$0.00$.
*   **Entity Separation:**
    - Member funding events must route through equity tracking accounts, never directly to asset accounts.
    - The cash trail must flow: *Member → LLC Operating Bank Account → Escrow Agent / Title Company*.
*   **Tax vs. Book Treatment:**
    - The software must split standard transactional payments from closing statement entries.
    - It must flag closing document entries for specialized tax classification mapping
    - rather than processing them as pure operating expenses.
*   **Audit Trail Records:**
    - Every manual or system-generated journal entry must anchor to an immutable file attachment
    - e.g., Bank Statement, Signed HUD-1 / Settlement Statement, County Tax Assessment Card).
*   
### Software Engineering System Design Tips

*   **Enforce Account Field Hardening:**
    - Never use open-ended text fields for account categorization or any fields defined as close set classification. 
    - Programmatic drop-down picklists must bind to the strict System Chart of Accounts (COA).
*   **Dynamic Ratio Modifiers:**
    - The system must accept user-defined land/building assessment ratios derived from local county appraisal districts.
    - It must automatically distribute the combined purchase price and settlement costs according to those values.
*   **Proration Logic Engines:**
    - Any pre-paid credits or accrued liabilities (such as real estate tax or HOA prorations) must be mapped to
        - liability
        - balance sheet accounts,
    - prevent artificially inflating or deflating active operating expense ledgers at the moment of closing.

---

## 2. Ledger Object Design: 

### 2.1 Overall Accounting Principles

- Double-entry bookkeeping—is a system where every single financial transaction must be recorded in at least two different accounts.
- Think of it as a system of cause and effect.
-  Money never just appears or disappears; it moves from one place to another.
-  Here is the simple breakdown of how it works:
-  1. The Core Rule: Debits must equal Credits
   2. Every time you enter a transaction, you must write down
        - at least one Debit (money going into an account) and
        - at least one Credit (money leaving an account).
   3. The total amount of Debits must exactly equal the total amount of Credits.
   4. If they do not match, your books are out of balance, and you know an error was made.-

### 2.2 Ledger Objects

Within the LLC App there are 2 types of ledger objects:

1. **dual-account objects**:
    - These are typically `ledger.llcObject.py`
    - For a single transaction 2 accounts are entered: `acct` and `Ledger`, with the `amt` being either a debit or credit against the `acct` and the opposit against the `Ledger` account.
    - This ensure all transactions adhere to the dual-entry rule.
    - The `llcExpRev` ledger object is created automatically from a given `BankStmt` (csv) statement.
        - the import pipeline will classify each transaction into `acct`
        - The bookkeeper operator will review and correct as needed and assign the `Ledger` account to enter against.
    - The `llcAssets`, `llcCustomers`, `llcOwners` are human edited by the LLC bookkeeper/manager.
        - These reflect information and transactions (e.g. Clossing) whose details do not flow thru the bank statement.
        - 
2. **single-account objects**:
    - The GL (General Ledger) is the single focal point that merges the Books dual-account objects and creates a single-acct transaction for each the `acct` and `ledger`.
    - The `amt` is classified into the `Debit` or `Credit` fields.
    - A GL.TrialBalance is created for checking that the books (GL transactions) adhere to GAAP.

### 2.3 Auditor Service

- The `ledger.auditor.py` provides services & view dialogs to do an audit on the GL object.
- The GL View will have a button to invoke the auditor who will either:
    a. Report any discrepencies across the whole GL
    b. The operator can select the "Audit" buttton that will
        - 1. invoke the auditor to review the GL trail balance and all its transactions.
        - 2. will flag any issues needing to be addressed.
        - 3. Will perform standard accounting review practices to identitfy the root cause for the discrepency.
        - 4. Suggest corrective action to ensure books are in balance. 
    

## 9. Standardized Chart of Accounts (COA) Blueprint
System configurations must restrict transaction processing exclusively to these standard account naming structures:

The following are example standard COA.  Refer to `accts.ChartOfAccounts_WBGroupLLC` file for COA used by this LLC App. 

| Account Number | Account Name | Account Type | Financial Statement |
| :--- | :--- | :--- | :--- |
| **1100** | Cash / Operating Bank Account | Asset | Balance Sheet |
| **1410** | Land | Asset (Non-Depreciable) | Balance Sheet |
| **1420** | Building | Asset (Depreciable) | Balance Sheet |
| **1430** | Escrow / Earnest Money Deposit | Asset | Balance Sheet |
| **2150** | Accrued Property Taxes | Liability | Balance Sheet |
| **3100** | Member Equity - Primary | Equity | Balance Sheet |
| **5200** | HOA Expense | Expense | Income Statement |
---

# B. Property Acquistion / Disposition

## 1. Property Basis Computation & Technical Analysis
- Per IRS Publication 551, the basis of a real estate asset includes
    - the initial purchase price
    - plus specific fees tied to the transfer of title.

Fees associated with securing a property cannot be added to the property basis
    - a mortgage (e.g., loan origination fees, appraisal points)
    - instead, they must be amortized over the life of the loan.
      
### The Accounting Scenario Specifications

*   **Contract Purchase Price:** \$220,000.00
*   **Settlement Fee:** \$625.00 *(Capitalized per IRS rules)*
*   
*   **E-Recording Fee:** \$8.00 *(Capitalized per IRS rules)*
*   **Recording Deed Fee:** \$29.25 *(Capitalized per IRS rules)*
*   **County Assessment Split:** \$63,720.00 Land | \$112,800.00 Building *(Total: \$176,520.00)*

### Step-by-Step Computational Workflow

[Contract Purchase Price: $220,000.00] + [Capitalized Closing Fees: $662.25]
│
▼
[Total Basis: $220,662.25]
│
┌────────────────────────┴────────────────────────┐
▼ ▼
[Land Ratio: 36.10%] [Building Ratio: 63.90%]
│ │
▼ ▼
[Allocated Land: $79,654.42] [Allocated Building: $141,007.83]


#### Step 1.1: Derive Asset Ratios
$$\text{Total Assessment} = \$63,720.00 + \$112,800.00 = \$176,520.00$$
$$\text{Land Allocation Ratio} = \frac{\$63,720.00}{\$176,520.00} = 36.10\%$$
$$\text{Building Allocation Ratio} = \frac{\$112,800.00}{\$176,520.00} = 63.90\%$$

#### Step 1.2: Aggregate Capitalized Base Value
$$\text{Total Capitalized Expenses} = \$625.00 + \$8.00 + \$29.25 = \$662.25$$
$$\text{Total System Cost Basis} = \$220,000.00 + \$662.25 = \$220,662.25$$

#### Step 1.3: Calculate Allocated Account Balances
*   **Account 1410 Land Basis:** $\$220,662.25 \times 36.10\% = \mathbf{\$79,654.42}$
*   **Account 1420 Building Basis:** $\$220,662.25 \times 63.90\% = \mathbf{\$141,007.83}$

---

## 2. Double-Entry Ledger Event Postings

### Phase A: Capitalization & Escrow Funding Logs

#### Entry 1: LLC Initial Funding Injection
*   **Debit:** `1100 Cash / Operating Bank Account` — **\$219,000.00**
*   **Credit:** `3100 Member Equity - Primary` — **\$219,000.00**
*   *Auditor Note:* Verifies bank ledger receipt matches investor operating capital.

#### Entry 2: Out-of-Pocket Escrow / Earnest Funding Entry
*   **Debit:** `1430 Escrow / Earnest Money Deposit` — **\$5,300.00**
*   **Credit:** `3100 Member Equity - Primary` — **\$5,300.00**
*   *Auditor Note:* Reflects the primary investor's direct downpayment to the title company as an addition to their equity position.

---

### Phase B: Settlement Statement Execution

#### Entry 3: Compound Settlement Closing Record
This automated entry clears outstanding escrow funds, records long-term assets based on the calculated county appraisal ratios, expenses short-term HOA items, and tracks the seller's property tax credit as a liability.


| Account Number | Account Name | Debit ($) | Credit ($) |
| :--- | :--- | :--- | :--- |
| **1410** | Land | 79,654.42 | |
| **1420** | Building | 141,007.83 | |
| **5200** | HOA Expense *(Dues: \$35.34 + Cert: \$100.00 + Transfer: \$100.00)* | 235.34 | |
| **1430** | Escrow / Earnest Money Deposit | | 5,300.00 |
| **2150** | Accrued Property Taxes *(Seller Proration Credit)* | | 1,660.64 |
| **1100** | Cash / Operating Bank Account *(Net Cash Outflow to Close)* | | 213,936.95 |
| **SYSTEM TOTALS** | **Balanced Accounting Verification State** | **220,897.59** | **220,897.59** |

## Scanrio : Closin

B  | Acct.Cash.Bank                  | Debit  | <- | Acct.Equity.Owner.Capital.Funds | 219000.00 | Initial EquityInvestment | 
B  | Acct.Cash.Bank                  | Credit | -> | Acct.Fixed.Tangible.InService   | 213936.95 | Closing, Cash to TitleCo | 
1. | Acct.Fixed.Land                 | Debit  | <- | Acct.Fixed.Tangible.InService   |  79654.42 | Land Percent 36.10 HaysCo|
2. | Acct.Cash.Bank (J)              | Debit  | <- | Acct.Fixed.Tangible.InService   |    235.34 | HOA Fees |
3. | Acct.Liab.AccuredTax            | Credit | -> | Acct.Fixed.Tangible.InService   |   1660.64 | Liab Accured Tax, seller prorate 2025 |
4. | Acct.Equity.Owner.Capital.Funds | Credit | -> | Acct.Fixed.Tangible.InService   |   5300.00 | Closing, Member Equity Invmt | 
Asset Cash: 3637.75,  Fixed: 220,662.25 | Eq. Mem 219,000 | Liab: 1660.64







| Acct.Equity.Owner.Capital.Funds | 
