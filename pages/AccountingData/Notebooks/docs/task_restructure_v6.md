# Restructure Plan v6 — LLC-WB-Group → Business Repo + llcRentalTracker

**Date:** 2026-05-17 (updated)
**Session goal:** Split monolithic LLC-WB-Group repo into a business data repo and a generic rental accounting web app / MCP server.

---

## 1. Goals

| # | Goal |
|---|------|
| 1 | Separate **business files** from **application code** into two independent repos |
| 2 | Make the app (`llcRentalTracker`) configurable for any LLC business folder — not hardwired to WB Group |
| 3 | Design llcRentalTracker as both a **Flask web app** and an **MCP server** specializing in rental property management |
| 4 | Integrate both repos into the **PA MultiTaskWS** platform |

---

## 2. Proposed Repository Layout After Split

### 2.1 Business Repo — `LLC-WBGroup`

**Destination:** `~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup/`

**Key structural changes from current LLC-WB-Group:**
- `books/` is a NEW top-level folder holding all fiscal-year accounting data — `pages/` is NOT renamed, it stays for reference/guide content (Operations, IRSGuide, RentalMgmt, Taxes)
- `Accts/` moves under the fiscal year: `books/<YEAR>/Accts/` — accounting records are per fiscal period
- `Forms/` consolidates IRS PDFs + namespace JSON files into one year-level folder
- `Receipts/` and `Expenses/` move inside the year folder (they are year-specific)
- `Working/` replaces `FinancialTemplates` as the scratch/draft directory
- `.bookNS_backups/` moves outside git structure (not committed)

```
LLC-WBGroup/
├── llcProfile_WBGroupLLC.json        # Root entity + IRS form metadata
├── Assets/                           # Property acquisition docs (16ElConejo, 805HighMesa, RVCamper)
├── LLC Doc Records/                  # Articles, operating agreement, IRS letter
├── docs/                             # Release notes, milestone docs
├── pages/                            # Guide/reference content: Operations, IRSGuide, RentalMgmt, Taxes
├── Notebooks/                        # Legacy Jupyter (root-level, kept in business repo)
├── index.md
├── requirements.txt
└── books/                            # Fiscal books — year-specific accounting data
    ├── 2025/
    │   ├── Accts/                    # ← MOVED from AccountingData/Accts/ (per-year ledger DBs)
    │   │   ├── llcProfile_WBGroupLLC.json
    │   │   ├── ChartOfAccounts_WBGroupLLC.json
    │   │   ├── llcAssets_WBGroupLLC.json
    │   │   ├── llcExpRev_WBGroupLLC.json
    │   │   ├── llcPayables_WBGroupLLC.json
    │   │   ├── llcReceivables_WBGroupLLC.json
    │   │   ├── llcOwners_WBGroupLLC.json
    │   │   ├── llcCustomers_WBGroupLLC.json
    │   │   └── accountNameSpace.json
    │   ├── BankStmts/                # Downloads from bank accounts
    │   ├── Forms/                    # ← CONSOLIDATED (from YE_Tax_Records/Forms_IRS + bookNS_*)
    │   │   ├── *IRS.pdf              # Original empty IRS forms
    │   │   ├── *FILL.pdf             # Filled IRS forms (output)
    │   │   ├── *namespace.pdf        # Namespace visual: IRS form mappings
    │   │   └── bookNS_*.json         # Namespace data per financial object (GL, IS, BS)
    │   ├── YE_Tax_Records/           # Other year-end tax records (non-form documents)
    │   ├── Expenses/                 # Expense tracking (year-specific)
    │   ├── Receipts/                 # Scanned receipts (year-specific)
    │   └── Working/                  # Drafts, misc (replaces FinancialTemplates)
    └── 2026/
        ├── Accts/                    # Populated when FY2026 books open
        └── BankStmts/
```

**Accounting principle:** Each fiscal year's ledger is self-contained. When a new year opens, a new `<YEAR>/Accts/` is created — COA carried forward, transactions start clean. The active year is set in the tracker config (not inside the profile). Backups go outside git.

### 2.2 OLD → NEW Migration Map (current LLC-WB-Group → LLC-WBGroup)

