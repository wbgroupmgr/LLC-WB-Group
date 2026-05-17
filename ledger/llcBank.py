'''
manage bank of LLC
this version is based on WellsFargo business bank account
'''

import os
from pathlib import Path
import pandas as pd
import numpy as np
import json
import datetime

from ledger.ledgerObject import ledgerObject
from ledger.ledgerClassify import ledgerClassify
from ledger.llcExpRev import llcExpRev
from ledger.llcCOA import ChartOfAccounts as llcCOA

# -------- Heuristic pattern matching : derive info from patterns in desc field
#           infer best acct, acctSub and other info
#           This will need to be updated over time

# ---- patterns within transaction.desc to map to acct, acct 
expKWDict = {"comwsc": ['Acct.Exp.Util','Water','Pay Monthly Util'],
             "pedernales" :['Acct.Exp.Util','Elec','Pay Monthly Util'],
             "dispre.al" : ['Acct.Exp.Util','Waste','Pay Monthly Util'],
             "allstate" : ['Acct.Exp.Util','Ins_Home','Pay Monthly Util'],
             "check # 101" : ['Acct.Exp.Util','Water','Pay Monthly Util'],
             "check # 102" : ['Acct.Exp.Util','Util','Pay Electrician Repair Outlet'],
             "venmo&&251022" : ['Acct.Exp.Repair','Maintenance','Repair Utility Outlet,Electrician'],
             "promotion bonus" : ['Acct.Cash.Bank','Bank','Bank Promotion for account openning'],
             "bankOpen wf opening deposit" : ['Acct.Equity.Owner.Cash','o20250801-1','Initial seed to open account'],    
             "purchase authorized" : ['Acct.Exp.Other',np.nan,'Approved Purchase'],
             "acctverify" : ['Acct.Rev.Fees.Other',np.nan,'Customer payment setup'],
             "nicola" : ['Acct.Rev.Rent','Income.Rent',''],
             "alejandro" : ['Acct.Rev.Rent','Income.Rent',''],
             "zelle from" : ['Acct.Rev.Rent','Income.Rent',''],
             "purchase return" : ['Acct.Exp.Other',np.nan,'Return of materials'],
             "fed#02m03" : ['Acct.Cash.Bank',np.nan,'Owner investment'],
             "withdrawal" : ['Acct.Fixed.Tangible.InService',np.nan,'Property Purchase'],
             "deposit" : ['Acct.Cash.Bank',np.nan,'Owner Investment'],
            }


# Map acct -> Ledger via Bk Stmt acct
mapLedgerDict = {'Acct.Exp.Util': 'Acct.Cash.Bank', 
         'Acct.Exp.Other': 'Acct.Cash.Bank', 
         'Acct.Exp.Repair': 'Acct.Cash.Bank',
         'Acct.Cash.Bank': 'Acct.Equity.Owner.Cash', 
         'Acct.Cash.Bank._Rent' : 'Acct.Rev.OwnerRent',
         'Acct.Cash.Bank._Other':'Acct.Rev.Other',
         'Acct.Cash.Bank._Other.Promotion' : 'Acct.Rev.Other',
         'Acct.Cash.Bank._withdrawal' : 'Acct.Fixed.Tangible.InService' # Bk Stmt is Credit, so reverse
        }


