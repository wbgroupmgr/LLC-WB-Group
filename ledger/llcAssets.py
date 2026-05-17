md = '''

<h1> llcAsset Tips/Guidelines

This DB manages assets owned by LLC
- Fundamental Principle: Assets - Liabilities - Equity = 0 
- list of owners is stored in accountingData/YEAR/llcAssets_<llcName>.json

<h2>Assets DB Classifications
- The  1st letter of oID per entry signifies the `asset type`.
- asset        : 'a' in oID  + Cash investment
- equity       : 'e' in oID  + Purchase capital, property
- liqbility    : 'l' in oID  - Debt of LLC: morgage, debt to owner
- depreciation : 'd' in oID  - Depreciation of an equity 

<h2> Equity Ledger:  Capital Account 
- A running, long-term record on the balance sheet reflecting a member's net interest in the LLC. 
- Tracks value from start to finish.
- is an internal accounting record tracking an owner's equity
- equity = (contributions + profit - losses - draws)
- representing their stake in the company. 

<h2> Ledger investment account
- **capital contribution**
- The actual assets (cash, property, services) injected by a member, 
    - a debit to assets (equity)
    - a credit to the capital account.
- initial or additional cash/assets a member puts into that ledger
- increases the capital account balance. 


<h3>Purpose
The capital account defines ownership percentages and distribution rights. The investment represents the funding source.
Nature: Neither is usually a separate, active bank account, but rather, they are "paper" or software ledger entries. 

<h3> Assets Elements
- Initial Capital Contribution: Initial investment.
- Additional Contributions: Later cash or assets added.
+ Profits / - Losses: Share of earnings.
- Distributions/Draws: Money taken out. 

Asset accounts determine how much a member is owed if they leave, sell their share, or if the business dissolves.

<h2>Balance Sheet Tips/Guidelines

- 3 Assets: 
    - Cash in bank accounts, 
    - property value (land + building
    - Inventory : furniture/appliances.
- Must show the beginning and end-of-year values of assets, liabilities, and equity (capital accounts).
- Liabilities: Mortgages/loans, accounts payable, and security deposits held for tenants.
- Equity: Total assets minus total liabilities (capital invested + retained earnings).
    - less running accumulated depreciation
    - Depreciation: debit: depreciation expense /  credit accumulated depreciation.

<h3> Key Requirements for 1065 Financials
- **Schedule L (Balance Sheet)**:
    - Required if the LLC has total receipts of $250,000+ or total assets of $1 million+.
    - Even if smaller, filling this out is recommended for accuracy.
- **Schedule M-1 (Reconciliation)**:
    - Reconciles net income per books to taxable income.
    - For example, if you took bonus depreciation on the tax return but not on your internal books, you adjust that here.
- **Schedule M-2 (Capital Accounts)**:
    - Tracks the change in partners' capital accounts based on tax-basis records (not GAAP).
- **Accounting Method**: The financial reports must follow the accounting method (cash or accrual) indicated on the 1065

'''
import os
import pandas as pd
import numpy as np
import datetime

from ledger.ledgerDB import ledgerDB

# Get balances from most ledgers, debit:+ , credit:-
getBal = lambda df : df.apply(lambda r: abs(r.amt) if r.aType == 'Debit' else -abs(r.amt), axis=1)

# Get balances from Asset ledger, debit:- , credit:+
getBalSh = lambda df : df.apply(lambda r: -abs(r.amt) if r.aType == 'Debit' else abs(r.amt), axis=1)
    


