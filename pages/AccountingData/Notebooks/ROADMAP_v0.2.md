# LLC Editor — v0.2 Roadmap

Target: cut v0.2.0 from the current `main` once the items below are done
and the editor still loads for `W&B Group, LLC` with the 2025 and 2026
accounting folders.

## Goals

1. Make the editor safer to use (less chance of accidental data loss).
2. Make reports easier to reconcile (closer to the IRS forms the user files).
3. Make the package easier to version, test, and re-deploy.

## Candidate work items

### Infrastructure
- [x] Add `__version__` to the `uillc` package.
- [x] Add `CHANGELOG.md`.
- [x] Add this roadmap file.
- [ ] Show the package version in the Flask home page header/footer.
- [ ] Add a small `tests/` folder with smoke tests for each view's `load()`
      and `stats()` on a fixture session.
- [ ] Add a `make run` / notebook snippet doc so the editor can be started
      with one line against the current YEAR.

### Data safety
- [ ] Before `save()`, write the previous working file to a timestamped
      `.bak` in the same directory.
- [ ] Confirm-dialog on destructive actions in editable views
      (delete row, "save from empty view").
- [ ] Log every `save`/`save_object`/`delete` to an append-only
      `uillc_audit.log` next to the working files.

### Views & reports
- [ ] `stmtIncomeStmt` PerMember: show owner % share alongside the absolute
      numbers.
- [ ] `stmtBalanceSheet`: expose `last_check()` result (accounting-equation
      delta) directly on the view, with a red banner when non-zero.
- [ ] `llcFormK1`: one PDF export per partner that mirrors the live table.
- [ ] `stmtPropertyEquity`: add "since acquisition" and "YTD" columns.

### Bank reconciliation
- [ ] Persist the last uploaded CSV per bank account so a restart doesn't
      lose the staged transactions.
- [ ] Highlight duplicates detected by `llcBankView` instead of silently
      dropping them.

### Developer experience
- [ ] Split `llcMgmt.py` route handlers into their own module once it
      exceeds ~1000 lines — it is currently ~740.
- [ ] Typed `TypedDict` for row shapes used across views, shared via
      `uillc/util/types.py`.

## Out of scope for v0.2
- Multi-LLC support (one editor instance still = one LLC).
- Authentication / multi-user editing.
- Migrating off Flask.

## Release checklist
- [ ] All "Infrastructure" + "Data safety" items above done.
- [ ] `CHANGELOG.md` [0.2.0-dev] section renamed to [0.2.0] with date.
- [ ] `__version__` bumped from `0.2.0-dev` → `0.2.0` in `uillc/__init__.py`.
- [ ] Smoke test: `llcMgmt(eSession).run(notebook=True)` loads every view
      for the 2026 session without exception.
