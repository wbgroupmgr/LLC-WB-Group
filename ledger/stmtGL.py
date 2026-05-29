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

Contains the stateless ``ledgerGeneral`` service (mergeGL / toDoubleEntry /
classify) — previously a separate ledger/ledgerGeneral.py, consolidated here
in v0.3 so there is one canonical GL module.

Timestamp: 2026.04.27 — v0.3.GL
'''

from __future__ import annotations

import json as _json
import os as _os
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as _pd

from ledger.stmtDB import stmtDB
from ledger.llcCOA import ChartOfAccounts as _llcCOA
from ledger.ledgerObject import ledgerObject

# ── GL helper lambdas ─────────────────────────────────────────────────────────
toKAmt   = lambda d: -float(d['amt'] or 0) if d['aType'] == 'Credit' else float(d['amt'] or 0)
toTid    = lambda d: f"{d['dt']}_{toKAmt(d):0.2f}"
toIDDict = lambda l: {toTid(d): i for i, d in enumerate(l)}


# ─────────────────────────────────────────────────────────────────────────────
# 0. ledgerGeneral — stateless GL-building service
# ─────────────────────────────────────────────────────────────────────────────
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
        glSumDF = df.groupby(['acct', 'aType']).amt.sum().unstack()
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
        newList = []
        for bkDict in bkList:
            bkID = toTid(bkDict)
            if bkID in erIDList:
                continue
            newList.append(bkDict)
        return newList

    def toGLList(self, tObj):
        glDF = tObj.toGL(self).copy()
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

        tID uniqueness: within one source DB, two different transactions can
        produce the same base tID (same date + same signed amount).  A per-call
        counter suffix (_001, _002 …) is appended on collision so every GL
        entry has a unique tID.  The first occurrence keeps the bare tID so
        existing references are unchanged; only duplicates get a suffix.
        '''
        result  = []
        seen: dict = {}   # base_tID → count of times already used

        def _unique_tid(base: str) -> str:
            if base not in seen:
                seen[base] = 0
                return base
            seen[base] += 1
            return f"{base}_{seen[base]:03d}"

        for r in records:
            _lv = r.get('Ledger')
            ledger_acct = (
                '' if (_lv is None or (isinstance(_lv, float) and _lv != _lv)
                       or str(_lv).strip().lower() == 'nan')
                else str(_lv).strip()
            )

            src_tid = r.get('tID', '') or ''
            e1 = {k: v for k, v in r.items() if k not in ('Ledger', 'tID')}
            e1['srcTID']   = src_tid
            e1['tID']      = _unique_tid(toTid(e1))
            e1['acctType'] = self.coa._Type(e1.get('acct', ''))
            result.append(e1)

            if ledger_acct:
                e2 = {k: v for k, v in r.items() if k not in ('Ledger', 'tID')}
                e2['acct']     = ledger_acct
                e2['aType']    = self._toggle_atype(r.get('aType', 'Debit'))
                e2['srcTID']   = src_tid
                e2['tID']      = _unique_tid(toTid(e2))
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
        newDF = _pd.concat(
            [df, _pd.DataFrame(rList, index=df.columns).transpose()]
        ).set_index(cList[0:2])
        newDF['Total'] = newDF.Debit - newDF.Credit
        with _pd.option_context('future.no_silent_downcasting', True):
            return newDF.fillna('')


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
               'desc', 'acctSub', 'propNm', 'propOwners', 'refDB', 'tID', 'srcTID']
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

        # Sort transaction rows by tID (date-prefixed → chronological order).
        # COA seed rows are kept separate so they don't interleave with txns.
        tx_rows = sorted(
            [self._norm_row(r) for r in (gl_records or [])],
            key=lambda r: (str(r.get('dt') or ''), float(r.get('amt') or 0), str(r.get('tID') or '')),
        )
        seed_rows = [self._norm_row(r) for r in seed]
        rows = seed_rows + tx_rows

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
        po = r.get('propOwners') or r.get('propOwner') or ''
        if isinstance(po, dict):
            po = ', '.join(f"{k}:{v}%" for k, v in po.items())
        return {
            'Status':     r.get('Status',   '') or '',
            'dt':         r.get('dt',       '') or '',
            'acctType':   r.get('acctType', '') or '',
            'acct':       r.get('acct',     '') or '',
            'aType':      r.get('aType',    '') or '',
            'amt':        amt,
            'desc':       r.get('desc',     '') or '',
            'acctSub':    r.get('acctSub',  '') or '',
            'propNm':     str(r.get('propNm', '') or ''),
            'propOwners': str(po),
            'refDB':      r.get('refDB',    '') or '',
            'tID':        r.get('tID',      '') or '',
            'srcTID':     r.get('srcTID',   '') or '',
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
        '''Double-entry-expand each source then merge via ledgerGeneral.'''
        gl = ledgerGeneral(self.llc)
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

        if not view_by or view_by in ('All', 'Details'):  # Details = no type filter
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
                       'ByIncome', 'ByExpense', 'Details']

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

        # Normalise acct → top-2 UAS nodes; derive acctMinor from remainder.
        normed = []
        for r in rows:
            parts = str(r.get('acct', '')).split('.')
            r2 = dict(r)
            r2['acct']      = '.'.join(parts[:2]) if len(parts) >= 2 else r.get('acct', '')
            r2['acctMinor'] = '.'.join(parts[2:]) if len(parts) > 2 else ''
            normed.append(r2)

        if view_by == 'Details':
            group_keys = ['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm']
        else:
            # Default (All): aggregate on [acct, acctMinor] so minor sub-accounts
            # are visible as separate rows rather than rolled into the top-2 node.
            group_keys = ['acctType', 'acct', 'acctMinor']

        pipe = _Pipeline(normed, self._columns, self)
        result = (pipe
                  .ViewBy('All', include_coa_seed=True)
                  .GroupBy(group_keys)
                  .WithTotals(with_totals)
                  .load())

        # Sort by _TB_ACCT_ORDER then acct then acctMinor.
        _order = {t: i for i, t in enumerate(_TB_ACCT_ORDER)}
        body  = [r for r in result if r.get('acctType') != 'TOTAL']
        total = [r for r in result if r.get('acctType') == 'TOTAL']
        body.sort(key=lambda r: (_order.get(r.get('acctType', ''), 99),
                                  str(r.get('acct', '')),
                                  str(r.get('acctMinor', ''))))
        return body + total

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
                       'ByIncome', 'ByExpense', 'Details']

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

        if view_by and view_by not in ('All', 'Details') and view_by.startswith('By'):
            tb = tb[tb['acctType'] == view_by[2:]]

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
