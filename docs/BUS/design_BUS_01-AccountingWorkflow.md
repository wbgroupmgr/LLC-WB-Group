# LLC Accounting Workflow: Transactions to Books to Tax

## Accounting Guidelines:
1. ✅ The recommended workflow is to use a Trial Balance to bridge General Ledger totals directly into categorized financial statements before mapping to the specific line items of Form 1065.

## 🏛️ Levels of Accounting Tasks

1. **Transactional**
- This is the day to day running of the LLC business.
- All financial transactions should go thru the bank, except
    - llcAssets : purchase/sale  of properties
    - llcPayable : AP accounts payable - not done thru the bank
    - llcReceivable : AR account receivables - not done thru the bank
- Phase Beginning, Phase End
    - This `Transactional` accounting phase is defined by the specific busines operatitations.
    - For a Property Rental LLC business the `Transactional` phase cycle on 2 levels:
    - Monthly Rent Phase - rent payment
    - IRS Tax Fiscal Year (1st - last transaction within the IRS fiscal period).
2. **Book**
- This is the `bookkeeping` foundational level focused on recording all transactions
- Ensure the transactional objects are correct.
- Tasks: Data entry, invoicing, bank reconciliation, and payroll.
- Goal: To ensure every dollar is tracked and the General Ledger is accurate and current. 
- Phase Beginning, Phase End
    - This `Book` accounting phase is linked to
    - A. periodic Reconcilation per each Bank Statements
    - B. the period end is defined at the time of `closed book` (usally aligned with IRS fiscal period)
3. **Analytical** (Accounting)
- This level focuses on interpreting the data produced by the transactional level. 
- Tasks: Preparing financial statements
    - Income Statement
    - Balance Sheet
    - Advanced: identifying trends, and ensuring regulatory compliance.
- Goal: To explain what the data means for the business's current performance. 
- Phase Beginning, Phase End
    - This `Analytical` accounting phase is linked typically tied to the end of the fiscal period. 
    - A. The key import is closed books (see prior phase). periodic Reconcilation with Bank Statements
    - B.IRS fiscal periods. 
4. **Tax Prepariness** (Tax activities)
- manage mappnig book data (GL) to tax forms
- reconciling Tax Forms with Financial Books
- Preparing Financial Reports and Letters to aid downstream consumers (IRS, auditors)
- Phase Beginning, Phase End
    - This `Tax` accounting phase is linked to the end of the IRS fiscal period. 
    - A. The key import is closed books at the end of the IRS Fiscal Period).
5. **Strategic** (Controller/CFO)
- The highest level involves oversight and planning. 
- Tasks: Long-term financial forecasting, tax strategy, and risk assessment.
- Goal: To guide the company's future growth and ensure sound financial health. 
- Phase Beginning, Phase End
    - This `Strategic` accounting phase is linked to the closing of the books.
    - A. The key import is closed books at the end of the IRS Fiscal Period).
6. **Verification** (Auditing)
- Auditing is a separate, independent process that verifies the work of the other levels. 
- Tasks: Examining records and internal controls to provide an unbiased opinion on financial accuracy.
- Goal: To add credibility to the financial statements for external parties
- Phase Beginning, Phase End
    - This `Strategic` accounting phase is linked to the closing of the books.
    - A. The key import is closed books at the end of the IRS Fiscal Period).

## LLC Accounting App - Understand the Services

- The LLC Accounting Editor App is divided into a set of services - refer to doc/`LLC Accounting Editor - Model Design`.
- Understand the UAS accounting naming convention.

## Monthly Reconcilation Workflow

#### 1. General Ledger & COA
- Injest and Record all daily transactions
    - majory of monthly transaction go thru the Bank stmts; monthly reconcilation of bank stmt into llcExpRev
    - record property purchases/member investment/disbursemtns transactions go into the llcAssets DB
    - record AP transaction (not journaled in the bank) into the llcPayable DB
    - record AR transactions (not journaled in the bank) into the llcReceivables DB
    - Reconcile `new` llcBanks transactions withing the llcExpRev DB
    - Generate stmtGeneralLedger report (immutable during the eSession)
