'''
manage bank of LLC
this version is based on WellsFargo business bank account
'''

import os
from pathlib import Path
import pandas as pd
import json
import datetime

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

    def csvDIR(self):
        return os.path.join(self.llc.TOP, self.llc.dirAccounting, str(self.llc.yr), 'BankStmts')

    def dwnLdCSV(self, **kwargs):
        DIR = self.csvDIR()
        csvList = [b for b in os.listdir(DIR) if ('csv' in b) and ('.csv' in b)]
        try:
            csvBN = csvList[kwargs.get('csvIndex',-1)]
        except Exception as err:
            print("ERROR: No Bank CSV file found", DIR)
            return None
        if self.debug : print(f"{self.oID} dwnLdCSV: importBankCSV csvBN:", csvBN)
        return os.path.join(DIR, csvBN)

    def importBankCSV(self, **kwargs):
        csvFN = self.dwnLdCSV(**kwargs)
        if csvFN is None:
            # No bank entries
            self.df = pd.DataFrame()
            return
        self.df = pd.read_csv(csvFN, index_col=False, header=None, 
                              names=['dt', 'amt', 'C2', 'CheckNo','desc'])
        if self.debug: print("llcBank CSV Loaded", csvFN)

        # Add field TransType
        self.df['TransType'] = self.df.amt.apply(lambda v : 'Exp' if v < 0 else 'Rev')

        # Wrangle dt into format %Y.%m.%d
        self.df['dt'] = self.df['dt'].apply(lambda v: datetime.datetime.strptime(v, '%m/%d/%Y').strftime('%Y.%m.%d'))

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
        self.llc.assets()
        self.llc.aObj.fetch()
        if self.debug: 
            print(f"{self.oID}.wrangleLedger: llc assets:{len(self.llc.assets().load())}")
            print(f"{self.oID}.wrangleLedger: llc owners:{len(self.llc.aObj.df)}")
            print(f"{self.oID}.wrangleLedger: llc customers:{len(self.llc.customers())}")
        lc = ledgerClassify(self.llc, debug=self.debug)
        #lList = self.df.apply(lambda r: lc.classifyTransaction(r), axis=1)

        ## Classify each entry, some transactions may have N accts to 1 bank item
        transList = []
        for i,r in self.df.iterrows():
            tList = lc.classifyTransaction(r)
            if not isinstance(tList,list) : 
                # Older versions return tDict, convert to list
                tList = [tList]
            for tDict in tList:
                # FIX: 2026.04 -handle 1 to N, record Multi acct per row
                tDict =  {**r , **tDict}
                transList.append(tDict)

        # Create general ledger
        glDF = pd.DataFrame(transList)
        
        if self.debug: 
            print(f"{self.oID}.wrangleLedger: transList:{len(transList)}")
            miscNum = glDF.groupby('Acct').Acct.count().loc['Acct.Cash.Misc'] 
            print(f"{self.oID}.wrangleLedger: {'*'*10} Misc:{miscNum} Potential New, unClassified Ttansactions{'*'*5}")

        # Return General Ledger - all Transactions
        return glDF

    def fetch(self, **kwargs):
        self.importBankCSV(**kwargs)
        self.df = self.wrangleLedger()
        return