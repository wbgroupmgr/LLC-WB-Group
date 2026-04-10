#!/usr/bin/env python3
"""
Define edit session

- llcEditSession( llcName='xxxLLC', edOpt='llc' or single LLC DB, load=False | True)

- init ; create wkDict map DB/artifact into workingObj 
    - load based on eSession loadOpt
- loadTemp : import llc DB's into eidt session working DB's, timestamp time of wFN
- saveTemp : Commit *changed* working DB files to llc DB's
- clean : will delete working files
"""

import sys
import os
from pathlib import Path
import datetime
import shutil
import pandas as pd



from ledger.LLC import LLC
from ledger.llcExpRev import llcExpRev
from ledger.llcAssets import llcAssets
from ledger.llcFinancialReport import llcFinancialReport

from util.utilWorkingDB import utilWorkingDB

class wkAssets(utilWorkingDB):
    pass

class wkExpRev(utilWorkingDB):
    pass

class noDBFinancialReport(llcFinancialReport):
    def load(self):
        return []
 
class wkBalanceSheet(utilWorkingDB):
    def load(self):
        # FIXME: load balance sheet - working version
        return []

class wkIncomeStmt(utilWorkingDB):
    def load(self):
        # FIXME: load income stmt - working version
        return []


class utilEditSession():

    def __init__(self, **kwargs):
        # Session data parameters 
        self.loadOpt = kwargs.get('load', False)
        self.edOpt = kwargs.get('edOpt', 'llc')

        # LLC 
        llcName = kwargs.get('llcName', None)
        if llcName is None or llcName == 'NoNameLLC':
            print("Missing LLC name, exiting")
            raise Exception("Missing --llcName option")

        # bind to LLC
        top = Path.cwd().parents[2]
        self.llc = LLC(llcName,debug=False, top=top)  # debug='details'
        _ = self.llc._Bank()

        # bind LLC data
        self.wkDict = self.llcBind()
        self.oDict = {wk.o.oID:wk for wkID, wk in self.wkDict.items()}

    def get(self, oID):
        # returns the work object for the oID object ID
        try:
            return self.oDict[oID]
        except:
            print(f"WARNING - editSession.get failed, oid:{oID}")


    def getWk(self, wkID):
        # returns the work object for the oID object ID
        try:
            return self.wkDict[wkID]
        except:
            print(f"WARNING - editSession.getWk failed, oid:{oID}")

    def llcBind(self, **kwargs):
        '''
        bind Edit Session to LLC data
        
        create workingObj for all possible LLC data object, wFN is set or None depending on edOpt 

        '''
        wkDict = {}
        
        aObj = llcAssets(self.llc, **kwargs)
        wObj = wkAssets(self.llc, editSession=self, tObj=aObj)   
        wkDict[wObj.oID] = wObj
        
        erObj = llcExpRev(self.llc, **kwargs)
        wObj = wkExpRev(self.llc, editSession=self, tObj=erObj)
        wkDict[wObj.oID] = wObj

        if False:
            bsObj = noDBFinancialReport(self.llc, **kwargs)
            wObj = wkBalanceSheet(self.llc, editSession=self, tObj=bsObj)
            wkDict[wObj.oID] = wObj
    
            incStObj = noDBFinancialReport(self.llc, **kwargs)
            wObj = wkIncomeStmt(self.llc, editSession=self, tObj=incStObj)
            wkDict[wObj.oID] = wObj

        d = {k:wk.FN() for k,wk in wkDict.items()}
        print(f"99 eSession bind objects: {d}")
        
        return wkDict
        
    def loadTemp(self):
        '''
        get LLC data and fill working data 
        '''
        for wkID,wk in self.wkDict.items():
            try:
                wk.loadTemp()
            except:
                # Some objects do not have a DB but load is derived, not yet implemented
                pass

    def saveTemp(self):
        for wkID, wk in self.wkDict.items():
            wk.saveTemp()

    def clean(self):
        for wkID, wk in self.wkDict.items():
            fn = wk.FN()
            try:
                os.remove(fn)
            except Exception as err:
                print(f"{wkID} Warning: Remove failed on Working file ({fn}) - error:{err}")


    def push(self):
        '''
        Push working files into queue (copy /tmp/*LLCname_push.json)
        '''
                
        for wkID, wk in self.wkDict.items():
            # Create queue name
            qNm = wk.FN().replace('temp', 'push')

            # Copy wk -> queue
            try:
                # Copy 'source.txt' to a new file named 'destination.txt'
                shutil.copy(wk.FN(), qNm)
            except Exception as err:
                print(f"{self.wk.oID} ERROR: **** push failed on Working file ({wk.FN()}) - error:{err}")

    def pop(self):
        '''
        pop working files from queue (copy /tmp/*LLCname_push.json)
        '''
        
        for oID,wk in self.wkDict.items():
            # Create queue name
            qNm = wk.FN().replace('temp', 'push')

            # copy queue -> wk
            try:
                # Copy 'source.txt' to a new file named 'destination.txt'
                shutil.copy(qNm, wk.FN())
            except Exception as err:
                print(f"{self.wk.oID} ERROR: **** pop failed on Working file ({wk.FN()}) - error:{err}")

    def __repr__(self):
        s = f"llcEditSession Status:"
        for wkID, wk in self.wkDict.items():
            s +=f"\n{wk}"
        return s
        

    
            
