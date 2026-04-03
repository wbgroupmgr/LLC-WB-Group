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

    def getGLTaxDict(self):

        glDict = self.entity | self.form1065

        aCount = len(self._assets().properties())

        glDict["total_assets"] = aCount
        glDict["number_of_k1s"] = aCount
        glDict["tax_year"] = str(self.yr)[2:]
        glDict["preparer_date"] = datetime.datetime.now().strftime('%m/%d/%Y')
        return glDict
        

    def _Bank(self, **kwargs):
        self.bk = llcBank(self, debug=self.debug)
        
        # wrangle all transactions to create Accounting books add Acct, AcctSub, TDesc
        self.bk.fetch()
        return self.bk

    def _Profile(self, **kwargs):
        pDict = self._ProfileLoad(**kwargs)
        for k, v in  pDict.items():
            if k == 'YEAR' :
                self.yr = v
            elif k == 'TOP' :
                # Handle ~ in TOP
                v = self._path(v)
            setattr(self, k, v)

    ## ----- llc objects assets, owners, customers
    def _owners(self, **kwargs):
        # Return ornwers obj
        return llcOwners(self, **kwargs)

    def _customers(self, **kwargs):
        # Return ornwers obj
        return llcCustomers(self, **kwargs)

    def _assets(self, **kwargs):
        # Rturn ornwers obj 
        return llcAssets(self, **kwargs)

    ##  ----- llc lists per object
    def owners(self, **kwargs):
        # Return list of entries in ownerDB
        return self._owners(**kwargs).load()

    def customers(self, **kwargs):
        return self._customers(**kwargs).load()

    def assets(self, **kwargs):
        #Return list of entries in ownerDB
        try:
            return self.aObj
        except:
            # initialize assets  & fetch assets for downstream services
            self.aObj = self._assets(**kwargs)
            # initialize aobj.df
            self.aObj.fetch()
            # return as list of dicts
            return self.aObj.df.to_dict(orient='records')

    def acctDir(self, **kwargs):
        '''
        Get AccountingData directories
        '''
        # Save entity information

        # Top of AccountingData, based on year
        acctDIR = os.path.join(self.TOP, self.dirAccounting, str(self.yr))
        
        dir = kwargs.get('dirName', 'acctTop')
        if dir == 'acctTop' : 
            return acctDIR
        elif dir == 'ye' : 
            # REeturn YE Records dir for the given year
            return os.path.join(acctDIR, 'YE_Tax_Records')


    def acctsDF(self):
        bk = self._Bank()
        glDF = bk.df.groupby(['Acct']).amt.sum()
        glDF.loc[f'Balance'] = glDF.sum()
        return glDF

    
                