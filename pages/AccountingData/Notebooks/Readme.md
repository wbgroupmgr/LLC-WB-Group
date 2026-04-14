# workspace/ — Claude Working Folder

This is the active working directory for code development and testing with Claude.

## Purpose
Scratch scripts, experiments, and new features are developed here before being
promoted to the main package directories (`ledger/`, `irs/`, etc.).

## Quick Start

Every script or notebook in this folder should begin with:

```python
from ledger import setup_paths
```

`setup_paths` lives in `ledger/` and uses `Path(__file__).parents[N]` to anchor
all paths relative to the file itself — no hard-coded absolute paths needed.

### Available imports after `from ledger import setup_paths`:

```python
from ledger import ledgerDB, llcCOA, LLC, llcBank, llcExpRev
from irs import pdfFill, irsForms, pdfMap
from F1065_K1 import F1065, gl_ledger
from uillc import llcMgmt, llcAssets, llcSession
from util import utilEditSession, utilWorkingDB
```

### Path constants:

| Constant | `parents[N]` | Points to |
|---|---|---|
| `setup_paths.TOP` | `parents[4]` | `LLC-WB-Group/` |
| `setup_paths.NOTEBOOKS_DIR` | `parents[1]` | `Notebooks/` |
| `setup_paths.ACCT_DATA_DIR` | `parents[2]` | `AccountingData/` |
| `setup_paths.ACCTS_DIR` | — | `AccountingData/Accts/` |
| `setup_paths.EXPENSES_DIR` | — | `AccountingData/Expenses/` |
| `setup_paths.BANK_STMTS_2025` | — | `AccountingData/2025/BankStmts/` |
| `setup_paths.BANK_STMTS_2026` | — | `AccountingData/2026/BankStmts/` |
| `setup_paths.TAX_RECORDS_2025` | — | `AccountingData/2025/YE_Tax_Records/` |
| `setup_paths.IRS_FORMS_DIR` | — | `.../YE_Tax_Records/Forms_IRS/` |

### LLC instantiation (no `top` arg needed):

```python
from ledger.LLC import LLC

llc = LLC('WBGroupLLC')   # setup_paths.TOP used automatically as default
```

## Structure

```
workspace/
├── README.md           ← this file
└── <your scripts>.py / .ipynb
```
