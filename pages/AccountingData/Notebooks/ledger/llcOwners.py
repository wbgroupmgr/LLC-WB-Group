# class llcOwners
from ledger.ledgerObject import ledgerObject
'''
manage owners of LLC
list of owners is stored in accountingData/YEAR/llcOwners_<llcName>.json
'''

class llcOwners(ledgerObject):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")
        
