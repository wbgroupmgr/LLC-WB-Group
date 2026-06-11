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
        fn = os.path.join(self.llc.acctDir(), 'Accts', f"{self.oID}_{self.llc.objName}.json")
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

    # ── _to_IRS : IRS2LLC provisioning declaration ──────────────────────────
    # CPA knowledge: llcOwners provisions partner-identification cells on
    # Form1065 (count of K-1s) and Schedule K-1 per-partner header / box-J
    # percentages and box-L beginning capital + contributions.
    #
    # Per-partner forms (Sch_K1) are flattened: for each owner we emit
    # one formLineDict entry per logicalKey, with rowNm = f"owner[{i}]"
    # so the consumer can distinguish which partner-column the cell
    # belongs to when Sch_K1 is rendered once per partner.  Owner
    # iteration order follows the llcOwners list (same order that is
    # written to disk).
    def _to_IRS(self, formObj):
        '''
        Return the per-fid IRS bindings this owners roster provisions
        for ``formObj``.  Invoked by ``irs.mapIRS2LLC._mapIRS2LLC()``.
        '''
        try:
            from irs.mapIRS2LLC import _lk_to_fid
        except ImportError:
            from mapIRS2LLC import _lk_to_fid

        formNm = getattr(formObj, 'oID', '')
        lk2fid = _lk_to_fid(formObj)
        owners = self.load() or []
        out = []

        if formNm == 'Form1065':
            # Page 1 box I — number of Schedules K-1 attached = owner count
            fid = lk2fid.get('P1_I')
            if fid:
                out.append({
                    'fid':   fid,
                    'tbl':   'llcOwners',
                    'row':   'count',
                    'col':   'n',
                    'value': len(owners),
                })
            return out

        if formNm == 'Sch_K1':
            # Per-partner header + box-J percentages + capital contributions.
            # Owner columns follow the llcOwners list order (partner index i).
            for i, o in enumerate(owners):
                nm_list  = o.get('nm') or []
                nm_first = nm_list[0] if isinstance(nm_list, list) and nm_list else str(o.get('oID', ''))
                pct      = o.get('pct', 0) or 0
                try:
                    pct_num = float(pct)
                except (TypeError, ValueError):
                    pct_num = 0.0
                # pct is stored as fraction (e.g. 0.96 → 96.00%).
                pct_str = f"{pct_num * 100:.2f}"
                partner_bindings = [
                    ('K1_PtName',   'nm',          nm_first),
                    ('K1_PtEIN',    'ein',         o.get('ein', '') or o.get('SSN', '') or ''),
                    ('K1_PtAddr',   'addr',        o.get('addr', '') or ''),
                    ('K1_PtType',   'memType',     o.get('memType', '') or ''),
                    ('K1_PtStatus', 'status',      o.get('status', '') or ''),
                    ('K1_J_Profit',  'pct_str',    pct_str),
                    ('K1_J_Loss',    'pct_str',    pct_str),
                    ('K1_J_Capital', 'pct_str',    pct_str),
                    ('K1_L1', 'beg_capital',       o.get('beg_capital', 0) or 0),
                    ('K1_L2', 'capital_contributed', o.get('capital_contributed', 0) or 0),
                ]
                rowNm = f"owner[{i}]"
                for lk, colNm, value in partner_bindings:
                    fid = lk2fid.get(lk)
                    if not fid:
                        continue
                    out.append({
                        'fid':   fid,
                        'tbl':   'llcOwners',
                        'row':   rowNm,
                        'col':   colNm,
                        'value': value,
                    })
            return out

        return out