| Old path | New path | Notes |
|----------|----------|-------|
| `pages/AccountingData/Accts/` | `books/2025/Accts/` | Per-year ledger DBs |
| `pages/AccountingData/2025/BankStmts/` | `books/2025/BankStmts/` | Same content |
| `pages/AccountingData/2025/YE_Tax_Records/Forms_IRS/` | `books/2025/Forms/` | Consolidated with bookNS |
| `pages/AccountingData/2025/bookNS_*.json` | `books/2025/Forms/bookNS_*.json` | Namespace data files |
| `pages/AccountingData/2025/.bookNS_backups/` | Outside git | Not committed |
| `pages/AccountingData/2025/FinancialTemplates/` | `books/2025/Working/` | Renamed |
| `pages/AccountingData/2025/YE_Tax_Records/` | `books/2025/YE_Tax_Records/` | Non-form tax records |
| `pages/AccountingData/Expenses/` | `books/2025/Expenses/` | Now year-specific |
| `Receipts/` (root) | `books/2025/Receipts/` | Now year-specific |
| `pages/IRSGuide/`, `pages/Operations/`, etc. | `pages/` (unchanged) | Reference content stays |
| `pages/AccountingData/Notebooks/` | `~/GDrive/dev/trackers/llcRentalTracker/` | App code split out |

**Git:** New independent repo. No Python source code.
**Profile updates needed:**
- `TOP` → `~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup`
- `dirAccounting` → `books` (was `pages/AccountingData` — now the year folder is directly under `books/`)

---

### 2.3 Application Repo — `llcRentalTracker`

**Destination:** `~/GDrive/dev/trackers/llcRentalTracker/`

**Git:** Inherits current `LLC-WB-Group` GitHub remote — rename repo to `llcRentalTracker` in GitHub settings, update remote URL.

Contains the current `pages/AccountingData/Notebooks/` tree, with these structural changes:
- `uillc/` **removed entirely** — all imports redirected to `ui.*` before copy
- `mcp/` **added** — MCP server skeleton
- `irsv1/`, `Untitled Folder/`, `working/`, `.ipynb_checkpoints/`, `__pycache__` excluded

```
llcRentalTracker/
├── ledger/                  # Double-entry engine (LLC, ledgerDB, COA, etc.)
│   └── setup_paths.py       # REFACTORED — config-driven (see §3)
├── stmt/                    # Immutable statement objects (BS, IS, GL, OE, PE)
├── irs/                     # IRS form builders + PDF population
├── F1065_K1/                # Tax workflow orchestration
├── ui/                      # Flask view wrappers + Jinja2 templates
│   └── templates/
├── util/                    # utilEditSession, utilWorkingDB, multitask_wsgi
├── tests/                   # Test suite (stmtBS, stmtGL, stmtIS)
├── docs/                    # Architecture and design docs
│   └── irs/
├── mcp/                     # NEW — MCP server
│   ├── server.py            # MCP entry point
│   └── skills/              # Skill stubs: accounting, cpa, irs, webapp
├── wsCmd.py                 # CLI — start/stop, --newBus provisioning
├── wsgi.py                  # Flask WSGI entry point
├── CLAUDE.md                # Updated for new repo identity
└── requirements.txt
```

**No business data files in this repo.** All data access goes through `~/.llcRentalTracker/<llcName>_config.json`.

---

## 3. Key Technical Challenge: Path Resolution

### 3.1 Current State

`ledger/setup_paths.py` uses **relative parent traversal** — works only when code lives inside the business repo tree:

```python
_here = Path(__file__).resolve()
TOP           = _here.parents[4]   # LLC-WB-Group/        ← BREAKS after split
ACCT_DATA_DIR = _here.parents[2]   # AccountingData/      ← BREAKS after split
ACCTS_DIR     = ACCT_DATA_DIR / "Accts"   ← BREAKS (wrong structure too)
```

After the split AND the layout change, two things break:
1. `parents[N]` no longer reaches the business repo (code is in a separate tree)
2. `ACCTS_DIR` must now be `TOP / "books" / str(YEAR) / "Accts"` — completely different path shape

### 3.2 New Design: Per-Business Config File

Each business managed by the tracker gets a config at:

```
~/.llcRentalTracker/<llcName>_config.json
```

**`~/.llcRentalTracker/WBGroupLLC_config.json`** (generated by `--newBus`):

```json
{
  "llcName":   "WBGroupLLC",
  "bus_repo":  "~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup",
  "books_dir": "books",
  "year":      2025
}
```

**All derived at runtime** from just these four fields:

| Constant | Derived Path |
|----------|-------------|
| `TOP` | `bus_repo` (expanded) |
| `ACCT_DATA_DIR` | `TOP / books_dir` |
| `ACCTS_DIR` | `TOP / books_dir / year / "Accts"` |
| `BANK_STMTS` | `TOP / books_dir / year / "BankStmts"` |
| `IRS_FORMS_DIR` | `TOP / books_dir / year / "Forms"` |
| `STMTS_DIR` | `TOP / books_dir / "Stmts"` (cross-year cache) |
| `EXPENSES_DIR` | `TOP / books_dir / year / "Expenses"` |

