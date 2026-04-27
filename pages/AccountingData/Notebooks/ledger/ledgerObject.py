# class ledgerObject
import os
from pathlib import Path
import json
import datetime

from deepdiff import DeepDiff # Used in __eq__


# ── Uniform Ledger API — raised by stmt*.save() per Q2 resolution ────────────
class InvalidRequestError(Exception):
    '''
    Raised when a caller asks a ledger object to perform an operation that
    is not permitted for that object's role.  Used primarily by immutable
    constructed ``stmt*`` objects to reject ``save()``.
    '''
    pass


class ledgerObject(object):
    '''
    Most ledger objects is a list of properties, ie. dict().
    All objects have field kw 'nm',  'oID'

    Uniform Ledger API (v0.2 DataModelGuide):
        load()        → list[dict]                — raw records (Dual / Single Acct)
        save(tList)   → None                      — persist raw records to JSON
                                                    stmt*  overrides → raises InvalidRequestError
        to_DF()       → pd.DataFrame              — raw records, index=tID when available
        to_agg(...)   → {'table': DataFrame,      — aggregated view + placeholder for
                         'extraFields': dict}       non-numeric context injected by to_IRS.
                       kwargs: filterDict=, by=, aggDict=, pretty=
                       by ∈ {'Trial', 'BalSh', 'IncStmt', 'custom:[list]'}
        to_IRS()      → list[dict]                — default: one dict per entity row,
                                                    keyed by entity ID.  stmt* overrides
                                                    return a flat Book-field dict.
    '''
    def __init__(self, llc, **kwargs):
        self.oID = self.__class__.__name__
        self.debug = kwargs.get('debug', False)
        if llc is None : raise Exception(f"ledgerObject:{self.oID}: no llc args")
        self.llc = llc
        self.oName = kwargs.get('name', self.__class__.__name__)

        try:
            llcName = llc.oName
        except:
            llcName = 'llcGeneral'
            
        # compure name of data for object (llcAssets_LLCNAME.json)
        self.dbName = f'{self.oName}_{llcName}.json'
        
        # Used to find fields within ledger object members, oDict['nm'] 
        self.kwList = ['oID', 'nm']

        # Process ledger object as iterator
        itr = kwargs.get('iterate', False)
        if itr : self.iterator()

        if self.debug: print(f"{self.oID} {type(self).__name__} Init Done")

    def mdIRS(self):
        try:
            # Return Documentation (Tios/Guidelines) for object
            return self.md
        except:
            # Return md provided or default
            return f"{self.oID} ha not IRS Tips/Guidelines"

    def _key(self, r):
        # Return tuple of transKey,index for given row (dt, amt)
        # Create unique Key per transaction:   <dt>_<amt>_<desc>, <index>
        # Return a unique transaction key id for asset entry
        try:
            nm = r.name
        except:
            nm = ''
        return (f"{r['dt']}_{r.amt}", nm)
    
    def _path(self, p):
        # use expanduser() to expand path with ~
        return Path(p).expanduser()

    def FN(self): 
        fn = os.path.join(self.llc.TOP, f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    def load(self):
        '''
        Load ledger objects:  dicts of transaction records
        return list of dicts representing a ledger object
        '''
        try:
            with open(self.FN(),'r') as fio:
                return json.load(fio)
        except Exception as err:
            print(f"{self.oID}: FAIL load: {self.FN()}, {err}")
            return []

    def save(self, tList):
        '''
        Load ledger objects dict of transaction records
        return list of dicts representing a ledger object
        '''
        try:
            with open(self.FN(),'w') as fio:
                return json.dump(tList, fio, indent=4)
        except Exception as err:
            print(f"{self.oID}: FAIL save: {self.FN()}, {err}")
            return []

    def find(self, **kwargs):
        '''
        Search for matching DB object: owners, customers, assets
        Trys to match by (str) value to a field within a field within the list of DB fields      
        '''
        by = kwargs['by']
        for oDict in self.load():
            if self.debug: print(f"{self.oID}: find oDict:{oDict}")
            for kw in self.kwList: 
                # Get field within DB lists
                fld = oDict[kw]

                # Check if field == by (str)
                if (type(fld) is str) and (by in oDict[kw]) :
                    return oDict
                    
                # check if by matches a the list of values
                elif type(fld) is list:
                    for s in fld:
                        if by in s : return oDict  
        # No match found                  
        if self.debug : print(f"{self.oID}: WARNING FAIL find on {by} ")
        return None

    def __eq__(self, tObj):
        '''
        Test if records are equal to another tObj's records
        Returns:
        False : len of objects is different
        True : transaction records are equal
        difDict : Difference found withihn some transaction records, details provided
        '''
        sList = self.load()
        oList = tObj.load()
        n = len(sList)
        if n != len(oList): 
            return False

        from ledger.llcCOA import ChartOfAccounts
        coa = ChartOfAccounts(self.llc)
    
        difDict = {}
        for i in range(n):
            sDict = sList[i]
            oDict = oList[i]
            oDict['acctType'] = coa._Type(oDict['acct'])
            if sDict == oDict : continue
            difDict[i] = DeepDiff(sDict, oDict)
    
        if len(difDict) == 0:
            return True
        return difDict


    def iterator(self):
        self.oList = self.load()

    def __iter__(self):
        for x in self.oList:
            yield x

    # ── Uniform Ledger API (declared on base; specialized per subclass) ──────

    def to_DF(self):
        '''
        Default DataFrame materialization — converts ``self.load()`` (list
        of dicts) into a pandas DataFrame.  Subclasses that carry richer
        shape (transactions with tID, stmt tables with _lineNo) override
        this to set a meaningful index.
        '''
        try:
            import pandas as pd
        except ImportError:
            raise RuntimeError("pandas not available for to_DF()")
        records = self.load() or []
        return pd.DataFrame(records)

    def to_agg(self, filterDict=None, by=None, aggDict=None, pretty=False):
        '''
        Uniform aggregation surface.  Returns::

            {'table': pandas.DataFrame, 'extraFields': dict}

        Kwargs:
          filterDict : dict filter applied to raw records pre-aggregation.
          by         : 'Trial' | 'BalSh' | 'IncStmt' | 'custom:[cols]' |
                       list[str].  Drives the groupby.
          aggDict    : pandas groupby().agg() spec.
          pretty     : False → raw aggregation; True → add row refs +
                       subtotals on both axes.

        Default base implementation returns ``to_DF()`` wrapped with an
        empty ``extraFields`` placeholder.  Transaction-shaped subclasses
        (ledgerDB) override to implement the four ``by`` modes;
        constructed-stmt subclasses (stmtDB) override to serve pre-built
        aggregates from ``self._rows``.
        '''
        df = self.to_DF()
        if filterDict:
            for k, v in filterDict.items():
                if k in df.columns:
                    df = df[df[k] == v]
        return {'table': df, 'extraFields': {}}

    def to_IRS(self):
        '''
        Default IRS payload — returns ``list[dict]`` with one dict per
        entity record, keyed by that entity's ID (oID / entityID / nm).

        Example (llcOwners)::

            [ {'owner1': {'nm': ..., 'addr': ..., 'entityID': ...}},
              {'owner2': {'nm': ..., 'addr': ..., 'entityID': ...}}, ... ]

        This shape directly drives the "1 PDF per owner-member" K-1
        pattern consumed in v0.3.  Constructed ``stmt*`` subclasses
        override this method to return a flat Book-field dict.
        '''
        out = []
        for rec in (self.load() or []):
            if not isinstance(rec, dict):
                continue
            # Pick a stable entity key: prefer explicit entityID, fall
            # back to oID, then nm, finally a positional index.
            entity_id = (rec.get('entityID')
                         or rec.get('oID')
                         or rec.get('nm')
                         or f"{self.oID}_{len(out)}")
            out.append({str(entity_id): dict(rec)})
        return out