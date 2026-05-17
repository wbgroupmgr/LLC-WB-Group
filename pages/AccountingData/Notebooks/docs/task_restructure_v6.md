# Restructure Plan v6 — LLC-WB-Group → Business Repo + llcRentalTracker

**Date:** 2026-05-17  
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

Contains **everything from current LLC-WB-Group EXCEPT `pages/AccountingData/Notebooks/`**:

```
LLC-WBGroup/
├── Assets/                          # Property acquisition docs (16ElConejo, 805HighMesa, RVCamper)
├── LLC Doc Records/                 # Articles, operating agreement, IRS letter
├── Receipts/                        # Scanned receipt archives
├── docs/                            # Release notes, milestone docs
├── Notebooks/                       # Legacy Jupyter (root-level, NOT the app Notebooks)
├── llcProfile_WBGroupLLC.json       # Root entity metadata
├── index.md
├── requirements.txt
└── pages/
    └── AccountingData/
        ├── Accts/                   # JSON ledger databases (the source of truth)
        │   ├── llcProfile_WBGroupLLC.json
        │   ├── ChartOfAccounts_WBGroupLLC.json
        │   ├── llcAssets_WBGroupLLC.json
        │   ├── llcExpRev_WBGroupLLC.json
        │   ├── llcPayables_WBGroupLLC.json
        │   ├── llcReceivables_WBGroupLLC.json
        │   ├── llcOwners_WBGroupLLC.json
        │   ├── llcCustomers_WBGroupLLC.json
        │   └── accountNameSpace.json
        ├── Expenses/
        ├── 2025/                    # Year-specific bank stmts + IRS output PDFs
        └── 2026/
```

**Git:** New independent repo. No Python source code.  
**llcProfile update:** Change `TOP` field to new path `~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup`.

---

### 2.2 Application Repo — `llcRentalTracker`

**Destination:** `~/GDrive/dev/trackers/llcRentalTracker/`

Contains the current `pages/AccountingData/Notebooks/` tree, restructured:

```
llcRentalTracker/
├── ledger/              # Double-entry engine (LLC, ledgerDB, COA, etc.)
│   └── setup_paths.py  # REFACTORED — reads from ~/.llcRentalTracker/<llcName>_config.json
├── stmt/                # Immutable statement objects (BS, IS, GL, OE, PE)
├── irs/                 # IRS form builders + PDF population
├── F1065_K1/            # Tax workflow orchestration
├── ui/                  # Flask view wrappers + Jinja2 templates
├── uillc/               # Compatibility shim (re-exports from ui/)
├── util/                # utilEditSession, utilWorkingDB, multitask_wsgi
├── tests/               # Test suite (stmtBS, stmtGL, stmtIS)
├── docs/                # Architecture and design docs (this file included)
├── mcp/                 # NEW — MCP server entry point + skill definitions
│   ├── server.py        # MCP server (FastMCP or compatible)
│   └── skills/          # Skill modules (accounting, cpa, irs, webapp)
├── wsCmd.py             # CLI — start/stop server, --newBus provisioning
├── wsgi.py              # Flask WSGI entry point
└── requirements.txt
```

**Git:** New independent repo. No business data files.

---

## 3. Key Technical Challenge: Path Resolution

### 3.1 Current State

`ledger/setup_paths.py` resolves all data paths using **relative parent traversal**:

```python
_here = Path(__file__).resolve()  # .../Notebooks/ledger/setup_paths.py
TOP           = _here.parents[4]  # LLC-WB-Group/ (4 levels up)
ACCT_DATA_DIR = _here.parents[2]  # AccountingData/
ACCTS_DIR     = ACCT_DATA_DIR / "Accts"
```

This works because the code lives **inside** the business repo tree. After the split, the code is in a completely different directory from the data — `parents[N]` no longer reaches the business files.

### 3.2 New Design: Per-Business Config File