Storing only `bus_repo + books_dir + year` is enough to derive everything. Changing fiscal year = change `year` field only.

### 3.3 Refactored `setup_paths.py` (design sketch)

```python
import json
from pathlib import Path

TRACKER_CFG_DIR = Path("~/.llcRentalTracker").expanduser()
TRACKER_DIR     = Path(__file__).resolve().parent.parent  # llcRentalTracker/

# Populated by load_config(); None until LLC('name') is called
TOP = ACCT_DATA_DIR = ACCTS_DIR = STMTS_DIR = None
BANK_STMTS = IRS_FORMS_DIR = EXPENSES_DIR = YEAR = None

def load_config(llcName: str):
    cfg_path = TRACKER_CFG_DIR / f"{llcName}_config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)
    base = Path(cfg["bus_repo"]).expanduser()
    books = base / cfg["books_dir"]
    yr    = cfg["year"]

    import ledger.setup_paths as _sp
    _sp.TOP           = base
    _sp.ACCT_DATA_DIR = books          # kept for stmtDB.py compatibility (TOP/dirAccounting)
    _sp.ACCTS_DIR     = books / str(yr) / "Accts"
    _sp.STMTS_DIR     = books / "Stmts"
    _sp.BANK_STMTS    = books / str(yr) / "BankStmts"
    _sp.IRS_FORMS_DIR = books / str(yr) / "Forms"
    _sp.EXPENSES_DIR  = books / str(yr) / "Expenses"
    _sp.YEAR          = yr
    return cfg
```

`LLC.__init__(llcName)` calls `load_config(llcName)` before any file access. All downstream modules that import `setup_paths` get updated constants with no changes.

**Note:** `stmtDB.py` uses `TOP/dirAccounting/Stmts`. With `dirAccounting = "books"`, this resolves to `TOP/books/Stmts` = `STMTS_DIR`. Consistent.

---

## 4. Task List

### Task 1 — Plan (this document) ✅

### Task 2 — Create Business Repo `LLC-WBGroup`

**Steps:**
1. `cp -r LLC-WB-Group/ ~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup/` — duplicate full tree
2. `rm -rf LLC-WBGroup/pages/AccountingData/Notebooks/` — remove app code
3. Build `books/` structure:
   - `mkdir -p LLC-WBGroup/books/2025/`
   - `mv LLC-WBGroup/pages/AccountingData/Accts/ LLC-WBGroup/books/2025/Accts/`
   - `mv LLC-WBGroup/pages/AccountingData/2025/BankStmts/ LLC-WBGroup/books/2025/BankStmts/`
   - `mkdir LLC-WBGroup/books/2025/Forms/`
   - `mv LLC-WBGroup/pages/AccountingData/2025/YE_Tax_Records/Forms_IRS/* LLC-WBGroup/books/2025/Forms/`
   - `mv LLC-WBGroup/pages/AccountingData/2025/bookNS_*.json LLC-WBGroup/books/2025/Forms/`
   - `mv LLC-WBGroup/pages/AccountingData/2025/YE_Tax_Records/ LLC-WBGroup/books/2025/YE_Tax_Records/`
   - `mv LLC-WBGroup/pages/AccountingData/Expenses/ LLC-WBGroup/books/2025/Expenses/`
   - `mv LLC-WBGroup/pages/AccountingData/2025/FinancialTemplates/ LLC-WBGroup/books/2025/Working/`
   - `mv LLC-WBGroup/Receipts/ LLC-WBGroup/books/2025/Receipts/`
   - Leave `.bookNS_backups/` out (not committed)
4. Update `books/2025/Accts/llcProfile_WBGroupLLC.json`:
   - `"TOP"` → `"~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup"`
   - `"dirAccounting"` → `"books"`
5. Update root `llcProfile_WBGroupLLC.json` with same changes
6. `mkdir -p LLC-WBGroup/books/2026 && mkdir LLC-WBGroup/books/2026/Accts`
7. `git init && git add . && git commit -m "init: LLC-WBGroup business repo"` in the new folder

### Task 3 — Create `llcRentalTracker`

