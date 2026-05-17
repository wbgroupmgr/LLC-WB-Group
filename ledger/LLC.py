# class LLC Bookkeeping
import os
from pathlib import Path
import datetime
import json

from ledger.ledgerObject import ledgerObject
from ledger.llcCOA import ChartOfAccounts as llccoa

from ledger.llcOwners import llcOwners
from ledger.llcCustomers import llcCustomers
from ledger.llcAssets import llcAssets

from ledger.llcBank import llcBank
from ledger import setup_paths

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

        self.coa = llccoa(self)

        self.debug = kwargs.get('debug', self.debug)

        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

    def _path(self, p):
        # use expanduser() to expand path with ~
        return Path(p).expanduser()
        
    def _ProfileLoad(self, **kwargs):
        '''
        Load LLC profile.

        Resolution order (v0.2.2.7):
          1. kwargs['FN_profile']                              (explicit override)
          2. <setup_paths.ACCTS_DIR>/llcProfile_<name>.json     (canonical)
          3. <kwargs['top'] or setup_paths.TOP>/llcProfile_<name>.json
             (legacy top-level location — retained for backwards compat)
        '''
        BN = f"llcProfile_{self.objName}.json"

        # 1. Explicit override wins
        explicit = kwargs.get('FN_profile')
        if explicit:
            FN = explicit
        else:
            # 2. Canonical location inside Accts/
            canonical_FN = os.path.join(str(setup_paths.ACCTS_DIR), BN)
            # 3. Legacy location at repo TOP
            dirTOP     = kwargs.get('top', setup_paths.TOP)
            legacy_FN  = os.path.join(str(dirTOP), BN)
            FN = canonical_FN if os.path.exists(canonical_FN) else legacy_FN

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

    # ── _to_IRS : IRS2LLC provisioning declaration ──────────────────────────
    # CPA knowledge: the LLC profile (self.entity + self.F1065) publishes
    # every entity-header / business-identification cell that is NOT a
    # financial aggregate.  The knowledge of which profile key goes to
    # which IRS logicalKey lives here (no UI imports; reads only self.*).
    #
    # Binding table per form.  The value is a (source_attr, key) tuple:
    #   source_attr ∈ {"entity", "F1065"}   — maps to self.entity / self.F1065
    #   key          — dict key inside that source
    _IRS_BINDINGS = {
        "Form1065": {
            # Page 1 — Header
            "P1_Hdr_0": ("F1065",  "date_from"),
            "P1_Hdr_1": ("F1065",  "tax_year"),
            "P1_Hdr_2": ("F1065",  "date_to"),
            "P1_Hdr_3": ("F1065",  "tax_year"),
            "P1_Hdr_4": ("entity", "entity_name"),
            "P1_Hdr_5": ("entity", "address"),
            "P1_Hdr_7": ("F1065",  "C_city"),
            "P1_Hdr_8": ("F1065",  "C_state"),
            "P1_Hdr_9": ("F1065",  "C_zip"),
            # Page 1 — Entity info
            "P1_A":     ("F1065",  "principal_activity"),
            "P1_B":     ("F1065",  "B_product"),
            "P1_C":     ("F1065",  "C_busCode"),
            "P1_D":     ("entity", "ein"),
            "P1_E":     ("entity", "date_business_began"),
            # Paid preparer block
            "P1_PP_0":  ("F1065",  "preparer_name"),
            "P1_PP_2":  ("F1065",  "preparer_date"),
            "P1_PP_3":  ("F1065",  "preparer_ptin"),
            "P1_PP_4":  ("F1065",  "preparer_ein"),
            "P1_PP_5":  ("F1065",  "preparer_firm"),
            "P1_PP_6":  ("F1065",  "preparer_addr"),
        },
        "Sch_K1": {
            "K1_EIN":       ("entity", "ein"),
            "K1_TaxYr":     ("F1065",  "tax_year"),
            "K1_PshipNm":   ("entity", "entity_name"),
            "K1_PshipAddr": ("entity", "address"),
        },
        "Form4562": {
            "F4562_Nm":  ("entity", "entity_name"),
            "F4562_EIN": ("entity", "ein"),
            "F4562_Biz": ("F1065",  "principal_activity"),
        },
    }

    def _to_IRS(self, formObj):
        '''
        Return the per-fid IRS bindings this LLC profile provisions
        for ``formObj``.  Invoked by ``irs.mapIRS2LLC._mapIRS2LLC()``.
        '''
        try:
            from irs.mapIRS2LLC import _lk_to_fid
        except ImportError:
            from mapIRS2LLC import _lk_to_fid

        formNm   = getattr(formObj, 'oID', '')
        bindings = self._IRS_BINDINGS.get(formNm, {})
        if not bindings:
            return []
        lk2fid = _lk_to_fid(formObj)

        entity = getattr(self, 'entity', {}) or {}
        f1065  = getattr(self, 'F1065',  {}) or {}
        out = []
        for lk, (src, key) in bindings.items():
            fid = lk2fid.get(lk)
            if not fid:
                continue
            src_dict = entity if src == 'entity' else f1065
            value = src_dict.get(key) if isinstance(src_dict, dict) else None
            out.append({
                'fid':   fid,
                'tbl':   f'LLC.{src}',
                'row':   src,
                'col':   key,
                'value': value,
            })
        return out
