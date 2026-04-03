'''
Chart Of Accounts DB

- coa.get(acct) -> dict(acctCat, acctSub, acctNum, acctDesc)

'''

import pandas as pd
from ledger.ledgerDB import ledgerDB


class ChartOfAccounts(ledgerDB):
    '''
    Chart of Accounts (COA) - dict for checking if entry is within the COA
    '''
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")


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
            print(f"{self.oID} ERROR: acct:{acct} was not found in ChartOfAccounts DB")
            return None
            

    def __repr__(self):
        return pd.DataFrame(self.load()).transpose().to_string()
