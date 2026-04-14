'''
llcReportEngine — Financial data adapter for the web UI layer.

Bridges the eSession / WkNode data model to the analytics pipeline in
ledger.ledgerGeneral (double-entry expansion + merge) and produces
clean, pandas-backed GL / Balance-Sheet / Income-Statement data.

Fixes two inverted filters that exist in ledger.llcFinancialReport:
  _buildBS()      used ~isin(BS types) → should be isin(BS types)
  _BuildIncStmt() used isin(BS types)  → should be isin(IS types)

Timestamp of last change: 2026.04.14
'''

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

from ledger.ledgerGeneral import ledgerGeneral

# ── Account-type groupings ────────────────────────────────────────────────────
BS_TYPES = {'Asset', 'Liability', 'Equity'}
IS_TYPES = {'Income', 'Expense'}
BS_ORDER  = ['Asset', 'Liability', 'Equity']
IS_ORDER  = ['Income', 'Expense']


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


class llcReportEngine:
    '''
    Core analytics engine for the web UI.

    Usage:
        engine = llcReportEngine(eSession)
        gl_list  = engine.getGLList()          # flat list of GL dicts
        bs_rows, bs_check = engine.buildBS()   # (rows, accounting-equation check)
        is_rows, is_summ  = engine.buildIS()   # (rows, net-income summary)
    '''

    def __init__(self, eSession):
        self.eSession = eSession
        self.gl = ledgerGeneral(eSession.llc)
        self._gl_cache: Optional[List[Dict]] = None

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_source(self, name: str) -> List[Dict[str, Any]]:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return []
        data = wk.o.load()
        return data if isinstance(data, list) else []

    def getGLList(self, resolve_dups: bool = True, force: bool = False) -> List[Dict[str, Any]]:
        '''
        Build the full General Ledger via double-entry expansion + merge.
        Result is cached per engine instance (call with force=True to refresh).
        '''
        if self._gl_cache is not None and not force:
            return self._gl_cache

        er_list    = self._load_source('llcExpRev')
        asset_list = self._load_source('llcAssets')

        er_expanded    = self.gl.toDoubleEntry(er_list)
        asset_expanded = self.gl.toDoubleEntry(asset_list)

        self._gl_cache = self.gl.mergeGL(
            [er_expanded, asset_expanded], resolve_dups=resolve_dups
        )
        return self._gl_cache

    def getGLListWithDups(self) -> List[Dict[str, Any]]:
        '''GL list keeping all records and flagging cross-source dups.'''
        er_list    = self._load_source('llcExpRev')
        asset_list = self._load_source('llcAssets')
        er_expanded    = self.gl.toDoubleEntry(er_list)
        asset_expanded = self.gl.toDoubleEntry(asset_list)
        return self.gl.mergeGL([er_expanded, asset_expanded], resolve_dups=False)

    def toDF(self) -> 'pd.DataFrame':
        '''Return GL as a pandas DataFrame with acctType column.'''
        if not _PANDAS_OK:
            raise ImportError('pandas is required for toDF()')
        rows = self.getGLList(resolve_dups=True)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df['amt']      = pd.to_numeric(df.get('amt'), errors='coerce').fillna(0.0)
        df['acctType'] = df['acct'].apply(lambda v: self.gl.coa._Type(v))
        return df

    # ── Balance Sheet ─────────────────────────────────────────────────────────

    def buildBS(self, view_by: str = 'All') -> Tuple[List[Dict], Dict]:
        '''
        Build Balance Sheet rows from the double-entry GL.

        Returns (rows, check_dict) where check_dict contains:
          asset, liability, equity  — net balances (Debit - Credit) per type
          equation_diff             — asset + liability + equity (should be 0)
          balanced                  — True if |equation_diff| < 0.01
        '''
        if _PANDAS_OK:
            return self._buildBS_pandas(view_by)
        return self._buildBS_fallback(view_by), {'balanced': None}

    def _buildBS_pandas(self, view_by: str) -> Tuple[List[Dict], Dict]:
        df = self.toDF()
        if df.empty:
            return [], {'balanced': True, 'equation_diff': 0}

        bs = df[df['acctType'].isin(BS_TYPES)].copy()

        if view_by and view_by != 'All':
            acct_type = view_by[2:]          # 'ByAsset' → 'Asset'
            bs = bs[bs['acctType'] == acct_type]

        if bs.empty:
            return [], {'balanced': True, 'equation_diff': 0}

        grp = (
            bs.groupby(['acctType', 'acct', 'aType'])['amt']
            .sum().unstack(fill_value=0.0).reset_index()
        )
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        order = {t: i for i, t in enumerate(BS_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct']).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        # Accounting equation check: Assets = Liabilities + Equity
        # In Debit-Credit convention: asset_bal + liab_bal + equity_bal = 0
        asset_bal  = round(sum(r['Balance'] for r in result if r['acctType'] == 'Asset'),  2)
        liab_bal   = round(sum(r['Balance'] for r in result if r['acctType'] == 'Liability'), 2)
        equity_bal = round(sum(r['Balance'] for r in result if r['acctType'] == 'Equity'), 2)
        diff       = round(asset_bal + liab_bal + equity_bal, 2)

        total_d = round(sum(r['Debit']   for r in result), 2)
        total_c = round(sum(r['Credit']  for r in result), 2)
        result.append({
            'acctType': 'TOTAL', 'acct': '',
            'Debit': total_d, 'Credit': total_c, 'Balance': round(total_d - total_c, 2),
        })

        check = {
            'asset':          asset_bal,
            'liability':      liab_bal,
            'equity':         equity_bal,
            'equation_diff':  diff,
            'balanced':       abs(diff) < 0.01,
        }
        return result, check

    def _buildBS_fallback(self, view_by: str) -> List[Dict]:
        rows  = self.getGLList(resolve_dups=True)
        buckets: Dict[tuple, Dict[str, float]] = {}
        for r in rows:
            at = r.get('acctType', '')
            if at not in BS_TYPES:
                continue
            if view_by and view_by != 'All' and at != view_by[2:]:
                continue
            acct = r.get('acct', '')
            try:   amt = float(r.get('amt', 0) or 0)
            except: amt = 0.0
            atype = str(r.get('aType', 'Debit')).strip()
            key = (at, acct)
            if key not in buckets:
                buckets[key] = {'Debit': 0.0, 'Credit': 0.0}
            buckets[key]['Debit' if atype not in ('Credit','Cr','CR','C') else 'Credit'] += amt

        order = {t: i for i, t in enumerate(BS_ORDER)}
        result = []
        for (at, acct), s in sorted(buckets.items(), key=lambda x: (order.get(x[0][0], 99), x[0][1])):
            d = round(s['Debit'], 2); c = round(s['Credit'], 2)
            result.append({'acctType': at, 'acct': acct, 'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({'acctType': 'TOTAL', 'acct': '', 'Debit': total_d, 'Credit': total_c,
                       'Balance': round(total_d - total_c, 2)})
        return result

    # ── Income Statement ──────────────────────────────────────────────────────

    def buildIS(self, view_by: str = 'All') -> Tuple[List[Dict], Dict]:
        '''
        Build Income Statement rows from the double-entry GL.

        Returns (rows, summary_dict) where summary_dict contains:
          income, expense, net_income
        '''
        if _PANDAS_OK:
            return self._buildIS_pandas(view_by)
        return self._buildIS_fallback(view_by), {}

    def _buildIS_pandas(self, view_by: str) -> Tuple[List[Dict], Dict]:
        df = self.toDF()
        if df.empty:
            return [], {'net_income': 0, 'income': 0, 'expense': 0}

        idf = df[df['acctType'].isin(IS_TYPES)].copy()

        if view_by and view_by != 'All':
            acct_type = view_by[2:]
            idf = idf[idf['acctType'] == acct_type]

        if idf.empty:
            return [], {'net_income': 0, 'income': 0, 'expense': 0}

        grp = (
            idf.groupby(['acctType', 'acct', 'aType'])['amt']
            .sum().unstack(fill_value=0.0).reset_index()
        )
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        order = {t: i for i, t in enumerate(IS_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct']).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        # Income balance = Credit - Debit (Credit > Debit = positive income)
        # Expense balance = Debit - Credit (Debit > Credit = positive expense)
        income_net  = round(sum(-(r['Balance']) for r in result if r['acctType'] == 'Income'),  2)
        expense_net = round(sum(  r['Balance']  for r in result if r['acctType'] == 'Expense'), 2)
        net_income  = round(income_net - expense_net, 2)

        total_d = round(sum(r['Debit']   for r in result), 2)
        total_c = round(sum(r['Credit']  for r in result), 2)
        result.append({
            'acctType': 'TOTAL',
            'acct':     f'Net Income: {net_income:,.2f}',
            'Debit': total_d, 'Credit': total_c, 'Balance': net_income,
        })

        summary = {
            'income':     income_net,
            'expense':    expense_net,
            'net_income': net_income,
        }
        return result, summary

    def _buildIS_fallback(self, view_by: str) -> List[Dict]:
        rows = self.getGLList(resolve_dups=True)
        buckets: Dict[tuple, Dict[str, float]] = {}
        for r in rows:
            at = r.get('acctType', '')
            if at not in IS_TYPES:
                continue
            if view_by and view_by != 'All' and at != view_by[2:]:
                continue
            acct = r.get('acct', '')
            try:   amt = float(r.get('amt', 0) or 0)
            except: amt = 0.0
            atype = str(r.get('aType', 'Debit')).strip()
            key = (at, acct)
            if key not in buckets:
                buckets[key] = {'Debit': 0.0, 'Credit': 0.0}
            buckets[key]['Debit' if atype not in ('Credit','Cr','CR','C') else 'Credit'] += amt

        order = {t: i for i, t in enumerate(IS_ORDER)}
        result = []
        for (at, acct), s in sorted(buckets.items(), key=lambda x: (order.get(x[0][0], 99), x[0][1])):
            d = round(s['Debit'], 2); c = round(s['Credit'], 2)
            result.append({'acctType': at, 'acct': acct, 'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        income_net  = round(sum(-(r['Balance']) for r in result if r['acctType'] == 'Income'), 2)
        expense_net = round(sum(  r['Balance']  for r in result if r['acctType'] == 'Expense'), 2)
        net_income  = round(income_net - expense_net, 2)
        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({'acctType': 'TOTAL', 'acct': f'Net Income: {net_income:,.2f}',
                       'Debit': total_d, 'Credit': total_c, 'Balance': net_income})
        return result

    # ── COA lookup ────────────────────────────────────────────────────────────

    def coa_lookup(self, acct: str) -> Optional[Dict[str, Any]]:
        '''Return COA entry for acct, or None if not found.'''
        entry = self.gl.coa.get(acct)
        if entry is None:
            return None
        return {
            'acct':     acct,
            'acctID':   entry.get('acctID', ''),
            'acctDesc': entry.get('acctDesc', ''),
            'acctType': self.gl.coa._Type(acct),
        }

    def coa_all(self) -> List[Dict[str, Any]]:
        '''Return all COA entries as a list for autocomplete.'''
        coa_dict = self.gl.coa.load()
        result = []
        for acct, entry in coa_dict.items():
            result.append({
                'acct':     acct,
                'acctID':   entry.get('acctID', ''),
                'acctDesc': entry.get('acctDesc', ''),
                'acctType': self.gl.coa._Type(acct),
            })
        return sorted(result, key=lambda x: x.get('acctID', ''))

    # ── Owners file discovery ─────────────────────────────────────────────────

    def _find_owners_path(self) -> Optional[Path]:
        '''Discover the llcOwners JSON file from known WkNode paths.'''
        for wk in self.eSession.oDict.values():
            p = Path(wk.o.FN())
            accts_dir = p.parent
            # Pattern: llcOwners_<LLCName>.json
            for candidate in accts_dir.glob('llcOwners_*.json'):
                return candidate
        return None

    def load_owners(self) -> List[Dict[str, Any]]:
        '''Load owner records from the llcOwners JSON file.'''
        path = self._find_owners_path()
        if path is None or not path.exists():
            return []
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ── Net income per owner ──────────────────────────────────────────────────

    def owner_pl_allocation(self) -> List[Dict[str, Any]]:
        '''
        Allocate net income/loss to each owner based on their pct field in llcOwners.
        Returns list of {oID, name, pct, net_income_share}.
        '''
        _, is_summary = self.buildIS()
        net_income = is_summary.get('net_income', 0.0)

        owners = self.load_owners()
        result = []
        for o in owners:
            pct = float(o.get('pct', 0))
            result.append({
                'oID':              o.get('oID', ''),
                'name':             ', '.join(o.get('nm', [])),
                'status':           o.get('status', ''),
                'pct':              pct,
                'net_income_share': round(net_income * pct, 2),
            })
        return result
