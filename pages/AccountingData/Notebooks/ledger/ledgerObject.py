# class ledgerObject
import os
from pathlib import Path
import json
import datetime

from deepdiff import DeepDiff # Used in __eq__



class ledgerObject(object):
    '''
    Most ledger objects is a list of properties, ie. dict(). 
    All objects have field kw 'nm',  'oID'
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