**Steps:**
1. `cp -r pages/AccountingData/Notebooks/ ~/GDrive/dev/trackers/llcRentalTracker/`
2. Remove excluded dirs: `uillc/`, `irsv1/`, `Untitled Folder/`, `working/`, all `__pycache__`, `.ipynb_checkpoints`
3. Rewrite all `from uillc.` imports → `from ui.` across all .py files
4. Refactor `ledger/setup_paths.py` per §3.3
5. Update `ledger/LLC.__init__()` to call `setup_paths.load_config(llcName)` before profile load
6. Fix late-binding issue in `ui/llcLogin_auth.py` (see §5.2)
7. Add `mcp/` skeleton: `server.py` + `skills/__init__.py` + 4 stub files
8. Update `wsCmd.py` — add `--newBus <bus_folder>` flag
9. Update `CLAUDE.md` for new repo identity
10. `git init && git remote add origin <existing LLC-WB-Group GitHub URL>`
11. `git add . && git commit -m "init: llcRentalTracker (split from LLC-WB-Group)"`

### Task 4 — Configure & Test

**Steps:**
1. `mkdir -p ~/.llcRentalTracker`
2. `python wsCmd.py --newBus ~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup` → generates `WBGroupLLC_config.json`
3. Verify config: `ACCTS_DIR` resolves to `…/books/2025/Accts/`, `IRS_FORMS_DIR` to `…/books/2025/Forms/`
4. Start app: `python wsCmd.py --llcName WBGroupLLC --port 5000`
5. Run test suite:
   ```bash
   python -m tests.test_stmtBS
   python -m tests.test_stmtGL
   python -m tests.test_stmtIS
   ```
6. Smoke-test Flask UI: BS, IS, GL views load; editor saves to `books/2025/Accts/`; IRS PDFs write to `books/2025/Forms/`

**Pass criteria:** All 3 test suites pass; Flask UI matches current behavior; all file paths resolve under `books/2025/`.

### Task 5 — MCP Server (separate session after Task 4 passes)

---

## 5. Code Change Impact: `llcRentalTracker` (Task 3 Detail)

All changes are isolated to the path/config layer. Business logic in `ledger/`, `stmt/`, `irs/`, `ui/` is untouched.

### 5.1 Full Change Table

| File | What Changes | Why |
|------|-------------|-----|
| `ledger/setup_paths.py` | Full rewrite — remove `parents[N]`, add `load_config()` | Code no longer inside business repo; paths now config-driven |
| `ledger/LLC.py:__init__` | Call `setup_paths.load_config(llcName)` before profile load | Must populate constants before any file access |
| `ledger/LLC.py:165` | `acctDIR = TOP/dirAccounting/yr` — verify resolves to `books/2025/` after profile update | Auto-corrects via profile change |
| `ledger/stmtDB.py:404` | `stmts_dir = TOP/dirAccounting/Stmts` — verify resolves to `books/Stmts/` | Auto-corrects via profile change |
| `ledger/stmtProfile.py:149` | Uses `setup_paths.ACCTS_DIR` | Auto-corrects once `load_config` sets it |
| `irs/BookToIRS.py:151` | Uses `setup_paths.ACCTS_DIR` | Auto-corrects |
| `irs/` PDF write paths | Currently write to `IRS_FORMS_DIR` (`YE_Tax_Records/Forms_IRS/`) | Auto-corrects to `books/2025/Forms/` via config |
| `ui/llcLogin_auth.py:136` | `_ACCTS = _sp.ACCTS_DIR` at import time | Late-bind fix required (see §5.2) |
| `wsCmd.py` | Add `--newBus` argument | New feature |
| `util/multitask_wsgi.py` | Update `_pkg` path to llcRentalTracker location | Deployment path change |
| All `from uillc.*` imports | Rewrite to `from ui.*` | `uillc/` removed |

### 5.2 The `ui/llcLogin_auth.py` Late-Binding Issue

`_ACCTS = _sp.ACCTS_DIR` is assigned at module import time. If the module is imported before `LLC('WBGroupLLC')` calls `load_config()`, `_ACCTS` is `None`.

**Fix:** Change to a function:
```python
# Before
_ACCTS = _sp.ACCTS_DIR

# After — late-bound
def _accts(): return _sp.ACCTS_DIR
```
Replace all `_ACCTS` usages inside `llcLogin_auth.py` with `_accts()`. Scope: one file.

### 5.3 MCP Structural Note

MCP tools will call `stmt.*` and `ledger.*` directly (stateless reads). The Flask session layer (`ui/`, `utilEditSession`) stays Flask-only. No changes to `ui/` required during restructure; this clean boundary makes MCP wiring straightforward in Task 5.

