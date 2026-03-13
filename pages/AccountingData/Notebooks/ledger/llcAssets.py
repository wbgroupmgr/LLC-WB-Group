from ledger.ledgerObject import ledgerObject
'''
manage assets owned by LLC
list of owners is stored in accountingData/YEAR/llcAssets_<llcName>.json
'''


# class llcAssets
class llcAssets(ledgerObject):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")
