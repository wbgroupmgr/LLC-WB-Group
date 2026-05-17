# Build Keys & Link to LLC Ledger
import os
from pathlib import Path
import json

from irs.pdfFill import pdfFill

def R(f,t): return [i for i in range(f,t)]

class irsForms(object):
    def __init__(self, llc, **kwargs):
        self.oID = self.__class__.__name__
        self.llc = llc
        self.irsDir = os.path.join(self.llc.acctDir(dirName='ye'), 'Forms_IRS')
        self.pf = pdfFill(self.inFN(), self.outFN())

    def exists(self, FN):
        if os.path.exists(FN):
            return FN

        print(f"IRS Form does not exist in IRS Dir.  Download into {self.BN}.pdf")
        return None

    def inFN(self): return self.FN('IRS.pdf')
    def outFN(self): return self.FN('keys.pdf')
    def keyFN(self): return self.FN('keys.json')
    def FN(self, ext):
        return os.path.join(self.irsDir, f'{self.BN}-{ext}')
    def fm2glDict(self):
        d = {}
        for (s,lnList) in self.fmDict.items():
            for i in lnList:
                d[f"{s}_F{i}"] = f"F{i}"
        return d

    def fldNames(self):
        mx = len(self.get())
        return dict(fm = R(0,mx))

    
    def fldNmSave(self, fldNmDict):
        # save form field names to json
        with open(self.FN('FieldNames.json'),'w') as fio:
            json.dump(fldNmDict, fio, indent=4)

    def fldNmLoad(self):
        # Load form field names from json
        fn = self.FN('FieldNames.json')
        print(f"Loading Form Field Name (json): {Path(fn).name}\nDIR: {fn}")
        with open(fn,'r') as fio:
            return json.load(fio)

    # -------------

    def genTestKeyDict(self):

        # 1. create raw dict for every field in form
        #pf = pdfFill(self.inFN(), self.outFN())
        fDict = self.pf.get()

        # 2. Create testDict to map field ID (F#) into every field
        fldNmDict = self.fldNmLoad()
        testDict = {k:self.pf._testKey(i,k,fDict[k]) for i,k in enumerate(fDict)}

        # 3. Output: FILE 
        keyFN = self.keyFN()
        ts = pdfFill(self.inFN(), keyFN)
        oDict = ts.fillPDF(to = testDict)

        print(f"{self.__class__.__name__} SUCC: testDict Generated {len(testDict)} Fields; \n-- FILE: {Path(keyFN)}")
        
from irs.irsFormFieldNames import irsSchKFields
class irsSchK1(irsForms):
    BN = 'Schedule_K_1' 

    if False:  # v2 method, replace by irsFormFieldNames.py
        # ---- keys <secName>_F# for form, mapped to field number [F#] based on order
        def fldNames(self):
            return dict(Hdr = R(0,7),
                      P1_llc = R(7,11),
                      P2_mem = R(11,38),
                      P2_cap = R(38,48),
                      P3_inc = R(48, 75),
                      P3_earn = R(75,79),
                      P3_credits = R(79,84),
                      P3_other = R(84,110)
                     )
from irs.irsFormFieldNames import irsF1065Fields
class irsF1065(irsForms):
    BN = 'Form_1065'

