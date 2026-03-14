# class ledgerClassify
import pandas as pd
import numpy as np
import json
import re

from ledger.llcCustomers import llcCustomers
from ledger.llcOwners import llcOwners

class ledgerClassify(object):
    '''
    Accounting Practices / Statements
    - input is Wells Fargo DF of business account, columns: dt, amt(+/-), C1, C2, desc

    CLASSIFICATION WORK FLOW
    .classifyTransaction
    -> ._isSpecial(row)  :: handle investments, non Exp/Inc items
    -> ._isCust(desc) :: handle known customer income
       -> ._isinDesc(desc) :: regex pattern
    -> ._isOwner(desc) :: handle if owner name in transaction 
       -> ._isinDesc(desc) :: regex pattern
    -> ._classifyExpense(r)
       -> ._isSupplier(desc) :: bank phrase PURCHASE AUTHORIZED
       -> ._isPurchase(desc) :: parse desc into Tranaction Identifier
       -> ._isMatch(desc) :: match patterns into specific AcctSub, TDesc
       -> Acct Misc
    -> ._classifyIncome(r)
    '''
    def __init__(self, llcObj, **kwargs):
        self.oID = self.__class__.__name__
        self.debug = kwargs.get('debug', False)
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
        
        # if a Customer ID is in the description - classify as cash
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
        d = r.desc.lower()

        # Eval special cases 1st - assets purchases, investments
        tDict = self._isSpecial(r)
        if tDict : return tDict
        
        if r.TransType == 'Exp': 
            tDict = self._classifyExpense(d, **kwargs)
            if tDict : return tDict
            
            tDict = self._isExpRev(r, **kwargs)
            if tDict: return tDict
            
        else:
            tDict = self._classifyIncome(d, **kwargs)
            if tDict: return tDict

            tDict = self._isExpRev(r, **kwargs)
            if tDict: return tDict

        return self.acctDict('Acct.Cash.Misc','Misc',f"Misc Income")

    def _isSpecial(self, r):
        '''
        Handle Special transactions: investments, assets, bank actions
        Match assets against bank transactions
        '''
        clsTuple = self.llc.aObj._matchBk(r)
        if clsTuple :
            return self.acctDict(*clsTuple)
        return None

        if False:
            owners = llcOwners(self.llc)
            if r['dt']== '08/20/2025' and r.amt == 219000 :
                oDict = owners.find(by = 'Francis X')
                return self.acctDict(f'Acct.Cash.Investment',oDict['oID'],f"Initial Investment by member {oDict['nm']}")
            if r['dt'] == '08/26/2025' and r.amt == -213936.95	 :
                oDict = owners.find(by = 'Francis X')
                return self.acctDict(f'Acct.Asset.Purchase',self.llc.objName,f"Purchase Property: 805 High Mesa")
        
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
        return self.acctDict('Acct.Cash.Misc','Misc',f"Misc Expense")

    def _isSupplier(self, d):
        if 'purchase authorized' in d:
            supplier = d.split('on')[1].strip()
        elif 'purchase return authorized' in d:
            supplier = d.split('on')[1].strip()

    def _isMatch(self, d):
        '''
        # Process repeating expenses
        # Handle special matches, venmo & 251022 ==> repaire
        '''
        expKWDict = {"comwsc": ['Acct.Cash.Util','Water','Pay Monthly Util'],
                     "pedernales" :['Acct.Cash.Util','Elec','Pay Monthly Util'],
                     "dispre.al" : ['Acct.Cash.Util','Waste','Pay Monthly Util'],
                     "allstate" : ['Acct.Cash.Util','Ins_Home','Pay Monthly Util'],
                     "check # 101" : ['Acct.Cash.Util','Water','Pay Monthly Util'],
                     "check # 102" : ['Acct.Cash.Util','Util','Pay Electrician Repair Outlet'],
                     "venmo&&251022" : ['Acct.Cash.Expense','Maintenance','Repair Utility Outlet,Electrician'],
                     "promotion bonus" : ['Acct.Interest.Income','Bank','Bank Promotion for account openning'],
                     "wfb opening deposit" : ['Acct.Cash.Investment','o20250801-1','Initial see to open account'],
                    }
        for k,expDict in expKWDict.items():
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
            # Match patterns based on expense description
            patPurchase = r'^.*(purchase authorized|purchase return authorized).*?\s+on\s+(\S+)\s*(.*)'
            pList = [dict(pat = patPurchase, dt=2, who=3)]
            
        for pDict in pList:
            
            mList = re.split(pDict['pat'], d)
            if mList is None :
                continue
                
            try:
                dt = mList[pDict['dt']]
                who = mList[pDict['who']]
            except:
                #print("D120 isPurchase", mList)
                # Unknown pattern
                continue            
    
            tDict = self.acctDict('Acct.Cash.Expense',
                             who.split()[0],
                             f"Expense: {dt} {who}")
            #print("D122 isPurchase", tDict, d)
            return tDict
            
        return None

        
    def _isCust(self, d):
        '''
        Verify if customer transaction
        '''
        for cDict in llcCustomers(llc=self.llc, iterate=True):
            if self._isinDesc(d, cDict['nm']) : return cDict['oID']
        return None

    def _isOwner(self, d):
        '''
        Verify if owner transaction
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
        

    