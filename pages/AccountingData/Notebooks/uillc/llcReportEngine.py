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

        Sources merged, in priority order (first source wins on tID collision):
            llcAssets → llcExpRev → llcPayables → llcReceivables

        v0.2: llcPayables and llcReceivables are converted to GL entries
        (via the same toDoubleEntry expansion) and merged in alongside the
        existing llcAssets / llcExpRev GL.
        '''
        if self._gl_cache is not None and not force:
            return self._gl_cache

        asset_list = self._load_source('llcAssets')
        er_list    = self._load_source('llcExpRev')
        ap_list    = self._load_source('llcPayables')
        ar_list    = self._load_source('llcReceivables')

        asset_expanded = self.gl.toDoubleEntry(asset_list)
        er_expanded    = self.gl.toDoubleEntry(er_list)
        ap_expanded    = self.gl.toDoubleEntry(ap_list)
        ar_expanded    = self.gl.toDoubleEntry(ar_list)

        # Order matters on tID collisions: first source wins the dedup.
        self._gl_cache = self.gl.mergeGL(
            [asset_expanded, er_expanded, ap_expanded, ar_expanded],
            resolve_dups=resolve_dups,
        )
        return self._gl_cache

    def getGLListWithDups(self) -> List[Dict[str, Any]]:
        '''GL list keeping all records and flagging cross-source dups.

        v0.2: llcPayables and llcReceivables are also converted to GL entries
        and folded in so that the General Ledger view reflects A/P + A/R.
        '''
        er_list    = self._load_source('llcExpRev')
        asset_list = self._load_source('llcAssets')
        ap_list    = self._load_source('llcPayables')
        ar_list    = self._load_source('llcReceivables')
        er_expanded    = self.gl.toDoubleEntry(er_list)
        asset_expanded = self.gl.toDoubleEntry(asset_list)
        ap_expanded    = self.gl.toDoubleEntry(ap_list)
        ar_expanded    = self.gl.toDoubleEntry(ar_list)
        return self.gl.mergeGL(
            [er_expanded, asset_expanded, ap_expanded, ar_expanded],
            resolve_dups=False,
        )

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

        # Normalise acctSub so groupby doesn't split on NaN
        if 'acctSub' in bs.columns:
            bs['acctSub'] = bs['acctSub'].fillna('').astype(str)
        else:
            bs['acctSub'] = ''

        grp = (
            bs.groupby(['acctType', 'acct', 'acctSub', 'aType'])['amt']
            .sum().unstack(fill_value=0.0).reset_index()
        )
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        order = {t: i for i, t in enumerate(BS_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct', 'acctSub']).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        # Accounting equation check: Assets = Liabilities + Equity
        # In Debit-Credit convention: asset_bal + liab_bal + equity_bal = 0
        asset_bal  = round(sum(r['Balance'] for r in result if r['acctType'] == 'Asset'),  2)
        liab_bal   = round(sum(r['Balance'] for r in result if r['acctType'] == 'Liability'), 2)
        equity_bal = round(sum(r['Balance'] for r in result if r['acctType'] == 'Equity'), 2)
        diff       = round(asset_bal + liab_bal + equity_bal, 2)

        total_d = round(sum(r['Debit']   for r in result), 2)
        total_c = round(sum(r['Credit']  for r in result), 2)
        result.append({
            'acctType': 'TOTAL', 'acct': '', 'acctSub': '',
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
            acct    = r.get('acct', '')
            acct_sub = str(r.get('acctSub') or '')
            try:   amt = float(r.get('amt', 0) or 0)
            except: amt = 0.0
            atype = str(r.get('aType', 'Debit')).strip()
            key = (at, acct, acct_sub)
            if key not in buckets:
                buckets[key] = {'Debit': 0.0, 'Credit': 0.0}
            buckets[key]['Debit' if atype not in ('Credit','Cr','CR','C') else 'Credit'] += amt

        order = {t: i for i, t in enumerate(BS_ORDER)}
        result = []
        for (at, acct, acct_sub), s in sorted(buckets.items(), key=lambda x: (order.get(x[0][0], 99), x[0][1], x[0][2])):
            d = round(s['Debit'], 2); c = round(s['Credit'], 2)
            result.append({'acctType': at, 'acct': acct, 'acctSub': acct_sub, 'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({'acctType': 'TOTAL', 'acct': '', 'acctSub': '', 'Debit': total_d, 'Credit': total_c,
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

        # Normalise acctSub so groupby doesn't split on NaN
        if 'acctSub' in idf.columns:
            idf['acctSub'] = idf['acctSub'].fillna('').astype(str)
        else:
            idf['acctSub'] = ''

        grp = (
            idf.groupby(['acctType', 'acct', 'acctSub', 'aType'])['amt']
            .sum().unstack(fill_value=0.0).reset_index()
        )
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        order = {t: i for i, t in enumerate(IS_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct', 'acctSub']).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

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
            'acctSub':  '',
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
            acct     = r.get('acct', '')
            acct_sub = str(r.get('acctSub') or '')
            try:   amt = float(r.get('amt', 0) or 0)
            except: amt = 0.0
            atype = str(r.get('aType', 'Debit')).strip()
            key = (at, acct, acct_sub)
            if key not in buckets:
                buckets[key] = {'Debit': 0.0, 'Credit': 0.0}
            buckets[key]['Debit' if atype not in ('Credit','Cr','CR','C') else 'Credit'] += amt

        order = {t: i for i, t in enumerate(IS_ORDER)}
        result = []
        for (at, acct, acct_sub), s in sorted(buckets.items(), key=lambda x: (order.get(x[0][0], 99), x[0][1], x[0][2])):
            d = round(s['Debit'], 2); c = round(s['Credit'], 2)
            result.append({'acctType': at, 'acct': acct, 'acctSub': acct_sub, 'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        income_net  = round(sum(-(r['Balance']) for r in result if r['acctType'] == 'Income'), 2)
        expense_net = round(sum(  r['Balance']  for r in result if r['acctType'] == 'Expense'), 2)
        net_income  = round(income_net - expense_net, 2)
        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({'acctType': 'TOTAL', 'acct': f'Net Income: {net_income:,.2f}', 'acctSub': '',
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

    # ── K-1 / IS-per-member helpers ───────────────────────────────────────────

    @staticmethod
    def _owner_first_name(o: Dict[str, Any]) -> str:
        nm = o.get('nm', '')
        if isinstance(nm, list):
            return nm[0] if nm else o.get('oID', '')
        return str(nm) if nm else o.get('oID', '')

    def _rent_income_total(self) -> float:
        '''Sum Credit amounts for Acct.Rev.Rent entries in the GL.'''
        total = 0.0
        for r in self.getGLList(resolve_dups=True):
            if r.get('acct') != 'Acct.Rev.Rent':
                continue
            atype = str(r.get('aType', '')).strip().lower()
            if atype in ('credit', 'cr', 'c'):
                try:
                    total += float(r.get('amt', 0) or 0)
                except (TypeError, ValueError):
                    pass
        return round(total, 2)

    def _interest_expense_total(self) -> float:
        '''
        Sum Debit amounts for Acct.Exp.Other entries where
        acctSub contains "interest" OR desc contains "interest" (case-insensitive).
        '''
        total = 0.0
        for r in self.getGLList(resolve_dups=True):
            if r.get('acct') != 'Acct.Exp.Other':
                continue
            acct_sub = str(r.get('acctSub') or '').lower()
            desc     = str(r.get('desc')    or '').lower()
            if 'interest' not in acct_sub and 'interest' not in desc:
                continue
            atype = str(r.get('aType', '')).strip().lower()
            if atype in ('debit', 'dr', 'd'):
                try:
                    total += float(r.get('amt', 0) or 0)
                except (TypeError, ValueError):
                    pass
        return round(total, 2)

    def _contributions_by_owner(self) -> Dict[str, float]:
        '''
        Per-owner capital contributions: GL Credit entries to Acct.Equity.Owner.Capital.Funds
        weighted by the record's propOwners (integer %).
        '''
        result: Dict[str, float] = {}
        for r in self.getGLList(resolve_dups=True):
            if r.get('acct') != 'Acct.Equity.Owner.Capital.Funds':
                continue
            atype = str(r.get('aType', '')).strip().lower()
            if atype not in ('credit', 'cr', 'c'):
                continue
            prop_owners = r.get('propOwners')
            if not isinstance(prop_owners, dict):
                continue
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            for oID, pct in prop_owners.items():
                try:
                    result[str(oID)] = result.get(str(oID), 0.0) + amt * float(pct) / 100.0
                except (TypeError, ValueError):
                    pass
        return {k: round(v, 2) for k, v in result.items()}

    def _capital_end_year_by_owner(self) -> Dict[str, float]:
        '''
        Capital Account End of Year: GL Debit entries to Acct.Fixed.Tangible* accounts
        weighted by propOwners (integer %).  Represents partner book-value share of
        tangible fixed assets.
        '''
        result: Dict[str, float] = {}
        for r in self.getGLList(resolve_dups=True):
            acct = r.get('acct', '')
            if not acct.startswith('Acct.Fixed.Tangible'):
                continue
            atype = str(r.get('aType', '')).strip().lower()
            if atype not in ('debit', 'dr', 'd'):
                continue
            prop_owners = r.get('propOwners')
            if not isinstance(prop_owners, dict):
                continue
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            for oID, pct in prop_owners.items():
                try:
                    result[str(oID)] = result.get(str(oID), 0.0) + amt * float(pct) / 100.0
                except (TypeError, ValueError):
                    pass
        return {k: round(v, 2) for k, v in result.items()}

    # ── Income Statement per member ───────────────────────────────────────────

    def buildISPerMember(self) -> Tuple[List[Dict], List[str], Dict]:
        '''
        Income Statement with per-owner allocation columns.

        Layout:
          INCOME section (acctType = Income)
            [income data rows — Bal = Credit − Debit, positive]
            SubTotal Income row         (row_type='income-subtotal')
          EXPENSE section (acctType = Expense, excl. Acct.Exp.Depreciation)
            [expense data rows — Bal = Credit − Debit, negative]
            SubTotal Expense row        (row_type='expense-subtotal')
          ─────────────────────────────────────────────────────
          Net Income (before Depr)      (row_type='net-income')
          Acct.Exp.Depreciation         (row_type='depreciation')
          Net Income (w/ Depreciation)  (row_type='net-income-depr')
          Member Distribution           (row_type='distribution', 0 if NI w/ Depr < 0)

        Bal convention throughout: Credit − Debit
          • Income rows:  positive
          • Expense rows: negative
          • Depreciation: negative (reduces income)

        summary keys:
          income_subtotal, expense_subtotal, net_income,
          depreciation, net_income_with_depr
        '''
        DEPR_ACCT   = 'Acct.Exp.Depreciation'
        is_rows, _  = self.buildIS(view_by='All')
        owners      = self.load_owners()
        owner_names = [self._owner_first_name(o) for o in owners]

        # ── bucket rows by section ────────────────────────────────────────────
        income_rows:  List[tuple] = []   # (row_dict, eff_bal)
        expense_rows: List[tuple] = []
        deprec_val    = 0.0              # positive depreciation amount

        for row in is_rows:
            if row.get('acctType') == 'TOTAL':
                continue
            debit  = float(row.get('Debit',  0) or 0)
            credit = float(row.get('Credit', 0) or 0)
            eff_bal = round(credit - debit, 2)   # positive for income, neg for expense

            if row.get('acct') == DEPR_ACCT:
                deprec_val += round(debit - credit, 2)   # keep as positive amount
            elif row.get('acctType') == 'Income':
                income_rows.append((row, eff_bal))
            else:                                         # Expense (excl. depr)
                expense_rows.append((row, eff_bal))

        # ── helper: build one data or summary row ─────────────────────────────
        def _make_row(at, acct, acct_sub, eff_bal, rtype):
            r: Dict[str, Any] = {
                'acctType': at, 'acct': acct, 'acctSub': acct_sub,
                'Bal': round(eff_bal, 2), 'row_type': rtype,
            }
            for o, nm in zip(owners, owner_names):
                pct = float(o.get('pct', 0))
                r[nm] = round(eff_bal * pct, 2)
            return r

        result: List[Dict[str, Any]] = []

        # ── INCOME section ────────────────────────────────────────────────────
        for row, eff_bal in income_rows:
            result.append(_make_row(
                row.get('acctType', ''), row.get('acct', ''),
                row.get('acctSub', ''), eff_bal, 'data'))

        income_total = round(sum(eb for _, eb in income_rows), 2)
        result.append(_make_row('', 'SubTotal Income', '', income_total, 'income-subtotal'))

        # ── EXPENSE section (no depreciation) ────────────────────────────────
        for row, eff_bal in expense_rows:
            result.append(_make_row(
                row.get('acctType', ''), row.get('acct', ''),
                row.get('acctSub', ''), eff_bal, 'data'))

        expense_total = round(sum(eb for _, eb in expense_rows), 2)   # negative
        result.append(_make_row(
            '', 'SubTotal Expense (excl. Depreciation)', '', expense_total, 'expense-subtotal'))

        # ── Net Income (before depreciation) ─────────────────────────────────
        ni_before = round(income_total + expense_total, 2)
        result.append(_make_row('', 'Net Income (before Depreciation)', '', ni_before, 'net-income'))

        # ── Depreciation line (after Net Income) ─────────────────────────────
        depr_eff = round(-deprec_val, 2)     # negative: reduces income
        result.append(_make_row('', 'Acct.Exp.Depreciation', '', depr_eff, 'depreciation'))

        # ── Net Income (w/ Depreciation) ──────────────────────────────────────
        ni_with_depr = round(ni_before + depr_eff, 2)
        result.append(_make_row('', 'Net Income (w/ Depreciation)', '', ni_with_depr, 'net-income-depr'))

        # ── Member Distribution (0 if NI w/ Depr < 0) ────────────────────────
        dist: Dict[str, Any] = {
            'acctType': '', 'acct': 'Member Distribution', 'acctSub': '',
            'Bal': max(0.0, ni_with_depr), 'row_type': 'distribution',
        }
        for o, nm in zip(owners, owner_names):
            pct   = float(o.get('pct', 0))
            share = round(ni_with_depr * pct, 2)
            dist[nm] = max(0.0, share)
        result.append(dist)

        summary = {
            'income_subtotal':      income_total,
            'expense_subtotal':     expense_total,       # negative
            'net_income':           ni_before,
            'depreciation':         round(deprec_val, 2),
            'net_income_with_depr': ni_with_depr,
        }
        return result, owner_names, summary

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
