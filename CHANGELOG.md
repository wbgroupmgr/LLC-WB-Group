# uillc — LLC Editor Changelog

All notable changes to the `uillc` LLC editor package are tracked here.
This project loosely follows [Keep a Changelog](https://keepachangelog.com/)
and [Semantic Versioning](https://semver.org/).

---

## [BACKLOG — Pending Work Items]

### TODO-1: Form 1065 Schedule B — Checkbox Review (tackle after SchK1 complete)
**Priority:** High — most Schedule B checkbox answers are incorrect per Broader
Knowledge Injection standard.
**Scope:** Review every checkbox field in `Form1065Agent.py` Schedule B section.
Apply the Golden Rule: for each checkbox field, explicitly research the IRS
condition that makes "Check" correct; document it; default to NoCheck if the
condition cannot be confirmed from W&B Group's books/profile.
**File:** `irs/taxAgents/Form1065Agent.py` — Schedule B section agents.
**Reference:** IRS Form 1065 Instructions Part II (Schedule B), Questions 1–28.
All boolean/checkbox fields must follow the two-rule binary check standard
defined in `FormSchK1Agent._SectionAgent` Golden Rule §2.

---

## [1.3.0] — 2026-06-13  **Financial Snapshot + Form 1065 Guided Review Fix**

### Fixed
- **Home Financial Snapshot (issue #21)** — wired `/api/home/snapshot` to live
  IS/BS/GL data; stacked bar chart (Income / Exp:Ops / Exp:Other); horizontal
  5-column metrics table (YTD Revenue, YTD Expenses, Net Income, Total Equity,
  Earned P&L); split expense into `expense_op` (operational) vs `expense_cap`
  (Acct.Exp.Depreciation) so December depreciation no longer inflates expense bar.
- **Form 1065 Guided Review — KD-R02 false positive (issue #22)** —
  `_load_fill_dict()` fell back to reading `{}` when `Form1065_fillDict.json`
  was missing (pipeline never saves it).  Added FILL.pdf fallback: reads field
  values via pypdf using `_SHORT_TO_LK` (f5_02→K_2).  K_2 = 667.55 now resolved
  correctly so KD-R02 no longer fires.
- **Form 1065 Guided Review — contradictory badge/body (issue #22)** —
  `_normalize_summary()` omitted `'issues'` from section dicts; template
  `{% if sec.issues %}` was always falsy, showing "✓ No issues" while badge
  showed "✗ Needs Fixing".  Added `'issues': s.get('issues', [])`.
- **testForm.py alias (no issue)** — `--form 1069` now maps to `Form1065` with
  a NOTE message; unknown forms exit with a clear list of valid options.

### Technical Notes
- `Form1065Agent._SectionAgent._SHORT_TO_LK`: hardcoded shortName→logicalKey
  table for Schedule K fields; needed because Form1065 namespace has no keys PDF
  (all `logicalKey` = '').  Only K_1/K_2 needed today; extend as more K_ rules
  are added.
- Home snapshot API now returns `expense_op` + `expense_cap` separately; template
  uses Chart.js `stack: 'expense'` on both datasets to render stacked bar.

---

## [1.2.0] — 2026-06-11  **IRS Submission Package + Accountant Letter (Phase 3+4)**

### Added
- **LLCTaxAgent Phase 3 (`phase3_package`)** (`irs/taxAgents/LLCTaxAgent.py`):
  assembles `IRS_Submission_{year}/` directory, copies all FILL PDFs, computes
  SHA-256 checksums per file, writes `manifest.json` with per-artifact required/
  present flags and filing deadline.
- **LLCTaxAgent Phase 4 (`phase4_submit`)** (`irs/taxAgents/LLCTaxAgent.py`):
  builds submission checklist (per-form present/missing, accountant letter,
  filing method, K-1 delivery per partner), persists status in
  `Profile.F1065.submission_status`, generates Accountant Notification Letter
  PDF via reportlab.
- **`generate_accountant_letter()`**: saves `AccountantLetter_{year}.pdf` to
  `Forms/` — includes LLC letterhead, form list table, SHA-256 integrity note,
  filing deadline, IRS mailing address, principal officer contact.
- **`/view/tax_prep`** dashboard (`ui/templates/tax_prep.html`): 3 collapsible
  frames: (1) Submission Checklist with phase status strip, XF audit table,
  artifacts table; (2) Accountant Letter generate/view; (3) Submission Status
  + K-1 delivery per partner with date inputs.
- **Flask routes** in `ui/llcMgmt.py`:
  `GET /api/tax/status`, `POST /api/tax/prepare`, `POST /api/tax/package`,
  `POST /api/tax/accountant_letter`, `POST /api/tax/submission/update`,
  `GET /api/tax/report`, `GET /forms/AccountantLetter_{year}.pdf`.
- **📬 IRS Submission** nav link in `_nav_dropdown.html` (new "IRS Filing" group).
- **SSN wiring for Schedule K-1** (`irs/Sch_K1.py`, `ledger/llcOwners.py`,
  `irs/Form1065.py`): 3-location fix so K-1 header EIN field reads from
  `llcOwners[].SSN` when `ein` is absent.
- **LLC Admin view** (`/admin`, `ui/llcMgmt.py`, `ui/templates/admin_view.html`):
  3 collapsible frames for Owners (with SSN masking + RetainedEarning), Tenants,
  and State/Fed Milestones.
- **SSN field** in `llcOwners` records; `RetainedEarning` computed from IS
  per-owner (Books-First, not stored).

## [1.1.0] — 2026-06-11  **IRS Guided Review — Form 8825 / 4562 / 1065 all GO**

All three IRS Guided Review agents confirmed correct. No false-positive
ERRORs or WARNings. Schedule K-1 SSN-per-member deferred to v1.2.

### Added
- **`BooksContext`** (`util/utilEditSession.py`): session-level lazy GL
  snapshot shared by both `eSession.books` and `llc.books`. IRS agents
  (which receive only `llc`) reuse the cached snapshot instead of
  building a second `stmtGL` pass. Invalidated automatically by
  `llcRecordsView.savePayload()` on every DB write.
- **INFO / WARN / ERROR badge labels** in Guided Review issue rows
  (`ui/templates/agent_generic_review.html`): replaces icon-only color
  display with `ERROR` / `WARN` / `INFO` pill badges. Rule ID moved to a
  separate monospace span after the badge.

### Fixed
- **`stmtIS.taxAggregates()` Debit-only overcounting** (`ledger/stmtIS.py`):
  the v0.2 fast path (`rptFinancialReport.taxData()`) summed only the
  Debit column for expense accounts, overcounting when the same account
  had both a Debit and an offsetting Credit (e.g. an expense + its
  refund/return). Guard added: skip fast path when `gl_records` were
  explicitly passed to `stmtIS`. `_taxAggregates_local()` (Debit − Credit)
  is now always used for all IRS agent calls via `_GLContext`.
  Root cause of persistent F8EX-R05 false-positive ERROR on server with
  `--load`: `utilEditSession` initialises `llc.bk` (via `_Bank()`), which
  lets `rptFinancialReport.__init__` succeed; standalone tests skip it.
- **`Form8825Agent._GLContext.build()`**: checks `llc.books` (BooksContext)
  first so all four section agents within one run share a single snapshot
  (`inject_context()`) — no extra file reads.
- **`getSummary()` always-fresh**: never reads cached session-state JSON
  as truth; always calls `run_phases_1_2()` fresh per request.

### Documentation
- `docs/Books/design_LLC_02-App-Accounting.md`: added "BooksContext —
  Shared GL Snapshot (v1.1)" and "taxAggregates() Correctness Rule (v1.1)"
  sections documenting the three-pipeline problem, BooksContext invariant,
  and the Debit-only overcounting guard.

---

## [0.3.0] — 2026-05-18  **PythonAnywhere Production Milestone**

First version fully operational on PythonAnywhere under MultiTaskWS
DispatcherMiddleware. All views — Transactions, Financial Statements, and
IRS Tax Aids — confirmed working in production. Login, session, and auth
fully functional across uWSGI workers.

### Added
- **Structured logging** (`_setup_logging` in `llcMgmt`): rotating file log
  at `logs/llcRentalTracker.log` + stderr (captured by PA error log).
  Logs startup (llc, year, secret-key source, GPG passphrase status),
  auth events (login ok/fail, logout), and before-request guard redirects.
- **Unified `~/.llcRentalTracker/config.json`**: single config replaces
  per-file `<llcName>_<year>_config.json`. Supports `default` entry and
  `llcList` array. Backward-compatible fallback reads legacy per-file configs.
- **`addTracker()`** in `wsCmd.py`: registers `llcRentalTracker` stanza into
  `~/.MultiTaskWS/MultiTaskWS_config.json` on `--setup`, including `sys_path`.
- **`wsgi.py`** secrets loader: reads `WEB_SECRET_KEY` from MultiTaskWS config
  (per-tracker stanza then top-level fallback) before importing `llcMgmt`.
- **`--newBus --llcName`** flag: overrides folder-name auto-detect for data-file
  suffix (e.g. `LLC-WBGroup` folder → `WBGroupLLC` data files).
- **Switch Year** on home page: fiscal year selector persists to session.
- **Form 4562** full pipeline: BookToIRS, UI view, Review modal with Part
  disposition + depreciation reconciliation.
- **Schedule K-1** per-partner PDF pipeline and member selector.
- **Aid dialog**: full UAS universe, Profile.Form8825 source, value labels,
  edit/delete BookVal literals.
- **IS ByProperty / ByPropertyDetails** views with property columns unstacked.
- **IS PerMemberDetails** view + Rental/Ordinary income split.
- **GL Auditor Service** (`ledger/auditor.py`) + API routes + GL view panel.

### Fixed — PythonAnywhere / DispatcherMiddleware
- All templates replaced hardcoded paths (`/login`, `/logout`, `/home`) with
  `url_for()` so SCRIPT_NAME prefix (`/rentalTracker`) is honoured.
- `_require_login` guard: handle `request.endpoint is None` on trailing-slash
  redirects; use `request.script_root + request.path` for `next=` URL.
- `login_required` decorator: same `script_root + path` fix.
- `Flask.secret_key`: was `secrets.token_hex(32)` (random per worker) →
  now read from MultiTaskWS config then derived-hash fallback. Fixes session
  invalidation across uWSGI workers.
- `LLC_GPG_PASSPHRASE`: injected from `eSession.llc.MultiTaskWS_Config` in
  `llcMgmt.__init__` so the user DB can be decrypted without a pre-set env var.
- IRS PDF `url_for()`: `pdf_url` and `ns_pdf_url` replaced hardcoded
  `/forms/<id>.pdf` strings — was 404 under dispatcher mount prefix.

### Fixed — Setup / Config
- `wsCmd.py --setup`: no longer crashes on missing config or profile.
- `LLC.__init__`: `setup_paths` values always win over stale profile JSON
  (TOP, BOOKS_DIR, DATA_NAME).
- `llcBank.dwnLdCSV`: guard against missing BankStmts directory on fresh deploy.
- `wsCmd.py` line 296: removed U+00A0 non-breaking space that caused
  `SyntaxError` on PythonAnywhere Python 3.10.
- `addTracker()`: corrected config filename, fixed invalid list comprehension,
  added `sys_path` field.

### Changed
- `wsgi.py`: `LLC_NAME` / `LLC_YEAR` no longer constants — derived from
  `setup_paths.get_default()` so deployment works without code edits.
- `ledger/LLC.py`: `dataName` (file suffix) decoupled from `llcName` (folder).
- GL `stmtGeneralLedger` absorbed `ledgerGeneral`; `ledgerGeneral.py` deleted.
- IS default view changed to `PerMember`.

---

## [0.2.0-dev] — Unreleased (started 2026-04-16)

Scaffold + first round of v0.2 feature work.  See `ROADMAP_v0.2.md` for
the full list.

### Added
- `__version__` / `__version_info__` on the `uillc` package (`__init__.py`).
- `CHANGELOG.md` (this file).
- `ROADMAP_v0.2.md` — candidate work items and acceptance criteria for v0.2.
- **Logoff**: `/api/logoff` route in `llcMgmt` that quits the editor,
  plus a `⏻ Logoff` button and confirmation modal on the home page.
- **Accounts Payable** view (`llcPayables`):
  - New `uillc/llcPayables.py` (subclass of `llcRecordsView`).
  - New empty DB file `Accts/llcPayables_WBGroupLLC.json`.
  - Registered in `build_default_session` and `llcMgmt` under the
    Transactions group, uses the same `table_view.html` as `llcAssets`.
- **Accounts Receivable** view (`llcReceivables`):
  - New `uillc/llcReceivables.py` (subclass of `llcRecordsView`).
  - New empty DB file `Accts/llcReceivables_WBGroupLLC.json`.
  - Registered in `build_default_session` and `llcMgmt` under the
    Transactions group, uses the same `table_view.html` as `llcAssets`.
- Home page icons for the two new views (📤 A/P and 📥 A/R).

### Changed
- **General Ledger merge** now folds four sources instead of two:
  `llcAssets + llcExpRev + llcPayables + llcReceivables`.
  `llcReportEngine.getGLList` and `getGLListWithDups` convert Payables
  and Receivables to double-entry GL via `toDoubleEntry()` and merge
  them in via `mergeGL()` alongside the existing sources.
- `stmtGeneralLedger.meta()` now advertises all four source files.
- `llcMgmt`: `_canonical_name`, `_build_objects`, `_supports_record_views`,
  `VIEW_ORDER`, `VIEW_LABELS`, `VIEW_GROUPS` all extended for the new views.
- App title now includes the package version (e.g. `… (uillc 0.2.0-dev)`).

### Fixed
- `llcPayables` / `llcReceivables` no longer render the "Under
  Construction" page. `llcMgmt._build_objects` now auto-registers A/P and
  A/R `WkNode`s (pointing to the empty DB JSONs in `Accts/`) when the
  caller's `eSession` doesn't already include them, and `view_object`
  falls back to an empty `table_view.html` (standard record columns, zero
  rows) for any editable record view whose manager is still missing.

### DataModelGuide refactor — Phase 2 (stmt/ prototype)
Per `DataModel.md` § 2 (Constructed Financial Data Objects):

- **New `stmt/` package** for Constructed Financial Data Objects that
  subclass `ledger.ledgerObject` / `ledger.ledgerDB`.
  - `stmt/stmtObject.py` — base class enforcing the DataModelGuide contract:
    - Immutable once instantiated (attribute writes raise
      `StmtImmutableError`).
    - Every row carries `_lineNo` (1-based) and `_rowNm`; every column has a
      columnID (== its name).
    - Common API: `load()`, `save()`, `to_DF()`, `nSpaceMap()`, `get()`,
      `meta()`, `stats()`, `tblID()`, `columns()`, `rowNames()`.
    - `save()` writes a read-only JSON *snapshot cache* to
      `TOP/<dirAccounting>/Stmts/<tblID>_<objName>.json` (distinct from
      the live `Accts/` DB); the in-memory object stays immutable.
    - `nSpaceMap()` returns a flat `{(tblID, rowNm, colNm): value}` dict
      for cell-level addressing (matches the
      `stmtObj/tblID/rowNm/colNm` pattern from the guide).
  - `stmt/stmtDB.py` — marker subclass mirroring `ledger.ledgerDB`.
  - `stmt/__init__.py` — package exports.
- **Ported `stmtBalanceSheet` into `stmt/stmtBalanceSheet.py`** as the Phase 2
  prototype.  Accepts explicit `gl_records=` or `sources=` or defaults to
  loading from the `ledger.*` DB classes — no dependency on `eSession`.
  Aggregation pipeline is a bit-for-bit port of
  `uillc.llcReportEngine._buildBS_pandas` (with a pandas-free fallback).
- **Rewired `uillc/stmtBalanceSheet.py`** to be a pure UI wrapper: it pulls
  working-file GL records out of the session via `llcReportEngine` and
  passes them to `stmt.stmtBalanceSheet(gl_records=…)`.  Legacy interface
  (`load`, `last_check`, `stats`, `meta`, `list`, `save`, `save_object`,
  `reset_from_object`, `bind_session`) is preserved; each call constructs
  a fresh immutable stmt.  New accessors: `stmt()`, `nSpaceMap()`, `to_DF()`.
- `ledger/setup_paths.py` now lists `stmt` in its known-packages probe.

### DataModelGuide refactor — Phase 2 finalization (2026-04-19)

- **Consolidated `stmtObject` into `stmtDB`** and removed `stmt/stmtObject.py`.
  `stmtDB` now holds the full base-class implementation (immutability gate,
  `_lineNo`/`_rowNm` finalisation, flat `nSpaceMap()`, snapshot `save()` to
  `TOP/<dirAccounting>/Stmts/`) and subclasses **`ledger.ledgerDB`**
  directly so constructed statement tables inherit the ledger API
  (`toDF`, `load`, `save`, `FN`, `object_name`).
- **Relocated `stmtFinancialReport` from `ledger/` → `stmt/`.**  Updated
  consumers:
  - Python: `util/utilEditSession.py`, `uillc/llcIRSViewBase.py`,
    `irs/Form1065.py`, `irs/Form4562.py` (fallback chain simplified —
    ledger branch removed).
  - Notebooks: `Ledger_FinancialReport_WBGroupLLC_2025.ipynb`,
    `Ledger_General_WBGroupLLC_2025.ipynb`, `utilEditors.ipynb`.
  - Old `ledger/stmtFinancialReport.py` deleted.
- **Relocated `llcEquity` from `ledger/` → `stmt/`** (no external consumers
  needed updating).  Old `ledger/llcEquity.py` deleted.
- **Ported `stmtIncomeStmt` to `stmt/stmtIncomeStmt.py`** as an immutable
  `stmtDB` subclass, mirroring the stmtBalanceSheet pattern.  Accepts
  `gl_records=` / `sources=` / default-loader-from-ledger inputs; the IS
  aggregator is a bit-for-bit port of
  `uillc.llcReportEngine._buildIS_pandas` (pandas-free fallback included).
  `build_per_member(owners=…)` reproduces
  `llcReportEngine.buildISPerMember()`'s layout (data / income-subtotal /
  expense-subtotal / net-income / depreciation / net-income-depr /
  distribution rows, with per-owner allocation columns).
- **Rewired `uillc/stmtIncomeStmt.py`** to a pure UI wrapper that builds a
  fresh immutable `stmt.stmtIncomeStmt` on each `load()` using
  session-current GL records.  Legacy interface (`load`, `load_per_member`,
  `last_summary`, `stats`, `meta`, `list`, `save`, `save_object`,
  `reset_from_object`, `bind_session`) is preserved; new accessors
  `stmt()`, `nSpaceMap()`, `to_DF()` expose the underlying constructed
  object.
- **Smoke-tested Phase 2 finalization** — parity with
  `llcReportEngine._buildIS_pandas` (All / ByIncome / ByExpense),
  `StmtImmutableError` on attribute write post-construction,
  `build_per_member()` row-type coverage and per-owner column sums,
  `stmt.stmtFinancialReport` / `stmt.llcEquity` import successfully while
  `ledger.stmtFinancialReport` / `ledger.llcEquity` are gone, and the
  BalanceSheet regression still builds.

### DataModelGuide refactor — Phase 3 (2026-04-19)

Port the remaining constructed financial data objects onto the common
`stmtDB` base and rewire their `uillc/` counterparts as thin UI wrappers.

- **Ported `stmtOwnerEquity` to `stmt/stmtOwnerEquity.py`** as an immutable
  `stmtDB` subclass.  Accepts `asset_records=` / `owners=` / `net_income=` /
  `sources=` / default-loader-from-ledger inputs.  The aggregator is a
  bit-for-bit port of the legacy `uillc.stmtOwnerEquity.load()` pipeline
  (capital distribution by `propOwners`, grouped by `(owner, acct, acctSub)`,
  with per-member "Net Income Share (x.x%)" summary rows and a grand TOTAL
  row).  `_capital_dist` is re-implemented in-module so the stmt never
  depends on an `eSession` — the UI wrapper feeds it raw lists.
- **Ported `stmtPropertyEquity` to `stmt/stmtPropertyEquity.py`** as an
  immutable `stmtDB` subclass.  Accepts `asset_records=` / `owners=` /
  `sources=` / default-loader inputs.  Rows carry a `row_type` discriminator
  (`property-header` vs `data`); columns are the union of both row schemas
  so `nSpaceMap()` addressing is uniform.  View-by filtering (substring
  match on `propID` / `prop_identity`) is applied at construction time.
  `_default_rowNm` derives `<propID>` for headers and `<propID>.<tID>` for
  data rows.
- **Introduced `stmt/stmtGeneralLedger.py`** — immutable `stmtDB` subclass
  that wraps the merged, double-entry-expanded GL as a constructed
  statement table.  Accepts `gl_records=` (pre-merged with `Status` flags),
  `sources=` (the engine expands+merges), or defaults to loading from the
  four `ledger.*` DB classes.  View-by filtering (`All`, `By Dups`,
  `ByAsset`, `ByLiability`, `ByEquity`, `ByIncome`, `ByExpense`) happens at
  construction time — `By Dups` preserves the legacy `Dup1`, `Dup2` …
  relabelling.  Default row name is the GL `tID`.  `ledger.ledgerGeneral`
  remains unchanged as the service class (`toDoubleEntry` / `mergeGL` /
  `classify` helpers) that `stmt.stmtGeneralLedger` consumes.
- **Rewired `uillc/stmtOwnerEquity.py`**, **`uillc/stmtPropertyEquity.py`**,
  and **`uillc/stmtGeneralLedger.py`** to pure UI wrappers.  Each wrapper
  pulls working-file inputs from the session via `llcReportEngine` and
  forwards them into the corresponding `stmt.*` constructor on every
  `load()`.  Legacy interface (`load`, `stats`, `meta`, `list`, `save`,
  `save_object`, `reset_from_object`, `bind_session`) is preserved; new
  accessors `stmt()`, `nSpaceMap()`, `to_DF()`, `last_summary()` expose the
  underlying constructed object.
- **`stmt/__init__.py`** now re-exports `stmtOwnerEquity`,
  `stmtPropertyEquity`, and `stmtGeneralLedger`, and its `__all__` lists them.
- **Smoke-tested Phase 3** (`smoke_phase3.py`) — OE row parity + nSpaceMap
  shape; PE row parity + `view_by='P1'` filter + row-type counts; GL
  parity across `All` / `By Dups` / `ByAsset` / `ByIncome` + `Dup1` label
  + stats summary; `StmtImmutableError` on attribute write for all three
  classes; `stmt` package exposes Phase 3 classes; BalanceSheet and
  IncomeStmt regressions still build.  All six blocks PASS.  `save()`
  writes read-only snapshots to `TOP/<dirAccounting>/Stmts/OwnerEquity_*`,
  `Stmts/PropertyEquity_*`, and `Stmts/GeneralLedger_*`.

### DataModelGuide refactor — Phase 4 (2026-04-19)
Per `DataModel.md` § 3 (View Services): the `uillc/` view layer is now a
stripped-down `ui/` package, with `uillc/` retained as a compatibility
shim so legacy `from uillc.X import Y` imports keep working unchanged.

- **New `ui/` package** — full structural mirror of `uillc/`
  (26 modules + `templates/`).  Internal imports rewritten
  mechanically: every `from uillc.X import …` / `import uillc.X` now
  resolves within `ui.*`.  Flask templates continue to resolve from
  `ui/templates/` via `Path(__file__).resolve().parent / "templates"`
  in `ui.llcMgmt`.
- **`ui.__init__.py`** — new package docstring anchors Phase 4 in
  DataModelGuide § 3: *"View Services hold no data
  construction/wrangling: all stmt/DB/IRS data objects are constructed
  upstream in `stmt/`, `ledger/`, or `irs/`; modules here simply adapt
  that data for the Flask app."*  Re-exports the same eleven wrapper
  classes the legacy `uillc.__init__.py` did, plus lazy-import of
  `llcMgmt` (Flask optional).
- **`ui.llcReportEngine` stripped to a session adapter.**
  Removed: `_buildBS_pandas`, `_buildBS_fallback`, `_buildIS_pandas`,
  `_buildIS_fallback`, `buildISPerMember`.
  `buildBS(view_by)` now builds a fresh immutable
  `stmt.stmtBalanceSheet(llc, view_by=…, gl_records=self.getGLList())`
  and returns `(rows, last_check())`; `buildIS(view_by)` delegates to
  `stmt.stmtIncomeStmt` the same way (passing `owners=…` so per-member
  allocation is available via `build_per_member()`).
  Kept helpers: `getGLList`, `getGLListWithDups`, `toDF`, `_load_source`,
  `coa_lookup`, `coa_all`, `_find_owners_path`, `load_owners`,
  `_owner_first_name`, `_rent_income_total`, `_interest_expense_total`,
  `_contributions_by_owner`, `_capital_end_year_by_owner`,
  `owner_pl_allocation` (the last now delegates to the thinner
  `buildIS`).
- **`ui.llcMgmt`** — renamed the local title-bar variable
  `_uillc_version` → `_ui_version`; user-visible footer text changed from
  `(uillc …)` to `(ui …)` to match the new package identity.
- **`uillc/` is now a compatibility shim.**  Every `uillc/<X>.py` is
  replaced with a one-screen re-export:
  ```python
  from ui.<X> import *       # noqa: F401,F403
  from ui import <X> as _ui_mod
  try:
      __all__ = list(_ui_mod.__all__)
  except AttributeError:
      __all__ = [n for n in dir(_ui_mod) if not n.startswith("_")]
  ```
  `uillc/__init__.py` also now mirrors `ui/__init__.py`'s re-exports
  (via `from ui.<X> import <X>`), so `from uillc import llcAssets`,
  `import uillc.llcReportEngine as e`, `from uillc.llcForm1065 import
  llcForm1065`, etc. all resolve to exactly the same class/function
  objects as their `ui.*` counterparts.

#### Phase 4 smoke-test (`smoke_phase4.py`) — all PASS.
Five blocks:
  G. ui wrapper surface — every `ui.<X>` imports, exposes `load()`.
  H. uillc → ui shim identity — class-object identity for every
     wrapper, engine, session, IRS form, and package-level re-export
     (26 modules × all public symbols exported by the ui/ module,
     filtered to those whose `__module__` is `ui.<X>`).
  I. engine adapter shape — removed methods absent;
     `buildBS`/`buildIS` source references `_stmtBalanceSheet` /
     `_stmtIncomeStmt`; kept helpers still present.
  J. Phase 3 regression — stmt OE/PE/GL still build on fake inputs.
  K. Phase 2 regression — stmt BS/IS still build.

#### Consumer impact
- `from uillc.X import Y` — still works.  Same class object as
  `from ui.X import Y`.
- New code should import from `ui` directly.
- Any external module that reaches into
  `uillc.llcReportEngine._buildBS_pandas` / `._buildIS_pandas` /
  `.buildISPerMember` WILL break; there were no such call-sites in the
  Notebooks tree.  Per-member IS rendering goes through
  `stmt.stmtIncomeStmt.build_per_member()` / `ui.stmtIncomeStmt.load_per_member()`.

---

## [0.1.0] — Baseline (pre-2026-04-16)

Retroactive tag for the working Flask editor shipped before the v0.2 cycle.

### Views shipped in v0.1
- Transactions: `llcAssets`, `llcExpRev`, `stmtGeneralLedger`, `llcBank`
- Financial Statements: `stmtBalanceSheet`, `stmtIncomeStmt`, `stmtOwnerEquity`,
  `stmtPropertyEquity`
- IRS Tax Aids: `llcForm1065`, `llcFormK1`, `llcFormSchedL`, `llcFormSchedM1`,
  `llcFormSchedM2`

### Infrastructure in v0.1
- Flask app in `llcMgmt.py` with per-view templates under `templates/`.
- Merge-save logic so filtered-view saves don't drop unseen records.
- COA lookup API (`/api/coa/get`, `/api/coa/all`).
- Bank CSV upload endpoint (`/api/llcBank/upload_csv`).
- Notebook-mode runner (`run(notebook=True)`).