# class llcBank
class llcBank(ledgerObject):
    '''
    Manage bank csv files downloaded from WF (or other bank)
    - import LLC bank (Wells Fargo) csv transactions period
    - Merge csv with ledger - remove duplicates
    - classify all transactions into expense type
    - monthly Reconcilation
    '''
    def __init__(self, llc, **kwargs):
        self.xx = "llcBank"
        super().__init__(llc, **kwargs)
        self.coa = llcCOA(llc)
        self.lc = ledgerClassify(llc, patterns=expKWDict)
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

    def fetch(self, **kwargs):
        self.importBankCSV(**kwargs)
        self.df = self.wrangleLedger()
        return

    def saveBk(self):
        self.df.to_csv(os.bkFN(), index=False)

    def _loadRawDF(self):
        '''
        IMport bk CSV - raw form
        '''
        
        self.importBankCSV()
        df = self.df.sort_values(by='dt', ascending=True).reset_index(drop=True).copy()

        df.amt = abs(df.amt)
        df['aType'] = df.apply(lambda r : 'Debit' if r.TransType == 'Rev' else 'Credit', axis=1)
        
        df.drop(columns = ['TransType', 'CheckNo', 'C2'], inplace=True)
        return df

   
    def _loadRawList(self, rawDF):
        '''
        Load list of transaction Raw Bk Stmt csv -> COA std rec dict (empty)
        - fields dt, abs(amt), aType, desc + 
        ''' 

        # ---- Step 2 : extend transaction with empty COA RecDict fields

        # map each transaction into std coa.toRecDict fields - many will be empty
        rawList = [self.coa.toRecDict(**d) for d in rawDF.to_dict(orient='records')]

        return rawList

    def _loadDescList(self, descRawList):
        # ---- Step 3 :  descList : table of dict with best definition of  acct, acctSub, TDesc - using pattern matching
        #      If None, then no pattern found - review and re-iterate
        #.     acct is used to derive Ledger account (dual accounting)
        #.     use Nodes._Extra to identify Ledger, ie. Extra --> Unique Ledger
        descList = [self.lc._isMatch(desc.lower(), kwDict=expKWDict) for desc in descRawList]

        # ---- Step 3a : check if new transaction have no account
        mList = [desc for desc,d in zip(descRawList, descList) if d is None]
        if len(mList) > 0 :
            print("llcBank.loadRawList: ERROR - No acct for some new transaction")
            print(mList)
            ## Stop workflow until resolvedx
            return None
            
        return descList

    def _mapLedger(self, acct):
        try:
            return mapLedgerDict[acct]
        except:
            print(f"{self.oID} : _mapLedger Failed mapping  acct:{acct} in mapLedgerDict, default")
            return 'Acct.Ledger.Unknown'
        

    def _loadWorkList(self, rawList, acctList):
        '''
        Fill in transaction dict within rawList with account inference from acctList (derived from descList)
        '''
        # Merge 2 lists into the std RecDict
        wList = []
        for tDict,d in zip(rawList, acctList):
            # Update heuristic matching info
            a = d['Acct']
            aMajor = a.split('._')[0]
            tDict['acct'] = aMajor
            tDict['Ledger'] = self._mapLedger(aMajor),
            
            tDict['acctSub'] = d['AcctSub']
            
            bkDesc = tDict['desc']
            erDesc = d['TDesc']
            
            tDict['refDoc'] = bkDesc
            tDict['desc'] = erDesc
        
            # Property info
            tDict['propNm'] = 'H_805HighMesa'
        
            # bank Transaction Info
            tDict['tID'] = f"{tDict['dt']}_{tDict['amt']}"
            tDict['tDB'] = 'llcBank'
        
            # ---- reference the original source : bamk
            tDict['refDB'] = 'llcBank'

            wDict = tDict.copy()
            #del wDict['_unknown']
            
            wList.append(wDict)
        return wList
        
    def load(self):
        '''
        Custom load : convert raw csv into llcExpRev format 
        Input: csv list of transactions
        Output: llcExpRev list of transaction
        '''
        # ----- step 1 : import rawDF :: load csv into raw CSV, raw columns
        rawDF = self._loadRawDF()

        # ----- Step 2 : load rawList
        rawList = self._loadRawList(rawDF)

        # ----- Step 3 : load descList 
        descList = self._loadDescList(rawDF.desc.str.lower())
        if descList is None : return None # Workflow is halted until all accounts are determined.

        # ----- Step 4 : load workList (final transaction list for feed llcExpRev
        return self._loadWorkList(rawList, descList)


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
        lc = self.lc #ledgerClassify(self.llc, debug=self.debug)
        #lList = self.df.apply(lambda r: lc.classifyTransaction(r), axis=1)

        ## Classify each entry, some transactions may have N accts to 1 bank item
        transList = []
        for i,r in self.df.iterrows():
            #--- classify bank transaction based on predefined patterns
            tList = lc.classifyTransaction(r)
            if not isinstance(tList,list) : 
                # Older versions return tDict, convert to list
                tList = [tList]
            for tDict in tList:
                # FIX: 2026.04 -handle 1 to N, record Multi acct per row
                tDict =  {**r , **tDict}

                # wrangle bank expenses to provide more details
                transList.append(tDict)

        # Create general ledger
        glDF = pd.DataFrame(transList)
        
        if self.debug: 
            print(f"{self.oID}.wrangleLedger: transList:{len(transList)}")
            #miscNum = glDF.groupby('Acct').Acct.count().loc['Acct.Cash.Misc'] 
            #print(f"{self.oID}.wrangleLedger: {'*'*10} Misc:{miscNum} Potential New, unClassified Ttansactions{'*'*5}")

        # Return General Ledger - all Transactions
        return glDF

