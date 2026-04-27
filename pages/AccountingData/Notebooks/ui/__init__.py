'''
ui — LLC Editor View Services (Phase 4 refactor of uillc/).

Per DataModelGuide § 3, View Services hold no data construction/wrangling:
all stmt/DB/IRS data objects are constructed upstream in stmt/, ledger/, or
irs/; modules here simply adapt that data for the Flask app.

Timestamp of last change: 2026.04.19
'''

__version__ = "0.2.0-dev"
__version_info__ = (0, 2, 0, "dev")

from ui.llcRecordsView   import llcRecordsView
from ui.llcAssets        import llcAssets
from ui.llcExpRev        import llcExpRev
from ui.llcPayables      import llcPayables
from ui.llcReceivables   import llcReceivables
from ui.stmtIncomeStmt    import stmtIncomeStmt
from ui.stmtBalanceSheet  import stmtBalanceSheet
from ui.stmtGeneralLedger import stmtGeneralLedger
from ui.llcBankView      import llcBankView
from ui.stmtOwnerEquity   import stmtOwnerEquity
from ui.stmtPropertyEquity import stmtPropertyEquity

# llcMgmt depends on Flask — import lazily to avoid errors in pure-Python contexts
try:
    from ui.llcMgmt import llcMgmt
except ImportError:
    pass  # Flask not installed; llcMgmt unavailable
