'''
manage bank of LLC
this version is based on WellsFargo business bank account
'''

import os
from pathlib import Path
import pandas as pd

from ledger.ledgerObject import ledgerObject
from ledger.ledgerClassify import ledgerClassify

# class llcBank
class llcBank(ledgerObject):
    '''
    - import LLC bank (Wells Fargo) csv transactions period
    - Merge csv with ledger - remove duplicates
    - classify all transactions into expense type
    - monthly Reconcilation
    '''
    def __init__(self, llc, **kwargs):
        self.xx = "llcBank"
        super().__init__(llc, **kwargs)
        if self.debug: print(f"{self.oID} {type(self).__name__} Init Done")

    def dwnLd(self):
        DIR = os.path.join(Path.home(), 'Downloads')
        return DIR

    def dwnLdCSV(self, **kwargs):
        DIR = self.dwnLd()
        csvList = [b for b in os.listdir(DIR) if ('csv' in b) and ('Checking' in b)]
        csvBN = csvList[kwargs.get('csvIndex',0)]
        if self.debug : print(f"{self.oID} dwnLdCSV: importBankCSV csvBN:", csvBN)
        return os.path.join(DIR, csvBN)

    def importBankCSV(self, **kwargs):
        self.df = pd.read_csv(self.dwnLdCSV(**kwargs), index_col=False, header=None, 
                              names=['dt', 'amt', 'C2', 'CheckNo','desc'])
        self.df['TransType'] = self.df.amt.apply(lambda v : 'Exp' if v < 0 else 'Rev')

    def bkFN(self):
        DIR = os.path.join(self.dirDara, 'BankStmts')
        BN = f"{self.llcName}-BankStmt.csv"
        return os.path.join(DIR, BN)

    def saveBk(self):
        self.df.to_csv(os.bkFN(), index=False)
        

    def wrangleLedger(self):
        '''
        Classify all transactions with ledgerClassify, add columns: Acct, AcctSub and  TDesc
        '''
        lc = ledgerClassify(self.llc, debug=self.debug)
        lList = self.df.apply(lambda r: lc.classifyTransaction(r), axis=1)
        return self.df.join(pd.DataFrame(list(lList)))

    def summarize(self, **kwargs):
        self.importBankCSV(**kwargs)
        self.df = self.wrangleLedger()
        return