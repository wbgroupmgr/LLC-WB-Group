# uillc — LLC Editor Changelog

All notable changes to the `uillc` LLC editor package are tracked here.
This project loosely follows [Keep a Changelog](https://keepachangelog.com/)
and [Semantic Versioning](https://semver.org/).

---

## [2.2.2] — 2026-06-22  **Issue #41 — Soft-delete audit trail for Table Action Delete**

### Changed
- **`ui/llcMgmt.py`** — both delete paths (single `cmd="delete"` and batch
  `sub="delete"` within `cmd="batch"`) now soft-delete instead of physically
  removing rows. A deleted record has `amt` zeroed and `desc` prefixed with
  `"RECORD DELETED <YYYY-MM-DD>; amt zero'd out. "`. The row is preserved in
  the JSON DB for full audit trail.
- Added `import datetime` to top-level imports.

---

## [2.2.1] — 2026-06-21  **Bug fixes: Income.Summary restore + notebook baseline assertions**

### Fixed
- **BUS `llcAssets_WBGroupLLC.json`** — restored `Acct.Equity.Income.Summary →
  Acct.Equity.Earnings.PnL` (Debit 667.55, dt=2025.12.31) that was removed by
  commit `83373cf fix(#39)`. Without it:
  - GL total dropped 667.55 each side (672,945.93 → 672,278.38)
  - `Acct.Equity.Earnings.PnL` had a net Debit of 667.55 (unbalanced equity)
  - BS trial balance diverged from PA reference (669,198.89/668,531.34/667.55)
  The entry closes the intermediate YE closing leg: Income.Summary → PnL.
  The 3 per-member NI distribution entries (PnL → Owner.Capital.Funds) are
  retained — both legs are required for correct GAAP double-entry close.
- **`Notebooks/bankIngestPreview.ipynb` B2** — now loads only the YE statement
  (`WBGroupLLC_WF_20251231.csv`) instead of all 3 CSVs in the directory. The
  YE file supersedes the earlier partial exports (20251211, 20251216).

### Added
- **`Notebooks/bankIngestPreview.ipynb` B6** — 2025 full-GL baseline assertion
  cell. Asserts against PA-verified reference values:
  - GL: 672,945.93 / 672,945.93 / 0.00
  - IS: total_income=4400, net_rental=667.55, subtotal_rental_expense=3732.45,
        depreciation=1903.13, net_rental_before_depr=2570.68
  - BS (balance-sheet account trial balance): D=669,198.89 / C=668,531.34 / B=667.55

---

## [2.2.0] — 2026-06-21  **BankToBook P0 — Schema Migration + Notebook Baseline**

### Added
- **`ledger/bankAgent/` package** — new module directory for the BankToBook pipeline
  (issue #40). Includes `__init__.py` and `migrate_exprev_schema.py` (one-time
  migration runner).
- **`Notebooks/bankIngestPreview.ipynb`** — phased regression harness. B1–B5 P0
  baseline cells: setup → parse 2025 WF CSVs → load llcExpRev → double-entry GL
  expansion → trial balance (verified = 0: 440,577.19 debits = credits).
  Placeholder sections for P1–P4 phases added.

### Changed
- **`llcExpRev_WBGroupLLC.json` (BUS repo)** — schema migration: flat list →
  `{"records":[...],"LogHistory":[]}`. All 53 existing records: `refDB: "llcBank"`
  → `"llcBank-Manual"` (manually entered, not imported by BankAgent).
- **`ledger/llcExpRev.py`** — new overrides: `load()` unwraps new dict format;
  `save()` preserves `LogHistory`; `log_history()` accessor; `_normalize_for_temp()`
  hook ensures working-file temp stays a flat list (backward-compatible).
- **`util/utilWorkingDB.py`** — `loadTemp()` and `_refresh_from_real()` call
  `_normalize_for_temp()` hook when present on `self.o`, so the temp file always
  receives a flat list regardless of real-file format.
- **`ui/llcRecordsView.savePayload()`** — real-file write now delegates to
  `self.wk.o.save(payload)` so schema-aware objects control serialization
  (previously wrote flat list directly via `json.dump`).

---

## [2.1.0] — 2026-06-21  **BankToBook Design + BUS Repo Migration**

### Added
- **BankToBook design doc v0.5** (`docs/BUS/design_BUS_01.5_BankToBook.md`) —
  Full two-agent architecture: **BankAgent** (outer orchestrator — two-phase
  preview/commit pipeline, BkCIPGuard IRC §263(a) hard override, 3-scope
  dedup, BkAuditNotifier post-commit) + **IngestAgent** (per-record bookkeeper
  — BkVendorKB regex rules, BkTxnTypeDetector Tier 2 overrides, `classify()`,
  `learn()`). Includes end-user scenario (Home → `/view/bank_reconcile`),
  ClassifiedRow schema with `aType`/`Ledger` fields, module structure, and
  phased regression harness (P0 B1–B5 notebook baseline + P1–P4 per-phase
  COMPAT + new-capability cells).
- **GitHub issue #40** — clean replacement for issue #20: "feat(BankToBook):
  implement BankAgent + IngestAgent two-phase ingestion pipeline" with concise
  goals, requirements checklist (P0–P4), and action plan table (~6.5 days).
  Issue #20 commented with reference to #40.

### Infrastructure (BUS repo)
- **BUS repo migration** (issue #5) — `Assets/` → `pages/Assets/` (46 files);
  `pages/AccountingData/` retired (3 tracked files archived to `books/2025/`;
  48 `.bookNS_backups/` JSONs removed). No APP dependency — `ACCT_DATA_DIR`
  resolves to `books/`.
- **PA gitignore fix** — `*_session_state.json` and `*_diagnose_state.json`
  untracked from BUS (`git rm --cached`) and added to `.gitignore`.  Root
  cause: files were committed before gitignore rules existed; once tracked,
  gitignore does not untrack. Fixed PA pull failures.
- **BUS `release/v1.2`** — checkpoint branch from `origin/main` after old-repo
  migration and 2025 YE machinery landing.

---

## [2.0.0] — 2026-06-15  **PA Migration + Gmail SMTP Email Service**

### Fixed
- **IS View Print PDF** — `is_member_view.html` and `is_property_view.html` print
  buttons were calling `window.print()` (prints the whole browser page). Changed
  to `window.open(_scriptRoot + '/api/stmtIncomeStmt/print_pdf', '_blank')`.
- **Info messages disappearing on reload** — `tax_prep.html` reload-based actions
  (`runTaxAgent`, `assemblePackage`, `generateYEFR`, `generateLetter`, `saveK1`)
  cleared the DOM notification before the user could read it. Added `notifyQueued()`
  pattern: saves to `localStorage('tp_pending_msg')` before reload; `DOMContentLoaded`
  handler restores it on the next page load.
- **`_scriptRoot` missing in `tax_prep.html`** — all 8 fetch/href calls used bare
  `/api/...` paths; on PA (mounted at `/rentalTracker`) these 404'd and returned
  an HTML error page, causing `SyntaxError: Unexpected token '<'`. Added
  `const _scriptRoot = {{ request.script_root | tojson }}` and prefixed all calls.
- **Sch K-1 letter description** — shortened from "Income, Deduction, Credits" to
  `Member N (oID) — Sch K-1` in `LLCTaxAgent.py` line 927.

### PA Migration (issue #31)
- **`wsCmd.py --sync`** — rewritten to handle PA fresh-clone BUS: detects unrelated
  histories (`git merge-base` exit code) and uses `reset --hard` instead of rebase.
  Also clears stale `.pyc`/`__pycache__` after LLC reset and removes stale
  `.agent_work/*.json` files.
- **`_AGENT_REGISTRY` empty → 404 "Unknown form key"** — added `_AGENT_REGISTRY_ERR`
  capture and `_registry_404()` returning 503 with full traceback in JSON body.
  Added `/api/debug/status` diagnostic endpoint (registry state, bus_repo, accts_dir,
  forms_dir, accts_exists, forms_exists).
- **Python ≤3.11 f-string SyntaxError** — `FormSchK1Agent.py` line 1687 used a
  backslash escape inside an f-string `{}` expression (illegal before Python 3.12).
  Fixed by hoisting `_mgr_note` variable before the f-string.
- **HOME FS empty (404 on `/api/home/snapshot`)** — `home.html` had no `_scriptRoot`
  and used bare `/api/...` fetch paths. Added `_scriptRoot` and prefixed all three
  API calls (`/api/home/snapshot`, `/api/session/new`, redirect to `/`).
- **Wrong BUS repo at PA** — PA's `LLC-WBGroup/` folder was the APP repo
  (contained `CLAUDE.md`, `DiagnoseBooks.ipynb`). Fixed by `rm -rf LLC-WBGroup &&
  git clone git@github.com:wbgroupmgr/LLC-WBGroup.git`.

### Added
- **Server-side SMTP email via Gmail** (issue #33) — `notify_reviewer_email` route
  now sends directly via `smtplib` (port 587 STARTTLS) when `SMTP_APP_PASSWORD` is
  set in the environment. Falls back to `mailto:` URL when not configured (local dev
  behavior unchanged). Credentials stored in `wsgi.py` on PA (`SMTP_FROM`,
  `SMTP_APP_PASSWORD`).
- **Multi-recipient Notify Reviewer** — replaced bare `prompt()` with a modal dialog
  collecting: (1) comma-separated recipient email list, (2) "Attach IRS Package Files"
  checkbox. When checked, attaches all PDFs from `IRS_Submission_{year}/` as MIME
  attachments. Server accepts list, sends one email to all recipients with CC to
  `SMTP_FROM`.
- **`tests/testsmtp.py`** — standalone SMTP connectivity test for PA setup.
  Prompts for App Password and tests `smtp.gmail.com:587` login. Documents
  App Password creation steps in docstring.

### Technical Notes
- PA plan must support outbound port 587 (Hacker plan or above); port 465 is blocked.
- App Password must be created in incognito with only `wbgroupmgr@gmail.com` active;
  creating while another Google account is active silently binds it to the wrong account.
- `wsgi.py` (PA local file, not in git) is the correct place for `SMTP_APP_PASSWORD`;
  the PA Web tab "Environment variables" section does not inject into the WSGI process.

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

## [1.5.0] — 2026-06-14  **K-1 Header Field Fix + Unified Action Menu**

### Fixed
- **K-1 f12/f13 wrong field mapping** — The 2024+ IRS Schedule K-1 PDF has no
  AcroForm fields for Partnership CSZ (Line B city/state/zip) or IRS Service
  Center (Line C).  The namespace incorrectly assigned `K1_PshipCSZ` and
  `K1_IRSCtr` to f12/f13, which are physically Part II partner fields (Partner
  SSN Line E, Partner Name Line F).  Fixed: `K1_PshipCSZ` and `K1_IRSCtr`
  removed from `_FILL_MAP_K1`; f12 → `K1_PtEIN`, f13 → `K1_PtName`.
  `irsRefAgent.py` SECTIONS updated: F012/F013 moved from
  `_SCHK1_PARTNERSHIPINFO_FIDS` to `_SCHK1_PARTNERCAPITAL_FIDS`.
  `bookNS_Profile.json` Sch_K1 section: stale F012/F013 profile entries removed.
- **K-1 f13 merged identity block** — Added `name_addr_info` derived key in
  `partner_src` (name + address + status via `"\n".join(filter(None, [...]))`).
  `K1_PtName` FILL_MAP path changed to `name_addr_info` so Line F fills the
  full partner identity block, not just the name.
- **K-1 f19 forced blank** — f19 has no valid AcroForm meaning in this PDF
  revision.  Cleared logicalKey in `Sch_K1_namespace.json`; removed `K1_PtAddr`
  from `_FILL_MAP_K1` entirely.  FILL.pdf no longer shows partner address at f19.
- **Sections tab empty on startup / tab switch** — extracted `sectionsRefresh()`
  helper in `irs_form_view.html`.  Called from: `leftTabSwitch` (Sections tab),
  `k1MemberChanged` (member dropdown), and DOMContentLoaded (`{%- else %}`
  non-generate branch).  All three paths now re-fetch agent status consistently.

### Added
- **Action Menu** — replaced individual header buttons with a `<details>/<summary>`
  dropdown (⚡ Actions ▾).  Items: Generate Form, Download, Print Form,
  Print Summary, Aid — Book→IRS Map, CPA Review Fields, Logoff.
  `printForm()`: tries `iframe.contentWindow.print()`, falls back to new tab.
  `printSummary()`: lazy-fetches Diagnosis pane if not yet loaded; opens a
  print-optimised popup combining both Sections accordion and Diagnosis table.
- **`Sch_K1_namespace.json` force-tracked in BUS repo** — manually-maintained
  logicalKey assignments not purely auto-generated; force-added via `git add -f`
  to survive `*_namespace.json` gitignore.

### Technical Notes
- `_FILL_MAP_K1` in `Sch_K1.py`: keys `K1_PshipCSZ`, `K1_IRSCtr`, `K1_PtAddr`
  removed.  `K1_PtName.path` changed to `name_addr_info`.  `K1_PtEIN.path`
  unchanged (`ein`).
- `partner_src` dict in `_buildFillDict`: new `"name_addr_info"` entry added
  after `"address"`.
- f19 (`f1_11`), f20 (`f1_12`), f21 (`f1_13`) logicalKeys cleared in namespace.
- `sectionsRefresh()` pattern: single helper calling `agentUrl(_AGENT_STATUS_URL)`
  and delegating to `renderSections()`/`renderEmpty()`; stale-badge logic included.

---

## [1.4.0] — 2026-06-14  **SchK1 Box L Capital Account + Form 8825 Forensic Clusters**

### Added
- **Form 8825 forensic cluster reporting (F8NI-R05a…d)** — one finding per
  suspicious transaction cluster instead of a single bundled list.  Each cluster
  gets its own rule ID (`F8NI-R05a`, `F8NI-R05b`, …), its own resolve button, and
  its own description.  `_run_audit()` now handles list-returning rules via
  `issues.extend()`.  False-positive fix: `has_return` alone (same property
  return-and-rebuy) no longer triggers; only `multi_prop` or `duplicate` fires.
- **`gl_contributions(llc, oID)` returns `(attributed, untagged)` tuple** — null
  `propOwners` entries are NOT silently allocated by ownership %; surfaced as
  separate WARN `SK1B-R07u` so the operator can tag the entry explicitly.
- **SK1B-R07u — untagged capital contributions rule** — new
  `_rule_capital_unattributed` in `AgentSchK1_PartnerCapital`.  Fires when any
  `Capital.Funds` credit rows have null/empty `propOwners`; names the managing
  member as the almost-certain contributor.  Per-member display; same warning
  shown on all three K-1s since the GL gap affects all of them.
- **docs/BUS/design_BUS_03.01_Auditing_Forensics.md** — new design doc capturing
  three-layer control architecture: Layer 1 (GL entry prevention, v1.5), Layer 2
  (monthly reconciliation, v1.4), Layer 3 (continuous monitoring agent, v2.x).
  Opened GitHub issue #27.

### Fixed
- **SchK1 Box L capital account — wrong source** (issue #23 Problem 1) —
  `_gl_load_all()` misses `Capital.Funds` when it appears as the CONTRA account
  (e.g., DR Fixed.Asset / CR Capital.Funds for the $219K property contribution).
  Switched all capital GL reads to `stmtGL(llc).load()` (full double-entry
  expansion) so contra-side credits are visible.
- **Sch_K1._buildFillDict tuple leak** (issue #23) — `gl_contributions()` changed
  to return `(attributed, untagged)` but `_buildFillDict` passed the tuple directly
  to `_fmt()`, producing `"(225829.28, 0.0)"` in the PDF fill.  Fixed: unpack at
  call site (`partner_contrib, _ = gl_contributions(...)`).
- **SK1B-R07 display — one clean number per member** (issue #23) — removed
  "(tagged)" label when `untagged == 0`.  Passive members ($0 attributed, $0
  untagged) now show INFO "Expected for passive member" instead of WARN data gap.
- **SK1C-R02 misleading WARN** (issue #23) — changed to INFO when books have the
  Box 2 value.  New message: "✓ K-1 for {nm}: Box 2 = ${expected:,.2f}. Source:
  IS.net_rental × pct."
- **SK1C-R20 NIIT threshold vague** (issue #23) — added explicit thresholds:
  $200,000 (single/HOH) or $250,000 (married filing jointly).

### Technical Notes
- `_gl_capital_rows(llc)` — new module-level helper in `FormSchK1Agent.py`;
  reads `stmtGL(llc).load()` and filters to three tracked equity accounts
  (`Capital.Funds`, `Capital.Reinvestment`, `Capital.Dist`).
- `gl_ending_capital(llc, oID, owner_pct, net_rental)` — calls
  `gl_contributions()` and unpacks the tuple; `gl_distributions()` likewise uses
  `stmtGL` to find both debit-side `Capital.Funds` and credit-side `Capital.Dist`.
- IRS K-1 $0 field convention: `_fmt(0.0)` returns `""` (leave blank, not "0") —
  already correct in `irsForm._fmt`.  Members 2 & 3 contributions fill is blank.

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