class balanceSheet(ledgerDB):
    # Display Balance Sheet
    '''
    - Cash (investment, +amt)   : Acct.Equity.Cash     : Assets.Liability.Cash
    - Cash (payout, -amt).      : Acct.Equity.Cash     : Assets.Equity.Cash
    - Fixed Assets (buy, -amt)  : Acct.Equity.Cash     : Assets.Equity.Fixed.Sold
    - Fixed Assets (sell, +amt) : Acct.Equity.Cash.    : Assets.Equity.Fixed.Tangible.InService
    - AcctSub identifies investment owners (o#) or Asset Values Purchases (p#)
    - YE Gain/Losses shows profit of $1606.13
    '''
    
    ##--- llcAsset DB defines dual accounts per transactions : GenLeder <=> AssetLedger


    #---  Classify Account
    def _clsAL(self, c):
        if 'Equity' in c : return 'Equity'
        elif 'Liability' in c : return 'Liability'
        return 'Asset'
    
    def _abs(self, r, kAmt = 'amt'):
        if 'Costs' in r.Ledger: 
            return r[kAmt]
        return abs(r[kAmt])

    def glAcct(self):
        """
        Gen Ledger View of assets DB accounts - dual accounting GL <-> Account
        """
            
        df = pd.DataFrame(self.load())
    
        # Classify item into Asset type : Asset, Equity, Liability
        df['AL'] = df['Ledger'].apply(lambda c: self._clsAL(c))
        
        # Get Balance for Asset Ledger
        df['bal'] = getBalSh(df)
        
        # Reduct view 
        col = ['dt','aType', 'acct','amt', 'Ledger', 'bal', 'desc','AL', 'propNm', 'propRef','aID']
        return df[col].copy()
        
    def assetsAcct(self):
        """
        Showrt View of assets DB accounts - dual accounting GL <-> Account
        """
            
        df = pd.DataFrame(self.load())
    
        # Classify item into Asset type : Asset, Equity, Liability
        df['AL'] = df['Ledger'].apply(lambda c: self._clsAL(c))
        
        # Get Balance for Asset Ledger
        df['bal'] = getBalSh(df)
        
        # Reduct view 
        ## FIXME - what columns should be used i assetsAccts
        #col = ['dt','aType', 'acct','amt', 'Ledger', 'bal', 'desc','AL', 'propNm', 'propRef', 'aID']
        col = df.columns
        return df[col].copy()
    
    def getBalanceSheet(self):
        """
        Build a Balance Sheet (DF) based on items in the llcAsset DB. 
        - critical was dual accounts : General(accts) <-> Asset(acct) ledgers. 
        - this is driven by the data within the llcAsset DB fields
    
        - Acct : General ledger accounts
        - Ledger : Asset accounts
        """
    
        df = self.assetsAcct()
            
        # Groupby
        grp = df.groupby(['AL', 'Ledger', 'aType']).bal.sum()
        #return grp
        
        # Bal Sheet Accounts Dict
        bsAcctDict = {}
        kAmt = 'bal'
        for level in ['Asset', 'Equity', 'Liability']:
            
            try:
                gDF = pd.DataFrame(grp.loc[level])
                gDF.rename(columns = {kAmt:level}, inplace=True)
            except Exception as err:
                # Create a dummy record for account type
                gDF = pd.DataFrame([{'Ledger':np.nan, 'aType':np.nan, level:np.nan }]).set_index('Ledger', drop=True)
                gDF
           
    
            bsAcctDict[level] =  gDF.reset_index().drop(columns=['aType'])
            # Debug view
            #display(bsAcctDict[level])
    
        # Merge together the account DF's
        alDF = pd.concat(bsAcctDict.values()).set_index('Ledger')
        
        t = alDF.sum(axis=0)
        alDF.loc['Total'] = t
        #alDF.drop(['aType'], inplace=True, axis=1)
        #alDF.set_index('Ledger', drop=True, inplace=True)
        
        df2 = alDF[pd.notnull(alDF.index)].fillna('')
        return df2

# class llcAssets
class llcAssets(balanceSheet):
    
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")
            
    def FN(self): 
        fn = os.path.join(self.llc.acctDir(), 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    def toDF(self):
        return super().toDF()
    
    def toGL(self, gl, **kwargs):
        return super().toGL(gl, **kwargs)
        
    def _BegBal(self):
        '''
        Return annual Beginning Balance
        aDict['acct'] == "Acct.Cash.Balance" and aDict['desc'] = "YR.2025.Beg.Cash"
        '''
        aList = self.load()
        kDesc = f"YR.{self.llc.yr}.Beg.Cash"
        for aDict in aList:
            if aDict['acct'] == 'Acct.Cash.Balance' and  kDesc in aDict['desc'] : 
                return aList[0]['amt']

        print(f"WARNING: No {kDesc} in llcAsset DB,acct = Acct.Cash.Balance. -- default to 0.0")
        return 0.0

    def investments(self):
        self.fetch()
        return [d for d in self.df.to_dict(orient='records') if d['oID'][0].lower() == 'i']

    def properties(self):
        self.fetch()
        return [d for d in self.df.to_dict(orient='records') if d['oID'][0].lower() == 'p']

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
        try:
            len(self.df)
        except:
            self.df = pd.DataFrame(self.load())
            self.kDict = self._keyDict()

    def FIXME_DELETE__key(self, r):
        # Return tuple of k,index for given row (dt, amt)
        # Return a unique key id for asset entry
        return (f"{r['dt']}_{r.amt}",r.name)
    
    def _keyDict(self):
        '''
        # map dt :: amt, return dict dt:amt

        '''
        # Load asset DF
        df = self.df.copy()
        if df.empty or 'dt' not in df.columns:
            return {}
        df.amt = getBal(df)
        # Normalize asset datetime format to match bank format
        df['dt'] = df['dt'].apply(lambda v: datetime.datetime.strptime(v, '%Y.%m.%d').strftime('%m/%d/%Y'))

        # create list of transKey to assetDF.index
        kList = df.apply(lambda r : self._key(r), axis=1)

        # Convert to dict[transKey]
        return {r[0]:r[1] for r in kList}
    
    def _matchBk(self, r):
        # Classify transation
        # Match Bank transaction to asset event based on date(dt) and amount(amt)
        # Return tuple of Acct, SubAcct, and Desc
        (bkKey,ndx) = self._key(r)
        #print("debug_matchBk 262", bkKey, ndx)
        try:
            ndx = self.kDict[bkKey]
            aRow = self.df.iloc[ndx]
            subAcct = aRow.oID
            subAcct = subAcct if subAcct[0] == 'p' else ','.join(aRow.stakeholderPct.keys())
            
            return (aRow.acct, subAcct, aRow.desc)
        except:
            return None
        

