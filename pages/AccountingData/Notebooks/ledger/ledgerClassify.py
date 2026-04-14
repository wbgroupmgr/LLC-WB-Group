# class ledgerClassify
import pandas as pd
import numpy as np
import json
import re

from ledger.llcCustomers import llcCustomers
from ledger.llcOwners import llcOwners

# ---- patterns within transaction.desc to map to acct, acct 
class ledgerClassify(object):
    '''
    Accounting Practices / Statements
    - input is Wells Fargo DF of business account, columns: dt, amt(+/-), C1, C2, desc

    CLASSIFICATION WORK FLOW
    .classifyTransaction
    -> ._isEquity(row)  :: handle investments, non Exp/Inc items
    -> ._isCust(desc) :: handle known customer income
       -> ._isinDesc(desc) :: Cust isinDesc; regex pattern
    -> ._isOwner(desc) :: handle if owner name in transaction 
       -> ._isinDesc(desc) :: Owner Nm isinDesc; regex pattern
    -> ._classifyExpense(r)
       -> ._isSupplier(desc) :: bank phrase PURCHASE AUTHORIZED
       -> ._isPurchase(desc) :: parse desc into Tranaction Identifier
       -> ._isMatch(desc) :: create AcctSub, TDesc - match patterns
       -> Acct Misc
    -> ._classifyIncome(r)
    '''
    def __init__(self, llcObj, **kwargs):
        self.oID = self.__class__.__name__
        self.debug = kwargs.get('debug', False)
        self.expKWDict = kwargs['patterns']
        if llcObj is None: raise Exception(f"{self.oID}: bad llcObj on init")
        self.llc = llcObj        
        if self.debug: print(f"{self.oID} {type(self).__name__} Init Done")

    def acctDict(self, acctStr, subStr, descStr, **kwargs):
        aDict = dict(Acct = acctStr,
                    AcctSub = subStr,
                    TDesc = descStr,
                   )
        for k,v in kwargs.items(): aDict[k] = v
        return aDict

    def _isinDesc(self, desc, patternList):
        
        vList = [v.lower() for v in patternList]
        for v in vList:
            if v not in desc : continue
            return True
        return False

    def _isExpRev(self, r, **kwargs):
        '''
        Transaction is either Rental Income/Expense
        '''

        if r.TransType == 'Exp' :
            exp_rev = 'Expense'
            tDesc = 'Rental Expense'
        else :
            exp_rev = 'Income'
            tDesc = 'Rental Income'

        d = r.desc.lower()
        
        # if a Customer ID is in the description - classify as cash income
        custID = self._isCust(d)
        if custID:
            tDict = self.acctDict(f'Acct.Cash.{exp_rev}',custID,tDesc)
            return tDict

        # if an owner ID is in the description - classify as cash
        ownID = self._isOwner(d)
        if ownID: 
            tDict = self.acctDict(f'Acct.Cash.{exp_rev}',ownID,tDesc)
        else:
            tDict = None

    def classifyTransaction(self, r, **kwargs):
        '''
        Classify transaction
        '''
        debug = True if self.debug == 'details' else False
        
        d = r.desc.lower()
        # Eval special cases 1st - assets purchases, investments
        tDict = self._isEquity(r)
        if tDict : 
            if debug : print(f"{self.oID}/classify Special {tDict['Acct']} {r['dt']} {r['amt']}")
            return tDict
        
        if r.TransType == 'Exp': 
            tDict = self._classifyExpense(d, **kwargs)
            if tDict : 
                if debug : print(f"{self.oID}/classify  Expense {tDict['Acct']} {r['dt']} {r['amt']}")
                return tDict
            
            tDict = self._isExpRev(r, **kwargs)
            if tDict: 
                if debug : print(f"{self.oID}/classify ExpRev {tDict['Acct']} {r['dt']} {r['amt']}")
                return tDict
            
        else:
            tDict = self._classifyIncome(d, **kwargs)
            if tDict: 
                if debug : print(f"{self.oID}/classify Income  {tDict['Acct']} {r['dt']} {r['amt']}")
                return tDict

            tDict = self._isExpRev(r, **kwargs)
            if tDict: 
                if debug : print(f"{self.oID}/classify IncRev {tDict['Acct']} {r['dt']} {r['amt']}")
                return tDict
        
        if debug : print(f"{self.oID}/classify Misc.    Acct.None.Error {json.dumps(r)}")
        return self.acctDict('Acct.Cash.Misc','Misc',f"Misc Income")

    def _isEquity(self, r):
        '''
        Handle Equity transactions: investments, assets, bank actions
        Match assets against bank transactions
        '''
        clsTuple = self.llc.aObj._matchBk(r)
        if clsTuple :
            return self.acctDict(*clsTuple)
        return None

        

    def _wrangleBkDesc(self, s : str):
        '''
        wrangle bank (Wells Fargo) expense descriptions 
        - PURCHASE AUTHORIZED ON ...
        - PURCHASE RETURN AUTHORIZED ON 1
        '''
        if pd.isna(s) : return s
            
        pat = r'ON \S* (.*)'
        m = re.search(pat, s)
        if m : 
            return('Approved Purchse ' + ' '.join(m.group(1).split()[0:4]))
        else:
            return s


    def _classifyExpense(self, d, **kwargs):
        '''
        Classify transactions
        - transfers
        - bank item
        - others (divident, interest, etc..)
        '''
        tDict = self._isSupplier(d)
        if tDict : return tDict

        tDict = self._isPurchase(d)
        if tDict : return tDict
        
        tDict = self._isMatch(d)
        if tDict : return tDict

        

        # Expense, unknown/misc
        return self.acctDict('Acct.Exp.Other',"Unknown", self._wrangleBkDesc(d))

    def _isSupplier(self, d):
        if 'purchase authorized' in d:
            supplier = d.split('on')[1].strip()
        elif 'purchase return authorized' in d:
            supplier = d.split('on')[1].strip()

    def _isMatch(self, d, **kwargs):
        '''
        # Process repeating expenses
        # Handle special matches, venmo & 251022 ==> repaire
        '''

        kwDict = kwargs.get('kwDict', self.expKWDict)

        for k,expDict in kwDict.items():
            ## Special case of venmo payment
            if '&&' in k:
                kList = k.split('&&')
                k = kList[0]
                k2 = kList[1]
                if not( k2 in d ) : continue
            if k in d :
                acct = expDict[0]
                subID = expDict[1]
                desc = d if expDict[2] is None else expDict[2]
                return self.acctDict(acct,subID,desc)
        return None

        
    def _isPurchase(self, d, pList=None):
        if pList is None:
            # Match patterns based on expense description : PURCHASE*. match to vendor name in bank desc
            patPurchase = r'^.*(purchase authorized|purchase return authorized).*?\s+on\s+(\S+)\s*(.*)'
            pList = [dict(pat = patPurchase, dt=2, who=3)]
            
        for pDict in pList:
            
            mList = re.split(pDict['pat'], d)
            if mList is None :
                continue
            
            # Matches a property purchased    
            try:
                dt = mList[pDict['dt']]
                who = mList[pDict['who']]
            except:
                #print("D120 isPurchase", mList)
                # Unknown pattern
                continue            
    
            tDict = self.acctDict('Acct.Exp.Other',
                             who.split()[0],
                             f"Expense: {dt} {who}")
            #print("D122 isPurchase", tDict, d)
            return tDict
            
        return None

        
    def _isCust(self, d):
        '''
        Match transaction if Cust Nm is in bank description, return Cust dict
        '''
        for cDict in llcCustomers(llc=self.llc, iterate=True):
            if self._isinDesc(d, cDict['nm']) : return cDict['oID']
        return None

    def _isOwner(self, d):
        '''
        Match transaction if Owner Nm is in bank description, return Owner dict
        '''
        for oDict in llcOwners(llc=self.llc, iterate=True):
            if self._isinDesc(d, oDict['nm']) : 
                return oDict['oID']
            if self._isinDesc(d, oDict['kw']) : 
                return oDict['oID']
        return None

    def _classifyIncome(self, d, **kwargs):
        '''
        Classify transactions
        - transfers
        - bank item
        - others (divident, interest, etc..)
        '''
        # Purchase returns
        tDict = self._isPurchase(d)
        if tDict : return tDict

        # Other types of deposits
        tDict = self._isMatch(d)
        if tDict : return tDict
        
        return None 
        

    