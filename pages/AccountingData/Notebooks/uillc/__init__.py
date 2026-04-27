'''
uillc — Compatibility shim package (Phase 4 DataModelGuide refactor).

The real view-service implementations now live under `ui/`.  This package
re-exports them so any caller that still imports `uillc.<X>` keeps working.

New code should import directly from `ui`.

Timestamp of last change: 2026.04.19
'''

__version__ = "0.2.0-dev"
__version_info__ = (0, 2, 0, "dev")

# Re-export the same public surface as ui.__init__ for drop-in parity.
from ui.llcRecordsView    import llcRecordsView
from ui.llcAssets         import llcAssets
from ui.llcExpRev         import llcExpRev
from ui.llcPayables       import llcPayables
from ui.llcReceivables    import llcReceivables
from ui.stmtIncomeStmt     import stmtIncomeStmt
from ui.stmtBalanceSheet   import stmtBalanceSheet
from ui.stmtGeneralLedger  import stmtGeneralLedger
from ui.llcBankView       import llcBankView
from ui.stmtOwnerEquity    import stmtOwnerEquity
from ui.stmtPropertyEquity import stmtPropertyEquity

# llcMgmt depends on Flask — import lazily to avoid errors in pure-Python contexts
try:
    from ui.llcMgmt import llcMgmt
except ImportError:
    pass  # Flask not installed; llcMgmt unavailable
