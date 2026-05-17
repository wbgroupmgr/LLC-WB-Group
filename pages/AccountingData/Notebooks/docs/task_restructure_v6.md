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
- `pages/` renamed to `books/` — clearer separation of business content sections
- `Accts/` moves from `books/AccountingData/` (above the year) **into** `books/AccountingData/<YEAR>/Accts/` — accounting records are per fiscal period
- `Stmts/` cache stays at `books/AccountingData/Stmts/` (cross-year read cache, not live data)

```
LLC-WBGroup/
├── Assets/                              # Property acquisition docs
│   ├── 16ElConejo-2026/
│   ├── 805HighMesa/
│   └── RVCamper_2025/
├── LLC Doc Records/                     # Articles, operating agreement, IRS letter
│   ├── 20250818-LLC_forms/
│   └── LLC_Filing/
├── Notebooks/                           # Legacy Jupyter (root-level, kept in business repo)
├── Receipts/                            # Scanned receipt archives
├── docs/                                # Release notes, milestone docs
│   └── releases/
├── Claude-Work/                         # Claude session artifacts
├── llcProfile_WBGroupLLC.json           # Root entity metadata (TOP updated)
├── index.md
├── requirements.txt
└── books/                               # was "pages/" — business content sections
    ├── IRSGuide/
    ├── LLC-Filing/
    ├── Operations/
    ├── RentalMgmt/
    ├── Taxes/
    └── AccountingData/
        ├── Expenses/                    # Expense tracking JSONs (cross-year)
        ├── Stmts/                       # Read-only statement cache (cross-year)
        ├── 2025/
        │   ├── Accts/                   # ← MOVED HERE (was AccountingData/Accts/)
        │   │   ├── llcProfile_WBGroupLLC.json
        │   │   ├── ChartOfAccounts_WBGroupLLC.json
        │   │   ├── llcAssets_WBGroupLLC.json
        │   │   ├── llcExpRev_WBGroupLLC.json
        │   │   ├── llcPayables_WBGroupLLC.json
        │   │   ├── llcReceivables_WBGroupLLC.json
        │   │   ├── llcOwners_WBGroupLLC.json
        │   │   ├── llcCustomers_WBGroupLLC.json
        │   │   └── accountNameSpace.json
        │   ├── BankStmts/
        │   ├── YE_Tax_Records/
        │   │   └── Forms_IRS/           # IRS PDF output
        │   └── FinancialTemplates/
        └── 2026/
            ├── Accts/                   # Populated when FY2026 books open
            └── BankStmts/
```

**Accounting principle:** Each fiscal year's ledger is self-contained. When a new year opens, a new `<YEAR>/Accts/` is created — COA carried forward, transactions start clean. The active year is set in the tracker config, not inside the profile.

**Git:** New independent repo. No Python source code.
**Profile updates needed:**
- `TOP` → `~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup`
- `dirAccounting` → `books/AccountingData` (was `pages/AccountingData`)

---

### 2.2 Application Repo — `llcRentalTracker`

**Destination:** `~/GDrive/dev/trackers/llcRentalTracker/`

**Git:** Inherits current `LLC-WB-Group` GitHub remote — rename repo to `llcRentalTracker` in GitHub settings, update remote URL.

Contains the current `pages/AccountingData/Notebooks/` tree, with these structural changes:
- `uillc/` **removed entirely** — all imports redirected to `ui.*` before copy
- `mcp/` **added** — MCP server skeleton
- `irsv1/` and `Untitled Folder/` excluded (dead code)
- `.ipynb_checkpoints/`, `working/`, `__pycache__` excluded

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

**No business data files in this repo.** All data access goes through the business config in `~/.llcRentalTracker/`.

---

## 3. Key Technical Challenge: Path Resolution

### 3.1 Current State

`ledger/setup_paths.py` uses **relative parent traversal** — works only when code lives inside the business repo tree:

```python
_here = Path(__file__).resolve()
TOP           = _here.parents[4]   # LLC-WB-Group/        ← BREAKS after split
ACCT_DATA_DIR = _here.parents[2]   # AccountingData/      ← BREAKS after split
ACCTS_DIR     = ACCT_DATA_DIR / "Accts"  ← BREAKS (wrong year-level too)
```

