# LLC App-Accounting - Model Design

## Design Principles / Guidelines

#### 1. Core Philosophy
- ensure the app follows a **Separation of Concerns (SoC)** model, isolating financial calculation (ledger) from presentation (UI) and compliance (IRS).
- understand basic accounting lingo : `Book activities`, `Tax Activitiess` and `Book-to-Tax Reconcilation`


#### 2. "Tax Bridge" Pattern / Decoupled Book::IRS Logic
- Establish `Uniform Account Namespace` (UAS)
    - Ever account has a multi-node form: "Acct.<acctType>.node1.node2 ... nodeN"
    - where node1 is based on set of COA names per major account types (1000, 2000, etc.)
    - The noode2 thru nodeN are LLC specific - but all UAS names (node0-Node4) must be registered in the llcCOA module. 
- Maintain Seperation of Service boundaries
    - Keep the Transaction (ledger.llc*) bookkeeping services seperate from Book Accounting
    - Keep the Book (ledger.stmt* servies) accounting separate from others
    - Keep the Tax (irs service) accounting 
- The src.irs service should use a "Bridge Table" to adjust Book Net Income to Taxable Income (e.g., adding back 50% of non-deductible meals).
- Minimize annual hardcoding PDF coordinates in your main logic.
- Use a Mapping Schema (JSON) that links COA account totals to PDF field names/coordinates. This makes it easy to update for the 2026 tax year.
- **Decoupling and Scalability**:
    - Adhere to a model of consumer <- provider decoupling.
    - Consumers are UI services and IRS form services and are different.
        - in case of viewing PDF forms, the UI is the consumer of IRS services. 
    - It is best to use a separate `bridge function`
        - irs.fromBook class services
        - ui.fromIRS class services
           prevents an N x M complexity explosion
    - **Book (Data) Services**  focus only on retrieving and validating raw data
    - **IRS (form) Services** focus only on pdf field Namespace and rendering
    - **UI (views) Services** focus on the UI visual layout of data (not constructing/wrangling data).
    - **Bridge Service** - the BookToIRS() function acts as the glue, holding the "knowledge" of how to translate one to the other
- **Maintenance Efficiency**
    - If a data/UAS field name changes in the Book databases, you only update the Book (llc/stmt) module.
    - If an IRS Form namespace changes (e.g., a field moves from Page 1 to Page 2), the Book Services remains untouched.
    - If the UI (stats/tables) visuals/layout changes, the Book Services remain untouched. 
    - This "separation of concerns" ensures that changes in one domain don't break the other.
- **Avoiding "God Objects"Options** - encapsulating a bridge function within a provider/consumer.
    -  Keeping the bridge logic & responsibilities separate allows you to use a Factory Pattern within the bridge module.
    -  BookToIRS should be dynamically configured to spin N x M up specific mappers, as needed.


----------------
#### 3. Key Components
- **Persistence**: Flat-file JSON databases in `/Accts/` for portability and version control.
- **Stateless Logic**: `/Notebooks.ledger/` computes totals on-the-fly to ensure the UI always reflects the current data state.
- **Compliance Layer**: `/Notebooks.irs/` maps standard accounting objects to IRS-specific schema.

#### 4. Validation Protocol
Before finalizing a tax year, the `test/` suite must verify:
1. **The Zero-Sum Rule**: Total Debits == Total Credits.
2. **Equity Linkage**: Net Income from IncStmt matches the change in Retained Earnings on the BalSh.
3. **K-1 Consistency**: Total Partner Capital matches Schedule L, Line 21.

#### 5. Session Management
- Use top/Notebooks.util/eSession to store Uncommitted Transactions.
- Users should "Post" a batch of changes, moving them from eSession to the Accts/ persistent store only after validation passes.

## 🛠️ Data Flow & Workflow

- **Data Integrity & Immutability**
    - **Append-Only Ledger**: Never delete a record in the Accts/ JSON. Use offsetting "Reversal" entries to correct errors.
    - **Checksums**: Store a hash of the Accts/ files after every session to detect manual tampering outside the app.
- **Transaction Ingestion**:
    - Bank Reconcilation triggers a fetch of BankStmts/ CSVs; merge new transactions into working sandbox.
    - Edit new transactions feed master DB (non bank Stmt) 
- **Normalization**:
    - Transactions account fields (acct and/or Ledger) are mapped to COA.json IDs and stored in llcAssets or llcExpRev.
- **Synthesis**:
    - ledger services calculate the Income Statement and Balance Sheet.
- **Tax Mapping**:
    - irs/ services pull these totals into a Form_FILL.pdf.
- **Validation**:
    - test/ suite runs "Accounting Equality" checks (Assets = Liabilities + Equity).

## LLC Structures

#### Project Director Structure

