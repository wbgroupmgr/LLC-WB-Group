# LLC Restructure Plans and Design 

- LLC-WBGroup - Business Files for LLC
- pyMultiTaskWS - Web Server
- llcRentalTracker - Property Rental LLC Services

*Written 2026-05-18. Starting point for the next work session.*

---
## 1. LLC-WBGroup repo

### 1.1 Docs
Create `docs/` with:
- `README.md` — explain repo structure (books/, Assets/, pages/, Notebooks/)
- `SOP-PropertyRental.md` — standard operating procedures for rental LLC:
  - Monthly: collect rent, record expenses, reconcile bank
  - Quarterly: review P&L, check depreciation schedule
  - Year-end: close books, generate financial statements, send K-1s to partners
  - Year-start: open new books/, set up new Accts/ directory, update profile

### 1.2 New Year Setup
Changes needed when starting a new fiscal year (e.g., 2025 → 2026):
1. Create `books/2026/Accts/` directory structure
2. Copy empty template JSONs (llcAssets, llcExpRev, llcPayables, llcReceivables)
3. Copy `llcProfile_WBGroupLLC.json` to new Accts/ (update year)
4. Run `wsCmd.py --newBus ~/llc/LLC-WBGroup --year 2026`
5. Update `~/.llcRentalTracker/config.json` default to new year
6. Set up `books/2026/BankStmts/` directory for CSV drops

### 1.3 Bank reconciliation setup
- Create `books/2026/BankStmts/` before first CSV upload
- Monthly task: download Wells Fargo CSV, drop in BankStmts/, reconcile in app

---


## 2. pyMultiTaskWS repo

**Update `docs/design_*.md`** — especially provisioning:
- Add a "Setup & Provisioning" section covering the exact sequence:
  1. Clone pyMultiTaskWS to PA
  2. Configure `/var/www/wbgroup_pythonanywhere_com_wsgi.py` (1 and only 1 — manual step)
  3. Run MultiTaskWS `wsCmd.py --setup` to generate `~/.MultiTaskWS/MultiTaskWS_config.json`
     (this is where `WEB_SECRET_KEY` and `WEB_GPG_PASSPHRASE` are generated)
  4. For each tracker app: clone repo, run tracker's `wsCmd.py --setup`
     (registers stanza in MultiTaskWS config, writes profile with passphrase)
  5. Reload PA web app
- Add section: "The 1 WSGI file rule" — MultiTaskWS is the sole WSGI entry point.
  PA Web tab points to `/var/www/wbgroup_pythonanywhere_com_wsgi.py` only.
  Tracker apps do NOT have their own WSGI files active on PA.

**Create `docs/design_future.md`** — ideas to improve multi-tracker platform:
- Health check endpoint per tracker (`/rentalTracker/_health`) polled by MultiTaskWS admin
- Centralized logging collector (all tracker logs → single rotating file)
- Auto-reload on git pull (webhook trigger or cron)
- Tracker config hot-reload without PA web app reload
- Per-tracker `rentalTracker.APP_GPG_PASSPHRASE` in MultiTaskWS config
  (currently falls back to top-level `WEB_GPG_PASSPHRASE`)
- Shared session store (Redis) so tracker sessions survive worker restarts
- MultiTaskWS admin dashboard showing tracker status, last deploy, log tail

---

## 3. llcRentalTracker repo

### 3.1 Notebooks — bring back from LLC-WBGroup
Notebooks found in `LLC-WBGroup` that belong in `llcRentalTracker`:
- `pages/AccountingData/2025/2025 IRS Filing Notes.ipynb` — tax filing notes
- `docs/irs/displayDoc.ipynb` — already in llcRentalTracker

Business-analysis notebooks (stay in LLC-WBGroup):
- `Assets/16ElConejo-2026/2026-Eval-16ElConejo.ipynb`
- `Assets/805HighMesa/805HighMesa.ipynb`
- `pages/Taxes/2026/2025-CostSegStudy.ipynb`

### 3.2 Help button — implement `design_help_button.md`
- Flask route `/help/<doc_name>`
- Slide-in drawer in `base.html`
- Per-view `help_doc=` context var
- Feedback mailto link to wbgroupmgr@gmail.com

