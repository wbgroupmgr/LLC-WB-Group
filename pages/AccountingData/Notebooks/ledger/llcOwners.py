# class llcOwners
'''
manage owners of LLC
list of owners is stored in accountingData/YEAR/llcOwners_<llcName>.json
'''

import os
from ledger.ledgerObject import ledgerObject

class llcOwners(ledgerObject):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

    def FN(self): 
        fn = os.path.join(self.llc.TOP, self.llc.dirAccounting, 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

        
