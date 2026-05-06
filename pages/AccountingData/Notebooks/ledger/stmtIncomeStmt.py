'''
ledger.stmtIncomeStmt — Constructed, immutable Income Statement statement.

Per DataModelGuide § 2:  constructed data object, immutable once instantiated,
every row has a line number, every column has a columnID, and every cell is
addressable by (stmtObj / tblID / rowNm / colNm).

Inheritance:    stmtDB → ledger.ledgerDB → ledger.ledgerObject

SINGLE SOURCE OF TRUTH — the General Ledger.
The IS no longer loads llcExpRev (or llcAssets/Payables/Receivables) directly.
Instead it constructs an ``ledger.stmtGeneralLedger`` (with
``include_coa_seed=True`` so every Income/Expense COA account shows as a
line even with no real postings) and aggregates its rows.  Callers may still
pass pre-built ``gl_records=...`` for test / notebook paths.

Construction inputs (exactly one path is taken, in this preference order):
  1. gl_records=...                 — pre-built GL record list (fastest,
                                      used by the ui/ layer so working-
                                      file data is honoured).
  2. (default) Build an stmtGeneralLedger(include_coa_seed=True).

After construction the instance is FROZEN; any attribute write raises
StmtImmutableError.

Columns (beside the _lineNo/_rowNm sentinels added by stmtDB):
    acctType, acct, acctSub, Debit, Credit, Balance

The final row is the TOTAL / Net-Income row:
    acct = "Net Income: {amount:,.2f}",  Balance = net_income

PerMember support lives in build_per_member() — it returns (rows, owner_names,
summary) exactly like llcReportEngine.buildISPerMember() did, but is a separate
method because its row schema (adds owner-name columns and row_type) differs
from the canonical IS tabular schema.

Timestamp of last change: 2026.04.19
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

from ledger.stmtDB import stmtDB
from irs.publishMap import PubEntry, F_TEXT


# Account-type groupings — match uillc.llcReportEngine for bit-identical output.
IS_TYPES  = {'Income', 'Expense'}
IS_ORDER  = ['Income', 'Expense']


class stmtIncomeStmt(stmtDB):
    '''
    Immutable Income Statement constructed at instantiation time.

    VIEW_BY_OPTIONS is exposed so ui modules can reuse the same list of
    view-by filters they presented under the uillc layer.
    '''

    DEFAULT_TBLID = "IncomeStmt"
    COLUMNS = ['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'Debit', 'Credit', 'Balance']
    VIEW_BY_OPTIONS = ['All', 'ByIncome', 'ByExpense', 'ByProperty', 'ByPropertyDetails', 'PerMember']

    # ── Form 1065 publish map (DataModelGuide § 4 / Phase 5) ─────────────────
    #
    # Bindings below are SIMPLE 1:1 cell → logicalKey mappings.
    # The TOTAL row's Balance column is set to ``net_income`` during
    # aggregation (see ``_aggregate_is_pandas``); it is already signed
    # positive (income − expense), so ``sign=+1`` is correct.
    #
    # Aggregate paths that sum many account rows (e.g. ``rent_income``
    # = Σ rows where ``acct == 'Acct.Rev.Rent.*'``) are NOT bound here
    # because their row set is data-dependent. irs.Form1065.nSpaceMap()
    # falls back to the legacy ``_FILL_MAP`` + ``rptFinancialReport``
    # aggregator for those keys during the transition.  Migration path:
    # expose ``tax_aggregates()`` on this class and extend PubEntry to
    # reference a named aggregate; see CHANGELOG Phase 5 notes.
    PUBLISH_MAP = {
        "Form1065": [
            PubEntry(src_row="TOTAL", src_col="Balance",
                     logicalKey="P1_23", fType=F_TEXT, sign=+1,
                     note="Pg1 L23 — Ordinary business income (loss)"),
            PubEntry(src_row="TOTAL", src_col="Balance",
                     logicalKey="K_1",  fType=F_TEXT, sign=+1,
                     note="Sched K L1 — Ordinary business income"),
            PubEntry(src_row="TOTAL", src_col="Balance",
                     logicalKey="M1_1", fType=F_TEXT, sign=+1,
                     note="Sched M-1 L1 — Net income (loss) per books"),
            PubEntry(src_row="TOTAL", src_col="Balance",
                     logicalKey="M1_5", fType=F_TEXT, sign=+1,
                     note="Sched M-1 L5 subtotal (simplified)"),
            PubEntry(src_row="TOTAL", src_col="Balance",
                     logicalKey="M1_9", fType=F_TEXT, sign=+1,
                     note="Sched M-1 L9 — Income per return"),
            PubEntry(src_row="TOTAL", src_col="Balance",
                     logicalKey="M2_3", fType=F_TEXT, sign=+1,
                     note="Sched M-2 L3 — Net income per books"),
        ],
    }

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(self,
                 llc,
                 view_by: str = 'All',
                 gl_records: Optional[List[Dict[str, Any]]] = None,
                 owners: Optional[List[Dict[str, Any]]] = None,
                 **kwargs):
        # Stash construction inputs so _build() can use them.
        # (Normal attribute writes — class is not yet frozen.)
        self._init_view_by: str = view_by
        self._init_gl_records = gl_records
        self._init_owners = owners

        # stmtDB.__init__ runs _build() then freezes the instance.
        super().__init__(llc, **kwargs)

    # ── Main build pipeline ──────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        gl_records = self._init_gl_records

        if gl_records is None:
            # Default path: source from stmtGeneralLedger (COA-seeded) so
            # every Income/Expense account appears as an IS line even before
            # any real postings.
            gl_records = self._load_from_general_ledger()

        # Stash the normalised GL so build_per_member() can use it without
        # reloading.  Normal attribute write — not yet frozen.
        self._gl_records = gl_records

        rows, summary = self._aggregate_is(gl_records, self._init_view_by)

        # Populate stmtDB slots.
        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "view_by":  self._init_view_by,
            "summary":  summary,
            "sourceMode": (
                "gl_records"  if self._init_gl_records is not None
                else "generalLedger"
            ),
            "note":     "Read-only. Sourced from stmtGeneralLedger (COA-seeded). Income / Expense groups. Balance = Net Income.",
        }
        # Keep a convenience handle; stmtDB will freeze us shortly.
        self._summary = summary

    # ── Source loading (default path: pull from General Ledger) ──────────────

    def _load_from_general_ledger(self) -> List[Dict[str, Any]]:
        '''
        Default: build an ``stmtGeneralLedger`` with COA seeds included so
        every Income / Expense COA account appears as an IS line and return
        its row list.  The GL itself handles loading + double-entry expansion
        + merging of llcAssets / llcExpRev / llcPayables / llcReceivables.
        '''
        try:
            from ledger.stmtGeneralLedger import stmtGeneralLedger
        except ImportError:
            from stmtGeneralLedger import stmtGeneralLedger
        gl = stmtGeneralLedger(self.llc, view_by='All', include_coa_seed=True)
        return list(gl._rows or [])

    # ── IS aggregation ───────────────────────────────────────────────────────

    def _aggregate_is(self,
                      gl_records: List[Dict[str, Any]],
                      view_by: str
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        '''
        Aggregate GL records into Income Statement rows.
        Mirrors uillc.llcReportEngine._buildIS_pandas for bit-identical output,
        and falls back to a pure-python path if pandas is unavailable.
        '''
        if _PANDAS_OK:
            return self._aggregate_is_pandas(gl_records, view_by)
        return self._aggregate_is_fallback(gl_records, view_by)

    def _aggregate_is_pandas(self,
                             gl_records: List[Dict[str, Any]],
                             view_by: str
                             ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not gl_records:
            return [], {'net_income': 0, 'income': 0, 'expense': 0}

        df = pd.DataFrame(gl_records)
        if df.empty:
            return [], {'net_income': 0, 'income': 0, 'expense': 0}

        if 'acctType' not in df.columns:
            try:
                from ledger.ledgerGeneral import ledgerGeneral
                gl = ledgerGeneral(self.llc)
                df['acctType'] = df.get('acct').apply(lambda v: gl.coa._Type(v))
            except Exception:
                df['acctType'] = ''
        df['amt'] = pd.to_numeric(df.get('amt'), errors='coerce').fillna(0.0)

        idf = df[df['acctType'].isin(IS_TYPES)].copy()

        if view_by in ('ByIncome', 'ByExpense'):
            idf = idf[idf['acctType'] == view_by[2:]]

        if idf.empty:
            return [], {'net_income': 0, 'income': 0, 'expense': 0}

        for col in ('acctSub', 'propNm', 'acctMinor'):
            if col in idf.columns:
                idf[col] = idf[col].fillna('').astype(str)
            else:
                idf[col] = ''

        # ByProperty: collapse to acct + propNm only (no minor/sub breakdown)
        if view_by == 'ByProperty':
            gb_keys = ['acctType', 'acct', 'propNm', 'aType']
        else:
            # All, ByIncome, ByExpense, ByPropertyDetails: full detail
            gb_keys = ['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'aType']

        grp = (
            idf.groupby(gb_keys)['amt']
               .sum().unstack(fill_value=0.0).reset_index()
        )
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        if view_by == 'ByProperty':
            grp['acctMinor'] = ''
            grp['acctSub']   = ''

        order = {t: i for i, t in enumerate(IS_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        sort_cols = ['_sort', 'acct', 'propNm'] if view_by == 'ByProperty' \
                    else ['_sort', 'acct', 'acctMinor', 'propNm', 'acctSub']
        grp = grp.sort_values(sort_cols).drop(columns=['_sort'])

        result = grp[['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        income_net  = round(sum(-(r['Balance']) for r in result if r['acctType'] == 'Income'),  2)
        expense_net = round(sum(  r['Balance']  for r in result if r['acctType'] == 'Expense'), 2)
        net_income  = round(income_net - expense_net, 2)

        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({
            'acctType': 'TOTAL',
            'acct':     f'Net Income: {net_income:,.2f}',
            'acctMinor': '', 'acctSub': '', 'propNm': '',
            'Debit': total_d, 'Credit': total_c, 'Balance': net_income,
        })

        summary = {
            'income':     income_net,
            'expense':    expense_net,
            'net_income': net_income,
        }
        return result, summary

    def _aggregate_is_fallback(self,
                               gl_records: List[Dict[str, Any]],
                               view_by: str
                               ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        '''Pandas-free aggregator — mirrors uillc.llcReportEngine._buildIS_fallback.'''
        try:
            from ledger.ledgerGeneral import ledgerGeneral
            gl = ledgerGeneral(self.llc)
            classify = lambda v: gl.coa._Type(v)
        except Exception:
            classify = lambda v: ''

        buckets: Dict[tuple, Dict[str, float]] = {}
        for r in gl_records:
            at = r.get('acctType') or classify(r.get('acct', ''))
            if at not in IS_TYPES:
                continue
            if view_by in ('ByIncome', 'ByExpense') and at != view_by[2:]:
                continue
            acct      = r.get('acct', '')
            acct_minor = str(r.get('acctMinor') or '')
            acct_sub  = str(r.get('acctSub') or '')
            prop_nm   = str(r.get('propNm') or '')
            try:    amt = float(r.get('amt', 0) or 0)
            except: amt = 0.0
            atype = str(r.get('aType', 'Debit')).strip()

            if view_by == 'ByProperty':
                key = (at, acct, '', '', prop_nm)
            else:
                key = (at, acct, acct_minor, acct_sub, prop_nm)

            if key not in buckets:
                buckets[key] = {'Debit': 0.0, 'Credit': 0.0}
            is_credit = atype in ('Credit', 'Cr', 'CR', 'C')
            buckets[key]['Credit' if is_credit else 'Debit'] += amt

        order = {t: i for i, t in enumerate(IS_ORDER)}
        result: List[Dict[str, Any]] = []
        for (at, acct, acct_minor, acct_sub, prop_nm), s in sorted(
                buckets.items(),
                key=lambda x: (order.get(x[0][0], 99), x[0][1], x[0][2], x[0][4], x[0][3])):
            d = round(s['Debit'], 2)
            c = round(s['Credit'], 2)
            result.append({'acctType': at, 'acct': acct, 'acctMinor': acct_minor,
                           'acctSub': acct_sub, 'propNm': prop_nm,
                           'Debit': d, 'Credit': c, 'Balance': round(d - c, 2)})

        income_net  = round(sum(-(r['Balance']) for r in result if r['acctType'] == 'Income'), 2)
        expense_net = round(sum(  r['Balance']  for r in result if r['acctType'] == 'Expense'), 2)
        net_income  = round(income_net - expense_net, 2)
        total_d = round(sum(r['Debit']  for r in result), 2)
        total_c = round(sum(r['Credit'] for r in result), 2)
        result.append({'acctType': 'TOTAL', 'acct': f'Net Income: {net_income:,.2f}',
                       'acctMinor': '', 'acctSub': '', 'propNm': '',
                       'Debit': total_d, 'Credit': total_c, 'Balance': net_income})

        summary = {
            'income':     income_net,
            'expense':    expense_net,
            'net_income': net_income,
        }
        return result, summary

    # ── PerMember builder (separate schema; callable after construction) ─────

    def build_per_member(self,
                         owners: Optional[List[Dict[str, Any]]] = None
                         ) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
        '''
        Income Statement with per-owner allocation columns.

        Mirrors uillc.llcReportEngine.buildISPerMember() for bit-identical output.
        Returns (rows, owner_names, summary).

        owners parameter (optional):
          If provided, overrides the owner list passed at construction.
          Expected format: list of dicts with keys {oID, nm, pct, ...}.
        '''
        DEPR_ACCT = 'Acct.Exp.Depreciation'

        # View_by='All' IS over the full GL — ignore self._init_view_by here.
        is_rows, _ = self._aggregate_is(self._gl_records, 'All')

        if owners is None:
            owners = self._init_owners
        if owners is None:
            owners = []

        def _first_name(o: Dict[str, Any]) -> str:
            nm = o.get('nm', '')
            if isinstance(nm, list):
                return nm[0] if nm else o.get('oID', '')
            return str(nm) if nm else o.get('oID', '')

        owner_names = [_first_name(o) for o in owners]

        # ── bucket rows by section ────────────────────────────────────────────
        income_rows:  List[tuple] = []   # (row_dict, eff_bal)
        expense_rows: List[tuple] = []
        deprec_val    = 0.0              # positive depreciation amount

        for row in is_rows:
            if row.get('acctType') == 'TOTAL':
                continue
            debit  = float(row.get('Debit',  0) or 0)
            credit = float(row.get('Credit', 0) or 0)
            eff_bal = round(credit - debit, 2)

            if row.get('acct') == DEPR_ACCT:
                deprec_val += round(debit - credit, 2)
            elif row.get('acctType') == 'Income':
                income_rows.append((row, eff_bal))
            else:
                expense_rows.append((row, eff_bal))

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

        expense_total = round(sum(eb for _, eb in expense_rows), 2)
        result.append(_make_row(
            '', 'SubTotal Expense (excl. Depreciation)', '', expense_total, 'expense-subtotal'))

        # ── Net Income (before depreciation) ─────────────────────────────────
        ni_before = round(income_total + expense_total, 2)
        result.append(_make_row('', 'Net Income (before Depreciation)', '', ni_before, 'net-income'))

        # ── Depreciation line (after Net Income) ─────────────────────────────
        depr_eff = round(-deprec_val, 2)
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
            'expense_subtotal':     expense_total,
            'net_income':           ni_before,
            'depreciation':         round(deprec_val, 2),
            'net_income_with_depr': ni_with_depr,
        }
        return result, owner_names, summary

    # ── UI conveniences (read-only) ──────────────────────────────────────────

    def last_summary(self) -> Dict[str, Any]:
        '''IS net-income summary captured at construction time.'''
        return dict(self._summary) if getattr(self, '_summary', None) else {}

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

    # ── Tax aggregates (rent_income, depreciation, …) ───────────────────────
    def taxAggregates(self) -> Dict[str, float]:
        '''
        Return the IS aggregates dict in rptFinancialReport.taxData()
        ``is_data`` format: rent_income, total_income, salaries, repairs,
        taxes_licenses, interest_expense, depreciation, other_deductions,
        total_expenses, net_income, interest_income, distributions_cash, …

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
                from ledger.rptFinancialReport import stmtFinancialReport
            except ImportError:
                from rptFinancialReport import stmtFinancialReport
            td = _json.loads(rptFinancialReport(self.llc).taxData())
            agg = dict(td.get('is_data', {}) or {})
        except Exception as exc:
            print(f"stmtIncomeStmt.taxAggregates: {exc}")
            agg = {}
        try:
            object.__setattr__(self, '_taxAggregates_cache', agg)
        except Exception:
            pass
        return dict(agg)

    # ── _to_IRS : IRS2LLC provisioning declaration ──────────────────────────
    # CPA knowledge: which IRS fields the Income Statement provisions
    # (keyed by IRS form oID → logicalKey → (rowNm, colNm) on this stmt).
    # rowNm == "TOTAL" + colNm == "Balance" binds directly to the TOTAL
    # row's Balance cell (net_income, already signed positive).  All other
    # rows/cols refer to named tax aggregates resolved via taxAggregates().
    _IRS_BINDINGS: Dict[str, Dict[str, tuple]] = {
        "Form1065": {
            # Page 1 — Income
            "P1_1a":  ("rent_income",      "amount"),
            "P1_1c":  ("rent_income",      "amount"),
            "P1_3":   ("rent_income",      "amount"),
            "P1_8":   ("total_income",     "amount"),
            # Page 1 — Deductions
            "P1_9":   ("salaries",         "amount"),
            "P1_11":  ("repairs",          "amount"),
            "P1_14":  ("taxes_licenses",   "amount"),
            "P1_15":  ("interest_expense", "amount"),
            "P1_16a": ("depreciation",     "amount"),
            "P1_16c": ("depreciation",     "amount"),
            "P1_21":  ("other_deductions", "amount"),
            "P1_22":  ("total_expenses",   "amount"),
            # Page 1 — Ordinary business income (loss)
            "P1_23":  ("TOTAL",            "Balance"),
            # Schedule K (page 4/5)
            "K_1":    ("TOTAL",            "Balance"),
            "K_2":    ("rent_income",      "amount"),
            "K_5":    ("interest_income",  "amount"),
            "K_19a":  ("distributions_cash", "amount"),
            # Schedule M-1 / M-2 (page 5)
            "M1_1":   ("TOTAL",            "Balance"),
            "M1_5":   ("TOTAL",            "Balance"),
            "M1_9":   ("TOTAL",            "Balance"),
            "M2_3":   ("TOTAL",            "Balance"),
            "M2_6a":  ("distributions_cash", "amount"),
        },
        "Sch_K1": {
            # K-1 box totals — per-partner allocation is applied by the
            # consumer (FILL writer); we publish the partnership total.
            "K1_1":    ("TOTAL",             "Balance"),
            "K1_2":    ("rent_income",       "amount"),
            "K1_5":    ("interest_income",   "amount"),
            "K1_14a":  ("TOTAL",             "Balance"),
            "K1_19a":  ("distributions_cash","amount"),
            "K1_L3":   ("TOTAL",             "Balance"),
        },
        "Form4562": {
            "F4562_19a_depr": ("depreciation", "amount"),
            "F4562_22":       ("depreciation", "amount"),
            "F4562_42":       ("depreciation", "amount"),
        },
    }

    def _to_IRS(self, formObj) -> List[Dict[str, Any]]:
        '''
        Return the per-fid IRS bindings this Income Statement provisions
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
            # TOTAL.Balance is a canonical stmt cell; aggregates go
            # through taxAggregates().
            if rowNm == 'TOTAL' and colNm == 'Balance':
                value = self.get('TOTAL', 'Balance')
            else:
                value = agg.get(rowNm)
            out.append({
                'fid':   fid,
                'tbl':   self._tblID,
                'row':   rowNm,
                'col':   colNm,
                'value': value,
            })
        return out
