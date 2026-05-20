import os
import pandas as pd
import numpy as np

from ledger.ledgerObject import ledgerObject

# ── acctType buckets used by to_agg() 'by' modes ─────────────────────────────
_BS_TYPES = {'Asset', 'Liability', 'Equity'}
_IS_TYPES = {'Income', 'Expense'}


class ledgerDB(ledgerObject):
    '''
    Common access to all LLC DB files
    '''
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

    def FN(self):
        fn = os.path.join(self.llc.acctDir(), 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    def toDF(self):
        # list of transactions (dual accounts ['acct', 'Ledger']0
        tList = self.load()
        if not tList:
            return None

        return pd.DataFrame(tList)

    # ── Uniform Ledger API: transaction-aware to_DF / to_agg ────────────────

    def to_DF(self):
        '''
        Transaction DataFrame — list of raw records (Dual-Accounts for
        llcAssets/llcExpRev/etc).  Returns empty DataFrame (not None) so
        downstream to_agg() never has to special-case.
        '''
        df = self.toDF()
        if df is None:
            return pd.DataFrame()
        return df

    def _annotate_acct_type(self, df):
        '''
        Ensure ``acctType`` column is populated for every row using the
        COA classifier.  Works in-place on a copy; returns the copy.
        '''
        if df is None or df.empty:
            return df
        out = df.copy()
        if 'acctType' not in out.columns:
            out['acctType'] = ''
        try:
            coa = self.llc.coa
        except AttributeError:
            from ledger.llcCOA import ChartOfAccounts
            coa = ChartOfAccounts(self.llc)
        # Fill only the missing / empty cells.
        mask = out['acctType'].astype(str).str.strip().eq('')
        if 'acct' in out.columns:
            out.loc[mask, 'acctType'] = out.loc[mask, 'acct'].map(
                lambda a: coa._Type(a) if a else ''
            )
        return out

    def to_agg(self, filterDict=None, by=None, aggDict=None, pretty=False):
        '''
        Uniform aggregation surface — see ledgerObject.to_agg for the
        contract.  ledgerDB implements the four ``by`` modes over
        transaction-shaped data.

        Return shape::

            {'table': pandas.DataFrame, 'extraFields': dict}

        The ``extraFields`` placeholder is empty by default; downstream
        ``to_IRS()`` layers supplement it with non-numeric context
        (LLC name, EIN, propertyName, etc.).
        '''
        df = self.to_DF()
        if df is None or df.empty:
            return {'table': pd.DataFrame(), 'extraFields': {}}

        # Ensure acctType is present so by-mode filters work.
        df = self._annotate_acct_type(df)

        # Apply pre-agg filter dict (equality match per column).
        if filterDict:
            for k, v in filterDict.items():
                if k in df.columns:
                    df = df[df[k] == v]

        if df.empty:
            return {'table': df, 'extraFields': {}}

        # Default agg: sum amt per group, count rows.
        if aggDict is None:
            aggDict = {'amt': 'sum'}

        # ---- Resolve ``by`` into a groupby column list ---------------------
        by_cols = None
        if by is None or by == '' or by == 'All':
            # Ungrouped — return the raw (filtered) DataFrame.
            return {'table': df.reset_index(drop=True), 'extraFields': {}}

        if isinstance(by, list):
            by_cols = list(by)
        elif isinstance(by, str):
            if by == 'Trial':
                by_cols = ['acctType']
            elif by == 'BalSh':
                df = df[df['acctType'].isin(_BS_TYPES)]
                by_cols = ['acctType', 'acct', 'aType']
            elif by == 'IncStmt':
                df = df[df['acctType'].isin(_IS_TYPES)]
                by_cols = ['acctType', 'acct', 'aType']
            elif by.startswith('custom:'):
                spec = by[len('custom:'):].strip()
                if spec.startswith('[') and spec.endswith(']'):
                    spec = spec[1:-1]
                by_cols = [c.strip().strip("'\"") for c in spec.split(',') if c.strip()]
            else:
                raise ValueError(
                    f"ledgerDB.to_agg: unknown 'by' mode {by!r}. "
                    "Expected one of: 'Trial', 'BalSh', 'IncStmt', "
                    "'custom:[c1,c2,...]', list[str], or None."
                )

        if not by_cols:
            return {'table': df.reset_index(drop=True), 'extraFields': {}}

        # Only group by columns that actually exist in the filtered frame.
        by_cols = [c for c in by_cols if c in df.columns]
        if not by_cols:
            return {'table': df.reset_index(drop=True), 'extraFields': {}}

        # Only aggregate columns that actually exist.
        real_agg = {k: v for k, v in aggDict.items() if k in df.columns}
        if not real_agg:
            real_agg = {df.columns[0]: 'count'}

        g = df.groupby(by_cols, dropna=False, as_index=False).agg(real_agg)

        if pretty:
            # Add a grand-total row + per-group subtotals on the first by_col.
            g = self._prettify(g, by_cols, real_agg)

        return {'table': g, 'extraFields': {}}

    @staticmethod
    def _prettify(df, by_cols, aggDict):
        '''
        Add subtotals on the leading by-col plus a grand-total row.
        Keeps the structure simple for v0.2; richer pivot-style pretty
        output can land in v0.3 if needed.
        '''
        if df.empty or not by_cols:
            return df
        lead = by_cols[0]
        numeric_cols = [c for c in aggDict.keys() if c in df.columns]
        blocks = []
        for key, chunk in df.groupby(lead, dropna=False):
            blocks.append(chunk)
            sub = {c: '' for c in df.columns}
            sub[lead] = f"{key} — subtotal"
            for c in numeric_cols:
                try:
                    sub[c] = chunk[c].sum()
                except Exception:
                    sub[c] = ''
            blocks.append(pd.DataFrame([sub]))
        total = {c: '' for c in df.columns}
        total[lead] = 'TOTAL'
        for c in numeric_cols:
            try:
                total[c] = df[c].sum()
            except Exception:
                total[c] = ''
        blocks.append(pd.DataFrame([total]))
        return pd.concat(blocks, ignore_index=True)


    def toGL(self, gl, **kwargs):
        '''
        Convert llc DB dual Accounts per transaction into journal format: 2 posts with 1 acct
        - DB must conform to COA.toRecDict fields
        - DB may be super set of fields 

        Needed: 
        - fromObj.toDF()(
        - fromObj._key(row)
        '''
        fromDF = self.toDF()
        if fromDF is None:
            return None

        # =========== Convert Dual accounts (acct, Ledger) into a single Acct columns        
        
        # ---- dfL make acct = Ledger; clear out Ledger
        # Only include rows that actually have a Ledger account (1-sided closing entries have Ledger=NaN)
        dfL = fromDF.copy()
        _lmask = fromDF['Ledger'].notna() & (fromDF['Ledger'].astype(str).str.strip().str.lower() != 'nan')
        dfL = dfL[_lmask].copy()
        dfL.acct = dfL.Ledger
        dfL.Ledger = np.nan
        #      Reverse sign of amt depending on aType [Debit/Credit]
        try:
            dfL.aType = fromDF.aType.apply(lambda v : 'Debit' if v == 'Credit' else 'Credit')
        except:
            pass
        
        # ---- df2 already has acct, clear out Ledger
        dfA = fromDF.copy()
        dfA.Ledger = np.nan
        
        df = pd.concat([dfA, dfL])

        # Return a GL with a single acct; 2 entries per transaction; sort by date via tID; reset index
        cDefault = [c for c in self.llc.coa.recCols() if c != 'Ledger']
        cOpt = kwargs.get('cols', cDefault)
        if cOpt is None:
            cols = df.columns
        return df[cols].sort_values(by='tID').reset_index(drop=True)


        