After the split AND the `Accts/` move, two things break simultaneously:
1. `parents[N]` no longer reaches the business repo (code is in a separate tree)
2. `ACCTS_DIR` is one level too high — it must be `ACCT_DATA_DIR / str(YEAR) / "Accts"`

### 3.2 New Design: Per-Business Config File

Each business managed by the tracker gets a config at:

```
~/.llcRentalTracker/<llcName>_config.json
```

**`~/.llcRentalTracker/WBGroupLLC_config.json`** (generated by `--newBus`):

```json
{
  "llcName":        "WBGroupLLC",
  "bus_repo":       "~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup",
  "acct_data_dir":  "books/AccountingData",
  "year":           2025,
  "bank_stmts":     "books/AccountingData/{year}/BankStmts",
  "irs_forms_dir":  "books/AccountingData/{year}/YE_Tax_Records/Forms_IRS"
}
```

**Derived at runtime** (not stored in config — computed by `setup_paths.load_config()`):
- `ACCTS_DIR`      = `bus_repo / acct_data_dir / year / "Accts"`
- `BANK_STMTS`     = `bus_repo / acct_data_dir / year / "BankStmts"`
- `IRS_FORMS_DIR`  = `bus_repo / acct_data_dir / year / "YE_Tax_Records/Forms_IRS"`
- `STMTS_DIR`      = `bus_repo / acct_data_dir / "Stmts"` (cross-year cache)

Storing only `bus_repo + acct_data_dir + year` is enough to derive everything else. The year field makes it trivial to switch fiscal years without moving files.

### 3.3 Refactored `setup_paths.py` (design sketch)

```python
import json
from pathlib import Path

TRACKER_CFG_DIR = Path("~/.llcRentalTracker").expanduser()
TRACKER_DIR     = Path(__file__).resolve().parent.parent  # llcRentalTracker/

# Populated by load_config(); None until LLC('name') is called
TOP           = None
ACCT_DATA_DIR = None
ACCTS_DIR     = None
STMTS_DIR     = None
BANK_STMTS    = None
IRS_FORMS_DIR = None
YEAR          = None

def load_config(llcName: str):
    cfg_path = TRACKER_CFG_DIR / f"{llcName}_config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)
    base     = Path(cfg["bus_repo"]).expanduser()
    acct     = base / cfg["acct_data_dir"]
    yr       = cfg["year"]

    import ledger.setup_paths as _sp
    _sp.TOP           = base
    _sp.ACCT_DATA_DIR = acct
    _sp.ACCTS_DIR     = acct / str(yr) / "Accts"
    _sp.STMTS_DIR     = acct / "Stmts"
    _sp.BANK_STMTS    = acct / str(yr) / "BankStmts"
    _sp.IRS_FORMS_DIR = acct / str(yr) / "YE_Tax_Records" / "Forms_IRS"
    _sp.YEAR          = yr
    return cfg
```

`LLC.__init__(llcName)` calls `load_config(llcName)` before any file access. All downstream modules that already import `setup_paths` get the updated constants with no changes.

---

## 4. Task List

### Task 1 — Plan (this document) ✅

### Task 2 — Create Business Repo `LLC-WBGroup`

**Steps:**
1. `cp -r LLC-WB-Group/ ~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup/` — duplicate full tree
2. `rm -rf LLC-WBGroup/pages/AccountingData/Notebooks/` — remove app code from business copy
3. Rename `LLC-WBGroup/pages/` → `LLC-WBGroup/books/`
4. Move `books/AccountingData/Accts/` → `books/AccountingData/2025/Accts/`
5. Update `books/AccountingData/2025/Accts/llcProfile_WBGroupLLC.json`:
   - `"TOP"` → `"~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup"`
   - `"dirAccounting"` → `"books/AccountingData"`
6. Update root `llcProfile_WBGroupLLC.json` with same changes
7. `git init && git add . && git commit -m "init: LLC-WBGroup business repo"` in the new folder

