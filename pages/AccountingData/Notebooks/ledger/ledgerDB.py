import os
import pandas as pd
import numpy as np

from ledger.ledgerObject import ledgerObject

class ledgerDB(ledgerObject):
    '''
    Common access to all LLC DB files
    '''
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

    def FN(self): 
        fn = os.path.join(self.llc.TOP, self.llc.dirAccounting, 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    def toDF(self):
        # list of transactions (dual accounts ['acct', 'Ledger']0 
        tList = self.load()
        if not tList:
            return None
            
        return pd.DataFrame(tList)


    def toGL(self, gl, **kwargs):
        '''
        Convert llc DB dual Accounts per transaction into journal format: 2 posts with 1 acct
        - DB must conform to COA.toRecDict fields
        - DB may be super set of fields 

        Needed: 
        - fromObj.toDF()(
        - fromObj._key(row)
        '''
        fromDF = self.toDF()
        if fromDF is None:
            return None

        # =========== Convert Dual accounts (acct, Ledger) into a single Acct columns        
        
        # ---- dfL make acct = Ledger; clear out Ledger
        dfL = fromDF.copy()
        dfL.acct = dfL.Ledger
        dfL.Ledger = np.nan
        #      Reverse sign of amt depending on aType [Debit/Credit]
        try:
            dfL.aType = fromDF.aType.apply(lambda v : 'Debit' if v == 'Credit' else 'Credit')
        except:
            pass
        
        # ---- df2 already has acct, clear out Ledger
        dfA = fromDF.copy()
        dfA.Ledger = np.nan
        
        df = pd.concat([dfA, dfL])

        # Return a GL with a single acct; 2 entries per transaction; sort by date via tID; reset index
        cols = [c for c in gl.coa.recCols() if c != 'Ledger']
        return df[cols].sort_values(by='tID').reset_index(drop=True)


        
