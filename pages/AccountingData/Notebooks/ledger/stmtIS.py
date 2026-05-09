'''
ledger.stmtIS — v0.3 Income-Statement stmtOBJ hierarchy.

Per docs/LLC_stmtDesign.md "Design Decision v0.3":
    Five classes per stmtOBJ, no overlay between consumer concerns.

        stmtIS          — core data only (immutable aggregated IS rows)
        stmtIS_Tax      — Tax provisioning; reads bookNS_IS.json; nSpaceMap()
                          returns {formNm: [{fid, acct, fval}, ...]}
        stmtIS_Agg      — pipeline base; AggBy() returns a chainable aggregator
        stmtIS_View     — UI-facing; pipeline + view() + per_member()
        stmtIS_Reports  — stub (TBD)

Design rules honoured here:
    - v0.2 ledger/stmtIncomeStmt.py is NOT modified; v0.3 lives in this new file.
    - No save(); to_json() returns a JSON string.
    - Only stmtOBJ_Tax exposes the IRS-form nSpaceMap semantics.
    - Pipeline pattern:
        ``stmtIS_View(...).AggBy().ViewBy(vb).GroupBy(keys).SortBy(keys).load()``

PerMember note (v0.3 §4 "Future Consideration"):  some stmtOBJ need their
data propagated X times per llcOwners (Sch_K_1).  IS is one of these.
The pipeline gains a ``PerMember(owners)`` stage which appends per-owner
allocation columns to each row; the convenience wrapper
``stmtIS_View.per_member(owners)`` preserves the v0.2
``build_per_member()`` row schema for the legacy IS member template.

Inheritance:    stmtDB → ledgerDB → ledger.ledgerObject

SINGLE SOURCE OF TRUTH — the v0.3 General Ledger.  The IS aggregates the
``ledger.stmtGL.stmtGL`` row list (with the COA seed included so every
Income/Expense COA account appears as an IS line even before any posting).

Columns (alongside the _lineNo / _rowNm sentinels added by stmtDB):
    acctType, acct, acctSub, Debit, Credit, Balance

The final row is the TOTAL / Net-Income row:
    acctType='TOTAL', acct=f"Net Income: {net_income:,.2f}",  Balance=net_income

Timestamp: 2026.04.27 — v0.3.IS
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

# Account-type groupings — match v0.2 stmtIncomeStmt for parity.
IS_TYPES = {'Income', 'Expense'}
IS_ORDER = ['Income', 'Expense']

DEPR_ACCT = 'Acct.Exp.Depreciation'

# Ordinary income accounts — acct starts with this prefix (COA acctIDs 4000-4090).
# All other Income accounts are treated as Rental income.
# Ordinary Expense accounts (Acct.Exp.Ord.*) don't exist in the COA yet → subtotal = 0.
ORDINARY_INCOME_PREFIX = 'Acct.Rev.Ord.'


# ─────────────────────────────────────────────────────────────────────────────
# 1. stmtIS — core data only (aggregated IS rows, no view/agg/tax overlay)
# ─────────────────────────────────────────────────────────────────────────────
class stmtIS(stmtDB):
    '''
    Immutable Income Statement snapshot — aggregated to one row per
    (acctType, acct, acctSub) plus a TOTAL row carrying Net Income.

    Construction inputs (in preference order):
        1. gl_records=[{...}, ...]                  — pre-built GL row list
        2. (default) build a stmtGL with COA seed and pull its rows.
    '''

    DEFAULT_TBLID = "IncomeStmt"
    COLUMNS = ['acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance']

    PUBLISH_MAP: Dict[str, List[Any]] = {}

    def __init__(self,
                 llc,
                 gl_records: Optional[List[Dict[str, Any]]] = None,
                 **kwargs):
        self._init_gl_records = gl_records
        super().__init__(llc, **kwargs)

    # ── stmtDB hook ──────────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        gl_records = self._init_gl_records
        if gl_records is None:
            gl_records = self._load_from_gl()

        # Stash for downstream PerMember stage (immutable callers).
        self._gl_records = list(gl_records or [])

        rows, summary = self._aggregate_is(gl_records)

        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "version": "v0.3",
            "sourceMode": ("gl_records" if self._init_gl_records is not None
                           else "stmtGL"),
            "row_count": len(rows),
            "summary": summary,
            "note": (
                "v0.3 stmtIS — aggregated by (acctType, acct, acctSub). "
                "Balance row carries net_income.  Use stmtIS_View pipeline "
                "(AggBy → ViewBy → GroupBy → SortBy → load) for slicing.  "
                "No save(); use to_json()."
            ),
        }
        self._summary = summary

    # ── Source loading (default: pull from v0.3 stmtGL) ──────────────────

    def _load_from_gl(self) -> List[Dict[str, Any]]:
        '''Default: build a v0.3 stmtGL with COA seeds and return its rows.'''
        try:
            from ledger.stmtGL import stmtGL
        except ImportError:
            from stmtGL import stmtGL  # pragma: no cover
        gl = stmtGL(self.llc)
        return list(gl._rows or [])

    # ── IS aggregation ───────────────────────────────────────────────────

    def _aggregate_is(self,
                      gl_records: List[Dict[str, Any]]
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if _PANDAS_OK:
            return self._aggregate_is_pandas(gl_records)
        return self._aggregate_is_fallback(gl_records)

    def _aggregate_is_pandas(self,
                             gl_records: List[Dict[str, Any]]
                             ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not gl_records:
            return [], {'income': 0, 'expense': 0, 'net_income': 0}

        df = _pd.DataFrame(gl_records)
        if df.empty:
            return [], {'income': 0, 'expense': 0, 'net_income': 0}

        if 'acctType' not in df.columns:
            df['acctType'] = ''
        df['amt'] = _pd.to_numeric(df.get('amt'), errors='coerce').fillna(0.0)

        idf = df[df['acctType'].isin(IS_TYPES)].copy()
        if idf.empty:
            return [], {'income': 0, 'expense': 0, 'net_income': 0}

        if 'acctSub' in idf.columns:
            idf['acctSub'] = idf['acctSub'].fillna('').astype(str)
        else:
            idf['acctSub'] = ''

        grp = (idf.groupby(['acctType', 'acct', 'acctSub', 'aType'])['amt']
                  .sum().unstack(fill_value=0.0).reset_index())
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        order = {t: i for i, t in enumerate(IS_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct', 'acctSub']).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'acctSub',
                      'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        summary = stmtIS._compute_summary(result)
        result.extend(stmtIS._make_summary_rows(result))
        return result, summary

    def _aggregate_is_fallback(self,
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
            if at not in IS_TYPES:
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

        order = {t: i for i, t in enumerate(IS_ORDER)}
        result: List[Dict[str, Any]] = []
        for (at, acct, acct_sub), s in sorted(
                buckets.items(),
                key=lambda x: (order.get(x[0][0], 99), x[0][1], x[0][2])):
            d = round(s['Debit'],  2)
            c = round(s['Credit'], 2)
            result.append({'acctType': at, 'acct': acct, 'acctSub': acct_sub,
                           'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        summary = stmtIS._compute_summary(result)
        result.extend(stmtIS._make_summary_rows(result))
        return result, summary

    @staticmethod
    def _compute_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        '''
        Compute the enriched IS summary from data rows (no TOTAL/summary rows).
        Income credits are negative-balance; we negate so summary values read
        as positive amounts.  Ordinary income = Acct.Rev.Ord.* accounts.
        '''
        def _is_ord(r: Dict[str, Any]) -> bool:
            return str(r.get('acct') or '').startswith(ORDINARY_INCOME_PREFIX)

        rental_income    = round(sum(-r['Balance'] for r in rows
                                     if r.get('acctType') == 'Income' and not _is_ord(r)), 2)
        ordinary_income  = round(sum(-r['Balance'] for r in rows
                                     if r.get('acctType') == 'Income' and _is_ord(r)), 2)
        rental_expense   = round(sum( r['Balance'] for r in rows
                                     if r.get('acctType') == 'Expense'), 2)
        ordinary_expense = 0.0   # no Acct.Exp.Ord.* accounts in COA yet
        net_ordinary     = round(ordinary_income  - ordinary_expense, 2)
        net_rental       = round(rental_income    - rental_expense,   2)
        net_income       = round(net_ordinary + net_rental, 2)
        return {
            # backward-compat keys
            'income':    round(rental_income + ordinary_income, 2),
            'expense':   round(rental_expense + ordinary_expense, 2),
            'net_income': net_income,
            # new detail keys
            'subtotal_rental_income':    rental_income,
            'subtotal_ordinary_income':  ordinary_income,
            'subtotal_rental_expense':   rental_expense,
            'subtotal_ordinary_expense': ordinary_expense,
            'net_ordinary': net_ordinary,
            'net_rental':   net_rental,
        }

    @staticmethod
    def _make_summary_rows(rows: List[Dict[str, Any]],
                           view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Build IS summary rows for appending after the data rows.
        All rows carry acctType='TOTAL' so the template routes them through
        the TOTAL block; row_type disambiguates styling and semantics.

        view_by='ByIncome'  → only income subtotals
        view_by='ByExpense' → only expense subtotals
        otherwise           → all 7 rows (6 subtotals/nets + grand-total)
        '''
        s  = stmtIS._compute_summary(rows)
        td = round(sum(r.get('Debit',  0) for r in rows), 2)
        tc = round(sum(r.get('Credit', 0) for r in rows), 2)

        def _srow(label: str, rtype: str, balance: float) -> Dict[str, Any]:
            return {
                'acctType': 'TOTAL', 'acct': label, 'acctSub': '',
                'Debit': 0.0, 'Credit': 0.0, 'Balance': balance,
                'row_type': rtype,
            }

        if view_by == 'ByIncome':
            return [
                _srow('SubTotal Rental Income',   'rental-income-subtotal',   s['subtotal_rental_income']),
                _srow('SubTotal Ordinary Income', 'ordinary-income-subtotal', s['subtotal_ordinary_income']),
            ]
        if view_by == 'ByExpense':
            return [
                _srow('SubTotal Rental Expense',   'rental-expense-subtotal',   s['subtotal_rental_expense']),
                _srow('SubTotal Ordinary Expense', 'ordinary-expense-subtotal', s['subtotal_ordinary_expense']),
            ]
        return [
            _srow('SubTotal Rental Income',    'rental-income-subtotal',    s['subtotal_rental_income']),
            _srow('SubTotal Ordinary Income',  'ordinary-income-subtotal',  s['subtotal_ordinary_income']),
            _srow('SubTotal Rental Expense',   'rental-expense-subtotal',   s['subtotal_rental_expense']),
            _srow('SubTotal Ordinary Expense', 'ordinary-expense-subtotal', s['subtotal_ordinary_expense']),
            _srow('Net Ordinary Income/Loss',  'net-ordinary',              s['net_ordinary']),
            _srow('Net Rental Income/Loss',    'net-rental',                s['net_rental']),
            {
                'acctType': 'TOTAL', 'acct': 'Total Net Income/Loss', 'acctSub': '',
                'Debit': td, 'Credit': tc, 'Balance': s['net_income'],
                'row_type': 'total-net',
            },
        ]

    @staticmethod
    def _summarise_and_total(rows: List[Dict[str, Any]]
                             ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        '''Thin backward-compat wrapper — returns (summary, single grand-total row).'''
        summary = stmtIS._compute_summary(rows)
        td = round(sum(r.get('Debit',  0) for r in rows), 2)
        tc = round(sum(r.get('Credit', 0) for r in rows), 2)
        total_row = {
            'acctType': 'TOTAL',
            'acct':     f'Total Net Income/Loss: {summary["net_income"]:,.2f}',
            'acctSub':  '',
            'Debit':    td,
            'Credit':   tc,
            'Balance':  summary['net_income'],
            'row_type': 'total-net',
        }
        return summary, total_row

    # ── Row-name override ────────────────────────────────────────────────

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
        Named IS aggregates consumed by IRS forms.

        Order of resolution:
            1. v0.2 ``stmtFinancialReport.taxData()['is_data']`` if available
               (preserves CPA semantics around revenue / expense buckets).
            2. Local computation from this stmt's rows otherwise.

        Cached on the instance via ``object.__setattr__``.
        '''
        cache = getattr(self, '_taxAggregates_cache', None)
        if cache is not None:
            return dict(cache)

        agg: Dict[str, float] = {}
        # ── 1. v0.2 fast path ──
        for mod_name, cls_name in (
            ('ledger.stmtFinancialReport', 'stmtFinancialReport'),
            ('ledger.rptFinancialReport',  'rptFinancialReport'),
            ('stmtFinancialReport',        'stmtFinancialReport'),
            ('rptFinancialReport',         'rptFinancialReport'),
        ):
            try:
                mod = __import__(mod_name, fromlist=[cls_name])
                cls = getattr(mod, cls_name)
                td = _json.loads(cls(self.llc).taxData())
                agg = dict(td.get('is_data', {}) or {})
                if agg:
                    break
            except Exception:
                continue

        # ── 2. Local fallback ──
        if not agg:
            agg = self._taxAggregates_local()

        try:
            object.__setattr__(self, '_taxAggregates_cache', agg)
        except Exception:
            pass
        return dict(agg)

    def _taxAggregates_local(self) -> Dict[str, float]:
        '''Pure local computation when the financial-report layer is absent.'''
        rows = [r for r in self._rows if r.get('acctType') != 'TOTAL']
        starts = lambda r, p: str(r.get('acct') or '').startswith(p)

        # Income side — flip sign so credits → positive revenue.
        rev = lambda pred: round(sum(-float(r.get('Balance') or 0)
                                     for r in rows if pred(r)), 2)
        # Expense side — debits already positive.
        exp = lambda pred: round(sum(float(r.get('Balance') or 0)
                                     for r in rows if pred(r)), 2)

        rent_income     = rev(lambda r: starts(r, 'Acct.Rev.Rent'))
        interest_income = rev(lambda r: starts(r, 'Acct.Rev.Interest'))
        other_income    = rev(lambda r: r.get('acctType') == 'Income'
                                    and not starts(r, 'Acct.Rev.Rent')
                                    and not starts(r, 'Acct.Rev.Interest'))
        total_income    = rev(lambda r: r.get('acctType') == 'Income')

        depreciation     = exp(lambda r: r.get('acct') == DEPR_ACCT)
        repairs          = exp(lambda r: starts(r, 'Acct.Exp.Repair'))
        salaries         = exp(lambda r: starts(r, 'Acct.Exp.Salaries'))
        taxes_licenses   = exp(lambda r: starts(r, 'Acct.Exp.Taxes')
                                       or starts(r, 'Acct.Exp.Licenses'))
        interest_expense = exp(lambda r: starts(r, 'Acct.Exp.Interest'))
        total_expenses   = exp(lambda r: r.get('acctType') == 'Expense')
        other_deductions = round(total_expenses
                                 - depreciation - repairs - salaries
                                 - taxes_licenses - interest_expense, 2)

        net_income = round(total_income - total_expenses, 2)

        # No Acct.Rev.Ord.* accounts in COA yet → ordinary = 0, rental = total.
        subtotal_rental_income = total_income
        subtotal_ordinary_income = 0.0
        net_ordinary = 0.0
        net_rental   = net_income

        # distributions_cash isn't on the IS — we expose 0.0 here so IRS
        # form publishers that consult this layer get a non-None value.
        return {
            'rent_income':       rent_income,
            'interest_income':   interest_income,
            'other_income':      other_income,
            'total_income':      total_income,
            'salaries':          salaries,
            'repairs':           repairs,
            'taxes_licenses':    taxes_licenses,
            'interest_expense':  interest_expense,
            'depreciation':      depreciation,
            'other_deductions':  other_deductions,
            'total_expenses':    total_expenses,
            'net_income':        net_income,
            'distributions_cash': 0.0,
            # Rental / Ordinary split (Form 8825 aggregate fids)
            'subtotal_rental_income':    subtotal_rental_income,
            'subtotal_ordinary_income':  subtotal_ordinary_income,
            'subtotal_rental_expense':   total_expenses,
            'subtotal_ordinary_expense': 0.0,
            'net_ordinary':              net_ordinary,
            'net_rental':                net_rental,
        }

    def last_summary(self) -> Dict[str, Any]:
        return dict(self._summary) if getattr(self, '_summary', None) else {}


# ─────────────────────────────────────────────────────────────────────────────
# 2. stmtIS_Tax — IRS form provisioning (reads bookNS_IS.json)
# ─────────────────────────────────────────────────────────────────────────────
class stmtIS_Tax(stmtIS):
    '''
    Tax-provisioning view of the IS.  Reads ``bookNS_IS.json`` and resolves
    each (fid, UAS) pair to a value sourced from the IS.

    Recognised UAS prefixes:
        "IS.<name>"   → taxAggregates()[name]
        "Acct.<...>"  → acct_balance(...) on this IS
        "Profile.*", "BS.*"  → out of stmtIS_Tax scope; returns None.

    Per-partner Sch_K1 multiplication is performed by the consumer
    (irsForm.savePDF) using llcOwners.pct — the values returned here are
    partnership-level totals.
    '''

    BKNS_FN = "bookNS_IS.json"

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
            print(f"stmtIS_Tax: could not load {fn}: {err}")
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

        Form8825 uses a dynamic per-property builder (``_build_f8825_filldict``)
        instead of the static bookNS_IS.json mapping, because the form has one
        column per rental property and the number/names of properties vary.

        All other forms use the static bookNS_IS.json mapping.
        '''
        if formNm == 'Form8825':
            return self._build_f8825_filldict()
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

    def _build_f8825_filldict(self) -> Dict[str, Any]:
        '''
        Build a Form 8825 fill dict dynamically from IS ByProperty data.

        Form 8825 has one column per rental property (A-D on page 1,
        E-H on page 2).  Properties are sorted alphabetically by propNm
        and assigned columns in that order.

        Account-to-line mapping (Form 8825 line numbers):
            Acct.Rev.Rent         → Line 2a  (F023) Gross rents
            Acct.Rev.Fees.Other   → Line 2b  (F027) Other income
                                  → Line 2c  (F031) Income subtotal (computed)
            Acct.Exp.Repair       → Line 11  (F067) Repairs
            Acct.Exp.Util         → Line 12  (F071) Utilities
            Acct.Exp.Depreciation → Line 14  (F079) Depreciation
            Acct.Exp.Operating  ↘ → Line 17  (F091) Other (summed together)
            Acct.Exp.Other      ↗
                                  → Line 18  (F095) Expense subtotal (computed)
                                  → Line 19a (F099) Net income/loss (computed)

        Field numbering:
            Page 1 (props A-D): base_fid + col_offset (0-3)
            Page 2 (props E-H): Page 1 base + 119
        '''
        gl_records = getattr(self, '_gl_records', []) or []
        if not gl_records:
            return {}

        rows = _Pipeline._aggregate_by_property(gl_records, 'ByProperty')

        # base fid for the first property column (Col_a) of each line, per page
        _P1: Dict[str, int] = {
            'gross_rents':      23,   # Line 2a  F023
            'other_income':     27,   # Line 2b  F027
            'income_subtotal':  31,   # Line 2c  F031 (computed)
            'repairs':          67,   # Line 11  F067
            'utilities':        71,   # Line 12  F071
            'depreciation':     79,   # Line 14  F079
            'other':            91,   # Line 17  F091 (Operating + Other summed)
            'exp_subtotal':     95,   # Line 18  F095 (computed)
            'net_income':       99,   # Line 19a F099 (computed)
        }
        _P2: Dict[str, int] = {k: v + 119 for k, v in _P1.items()}

        # account → (line_key, negate)
        # Income: Balance is negative (credit), negate to get positive display value
        # Expense: Balance is positive (debit), use as-is
        # Acct.Exp.Operating and Acct.Exp.Other both fold into 'other' (F091, summed)
        _ACCT_LINE: Dict[str, tuple] = {
            'Acct.Rev.Rent':       ('gross_rents',  True),
            'Acct.Rev.Fees.Other': ('other_income', True),
            DEPR_ACCT:             ('depreciation', False),
            'Acct.Exp.Repair':     ('repairs',      False),
            'Acct.Exp.Util':       ('utilities',    False),
            'Acct.Exp.Operating':  ('other',        False),
            'Acct.Exp.Other':      ('other',        False),
        }

        prop_vals: Dict[str, Dict[str, float]] = {}
        for r in rows:
            if r.get('acctType') not in IS_TYPES:
                continue
            propNm = str(r.get('propNm', '') or '')
            acct   = str(r.get('acct',   '') or '')
            if not propNm or acct not in _ACCT_LINE:
                continue
            balance = float(r.get('Balance', 0) or 0)
            line_key, negate = _ACCT_LINE[acct]
            val = -balance if negate else balance
            if propNm not in prop_vals:
                prop_vals[propNm] = {}
            prop_vals[propNm][line_key] = prop_vals[propNm].get(line_key, 0.0) + val

        if not prop_vals:
            return {}

        # Compute derived subtotals per property
        for pv in prop_vals.values():
            pv['income_subtotal'] = pv.get('gross_rents', 0.0) + pv.get('other_income', 0.0)
            pv['exp_subtotal']    = (pv.get('repairs', 0.0) + pv.get('utilities', 0.0) +
                                     pv.get('depreciation', 0.0) + pv.get('other', 0.0))
            pv['net_income']      = pv['income_subtotal'] - pv['exp_subtotal']

        out: Dict[str, Any] = {}
        for i, propNm in enumerate(sorted(prop_vals.keys())):
            if i >= 8:
                break
            base_map = _P1 if i < 4 else _P2
            col = i if i < 4 else i - 4
            for line_key, base_fid in base_map.items():
                val = prop_vals[propNm].get(line_key, 0.0)
                if val == 0.0:
                    continue
                out[f'F{base_fid + col:03d}'] = round(val, 2)

        # Aggregate totals across all properties
        total_rental_income = round(sum(pv.get('income_subtotal', 0.0) for pv in prop_vals.values()), 2)
        total_rental_expense = round(sum(pv.get('exp_subtotal', 0.0) for pv in prop_vals.values()), 2)
        total_net = round(sum(pv.get('net_income', 0.0) for pv in prop_vals.values()), 2)
        if total_rental_income: out['F103'] = total_rental_income
        if total_rental_expense: out['F104'] = total_rental_expense
        # F106 = net ordinary income (0 — no ordinary income accounts yet)
        if total_net: out['F113'] = total_net
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

    SOURCE_TAG = 'IS'

    def to_pdf(self):
        '''
        Return the full PDF-fill DataFrame for this stmt's tax mapping.

        Columns: [fid, acct, fval, formNm, source]
        Each row is one (fid, UAS) pair from ``bookNS_IS.json`` resolved
        against the current IS (IS.* aggregates or COA Acct.* balances).
        Values are partnership-level totals — per-partner Sch_K1
        multiplication is applied downstream by the IRS-fill consumer.
        The ``source`` column is fixed to 'IS'.

        Returns ``pandas.DataFrame``.  Raises ImportError if pandas is
        not available.
        '''
        try:
            import pandas as pd
        except ImportError as err:                           # pragma: no cover
            raise ImportError(
                "stmtIS_Tax.to_pdf() requires pandas; install pandas "
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
        if acct.startswith('IS.'):
            return self.taxAggregates().get(acct[3:])
        if acct.startswith('Acct.'):
            return self.acct_balance(acct)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 3. _Pipeline — chainable aggregator + PerMember stage
# ─────────────────────────────────────────────────────────────────────────────
class _Pipeline:
    '''
    Chainable pipeline produced by stmtIS_Agg.AggBy().

    Stages:
        ViewBy(view_by)        — slice by acctType (ByIncome / ByExpense)
        GroupBy(keys)          — re-bucket pre-aggregated rows
        SortBy(keys)           — sort (acctType in IS_ORDER, others lex)
        WithTotals(bool)       — append the TOTAL / Net-Income row
        PerMember(owners)      — append per-owner allocation columns to
                                  each row.  Mutually exclusive with
                                  GroupBy because it consumes the body
                                  rows verbatim.
    '''

    IS_VIEW_BY_OPTIONS = ['All', 'ByIncome', 'ByExpense',
                          'ByProperty', 'ByPropertyDetails', 'PerMember']

    def __init__(self, rows: List[Dict[str, Any]],
                 columns: List[str], parent: stmtDB):
        # Body rows only (drop the TOTAL row from the parent set).
        self._rows0 = [dict(r) for r in rows if r.get('acctType') != 'TOTAL']
        self._columns = list(columns)
        self._parent = parent
        self._view_by: str = 'All'
        self._group_by: Optional[List[str]] = None
        self._sort_by:  Optional[List[str]] = None
        self._totals_row: bool = False
        self._owners:  Optional[List[Dict[str, Any]]] = None

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

    def PerMember(self,
                  owners: Optional[List[Dict[str, Any]]] = None) -> "_Pipeline":
        '''Stage that propagates each row by partner.pct (Sch_K_1 path).'''
        self._owners = list(owners or [])
        return self

    def load(self) -> List[Dict[str, Any]]:
        if self._view_by in ('ByProperty', 'ByPropertyDetails'):
            gl_records = getattr(self._parent, '_gl_records', []) or []
            rows = self._aggregate_by_property(gl_records, self._view_by)
            if self._totals_row:
                rows = list(rows) + stmtIS._make_summary_rows(rows, view_by=self._view_by or 'All')
            return rows

        rows = self._apply_view_by(self._rows0, self._view_by)
        if self._group_by:
            rows = self._apply_group_by(rows, self._group_by)
        if self._sort_by:
            rows = self._apply_sort_by(rows, self._sort_by)
        if self._owners is not None:
            rows = self._apply_per_member(rows, self._owners)
        if self._totals_row:
            rows = list(rows) + stmtIS._make_summary_rows(rows, view_by=self._view_by or 'All')
        return rows

    # ── Stage implementations ────────────────────────────────────────────

    @staticmethod
    def _apply_view_by(rows: List[Dict[str, Any]],
                       view_by: str) -> List[Dict[str, Any]]:
        if not view_by or view_by in ('All', 'PerMember'):
            return [dict(r) for r in rows]
        # 'ByIncome' / 'ByExpense'
        acct_type = view_by[2:]
        return [dict(r) for r in rows if r.get('acctType') == acct_type]

    @staticmethod
    def _apply_group_by(rows: List[Dict[str, Any]],
                        keys: List[str]) -> List[Dict[str, Any]]:
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
        order = {t: i for i, t in enumerate(IS_ORDER)}

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

    @staticmethod
    def _unstack_by_property(gl_records: List[Dict[str, Any]],
                             view_by: str
                             ) -> 'Tuple[List[Dict[str, Any]], List[str]]':
        '''
        Pivot GL records so each unique propNm becomes a column.

        Returns (rows, prop_names) where every row has:
            acctType, acct, [acctMinor, acctSub for Details], Balance,
            <propNm1>, <propNm2>, ...
        Plus Income-Subtotal, Expense-Subtotal, and Net-Income summary rows.
        '''
        from collections import defaultdict

        def _acct_minor(acct: str) -> str:
            parts = str(acct or '').split('.')
            return '.'.join(parts[2:]) if len(parts) > 2 else ''

        prop_names = sorted({
            str(r.get('propNm', '') or '')
            for r in gl_records
            if r.get('acctType') in IS_TYPES and float(r.get('amt', 0) or 0) != 0
            and str(r.get('propNm', '') or '')
        })

        # row_key → propNm → {Debit, Credit}
        by_key: Dict[tuple, Dict[str, Dict[str, float]]] = defaultdict(
            lambda: defaultdict(lambda: {'Debit': 0.0, 'Credit': 0.0})
        )
        for r in gl_records:
            at = r.get('acctType', '')
            if at not in IS_TYPES:
                continue
            acct    = str(r.get('acct', '') or '')
            prop_nm = str(r.get('propNm', '') or '')
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if amt == 0.0:
                continue
            atype = str(r.get('aType', 'Debit')).strip()
            if view_by == 'ByProperty':
                key = (at, acct, '', '')
            else:
                key = (at, acct, _acct_minor(acct), str(r.get('acctSub', '') or ''))
            is_credit = atype in ('Credit', 'Cr', 'CR', 'C')
            by_key[key][prop_nm]['Credit' if is_credit else 'Debit'] += amt

        order = {t: i for i, t in enumerate(IS_ORDER)}
        if view_by == 'ByProperty':
            sort_key = lambda item: (order.get(item[0][0], 99), item[0][1])
        else:
            sort_key = lambda item: (order.get(item[0][0], 99), item[0][1], item[0][2], item[0][3])

        def _prop_balance(prop_data: Dict, pnm: str) -> float:
            pd = prop_data.get(pnm, {'Debit': 0.0, 'Credit': 0.0})
            return round(pd['Debit'] - pd['Credit'], 2)

        result: List[Dict[str, Any]] = []
        rental_income_bal: Dict[str, float] = {p: 0.0 for p in prop_names}
        ord_income_bal:    Dict[str, float] = {p: 0.0 for p in prop_names}
        rental_income_total = 0.0
        ord_income_total    = 0.0
        expense_bal: Dict[str, float] = {p: 0.0 for p in prop_names}
        expense_total = 0.0

        for key, prop_data in sorted(by_key.items(), key=sort_key):
            at, acct, acct_minor, acct_sub = key
            total_d = sum(v['Debit'] for v in prop_data.values())
            total_c = sum(v['Credit'] for v in prop_data.values())
            balance = round(total_d - total_c, 2)
            row: Dict[str, Any] = {
                'acctType':  at, 'acct': acct,
                'acctMinor': acct_minor, 'acctSub': acct_sub,
                'Balance':   balance,
                'row_type':  'data',
            }
            for pnm in prop_names:
                pb = _prop_balance(prop_data, pnm)
                row[pnm] = pb
                if at == 'Income':
                    if acct.startswith(ORDINARY_INCOME_PREFIX):
                        ord_income_bal[pnm] = ord_income_bal.get(pnm, 0.0) + pb
                    else:
                        rental_income_bal[pnm] = rental_income_bal.get(pnm, 0.0) + pb
                else:
                    expense_bal[pnm] = expense_bal.get(pnm, 0.0) + pb
            if at == 'Income':
                if acct.startswith(ORDINARY_INCOME_PREFIX):
                    ord_income_total += balance
                else:
                    rental_income_total += balance
            else:
                expense_total += balance
            result.append(row)

        # ── Summary rows (7 rows) ──
        # Income balances are Debit-Credit (negative for credits); negate for display.
        def _summary_row(label: str, rtype: str,
                         bal: float, per_prop: Dict[str, float]) -> Dict[str, Any]:
            safe = lambda v: round(v, 2) or 0.0   # collapse -0.0 → 0.0
            r: Dict[str, Any] = {
                'acctType': '', 'acct': label, 'acctMinor': '', 'acctSub': '',
                'Balance': safe(bal), 'row_type': rtype,
            }
            for pnm in prop_names:
                r[pnm] = safe(per_prop.get(pnm, 0.0))
            return r

        _zero = {p: 0.0 for p in prop_names}
        rental_inc_disp  = {p: -rental_income_bal[p] for p in prop_names}
        ord_inc_disp     = {p: -ord_income_bal[p]    for p in prop_names}
        net_rental_bal   = {p: round(-rental_income_bal[p] - expense_bal[p], 2)
                            for p in prop_names}
        net_total_bal    = {p: round(net_rental_bal[p] - ord_income_bal[p], 2)
                            for p in prop_names}

        net_rental_total  = round(-rental_income_total - expense_total, 2)
        net_ord_total     = round(-ord_income_total, 2)
        net_total         = round(net_rental_total + net_ord_total, 2)

        result.append(_summary_row('SubTotal Rental Income',   'rental-income-subtotal',
                                   -rental_income_total,  rental_inc_disp))
        result.append(_summary_row('SubTotal Ordinary Income', 'ordinary-income-subtotal',
                                   -ord_income_total,     ord_inc_disp))
        result.append(_summary_row('SubTotal Rental Expense',  'rental-expense-subtotal',
                                   expense_total,          expense_bal))
        result.append(_summary_row('SubTotal Ordinary Expense','ordinary-expense-subtotal',
                                   0.0,                    _zero))
        result.append(_summary_row('Net Ordinary Income/Loss', 'net-ordinary',
                                   net_ord_total,          _zero))
        result.append(_summary_row('Net Rental Income/Loss',   'net-rental',
                                   net_rental_total,       net_rental_bal))
        result.append(_summary_row('Total Net Income/Loss',    'total-net',
                                   net_total,              net_total_bal))

        return result, prop_names

    @staticmethod
    def _aggregate_by_property(gl_records: List[Dict[str, Any]],
                               view_by: str) -> List[Dict[str, Any]]:
        '''
        Re-aggregate raw GL records by property for ByProperty / ByPropertyDetails.

        ByProperty:        group key = (acctType, acct, propNm)
        ByPropertyDetails: group key = (acctType, acct, acctMinor, acctSub, propNm)
        '''
        from collections import defaultdict

        def _acct_minor(acct: str) -> str:
            parts = str(acct or '').split('.')
            return '.'.join(parts[2:]) if len(parts) > 2 else ''

        buckets: Dict[tuple, Dict[str, float]] = defaultdict(
            lambda: {'Debit': 0.0, 'Credit': 0.0}
        )
        for r in gl_records:
            at = r.get('acctType', '')
            if at not in IS_TYPES:
                continue
            acct      = str(r.get('acct', '') or '')
            acct_sub  = str(r.get('acctSub',  '') or '')
            prop_nm   = str(r.get('propNm',   '') or '')
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if amt == 0.0:
                continue
            atype = str(r.get('aType', 'Debit')).strip()
            if view_by == 'ByProperty':
                key = (at, acct, '', '', prop_nm)
            else:
                key = (at, acct, _acct_minor(acct), acct_sub, prop_nm)
            is_credit = atype in ('Credit', 'Cr', 'CR', 'C')
            buckets[key]['Credit' if is_credit else 'Debit'] += amt

        order = {t: i for i, t in enumerate(IS_ORDER)}
        if view_by == 'ByProperty':
            sort_key = lambda x: (order.get(x[0][0], 99), x[0][1], x[0][4])
        else:
            sort_key = lambda x: (order.get(x[0][0], 99), x[0][1], x[0][2], x[0][4], x[0][3])

        result: List[Dict[str, Any]] = []
        for (at, acct, acct_minor, acct_sub, prop_nm), s in sorted(
                buckets.items(), key=sort_key):
            d = round(s['Debit'],  2)
            c = round(s['Credit'], 2)
            result.append({
                'acctType':  at,
                'acct':      acct,
                'acctMinor': acct_minor,
                'acctSub':   acct_sub,
                'propNm':    prop_nm,
                'Debit':     d,
                'Credit':    c,
                'Balance':   round(d - c, 2),
            })
        return result

    @staticmethod
    def _apply_per_member(rows: List[Dict[str, Any]],
                          owners: List[Dict[str, Any]]
                          ) -> List[Dict[str, Any]]:
        '''
        Append one column per owner whose value = row.Balance × owner.pct.

        owners item shape:  {oID, nm, pct, ...}.  ``nm`` may be a string
        or a [first, last] pair — we use the first-name as the column key.
        '''
        def _first_name(o: Dict[str, Any]) -> str:
            nm = o.get('nm', '')
            if isinstance(nm, list):
                return nm[0] if nm else o.get('oID', '')
            return str(nm) if nm else o.get('oID', '')

        names = [_first_name(o) for o in owners]
        out: List[Dict[str, Any]] = []
        for r in rows:
            new_r = dict(r)
            try:
                bal = float(r.get('Balance') or 0)
            except (TypeError, ValueError):
                bal = 0.0
            for o, nm in zip(owners, names):
                try:
                    pct = float(o.get('pct', 0) or 0)
                except (TypeError, ValueError):
                    pct = 0.0
                new_r[nm] = round(bal * pct, 2)
            out.append(new_r)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# 4. stmtIS_Agg — pipeline entry point
# ─────────────────────────────────────────────────────────────────────────────
class stmtIS_Agg(stmtIS):
    '''Adds the ``AggBy()`` pipeline entry point.'''

    def AggBy(self) -> _Pipeline:
        return _Pipeline(self._rows, self._columns, self)


# ─────────────────────────────────────────────────────────────────────────────
# 5. stmtIS_View — UI consumer + convenience wrappers
# ─────────────────────────────────────────────────────────────────────────────
class stmtIS_View(stmtIS_Agg):
    '''
    UI consumer of the IS.  ``view(view_by)`` mirrors the v0.2 single-frame
    output (with TOTAL row).  ``per_member(owners)`` returns the v0.2
    per-member row schema (data / sub-total / net-income / depreciation /
    distribution rows) for the legacy IS member template.
    '''

    VIEW_BY_OPTIONS = list(_Pipeline.IS_VIEW_BY_OPTIONS)  # includes ByProperty/ByPropertyDetails

    # ── Default IS view (Frame 1) ────────────────────────────────────────

    def view(self, view_by: str = 'All',
             with_totals: bool = True) -> List[Dict[str, Any]]:
        '''
        Pipeline:
            AggBy().ViewBy(view_by).SortBy(['acctType','acct','acctSub'])
                   .WithTotals(with_totals).load()
        '''
        return (self.AggBy()
                  .ViewBy(view_by)
                  .SortBy(['acctType', 'acct', 'acctSub'])
                  .WithTotals(with_totals)
                  .load())

    # ── PerMember view (Sch_K_1 row schema) ──────────────────────────────

    def per_member(self,
                   owners: Optional[List[Dict[str, Any]]] = None,
                   details: bool = False,
                   ) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
        '''
        v0.2-compatible per-member output:

            Returns (rows, owner_names, summary).

        Rows include the source IS lines (excluding depreciation), a
        SubTotal Income row, expense lines, a SubTotal Expense row,
        Net Income (before depreciation), the depreciation line, Net
        Income (w/ depreciation), and a Member Distribution row.

        Each owner-named column carries Bal × owner.pct (distribution row
        is clamped at zero per CPA convention).
        '''
        owners = list(owners or [])

        def _first_name(o: Dict[str, Any]) -> str:
            nm = o.get('nm', '')
            if isinstance(nm, list):
                return nm[0] if nm else o.get('oID', '')
            return str(nm) if nm else o.get('oID', '')

        owner_names = [_first_name(o) for o in owners]

        # Walk the body rows once; bucket Income vs Expense, capture
        # depreciation separately.  Use eff_bal = Credit − Debit so income
        # rows read as positive numbers (same convention as v0.2).
        income_rows:  List[Tuple[Dict[str, Any], float]] = []
        expense_rows: List[Tuple[Dict[str, Any], float]] = []
        deprec_val = 0.0

        for row in self._rows:
            if row.get('acctType') == 'TOTAL':
                continue
            try:
                debit  = float(row.get('Debit',  0) or 0)
                credit = float(row.get('Credit', 0) or 0)
            except (TypeError, ValueError):
                debit = credit = 0.0
            eff_bal = round(credit - debit, 2)

            if row.get('acct') == DEPR_ACCT:
                deprec_val += round(debit - credit, 2)
            elif row.get('acctType') == 'Income':
                income_rows.append((row, eff_bal))
            else:
                expense_rows.append((row, eff_bal))

        def _make_row(at: str, acct: str, acct_sub: str,
                      eff_bal: float, rtype: str) -> Dict[str, Any]:
            r: Dict[str, Any] = {
                'acctType': at, 'acct': acct, 'acctSub': acct_sub,
                'Bal': round(eff_bal, 2), 'row_type': rtype,
            }
            for o, nm in zip(owners, owner_names):
                try:
                    pct = float(o.get('pct', 0) or 0)
                except (TypeError, ValueError):
                    pct = 0.0
                r[nm] = round(eff_bal * pct, 2)
            return r

        result: List[Dict[str, Any]] = []

        def _emit_rows(bucket: List[Tuple[Dict[str, Any], float]]) -> None:
            if details:
                for row, eb in bucket:
                    result.append(_make_row(row.get('acctType', ''),
                                            row.get('acct', ''),
                                            row.get('acctSub', ''),
                                            eb, 'data'))
            else:
                # Aggregate by acct — collapse multiple acctSub rows
                seen: Dict[str, float] = {}
                seen_at: Dict[str, str] = {}
                order: List[str] = []
                for row, eb in bucket:
                    key = row.get('acct', '')
                    if key not in seen:
                        seen[key] = 0.0
                        seen_at[key] = row.get('acctType', '')
                        order.append(key)
                    seen[key] = round(seen[key] + eb, 2)
                for key in order:
                    result.append(_make_row(seen_at[key], key, '', seen[key], 'data'))

        # Income section
        _emit_rows(income_rows)
        income_total = round(sum(eb for _, eb in income_rows), 2)
        result.append(_make_row('', 'SubTotal Rental Income', '',
                                income_total, 'rental-income-subtotal'))
        result.append(_make_row('', 'SubTotal Ordinary Income', '',
                                0.0, 'ordinary-income-subtotal'))

        # Expense section (depreciation moved below)
        _emit_rows(expense_rows)
        expense_total = round(sum(eb for _, eb in expense_rows), 2)
        result.append(_make_row(
            '', 'SubTotal Rental Expense (excl. Depr)', '',
            expense_total, 'rental-expense-subtotal'))
        result.append(_make_row('', 'SubTotal Ordinary Expense', '',
                                0.0, 'ordinary-expense-subtotal'))

        result.append(_make_row('', 'Net Ordinary Income/Loss', '',
                                0.0, 'net-ordinary'))

        ni_before = round(income_total + expense_total, 2)
        result.append(_make_row('', 'Net Rental Income/Loss (before Depr)', '',
                                ni_before, 'net-rental'))

        depr_eff = round(-deprec_val, 2)
        result.append(_make_row('', 'Acct.Exp.Depreciation', '',
                                depr_eff, 'depreciation'))

        ni_with_depr = round(ni_before + depr_eff, 2)
        result.append(_make_row('', 'Total Net Income/Loss (w/ Depr)', '',
                                ni_with_depr, 'net-income-depr'))

        # Distribution row — clamp to zero per CPA convention.
        dist: Dict[str, Any] = {
            'acctType': '', 'acct': 'Member Distribution', 'acctSub': '',
            'Bal': max(0.0, ni_with_depr), 'row_type': 'distribution',
        }
        for o, nm in zip(owners, owner_names):
            try:
                pct = float(o.get('pct', 0) or 0)
            except (TypeError, ValueError):
                pct = 0.0
            share = round(ni_with_depr * pct, 2)
            dist[nm] = max(0.0, share)
        result.append(dist)

        summary = {
            'income_subtotal':      income_total,
            'expense_subtotal':     expense_total,
            'net_income':           ni_before,
            'depreciation':         round(deprec_val, 2),
            'net_income_with_depr': ni_with_depr,
        }
        return result, owner_names, summary

    # ── Stats ────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        rows = list(self._rows)
        acct_counts: Dict[str, int] = {}
        total_row: Dict[str, Any] = {}
        for row in rows:
            at = row.get('acctType', '')
            if at == 'TOTAL':
                total_row = row
                continue
            acct_counts[at] = acct_counts.get(at, 0) + 1
        summ = self.last_summary()
        return {
            'Accounts':    sum(acct_counts.values()),
            'TotalDebit':  total_row.get('Debit',   0),
            'TotalCredit': total_row.get('Credit',  0),
            'NetIncome':   summ.get('net_income', total_row.get('Balance', 0)),
            'Income':      summ.get('income',  0),
            'Expense':     summ.get('expense', 0),
            'ByAcctType':  acct_counts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 6. stmtIS_Reports — stub
# ─────────────────────────────────────────────────────────────────────────────
class stmtIS_Reports(stmtIS):
    '''Reports consumer — stub for v0.3.  Implementation TBD.'''

    def load(self) -> List[Dict[str, Any]]:                        # type: ignore[override]
        raise NotImplementedError(
            "stmtIS_Reports is a v0.3 stub — implementation TBD."
        )
