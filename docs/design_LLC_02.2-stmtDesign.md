# LLC Design : ledger.stmt* (constructed table object)s

The `ledger.stmt*` objects are modules that construct a tables based on input from core LLC financial transactional data - refer to the LLC_DataFlowDesign.md for the set of `stmt` objects.  The `stmt` objects can be considered a collection/aggregation of core transactional data objects.  Generally,  each `stmt` table can be represented by a dataframe (`to_DF()`)or as a list of dicts (`load()`)

The `stmtGenteralLedger` is the foundation for all other `stmt` objects with a few exceptions:
- stmtProfile.

The design for stmt objects has gone thru several iterations as there are different consumers of stmt objects, thus conflicting design goals.  The primary consumers of stmt objects are:
1. Tax Preparation
2. UI - views
3. Financial Reports

## Design Decision v0.3

- stmtProfile does not change
- Use `rpt` prefix for **REPORT** objects which are a collection of text, tables that generate PDF.

**Major changes in stmtOBJ architecture**:<br>
1. The v0.2 `stmt` incorrectly overlayed differnt consumer functionality over each other making the whole design very complex.
2. Going forward all the stmt objects will use the following class subclass hierarchy (using BalanceSheet/BS as example)
    - ledger.ledgerDB
    - ledger.stmtDB
    - ledger.stmtOBJ.py <- class stmtOBJ(stmtDB) - just returns the core data of a stmt object, no view wrangling
    - ledger.stmtOBJ.py <- class stmtOBJ_Tax(stmtOBJ)- data provisioning services for Tax Preparation [per Tax form mapping], consumed by irs/*.py
    - ledger.stmtOBJ.py <- class stmtOBJ_Agg(stmtOBJ) - intantiate aggregator
    - ledger.stmtOBJ.py <- class stmtOBJ_View(stmtOBJ_Agg) - data provisioning servies for Views [slice, aggregation, etc], consumed by ui/*.py
    - ledger.stmtOBJ.py <- class stmtOBJ_Reports(stmtOBJ) - data provisioning services for Reports [future collection services for reports],TBD
3. Guidelines/Groundrules
    - There is NO overlap of functionality, each consumer knows nothing about other consumers
    - There is no save() functionality, instead there is a to_json()
    - There is no _build() for different consumers, instead this is performed by the load()
    - Only stmtOBJ_Tax has nSpaceMap functionality
        - each OBJ refernces a human editable bkNS_OBJ.json file
        - The original bkNS_OBJ_ACCOUNTING.json is generate by an expert claude AI request independent of ALL existing code. 
    - The stmt operate based on concept of a pipeline, do not overlay downstream functionality into any single module
          - consumerData = stmtOBJ_xxx.AggBy.ViewBy().GroupBy().SortBy().load() - the load returns data filtered by preceeding API
    - The AggBy/ViewBy/GroupBy/SortBy - pass an aggregator for downstream consumers, AggBy creates the base aggregator (required for pipeline)
4. Future Consideration
    - some stmtOBJ need there data to be propagated X times per llcOwners, for Sch_K_1.
    - some stmtOBJ need to be propagated X properties
    - some stmtOBJ needs to be propagated X customers

## Lessons Learned — Session 2026-06-02

### Accounting
- **BS open-period gap is structural, not a bug**: In an open period, the Balance Sheet will show `Assets ≠ Liabilities + Equity` by exactly the Net Income amount. This is correct for a partnership LLC: income/expense accounts remain open for K-1 allocation detail and have not been closed to Equity. The gap disappears after YE closing entries post. `stmtBalanceSheet.stats()` should expose this gap and label it `open_period_ni` when it matches the income statement NI.
- **`acctMinor` column in ViewBy=All**: The BS aggregation layer adds `acctMinor` to each equity row derived from `acctOwner` on the GL records. This allows the BS to display per-member capital splits without changing the COA structure. The column is present only in `view_by='All'` mode; property/liability views omit it.

### Software Engineering
- **`stmt` objects are immutable — bypass via `object.__setattr__`**: When lazy-computing derived attributes (e.g., `taxAggregates`) after construction, use `object.__setattr__(self, '_cache_key', value)` to bypass the freeze. Do NOT override `__setattr__` logic to allow selective mutation — the freeze must apply to all user-visible attributes.
- **Pipeline filter order matters for BS**: `AggBy` must run before `ViewBy` because `acctMinor` is derived during aggregation. If `ViewBy` is applied first (filtering rows), the aggregation loses context for per-owner equity grouping. The correct order is: `_build → AggBy → ViewBy → GroupBy → SortBy → _finalize`.
- **`check` dict from aggregator is metadata, not a row**: The `check` dict (`asset, liability, equity, equation_diff, balanced`) is stored in `self._meta['check']` and exposed via `last_check()` / `stats()`. It must NOT appear in `load()` output — downstream consumers (UI tables, IRS mappers) iterate over rows and will fail if a non-row dict is mixed in.

---

## ledger.stmtDB Overview

stmtDB — base class for all `stmt*` object, ie. Constructed Financial Data Objects.

- Per DataModelGuide § 2:
  - Constructed data objects are immutable once instantiated.
  - Every table row has a line number; every column has a columnID.
  - Every value is addressable by (stmtObj / tblID / rowNm / colNm).

- Inherits ledger.ledgerDB so stmt objects participate in the same class hierarchy as Financial DB Data Objects.  
- Unlike ledgerDB, which reads and writes a live JSON DB file under Accts/,
- stmtDB keeps the constructed table purely in memory;
- save() writes a read-only snapshot cache under Stmts/ — the in-memory object remains immutable.

Common API shared with ledger/* and consumed by ui/* + irs/*:
    load()        → list[dict]      (rows with _lineNo + _rowNm + colNm keys)
    save()        → there is no save() function (see to_json)
    to_DF()       → pandas.DataFrame
    to_json()     → json string {meta: {}, table: {df.to

Specialized API per class
    nSpaceMap()   → dict{(tblID, rowNm, colNm): value} -- this is only provided by the OBJ_Tax class. 
    ViewBY(), AggBy() and SortBy() are specialized for the OBJ_View class
    self._default_rowNm(row, i) : str   - special for OBJ_View only, override to customise row-name derivation)

## Difference between load() across sub classes

All `stmtOBJ.load()` inherite the common load() from `stmtDB` (`stmtDB.py:185) which is a list of dict, input to `to_DF()`. 
The subclass can overlay the design the contents of the format of the dict within the list. 

- The returned load() is a shallow copy of `self._rows` so callers cannot mutate the constructed table.
- Each element is a dict with keys `acctType, acct, acctSub, Debit, Credit, Balance` plus the `_lineNo` / `_rowNm` sentinels added by `stmtDB._finalize`.
- Because constructed stmt objects are immutable (DataModelGuide §2), 
-  `load()` takes no parameters and does no filtering — every call returns the same canonical row list. 
- The `view_by` filter (`'All' | 'ByAsset' | 'ByLiability' | 'ByEquity'`) is applied **once**, at `__init__` time, by `_aggregate_bs()`.
- By the time `_rows` is populated, that filter has already been baked in. 
- This is different from `stmtProfile.load(view_by='All')`, which does accept a runtime filter argument because Profile rows are cheap to filter by string prefix.

####  Full Construction pipeline 

- _build executes the pipeline @ init
- output of the pipeline  produces self._rows table of dicts

1. `__init__` stashes `view_by` and any pre-built `gl_records` on the instance.
2. `stmtOBJ.load()` runs:
   - If no `gl_records` were passed, 
       - it builds an `stmtGeneralLedger(llc, view_by='All', include_coa_seed=True)` and 
       - grabs `gl._rows` — so every COA Asset/Liability/Equity account appears on the BS even with zero postings.
2. stmtOBJ_Tax.load()
    - this will return the bkNS_OBJ.json with field value (fval) filled in.
    - each dict( fid='F###', acct=<UAS account name>, fval=<value of field>}
    - {UAS} refers to a field within stmtOBJ.load().loc[UAS_rowNm]
4. stmtOBJ_Agg.load()
    - defaults to same as `stmtOBJ.load()`
    - mostly has v0.2 behavior, except via subclass architecture w/ pipeline capability
    - super().load()
    - stmtOBJ_View.AggBy() 
        - Instanciates  `_aggregate_OBJ(gl_records) with default records
        - start of a pipeline
        - dispatches to `_aggregate_bs_pandas` (preferred) or 
            - `_aggregate_bs_fallback` (no pandas).
    - stmtOBJ_View: pipeline aggregation
        - The aggregator filters rows based on xxxBy setting
        - ViewBy : slice based on `acctType ∈ {Asset, Liability, Equity}`, 
        - Groupby : `(acctType, acct, acctSub)`, sums Debit / Credit
            - computes and adds: `Balance = Debit − Credit`, 
        - SortBy  : `OBJ_ORDER` then by `acct`
    - aggregator.load()
        - appends a `TOTAL` row.
        - returns a `check` dict (`asset, liability, equity, equation_diff, balanced`) 
        - checkDict  gets stashed in `self._meta['check']` and 
        - `self._check`, exposed via 
            - `last_check()` and 
            - `stats()`. 
        - the checkDict is NOT part of what `load()` returns.
        - _finalize` (in stmtDB) renumbers `_lineNo` globally, 
            - fills in `_rowNm`, 
            - builds the cell index that `get(rowNm, colNm)` and 

    
## get() -  Cell values
- available only with OBJ_View
- `get(rowNm, colNm)` against the cell index. 
- to get tax aggregates (`cash`, `total_assets`, `accum_depr`, etc.), 
- get  tax aggregates (cash, total_assets, accum_depr, etc.)
    - use `taxAggregates()`
    - lazily delegates to `stmtFinancialReport.taxData()`
    - caches via `object.__setattr__` to bypass the freeze.