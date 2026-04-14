# class ledgerGeneral
import pandas as pd
from ledger.ledgerObject import ledgerObject
from ledger.llcCOA import ChartOfAccounts as llcCOA
from ledger.llcAssets import getBal

toKAmt = lambda d : -d['amt'] if d['aType'] == 'Credit' else d['amt']
toTid = lambda d : f"{d['dt']}_{toKAmt(d):0.2f}"
toIDDict = lambda l : {toTid(d):i for i,d in enumerate(l)}

class ledgerGeneral(ledgerObject):
    '''

    General Ledger Services ... 
    - constructor per the financial pipeline
        - import llcAsset
        - import llcExpense
        - import llcBank
        - reconcile

    - Referennce 
        - llcUsers
        - llcCustomer
    
    - GL Tranaction Records (normalized) - refer to llcCOA.toRecDict() for std definition

    - all LLC DB object must have a obj.to_GL() service call that normalizes their DB into the GL records
    '''
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        self.coa = llcCOA(self.llc)
        self.stdCols = ['tID', 'dt', 'desc', 'amt', 'aType', 'acct', 'acctSub', 'acctType',
                     'refKey', 'refDB', 'refDoc', 'refProp']

    def _ckCOA(self, df = None, col='acct'):
        '''
        Check if account values (col) matches COA 
        '''
        if df is None: df = self.glDF
        for a in df[col].unique():
            if self.coa.get(a) is None:
                print(f"{a:40s} not in COA")

    def classifyAccts(self, df):
        '''
        '''
        # Break down by account
        glSumDF = df.groupby(['acct', 'aType']).amt.sum().unstack()
    
        # compute the totals: bottom, side
        glSumDF.loc['Total'] = glSumDF.sum(axis=0)
        glSumDF['Bal'] = glSumDF.Debit - glSumDF.Credit
        
        return glSumDF.fillna('')

    def classifyAssets(self, df, **kwargs):
        glDF = df.copy()
        # Break down by account
        byCols = kwargs.get('by', ['acctType', 'acct', 'aType'])
        glSumDF = df.groupby(byCols).amt.sum().unstack()
        glSumDF['Bal'] = round(glSumDF.fillna(0).apply(lambda r : r.Debit - r.Credit, axis=1),2)
        glSumDF.loc[('All', 'Total'), :] = glSumDF.sum( axis=0)
        return glSumDF.fillna('')

    def findNewExpRevFromBank(self, bkObj, erObj):
        '''
        return list of new bank (bkObj) transactions not in llcExpRev (erObj) 
        '''
                
        # Load bank stmt transaction in ExpRev format
        bkList = bkObj.load()

        # Load llcExpRev transactions
        erList = erObj.load() # List of transactions
        erIDList = [toTid(d) for d in erList]  # List of ExpRev tID's
        erCols = erList[0].keys() # Raw columns
        erCols = [c for c in erCols if c not in ['_unknown', 'acctMinor', 'acctMajor', 'acctType']] # Clean set of columns
        
        newList = []
        for bkDict in bkList:
            bkID = toTid(bkDict)
            if bkID in erIDList: 
                continue
            newList.append(bkDict)

        return newList

    def toGLList(self, tObj):
    
        glDF = tObj.toGL(self).copy()

        # Check if any amt is negative, must be 0 or positive 
        aPos = glDF.amt.apply(lambda v : False if v < 0 else True)
        xDF = glDF[aPos]
        if len(xDF) > 0 : 
            print("Amt is negative", tObj.oID, len(xDF))
            glDF.amt = abs(glDF.amt)        
        
        return glDF.to_dict(orient='Records')
    
    
    def mergeGL(self, oList, resolve_dups=True):
        '''
        Merge multiple GL sources into one list.

        oList: list of items where each item is either:
          - a ledger object with a toGLList() method  (original interface), or
          - a plain Python list of transaction dicts   (new raw-dict interface).

        resolve_dups=True  (default, used by BS / IS):
          Standard dedup: first-source-wins by tID.  Pass the preferred source
          first (e.g. [asset_list, er_list] so llcAssets takes priority).
          No 'Status' field is added.

        resolve_dups=False (used by General Ledger view):
          Keep ALL records.  Same tID + same refDB → deduplicated (exact copy).
          Same tID + different refDB → both kept, Status set to '⚠ Dup'.
          Unique records get Status=''.
        '''
        def _as_list(obj):
            '''Accept either a ledger object or a raw dict list.'''
            if isinstance(obj, list):
                return list(obj)
            return self.toGLList(obj)

        # Add acctType based on Debit/Credit
        #oList = self.llc.coa.getAcctType(tList)

        if resolve_dups:
            # ── first-wins dedup ──────────────────────────────────────────────
            merged = []
            seen_tids = set()
            for src in oList:
                src_list = _as_list(src)
                for d in src_list:
                    tid = d.get('tID') or toTid(d)
                    if tid in seen_tids:
                        continue
                    seen_tids.add(tid)
                    r = dict(d)
                    r['tID'] = tid
                    # --- FIXED by coa.toAcctType
                    #r['acctType'] = self.coa._Type(r.get('acct', ''))
                    r.pop('Status', None)
                    merged.append(r)
            return sorted(merged, key=lambda r: (r.get('dt', ''), r.get('acct', '')))

        else:
            # ── keep all; mark cross-source dups ─────────────────────────────
            all_records = []
            for src in oList:
                for d in _as_list(src):
                    r = dict(d)
                    r['tID'] = r.get('tID') or toTid(r)
                    # --- FIXED by coa.toAcctType
                    #r['acctType'] = self.coa._Type(r.get('acct', ''))
                    all_records.append(r)

            # Identify tIDs that appear with more than one distinct refDB value
            from collections import defaultdict
            by_tid: dict = defaultdict(set)
            for r in all_records:
                by_tid[r['tID']].add(r.get('refDB', ''))
            dup_tids = {tid for tid, refs in by_tid.items() if len(refs) > 1}

            # Deduplicate exact copies (same tID + same refDB)
            seen_tid_ref = set()
            result = []
            for r in all_records:
                key = (r['tID'], r.get('refDB', ''))
                if key in seen_tid_ref:
                    continue
                seen_tid_ref.add(key)
                r['Status'] = '⚠ Dup' if r['tID'] in dup_tids else ''
                result.append(r)

            return sorted(result, key=lambda r: (r.get('dt', ''), r.get('acct', '')))

    # ── Double-entry expansion ────────────────────────────────────────────────

    _ATYPE_TOGGLE = {
        'Debit': 'Credit', 'Credit': 'Debit',
        'Dr':    'Cr',     'Cr':    'Dr',
        'DR':   'CR',      'CR':   'DR',
        'D':    'C',       'C':    'D',
        'dr':   'cr',      'cr':   'dr',
    }

    def _toggle_atype(self, atype: str) -> str:
        s = str(atype).strip()
        if s in self._ATYPE_TOGGLE:
            return self._ATYPE_TOGGLE[s]
        return 'Credit' if s.lower() in ('debit', 'dr', 'd') else 'Debit'

    def toDoubleEntry(self, records):
        '''
        Expand each source record into two GL entries (double-entry bookkeeping).

        For records that have a non-empty 'Ledger' field:
          Entry 1 (acct side)   : acct = original acct,   aType = original
          Entry 2 (ledger side) : acct = Ledger value,    aType = toggled

        Both entries:
          - Drop the 'Ledger' key
          - Always recompute tID via toTid() (so sign-flip gives a distinct key)
          - Recompute acctType from the new acct via COA

        Records without a Ledger field pass through as a single entry.
        '''
        result = []
        for r in records:
            ledger_acct = (r.get('Ledger') or '').strip()

            # ── Entry 1: acct side ───────────────────────────────────────────
            e1 = {k: v for k, v in r.items() if k not in ('Ledger', 'tID')}
            e1['tID']      = toTid(e1)
            e1['acctType'] = self.coa._Type(e1.get('acct', ''))
            result.append(e1)

            # ── Entry 2: ledger (offset) side ────────────────────────────────
            if ledger_acct:
                e2 = {k: v for k, v in r.items() if k not in ('Ledger', 'tID')}
                e2['acct']     = ledger_acct
                e2['aType']    = self._toggle_atype(r.get('aType', 'Debit'))
                e2['tID']      = toTid(e2)          # sign flipped → distinct tID
                e2['acctType'] = self.coa._Type(e2['acct'])
                result.append(e2)

        return result

    def findDup(self, glList):
        '''
        Return every record in glList that is a duplicate of another record.
        Duplicates are defined as: same toTid() value but different refDB values
        (i.e. the same real-world transaction exists in more than one source DB).
        '''
        from collections import defaultdict
        by_tid: dict = defaultdict(list)
        for d in glList:
            tid = d.get('tID') or toTid(d)
            by_tid[tid].append(d)

        dup_tids = set()
        for tid, records in by_tid.items():
            refDBs = {r.get('refDB', '') for r in records}
            if len(refDBs) > 1:
                dup_tids.add(tid)

        return [d for d in glList if (d.get('tID') or toTid(d)) in dup_tids]

    def sumRowCol(self, df):
        '''
        Summarize Sum Totals (vertical/horizontal) of a groupby dataframe
        '''
        n = len(df)
        cList = list(df.columns)
        c = len(cList)
        rList = ['' for i in range(c)]
        rList[-3] = 'Total'
        c_2 = df.iloc[:,-2].sum()
        rList[-2] = c_2
    
        c_1 = df.iloc[:,-1].sum()
        rList[-1] = c_1
        #pd.concatdf.iloc[n] = rList
        newDF = pd.concat([df, pd.DataFrame(rList,index = df.columns).transpose()]).set_index(cList[0:2])
        newDF['Total'] = newDF.Debit - newDF.Credit
        with pd.option_context('future.no_silent_downcasting', True):
            return newDF.fillna('')
    
    def glIncomeExpense(self, glDF):
        '''
        Generate IncomeExpense dataframe using General Ledger transaction, via groupby
        '''
        df = glDF[glDF.acctType.isin(['Income', 'Expense'])]
        grpDF = df.groupby(['acctType', 'acct', 'aType']).amt.sum().unstack().reset_index()
        return self.sumRowCol(grpDF)
    
    def glBalSheet(self, glDF):
        '''
        Generate BalanceSheet dataframe using General Ledger transaction, via groupby
        '''
        df = glDF[glDF.acctType.isin(['Asset', 'Equity', 'Liability'])]
        grpDF = df.groupby(['acctType', 'acct', 'aType']).amt.sum().unstack().reset_index()
        #glSumDF.loc[f'Balance'] = glDF.sum()
        return self.sumRowCol(grpDF)


    

