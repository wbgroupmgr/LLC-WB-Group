'''
Chart Of Accounts DB

- coa.get(acct) -> dict(acctCat, acctSub, acctNum, acctDesc)

'''

import pandas as pd
import numpy as np
from typing import Any, Dict, List
from ledger.ledgerDB import ledgerDB


class ChartOfAccounts(ledgerDB):
    '''
    Chart of Accounts (COA) - dict for checking if entry is within the COA
    '''
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

        # Standard llc object DB to dbKey
        self.dbNmDict = dict(llcAssets = 'as',
                         llcExpenses = 'ex',
                         llcCustomers = 'cs',
                         llcOwners = 'ur',
                         llcBank = 'bk')

    def load(self):
        # Return list of COA accounts details
        return self.loadAll()['coaDict']

    def loadAll(self):
        # Return list of COA accounts details
        return super().load()

    def get(self, acct):

        # Access local copy
        try:
            d = self.coaDict
        except:
            self.coaDict = self.load()
            d = self.coaDict

        # Look for acct
        try:
            return d[acct]
        except:
            #print(f"{self.oID} ERROR: acct:{acct} was not found in ChartOfAccounts DB")
            return None


    ## -------------- Util to get Category, ID, acctType

    def _Cat(self, acct):
        aDict = self.get(acct)
        try: 
            l = acct.split('.')
            cat = '.'.join(l[0:2])
            s = '.'.join(l[2:])
            return cat,s
        except:
            return f"Bad_{acct}", 'na'

    def _ID(self, acct):
        try:
            return self.get(acct)['acctID']
        except:
            return '0000'

    def _Type(self, acct):
        '''
        Map acct form ('Acct.x.y.c') -> Accountint type
        '''
        aType = ['na', 'Asset', 'Liability', 'Equity', 'Income', 'Expense', 'Appreciation']

        aDict = self.get(acct)
        if aDict is None : 
            return f"Bad_{acct}"
        try: 
            aID = self._ID(acct)
            i = int(aID[0])
            return aType[i]
        except:
            return f"Bad_{acct}"

    def toAcctType(self, recDict: Dict[str, Any], fromField=None) -> List[Dict[str, Any]]:
        '''
        Add field acctType to transaction record (dict)
        determine acctType based on 
        Debit :: Ledger
        Credit :: acct

        Input : transaction Dict that constins atype(Debit/Credit) and acct/Ledger (account URL)
        '''
        tDict = dict(recDict)
        if fromField is None:
            # determine account type based on Debit/Credit
            aType = tDict.get('aType')
            if aType == 'Debit' :
                acct = tDict.get('Ledger')
            else:
                acct = tDict.get('acct')
        else:                
            # Force account type
            acct = tDict.get(fromField)
            
        acct_type = self._Type(acct)
        tDict['acctType'] = acct_type
        return tDict
        
        
    def toDF(self):
        coaDF = pd.DataFrame(self.load()).transpose()
        coaDF['acctType'] = coaDF.apply(lambda r : self._Type(r.name),axis=1)
        return coaDF
        
    def toRecDict(self, **kwargs):
        '''
        Create std default GL transaction record 
        - defines the standard transactio record within all DB

        
        '''
        recDict = dict(
            dt = kwargs.get('dt', np.nan),   # Date: The date the expense was paid.
            desc  = kwargs.get('desc', np.nan), # : Description: A short clear description of the item or service 
                                         # (e.g., "HVAC repair," "Monthly Landscaping").
            amt  = kwargs.get('amt', np.nan) ,#  :  transaction amount, always positive, see aType
            aType  = kwargs.get('aType', np.nan), # :  Debit or Credit
            

        # ------------- account details
            acct  = kwargs.get('acct', np.nan), #  : AcctID:  Node1.Node2.Node3 ...  .NodeN
                                          # Refer to llcCOA services for approved accounts. 
                                          # Within DB, acct may be : <nodeSet>.<extraSet>
                                          #- within GL these are seperated into gl.acct and gl.acctExtra
                                          # Nodes beyond the approved set are application specific
                                          # Used in reconciling, ignored by financial bookkeeping pipeline
            Ledger = kwargs.get('Ledger',  np.nan), # dual acct'ing :  acct <-> ledger
            acctMajor  = kwargs.get('acctMajor', np.nan), # COA major categories via COA services 
            acctMinor  = kwargs.get('acctMinor', np.nan), # : Key reference per transaction - varies by account
                                          # Acct.Exp : supplier, purchaseOrder[Opt], 
                                          # Acct.Fixed : Owner
                                          # Acct.Rev : Customer or Org (e.g. Bank)
            acctSub  = kwargs.get('acctSub', np.nan), # - Optional, sub accts info: form Extra1.Extra2 ... ExtraN
                                          # sepearated by '._'
                                          # Node1.Node2 ... NodeN[._Extra1.Extra2 ... ExtraN]
                                          # acct <== Node1.Node2 ... NodeN._Extra1.Extra2 ... ExtraN
                                          # acctSub <== Extra1.Extra2 ... ExtraN
            
        #-------------- Property Reference  -- all properties are stored in llcAssets
            propNm  = kwargs.get('propNm', np.nan), # : short name of Prop - human consumption
            propID  = kwargs.get('propID', np.nan), # nan or real property 
            propAddr  = kwargs.get('propAddr', np.nan), # nan if ref, accual prop address
            propOwners  = kwargs.get('propOwners', np.nan), # nan if ref, accual prop, stakeholderPct
        
        #-------------- Reference within DB
            tID  = kwargs.get('tID', np.nan), # :    transaction key 
            tDB  = kwargs.get('tDB', np.nan), # 

        #------------- Reference original source of transaction
            refDB  = kwargs.get('refDB', np.nan), # : <DBKey>_<transaction Key 
                                          #(dt_amt)> Payment Method: Check #, Credit Card, or Bank Transfer.
            refDoc  = kwargs.get('refDoc', np.nan), # : Hard Copy location/info 
                                          # - Account specific info - varies per account; long details : 
                                          # - supporting Documentation: Receipt or invoice number.
        )
        # Register unknown keywards wihtin kwargs 
        uList = set(recDict.keys()) ^ set(kwargs.keys())
        recDict['_unknown'] = {k:v for k,v in kwargs.items() if k in uList}
        return recDict

    def recCols(self):
        # Transaction standard columns
        return [c for c in self.toRecDict().keys() if c not in ['_unknown']]

    def __repr__(self):
        coaDF = self.toDF()
        return coaDF.reset_index().groupby(['acctType', 'index','acctID']).acctDesc.sum().to_string()