### 3.3 Docs restructure — per audit
Delete redundant files:
- `LLC_AccountingWorkflow.md` (dup of `design_LLC_AccountingWorkflow.md`)
- `LLC_AccountingDesign.md` (dup of `design_LLC_App-Accounting.md`)
- `LLC_DataModel.md` (incomplete)
- `PLAN_SchK1_v0.3.md` (superseded)
- `Readme_aiCowork.md` (move content to CLAUDE.md)

Restructure into 5 sections (see `docs/` audit for full proposed tree).

Create missing docs:
- `docs/03-Setup-Business-Repo/Setup-Guide.md`
- `docs/04-Fiscal-Year-Start-End/Fiscal-Year-Procedures.md`
- `docs/05-Operations-SOP/Troubleshooting.md`

### 3.4 Code cleanup (SW design review)
Priority areas identified:
- `llcMgmt.py` — over 900 lines; split view routing into per-view files
- `wsCmd.py` — `_write_profile_config` generates its own `LLC_SECRET_KEY`
  (conflicts with MultiTaskWS owning that key — should be removed)
- `setup_paths.py` — fallback to legacy per-file configs is complex; simplify
  once all deployments use unified config
- Remove `uillc/` shim once all imports are from `ui/` directly
- `llcLogin_auth.py` `make_auth_routes` — consider Flask Blueprint

---


## 4. Local folder `LLC-WB-Group.v05`

This is the **dead shim** — the pre-split monorepo. Confirm:
- No code here that isn't already in `llcRentalTracker` or `LLC-WBGroup`
- The `pages/AccountingData/Notebooks/` Jupyter notebooks — check if any
  are development/exploration notebooks that belong in `llcRentalTracker`
- After confirming, archive the folder (don't delete — tax records may reference it)

---

## Lessons Learned — Session 2026-06-02

### Operations / Deployment
- **PA = master host, local = pull-only**: PythonAnywhere is the sole host that pushes to `LLC-WBGroup`. Local machines and any other hosts pull only and never push data files. This enforces a single authoritative `pw.json.gpg` encrypted with a shared `LLC_GPG_PASSPHRASE` that works everywhere.
- **`keys.json.gpg` as secrets bootstrap**: Per-host setup: `~/.llcRentalTracker/config.json` holds MASTER passphrase → `keys.json.gpg` decrypts to `{LLC_GPG_PASSPHRASE, LLC_SECRET_KEY}` → injected as env vars at app startup. Only the MASTER passphrase is host-specific; all other secrets are repo-committed (encrypted) and shared.
- **`wsCmd --newBus` for new LLC provisioning**: Bootstrap sequence for a new business: `--newBus <LLC-WBGroup-path>` creates repo skeleton and JSONs, then `--setup` seeds `pw.json.gpg` with default user and writes `MultiTaskWS_Config` stanza to `llcProfile`. Must run on PA first so it commits the canonical `pw.json.gpg`.

### Software Engineering
- **Single DB across years requires explicit year scoping at query time**: Moving `Accts/` out of year subdirectories (Phase 3) means every query that was previously year-isolated by directory is now year-filtered by `dt` prefix in `llcReportEngine` and `utilWorkingDB`. All new query paths must pass `year` as a filter parameter, not rely on file location.
- **New Year setup checklist** (updated for Phase 3 single-DB): No need to copy Accts/ JSONs to a new year directory. Steps are: (1) create `books/<year>/BankStmts/` and `books/<year>/YE_Tax_Records/Forms_IRS/`, (2) update `llcProfile` fiscal year, (3) run `wsCmd --newYear <year>` (future: not yet implemented). The single `Accts/` DB accumulates all years.

---

## Priority Order for Next Session

1. **Bookkeeping first** — reconcile 2025 bank statements, enter transactions
2. **New Year 2026 setup** — run `--newBus` for 2026, test app loads
3. **Help button** — small, high-value for partners using the app
4. **LLC-WBGroup SOP doc** — write while doing bookkeeping (capture the steps)
5. **pyMultiTaskWS docs** — lower urgency, no users besides us
6. **Docs restructure** — can be done incrementally
7. **Code cleanup** — after books are balanced, not before
