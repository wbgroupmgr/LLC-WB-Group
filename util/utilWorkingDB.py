import sys
import os
from pathlib import Path
import datetime
import shutil
import pandas as pd
import json
from typing import Any, Dict, List



from ledger.ledgerDB import ledgerDB

class utilWorkingDB(ledgerDB):
    '''
    Manage a working version of a transaction object (tObj, aka: llcAssets, llcExpRev)

    Acts just like the tObj but keeps temporary objects

    ## Usage 
    
    workObj.loadTemp()
        >>>> Edit Session <<<
        workObj.load()
        saveObj.save
        >>>> END Edit Session <<<
    workObj.saveTemp()


    ## Create Working Obj for llcXXX
    
    class llcXXX=(llcWorkingDB):
        def FN(self):
            return working filepath


    workObj = llcXXX(llc, es=EditSession(), tObj=assetObj)
    '''
    
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        self.es = kwargs['editSession']     # Editing session
        self.o = kwargs['tObj'] # Transaction Object
        self.bind() # bind 
        self.crTime = datetime.datetime.now().timestamp()


    #
    # Mimic ledgerDB object for working file

    def FN(self):
        return f"/tmp/{self.o.oID}_{self.o.llc.objName}_temp.json"

    def load(self):
        if Path(self.FN()).exists():
            tList = super().load()
            return self.llc.coa.getAcctType(tList)
            
        return []

    #
    ## ---------- Working  file services

    def fnTime(self, fn = None):
        # get mod time of working file,   fn= will override to check LLC file
        if fn is None : fn = self.FN()
        fnObj = Path(fn)
        if fnObj.exists():
            # stat().st_mtime returns the timestamp
            mtime = fnObj.stat().st_mtime
            return datetime.datetime.fromtimestamp(mtime)
        return str(pd.NaT) # Bot a Time

    def bind(self):
        '''
        Bind working files from LLC
        '''
        # Confirm if edit session includes transaction object type
        if not(self.es.edOpt in ['llc', self.o.oID] ):
            return None

        try:
            self.loadTemp()
        except:
            self.oTime = None
   

    def loadTemp(self):
        '''
        Load working file from LLC object
        '''
        #print("debug 85 loadTem utilWorkngDB: ", self.es.loadOpt)
        if self.es.loadOpt:
            with open(self.o.FN(), 'r') as fio:
                # Handle NaN case in DB
                jStr = fio.read()
                            # save to temp
            wkList = json.loads(jStr.replace('NaN', 'null'))
            self.save(wkList)
            self.oTime = self.fnTime(self.FN())
            return True

        # not loading, make sure previous working file exists
        elif Path(self.FN()).exists():
            return True
            
        # Validate file paths
        print(f"⚠️  Warning Loan Failed: {self.oID} working file not found. Correct and restart, {self.FN()}, loadOpt:{self.es.loadOpt}")

        return False


    def saveTemp(self):
        '''
        if working file was modified (FN.mTime > obj.mTime)
        Save working file to LLC
        '''
        # if File changed, 
        if self.oTime  != self.fnTime(self.FN()) : 
            # Load working data
            tList = self.load()
            self.o.save(tList)

        # UNCHANGED - DO NOTHING
        return 

    def __repr__(self):
        oList = self.o.load()
        wkList = self.load()
        wTime = self.fnTime(self.FN())
        oTime = self.fnTime(self.o.FN())
        wChg = 'NoChanges' if wTime != oTime else 'Changed'
        return f"Work oID:{self.oID}> num:{len(wkList)}:{len(oList)}, st:{wChg}, Load:{self.es.loadOpt},  edOpt:{self.es.edOpt} wFN:{self.FN()},  "


