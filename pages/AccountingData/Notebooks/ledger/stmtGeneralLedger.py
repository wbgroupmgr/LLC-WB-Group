'''
ledger.stmtGeneralLedger — Constructed, immutable General Ledger snapshot.

Per DataModelGuide § 2:  constructed data object, immutable once instantiated,
every row carries a _lineNo and _rowNm, every column has a columnID, and every
cell is addressable by (stmtObj / tblID / rowNm / colNm).

Inheritance:    stmtDB → ledger.ledgerDB

This is the "constructed GL table" statement.  It owns BOTH halves of the
General Ledger pipeline:

  ``ledgerGeneral``      — stateless GL-building service (toDoubleEntry,
                           mergeGL, classifyAccts, glBalSheet, etc.)
                           Also lives here (v0.2 merge) so there is a single
                           source of truth for GL transformations.
  ``stmtGeneralLedger``  — the constructed, immutable snapshot that consumes
                           ledgerGeneral's output and exposes an addressable
                           (stmtObj / tblID / rowNm / colNm) table.

The legacy module path ``ledger.ledgerGeneral`` survives as a thin
backwards-compat shim that re-exports ``ledgerGeneral`` from this file.

Construction inputs (exactly one path is taken, in preference order):
  1. gl_records=..., resolve_dups=False
     — a pre-expanded + pre-merged GL list (fastest; used by the ui/ wrapper
       so working-file edits are honoured).  Cross-source duplicates are
       expected to already carry a 'Status' field (⚠ Dup / '').
  2. sources=dict(asset=..., expRev=..., payable=..., receivable=...)
     — the engine expands each with toDoubleEntry and merges with mergeGL.
  3. (default) Load from ledger DB
     — llcAssets / llcExpRev / llcPayables / llcReceivables JSON files.

After construction the instance is FROZEN; any attribute write raises
StmtImmutableError.

Columns (all preserved from the GL record, plus the stmtDB _lineNo/_rowNm
sentinels):
    Status, dt, acctType, acct, aType, amt, desc, acctSub, refDB, tID
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ledger.stmtDB import stmtDB


class stmtGeneralLedger(stmtDB):
    '''
    Immutable constructed General Ledger snapshot.

    View-by filtering is applied at construction time — subclasses that want
    a different filter build a fresh instance with a different view_by.
    '''

    DEFAULT_TBLID = "GeneralLedger"
    COLUMNS = ['Status', 'dt', 'acctType', 'acct', 'acctMinor', 'propNm', 'aType', 'amt',
               'desc', 'acctSub', 'refDB', 'tID']
    VIEW_BY_OPTIONS = ['All', 'By Dups', 'By COA Seed',
                       'ByAsset', 'ByLiability', 'ByEquity',
                       'ByIncome', 'ByExpense']

    #: Every GL is seeded with one zero-amount Debit per COA account so
    #: downstream aggregators (BS, IS) always show every account line even
    #: before any real transactions are posted.  These rows carry
    #: refDB='COA' and are hidden from GL views by default.
    COA_SEED_REFDB = 'COA'

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(self,
                 llc,
                 view_by: str = 'All',
                 gl_records:   Optional[List[Dict[str, Any]]] = None,
                 sources:      Optional[Dict[str, List[Dict[str, Any]]]] = None,
                 resolve_dups: bool = False,
                 include_coa_seed: bool = False,
                 **kwargs):
        self._init_view_by         = view_by
        self._init_gl_records      = gl_records
        self._init_sources         = sources
        self._init_resolve_dups    = resolve_dups
        self._init_include_coa_seed = bool(include_coa_seed)

        super().__init__(llc, **kwargs)

    # ── Main build pipeline ──────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        gl_records = self._init_gl_records
        sources    = self._init_sources

        if gl_records is None:
            if sources is None:
                sources = self._load_default_sources()
            gl_records = self._expand_and_merge(sources, self._init_resolve_dups)

        # Seed the GL with one zero-amount Debit per COA account so that
        # every account participates in BS / IS aggregation even before
        # any real transactions have been posted.  Seed rows are tagged
        # refDB='COA' and are stripped by the default view filter.
        seed_records = self._coa_seed_records()
        gl_records = list(seed_records) + list(gl_records or [])

        # Apply view_by filtering at construction time.
        filtered = self._apply_view_by(
            gl_records or [],
            self._init_view_by,
            include_coa_seed=self._init_include_coa_seed,
        )

        # Normalise row keys so every row exposes the full column list.
        rows: List[Dict[str, Any]] = []
        for r in filtered:
            acct = r.get('acct', '') or ''
            parts = acct.split('.')
            acct_minor = '.'.join(parts[2:]) if len(parts) > 2 else ''
            prop_nm = r.get('propNm', '')
            if prop_nm is None or (isinstance(prop_nm, float) and prop_nm != prop_nm):
                prop_nm = ''
            rows.append({
                'Status':    r.get('Status',   '') or '',
                'dt':        r.get('dt',       '') or '',
                'acctType':  r.get('acctType', '') or '',
                'acct':      acct,
                'acctMinor': acct_minor,
                'propNm':    str(prop_nm),
                'aType':     r.get('aType',    '') or '',
                'amt':       r.get('amt',      0) or 0,
                'desc':      r.get('desc',     '') or '',
                'acctSub':   r.get('acctSub',  '') or '',
                'refDB':     r.get('refDB',    '') or '',
                'tID':       r.get('tID',      '') or '',
            })

        summary = self._summarise(rows)

        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "view_by":         self._init_view_by,
            "resolve_dups":    bool(self._init_resolve_dups),
            "include_coa_seed": bool(self._init_include_coa_seed),
            "sourceMode": (
                "gl_records" if self._init_gl_records is not None
                else "sources" if self._init_sources is not None
                else "ledgerDB"
            ),
            "transactions":    summary.get('transactions', 0),
            "duplicates":      summary.get('duplicates',   0),
            "coa_seed_count":  len(seed_records),
            "note": (
                "Read-only. Double-entry expanded GL built by merging "
                "llcAssets + llcExpRev + llcPayables + llcReceivables, "
                "prepended with one zero-amount Debit per COA account "
                "(refDB='COA') so every account participates in BS/IS "
                "aggregation.  Cross-source dups flagged ⚠ Dup."
            ),
        }
        self._summary = summary

    # ── Source loading (default path: read ledger DB files) ──────────────────

    def _load_default_sources(self) -> Dict[str, List[Dict[str, Any]]]:
        def _safe_load(cls_path: str) -> List[Dict[str, Any]]:
            try:
                module_name, cls_name = cls_path.rsplit('.', 1)
                mod = __import__(module_name, fromlist=[cls_name])
                cls = getattr(mod, cls_name)
                obj = cls(self.llc)
                data = obj.load()
                return data if isinstance(data, list) else []
            except Exception as err:
                print(f"stmtGeneralLedger: could not load {cls_path}: {err}")
                return []

        return {
            'asset':      _safe_load('ledger.llcAssets.llcAssets'),
            'expRev':     _safe_load('ledger.llcExpRev.llcExpRev'),
            'payable':    _safe_load('ledger.llcPayables.llcPayables'),
            'receivable': _safe_load('ledger.llcReceivables.llcReceivables'),
        }

    def _expand_and_merge(self,
                          sources:      Dict[str, List[Dict[str, Any]]],
                          resolve_dups: bool
                          ) -> List[Dict[str, Any]]:
        '''Double-entry-expand + mergeGL — delegates to the ledgerGeneral service
        defined at the bottom of this module (v0.2 merge).'''
        gl = ledgerGeneral(self.llc)

        asset_list = sources.get('asset',      []) or []
        er_list    = sources.get('expRev',     []) or []
        ap_list    = sources.get('payable',    []) or []
        ar_list    = sources.get('receivable', []) or []

        return gl.mergeGL(
            [
                gl.toDoubleEntry(asset_list),
                gl.toDoubleEntry(er_list),
                gl.toDoubleEntry(ap_list),
                gl.toDoubleEntry(ar_list),
            ],
            resolve_dups=resolve_dups,
        )

    # ── COA seed rows ────────────────────────────────────────────────────────

    def _coa_seed_records(self) -> List[Dict[str, Any]]:
        '''
        Return one dummy Debit-0 transaction per COA account.

        Each record looks like::

            {'Status':'', 'dt':'<yr>-01-01', 'acctType':<coa._Type>,
             'acct':<coaKey>, 'aType':'Debit', 'amt':0,
             'desc':"Initial Balance for the Account; <acctDesc>",
             'acctSub':'', 'refDB':'COA', 'tID':'COA_<coaKey>'}

        These rows are always prepended to the GL so every COA account
        participates in downstream aggregation even with no real postings.
        They are stripped from the default GL view but preserved when
        BS/IS build from the GL (include_coa_seed=True).
        '''
        try:
            coa = getattr(self.llc, 'coa', None)
            if coa is None:
                from ledger.llcCOA import ChartOfAccounts
                coa = ChartOfAccounts(self.llc)
            coa_dict = coa.load() or {}
        except Exception as err:
            if getattr(self, 'debug', False):
                print(f"stmtGeneralLedger._coa_seed_records: {err}")
            return []

        try:
            yr = int(getattr(self.llc, 'yr', None) or 0)
        except (TypeError, ValueError):
            yr = 0
        dt_iso = f"{yr:04d}-01-01" if yr else "0001-01-01"

        seeds: List[Dict[str, Any]] = []
        for acct, meta in coa_dict.items():
            try:
                acctType = coa._Type(acct)
            except Exception:
                acctType = ''
            std_nm = (meta.get('acctDesc', '') if isinstance(meta, dict) else '') or ''
            seeds.append({
                'Status':   '',
                'dt':       dt_iso,
                'acctType': acctType,
                'acct':     acct,
                'aType':    'Debit',
                'amt':      0,
                'desc':     f"Initial Balance for the Account; {std_nm}",
                'acctSub':  '',
                'refDB':    self.COA_SEED_REFDB,
                'tID':      f"COA_{acct}",
            })
        return seeds

    # ── View-by filter (ported from uillc.stmtGeneralLedger) ──────────────────

    @staticmethod
    def _apply_view_by(rows: List[Dict[str, Any]],
                       view_by: str,
                       include_coa_seed: bool = False
                       ) -> List[Dict[str, Any]]:
        # ``By COA Seed`` is the explicit request to see only the seed rows.
        if view_by == 'By COA Seed':
            return [r for r in rows if r.get('refDB') == 'COA']

        # All other views strip the COA seed rows unless the caller opts in.
        work = list(rows) if include_coa_seed else [
            r for r in rows if r.get('refDB') != 'COA'
        ]

        if not view_by or view_by == 'All':
            return work

        if view_by == 'By Dups':
            dups = [r for r in work if r.get('Status') == '⚠ Dup']

            def _sort_key(r):
                try:
                    amt = float(r.get('amt', 0) or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                return (str(r.get('dt', '')), amt, str(r.get('tID', '')))

            dups = sorted(dups, key=_sort_key)

            dup_label: Dict[str, str] = {}
            counter = 0
            for r in dups:
                tid = r.get('tID', '')
                if tid not in dup_label:
                    counter += 1
                    dup_label[tid] = f'Dup{counter}'

            return [
                {**r, 'Status': dup_label.get(r.get('tID', ''), '?')}
                for r in dups
            ]

        acct_type = view_by[2:]
        return [r for r in work if r.get('acctType', '') == acct_type]

    # ── Summary ──────────────────────────────────────────────────────────────

    @staticmethod
    def _summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        acct_counts: Dict[str, int] = {}
        total_debit = total_credit = 0.0
        dup_count = 0
        for row in rows:
            at = row.get('acctType', 'Unknown') or 'Unknown'
            acct_counts[at] = acct_counts.get(at, 0) + 1
            if row.get('Status') == '⚠ Dup':
                dup_count += 1
            try:
                amt = float(row.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if str(row.get('aType', '')).strip().lower() in ('debit', 'dr', 'd'):
                total_debit += amt
            else:
                total_credit += amt

        return {
            'transactions': len(rows),
            'total_debit':  round(total_debit,  2),
            'total_credit': round(total_credit, 2),
            'net_balance':  round(total_debit - total_credit, 2),
            'by_acct_type': acct_counts,
            'duplicates':   int(dup_count),
        }

    # ── Row-name derivation (override) ───────────────────────────────────────

    def _default_rowNm(self, row: Dict[str, Any], i: int) -> str:
        '''
        GL rows are naturally keyed by tID.  Fall back to base derivation
        when tID is missing.
        '''
        tid = str(row.get('tID', '') or '').strip()
        if tid:
            return tid
        return super()._default_rowNm(row, i)

    # ── UI conveniences (read-only) ──────────────────────────────────────────

    def last_summary(self) -> Dict[str, Any]:
        return dict(self._summary) if getattr(self, '_summary', None) else {}

    def stats(self) -> Dict[str, Any]:
        s = self.last_summary() or {}
        result: Dict[str, Any] = {
            'Transactions': s.get('transactions', 0),
            'TotalDebit':   s.get('total_debit',  0.0),
            'TotalCredit':  s.get('total_credit', 0.0),
            'NetBalance':   s.get('net_balance',  0.0),
            'ByAcctType':   s.get('by_acct_type', {}),
        }
        if s.get('duplicates'):
            result['Duplicates'] = int(s['duplicates'])
        return result

    # ── _to_IRS : IRS2LLC provisioning declaration ──────────────────────────
    # The General Ledger is the LOWEST-priority provider in the IRS2LLC
    # hierarchy — it only fills fids that no higher-authority data object
    # (IS, BS, Customers, Owners, LLC profile) has claimed.  For the current
    # rental-LLC form set (Form1065 pages 1-6, Sch_K1, Form4562) the GL has
    # no additional authoritative cells beyond what IS/BS already publish,
    # so this hook intentionally returns [].  Reserved as a future fallback
    # for raw-GL-derived cells (e.g. supporting schedules).
    def _to_IRS(self, formObj):
        '''Return [] — GL is the fallback layer; no extra cells yet.'''
        return []


# ═════════════════════════════════════════════════════════════════════════════
# stmtTrialBalance — Constructed, immutable Trial Balance snapshot
# ─────────────────────────────────────────────────────────────────────────────
# The Trial Balance is the classic bookkeeper's check: for every account,
# Σ Debits and Σ Credits; the grand totals must agree for the books to
# "trial balance".  Unlike the Balance Sheet (which only shows A/L/E) or
# the Income Statement (I/E), the Trial Balance shows EVERY acctType.
#
# Implementation strategy (v0.2.3.1): like stmtBalanceSheet / stmtIncomeStmt,
# we source strictly from the GL — the GL is the single source of truth.
# COA seed rows are included so every COA account appears even when it has
# no real postings.  The last row is a TOTAL line whose (Debit, Credit) must
# match within 0.01 for the book to balance.
# ═════════════════════════════════════════════════════════════════════════════


# Full list of acctTypes we expect from the COA classifier.  Ordered for
# presentation: A, L, E, Income, Expense, then anything else (stability).
_TB_ACCT_ORDER = ['Asset', 'Liability', 'Equity', 'Income', 'Expense']
_TB_ACCT_TYPES = set(_TB_ACCT_ORDER)


class stmtTrialBalance(stmtDB):
    '''
    Immutable Trial Balance constructed at instantiation time.

    Columns (beyond the _lineNo / _rowNm sentinels):
        acctType, acct, acctSub, Debit, Credit, Balance

    Construction:
        gl_records=...  — pre-built GL record list (optional fast path).
        (default)       — build stmtGeneralLedger(include_coa_seed=True)
                          and aggregate its rows.

    The final row is ``acctType='TOTAL'`` and its Debit / Credit should
    agree (``_meta['balanced'] == True`` when |Σ Debit − Σ Credit| < 0.01).
    '''

    DEFAULT_TBLID = "TrialBalance"
    COLUMNS = ['acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance']
    VIEW_BY_OPTIONS = ['All', 'ByAsset', 'ByLiability', 'ByEquity',
                       'ByIncome', 'ByExpense']

    PUBLISH_MAP: Dict[str, List[Any]] = {}

    def __init__(self,
                 llc,
                 view_by: str = 'All',
                 gl_records: Optional[List[Dict[str, Any]]] = None,
                 **kwargs):
        self._init_view_by    = view_by
        self._init_gl_records = gl_records
        super().__init__(llc, **kwargs)

    # ── Build pipeline ───────────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        gl_records = self._init_gl_records
        if gl_records is None:
            gl_records = self._load_gl_records()

        rows, check = self._aggregate_tb(gl_records, self._init_view_by)

        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "view_by":      self._init_view_by,
            "sourceMode": (
                "gl_records" if self._init_gl_records is not None else "stmtGeneralLedger"
            ),
            "balanced":      bool(check.get('balanced', False)),
            "total_debit":   float(check.get('total_debit',  0.0)),
            "total_credit":  float(check.get('total_credit', 0.0)),
            "tb_diff":       float(check.get('tb_diff',      0.0)),
            "note": (
                "Trial Balance built from stmtGeneralLedger "
                "(include_coa_seed=True).  Balanced ↔ Σ Debit = Σ Credit "
                "within $0.01.  Zero-balance rows are retained so every "
                "COA account appears as a line."
            ),
        }

    # ── Source loading ───────────────────────────────────────────────────────

    def _load_gl_records(self) -> List[Dict[str, Any]]:
        gl = stmtGeneralLedger(self.llc, view_by='All', include_coa_seed=True)
        return list(gl._rows or [])

    # ── Aggregation ──────────────────────────────────────────────────────────

    def _aggregate_tb(self,
                      gl_records: List[Dict[str, Any]],
                      view_by: str
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        '''
        Group GL records by (acctType, acct, acctSub, aType) and pivot
        Debit / Credit into columns.  Trailing TOTAL row carries the
        grand-totals for the zero-sum check.
        '''
        if not gl_records:
            return [], {'balanced': True, 'total_debit': 0.0, 'total_credit': 0.0, 'tb_diff': 0.0}

        df = pd.DataFrame(gl_records)
        if df.empty:
            return [], {'balanced': True, 'total_debit': 0.0, 'total_credit': 0.0, 'tb_diff': 0.0}

        # Ensure acctType populated (classify via COA if missing).
        if 'acctType' not in df.columns or df['acctType'].astype(str).str.strip().eq('').any():
            coa = getattr(self.llc, 'coa', None) or _llcCOA(self.llc)
            need_class = df.get('acctType', pd.Series([''] * len(df))).astype(str).str.strip().eq('')
            df['acctType'] = df.get('acctType', '').astype(str)
            df.loc[need_class, 'acctType'] = df.loc[need_class, 'acct'].map(
                lambda a: coa._Type(a) if a else ''
            )

        df['amt'] = pd.to_numeric(df.get('amt'), errors='coerce').fillna(0.0)

        # Drop any rows whose acctType falls outside the classic 5 buckets
        # (e.g. "Appreciation" if classifier returned it) — they'd skew the
        # TB totals.  If future acctTypes need inclusion they can be added
        # to _TB_ACCT_TYPES above.
        tb = df[df['acctType'].isin(_TB_ACCT_TYPES)].copy()

        # View-by filter (ByAsset, ByLiability, ByEquity, ByIncome, ByExpense)
        if view_by and view_by != 'All':
            wanted = view_by[2:]  # strip 'By'
            tb = tb[tb['acctType'] == wanted]

        if tb.empty:
            return [], {'balanced': True, 'total_debit': 0.0, 'total_credit': 0.0, 'tb_diff': 0.0}

        if 'acctSub' in tb.columns:
            tb['acctSub'] = tb['acctSub'].fillna('').astype(str)
        else:
            tb['acctSub'] = ''

        grp = (
            tb.groupby(['acctType', 'acct', 'acctSub', 'aType'])['amt']
              .sum().unstack(fill_value=0.0).reset_index()
        )
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        order = {t: i for i, t in enumerate(_TB_ACCT_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct', 'acctSub']).drop(columns=['_sort'])

        rows = grp[['acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        total_d = round(sum(r['Debit']  for r in rows), 2)
        total_c = round(sum(r['Credit'] for r in rows), 2)
        tb_diff = round(total_d - total_c, 2)

        rows.append({
            'acctType': 'TOTAL',
            'acct':     '',
            'acctSub':  '',
            'Debit':    total_d,
            'Credit':   total_c,
            'Balance':  tb_diff,
        })

        return rows, {
            'balanced':     abs(tb_diff) < 0.01,
            'total_debit':  total_d,
            'total_credit': total_c,
            'tb_diff':      tb_diff,
        }

    # ── Convenience accessors ────────────────────────────────────────────────

    def is_balanced(self) -> bool:
        '''True when Σ Debit == Σ Credit within $0.01.'''
        return bool(self._meta.get('balanced', False))

    def totals(self) -> Dict[str, float]:
        '''Return grand totals: {'Debit': ..., 'Credit': ..., 'Diff': ...}.'''
        return {
            'Debit':  float(self._meta.get('total_debit',  0.0)),
            'Credit': float(self._meta.get('total_credit', 0.0)),
            'Diff':   float(self._meta.get('tb_diff',      0.0)),
        }

    def _to_IRS(self, formObj):
        '''Return [] — TB is a diagnostic snapshot, not an authority layer.'''
        return []


# ═════════════════════════════════════════════════════════════════════════════
# ledgerGeneral — stateless GL-building service
# ─────────────────────────────────────────────────────────────────────────────
# Merged in from ledger/ledgerGeneral.py (v0.2.2.6).  This class provides the
# double-entry / merge / classify helpers consumed by stmtGeneralLedger and
# by tests, ui/*, notebooks.  Kept as a stateless service (not an immutable
# stmt object) so it can be instantiated cheaply for ad-hoc transformations
# without building the full constructed snapshot.
# ═════════════════════════════════════════════════════════════════════════════

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
        # (erCols kept for reference; unused here but preserved from original)
        # erCols = [c for c in erList[0].keys() if c not in ['_unknown', 'acctMinor', 'acctMajor', 'acctType']]

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

    def glIncomeExpense(self, glDF):
        '''Generate Income/Expense DataFrame from GL transactions via groupby.'''
        df = glDF[glDF.acctType.isin(['Income', 'Expense'])]
        grpDF = df.groupby(['acctType', 'acct', 'aType']).amt.sum().unstack().reset_index()
        return self.sumRowCol(grpDF)

    def glBalSheet(self, glDF):
        '''Generate Balance-Sheet DataFrame from GL transactions via groupby.'''
        df = glDF[glDF.acctType.isin(['Asset', 'Equity', 'Liability'])]
        grpDF = df.groupby(['acctType', 'acct', 'aType']).amt.sum().unstack().reset_index()
        return self.sumRowCol(grpDF)