**What stays in LLC-WB-Group:** unchanged until Task 4 validates llcRentalTracker works.

### Task 3 — Create `llcRentalTracker`

**Steps:**
1. `cp -r pages/AccountingData/Notebooks/ ~/GDrive/dev/trackers/llcRentalTracker/`
2. Remove excluded dirs: `uillc/`, `irsv1/`, `Untitled Folder/`, `working/`, all `__pycache__`, `.ipynb_checkpoints`
3. Redirect `uillc/` imports → scan for `from uillc.` and rewrite to `from ui.` across all .py files
4. Refactor `ledger/setup_paths.py` per §3.3 design
5. Update `ledger/LLC.__init__()` to call `setup_paths.load_config(llcName)` first
6. Add `mcp/` skeleton: `server.py` + `skills/__init__.py` + 4 skill stubs
7. Update `wsCmd.py` — add `--newBus <bus_folder>` flag (reads profile, writes `~/.llcRentalTracker/<llcName>_config.json`)
8. Update `CLAUDE.md` to reflect new repo identity and layout
9. `git init && git remote add origin <existing LLC-WB-Group GitHub URL>`
10. `git add . && git commit -m "init: llcRentalTracker (split from LLC-WB-Group)"`

### Task 4 — Configure & Test

**Steps:**
1. `mkdir -p ~/.llcRentalTracker`
2. `python wsCmd.py --newBus ~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup` → generates `WBGroupLLC_config.json`
3. Verify config has correct paths (spot-check `ACCTS_DIR` resolves to `…/2025/Accts/`)
4. Start app: `python wsCmd.py --llcName WBGroupLLC --port 5000`
5. Run test suite:
   ```bash
   python -m tests.test_stmtBS
   python -m tests.test_stmtGL
   python -m tests.test_stmtIS
   ```
6. Smoke-test Flask UI: BS, IS, GL views load; editor saves to correct `2025/Accts/` files

**Pass criteria:** All 3 test suites pass; Flask UI matches current behavior; Accts writes go to `books/AccountingData/2025/Accts/`.

### Task 5 — MCP Server (separate session after Task 4 passes)

---

## 5. Code Change Impact: `llcRentalTracker` (Task 3 Detail)

All changes are isolated to the path/config layer. Business logic in `ledger/`, `stmt/`, `irs/`, `ui/` is untouched.

### 5.1 Changes Required

| File | What Changes | Why |
|------|-------------|-----|
| `ledger/setup_paths.py` | Full rewrite — remove `parents[N]`, add `load_config()` | Code no longer inside business repo tree; `ACCTS_DIR` now year-relative |
| `ledger/LLC.py` | `__init__` calls `setup_paths.load_config(llcName)` before profile load | Must populate constants before any file access |
| `ledger/LLC.py:165` | `acctDIR` already built as `TOP/dirAccounting/yr` — verify it still resolves correctly after profile `dirAccounting` changes to `books/AccountingData` | `pages/` → `books/` |
| `ledger/stmtDB.py:404` | `stmts_dir = TOP/dirAccounting/Stmts` — driven by profile `dirAccounting` | Auto-corrects once profile updated; no code change |
| `ledger/stmtProfile.py:149` | Uses `setup_paths.ACCTS_DIR` — auto-corrects once `load_config` sets it | No code change needed |
| `irs/BookToIRS.py:151` | Uses `setup_paths.ACCTS_DIR` — same | No code change needed |
| `ui/llcLogin_auth.py:136` | `_ACCTS = _sp.ACCTS_DIR` — assigned at module import; must import after `load_config` runs | Move assignment inside a function or use late binding |
| `wsCmd.py` | Add `--newBus` argument; update any hardcoded paths | New feature |
| `util/multitask_wsgi.py` | Update `_pkg` path to llcRentalTracker location | Deployment path change |
| All `from uillc.*` imports | Rewrite to `from ui.*` | `uillc/` removed |

### 5.2 The `ui/llcLogin_auth.py` Late-Binding Issue

