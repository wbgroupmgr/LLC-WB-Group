'''
ledger.stmtBS — v0.3 Balance-Sheet stmtOBJ hierarchy.

Per docs/LLC_stmtDesign.md "Design Decision v0.3":
    Five classes per stmtOBJ, no overlay between consumer concerns.

        stmtBS          — core data only (immutable aggregated BS rows)
        stmtBS_Tax      — Tax provisioning; reads bookNS_BS.json; nSpaceMap()
                          returns {formNm: [{fid, acct, fval}, ...]}
        stmtBS_Agg      — pipeline base; AggBy() returns a chainable aggregator
        stmtBS_View     — UI-facing; inherits the pipeline + convenience wrappers
        stmtBS_Reports  — stub (TBD)

Design rules honoured here:
    - v0.2 ledger/stmtBalanceSheet.py is NOT modified; v0.3 lives in this new file.
    - No save(); to_json() returns a JSON string.
    - No per-consumer _build() — _build() runs once on the base; each consumer
      shapes its own load() output without re-doing construction.
    - Only stmtOBJ_Tax exposes the IRS-form nSpaceMap semantics.
    - Pipeline pattern:
        ``stmtBS_View(...).AggBy().ViewBy(vb).GroupBy(keys).SortBy(keys).load()``

Inheritance:    stmtDB → ledgerDB → ledger.ledgerObject

SINGLE SOURCE OF TRUTH — the v0.3 General Ledger.  The BS aggregates the
``ledger.stmtGL.stmtGL`` row list (with the COA seed included so every
Asset/Liability/Equity account appears as a BS line even before any
posting).  Callers may still pass pre-built ``gl_records=...`` for test /
notebook paths that want to feed working-file edits directly.

Columns (alongside the _lineNo / _rowNm sentinels added by stmtDB):
    acctType, acct, acctSub, Debit, Credit, Balance

Timestamp: 2026.04.27 — v0.3.BS
'''

from __future__ import annotations

import json as _json
import os as _os
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import pandas as _pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

from ledger.stmtDB import stmtDB

# Account-type groupings — match v0.2 stmtBalanceSheet for parity.
BS_TYPES = {'Asset', 'Liability', 'Equity'}
BS_ORDER = ['Asset', 'Liability', 'Equity']


