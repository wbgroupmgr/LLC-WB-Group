# ProjectLevel3 v0.2 — Book Activities to Level 3 (Analytical) Accounting

> **Scope.** Planning document only. NO code changes are made by this file.
> **Baseline.** State of the codebase after the reset-and-simplify refactor
> (Tasks #30–#35 — implicit `v0.2.1`): all stmt/ledger code lives under
> `ledger/`; GL is the single source of truth for BS/IS; COA-seed rows
> render empty accounts; `tests/testBalSh` and `tests/testIncStmt` both
> pass the `GL == VIEW` invariant.
> **Target.** Level 3 (non-Advanced) of `LLC_AccountingWorkflow.md` —
> **Analytical**: ability to view GL + Trial Balance; assert every COA
> account is represented in the Trial Balance; enforce Σ Debits = Σ Credits.
> PDF Financial Reports / Letters and any IRS work are **out of scope**
> (those are v0.3 / ProjectLevel4).

---

## 0. TL;DR

* **Two subtasks + release step**: `v0.2.2` (code-base clean-up + uniform
  ledger API) and `v0.2.3` (`stmtTrialBalance` + 2-frame GL view), followed
  by a v0.2 GitHub release.
* **Estimated total effort: ~39% of the remaining usage window**
  (v0.2.2 ≈ 23%, v0.2.3 ≈ 10%, release ≈ 1%, contingency ≈ 5%).
* **Will additional usage be needed? No** — project fits within the
  current allocation with a 5% contingency buffer. See §8.
* **All five open questions are resolved** (§10); execution task list
  ready in §12.

---

## 1. What "Level 3" Analytical (non-Advanced) means

`LLC_AccountingWorkflow.md` defines Level 3 as *Analytical* — interpreting
the General Ledger to produce and display financial views. "Non-Advanced"
here means: no trend analytics, no regulatory-compliance checks, no tax
mapping.

As an accounting/software expert I am locking Level 3 (non-Advanced) to
the following concrete acceptance criteria:

| # | Acceptance criterion | Why this is the right bar for Level 3 |
|---|-----------------------|----------------------------------------|
| A | A `stmtTrialBalance` constructed object exists, sourced from `stmtGeneralLedger`, with columns `[acctType, acct, Debit, Credit, Balance]`. | Trial Balance is the canonical bridge view in Book accounting. |
| B | The Trial Balance contains **every** COA account (via COA seed) — zero-balance accounts appear with `Debit=0, Credit=0`. | "Trial Balance accounts match COA 100%" per user directive. |
| C | Σ Debits == Σ Credits within EPS on the Trial Balance (zero-sum invariant). | Standard book-keeping closure check. |
| D | The GL view is a 2-frame UI: top frame = Trial Balance (aggregated), bottom frame = Transaction Records (details). Each frame is independently collapsible; ViewBy options are wired to `to_agg()` arguments. | User directive in §4 v0.2.3. |
| E | Every `llc*` / `stmt*` module conforms to the uniform API: `load() / save() / to_DF() / to_agg() / to_IRS()`. | Pre-condition for ProjectLevel4 (v0.3). |
| F | `tests/testLedgerAPI.py` exercises all "safe" (read-only) APIs on every ledger/stmt module without raising. | Regression floor. |

Anything beyond A–F (IRS forms, Book-to-Tax bridge, PDF reports, letters,
cross-year analytics) is **explicitly out of scope** for v0.2 and deferred
to ProjectLevel4 v0.3.

---

## 2. Current-State Audit (Post-Task #35)

### What is done

| Level | Status | Evidence |
|-------|--------|----------|
| 1 Transactional | ✅ | `llcBank`, `llcAssets`, `llcExpRev`, `llcPayables`, `llcReceivables` all persist JSON, double-entry dual-account shape. |
| 2 Book | ✅ | `stmtGeneralLedger` is the authoritative store; COA-seed rows render empty accounts; `include_coa_seed=True` flag in place. |
| 3 Analytical | ✅ | `stmtBalanceSheet`, `stmtIncomeStmt`, `stmtOwnerEquity`, `stmtPropertyEquity`, `stmtCashFlowStmt` built; `testBalSh` / `testIncStmt` pass `GL == VIEW`. |
| 4 Tax Prep | 🟡 partial | `irs/Form1065.py`, `Sch_K1.py`, `Form4562.py`, `mapIRS2LLC.py`, `pdfFill/pdfMap/publishMap` exist. `FILL.pdf` generation regressed ~3–4 days ago. No book-to-tax bridge. No reconciliation test. |

### What is missing to hit Level 3 A–F

1. **No Trial Balance constructed object** — it is conceptually present
   inside `stmtGeneralLedger`, but there is no `stmtTrialBalance` class
   nor a UI view that groups by `(acctType, acct)` with Debit/Credit columns.
2. **Current code base is out of sync with the Accounting Model Design** —
   constructed objects still carry the `llc*` prefix (e.g. `stmtGeneralLedger`)
   instead of the design-specified `stmt*` prefix that distinguishes them
   from DB-layer `llc*` objects.
3. **No uniform ledger API** — each module exposes its own ad-hoc method
   names. The design calls for `load / save / to_DF / to_agg / to_IRS` on
   every object.
4. **`setup_paths.py` is static Python** — the design calls for a
   per-LLC profile JSON (`llcProfile_<LLC>.json`) so paths/metadata are
   data-driven.
5. **`ledgerGeneral` double-entry logic** lives in its own module but
   conceptually belongs inside `stmtGeneralLedger` (the only consumer).
---

## 3. Design Decisions (Assumptions Made Without Asking)

These lock-ins let the plan proceed without further clarification:

1. **Level numbering fix. fixed
2. **Trial Balance is a constructed object** (frozen `stmtDB`), not a
   recompute-on-read view. It is the canonical bridge between GL and every
   IRS form — so giving it a stable, testable shape is worth the tiny
   amount of extra code.
--

## 4. The Shortest-Path Plan (Minimum Work, Ordered by Dependency)

The plan is two subtasks followed by a release step.

## Book Activities

### Proj_v0.2.2 — Clean up current code base (uniform Ledger API)

**Scope.** Rename constructed-stmt modules to `stmt*`, enforce the uniform
`load/save/to_DF/to_agg/to_IRS` API on every ledger module, merge
`ledgerGeneral` into `stmtGeneralLedger`, and replace static `setup_paths.py`
with a data-driven `llcProfile_<LLC>.json`.

**Changes.**
1. Rename `ledger/llc<Constructed>.py` → `ledger/stmt<Constructed>.py`
   for the 7 constructed objects: `stmtBalanceSheet`, `stmtIncomeStmt`,
   `stmtGeneralLedger`, `stmtOwnerEquity`, `stmtPropertyEquity`,
   `stmtCashFlowStmt`, `stmtFinancialReport`. DB-layer modules
   (`llcAssets`, `llcExpRev`, `llcPayables`, `llcReceivables`, `llcBank`,
   `llcOwners`, `llcCustomers`, `llcCOA`) keep the `llc*` prefix.
2. Fix all consumers (`ledger/`, `irs/`, `ui/`, `util/`, `tests/`) —
   rewrite every `from ledger.llc<X>` → `from ledger.stmt<X>` for
   constructed objects only.
3. Ensure every ledger/stmt module adheres to the uniform API (declared
   on `ledgerObject` base class):
    - `fObj.load() -> list[dict]` — raw per-transaction records (Dual or Single Accounts)
    - `fObj.save() -> None` — persist raw transaction records to JSON
    - `fObj.to_DF() -> pd.DataFrame` — raw records, `index=tID`
    - `fObj.to_agg(filterDict=, by=, aggDict=, pretty=) -> {'table': pd.DataFrame, 'extraFields': dict}` — aggregated view:
        - `filterDict=` : select subset of transactions (pre-agg)
        - `by=` : one of `'Trial' | 'BalSh' | 'IncStmt' | 'custom:[list]'`
            - `Trial`   — groupby `[acctType]`
            - `BalSh`   — filter `acctType ∈ {Asset, Liability, Equity}`, then groupby
            - `IncStmt` — filter `acctType ∈ {Income, Expense}`, groupby `[acctType, acct, Ledger]`
            - `custom`  — groupby caller-supplied column list
        - `aggDict=` : pandas `groupby().agg()` dict
        - `pretty=` : `False` → raw; `True` → row refs + subtotals on both axes
        - **Return shape** — a dict with two keys:
            - `'table'`       : the aggregated `pd.DataFrame` (Book numeric data)
            - `'extraFields'` : a `dict` placeholder (initially `{}`) that
              downstream `to_IRS()` can supplement with non-numeric
              context fields — e.g. `propertyName`, `LLCname`, `EIN`,
              partner ownership %, asset descriptions — that the
              numeric GL alone cannot supply.
        - Output of `.to_agg()` is the base input for downstream `stmt*` pipelines (primary consumer: `stmtGeneralLedger.to_agg`).
    - `fObj.to_IRS() -> list[dict]` — **default** on any DB-layer
      entity object: one dict per entity row, keyed by entity ID, e.g.:
      ```
      llcOwners.to_IRS()   → [ {'owner1': {'nm':..., 'addr':..., 'entityID':...}},
                               {'owner2': {'nm':..., 'addr':..., 'entityID':...}}, ... ]
      llcCustomers.to_IRS()→ [ {'customer1': {...}}, ... ]
      llcAssets.to_IRS()   → [ {'property1': {'propertyName':..., 'address':..., 'basis':...}}, ... ]
      ```
      This shape is intentional — it directly drives the **"1 PDF per
      owner-member" K-1 pattern** in v0.3 (one entity → one PDF) and
      supplies the `extraFields` values that `stmt*.to_IRS()` merges
      into its numeric payload.
      `stmt*` constructed objects override `to_IRS()` to emit a single
      Book-field dict: `{'field1': value1, 'field2': value2, ...}`.
4. Create `tests/testLedgerAPI.py` exercising all "safe" (read-only) APIs
   (`load / to_DF / to_agg / to_IRS`) on every ledger module — no master-DB
   mutations.
5. Merge `ledger/ledgerGeneral.py` into `ledger/stmtGeneralLedger.py`
   (the double-entry expansion is used only there post-refactor).
6. Refactor `setup_paths.py` → data-driven profile
   `Accts/llcProfile_<LLC>.json` (e.g. `llcProfile_WBGroupLLC.json`):
   profile carries `{ TOP, dirAccounting, dirAccts, dirBankStmts[year],
   dirTaxRecords[year], currentYear, llcName, EIN, filingStatus, partners[] }`.
   `setup_paths.py` becomes a thin loader that reads the active profile.

**Done when.**
1. Every module's `to_agg(by='Trial')` returns 1 row per COA account per
   acctType, with a balance value (zero-balance accounts included via
   COA seed).
2. `tests/testLedgerAPI.py` green on every module.
3. `tests/testBalSh.py` and `tests/testIncStmt.py` still pass post-rename.
4. `llcProfile_WBGroupLLC.json` loads; all path constants resolve.

**Token % estimate:** ~**23%**.
Breakdown: renames + import fixes 4%; uniform-API implementation across
~14 modules 10%; `to_agg` 4-mode rollout + `extraFields` plumbing 4%;
`to_IRS` entity-dict-list default + `stmt*` overrides 1%;
`ledgerGeneral` merge 1%; `llcProfile` refactor 1%; `testLedgerAPI.py`
2%.

---

### Proj_v0.2.3 — Introduce `stmtTrialBalance` + 2-frame GL view

**Scope.** A thin `stmtTrialBalance` class inside the `stmtGeneralLedger`
module that aggregates GL data with all COA accounts into
`(acctMajor, acct, Debit, Credit, Balance)` rows. No new data source —
it is a re-shaping of `stmtGeneralLedger.to_agg(by='Trial', …)`. Plus a
UI enhancement that splits the GL page into two collapsible frames
(Trial Balance + Transaction Records) wired to `to_agg()` params.

**Changes.**
1. New `stmtTrialBalance` class inside `ledger/stmtGeneralLedger.py`
   (sibling to `stmtGeneralLedger`, subclass pattern).
2. `ledger/stmtFinancialReport.py` imports
   `from ledger.stmtGeneralLedger import stmtTrialBalance` and adds it
   to the report bundle.
3. Add unit tests to `tests/testLedgerAPI.py`:
    - Σ Debits == Σ Credits within EPS (zero-sum).
    - `set(accts per acctType)` in Trial Balance == COA-defined set.
4. Enhance `ui/stmtGeneralLedger.py` view: 2 collapsible frames —
    - Top frame: Trial Balance (newly added)
    - Bottom frame: Transaction Records (existing table)
    - Wire existing ViewBy dropdown into `stmtGL.to_agg()` `filterDict`/`by`
      parameters so the same control drives both frames.

**Done when.**
1. `stmtTrialBalance(llc)._rows` yields exactly one row per
   `(acctMajor, acct)` (including zero-balance accounts via COA seed).
2. Tests confirm `acct`-per-`acctType` set matches COA definitions.
3. Zero-sum test passes.
4. GL page renders both frames; ViewBy changes are reflected in each.

**Token % estimate:** ~**10%**.
Breakdown: `stmtTrialBalance` class + wiring 2%; tests 2%; UI 2-frame
view + ViewBy binding 5%; debugging 1%.

---

### Proj_v0.2.final — Release v0.2 to GitHub

**Scope.** Tag and push v0.2 (commit + push + `git tag v0.2`). Update
`CHANGELOG.md`. No code changes.

**Token % estimate:** ~**1%**.

---

### Total token estimate

| Subtask | Effort | Token % |
|---------|--------|---------|
| v0.2.2 — Clean up code base (uniform Ledger API) | Large | **23** |
| v0.2.3 — `stmtTrialBalance` + 2-frame GL view     | Medium | **10** |
| v0.2.final — GitHub release                       | Trivial | **1** |
| Contingency / diagnostic                          | Buffer  | **5** |
| **TOTAL** |  | **~39%** |

---

## 5. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | Renaming `llc<Constructed>` → `stmt<Constructed>` leaves stale imports that only surface at runtime (lazy imports, `__init__.py` re-exports, docstring examples). | High | Medium — broken pages until fixed. | Do renames via one sed pass + full grep for `llc<Constructed>` stem; run `testBalSh` / `testIncStmt` / `testLedgerAPI` as the quick regression gate. |
| R2 | Uniform API imposes `to_DF / to_agg / to_IRS` on DB objects that currently don't have natural aggregations (e.g. `llcOwners`, `llcCustomers`). | Medium | Low — risk is over-engineering. | `to_agg` on a non-transactional object raises `NotImplementedError` with a clear message; `to_IRS` returns `{}` by default on the base class. |
| R3 | `llcProfile` refactor breaks every module that imports bare constants from `setup_paths` (e.g. `from ledger.setup_paths import TOP`). | Medium | Medium. | Keep `setup_paths.py` as a back-compat shim that loads the active profile on import and re-exports the same constant names. |
| R4 | The 2-frame UI requires re-wiring the ViewBy dropdown to drive two aggregations; current UI is tightly coupled to a single table. | Medium | Low. | Implement as a thin template change — Trial Balance frame fetches `to_agg(by='Trial', filterDict=<current viewBy>)`, Transactions frame fetches current rows. Collapsible via `<details>` tag, no JS framework change. |
| R5 | `ledgerGeneral` has consumers outside `stmtGeneralLedger` that we haven't catalogued. | Low | Medium — runtime break. | Quick grep for `ledgerGeneral` imports before merging; if >1 consumer, keep it in place and merge in v0.3 instead. |
| R6 | `testLedgerAPI.py` surfaces API-shape mismatches that require retroactive changes in other modules. | Medium | Low — expected work, counts toward the 22%. | Time-box at 2% of token budget; if blown, ship partial coverage and log the rest. |

---

## 6. Proposed Enhancements to Design / Workflow Docs (scoped to v0.2)

> Only doc changes that are needed to make the v0.2 plan coherent are
> listed here. Tax-layer doc changes (Book-to-Tax Bridge, Sch-M-2, IRS
> packet) are moved to ProjectLevel4 v0.3.

### `LLC_AccountingWorkflow.md`

1. **Level numbering.** Current text lists levels 1, 2, 3, 5, 6, 7
   (skipping 4). Renumber to 1, 2, 3, 4, 5, 6 where 4 = Tax Preparedness.
2. **Monthly Reconciliation sections.** Two "#### 2" and two "#### 5"
   headings — renumber cleanly.
3. **Fix the table row** "Sch L, Line 16 | BalSh | Accounts Payable" —
   currently has a missing `|` that breaks Markdown rendering.
4. **Add an explicit "Level 3 Exit Criteria" block** mirroring §1 of this
   plan doc.

### `LLC_AccountingDesign.md`

1. **Codify the `llc*` vs `stmt*` naming split** — all code lives under
   `ledger/` today, but there is no naming distinction between DB-layer
   objects (`llc*`) and constructed objects (`stmt*`). v0.2.2 introduces
   that distinction; the design doc must say so explicitly.
2. **Add `ledger/stmtGeneralLedger.py::stmtTrialBalance`** to the
   constructed-object list.
3. **Declare the uniform Ledger API** on the `ledgerObject` base class:
   `load / save / to_DF / to_agg / to_IRS`.
4. **Document the `to_agg` four-mode semantics** (Trial / BalSh /
   IncStmt / custom).
5. **Replace `setup_paths.py` description** with the new
   profile-driven loader + `llcProfile_<LLC>.json` schema reference.
6. **Fix typo `smtGeneralLedger.py`** → `stmtGeneralLedger.py`.

### `DataModel.md`

Add `stmtTrialBalance` to "Constructed Financial Data Objects" and
adopt the `llc*` / `stmt*` split.

---

## 7. Open Questions (Answered Here via Expert Assumptions)

> Per the user's instruction: I do **not** ask any of these of the user.
> Each is answered with the best accounting/software assumption so the
> project can proceed.

**Q2. Should Trial Balance be a persistent `Accts/` artifact or a
recomputed stmt?**
**A2.** Constructed stmt only — consistent with the "stateless logic"
principle in the design doc. Persisting it would violate append-only. - approved

**Q8. Does the user want interactive PDF editing?**
**A8.** No — the design doc specifically mentions providing an "Edit
button on each field item mapping to allow human customization on a
small set" *within the UI*, not a live PDF editor. Out of scope for v0.2.
-- Correction: not editing of PDF... but editing of the TaxField2GLAcct map. 

All other question will be addressed in future project

---

## 8. Will Additional Usage Be Needed?

**Answer: No.**

**Justification.** The remaining work is ~39% of the current usage
window (34% for v0.2.2 + v0.2.3 + release, plus 5% contingency). The
codebase is already at "Level 3 minus Trial Balance" — the refactor is
API normalization and a single new constructed object, not new
data-model design. The largest risk (R1: stale imports after rename)
is mitigated by the existing green test suite acting as a regression
gate. Under all other scenarios the project completes within the
current allocation.

If v0.2 scope grows beyond acceptance criteria A–F (e.g. cross-year
analytics, advanced Level-3 features like trend detection, Cash Flow
Statement regression fix, property-level drill-downs), additional
usage **may** be required — those are candidates for v0.2.4+ or
ProjectLevel4 and are not priced into the 38% estimate.

---

## 9. Appendix — File Manifest for v0.2 Completion

### Renamed (file basename change; 7 files)
```
ledger/stmtBalanceSheet.py        → ledger/stmtBalanceSheet.py
ledger/stmtIncomeStmt.py          → ledger/stmtIncomeStmt.py
ledger/stmtGeneralLedger.py       → ledger/stmtGeneralLedger.py
ledger/stmtOwnerEquity.py         → ledger/stmtOwnerEquity.py
ledger/stmtPropertyEquity.py      → ledger/stmtPropertyEquity.py
ledger/stmtCashFlowStmt.py        → ledger/stmtCashFlowStmt.py
ledger/stmtFinancialReport.py     → ledger/stmtFinancialReport.py
```

### New files (3)
```
Accts/llcProfile_WBGroupLLC.json     # data-driven paths + LLC metadata
tests/testLedgerAPI.py               # safe-API exercise of every module
(stmtTrialBalance class lives inside ledger/stmtGeneralLedger.py)
```

### Modified files (import + API rewrites; ~20 files)
```
ledger/__init__.py
ledger/ledgerObject.py               # declare uniform API base
ledger/setup_paths.py                # thin shim → loads llcProfile JSON
ledger/llcAssets.py                  # to_DF/to_agg/to_IRS
ledger/llcExpRev.py                  # to_DF/to_agg/to_IRS
ledger/llcPayables.py                # to_DF/to_agg/to_IRS
ledger/llcReceivables.py             # to_DF/to_agg/to_IRS
ledger/llcBank.py                    # to_DF only (raw bank CSV)
ledger/llcOwners.py                  # load/save only
ledger/llcCustomers.py               # load/save only
ledger/llcCOA.py                     # to_DF of COA
ledger/LLC.py                        # profile loader + re-exports
ledger/llcAPI.py                     # API surface
ledger/stmt*.py (all 7 renamed)      # to_DF/to_agg/to_IRS
irs/*.py                             # import path fixes
ui/stmtGeneralLedger.py               # 2-frame view (v0.2.3)
ui/*.py                              # import path fixes
util/utilEditSession.py              # import path fixes
tests/testBalSh.py, testIncStmt.py   # import path fixes
```

### Removed (1)
```
ledger/ledgerGeneral.py              # content moved into stmtGeneralLedger.py
```

Touched lines total estimate: **~700–900 LOC** across ~30 files — most
of it mechanical import/rename + the uniform API boilerplate.

---

## 10. Resolved Questions (user answered — no further input needed)

**Q1. Rename split → `llc*` (DB) / `stmt*` (constructed).** ✅ Confirmed.
The 7 constructed modules rename to `stmt*`; the 8 DB-layer modules
(`llcAssets`, `llcExpRev`, `llcPayables`, `llcReceivables`, `llcBank`,
`llcOwners`, `llcCustomers`, `llcCOA`) keep `llc*`.

**Q2. `save()` on `stmt*` constructed objects →
`raise Exception('InvalidRequest; ImmutableObject')`.** ✅ Confirmed.
Implementation: a custom `InvalidRequestError` (or `ImmutableObjectError`)
exception class on `ledgerObject`, raised with message
`"InvalidRequest; ImmutableObject"` from `stmt*.save()`. This makes the
immutability contract explicit and the failure easy to grep.

**Q3. `to_IRS()` default — list of per-entity dicts + `extraFields`
hand-off.** ✅ Confirmed.
- **DB-layer entity objects** (`llcOwners`, `llcCustomers`, `llcAssets`,
  etc.) → default `to_IRS()` returns `list[dict]`, one dict per entity
  row, keyed by the entity's ID. Shape:
  ```
  [ {'<entityID_1>': {'nm':..., 'addr':..., 'entityID':..., ...}},
    {'<entityID_2>': {...}}, ... ]
  ```
  This directly supports the **"1 PDF per owner-member"** K-1 pattern
  coming in v0.3 — each list entry drives a separate PDF fill.
- **`stmt*` constructed objects** → `to_IRS()` returns a flat Book-field
  `dict` for numeric IRS fields.
- **`stmtGeneralLedger.to_agg()` returns both an aggregated table AND an
  `extraFields` dict placeholder** (empty by default). Downstream
  `to_IRS()` calls supplement that placeholder with non-numeric context
  — profile metadata (LLC name, EIN) and asset-specific fields
  (propertyName, address) — that the numeric GL alone cannot provide.
  `extraFields` is a place-holder in v0.2; real consumption happens in
  v0.3 when IRS forms pull it into PDF fills.

**Q4. `llcProfile_<LLC>.json` schema → proceed with the §10-Q4 draft
as-is.** ✅ Confirmed. Iterate the schema in v0.3 as FILL.pdf surfaces
missing fields the GL can't supply.

**Q5. 2-frame GL view → server-side Flask/Jinja only.** ✅ Confirmed.
No client-side JS state, no new framework. Use HTML `<details open>`
for collapsibility and a single backend endpoint that returns both
aggregations in one render. ViewBy dropdown is a form submit (or
`htmx`-style request if already available) that re-renders the page.

---

## 11. Locked Assumptions (no answer needed)

These are the expert-accounting/software decisions driving the plan:

A. **`ledgerGeneral` merges into `stmtGeneralLedger`** (post-rename) —
   sole consumer; merging avoids a floating utility module.
B. **`setup_paths.py` stays as a back-compat shim** that re-exports
   profile-driven constants under the same names to protect the ~20
   existing importers.
C. **`stmtTrialBalance` is a subclass of `stmtGeneralLedger`** (not a
   sibling) — per the user directive in v0.2.3.
D. **`to_agg` 4-mode semantics** — `Trial`, `BalSh`, `IncStmt`,
   `custom:[list]`. Each raises a clear error when invoked on an
   object without the required `acctType` set.
E. **`to_agg()` return shape is `{'table': DataFrame, 'extraFields': dict}`**
   uniformly on every module (per Q3 resolution).
F. **`to_IRS()` default return is `list[dict]`** for DB-entity objects;
   `stmt*` overrides return a flat `dict` of Book fields
   (per Q3 resolution).
G. **`stmt*.save()` raises `Exception('InvalidRequest; ImmutableObject')`**
   (per Q2 resolution).
H. **COA seed is always on** for `stmtTrialBalance` so criterion B
   (every COA account present) is automatic.
I. **No persistence of Trial Balance** — always recomputed
   (consistent with stateless-logic principle).
J. **Release v0.2 is a git tag + CHANGELOG append**, not a separate
   branch. Done on current working branch after v0.2.3 passes.
K. **All existing passing tests remain green** — `testBalSh` and
   `testIncStmt` are the regression gate at every step.

---

## 12. Execution Task List

Once GO is given, work proceeds in strict dependency order:

```
v0.2.2.1  Rename ledger/llc<Constructed>.py → ledger/stmt<Constructed>.py (7 files)
v0.2.2.2  Fix all imports (ledger, irs, ui, util, tests) — sed + grep audit
v0.2.2.3  Declare uniform Ledger API on ledgerObject base class
          (load / save / to_DF / to_agg / to_IRS + InvalidRequestError)
v0.2.2.4  Implement to_agg 4-mode + extraFields on every module
v0.2.2.5  Implement to_IRS entity-dict-list default (DB) + stmt* overrides
v0.2.2.6  Merge ledger/ledgerGeneral.py into ledger/stmtGeneralLedger.py
v0.2.2.7  Refactor setup_paths.py → Accts/llcProfile_WBGroupLLC.json
v0.2.2.8  Write tests/testLedgerAPI.py — safe-API exercise on every module
v0.2.2.9  Regression gate: testBalSh + testIncStmt still green

v0.2.3.1  Implement stmtTrialBalance (subclass of stmtGeneralLedger)
v0.2.3.2  Wire into stmtFinancialReport
v0.2.3.3  Add TB unit tests (zero-sum + COA-completeness) to testLedgerAPI
v0.2.3.4  Rewrite ui/stmtGeneralLedger.py to 2-frame (Flask/Jinja, server-side)
v0.2.3.5  Regression gate: all tests green + visual GL view check

v0.2.final  Update CHANGELOG + git tag v0.2 + push
```
