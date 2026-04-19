# uillc — LLC Editor Changelog

All notable changes to the `uillc` LLC editor package are tracked here.
This project loosely follows [Keep a Changelog](https://keepachangelog.com/)
and [Semantic Versioning](https://semver.org/).

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
- `llcGeneralLedger.meta()` now advertises all four source files.
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

---

## [0.1.0] — Baseline (pre-2026-04-16)

Retroactive tag for the working Flask editor shipped before the v0.2 cycle.

### Views shipped in v0.1
- Transactions: `llcAssets`, `llcExpRev`, `llcGeneralLedger`, `llcBank`
- Financial Statements: `llcBalanceSheet`, `llcIncomeStmt`, `llcOwnerEquity`,
  `llcPropertyEquity`
- IRS Tax Aids: `llcForm1065`, `llcFormK1`, `llcFormSchedL`, `llcFormSchedM1`,
  `llcFormSchedM2`

### Infrastructure in v0.1
- Flask app in `llcMgmt.py` with per-view templates under `templates/`.
- Merge-save logic so filtered-view saves don't drop unseen records.
- COA lookup API (`/api/coa/get`, `/api/coa/all`).
- Bank CSV upload endpoint (`/api/llcBank/upload_csv`).
- Notebook-mode runner (`run(notebook=True)`).