Each business the tracker manages gets a config file at:

```
~/.llcRentalTracker/<llcName>_config.json
```

Example: `~/.llcRentalTracker/WBGroupLLC_config.json`

```json
{
  "llcName": "WBGroupLLC",
  "bus_repo": "~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup",
  "acct_data_dir": "pages/AccountingData",
  "accts_dir": "pages/AccountingData/Accts",
  "bank_stmts_2025": "pages/AccountingData/2025/BankStmts",
  "bank_stmts_2026": "pages/AccountingData/2026/BankStmts",
  "irs_forms_dir": "pages/AccountingData/2025/YE_Tax_Records/Forms_IRS",
  "year": 2025
}
```

All paths under `bus_repo` are relative to `bus_repo` so `~` expansion is applied once at resolution time.

### 3.3 Refactored `setup_paths.py`

```python
# setup_paths.py — new design (sketch)
import os, json
from pathlib import Path

TRACKER_DIR = Path("~/.llcRentalTracker").expanduser()

def load_config(llcName: str) -> dict:
    cfg_path = TRACKER_DIR / f"{llcName}_config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)
    base = Path(cfg["bus_repo"]).expanduser()
    return {k: base / v if k != "llcName" else v
            for k, v in cfg.items()}

# Module-level constants set after LLC is chosen (via LLC('WBGroupLLC'))
TOP = None          # set by LLC.__init__ after load_config()
NOTEBOOKS_DIR = Path(__file__).resolve().parent.parent  # always llcRentalTracker/
ACCTS_DIR = None
# ... etc.
```

`LLC.__init__(llcName)` calls `load_config(llcName)` and populates the module-level constants, so all downstream imports that do `from ledger import setup_paths` still work without changes.

---

## 4. Task List

### Task 1 — Plan (this document) ✅
Review current structure, identify coupling points, write this doc. 

### Task 2 — Create Business Repo `LLC-WBGroup`

**Steps:**
1. `cp -r LLC-WB-Group/ ~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup/` — duplicate full tree
2. `rm -rf LLC-WBGroup/pages/AccountingData/Notebooks/` — remove app code from business copy
3. Update `llcProfile_WBGroupLLC.json` → `"TOP": "~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup"`
4. `git init && git add . && git commit` in the new folder
5. Verify Accts/ JSON files are present and intact

**What stays in the old LLC-WB-Group:** unchanged until Task 4 validates llcRentalTracker works.

### Task 3 — Create `llcRentalTracker`

**Steps:**
1. `cp -r pages/AccountingData/Notebooks/ ~/GDrive/dev/trackers/llcRentalTracker/`
2. Add `mcp/` skeleton (server.py + skills/ stubs for 4 skill domains)
3. Refactor `ledger/setup_paths.py`:
   - Remove all `parents[N]` constants
   - Add `load_config(llcName)` function
   - Keep `NOTEBOOKS_DIR` (self-relative, still valid)
4. Update `LLC.__init__()` to call `load_config()` and bind module constants
5. Add `wsCmd.py --newBus <bus_folder>` that:
   - Reads `llcProfile_*.json` from the business folder
   - Generates `~/.llcRentalTracker/<llcName>_config.json`
6. `git init && git add . && git commit`

**Files NOT to copy into llcRentalTracker:**
- `*.ipynb` checkpoint dirs (`.ipynb_checkpoints/`)
- `working/` temp files
- `Untitled Folder/`
- `.DS_Store`

### Task 4 — Configure & Test

**Steps:**
1. `python wsCmd.py --newBus ~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup` — generates WBGroupLLC_config.json
2. Verify `~/.llcRentalTracker/WBGroupLLC_config.json` has correct paths
3. Start app: `python wsCmd.py --llcName WBGroupLLC --port 5000`
4. Run test suite: `python -m tests.test_stmtBS && python -m tests.test_stmtGL && python -m tests.test_stmtIS`
5. Smoke-test Flask UI: BS, IS, GL views load; editor saves correctly

