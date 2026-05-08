'''
ledger.stmtGL — v0.3 General-Ledger stmtOBJ hierarchy.

Per docs/LLC_stmtDesign.md "Design Decision v0.3":
    Five classes per stmtOBJ, no overlay between consumer concerns.

        stmtGL          — core data only (immutable rows from sources + COA seed)
        stmtGL_Tax      — Tax provisioning; reads bookNS_GL.json; nSpaceMap()
                          returns {formNm: [{fid, acct, fval}, ...]}
        stmtGL_Agg      — pipeline base; AggBy() returns a chainable aggregator
        stmtGL_View     — UI-facing; inherits the pipeline
                          (AggBy().ViewBy().GroupBy().SortBy().load())
        stmtGL_Reports  — stub (TBD)

Design rules honoured here:
    - v0.2 stmtGeneralLedger.py is NOT modified; v0.3 lives in this new file.
    - No save(); to_json() returns a JSON string (caller persists if desired).
    - No per-consumer _build() — _build() runs once on the base; each consumer
      shapes its own load() output without re-doing construction.
    - Only stmtOBJ_Tax exposes the IRS-form nSpaceMap semantics; the legacy
      stmtDB cell-index nSpaceMap stays untouched (it is unrelated v0.2 plumbing).
    - Pipeline pattern: ``stmtGL_View(...).AggBy().ViewBy(vb).GroupBy(keys).SortBy(keys).load()``

Inheritance:
    stmtDB → ledgerDB → ledger.ledgerObject

Reuses the v0.2 ``ledgerGeneral`` service (mergeGL / toDoubleEntry / classify)
because that is a stable, stateless transformation layer.  No code change there.

Timestamp: 2026.04.27 — v0.3.GL
'''

from __future__ import annotations

import json as _json
import os as _os
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as _pd

from ledger.stmtDB import stmtDB
from ledger.llcCOA import ChartOfAccounts as _llcCOA

# Stateless GL-building service (canonical in ledger.ledgerGeneral).
from ledger.ledgerGeneral import ledgerGeneral as _ledgerGeneral

# Ordered acctType list for Trial Balance presentation.
_TB_ACCT_ORDER = ['Asset', 'Liability', 'Equity', 'Income', 'Expense']
_TB_ACCT_TYPES = set(_TB_ACCT_ORDER)


