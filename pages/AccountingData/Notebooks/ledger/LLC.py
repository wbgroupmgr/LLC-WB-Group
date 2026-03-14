# class LLC Bookkeeping
import os
from pathlib import Path
import datetime
import json

from ledger.ledgerObject import ledgerObject

from ledger.llcOwners import llcOwners
from ledger.llcCustomers import llcCustomers
from ledger.llcAssets import llcAssets

from ledger.llcBank import llcBank

class LLC(object):
    '''
    LLC Bookkeeping
    TopDir : <llcDIR> :: basename is the llcName
    Profile : <llcDIR>/llcProfile_<llcName>.json
    Accounting: <llcDIR>/pages/AccountingData/YEAR/files
    LLC Bank : class llcBank - defaults to Wells Fargo account
    Py LLL Notebook: <llcDIR>/Notebooks

    This LLC object is owned by the LLC
    '''
    def __init__(self, llc, **kwargs):
        self.oID = self.__class__.__name__
        self.debug = kwargs.get('debug', False)
        self.objName = llc
        #super().__init__(llc, **kwargs)
        
        ###--- load profile ---
        if self.debug: print(f"llc:{self.oID} init load _Profile")

        # Set year before profile as default, profile may contain YEAR:xxxx
        self._Profile(**kwargs)
        
        try:
            # Use profile year
            self.yr = self.YEAR
        except:
            # Use current year
            self.yr = datetime.datetime.now().year

        self.debug = kwargs.get('debug', self.debug)

        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

    def _path(self, p):
        # use expanduser() to expand path with ~
        return Path(p).expanduser()
        
    def _ProfileLoad(self, **kwargs):
        '''
        Load LLC profile that points to where the LLC directory and data is
        ProfileDir = ../<objName>.json
        '''
        BN = f"llcProfile_{self.objName}.json"
        dirTOP = kwargs.get('top', os.path.join(Path.cwd().parent))
        FN = kwargs.get('FN_profile', os.path.join(dirTOP, BN))
                        

        if self.debug: print(f"{self.oID} llcProfile FN {FN}")
        if kwargs.get('saveProfile', False):
            pDict = dict(dirLLC = self.dirLLC,
                         dirData = self.dirData)
            
            with open(FN, 'w') as fio:
                json.dump(pDict, fio)
            return pDict
            
        with open(FN, 'r') as fio:
            pDict = json.load(fio)
            if self.debug : print("Profile loaded", FN)
        return pDict

    def _Bank(self, **kwargs):
        self.bk = llcBank(self, debug=self.debug)
        
        # wrangle all transactions to create Accounting books add Acct, AcctSub, TDesc
        self.bk.fetch()

    def _Profile(self, **kwargs):
        pDict = self._ProfileLoad(**kwargs)
        for k, v in  pDict.items():
            if k == 'YEAR' :
                self.yr = v
            elif k == 'TOP' :
                # Handle ~ in TOP
                v = self._path(v)
            setattr(self, k, v)

    def owners(self, **kwargs):
        return llcOwners(self, debug = self.debug).load()

    def customers(self, **kargs):
        return llcCustomers(self, debug=self.debug).load()

    def assets(self, **kwargs):
        return llcAssets(self, debug=self.debug).load()
    
                