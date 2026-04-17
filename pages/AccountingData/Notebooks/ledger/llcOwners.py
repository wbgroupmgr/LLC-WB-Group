# class llcOwners
'''
manage owners of LLC
list of owners is stored in accountingData/YEAR/llcOwners_<llcName>.json
'''

mdIRS = '''

## Self-Employment Taxes 
- members of a multi-member LLC (typically taxed as a partnership) 
- generally must declare their share of profits as self-employment income. 
- members are responsible for self-employment tax (social security and medicare) 
    - on your portion of the net earnings
    - usually reported on Schedule SE of your personal 1040 tax return. 

### Key Takeaways for Multi-Member LLCs
- **Tax Classification**: The IRS treats multi-member LLCs as partnerships by default, meaning profits "pass-through" to members.
- **Self-Employment Tax**: Active members generally pay self-employment tax on their share of ordinary business income, as they are not considered employees.
- **Reporting**: 
    - The LLC files Form 1065 (Partnership Return), 
    - Each member receives a Schedule K-1, which reports their share of income, deductions, and credits.
- **Threshold**: 
    - You usually must pay self-employment tax if your net earnings are $400 or more. 

### Important Considerations
- **Guaranteed Payments**: Payments for services rendered to the LLC, regardless of profit, are generally subject to self-employment tax.
- **Passive Members**: Passive investors (like limited partners) might not owe self-employment tax on their share of income, though this is a complex area.
- **S-Corp Election**: If the LLC elects to be taxed as an S-Corporation, active members may be treated as employees, allowing them to pay self-employment tax only on a reasonable salary, not on total profits.
'''

import os
from ledger.ledgerObject import ledgerObject

class llcOwners(ledgerObject):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

    def FN(self): 
        fn = os.path.join(self.llc.TOP, self.llc.dirAccounting, 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    def capitalDist(self, assetList):
        '''
        Expand a list of asset/transaction records by stakeholder ownership.

        For each record in assetList that has a 'propOwners' dict,
        creates one expanded record per owner with:
          - All original fields preserved
          - Owner fields prefixed with 'o_'  (o_oID, o_nm, o_pct, o_status, ...)
          - o_nm is flattened to the first entry from the nm list (or oID if empty)
          - amt scaled by the owner's integer percentage
            (propOwners stores e.g. {"oID": 100} meaning 100%, so divide by 100.0)

        Records without a valid propOwners dict are skipped.
        Returns a flat list of expanded dicts.
        '''
        # Build owner lookup: oID → ownerDict
        oList = self.load()
        oDict = {o['oID']: o for o in oList}

        def _new_owner(oID):
            return {
                'oID': oID, 'nm': [oID], 'addr': '',
                'status': 'Unknown', 'memType': '', 'pct': 1.0, 'kw': []
            }

        distList = []
        for tDict in assetList:
            propOwners = tDict.get('propOwners')
            if not isinstance(propOwners, dict):
                continue

            for oID, oPct in propOwners.items():
                ownerDict = oDict.get(str(oID)) or _new_owner(oID)

                # Build o_-prefixed owner fields
                o_fields = {'o_oID': ownerDict['oID']}
                for k, v in ownerDict.items():
                    if k != 'oID':
                        o_fields[f'o_{k}'] = v
                # Flatten nm list to first name only
                if isinstance(o_fields.get('o_nm'), list):
                    o_fields['o_nm'] = o_fields['o_nm'][0] if o_fields['o_nm'] else oID

                # Merge: original record fields + owner fields
                mDict = {**tDict, **o_fields}

                # Scale amt by integer ownership pct (100 → 100/100.0 = 1.0 = full share)
                try:
                    raw_amt = float(tDict.get('amt', 0) or 0)
                    mDict['amt'] = round(raw_amt * float(oPct) / 100.0, 4)
                except (TypeError, ValueError):
                    mDict['amt'] = 0.0

                distList.append(mDict)

        return distList

    def loadCapDist(self, tObj):
        '''
        Expand asset transactions from tObj (any object with a .load() method)
        by stakeholder ownership.  Delegates to capitalDist().
        '''
        return self.capitalDist(tObj.load())

    def toDF_CapDist(self, tObj):
        '''Return capitalDist result as a pandas DataFrame.'''
        import pandas as pd
        return pd.DataFrame(self.loadCapDist(tObj))


        