# ─────────────────────────────────────────────────────────────────────────────
# 1. stmtBS — core data only (aggregated BS rows, no view/tax overlay)
# ─────────────────────────────────────────────────────────────────────────────
class stmtBS(stmtDB):
    '''
    Immutable Balance Sheet snapshot — aggregated to one row per
    (acctType, acct, acctSub) plus a TOTAL row.  No view/agg/tax behaviour.

    Construction inputs (in preference order):
        1. gl_records=[{...}, ...]                  — pre-built GL row list
        2. (default) build a stmtGL with COA seed and pull its rows.

    Each row carries the columns defined in COLUMNS; the TOTAL row uses
    ``acctType='TOTAL'``.
    '''

    DEFAULT_TBLID = "BalanceSheet"
    COLUMNS = ['acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance']

    # PUBLISH_MAP intentionally empty for v0.3 — IRS publication is a
    # Tax-class concern, not core data.
    PUBLISH_MAP: Dict[str, List[Any]] = {}

    def __init__(self,
                 llc,
                 gl_records: Optional[List[Dict[str, Any]]] = None,
                 **kwargs):
        # Stash for _build() before the freeze.
        self._init_gl_records = gl_records
        super().__init__(llc, **kwargs)

    # ── stmtDB hook ──────────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        gl_records = self._init_gl_records
        if gl_records is None:
            gl_records = self._load_from_gl()

        rows, check = self._aggregate_bs(gl_records)

        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "version": "v0.3",
            "sourceMode": ("gl_records" if self._init_gl_records is not None
                           else "stmtGL"),
            "row_count": len(rows),
            "check": check,
            "note": (
                "v0.3 stmtBS — aggregated by (acctType, acct, acctSub). "
                "Use stmtBS_View pipeline (AggBy → ViewBy → GroupBy → "
                "SortBy → load) for slicing.  No save(); use to_json()."
            ),
        }
        self._check = check

    # ── Source loading (default: pull from v0.3 stmtGL) ──────────────────

    def _load_from_gl(self) -> List[Dict[str, Any]]:
        '''Default: build a v0.3 stmtGL with COA seeds and return its rows.'''
        try:
            from ledger.stmtGL import stmtGL
        except ImportError:
            from stmtGL import stmtGL  # pragma: no cover
        gl = stmtGL(self.llc)
        return list(gl._rows or [])

    # ── BS aggregation ───────────────────────────────────────────────────

    def _aggregate_bs(self,
                      gl_records: List[Dict[str, Any]]
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if _PANDAS_OK:
            return self._aggregate_bs_pandas(gl_records)
        return self._aggregate_bs_fallback(gl_records)

    def _aggregate_bs_pandas(self,
                             gl_records: List[Dict[str, Any]]
                             ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not gl_records:
            return [], {'asset': 0, 'liability': 0, 'equity': 0,
                        'equation_diff': 0, 'balanced': True}

        df = _pd.DataFrame(gl_records)
        if df.empty:
            return [], {'asset': 0, 'liability': 0, 'equity': 0,
                        'equation_diff': 0, 'balanced': True}

        if 'acctType' not in df.columns:
            df['acctType'] = ''
        df['amt'] = _pd.to_numeric(df.get('amt'), errors='coerce').fillna(0.0)

        bs = df[df['acctType'].isin(BS_TYPES)].copy()
        if bs.empty:
            return [], {'asset': 0, 'liability': 0, 'equity': 0,
                        'equation_diff': 0, 'balanced': True}

        if 'acctSub' in bs.columns:
            bs['acctSub'] = bs['acctSub'].fillna('').astype(str)
        else:
            bs['acctSub'] = ''

        grp = (bs.groupby(['acctType', 'acct', 'acctSub', 'aType'])['amt']
                 .sum().unstack(fill_value=0.0).reset_index())
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        order = {t: i for i, t in enumerate(BS_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct', 'acctSub']).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'acctSub',
                      'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        check = self._make_check(result)
        result.append(self._total_row(result))
        return result, check

    def _aggregate_bs_fallback(self,
                               gl_records: List[Dict[str, Any]]
                               ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        '''Pandas-free aggregator — same shape as the pandas path.'''
        try:
            from ledger.stmtGL import ledgerGeneral
            gl = ledgerGeneral(self.llc)
            classify = lambda v: gl.coa._Type(v)
        except Exception:
            classify = lambda v: ''

        buckets: Dict[tuple, Dict[str, float]] = {}
        for r in gl_records:
            at = r.get('acctType') or classify(r.get('acct', ''))
            if at not in BS_TYPES:
                continue
            acct     = r.get('acct', '')
            acct_sub = str(r.get('acctSub') or '')
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            atype = str(r.get('aType', 'Debit')).strip()
            key = (at, acct, acct_sub)
            if key not in buckets:
                buckets[key] = {'Debit': 0.0, 'Credit': 0.0}
            is_credit = atype in ('Credit', 'Cr', 'CR', 'C')
            buckets[key]['Credit' if is_credit else 'Debit'] += amt

        order = {t: i for i, t in enumerate(BS_ORDER)}
        result: List[Dict[str, Any]] = []
        for (at, acct, acct_sub), s in sorted(
                buckets.items(),
                key=lambda x: (order.get(x[0][0], 99), x[0][1], x[0][2])):
            d = round(s['Debit'],  2)
            c = round(s['Credit'], 2)
            result.append({'acctType': at, 'acct': acct, 'acctSub': acct_sub,
                           'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        check = self._make_check(result)
        result.append(self._total_row(result))
        return result, check

    @staticmethod
    def _make_check(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        a = round(sum(r['Balance'] for r in rows if r['acctType'] == 'Asset'),     2)
        l = round(sum(r['Balance'] for r in rows if r['acctType'] == 'Liability'), 2)
        e = round(sum(r['Balance'] for r in rows if r['acctType'] == 'Equity'),    2)
        diff = round(a + l + e, 2)
        return {'asset': a, 'liability': l, 'equity': e,
                'equation_diff': diff, 'balanced': abs(diff) < 0.01}

    @staticmethod
    def _total_row(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        td = round(sum(r['Debit']  for r in rows), 2)
        tc = round(sum(r['Credit'] for r in rows), 2)
        return {'acctType': 'TOTAL', 'acct': '', 'acctSub': '',
                'Debit': td, 'Credit': tc, 'Balance': round(td - tc, 2)}

    # ── Row-name derivation override ─────────────────────────────────────

    def _default_rowNm(self, row: Dict[str, Any], i: int) -> str:
        at = str(row.get('acctType', '') or '').strip()
        if at == 'TOTAL':
            return 'TOTAL'
        ac = str(row.get('acct', '') or '').strip()
        sub = str(row.get('acctSub', '') or '').strip()
        if ac and sub:
            return f"{ac}::{sub}"
        if ac:
            return ac
        return super()._default_rowNm(row, i)

    # ── v0.3 contract: to_json() instead of save() ────────────────────────

    def to_json(self, indent: int = 2) -> str:
        payload = {
            "meta":    self._meta,
            "columns": list(self._columns),
            "rows":    [
                {k: (v.isoformat() if hasattr(v, 'isoformat') else v)
                 for k, v in r.items()}
                for r in self._rows
            ],
        }
        return _json.dumps(payload, indent=indent, default=str)

    # ── Convenience: cell balance + named aggregates ─────────────────────

    def acct_balance(self, acct: str) -> float:
        '''Σ Balance for body rows whose acct matches.'''
        s = 0.0
        for r in self._rows:
            if r.get('acctType') == 'TOTAL':
                continue
            if r.get('acct') == acct:
                s += float(r.get('Balance') or 0)
        return round(s, 2)

    def taxAggregates(self) -> Dict[str, float]:
        '''
        Named BS aggregates consumed by IRS forms.

        Order of resolution:
            1. If the legacy v0.2 ``stmtFinancialReport.taxData()`` is wired
               and returns a ``bs_data`` dict, use it (preserves CPA semantics
               around AR / fixed-asset sub-buckets).
            2. Otherwise compute from this stmt's own rows — coarse but
               deterministic and pandas-free.

        Cached on the instance via ``object.__setattr__`` because stmtDB
        freezes us after _build().
        '''
        cache = getattr(self, '_taxAggregates_cache', None)
        if cache is not None:
            return dict(cache)

        agg: Dict[str, float] = {}
        # ── 1. v0.2 financial-report fast path (richer aggregates) ──
        try:
            try:
                from ledger.stmtFinancialReport import stmtFinancialReport
            except ImportError:
                from stmtFinancialReport import stmtFinancialReport  # pragma: no cover
            td = _json.loads(stmtFinancialReport(self.llc).taxData())
            agg = dict(td.get('bs_data', {}) or {})
        except Exception:
            agg = {}

        # ── 2. Fallback: compute from this stmt's rows ──
        if not agg:
            agg = self._taxAggregates_local()

        # ── 3. Inject placed_in_service_date (not in stmtFinancialReport) ──
        if 'placed_in_service_date' not in agg:
            agg['placed_in_service_date'] = self._earliest_in_service_date()

        try:
            object.__setattr__(self, '_taxAggregates_cache', agg)
        except Exception:
            pass
        return dict(agg)

    def _taxAggregates_local(self) -> Dict[str, float]:
        '''Pure local computation when stmtFinancialReport is unavailable.'''
        rows = [r for r in self._rows if r.get('acctType') != 'TOTAL']
        s = lambda pred: round(sum(float(r.get('Balance') or 0)
                                   for r in rows if pred(r)), 2)
        starts = lambda r, p: str(r.get('acct') or '').startswith(p)

        cash      = s(lambda r: starts(r, 'Acct.Cash.'))
        ar        = s(lambda r: starts(r, 'Acct.AR.') or
                                str(r.get('acct') or '') == 'Acct.AR')
        buildings = s(lambda r: starts(r, 'Acct.Fixed.Tangible'))
        accum_dep = s(lambda r: starts(r, 'Acct.Fixed.Depreciation'))
        land      = s(lambda r: starts(r, 'Acct.Fixed.Land'))
        total_assets = s(lambda r: r.get('acctType') == 'Asset')
        other_assets = round(total_assets
                             - cash - ar - buildings - accum_dep - land, 2)

        payables  = s(lambda r: r.get('acctType') == 'Liability'
                                 and starts(r, 'Acct.AP'))
        mortgage  = s(lambda r: r.get('acctType') == 'Liability'
                                 and (starts(r, 'Acct.Mortgage')
                                      or starts(r, 'Acct.Notes.LongTerm')))
        total_liab = s(lambda r: r.get('acctType') == 'Liability')
        other_liab = round(total_liab - payables - mortgage, 2)

        total_equity      = s(lambda r: r.get('acctType') == 'Equity')
        total_liab_capital = round(total_liab + total_equity, 2)

        return {
            'cash':                   cash,
            'ar':                     ar,
            'buildings':              buildings,
            'accum_depr':             accum_dep,
            'land':                   land,
            'other_assets':           other_assets,
            'total_assets':           total_assets,
            'payables':               payables,
            'mortgage':               mortgage,
            'other_liab':             other_liab,
            'total_equity':           total_equity,
            'total_liab_capital':     total_liab_capital,
            'placed_in_service_date': self._earliest_in_service_date(),
        }

    def _earliest_in_service_date(self) -> str:
        '''Scan llcAssets JSON for the earliest InService date (M/YYYY format).'''
        try:
            import json as _j2
            top  = _os.path.expanduser(getattr(self.llc, 'TOP', '') or '')
            acct = getattr(self.llc, 'dirAccounting', '') or ''
            name = getattr(self.llc, 'objName', '') or ''
            fn   = _os.path.join(top, acct, 'Accts', f'llcAssets_{name}.json')
            if not _os.path.exists(fn):
                return ''
            records = _j2.loads(open(fn).read())
            inservice = [r for r in records
                         if r.get('Ledger') == 'Acct.Fixed.Tangible.InService']
            # Prefer LLC-owned (propOwner == {'LLC': 100}); fall back to all InService.
            llc_owned = [r for r in inservice if r.get('propOwner') == {'LLC': 100}]
            dts = [r['dt'] for r in (llc_owned or inservice) if r.get('dt')]
            if not dts:
                return ''
            dts.sort()
            parts = dts[0].split('.')
            if len(parts) >= 2:
                return f"{int(parts[1])}/{parts[0]}"  # "8/2025"
            return dts[0]
        except Exception:
            return ''

    def last_check(self) -> Dict[str, Any]:
        return dict(self._check) if getattr(self, '_check', None) else {}


# ─────────────────────────────────────────────────────────────────────────────
# 2. stmtBS_Tax — IRS form provisioning (reads bookNS_BS.json)
# ─────────────────────────────────────────────────────────────────────────────
class stmtBS_Tax(stmtBS):
    '''
    Tax-provisioning view of the BS.  Reads ``bookNS_BS.json`` and resolves
    each (fid, UAS) pair to a value sourced from the BS.

    Recognised UAS prefixes:
        "BS.<name>"   → taxAggregates()[name]
        "Acct.<...>"  → acct_balance(...) on this BS
        "Profile.*", "IS.*"  → out of stmtBS_Tax scope; returns None.
    '''

    BKNS_FN = "bookNS_BS.json"

    def _bkNS_path(self) -> str:
        try:
            top  = _os.path.expanduser(getattr(self.llc, 'TOP', '') or '')
            acct = getattr(self.llc, 'dirAccounting', '') or ''
            yr   = getattr(self.llc, 'YEAR', None) or getattr(self.llc, 'yr', None)
            yr   = str(int(yr)) if yr else ''
            return _os.path.join(top, acct, yr, self.BKNS_FN) if yr \
                   else _os.path.join(top, acct, self.BKNS_FN)
        except Exception:
            return ''

    def _bkNS_load(self) -> Dict[str, Any]:
        fn = self._bkNS_path()
        if not fn or not _os.path.exists(fn):
            return {}
        try:
            with open(fn, 'r') as fio:
                return _json.load(fio)
        except Exception as err:
            print(f"stmtBS_Tax: could not load {fn}: {err}")
            return {}

    def nSpaceMap(self) -> Dict[str, List[Dict[str, Any]]]:        # type: ignore[override]
        bkNS = self._bkNS_load()
        out: Dict[str, List[Dict[str, Any]]] = {}
        for formNm, mappings in bkNS.items():
            if not formNm or formNm.startswith('_'):
                continue
            if not isinstance(mappings, list):
                continue
            entries: List[Dict[str, Any]] = []
            for pair in mappings:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                fid, acct = pair[0], pair[1]
                entries.append({
                    'fid':  fid,
                    'acct': acct,
                    'fval': self._resolve_acct(acct),
                })
            out[formNm] = entries
        return out

    def load(self) -> List[Dict[str, Any]]:                        # type: ignore[override]
        '''Flat [{fid, acct, fval, formNm}, ...] over every form section.'''
        flat: List[Dict[str, Any]] = []
        for formNm, entries in self.nSpaceMap().items():
            for e in entries:
                flat.append({**e, 'formNm': formNm})
        return flat

    def loadFillDict(self, formNm: str) -> Dict[str, Any]:
        '''
        Return ``{normalized_fid: fval}`` for the requested IRS form section.

        See ``stmtGL_Tax.loadFillDict`` for the v0.3 contract — same shape
        for all stmtOBJ_Tax/stmtProfile classes:
          * fids are normalized to zero-padded ``F###``;
          * UAS paths starting with ``Cplx`` -> fval = literal 'Complex';
          * other unresolved entries -> fval = None (BLANK, not Complex).
        '''
        import re
        bkNS = self._bkNS_load()
        mappings = bkNS.get(formNm, []) or []
        out: Dict[str, Any] = {}
        if not isinstance(mappings, list):
            return out
        for pair in mappings:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            fid_raw, acct = pair[0], pair[1]
            fid = self._normalizeFid(fid_raw)
            if not fid:
                continue
            if isinstance(acct, str) and (acct == 'Cplx' or acct.startswith('Cplx.')):
                out[fid] = 'Complex'
                continue
            try:
                out[fid] = self._resolve_acct(acct)
            except Exception:
                out[fid] = None
        return out

    @staticmethod
    def _normalizeFid(fid: Any) -> str:
        '''Canonical fid form: f1/F1 -> F001; non-numeric tokens pass through.'''
        import re
        if fid is None:
            return ''
        s = str(fid).strip()
        if not s:
            return ''
        m = re.match(r'^[fF]?(\d+)$', s)
        if m:
            return f'F{int(m.group(1)):03d}'
        return s

    # ── DataFrame export (full PDF-fill DF) ──────────────────────────────

    SOURCE_TAG = 'BS'

    def to_pdf(self):
        '''
        Return the full PDF-fill DataFrame for this stmt's tax mapping.

        Columns: [fid, acct, fval, formNm, source]
        Each row is one (fid, UAS) pair from ``bookNS_BS.json`` resolved
        against the current BS (BS.* aggregates or COA Acct.* balances).
        The ``source`` column is fixed to 'BS' so a unified PDF-fill DF
        can be sliced per stmt-of-origin.

        Returns ``pandas.DataFrame``.  Raises ImportError if pandas is
        not available.
        '''
        try:
            import pandas as pd
        except ImportError as err:                           # pragma: no cover
            raise ImportError(
                "stmtBS_Tax.to_pdf() requires pandas; install pandas "
                "or use load() for a list-of-dicts.") from err
        rows = self.load()
        for r in rows:
            r.setdefault('source', self.SOURCE_TAG)
        cols = ['fid', 'acct', 'fval', 'formNm', 'source']
        return pd.DataFrame(rows, columns=cols)

    # ── UAS resolver ─────────────────────────────────────────────────────

    def _resolve_acct(self, acct: Any) -> Any:
        if not isinstance(acct, str):
            return None
        if acct.startswith('Val.'):
            return acct[4:]
        if acct.startswith('BS.'):
            return self.taxAggregates().get(acct[3:])
        if acct.startswith('Acct.'):
            return self.acct_balance(acct)
        # Profile.* / IS.* are owned by other stmtOBJ_Tax modules.
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 3. _Pipeline — chainable aggregator (AggBy → ViewBy → GroupBy → SortBy → load)
# ─────────────────────────────────────────────────────────────────────────────
class _Pipeline:
    '''
    Chainable pipeline produced by stmtBS_Agg.AggBy().

    Stages operate on the *aggregated* BS row list (one row per acct).
    ViewBy slices by acctType.  GroupBy can re-bucket to a coarser key
    set (e.g. group by acctType only) — Debit/Credit/Balance are summed.
    '''

    BS_VIEW_BY_OPTIONS = ['All', 'ByAsset', 'ByLiability', 'ByEquity', 'Details']

    def __init__(self, rows: List[Dict[str, Any]],
                 columns: List[str], parent: stmtDB):
        # Body rows only (drop any TOTAL row from the parent set).
        self._rows0 = [dict(r) for r in rows if r.get('acctType') != 'TOTAL']
        self._columns = list(columns)
        self._parent = parent
        self._view_by: str = 'All'
        self._group_by: Optional[List[str]] = None
        self._sort_by:  Optional[List[str]] = None
        self._totals_row: bool = False

    def ViewBy(self, view_by: str = 'All') -> "_Pipeline":
        self._view_by = view_by or 'All'
        return self

    def GroupBy(self, keys: Optional[Iterable[str]] = None) -> "_Pipeline":
        self._group_by = list(keys) if keys else None
        return self

    def SortBy(self, keys: Optional[Iterable[str]] = None) -> "_Pipeline":
        self._sort_by = list(keys) if keys else None
        return self

    def WithTotals(self, totals: bool = True) -> "_Pipeline":
        self._totals_row = bool(totals)
        return self

    def load(self) -> List[Dict[str, Any]]:
        rows = self._apply_view_by(self._rows0, self._view_by)
        if self._group_by:
            rows = self._apply_group_by(rows, self._group_by)
        if self._sort_by:
            rows = self._apply_sort_by(rows, self._sort_by)
        if self._totals_row:
            rows = list(rows) + [stmtBS._total_row(rows)]
        return rows

    @staticmethod
    def _apply_view_by(rows: List[Dict[str, Any]],
                       view_by: str) -> List[Dict[str, Any]]:
        if not view_by or view_by in ('All', 'Details'):  # Details = no type filter
            return [dict(r) for r in rows]
        # 'ByAsset' / 'ByLiability' / 'ByEquity'
        acct_type = view_by[2:]
        return [dict(r) for r in rows if r.get('acctType') == acct_type]

    @staticmethod
    def _apply_group_by(rows: List[Dict[str, Any]],
                        keys: List[str]) -> List[Dict[str, Any]]:
        '''
        Re-bucket pre-aggregated BS rows by ``keys``; sum Debit/Credit and
        recompute Balance.  ``keys`` should be a subset of
        ``acctType / acct / acctSub`` for a meaningful re-aggregation.
        '''
        from collections import defaultdict
        bucket: Dict[tuple, Dict[str, float]] = defaultdict(
            lambda: {'Debit': 0.0, 'Credit': 0.0}
        )
        for r in rows:
            k = tuple(r.get(kk, '') for kk in keys)
            bucket[k]['Debit']  += float(r.get('Debit')  or 0)
            bucket[k]['Credit'] += float(r.get('Credit') or 0)
        out: List[Dict[str, Any]] = []
        for k, v in bucket.items():
            row: Dict[str, Any] = {kk: kv for kk, kv in zip(keys, k)}
            d = round(v['Debit'],  2)
            c = round(v['Credit'], 2)
            row['Debit']   = d
            row['Credit']  = c
            row['Balance'] = round(d - c, 2)
            out.append(row)
        return out

    @staticmethod
    def _apply_sort_by(rows: List[Dict[str, Any]],
                       keys: List[str]) -> List[Dict[str, Any]]:
        order = {t: i for i, t in enumerate(BS_ORDER)}

        def _sk(r: Dict[str, Any]) -> tuple:
            out: List[Any] = []
            for k in keys:
                v = r.get(k, '')
                if k == 'acctType':
                    out.append(order.get(str(v), 99))
                else:
                    out.append(str(v or ''))
            return tuple(out)

        return sorted([dict(r) for r in rows], key=_sk)


# ─────────────────────────────────────────────────────────────────────────────
# 4. stmtBS_Agg — pipeline entry point
# ─────────────────────────────────────────────────────────────────────────────
class stmtBS_Agg(stmtBS):
    '''Adds the ``AggBy()`` pipeline entry point.'''

    def AggBy(self) -> _Pipeline:
        return _Pipeline(self._rows, self._columns, self)


# ─────────────────────────────────────────────────────────────────────────────
# 5. stmtBS_View — UI consumer + convenience wrappers
# ─────────────────────────────────────────────────────────────────────────────
class stmtBS_View(stmtBS_Agg):
    '''
    UI consumer of the BS.  Use the AggBy() pipeline to filter/group;
    the convenience wrappers preserve the v0.2 view-by semantics so the
    existing balance_sheet_view.html template can be reused.
    '''

    VIEW_BY_OPTIONS = list(_Pipeline.BS_VIEW_BY_OPTIONS)

    def view(self, view_by: str = 'All',
             with_totals: bool = True) -> List[Dict[str, Any]]:
        '''
        Aggregate on (acctType, acct-top2, acctMinor) for both All and Details.
        Normalise acct → top-2 UAS nodes; roll acctSub variants into acctMinor.
        '''
        rows = self.AggBy().ViewBy(view_by).load()

        # Normalise: acct → top-2 nodes, acctMinor → remainder
        normed = []
        for r in rows:
            parts = str(r.get('acct', '')).split('.')
            r2 = dict(r)
            r2['acct']      = '.'.join(parts[:2]) if len(parts) >= 2 else r.get('acct', '')
            r2['acctMinor'] = '.'.join(parts[2:]) if len(parts) > 2 else ''
            normed.append(r2)

        pipe = _Pipeline(normed, self._columns, self)
        result = (pipe
                  .ViewBy('All')
                  .GroupBy(['acctType', 'acct', 'acctMinor'])
                  .WithTotals(with_totals)
                  .load())

        # Sort by BS_ORDER (not alphabetically) then acct then acctMinor.
        _order = {t: i for i, t in enumerate(BS_ORDER)}
        body  = [r for r in result if r.get('acctType') != 'TOTAL']
        total = [r for r in result if r.get('acctType') == 'TOTAL']
        body.sort(key=lambda r: (_order.get(r.get('acctType', ''), 99),
                                  str(r.get('acct', '')),
                                  str(r.get('acctMinor', ''))))
        return body + total

    def stats(self) -> Dict[str, Any]:
        '''Account-count + totals dict; mirrors v0.2 stats() shape.'''
        rows = list(self._rows)
        acct_counts: Dict[str, int] = {}
        total_row: Dict[str, Any] = {}
        for row in rows:
            at = row.get('acctType', '')
            if at == 'TOTAL':
                total_row = row
                continue
            acct_counts[at] = acct_counts.get(at, 0) + 1
        out: Dict[str, Any] = {
            'Accounts':    sum(acct_counts.values()),
            'TotalDebit':  total_row.get('Debit',   0),
            'TotalCredit': total_row.get('Credit',  0),
            'NetBalance':  total_row.get('Balance', 0),
            'ByAcctType':  acct_counts,
        }
        chk = self.last_check()
        if chk and chk.get('balanced') is False:
            out['⚠ Equation'] = f"diff={chk.get('equation_diff', '?')}"
        return out

    def is_balanced(self, tolerance: float = 0.01) -> bool:
        chk = self.last_check()
        if not chk:
            return True
        return abs(chk.get('equation_diff', 0)) < tolerance


# ─────────────────────────────────────────────────────────────────────────────
# 6. stmtBS_Reports — stub
# ─────────────────────────────────────────────────────────────────────────────
class stmtBS_Reports(stmtBS):
    '''Reports consumer — stub for v0.3.  Implementation TBD.'''

    def load(self) -> List[Dict[str, Any]]:                        # type: ignore[override]
        raise NotImplementedError(
            "stmtBS_Reports is a v0.3 stub — implementation TBD."
        )
