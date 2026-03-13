'''
manage customers of LLC
list of owners is stored in accountingData/YEAR/llcCustomers_<llcName>.json
'''
from ledger.ledgerObject import ledgerObject

class llcCustomers(ledgerObject):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

