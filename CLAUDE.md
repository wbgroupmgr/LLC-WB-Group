# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. What This Project Is

LLC accounting and IRS tax management system for **W&B Group, LLC** — a multi-member real estate investment LLC. It manages a double-entry ledger, generates financial statements (BS, IS, GL), produces IRS Form 1065 / Schedule K-1 PDFs, and provides a Flask web editor for data entry.

### 1.1 Claude Development Guidelines


#### Github Mgmt

- The github is always on `*main` -- this is the dev environment, just as it is for cowork.
- When a minor/major release is tested, we will push the code to a release/vMajor.Minor, currently working on Major:0 and Minor 3+
- Claude can work in its own worktree but when the fixes/enhancement are done, the changes should be put into `*main`
- At the end of every session, commit all changed source files (Python, JSON, HTML, Markdown — NOT .gdoc, .DS_Store, or binary PDFs) and merge the worktree branch into main with `--no-ff` so the user can test.

#### Design Workflow

- when doing `enhancements` / `major refactoring` we will discuss the issues and goals, then we'll work together to developed a multi-task plan.
- After review and approval of a task, a GO will be given - and I expect claude to make the changes with NO PROMPTs (see permissions below).
- With the GO, claude is authorized to make any/all changes.   NO PROMPTs. 

#### Fix/Test Workflow

- When fixing bugs, fix the root cause — don't bypass hooks or add workarounds.
- When unsure about a design decision, state the tradeoff in 2 sentences and ask before implementing.
- Run the relevant test suite (test_stmtIS, test_stmtBS, test_stmtGL) before merging to main. All tests must pass.

#### Permissions & Tool Behavior

- Bash read-only commands (find, grep, ls, cat, head, tail, python3 -c for inspection) are pre-approved — do not prompt.
- Reading any file under `pages/AccountingData/` is pre-approved.
- Writing Python source files under `pages/AccountingData/Notebooks/` is pre-approved.
- JSON data file writes under `pages/AccountingData/2025/` require confirmation only if destructive (overwrite without backup).

#### Coding Style

- No docstrings or multi-line comment blocks. One short inline comment only when the WHY is non-obvious.
- No trailing summaries in responses — I can read the diff.
- Prefer editing existing files over creating new ones.
- No backwards-compatibility shims for removed code.

---

## 2. Running the Application

**Start the Flask editor** (run from `pages/AccountingData/Notebooks/`):

```bash
python utilEditorCmd.py --llcName WBGroupLLC --port 5000
```

Optional flags: `--load` (load existing data), `--debug`, `--notebook` (Jupyter display mode), `--edOpt llc|llcAsset|llcExpRev`.

**Run tests** (from `pages/AccountingData/Notebooks/`):

```bash
python -m tests.test_stmtBS
python -m tests.test_stmtGL
python -m tests.test_stmtIS
```

**Verify path setup** (sanity check all packages are importable):

```bash
python ledger/setup_paths.py
```

---

## 3. Package Layout

All Python source lives under `pages/AccountingData/Notebooks/`. That directory is the **`sys.path` root** — all imports are relative to it.

| Package | Role |
|---|---|
| `docs/` | Architecture/Design/DataFlow/API Flow - MUST READ - see
| `ledger/` | Core double-entry engine: `LLC`, `ledgerDB`, COA, bank, asset/expense/payable/receivable records |
| `stmt/` | Immutable constructed statement objects (BS, IS, GL, OE, PE) — the v0.2 data layer |
| `irs/` | IRS form builders (`Form1065`, `Form8825`, `Form4562`, `Sch_K1`) and PDF population |
| `F1065_K1/` | High-level tax workflow orchestration |
| `ui/` | Flask view wrappers (thin adapters over `stmt/`; owns `templates/`) |
| `util/` | `utilEditSession` (session management), `utilWorkingDB` (temp-file safe edits) |
| | |
| `uillc/` | **Compatibility shim only** — every module re-exports from `ui/`. New code should import from `ui/` directly |

## 3.1 Data Files

| File | Purpose |
|---|---|
| `Accts/llcProfile_WBGroupLLC.json` | Entity metadata: EIN, address, members, tax year |
| `Accts/ChartOfAccounts_WBGroupLLC.json` | Account definitions (assets/liabilities/equity/income/expense) |
| `Accts/llcAssets_WBGroupLLC.json` | Fixed and current asset transactions |
| `Accts/llcExpRev_WBGroupLLC.json` | Operating expenses and rental income |
| `Accts/llcPayables_WBGroupLLC.json` | Accounts payable |
| `Accts/llcReceivables_WBGroupLLC.json` | Accounts receivable |
| `2025/YE_Tax_Records/Forms_IRS/Form1065_FILL.pdf` | Populated IRS Form 1065 output |