````
llcTop/
├── llcProfile_<LLC_Name>.json # per LLC profile information

top/pages/AcountingData/
├── Notebooks/               #---- Core Logic & Utility Controllers
│   ├── llcEditCmd.py        # Start LLC editor command
│   ├── ledger/              # Headless Financial Services (DB/Stmt Logic)
│   ├── irs/                 # Tax Form Mapping & PDF Generation; to_IRS 
│   ├── ui/                  # Web Interface & JS logic - no financial data construction (see ledger)
│   ├── util/                # Session & Temp Data Management
│   ├── test/                # Validation Suite
│   └── docs/                # Financial data Reports, modeling and aids
├── Accts/                   #---- Persistent JSON Databases (The "Books")
│   ├── COA.json             # Master Chart of Accounts
│   ├── llcExpRev.json       # Master Expense/Revenues ledger DB; new tranasctions from BankStmt, Dual Accounts Format
│   ├── llcAssets.json       # Master Assets ledger DB (not in BankStmt, Dual Accounts Format
│   ├── llcReveivable.json   # Master AR ledger DB (not in BankStmt), Dual Accounts Format
│   ├-─ llcPayable.json      # Master AP ledger DB (not in BankStmt), Dual Accounts Format
│   ├-─ llcOwners.json       # Master Owners DB. (no transactions)
│   ├-─ llcCustomers.json    # Master Customer DB (no transactions)
├-─2025/                     #--- Fiscal Year Workspace
    ├── BankStmts/           # Most recent/monthly/annual bank CSV Data
    ├── YE_Tax_Records/      # YTD or YE, Working & Final PDF Artifacts
          └── Forms_IRS      # IRS downloaded PDF Artifacts
````

#### Ledger: Financial Data Management 

1. Core class code

- transactional data objects. (raw transactionsal data :
    - transaction ID - unique ID for all transactions:   <date>_<amt>
    - dual account transaction records (llc* data objects)
        - acct : COA Account name
        - Ledger : COA Account name
        - aType : Debit or Credit
        - "journal an aType transaction against `acct` account and the opposite against the `Ledger` account"
    - single per-account transaction record. (GL) 
- constructed stmt data objects
    - (tables of aggregated accounts

````
- ledger/__init__.py
- ledger/ledgerObject.py   : transaction records base
- ledger/ledgerDB.py.      : transaction records DB services
- ledger/stmtDB.py.        : constructed table data services
- ledger/stmtEquity.py     : special constructed tables
````

2. Main LLC Management Class
````
- ledger/LLC.py            : Head of LLC financial accounting
- ledger/setup_paths.py    : paths  of LLC data folders
- ledger/llcAPI.py         : list of API's
- ledger/llcCOA.py         : transactons :
- ledger/llcOwners.py      : Owners information
- ledger/llcCustomers.py   : Customer information
`
````

3. Bank Reconcilation Services
````
- ledger/ledgerClassify.py : mapping bank desc to COA, repeating patterns
- ledger/llcBank.py        : bank injestion (CSV) -> new transactions
````

4. Financial Data - DB Transaction data services (non-bank stmt)

- The "Source of Truth." It aggregates JSON data from Accts/ to generate the Trial Balance. It must remain stateless and UI-independent.

````
- ledger/llcAssets.py      : transactons : Assets, Liability, Equity 
- ledger/llcExpRev.py      : transactons : Expense/Revenue
- ledger/llcReceivables.py : transactons : AR
- ledger/llcPayables.py    : transactons : AP
````

5. Financial Statement - constructed financial statements (tables)

````
- ledger/stmtFinancialReport.py : container of all Statement objects
- ledger/smtGeneralLedger.py    
- ledger/stmtBalanceSheet.py
- ledger/stmtIncomeStmt.py
- ledger/stmtOwnerEquity.py
- ledger/stmtPropertyEquity.py
- ledger/stmtCashFlowStmt.py

````

#### IRS Services 

- Acts as the translation layer. It transforms financial statement objects into the specific coordinate-based fields required by IRS PDFs.

````
- irs/Readme.md
- irs/to_IRS_Cmd.py
- irs/irsForm.py
````

````
- irs/Form1065.py
- irs/Sch_K1.py
- irs/Form4562.py
````

````
- irs/formWorksheetCmd.py
- irs/pdfFill.py
- irs/pdfMap.py
- irs/pdf.py
- irs/F1065_FillPage1.py
- irs/publishMap.py
- irs/irsFormFieldNames.py
````

#### Util Services

- eSession: Manages "Working" data.
- Users can modify transactions in a `working` sandbox before committing
- Commit to  the `master DB` (persistent Accts/ JSON files).

````
util/utilEditorLLC-UserGuide.md
util/utilWorkingDB.py
util/utilEditSession.py
````


