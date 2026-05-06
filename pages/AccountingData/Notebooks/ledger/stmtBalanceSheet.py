'''
ledger.stmtBalanceSheet — Constructed, immutable Balance Sheet statement.

Per DataModelGuide § 2:  constructed data object, immutable once instantiated,
every row has a line number, every column has a columnID, and every cell is
addressable by (stmtObj / tblID / rowNm / colNm).

Inheritance:    stmtDB → stmtObject → ledger.ledgerObject

SINGLE SOURCE OF TRUTH — the General Ledger.
The BS no longer loads llcAssets / llcPayables / llcReceivables directly.
Instead it constructs an ``ledger.stmtGeneralLedger`` (with ``include_coa_seed=True``
so every COA account shows as a line even with no real postings) and aggregates
its rows.  Callers may still pass pre-built ``gl_records=...`` for test / notebook
paths that want to supply GL records directly (e.g. after local working-file
edits).

Construction inputs (exactly one path is taken, in this preference order):
  1. gl_records=...                 — pre-built GL record list (fastest,
                                      used by the ui/ layer so working-
                                      file data is honoured).
  2. (default) Build an stmtGeneralLedger(include_coa_seed=True).

After construction the instance is FROZEN; any attribute write raises
StmtImmutableError.

Columns (beside the _lineNo/_rowNm sentinels added by stmtObject):
    acctType, acct, acctSub, Debit, Credit, Balance
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

from ledger.stmtDB import stmtDB


# Account-type groupings — match uillc.llcReportEngine for bit-identical output.
BS_TYPES = {'Asset', 'Liability', 'Equity'}
BS_ORDER  = ['Asset', 'Liability', 'Equity']


class stmtBalanceSheet(stmtDB):
    '''
    Immutable Balance Sheet constructed at instantiation time.

    VIEW_BY_OPTIONS is exposed so ui modules can reuse the same list of
    view-by filters they presented under the uillc layer.
    '''

    DEFAULT_TBLID = "BalanceSheet"
    COLUMNS = ['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'Debit', 'Credit', 'Balance']
    VIEW_BY_OPTIONS = ['All', 'ByAsset', 'ByLiability', 'ByEquity']

    # ── Form 1065 publish map (DataModelGuide § 4 / Phase 5) ─────────────────
    #
    # INTENTIONALLY EMPTY for Phase 5.  The Balance Sheet's Form 1065
    # bindings all reference aggregates that are NOT stored as cells in
    # the constructed table:
    #
    #   • ``total_assets``   = Σ rows where acctType == 'Asset'      → P1_F, L_14_2, L_22_2
    #   • ``cash``           = Σ rows where acct starts 'Acct.Cash.'  → L_1_2
    #   • ``ar``             = AR bucket                              → L_2a_2
    #   • ``buildings``      = building-cost sub-bucket               → L_9a_2
    #   • ``accum_depr``     = accumulated-depreciation sub-bucket    → L_9b_2
    #   • ``land``           = land sub-bucket                        → L_11_2
    #   • ``payables``       = Σ rows where acctType == 'Liability' + AP filter
    #   • ``mortgage``       = long-term notes payable bucket         → L_19a_2
    #   • ``total_equity``   = Σ Equity rows                          → L_21_2
    #   • ``total_liab_capital`` = Σ Liability + Equity rows          → L_22_2
    #
    # These aggregates are computed inside ``_aggregate_bs_*`` but stored
    # only in ``self._meta['check']`` (asset/liability/equity totals) —
    # they are not addressable via ``(rowNm, colNm)``.  Until a dedicated
    # aggregates API (see stmt/stmtFinancialReport.taxData()) lands in the
    # cell index, ``irs.Form1065.nSpaceMap()`` resolves these keys via
    # the legacy ``_FILL_MAP`` fallback path.
    PUBLISH_MAP = {}

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(self,
                 llc,
                 view_by: str = 'All',
                 gl_records: Optional[List[Dict[str, Any]]] = None,
                 **kwargs):
        # Stash construction inputs so _build() can use them.
        # (Normal attribute writes — class is not yet frozen.)
        self._init_view_by: str = view_by
        self._init_gl_records = gl_records

        # stmtObject.__init__ runs _build() then freezes the instance.
        super().__init__(llc, **kwargs)

    # ── Main build pipeline ──────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        gl_records = self._init_gl_records

        if gl_records is None:
            # Default path: source from stmtGeneralLedger with COA seeds
            # included so every Asset/Liability/Equity account appears
            # as a BS line even before any real postings.
            gl_records = self._load_from_general_ledger()

        rows, check = self._aggregate_bs(gl_records, self._init_view_by)

        # Populate stmtObject slots.
        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "view_by":  self._init_view_by,
            "check":    check,
            "sourceMode": (
                "gl_records"  if self._init_gl_records is not None
                else "generalLedger"
            ),
            "note":     "Read-only. Sourced from stmtGeneralLedger (COA-seeded). Assets = Liabilities + Equity check applied.",
        }
        # Keep a convenience handle; stmtObject will freeze us shortly.
        self._check = check

    # ── Source loading (default path: pull from General Ledger) ──────────────

    def _load_from_general_ledger(self) -> List[Dict[str, Any]]:
        '''
        Default: build an ``stmtGeneralLedger`` with COA seeds included so
        every COA account appears as a BS line and return its row list.
        The GL itself handles loading + double-entry expansion + merging
        of llcAssets / llcExpRev / llcPayables / llcReceivables.
        '''
        try:
            from ledger.stmtGeneralLedger import stmtGeneralLedger
        except ImportError:
            from stmtGeneralLedger import stmtGeneralLedger
        gl = stmtGeneralLedger(self.llc, view_by='All', include_coa_seed=True)
        return list(gl._rows or [])

    # ── BS aggregation ───────────────────────────────────────────────────────

    def _aggregate_bs(self,
                      gl_records: List[Dict[str, Any]],
                      view_by: str
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        '''
        Aggregate GL records into Balance Sheet rows.
        Mirrors uillc.llcReportEngine._buildBS_pandas for bit-identical output,
        and falls back to a pure-python path if pandas is unavailable.
        '''
        if _PANDAS_OK:
            return self._aggregate_bs_pandas(gl_records, view_by)
        return self._aggregate_bs_fallback(gl_records, view_by)

    def _aggregate_bs_pandas(self,
                             gl_records: List[Dict[str, Any]],
                             view_by: str
                             ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not gl_records:
            return [], {'balanced': True, 'equation_diff': 0}

        df = pd.DataFrame(gl_records)
        if df.empty:
            return [], {'balanced': True, 'equation_diff': 0}

        # Ensure acctType / amt cols exist.
        if 'acctType' not in df.columns:
            try:
                from ledger.ledgerGeneral import ledgerGeneral
                gl = ledgerGeneral(self.llc)
                df['acctType'] = df.get('acct').apply(lambda v: gl.coa._Type(v))
            except Exception:
                df['acctType'] = ''
        df['amt'] = pd.to_numeric(df.get('amt'), errors='coerce').fillna(0.0)

        bs = df[df['acctType'].isin(BS_TYPES)].copy()

        if view_by and view_by != 'All':
            acct_type = view_by[2:]  # 'ByAsset' → 'Asset'
            bs = bs[bs['acctType'] == acct_type]

        if bs.empty:
            return [], {'balanced': True, 'equation_diff': 0}

        if 'acctSub' in bs.columns:
            bs['acctSub'] = bs['acctSub'].fillna('').astype(str)
        else:
            bs['acctSub'] = ''
        if 'propNm' in bs.columns:
            bs['propNm'] = bs['propNm'].fillna('').astype(str)
        else:
            bs['propNm'] = ''

        grp = (
            bs.groupby(['acctType', 'acct', 'acctSub', 'propNm', 'aType'])['amt']
              .sum().unstack(fill_value=0.0).reset_index()
        )
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        def _acct_minor(acct):
            parts = str(acct or '').split('.')
            return '.'.join(parts[2:]) if len(parts) > 2 else ''
        grp['acctMinor'] = grp['acct'].map(_acct_minor)

        order = {t: i for i, t in enumerate(BS_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct', 'propNm', 'acctSub']).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        asset_bal  = round(sum(r['Balance'] for r in result if r['acctType'] == 'Asset'),  2)
        liab_bal   = round(sum(r['Balance'] for r in result if r['acctType'] == 'Liability'), 2)
        equity_bal = round(sum(r['Balance'] for r in result if r['acctType'] == 'Equity'), 2)
        diff       = round(asset_bal + liab_bal + equity_bal, 2)

        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({
            'acctType': 'TOTAL', 'acct': '', 'acctMinor': '', 'acctSub': '', 'propNm': '',
            'Debit': total_d, 'Credit': total_c, 'Balance': round(total_d - total_c, 2),
        })

        check = {
            'asset':         asset_bal,
            'liability':     liab_bal,
            'equity':        equity_bal,
            'equation_diff': diff,
            'balanced':      abs(diff) < 0.01,
        }
        return result, check

    def _aggregate_bs_fallback(self,
                               gl_records: List[Dict[str, Any]],
                               view_by: str
                               ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        '''Pandas-free aggregator — mirrors uillc.llcReportEngine._buildBS_fallback.'''
        # Derive acctType if missing.
        try:
            from ledger.ledgerGeneral import ledgerGeneral
            gl = ledgerGeneral(self.llc)
            classify = lambda v: gl.coa._Type(v)
        except Exception:
            classify = lambda v: ''

        def _acct_minor(acct):
            parts = str(acct or '').split('.')
            return '.'.join(parts[2:]) if len(parts) > 2 else ''

        buckets: Dict[tuple, Dict[str, float]] = {}
        for r in gl_records:
            at = r.get('acctType') or classify(r.get('acct', ''))
            if at not in BS_TYPES:
                continue
            if view_by and view_by != 'All' and at != view_by[2:]:
                continue
            acct     = r.get('acct', '')
            acct_sub = str(r.get('acctSub') or '')
            prop_nm  = str(r.get('propNm') or '')
            try:    amt = float(r.get('amt', 0) or 0)
            except: amt = 0.0
            atype = str(r.get('aType', 'Debit')).strip()
            key = (at, acct, acct_sub, prop_nm)
            if key not in buckets:
                buckets[key] = {'Debit': 0.0, 'Credit': 0.0}
            is_credit = atype in ('Credit', 'Cr', 'CR', 'C')
            buckets[key]['Credit' if is_credit else 'Debit'] += amt

        order = {t: i for i, t in enumerate(BS_ORDER)}
        result: List[Dict[str, Any]] = []
        for (at, acct, acct_sub, prop_nm), s in sorted(buckets.items(),
                                              key=lambda x: (order.get(x[0][0], 99), x[0][1], x[0][3], x[0][2])):
            d = round(s['Debit'], 2)
            c = round(s['Credit'], 2)
            result.append({'acctType': at, 'acct': acct, 'acctMinor': _acct_minor(acct),
                           'acctSub': acct_sub, 'propNm': prop_nm,
                           'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        asset_bal  = round(sum(r['Balance'] for r in result if r['acctType'] == 'Asset'),  2)
        liab_bal   = round(sum(r['Balance'] for r in result if r['acctType'] == 'Liability'), 2)
        equity_bal = round(sum(r['Balance'] for r in result if r['acctType'] == 'Equity'), 2)
        diff       = round(asset_bal + liab_bal + equity_bal, 2)

        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({'acctType': 'TOTAL', 'acct': '', 'acctMinor': '', 'acctSub': '', 'propNm': '',
                       'Debit': total_d, 'Credit': total_c,
                       'Balance': round(total_d - total_c, 2)})

        check = {
            'asset':         asset_bal,
            'liability':     liab_bal,
            'equity':        equity_bal,
            'equation_diff': diff,
            'balanced':      abs(diff) < 0.01,
        }
        return result, check

    # ── UI conveniences (read-only) ──────────────────────────────────────────

    def last_check(self) -> Dict[str, Any]:
        '''Accounting-equation check captured at construction time.'''
        return dict(self._check) if getattr(self, '_check', None) else {}

    def stats(self) -> Dict[str, Any]:
        rows = self.load()
        acct_counts: Dict[str, int] = {}
        total_row: Dict[str, Any] = {}
        for row in rows:
            at = row.get('acctType', '')
            if at == 'TOTAL':
                total_row = row
                continue
            acct_counts[at] = acct_counts.get(at, 0) + 1
        result: Dict[str, Any] = {
            'Accounts':    sum(acct_counts.values()),
            'TotalDebit':  total_row.get('Debit',   0),
            'TotalCredit': total_row.get('Credit',  0),
            'NetBalance':  total_row.get('Balance', 0),
            'ByAcctType':  acct_counts,
        }
        chk = self.last_check()
        if chk.get('balanced') is False:
            result['⚠ Equation'] = f"diff={chk.get('equation_diff', '?')}"
        return result

    # ── Tax aggregates (cash, ar, buildings, accum_depr, …) ─────────────────
    def taxAggregates(self) -> Dict[str, float]:
        '''
        Return the BS aggregates dict in stmtFinancialReport.taxData()
        ``bs_data`` format: cash, ar, buildings, accum_depr, land,
        other_assets, total_assets, payables, mortgage, other_liab,
        total_equity, total_liab_capital.

        Cached on the instance on first call; stmtDB immutability is
        bypassed via ``object.__setattr__`` because this is derived data
        (not part of the canonical row set).
        '''
        cache = getattr(self, '_taxAggregates_cache', None)
        if cache is not None:
            return dict(cache)
        agg: Dict[str, float] = {}
        try:
            import json as _json
            try:
                from ledger.stmtFinancialReport import stmtFinancialReport
            except ImportError:
                from stmtFinancialReport import stmtFinancialReport
            td = _json.loads(stmtFinancialReport(self.llc).taxData())
            agg = dict(td.get('bs_data', {}) or {})
        except Exception as exc:
            print(f"stmtBalanceSheet.taxAggregates: {exc}")
            agg = {}
        try:
            object.__setattr__(self, '_taxAggregates_cache', agg)
        except Exception:
            pass
        return dict(agg)

    # ── _to_IRS : IRS2LLC provisioning declaration ──────────────────────────
    # CPA knowledge: which IRS fields the Balance Sheet provisions
    # (keyed by IRS form oID → logicalKey → (rowNm, colNm) on this stmt).
    # All BS-side IRS cells are named aggregates (total_assets, cash, …)
    # resolved through taxAggregates(); rowNm carries the aggregate name
    # and colNm is always "amount" for consistency with IS bindings.
    _IRS_BINDINGS: Dict[str, Dict[str, tuple]] = {
        "Form1065": {
            # Page 1 — Entity block
            "P1_F":    ("total_assets",       "amount"),
            # Schedule L — Balance Sheets per Books, end-of-year column
            "L_1_2":   ("cash",               "amount"),
            "L_2a_2":  ("ar",                 "amount"),
            "L_9a_2":  ("buildings",          "amount"),
            "L_9b_2":  ("accum_depr",         "amount"),
            "L_11_2":  ("land",               "amount"),
            "L_13_2":  ("other_assets",       "amount"),
            "L_14_2":  ("total_assets",       "amount"),
            "L_15_2":  ("payables",           "amount"),
            "L_19a_2": ("mortgage",           "amount"),
            "L_20_2":  ("other_liab",         "amount"),
            "L_21_2":  ("total_equity",       "amount"),
            "L_22_2":  ("total_liab_capital", "amount"),
        },
        "Form4562": {
            # Part III — Line 19a residential rental property
            "F4562_19a_cost":  ("buildings",   "amount"),
            "F4562_19a_accum": ("accum_depr",  "amount"),
        },
    }

    def _to_IRS(self, formObj) -> List[Dict[str, Any]]:
        '''
        Return the per-fid IRS bindings this Balance Sheet provisions
        for ``formObj``.  Invoked by ``irs.mapIRS2LLC._mapIRS2LLC()``.
        '''
        try:
            from irs.mapIRS2LLC import _lk_to_fid
        except ImportError:
            from mapIRS2LLC import _lk_to_fid

        formNm   = getattr(formObj, 'oID', '')
        bindings = self._IRS_BINDINGS.get(formNm, {})
        if not bindings:
            return []
        lk2fid = _lk_to_fid(formObj)
        agg    = self.taxAggregates()

        out: List[Dict[str, Any]] = []
        for lk, (rowNm, colNm) in bindings.items():
            fid = lk2fid.get(lk)
            if not fid:
                continue
            value = agg.get(rowNm)
            out.append({
                'fid':   fid,
                'tbl':   self._tblID,
                'row':   rowNm,
                'col':   colNm,
                'value': value,
            })
        return out