- Ensure every entry is tagged with a standard **Chart of Accounts** account name.
- Categorization & Aggregation: Ensure every transaction in the General Ledger maps to a Chart of Accounts (COA) account (acct/Ledger account names should match names in llcCOA services).

#### 2. Generate Trial Balance 
- Sum GL balances by account to create a Trial Balance
- The General Ledger view should have 2 frames:
    1. **Trial Balance** : aggrated view of all transactions by [acctType / acct / aType (Debit/Credi) / amt / Desc]
    2. **Details** : per Transaction Frame

#### 2. Financials Statements Views
- **Income Statement**:
    - Filter GL for Revenue (4xxx) and Expenses (5xxx-6xxx).
    - Aggregate Revenue and Expense accounts to calculate "Net Income per Books".
- **Balance Sheet**:
    - Filter GL for `Assets` (1xxx), `Liabilities` (2xxx), and `Equity` (3xxx).
    - Aggregate Asset, Liability, and Equity accounts for beginning and end-of-year positions.
- **Owner Equity**:
    - currently based on llcOwners + llcAssets
    - FIXME : future base on GL
- **Property Equity**:
    - currently based on llcCustomers + llcExpRev
    - FIXME : future based on GL, today leave asis

#### 3. Build simple stmts:form mapping 
- generate IRS Form using a basic to_IRS mapping table per IRS Form.
- Provide a Edit button on each field item mapping to allow human customization on small set. 
- refer to Form1065 Mapping Table as an example
    - **Page 1 (Ordinary Income)**: Report active trade/business income and expenses.
    - **Schedule K (Distributive Share)**: Include "separately stated items" like interest and dividends that pass through directly to partners.
    - **Schedule L (Balance Sheet)**: Mirror the company's financial balance sheet.
    - **Schedule M-1**: Reconcile the difference between financial "book" income and "taxable" income.

#### 4. Trial Balance Review


#### 5. Generate FILL.pdf 

- Generate basic

#### 


#### 5. Final Review
- Ensure **Schedule L, Line 21** (Ending Capital) matches the sum of all **Schedule K-1, Item L** ending balances.


## IRS Form Mapping

#### Form 1065 (Pg 1-6)

This table provides a standard mapping from accounting objects to the main sections of IRS Form 1065.
- FIXME: change COA Standard Account Name into acct naming convention in llcCOA.
    - eg. 'Rental Income' -> 'Acct.Rev.*'
 
| Form 1065 Field 	| Source Object	| COA Standard Account Name	| Description |
| ---- | ---- | ---- | ---- | 
| Page 1, Line 1a	| IncStmt	| Sales / Gross Receipts	Total revenue from trade or business.| 
| Page 1, Line 2	| IncStmt	| Cost of Goods Sold (COGS)	Direct costs linked to production.| 
| Page 1, Line 10	| IncStmt	| Guaranteed Payments	Payments to partners for services/capital.| 
| Page 1, Line 12	| IncStmt	| Rent Expense	Business rent paid for property/equipment.| 
| Page 1, Line 16	| IncStmt	| Depreciation	Non-cash expense (Tax Basis vs Book).| 
| Sch K, Line 1	| IncStmt	| Rental Income	| Sum of Page 1 income and deductions.| 
| Sch K, Line 5	| IncStmt	| Interest Income	| Portfolio income (Separately Stated).| 
| Sch L, Line 1	| BalSh	| Cash	| Total liquid assets at year-end.| 
| Sch L, Line 2	| BalSh	| Accounts Receivable	| Amounts owed by customers.| 
| Sch L, Line 16	| BalSh	Accounts Payable	| Short-term obligations to vendors.| 
| Sch L, Line 21	| BalSh	| Partners' Capital Accounts	| Total equity of all partners.| 
| Sch M-1, Line 1	| IncStmt	| Net Income (Loss) per Books	| Final net income from the Income Statement.| 



