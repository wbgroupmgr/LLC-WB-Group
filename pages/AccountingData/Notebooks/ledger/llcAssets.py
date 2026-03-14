'''
manage assets owned by LLC
list of owners is stored in accountingData/YEAR/llcAssets_<llcName>.json
'''
import os
from ledger.ledgerObject import ledgerObject
import pandas as pd
import datetime


# class llcAssets
class llcAssets(ledgerObject):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")
            
    def FN(self): 
        fn = os.path.join(self.llc.TOP, self.llc.dirAccounting, 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    """
    -----------------------------------------------
    Services for classification and reconcilation
    - call .fetch() before using services
    -----------------------------------------------
    """
    def fetch(self):
        '''
        Load assets into df
        Load aDict to get keys to match
        '''
        self.df = pd.DataFrame(self.load())
        self.kDict = self._keyDict()

    def _key(self, r):
        # Return tuple of k,index for given row (dt, amt)
        # Return a unique key id for asset entry
        return (f"{r['dt']}_{r.amt}",r.name)
    
    def _keyDict(self):
        
        df = self.df
        df['dt'] = df.dt.apply(lambda v: datetime.datetime.strptime(v, '%Y.%m.%d').strftime('%m/%d/%Y'))

        kList = df.apply(lambda r : self._key(r), axis=1)
        return {r[0]:r[1] for r in kList}
    
    def _matchBk(self, r):
        # Classify transation
        # Match Bank transaction to asset event based on date(dt) and amount(amt)
        # Return tuple of Acct, SubAcct, and Desc
        (bkKey,ndx) = self._key(r)
        try:
            ndx = self.kDict[bkKey]
            aRow = self.df.iloc[ndx]
            subAcct = aRow.oID
            subAcct = subAcct if subAcct[0] == 'p' else ','.join(aRow.stakeholderPct.keys())
            
            return (aRow.acct, subAcct, aRow.desc)
        except:
            return None
        

