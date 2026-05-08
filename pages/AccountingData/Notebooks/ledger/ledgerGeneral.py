'''
ledger.ledgerGeneral — stateless General Ledger building service.

Canonical home for the ledgerGeneral class and the three helper lambdas
(toKAmt, toTid, toIDDict) that support mergeGL / toDoubleEntry / findDup.

Previously these symbols lived in ledger/stmtGeneralLedger.py; that module
was consolidated into ledger/stmtGL.py (v0.3).  This file is now the
single source of truth for the GL-building service.

Import paths supported:
    from ledger.ledgerGeneral import ledgerGeneral, toTid, toKAmt, toIDDict
'''

import pandas as pd
from ledger.ledgerObject import ledgerObject
from ledger.llcCOA import ChartOfAccounts as _llcCOA

# Key helpers used by mergeGL / toDoubleEntry / findDup.
toKAmt   = lambda d : -float(d['amt'] or 0) if d['aType'] == 'Credit' else float(d['amt'] or 0)
toTid    = lambda d : f"{d['dt']}_{toKAmt(d):0.2f}"
toIDDict = lambda l : {toTid(d): i for i, d in enumerate(l)}


class ledgerGeneral(ledgerObject):
    '''
    Stateless General Ledger service.

    Responsibilities:
      - Normalize source-DB records into GL rows (toGLList via obj.toGL())
      - Expand single-account source rows into double-entry pairs (toDoubleEntry)
      - Merge multiple GL sources with first-source-wins or cross-source dup
        flagging (mergeGL)
      - Classify GL transactions for BS / IS views (classifyAccts /
        classifyAssets / glBalSheet / glIncomeExpense)
      - Identify duplicates across source DBs (findDup)

    All operations are pure transformations — no persistent state beyond
    ``self.coa`` (Chart-of-Accounts lookup).
    '''
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        self.coa = _llcCOA(self.llc)
        self.stdCols = ['tID', 'dt', 'desc', 'amt', 'aType', 'acct', 'acctSub', 'acctType',
                        'refKey', 'refDB', 'refDoc', 'refProp']

    def _ckCOA(self, df=None, col='acct'):
        '''Check that every value in df[col] appears in the COA; print misses.'''
        if df is None:
            df = self.glDF
        for a in df[col].unique():
            if self.coa.get(a) is None:
                print(f"{a:40s} not in COA")

    def classifyAccts(self, df):
        # Break down by account
        glSumDF = df.groupby(['acct', 'aType']).amt.sum().unstack()
        # compute the totals: bottom, side
        glSumDF.loc['Total'] = glSumDF.sum(axis=0)
        glSumDF['Bal'] = glSumDF.Debit - glSumDF.Credit
        return glSumDF.fillna('')

    def classifyAssets(self, df, **kwargs):
        byCols = kwargs.get('by', ['acctType', 'acct', 'aType'])
        glSumDF = df.groupby(byCols).amt.sum().unstack()
        glSumDF['Bal'] = round(glSumDF.fillna(0).apply(lambda r: r.Debit - r.Credit, axis=1), 2)
        glSumDF.loc[('All', 'Total'), :] = glSumDF.sum(axis=0)
        return glSumDF.fillna('')

    def findNewExpRevFromBank(self, bkObj, erObj):
        '''Return list of bank transactions that aren't already in llcExpRev.'''
        bkList = bkObj.load()
        erList = erObj.load()
        erIDList = [toTid(d) for d in erList]

        newList = []
        for bkDict in bkList:
            bkID = toTid(bkDict)
            if bkID in erIDList:
                continue
            newList.append(bkDict)
        return newList

    def toGLList(self, tObj):
        glDF = tObj.toGL(self).copy()
        # Flag negative amt (must be non-negative; aType conveys sign)
        aPos = glDF.amt.apply(lambda v: False if v < 0 else True)
        xDF = glDF[aPos]
        if len(xDF) > 0:
            print("Amt is negative", tObj.oID, len(xDF))
            glDF.amt = abs(glDF.amt)
        return glDF.to_dict(orient='Records')

    def mergeGL(self, oList, resolve_dups=True):
        '''
        Merge multiple GL sources into one list.

        oList: list of items where each item is either:
          - a ledger object with a toGLList() method (original interface), or
          - a plain Python list of transaction dicts (raw-dict interface).

        resolve_dups=True  (default, used by BS / IS):
          Standard dedup — first-source-wins by tID.  No 'Status' field.

        resolve_dups=False (used by the General Ledger view):
          Keep ALL records.  Same tID + same refDB → deduped; same tID +
          different refDB → both kept, Status='⚠ Dup'.  Unique → Status=''.
        '''
        def _as_list(obj):
            if isinstance(obj, list):
                return list(obj)
            return self.toGLList(obj)

        if resolve_dups:
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
                    r.pop('Status', None)
                    merged.append(r)
            return sorted(merged, key=lambda r: (r.get('dt', ''), r.get('acct', '')))

        # keep all; mark cross-source dups
        all_records = []
        for src in oList:
            for d in _as_list(src):
                r = dict(d)
                r['tID'] = r.get('tID') or toTid(r)
                all_records.append(r)

        from collections import defaultdict
        by_tid: dict = defaultdict(set)
        for r in all_records:
            by_tid[r['tID']].add(r.get('refDB', ''))
        dup_tids = {tid for tid, refs in by_tid.items() if len(refs) > 1}

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

    # ── Double-entry expansion ──────────────────────────────────────────────

    _ATYPE_TOGGLE = {
        'Debit': 'Credit', 'Credit': 'Debit',
        'Dr':    'Cr',     'Cr':    'Dr',
        'DR':    'CR',     'CR':    'DR',
        'D':     'C',      'C':     'D',
        'dr':    'cr',     'cr':    'dr',
    }

    def _toggle_atype(self, atype: str) -> str:
        s = str(atype).strip()
        if s in self._ATYPE_TOGGLE:
            return self._ATYPE_TOGGLE[s]
        return 'Credit' if s.lower() in ('debit', 'dr', 'd') else 'Debit'

    def toDoubleEntry(self, records):
        '''
        Expand each source record into two GL entries (double-entry bookkeeping).

        Records with a non-empty 'Ledger' field emit:
          Entry 1 — acct side   : acct = original acct,   aType = original
          Entry 2 — ledger side : acct = Ledger value,    aType = toggled

        Both entries drop the 'Ledger' key, recompute tID, and re-type acctType.
        Records without a Ledger pass through as a single entry.
        '''
        result = []
        for r in records:
            ledger_acct = (r.get('Ledger') or '').strip()

            e1 = {k: v for k, v in r.items() if k not in ('Ledger', 'tID')}
            e1['tID']      = toTid(e1)
            e1['acctType'] = self.coa._Type(e1.get('acct', ''))
            result.append(e1)

            if ledger_acct:
                e2 = {k: v for k, v in r.items() if k not in ('Ledger', 'tID')}
                e2['acct']     = ledger_acct
                e2['aType']    = self._toggle_atype(r.get('aType', 'Debit'))
                e2['tID']      = toTid(e2)
                e2['acctType'] = self.coa._Type(e2['acct'])
                result.append(e2)
        return result

    def findDup(self, glList):
        '''Return every record in glList whose tID has more than one refDB.'''
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
        '''Append Debit/Credit column totals + Balance column to a groupby DF.'''
        cList = list(df.columns)
        c = len(cList)
        rList = ['' for _ in range(c)]
        rList[-3] = 'Total'
        rList[-2] = df.iloc[:, -2].sum()
        rList[-1] = df.iloc[:, -1].sum()
        newDF = pd.concat(
            [df, pd.DataFrame(rList, index=df.columns).transpose()]
        ).set_index(cList[0:2])
        newDF['Total'] = newDF.Debit - newDF.Credit
        with pd.option_context('future.no_silent_downcasting', True):
            return newDF.fillna('')


__all__ = ['ledgerGeneral', 'toTid', 'toKAmt', 'toIDDict']