---

## 6. MCP Server Design — Task 5

`llcRentalTracker` exposes both HTTP (Flask) and MCP from the same codebase; they share `ledger/` and `stmt/` but have separate entry points.

### 6.1 Skill Domains

| Skill | MCP Tools | Wraps |
|-------|-----------|-------|
| `accounting` | read_ledger, get_balance_sheet, get_income_stmt, get_gl | `stmt.*`, `ledger.*` |
| `cpa_analysis` | ratio_analysis, cashflow_projection, budget_vs_actual | `stmt.*` + Claude API |
| `irs_tax` | gen_form1065, gen_k1, gen_8825, map_irs_lines | `irs.*`, `F1065_K1.*` |
| `webapp` | start_server, stop_server, export_report | `wsCmd.*` |

### 6.2 MCP Entry Point

```
llcRentalTracker/mcp/server.py
```
Library choice deferred. Constraint: must support both `stdio` (Claude Desktop) and HTTP transport (PA deployment).

### 6.3 Claude API Integration

CPA analysis and tax review skills call the Claude API with prompt caching. Financial statement data passed as cached `user` content blocks. Model: `claude-sonnet-4-6`.

---

## 7. PA MultiTaskWS Integration

| Task Name | Entry Point | Port |
|-----------|-------------|------|
| `llcRentalTracker` | `llcRentalTracker/wsgi.py` | 5000 (local) / PA WSGI |

`util/multitask_wsgi.py` `_pkg` updated to `~/GDrive/dev/trackers/llcRentalTracker` for local dev; PA path set via config or env var.

---

## 8. Complete Coupling-Point Inventory

| Coupling | Current Location | Resolution | Task |
|----------|-----------------|------------|------|
| `parents[4]` = repo root | `ledger/setup_paths.py:39` | Replace with `load_config()` | T3 |
| `parents[2]` = AccountingData | `ledger/setup_paths.py:41` | Replace with `load_config()` | T3 |
| `ACCTS_DIR = ACCT_DATA_DIR / "Accts"` | `ledger/setup_paths.py:44` | `books / str(YEAR) / "Accts"` via config | T3 |
| `dirAccounting = "pages/AccountingData"` | `llcProfile_WBGroupLLC.json` | Change to `"books"` | T2 |
| `TOP` old path in profile | `llcProfile_WBGroupLLC.json` | Update to new bus_repo path | T2 |
| `IRS_FORMS_DIR` → `YE_Tax_Records/Forms_IRS/` | `setup_paths.py:48` | Redirect to `books/YEAR/Forms/` | T3 |
| `EXPENSES_DIR` → `AccountingData/Expenses/` | `setup_paths.py:45` | Redirect to `books/YEAR/Expenses/` | T3 |
| `_ACCTS = _sp.ACCTS_DIR` at import time | `ui/llcLogin_auth.py:136` | Late-bind via `_accts()` function | T3 |
| `from uillc.*` imports (multiple files) | Various .py files | Rewrite to `from ui.*` | T3 |
| `multitask_wsgi.py` `_pkg` path | `util/multitask_wsgi.py` | Update to llcRentalTracker path | T3 |
| `stmts_dir = TOP/dirAccounting/Stmts` | `ledger/stmtDB.py:404` | Auto-corrects via profile `dirAccounting = "books"` | T2 |
| `.claude/settings.json` | `.claude/` in old repo | Each new repo gets its own `.claude/` | T2+T3 |

---

## 9. What Stays in LLC-WB-Group (Archive)

The original `LLC-WB-Group` repo is **not deleted** — kept as archived monorepo / git history source. New repos start with clean git histories.

---

## 10. Session Decisions (All Resolved)

| Question | Decision |
|----------|----------|
| Business repo destination | `~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup` |
| llcRentalTracker GitHub remote | Inherits LLC-WB-Group remote; rename repo in GitHub |
| `uillc/` shim | Remove entirely; rewrite imports to `ui.*` |
| MCP library choice | Deferred to Task 5 |
| Root-level `Notebooks/` | Goes into business repo (LLC-WBGroup) |
| `pages/` rename | Stays as `pages/` for reference content; `books/` is new for fiscal data |
| `Accts/` location | Under fiscal year: `books/YEAR/Accts/` |
| `IRS_FORMS_DIR` new location | `books/YEAR/Forms/` (consolidated with bookNS files) |
| `dirAccounting` new value | `"books"` (was `"pages/AccountingData"`) |
| Backups (`.bookNS_backups/`) | Outside git structure |