`_ACCTS = _sp.ACCTS_DIR` is assigned at module load time. If the module is imported before `LLC('WBGroupLLC')` runs `load_config()`, `_ACCTS` will be `None`.

**Fix:** Change the assignment to a property or function call:
```python
# Before
_ACCTS = _sp.ACCTS_DIR

# After
def _accts(): return _sp.ACCTS_DIR
```
Then replace `_ACCTS` usages with `_accts()` inside the file. Scope of change: `ui/llcLogin_auth.py` only.

### 5.3 MCP Structural Note

The `ui/` layer is stateful (Flask sessions, `utilEditSession`). This is fine for the web app. For MCP tools, we will **not** wrap `ui/` — MCP tools will call `stmt.*` and `ledger.*` directly for stateless reads, and `ledger.*` write methods for mutations. The session layer stays Flask-only. This clean boundary means no changes to `ui/` are needed during restructure.

---

## 6. MCP Server Design — `llcRentalTracker` (Task 5)

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
Library choice deferred to Task 5. Constraint: must support both `stdio` (Claude Desktop) and HTTP transport (PA deployment).

### 6.3 Claude API Integration

CPA analysis and tax review skills call the Claude API with prompt caching. Financial statement data (BS/IS) passed as cached `user` content blocks. Model: `claude-sonnet-4-6`.

---

## 7. PA MultiTaskWS Integration (Goal 3)

| Task Name | Entry Point | Port |
|-----------|-------------|------|
| `llcRentalTracker` | `llcRentalTracker/wsgi.py` | 5000 (local) / PA WSGI |

`util/multitask_wsgi.py` `_pkg` path updated to `~/GDrive/dev/trackers/llcRentalTracker` for local; PA path set via `--newBus` config or env var.

---

## 8. Complete Coupling-Point Inventory

| Coupling | Current Location | Resolution | Task |
|----------|-----------------|------------|------|
| `parents[4]` = repo root (TOP) | `ledger/setup_paths.py:39` | Replace with `load_config()` | T3 |
| `parents[2]` = AccountingData | `ledger/setup_paths.py:41` | Replace with `load_config()` | T3 |
| `ACCTS_DIR = ACCT_DATA_DIR / "Accts"` | `ledger/setup_paths.py:44` | `ACCT_DATA_DIR / str(YEAR) / "Accts"` via config | T3 |
| `dirAccounting = "pages/AccountingData"` | `llcProfile_WBGroupLLC.json` | Change to `"books/AccountingData"` | T2 |
| `TOP` old path in profile | `llcProfile_WBGroupLLC.json` | Update to new bus_repo path | T2 |
| `_ACCTS = _sp.ACCTS_DIR` at import time | `ui/llcLogin_auth.py:136` | Late-bind via `_accts()` function | T3 |
| `from uillc.*` imports (all files) | Multiple .py files | Rewrite to `from ui.*` | T3 |
| `multitask_wsgi.py` `_pkg` path | `util/multitask_wsgi.py` | Update to llcRentalTracker path | T3 |
| `stmts_dir = TOP/dirAccounting/Stmts` | `ledger/stmtDB.py:404` | Auto-corrects via profile update | T2 |
| `.claude/settings.json` | `.claude/` in old repo | Each new repo gets its own `.claude/` | T2+T3 |

---

## 9. What Stays in LLC-WB-Group (Archive)

The original `LLC-WB-Group` repo is **not deleted** — kept as archived monorepo / git history source. New repos start with clean git histories.

---

## 10. Session Decisions (Resolved)

| Question | Decision |
|----------|----------|
| Business repo destination | `~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup` ✅ |
| llcRentalTracker GitHub remote | Inherits LLC-WB-Group remote; rename repo in GitHub ✅ |
| `uillc/` shim | Remove entirely; rewrite imports to `ui.*` ✅ |
| MCP library choice | Deferred to Task 5 ✅ |
| Root-level `Notebooks/` | Goes into business repo (LLC-WBGroup) ✅ |
| `pages/` rename | `books/` ✅ |
| `Accts/` location | Under fiscal year: `books/AccountingData/YEAR/Accts/` ✅ |