# ─────────────────────────────────────────────────────────────────────────────
# 1. stmtGL — core data only
# ─────────────────────────────────────────────────────────────────────────────
class stmtGL(stmtDB):
    '''
    Immutable General Ledger snapshot — no view/agg/tax behaviour.

    Constructs the raw GL row list (double-entry-expanded, COA-seeded, merged
    across source DBs).  Consumers (Tax / View / Reports) wrap or subclass
    this class; they never re-do construction.

    Construction inputs (in preference order):
        1. gl_records=[{...}, ...]              — pre-built GL rows
        2. sources={'asset':[...], ...}         — raw source-DB rows
        3. (default) load llcAssets / llcExpRev / llcPayables / llcReceivables
    '''

    DEFAULT_TBLID = "GeneralLedger"
    COLUMNS = ['Status', 'dt', 'acctType', 'acct', 'aType', 'amt',
               'desc', 'acctSub', 'refDB', 'tID']
    COA_SEED_REFDB = 'COA'

    # PUBLISH_MAP intentionally empty for v0.3 — IRS publication is a
    # Tax-class concern, not core data.
    PUBLISH_MAP: Dict[str, List[Any]] = {}

    def __init__(self,
                 llc,
                 gl_records: Optional[List[Dict[str, Any]]] = None,
                 sources: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                 resolve_dups: bool = False,
                 **kwargs):
        # Stash construction inputs — consumed by _build() before freeze.
        self._init_gl_records   = gl_records
        self._init_sources      = sources
        self._init_resolve_dups = bool(resolve_dups)
        super().__init__(llc, **kwargs)

    # ── stmtDB hook ────────────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        gl_records = self._init_gl_records
        if gl_records is None:
            sources    = self._init_sources or self._load_default_sources()
            gl_records = self._expand_and_merge(sources, self._init_resolve_dups)

        seed = self._coa_seed_records()
        all_records = list(seed) + list(gl_records or [])

        rows = [self._norm_row(r) for r in all_records]

        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "version":         "v0.3",
            "sourceMode":      ("gl_records" if self._init_gl_records is not None
                                else "sources" if self._init_sources is not None
                                else "ledgerDB"),
            "resolve_dups":    bool(self._init_resolve_dups),
            "transactions":    len(rows) - len(seed),
            "coa_seed_count":  len(seed),
            "row_count":       len(rows),
            "note": (
                "v0.3 stmtGL — core unfiltered, unaggregated GL rows. "
                "Use stmtGL_View pipeline (AggBy → ViewBy → GroupBy → "
                "SortBy → load) for slicing.  No save(); use to_json()."
            ),
        }

    @staticmethod
    def _norm_row(r: Dict[str, Any]) -> Dict[str, Any]:
        '''Normalise a GL record so every row has the full column set.'''
        try:
            amt = float(r.get('amt', 0) or 0)
        except (TypeError, ValueError):
            amt = 0.0
        return {
            'Status':   r.get('Status',   '') or '',
            'dt':       r.get('dt',       '') or '',
            'acctType': r.get('acctType', '') or '',
            'acct':     r.get('acct',     '') or '',
            'aType':    r.get('aType',    '') or '',
            'amt':      amt,
            'desc':     r.get('desc',     '') or '',
            'acctSub':  r.get('acctSub',  '') or '',
            'refDB':    r.get('refDB',    '') or '',
            'tID':      r.get('tID',      '') or '',
        }

    # ── Source loading (default path: read ledger DB files) ──────────────

    def _load_default_sources(self) -> Dict[str, List[Dict[str, Any]]]:
        '''Load the four canonical source DBs.  Same paths as v0.2.'''
        def _safe_load(cls_path: str) -> List[Dict[str, Any]]:
            try:
                module_name, cls_name = cls_path.rsplit('.', 1)
                mod = __import__(module_name, fromlist=[cls_name])
                cls = getattr(mod, cls_name)
                obj = cls(self.llc)
                data = obj.load()
                return data if isinstance(data, list) else []
            except Exception as err:
                print(f"stmtGL: could not load {cls_path}: {err}")
                return []
        return {
            'asset':      _safe_load('ledger.llcAssets.llcAssets'),
            'expRev':     _safe_load('ledger.llcExpRev.llcExpRev'),
            'payable':    _safe_load('ledger.llcPayables.llcPayables'),
            'receivable': _safe_load('ledger.llcReceivables.llcReceivables'),
        }

    def _expand_and_merge(self,
                          sources: Dict[str, List[Dict[str, Any]]],
                          resolve_dups: bool
                          ) -> List[Dict[str, Any]]:
        '''Double-entry-expand each source then merge — uses v0.2 ledgerGeneral.'''
        gl = _ledgerGeneral(self.llc)
        return gl.mergeGL(
            [
                gl.toDoubleEntry(sources.get('asset',      []) or []),
                gl.toDoubleEntry(sources.get('expRev',     []) or []),
                gl.toDoubleEntry(sources.get('payable',    []) or []),
                gl.toDoubleEntry(sources.get('receivable', []) or []),
            ],
            resolve_dups=resolve_dups,
        )

    # ── COA seed (one Debit-0 row per COA acct) ──────────────────────────

    def _coa_seed_records(self) -> List[Dict[str, Any]]:
        try:
            coa = getattr(self.llc, 'coa', None)
            if coa is None:
                from ledger.llcCOA import ChartOfAccounts
                coa = ChartOfAccounts(self.llc)
            coa_dict = coa.load() or {}
        except Exception as err:
            if getattr(self, 'debug', False):
                print(f"stmtGL._coa_seed_records: {err}")
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
                'amt':      0.0,
                'desc':     f"Initial Balance for the Account; {std_nm}",
                'acctSub':  '',
                'refDB':    self.COA_SEED_REFDB,
                'tID':      f"COA_{acct}",
            })
        return seeds

    # ── Row-name derivation override ─────────────────────────────────────

    def _default_rowNm(self, row: Dict[str, Any], i: int) -> str:
        '''GL rows are naturally keyed by tID.'''
        tid = str(row.get('tID', '') or '').strip()
        if tid:
            return tid
        return super()._default_rowNm(row, i)

    # ── v0.3 contract: to_json() instead of save() ────────────────────────

    def to_json(self, indent: int = 2) -> str:
        '''
        Return a JSON string {meta, columns, rows} representing the
        constructed table.  No file written.  Caller may persist if needed.
        '''
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

    # save() is inherited from stmtDB and raises InvalidRequestError —
    # honouring the v0.3 "no save()" rule.


