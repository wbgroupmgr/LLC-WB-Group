# llcRentalTracker — Developer Quick Start

Rental property accounting and tax tracker — Flask web app + future MCP server.

## Setup (first time)

```bash
# 1. Provision the business repo config
python3 wsCmd.py --newBus ~/GDrive/Family/Assets/LLC-WBGroup

# 2. Set up user DB and passphrase
python3 wsCmd.py --setup --llcName WBGroupLLC

# 3. Start local server
LLC_GPG_PASSPHRASE=<pp> python3 wsCmd.py --start --llcName WBGroupLLC
```

## Available imports

```python
from ledger import setup_paths
setup_paths.load_config('WBGroupLLC')   # call once before any LLC usage

from ledger.LLC import LLC
from ledger import ledgerDB, llcCOA, llcBank, llcExpRev
from irs import pdfFill, irsForms, pdfMap
from F1065_K1 import F1065, gl_ledger
from ui import llcMgmt, llcAssets, llcSession
from util import utilEditSession, utilWorkingDB
```

## Path constants (after load_config)

| Constant | Points to |
|---|---|
| `setup_paths.TOP` | business repo root |
| `setup_paths.ACCT_DATA_DIR` | `books/` |
| `setup_paths.ACCTS_DIR` | `books/<year>/Accts/` |
| `setup_paths.EXPENSES_DIR` | `books/<year>/Expenses/` |
| `setup_paths.IRS_FORMS_DIR` | `books/<year>/Forms/` |
| `setup_paths.BANK_STMTS` | `books/<year>/BankStmts/` |
| `setup_paths.YEAR` | current fiscal year (int) |

## LLC instantiation

```python
from ledger import setup_paths
setup_paths.load_config('WBGroupLLC')
from ledger.LLC import LLC
llc = LLC('WBGroupLLC')
```
