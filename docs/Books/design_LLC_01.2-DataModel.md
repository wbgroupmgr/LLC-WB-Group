# LLC Data Model

## FIXES/Enhancement

Enhance LLC App with the following changes

## Overview

The current design is very complicated and complex.   The whole LLC data model is not clear.  Please refractor the code to adhere to the following data model. 


## Lessons Learned — Session 2026-06-02

### Accounting
- **`acctOwner` field on equity records**: Multi-member LLC equity records use `acctOwner=oID` (owner identifier) on `Acct.Equity.Owner.Capital.*` entries to distinguish per-member capital without adding new COA accounts. The same COA path applies to all members; `acctOwner` is the discriminator for K-1 Item L aggregation.
- **YE closing entries require `Ledger` field set**: If `Ledger=nan` (or blank) on a closing entry, `toDoubleEntry()` skips it and no counter-entry is generated. The GL equation then breaks because only one side of the close posts. Both the Dr and Cr sides of every YE closing journal must have `Ledger` populated.

### Software Engineering
- **Single shared DB (Phase 3)**: `Accts/` is now a single DB across all fiscal years — no per-year subdirectory. Year isolation is achieved by date-prefix filtering at load time in `llcReportEngine` and `utilWorkingDB`. This simplifies COA and profile management (one file, never copied) while keeping year-specific artifacts (IRS Forms/, BankStmts/) in `<year>/` folders.
- **`acctMinor` column in ViewBy=All Balance Sheet**: The BS view surfaces `acctMinor` as a column when `view_by='All'` to show per-owner equity splits. This column is derived at aggregation time from `acctOwner` on the GL records — it does not require a separate COA entry.
- **Schema evolution — add fields without migration**: Adding `acctOwner` to COA and transaction records is backward-compatible if all code paths treat missing/null `acctOwner` as "entity-level" (no per-member split). No DB migration script is needed.

---

1. **Financial DB Data Objects** : DB/json File
    - these are all in the ledger folder as *.py
    - most of these are built on a `dual-account` transaction model.   For any given transaction, there is Credit Account and a Debit Account.
    - with ledgerObject and ledgerDB being the core classses of all DB objects. 
    - llcAsset
    - llcExpRev
    - llcBank
    - llcPayable
    - llcReceivable
1. **Constructed Financial Data Objects** : Financial Statements/tables constructed from the DB Financial Data,
    - these are usually the "Financial Statement" views.
        "NOTE: GeneralLedger should be listed under the financial statements Home page
    - all of core data management/services **should** be included in the ledger folder, but are not - need fixing.
    - Constructed data object are immutable once instanciated, ie. after construction there is no way to change them.
    - Generally, these are transaction records with a single account per tranaction record - that drive pivot/groupby data tables (statements).
    - These are load() only.
    - The (*) belows reflects that these data objects have been entangle with the View Objects
    - these include the following.  
    - ledgerGeneral
    - stmtBalanceSheet*
    - stmtIncomeStmt*
    - stmtOwnerEquity*
    - stmtPropertyEquity*
    - llcFinancialReports
1. **View Services** : LLC Editor api services to drive the User Interface.
    - refer to the HOME page for all the possible views as of now.
    - These modules are tied to API's and should use the underlying Data Objects for data flow
        - load
        - save
        - to_DF
    - There should NOT be any construction of financial data objects within the View services,
    - all data object construction, wrangling and access should be done within a respective ledger/*.py module. 
    - The utilEditSession is special case for managing "work data objects" vs "master data object".  Refer to util services. 
    - FIXME Needed - the whole uillc needs to be refractored to seperate all data mgmt/wrangle into the respective ledger/llc<object>
1. **IRS Forms Services** : These are for formating final IRS Tax forms needed to feed IRS, owners, and customers.
    - Form 1065. (SchB, SchK, SchM1, SchM2)
    - Sch_K1
    - Form 4562
    - PDF letters (future)
1. **Utilities services** : these are special services for managing LLC environment
    - the utilEditSession allows views to work on Work data objects and to Refresh/Publish data between Work <-> Masterure 
    - Future accounting practice aids, e.g. reconcilation, checks/asserts/balancing accounts.
1. **Notebooks** : these are jupyter notebooks that are used for initial prototypes of data wrangling.
    - also used to do major changes to N records across a pattern.
  