# ─────────────────────────────────────────────────────────────────────────────
# 2. stmtGL_Tax — IRS form provisioning (reads bookNS_GL.json)
# ─────────────────────────────────────────────────────────────────────────────
class stmtGL_Tax(stmtGL):
    '''
    Tax-provisioning view of the GL.  Reads a human-editable
    ``bookNS_GL.json`` mapping file ([fid, acct] pairs grouped by formNm)
    and resolves each acct to its current GL balance.

    Per design v0.3:  only stmtOBJ_Tax exposes the IRS-form nSpaceMap()
    semantics.  load() returns a flat list of {fid, acct, fval, formNm}.
    '''

    BKNS_FN = "bookNS_GL.json"

    def _bkNS_path(self) -> str:
        '''
        Best-effort path resolution under <TOP>/<dirAccounting>/<YEAR>/.
        Falls back to a relative search if llc.TOP / llc.YEAR are missing.
        '''
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
            print(f"stmtGL_Tax: could not load {fn}: {err}")
            return {}

    def nSpaceMap(self) -> Dict[str, List[Dict[str, Any]]]:    # type: ignore[override]
        '''
        Return {formNm: [{fid, acct, fval}, ...]} for each form section
        in bookNS_GL.json.  Underscore-prefixed sections (e.g. "_doc")
        are skipped.  ``fval`` is computed from the GL via _resolve_acct.
        '''
        bkNS = self._bkNS_load()
        out: Dict[str, List[Dict[str, Any]]] = {}
        for formNm, mappings in bkNS.items():
            if not formNm or formNm.startswith('_'):
                continue
            entries: List[Dict[str, Any]] = []
            if not isinstance(mappings, list):
                continue
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

    def load(self) -> List[Dict[str, Any]]:                    # type: ignore[override]
        '''Flatten nSpaceMap into [{fid, acct, fval, formNm}, ...].'''
        flat: List[Dict[str, Any]] = []
        for formNm, entries in self.nSpaceMap().items():
            for e in entries:
                flat.append({**e, 'formNm': formNm})
        return flat

    def loadFillDict(self, formNm: str) -> Dict[str, Any]:
        '''
        Return ``{normalized_fid: fval}`` for the requested IRS form section.

        Contract (v0.3 — same shape across all stmtOBJ_Tax / stmtProfile):

          * fid keys are NORMALIZED via ``_normalizeFid`` — numeric
            tokens become zero-padded ``F###`` so they merge cleanly with
            the IRS service's own ``loadFieldsDF()``.
          * fval is one of:
              - resolved value (str/number) — ready to stamp on the PDF
              - ``None`` / ``""``           — bookNS knows the field but
                                              has no value yet (BLANK,
                                              **not** Complex)
              - the literal ``'Complex'``   — UAS path is tagged
                                              ``Cplx`` / starts with
                                              ``Cplx.``; the field needs
                                              multi-source composition
                                              (next-task work).
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

    SOURCE_TAG = 'GL'

    def to_pdf(self):
        '''
        Return the full PDF-fill DataFrame for this stmt's tax mapping.

        Columns: [fid, acct, fval, formNm, source]
        Each row is one (fid, UAS) pair from ``bookNS_GL.json`` resolved
        against the current GL.  The DataFrame is the same shape produced
        by ``load()`` plus a ``source`` column tagging it as 'GL'.

        ``source`` is the stmt-of-origin tag — used by
        ``ledger.fillDict.buildFillDict`` to split the unified fill
        dataframe back into per-stmt slices when needed.

        Returns ``pandas.DataFrame``.  Raises ImportError if pandas is
        not available.
        '''
        try:
            import pandas as pd
        except ImportError as err:                           # pragma: no cover
            raise ImportError(
                "stmtGL_Tax.to_pdf() requires pandas; install pandas "
                "or use load() for a list-of-dicts.") from err
        rows = self.load()
        for r in rows:
            r.setdefault('source', self.SOURCE_TAG)
        cols = ['fid', 'acct', 'fval', 'formNm', 'source']
        return pd.DataFrame(rows, columns=cols)

    # ── UAS resolver ─────────────────────────────────────────────────────

    def _resolve_acct(self, acct: Any) -> Any:
        '''
        Resolve a UAS path to a value sourced from THIS GL.

        Recognised prefixes within the GL scope:
            "Acct.<key>"  → balance (Σ Debit − Σ Credit) for that COA acct
        Other prefixes (Profile., IS., BS.) are out of stmtGL_Tax scope and
        return None — those are owned by stmtProfile_Tax / stmtIS_Tax /
        stmtBS_Tax respectively.
        '''
        if not isinstance(acct, str):
            return None
        if acct.startswith('Acct.'):
            return self._acct_balance(acct)
        return None

    def _acct_balance(self, acct: str) -> float:
        '''Σ Debit − Σ Credit for ``acct`` over self._rows.'''
        d = c = 0.0
        for r in self._rows:
            if r.get('acct') != acct:
                continue
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            atype = str(r.get('aType', '')).strip().lower()
            if atype in ('debit', 'dr', 'd'):
                d += amt
            else:
                c += amt
        return round(d - c, 2)


# ─────────────────────────────────────────────────────────────────────────────
# 3. _Pipeline — chainable aggregator (AggBy → ViewBy → GroupBy → SortBy → load)
# ─────────────────────────────────────────────────────────────────────────────
class _Pipeline:
    '''
    Chainable pipeline produced by stmtGL_Agg.AggBy().

    Each stage returns ``self`` so calls can be chained:

        rows = stmtGL_View(llc).AggBy()\\
                  .ViewBy('ByAsset')\\
                  .GroupBy(['acctType', 'acct', 'acctSub'])\\
                  .SortBy(['acctType', 'acct'])\\
                  .load()

    The pipeline never mutates the parent stmt object; it builds a local
    list and applies stage functions on .load().
    '''

    def __init__(self, rows: List[Dict[str, Any]],
                 columns: List[str], parent: stmtDB):
        # Copy to insulate from parent's immutable rows (defensive).
        self._rows0 = [dict(r) for r in rows]
        self._columns = list(columns)
        self._parent = parent
        # Stage settings (default = pass-through).
        self._view_by: str = 'All'
        self._include_coa_seed: bool = False
        self._group_by: Optional[List[str]] = None
        self._sort_by:  Optional[List[str]] = None
        self._totals_row: bool = False

    # ── Stages ───────────────────────────────────────────────────────────

    def ViewBy(self, view_by: str = 'All',
               include_coa_seed: bool = False) -> "_Pipeline":
        self._view_by = view_by or 'All'
        self._include_coa_seed = bool(include_coa_seed)
        return self

    def GroupBy(self, keys: Optional[Iterable[str]] = None) -> "_Pipeline":
        self._group_by = list(keys) if keys else None
        return self

    def SortBy(self, keys: Optional[Iterable[str]] = None) -> "_Pipeline":
        self._sort_by = list(keys) if keys else None
        return self

    def WithTotals(self, totals: bool = True) -> "_Pipeline":
        '''Append a TOTAL row after grouping (Trial-Balance shape).'''
        self._totals_row = bool(totals)
        return self

    # ── Materialise ──────────────────────────────────────────────────────

    def load(self) -> List[Dict[str, Any]]:
        rows = self._apply_view_by(
            self._rows0, self._view_by, self._include_coa_seed,
        )
        if self._group_by:
            rows = self._apply_group_by(rows, self._group_by, self._totals_row)
        if self._sort_by:
            rows = self._apply_sort_by(rows, self._sort_by)
        return rows

    # ── Stage implementations ────────────────────────────────────────────

    @staticmethod
    def _apply_view_by(rows: List[Dict[str, Any]],
                       view_by: str,
                       include_coa_seed: bool) -> List[Dict[str, Any]]:
        '''Mirror v0.2 _apply_view_by semantics — same option strings.'''
        if view_by == 'By COA Seed':
            return [dict(r) for r in rows if r.get('refDB') == 'COA']

        work = ([dict(r) for r in rows]
                if include_coa_seed
                else [dict(r) for r in rows if r.get('refDB') != 'COA'])

        if not view_by or view_by == 'All':
            return work

        if view_by == 'By Dups':
            dups = [r for r in work if r.get('Status') == '⚠ Dup']

            def _sk(r):
                try:
                    a = float(r.get('amt', 0) or 0)
                except (TypeError, ValueError):
                    a = 0.0
                return (str(r.get('dt', '')), a, str(r.get('tID', '')))

            dups = sorted(dups, key=_sk)
            label: Dict[str, str] = {}
            n = 0
            for r in dups:
                tid = r.get('tID', '')
                if tid not in label:
                    n += 1
                    label[tid] = f'Dup{n}'
            return [{**r, 'Status': label.get(r.get('tID', ''), '?')} for r in dups]

        # ByAsset / ByLiability / ByEquity / ByIncome / ByExpense
        acct_type = view_by[2:]
        return [r for r in work if r.get('acctType', '') == acct_type]

    @staticmethod
    def _apply_group_by(rows: List[Dict[str, Any]],
                        keys: List[str],
                        with_totals: bool) -> List[Dict[str, Any]]:
        '''
        Group rows by ``keys``; sum amt by aType into Debit/Credit columns
        and compute Balance = Debit − Credit.  Returns a new list of dicts
        carrying only ``keys`` + Debit/Credit/Balance.
        '''
        from collections import defaultdict
        bucket: Dict[tuple, Dict[str, float]] = defaultdict(
            lambda: {'Debit': 0.0, 'Credit': 0.0}
        )
        for r in rows:
            k = tuple(r.get(kk, '') for kk in keys)
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            atype = str(r.get('aType', '')).strip().lower()
            if atype in ('debit', 'dr', 'd'):
                bucket[k]['Debit']  += amt
            else:
                bucket[k]['Credit'] += amt

        out: List[Dict[str, Any]] = []
        for k, v in bucket.items():
            row: Dict[str, Any] = {kk: kv for kk, kv in zip(keys, k)}
            d = round(v['Debit'],  2)
            c = round(v['Credit'], 2)
            row['Debit']   = d
            row['Credit']  = c
            row['Balance'] = round(d - c, 2)
            out.append(row)

        if with_totals:
            td = round(sum(r['Debit']  for r in out), 2)
            tc = round(sum(r['Credit'] for r in out), 2)
            tot: Dict[str, Any] = {kk: '' for kk in keys}
            if keys:
                tot[keys[0]] = 'TOTAL'
            tot['Debit']   = td
            tot['Credit']  = tc
            tot['Balance'] = round(td - tc, 2)
            out.append(tot)

        return out

    @staticmethod
    def _apply_sort_by(rows: List[Dict[str, Any]],
                       keys: List[str]) -> List[Dict[str, Any]]:
        # Keep TOTAL row last regardless of sort.
        body = [r for r in rows if not (
            isinstance(r.get(keys[0]), str) and r.get(keys[0]) == 'TOTAL'
        )] if keys else list(rows)
        tail = [r for r in rows if r not in body]

        def _sk(r):
            return tuple(str(r.get(k, '') or '') for k in keys)
        return sorted(body, key=_sk) + tail


# ─────────────────────────────────────────────────────────────────────────────
# 4. stmtGL_Agg — aggregator base; AggBy() is the pipeline entry point
# ─────────────────────────────────────────────────────────────────────────────
class stmtGL_Agg(stmtGL):
    '''
    Adds the ``AggBy()`` pipeline entry point.  ``load()`` defaults to the
    base stmtGL row list — callers reach for AggBy() when they want
    filtering / aggregation / sorting.
    '''

    def AggBy(self) -> _Pipeline:
        '''Start a chainable pipeline:  ViewBy → GroupBy → SortBy → load.'''
        return _Pipeline(self._rows, self._columns, self)


# ─────────────────────────────────────────────────────────────────────────────
# 5. stmtGL_View — UI-facing consumer.  Chainable pipeline + a couple of
#    convenience wrappers for the legacy 2-frame GL view template.
# ─────────────────────────────────────────────────────────────────────────────
class stmtGL_View(stmtGL_Agg):
    '''
    UI consumer of the GL.  Use the AggBy() pipeline to filter/aggregate.

    Convenience wrappers preserve v0.2 view-by semantics so the existing
    general_ledger_view.html template can be reused without change.
    '''

    VIEW_BY_OPTIONS = ['All', 'By Dups', 'By COA Seed',
                       'ByAsset', 'ByLiability', 'ByEquity',
                       'ByIncome', 'ByExpense']

    # ── Convenience: transaction frame (Frame 2 in the 2-frame GL view) ──

    def view(self, view_by: str = 'All',
             include_coa_seed: bool = False) -> List[Dict[str, Any]]:
        '''Flat slice via the pipeline.  No grouping.'''
        return (self.AggBy()
                .ViewBy(view_by, include_coa_seed=include_coa_seed)
                .load())

    # ── Convenience: trial balance frame (Frame 1) ───────────────────────

    def trial_balance(self,
                      view_by: str = 'All',
                      with_totals: bool = True) -> List[Dict[str, Any]]:
        '''
        Trial-balance aggregation via the pipeline:
            AggBy().ViewBy(view_by, include_coa_seed=True)
                   .GroupBy(['acctType','acct','acctSub'])
                   .WithTotals(True)
                   .SortBy(['acctType','acct']).load()
        '''
        # Filter the TB to the classic 5 acctTypes only — same as v0.2.
        _TB_TYPES = {'Asset', 'Liability', 'Equity', 'Income', 'Expense'}
        all_rows = self.AggBy().ViewBy(view_by, include_coa_seed=True).load()
        rows = [r for r in all_rows if r.get('acctType') in _TB_TYPES]

        # Run the rest of the pipeline on the filtered row set.
        pipe = _Pipeline(rows, self._columns, self)
        return (pipe
                .ViewBy('All', include_coa_seed=True)
                .GroupBy(['acctType', 'acct', 'acctSub'])
                .WithTotals(with_totals)
                .SortBy(['acctType', 'acct'])
                .load())

    # ── Stats summary (independent of view_by) ───────────────────────────

    def stats(self) -> Dict[str, Any]:
        td = tc = 0.0
        by_type: Dict[str, int] = {}
        # Use unfiltered rows minus COA seed for stats (matches v0.2).
        for r in self._rows:
            if r.get('refDB') == 'COA':
                continue
            at = r.get('acctType', 'Unknown') or 'Unknown'
            by_type[at] = by_type.get(at, 0) + 1
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if str(r.get('aType', '')).strip().lower() in ('debit', 'dr', 'd'):
                td += amt
            else:
                tc += amt
        return {
            'Transactions': sum(by_type.values()),
            'TotalDebit':   round(td, 2),
            'TotalCredit':  round(tc, 2),
            'NetBalance':   round(td - tc, 2),
            'ByAcctType':   by_type,
        }

    def is_balanced(self, tolerance: float = 0.01) -> bool:
        s = self.stats()
        return abs(s['TotalDebit'] - s['TotalCredit']) < tolerance


# ─────────────────────────────────────────────────────────────────────────────
# 6. stmtGL_Reports — stub
# ─────────────────────────────────────────────────────────────────────────────
class stmtGL_Reports(stmtGL):
    '''
    Reports consumer — stub for v0.3.

    Future scope: assemble GL-derived report fragments (audit trail,
    exception reports, bank-reconciliation aids) into a textual or PDF
    deliverable.  No implementation yet by user directive.
    '''

    def load(self) -> List[Dict[str, Any]]:                    # type: ignore[override]
        raise NotImplementedError(
            "stmtGL_Reports is a v0.3 stub — implementation TBD."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. stmtTrialBalance — backwards-compatible Trial Balance snapshot
# ─────────────────────────────────────────────────────────────────────────────
# Previously lived in ledger/stmtGeneralLedger.py (v0.2).  Moved here when
# that module was consolidated.  The v0.3 equivalent is
# stmtGL_View.trial_balance(), but this class is kept for call sites that
# instantiate it directly (rptFinancialReport, legacy tests).
# ─────────────────────────────────────────────────────────────────────────────

class stmtTrialBalance(stmtDB):
    '''
    Immutable Trial Balance constructed at instantiation time.

    Columns (beyond the _lineNo / _rowNm sentinels):
        acctType, acct, acctMinor, acctSub, propNm, Debit, Credit, Balance

    Construction:
        gl_records=...  — pre-built GL record list (optional fast path).
        (default)       — build stmtGL(llc) and use its rows.

    The final row is ``acctType='TOTAL'`` and its Debit / Credit should
    agree (``_meta['balanced'] == True`` when |Σ Debit − Σ Credit| < 0.01).
    '''

    DEFAULT_TBLID = "TrialBalance"
    COLUMNS = ['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'Debit', 'Credit', 'Balance']
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
            "view_by":    self._init_view_by,
            "sourceMode": (
                "gl_records" if self._init_gl_records is not None else "stmtGL"
            ),
            "balanced":     bool(check.get('balanced', False)),
            "total_debit":  float(check.get('total_debit',  0.0)),
            "total_credit": float(check.get('total_credit', 0.0)),
            "tb_diff":      float(check.get('tb_diff',      0.0)),
            "note": (
                "Trial Balance built from stmtGL (COA-seeded).  "
                "Balanced ↔ Σ Debit = Σ Credit within $0.01.  "
                "Zero-balance rows are retained so every COA account appears."
            ),
        }

    # ── Source loading ───────────────────────────────────────────────────────

    def _load_gl_records(self) -> List[Dict[str, Any]]:
        gl = stmtGL(self.llc)
        return list(gl.load() or [])

    # ── Aggregation ──────────────────────────────────────────────────────────

    def _aggregate_tb(self,
                      gl_records: List[Dict[str, Any]],
                      view_by: str
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not gl_records:
            return [], {'balanced': True, 'total_debit': 0.0, 'total_credit': 0.0, 'tb_diff': 0.0}

        df = _pd.DataFrame(gl_records)
        if df.empty:
            return [], {'balanced': True, 'total_debit': 0.0, 'total_credit': 0.0, 'tb_diff': 0.0}

        if 'acctType' not in df.columns or df['acctType'].astype(str).str.strip().eq('').any():
            coa = getattr(self.llc, 'coa', None) or _llcCOA(self.llc)
            need_class = df.get('acctType', _pd.Series([''] * len(df))).astype(str).str.strip().eq('')
            df['acctType'] = df.get('acctType', '').astype(str)
            df.loc[need_class, 'acctType'] = df.loc[need_class, 'acct'].map(
                lambda a: coa._Type(a) if a else ''
            )

        df['amt'] = _pd.to_numeric(df.get('amt'), errors='coerce').fillna(0.0)

        tb = df[df['acctType'].isin(_TB_ACCT_TYPES)].copy()

        if view_by and view_by != 'All':
            wanted = view_by[2:]  # strip 'By'
            tb = tb[tb['acctType'] == wanted]

        if tb.empty:
            return [], {'balanced': True, 'total_debit': 0.0, 'total_credit': 0.0, 'tb_diff': 0.0}

        for col in ('acctSub', 'acctMinor', 'propNm'):
            if col in tb.columns:
                tb[col] = tb[col].fillna('').astype(str)
            else:
                tb[col] = ''

        grp = (
            tb.groupby(['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'aType'])['amt']
              .sum().unstack(fill_value=0.0).reset_index()
        )
        if 'Debit'  not in grp.columns: grp['Debit']  = 0.0
        if 'Credit' not in grp.columns: grp['Credit'] = 0.0

        grp['Balance'] = (grp['Debit'] - grp['Credit']).round(2)
        grp['Debit']   = grp['Debit'].round(2)
        grp['Credit']  = grp['Credit'].round(2)

        order = {t: i for i, t in enumerate(_TB_ACCT_ORDER)}
        grp['_sort'] = grp['acctType'].map(lambda x: order.get(x, 99))
        grp = grp.sort_values(['_sort', 'acct', 'acctMinor', 'propNm', 'acctSub']).drop(columns=['_sort'])

        rows = grp[['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'Debit', 'Credit', 'Balance']].to_dict(orient='records')

        total_d = round(sum(r['Debit']  for r in rows), 2)
        total_c = round(sum(r['Credit'] for r in rows), 2)
        tb_diff = round(total_d - total_c, 2)

        rows.append({
            'acctType': 'TOTAL', 'acct': '', 'acctMinor': '',
            'acctSub': '', 'propNm': '',
            'Debit': total_d, 'Credit': total_c, 'Balance': tb_diff,
        })

        return rows, {
            'balanced':     abs(tb_diff) < 0.01,
            'total_debit':  total_d,
            'total_credit': total_c,
            'tb_diff':      tb_diff,
        }

    # ── Convenience accessors ────────────────────────────────────────────────

    def is_balanced(self) -> bool:
        return bool(self._meta.get('balanced', False))

    def totals(self) -> Dict[str, float]:
        return {
            'Debit':  float(self._meta.get('total_debit',  0.0)),
            'Credit': float(self._meta.get('total_credit', 0.0)),
            'Diff':   float(self._meta.get('tb_diff',      0.0)),
        }

    def _to_IRS(self, formObj):
        return []
