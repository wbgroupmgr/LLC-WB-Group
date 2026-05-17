'''
manage customers of LLC
list of owners is stored in accountingData/YEAR/llcCustomers_<llcName>.json
'''
import os
from ledger.ledgerObject import ledgerObject

class llcCustomers(ledgerObject):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

    def FN(self):
        fn = os.path.join(self.llc.acctDir(), 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    # ── _to_IRS : IRS2LLC provisioning declaration ──────────────────────────
    # Rental LLC: customers do NOT directly provision cells on Form1065,
    # Sch_K1 or Form4562.  Customer-side aggregates (rent collected, A/R)
    # flow through the Income Statement / Balance Sheet aggregators, which
    # publish them under stmtIncomeStmt / stmtBalanceSheet._to_IRS.  So this
    # hook intentionally returns an empty list — reserved for a future
    # Form 1099-NEC / 1099-MISC pipeline.
    def _to_IRS(self, formObj):
        '''Return [] — customers have no direct 1065/K-1/4562 bindings.'''
        return []