---

### 3.1 Path Constants

Every script or notebook begins with `from ledger import setup_paths`. This anchors all paths relative to the file, eliminating hard-coded absolute paths.

```python
setup_paths.TOP             # LLC-WB-Group/ (repo root)
setup_paths.NOTEBOOKS_DIR   # pages/AccountingData/Notebooks/
setup_paths.ACCT_DATA_DIR   # pages/AccountingData/
setup_paths.ACCTS_DIR       # pages/AccountingData/Accts/         (JSON DBs)
setup_paths.IRS_FORMS_DIR   # .../2025/YE_Tax_Records/Forms_IRS/
setup_paths.BANK_STMTS_2025 / BANK_STMTS_2026
```

---

## 4. Architecture / Design

Refer to DOCs under folder: `pages/AccountingData/Notebooks/docs`:


#### Key Conventions

- **Snapshot caching**: `stmt.*.save()` writes JSON to `Stmts/` (read-only cache). The live source of truth is always the `Accts/` JSON DBs.
- **GL merge order**: `llcAssets + llcExpRev + llcPayables + llcReceivables` — all four are folded via `toDoubleEntry()` + `mergeGL()`.
- **Working files**: `utilWorkingDB` copies a live DB to a temp file for safe in-editor edits; `utilEditSession` coordinates these across views.
- **IRS mapping**: `mapIRS2LLC.py` and `stmt.*.nSpaceMap()` map ledger account rows to IRS form line items for PDF population.
- **v0.2 status**: currently on branch `release/v0.2`; `uillc/__version__` is `0.2.0-dev`. See `ROADMAP_v0.2.md` for remaining work items.


### 4.1. Accounting WorkFlow

Overall LLC business design is explained in the follwoing design/workflows.  Services are designed to encapsulate the "Levels of Accounting

````
LLC_AccountingDesign.md		
LLC_AccountingWorkflow.md
````

### 4.2. Data Flow


````
LLC_DataFlowDesign.md     : overall design, understand LLC_
llcDataFlow_HL.mmd        : high level
llcDataFlow_L1_3.mmd
llcDataFlow_L4_6.mmd
llcDataFlow-Claude.mmd
````

Human Readable Diagrams
````
llcDataFlow_HL.svg
llcDataFlow_L1_3.svg
llcDataFlow_L4_6.svg
````

### 4.3. API Control Flow

````
apiFlow_ChangeFieldMap_Form8825.mmdc
apiFlow_DisplayForm8825.mmdc
apiFlow.mmdc
````

Human Readable Diagrams
````
apiFlow_DisplayForm8825.svg
apiFlow.svg
````

### 4.4. 

```
JSON DBs in Accts/          (ledger.*: llcAssets, llcExpRev, llcPayables, llcReceivables)
        ↓
ledger.ledgerGeneral        (double-entry expansion + mergeGL)
        ↓
stmt.*                      (immutable stmtBalanceSheet / stmtIncomeStmt / stmtGeneralLedger / …)
        ↓
ui.*                        (Flask view wrappers — call stmt.* constructors on each load())
        ↓
Flask templates in ui/templates/
```

- **`stmt/` objects are immutable** — attribute writes raise `StmtImmutableError`. `save()` writes a read-only JSON snapshot to `TOP/<dirAccounting>/Stmts/`; it does not mutate the live `Accts/` DBs.
- **`ui/` wrappers** hold no data construction logic. On every `load()`, they pull GL records from the session via `llcReportEngine` and forward them into the corresponding `stmt.*` constructor.
- **`uillc/` is a shim**: `from uillc.X import Y` and `from ui.X import Y` resolve to the same class objects. Prefer `ui.*` in new code.

---

## 5. Core Objects

**LLC** — main bookkeeping object:
```python
from ledger.LLC import LLC
llc = LLC('WBGroupLLC')   # setup_paths.TOP used automatically
```

**Edit session** — wires the LLC's working files into the Flask app:
```python
from util.utilEditSession import utilEditSession
eSession = utilEditSession(llcName='WBGroupLLC', load=True)
```

**Statement objects** (constructed from GL records, never from eSession directly):
```python
from stmt import stmtBalanceSheet, stmtIncomeStmt, stmtGeneralLedger
bs = stmtBalanceSheet(llc, view_by='All')
bs.load()         # returns rows as list-of-dicts
bs.to_DF()        # pandas DataFrame
bs.nSpaceMap()    # flat {(tblID, rowNm, colNm): value} for IRS mapping
```

---