**Pass criteria:** All 3 test suites pass; Flask UI matches current behavior; no hardcoded paths to old Notebooks location.

---

## 5. MCP Server Design (llcRentalTracker Goal 2)

`llcRentalTracker` exposes both HTTP (Flask) and MCP endpoints from the same process or as a sidecar.

### 5.1 Skill Domains

| Skill | Capabilities |
|-------|-------------|
| `accounting` | Read/write ledger entries, generate BS/IS/GL statements, COA management |
| `cpa_analysis` | Ratio analysis, cash flow projection, budget vs actual |
| `irs_tax` | Form 1065 / K-1 / 8825 / 4562 generation, IRS line mapping, PDF population |
| `webapp` | Start/stop server, session management, export reports |

### 5.2 MCP Entry Point

```
llcRentalTracker/mcp/server.py
```
Uses FastMCP (or compatible library). Each skill is a set of MCP tools that wrap existing `stmt.*`, `irs.*`, and `ledger.*` calls.

### 5.3 Claude API Integration

Skills that perform CPA analysis or tax review will call the Claude API with prompt caching enabled (using `claude-sonnet-4-6` default). Analysis prompts will be cached against the relevant financial statement data.

---

## 6. PA MultiTaskWS Integration (Goal 3)

Update `util/multitask_wsgi.py` for both repos:

| Task Name | Entry Point | Port |
|-----------|-------------|------|
| `llcRentalTracker` | `llcRentalTracker/wsgi.py` | 5000 (local) / PA WSGI |
| `LLC-WBGroup` | Static file server or future REST API | TBD |

`wsCmd.py` registration via `--register-pa` flag (future task — not in scope for this session).

---

## 7. Coupling Points to Break (Complete List)

| Coupling | Location | Resolution |
|----------|----------|------------|
| `parents[4]` = repo root | `ledger/setup_paths.py` | Replace with `load_config()` |
| `parents[2]` = AccountingData | `ledger/setup_paths.py` | Config-driven |
| `llcProfile_WBGroupLLC.json:TOP` old path | Business repo Accts/ | Update to new bus_repo path |
| `multitask_wsgi.py` hardcoded PA path | `util/multitask_wsgi.py` | Config-driven or env var |
| `wsCmd.py` home-dir detection | `wsCmd.py` | Remains (PA vs local detection OK) |
| `.claude/settings.json` worktree refs | `.claude/` | Each repo gets its own `.claude/` |

---

## 8. Files That Stay in LLC-WB-Group (Archive / Reference)

The original `LLC-WB-Group` repo is **not deleted** after the split — it remains the git history source and will be archived or kept as the legacy monorepo. The new repos will not share its git history (clean starts).

---

## 9. Open Questions (Resolve Before GO on Tasks 2-4)

1. **Destination of business repo:** `~/GDrive/Family/Financials/Assets-Hobby/LLC-WBGroup` — confirm this matches your GDrive layout. The exploration found `~/GDrive/Family/Assets-Hobby/RealEstateInvestments/LLC-WB-Group` currently. Should the new path be under `Financials/` or keep the same parent?

2. **Git remote:** Should `llcRentalTracker` and `LLC-WBGroup` get new GitHub repos, or should `llcRentalTracker` inherit the current `LLC-WB-Group` remote (since it's the app code)?

3. **uillc/ shim:** After the split, `uillc/` can be cleaned up (it's a compatibility layer). Keep it as-is or remove it during the restructure?

4. **MCP library:** FastMCP vs raw MCP SDK vs anthropic-mcp package — which do you want to use for the MCP server in Task 3?

5. **Root-level Notebooks/ folder:** The current repo has a legacy `Notebooks/` at the repo root (separate from `pages/AccountingData/Notebooks/`). Does this go into the business repo, llcRentalTracker, or neither?
