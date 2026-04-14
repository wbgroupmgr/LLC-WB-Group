'''
llcBalanceSheet — computed read-only view
Aggregates GL data (llcExpRev + llcAssets) grouped by Asset / Equity / Liability.
Output: flat list of {acctType, acct, Debit, Credit, Balance} rows + TOTAL row.
Rendered by financial_view.html.

Deduplication: delegates to ledgerGeneral.mergeGL(resolve_dups=True) with
llcAssets passed first so its records win over llcExpRev duplicates.

Timestamp of last change: 2026.04.13
'''

from typing import Any, Dict, List

from ledger.ledgerGeneral import ledgerGeneral

try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False


# Account types shown on the Balance Sheet
BS_ACCT_TYPES = {'Asset', 'Equity', 'Liability'}

# Desired sort order for acctType sections
BS_TYPE_ORDER = ['Asset', 'Liability', 'Equity']


class llcBalanceSheet:
    '''
    Read-only computed Balance Sheet view.
    Groups GL data by acctType / acct / aType (Debit vs Credit),
    pivots into Debit / Credit / Balance columns, appends a TOTAL row.
    '''

    # ViewBy options for the dropdown
    VIEW_BY_OPTIONS = ['All', 'ByAsset', 'ByLiability', 'ByEquity']

    def __init__(self, eSession):
        self.eSession = eSession
        self.gl = ledgerGeneral(eSession.llc)

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.gl = ledgerGeneral(eSession.llc)

    def object_name(self) -> str:
        return self.__class__.__name__

    # ── internal helpers ──────────────────────────────────────────────────────

    def _load_source(self, name: str) -> List[Dict[str, Any]]:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return []
        tObj = wk.o
        data = tObj.load()
        return data if isinstance(data, list) else []

    def _wk_fn(self, name: str) -> str:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return None
        tObj = wk.o
        return tObj.FN() if tObj else None

    def _merge_gl(self) -> List[Dict[str, Any]]:
        '''Merge llcAssets + llcExpRev; llcAssets wins dedup (passed first).'''
        asset_list = self._load_source('llcAssets')
        er_list    = self._load_source('llcExpRev')
        return self.gl.mergeGL([asset_list, er_list], resolve_dups=True)

    def _apply_view_by(self, rows: List[Dict[str, Any]], view_by: str) -> List[Dict[str, Any]]:
        '''Pre-filter raw GL rows before aggregation. 'ByAsset' → keep only Asset rows, etc.'''
        if not view_by or view_by == 'All':
            return rows
        acct_type = view_by[2:]  # strip leading 'By'
        return [r for r in rows if r.get('acctType', '') == acct_type]

    def _compute_pandas(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        '''Use pandas groupby to aggregate.'''
        df = pd.DataFrame(rows)

        # Filter to BS account types
        if 'acctType' in df.columns:
            df = df[df['acctType'].isin(BS_ACCT_TYPES)].copy()
        if df.empty:
            return []

        df['amt'] = pd.to_numeric(df.get('amt', 0), errors='coerce').fillna(0.0)
        df['aType'] = df.get('aType', 'Debit').fillna('Debit')

        # Pivot: rows=acctType+acct, cols=aType (Debit/Credit)
        grp = (
            df.groupby(['acctType', 'acct', 'aType'])['amt']
            .sum()
            .unstack(fill_value=0.0)
            .reset_index()
        )

        if 'Debit' not in grp.columns:
            grp['Debit'] = 0.0
        if 'Credit' not in grp.columns:
            grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        # Sort sections in standard BS order
        type_order = {t: i for i, t in enumerate(BS_TYPE_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: type_order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct']).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        # TOTAL row
        total_d = round(sum(r['Debit']   for r in result), 2)
        total_c = round(sum(r['Credit']  for r in result), 2)
        result.append({
            'acctType': 'TOTAL',
            'acct':     '',
            'Debit':    total_d,
            'Credit':   total_c,
            'Balance':  round(total_d - total_c, 2),
        })
        return result

    def _compute_fallback(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        '''Pure-Python fallback when pandas unavailable.'''
        buckets: Dict[tuple, Dict[str, float]] = {}
        for row in rows:
            at = row.get('acctType', '')
            if at not in BS_ACCT_TYPES:
                continue
            acct = row.get('acct', '')
            try:
                amt = float(row.get('amt', 0) or 0)
            except (ValueError, TypeError):
                amt = 0.0
            a_type = str(row.get('aType', 'Debit')).strip()
            key = (at, acct)
            if key not in buckets:
                buckets[key] = {'Debit': 0.0, 'Credit': 0.0}
            buckets[key][a_type if a_type in ('Debit', 'Credit') else 'Debit'] += amt

        type_order = {t: i for i, t in enumerate(BS_TYPE_ORDER)}
        result = []
        for (at, acct), sums in sorted(
            buckets.items(), key=lambda x: (type_order.get(x[0][0], 99), x[0][1])
        ):
            d = round(sums.get('Debit', 0.0), 2)
            c = round(sums.get('Credit', 0.0), 2)
            result.append({'acctType': at, 'acct': acct, 'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({
            'acctType': 'TOTAL', 'acct': '',
            'Debit': total_d, 'Credit': total_c, 'Balance': round(total_d - total_c, 2),
        })
        return result

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        rows = self._merge_gl()
        if not rows:
            return []
        rows = self._apply_view_by(rows, view_by)
        if _PANDAS_OK:
            return self._compute_pandas(rows)
        return self._compute_fallback(rows)

    def stats(self) -> Dict[str, Any]:
        rows = self.load()
        acct_counts: Dict[str, int] = {}
        total_row = {}
        for row in rows:
            at = row.get('acctType', '')
            if at == 'TOTAL':
                total_row = row
                continue
            acct_counts[at] = acct_counts.get(at, 0) + 1

        return {
            'Accounts':    sum(acct_counts.values()),
            'TotalDebit':  total_row.get('Debit', 0),
            'TotalCredit': total_row.get('Credit', 0),
            'NetBalance':  total_row.get('Balance', 0),
            'ByAcctType':  acct_counts,
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'sources': {
                'llcExpRev': self._wk_fn('llcExpRev'),
                'llcAssets': self._wk_fn('llcAssets'),
            },
            'acctTypes': list(BS_ACCT_TYPES),
            'note': 'Read-only. Dedup by llcAssets-first. Groups Asset / Liability / Equity.',
        }

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()
