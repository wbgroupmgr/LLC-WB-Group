'''
stmtDB — base class for Constructed Financial Data Objects.

Per DataModelGuide § 2:
  - Constructed data objects are immutable once instantiated.
  - Every table row has a line number; every column has a columnID.
  - Every value is addressable by (stmtObj / tblID / rowNm / colNm).

Inherits ledger.ledgerDB so stmt objects participate in the same class
hierarchy as Financial DB Data Objects.  Unlike ledgerDB, which reads and
writes a live JSON DB file under Accts/, stmtDB keeps the constructed
table purely in memory; save() writes a read-only snapshot cache under
Stmts/ — the in-memory object remains immutable.

Common API shared with ledger/* and consumed by ui/* + irs/*:
    load()        → list[dict]      (rows with _lineNo + _rowNm + colNm keys)
    save()        → path written    (snapshot cache)
    to_DF()       → pandas.DataFrame
    nSpaceMap()   → dict{(tblID, rowNm, colNm): value}

Subclasses MUST override _build() to populate:
    self._tblID      : str        (statement/table identifier)
    self._columns    : list[str]  (ordered columnIDs)
    self._rows       : list[dict] (row dicts, keyed by colNm)
Optionally:
    self._default_rowNm(row, i) : str     (override to customise row-name derivation)

## Difference between load() and _build()

`stmtBalanceSheet.load()` is inherited unchanged from `stmtDB` (`stmtDB.py:185`). It is a deliberately thin accessor — the real work happens at construction time, not at load time.

The implementation is just three lines:

```python
def load(self) -> List[Dict[str, Any]]:
    return [dict(r) for r in self._rows]
```

It returns a shallow copy of `self._rows` so callers cannot mutate the constructed table. Each element is a dict with keys `acctType, acct, acctSub, Debit, Credit, Balance` plus the `_lineNo` / `_rowNm` sentinels added by `stmtDB._finalize`.

1. Because constructed stmt objects are immutable (DataModelGuide §2), 
2. `load()` takes no parameters and does no filtering — every call returns the same canonical row list. 
3. The `view_by` filter (`'All' | 'ByAsset' | 'ByLiability' | 'ByEquity'`) is applied **once**, at `__init__` time, by `_aggregate_bs()`.
4. By the time `_rows` is populated, that filter has already been baked in. 
5. This is different from `stmtProfile.load(view_by='All')`, which does accept a runtime filter argument because Profile rows are cheap to filter by string prefix.

##  Full Construction pipeline 

- _build executes the pipeline @ init
- output of the pipeline  produces self._rows table of dicts

1. `__init__` stashes `view_by` and any pre-built `gl_records` on the instance.
2. `_build()` runs:
   - If no `gl_records` were passed, 
       - it builds an `stmtGeneralLedger(llc, view_by='All', include_coa_seed=True)` and 
       - grabs `gl._rows` — so every COA Asset/Liability/Equity account appears on the BS even with zero postings.
   - Hands those records to `_aggregate_OBJ(gl_records, view_by)`, 
       - dispatches to `_aggregate_bs_pandas` (preferred) or 
       - `_aggregate_bs_fallback` (no pandas).
3. Apply he ViewBy slice [aggregator] 
    - The aggregator filters rows based on ViewBy setting
    - slice based on `acctType ∈ {Asset, Liability, Equity}`, 
    - groupby `(acctType, acct, acctSub)`, sums Debit / Credit
    - computes `Balance = Debit − Credit`, 
    - sorts by `OBJ_ORDER` then by `acct`, and 
    - appends a `TOTAL` row.
4. returns a `check` dict (`asset, liability, equity, equation_diff, balanced`) 
    - checkDict  gets stashed in `self._meta['check']` and 
    - `self._check`, exposed via 
        - `last_check()` and 
        - `stats()`. 
    - the checkDict is NOT part of what `load()` returns.
5. `_finalize` (in stmtDB) renumbers `_lineNo` globally, 
    - fills in `_rowNm`, 
    - builds the cell index that `get(rowNm, colNm)` and 
    - `nSpaceMap()` use, and freezes the instance.

## load() 
- -returns self._rows
- just the read-side handle on data that was wrangled and locked at construction. 
_ For a different view
    - build a new `stmtBalanceSheet(llc, view_by=…)`.
    
## get() -  Cell values
- `get(rowNm, colNm)` against the cell index. 
- to get tax aggregates (`cash`, `total_assets`, `accum_depr`, etc.), 
- get  tax aggregates (cash, total_assets, accum_depr, etc.)
    - use `taxAggregates()`
    - lazily delegates to `rptFinancialReport.taxData()`
    - caches via `object.__setattr__` to bypass the freeze.
'''

from __future__ import annotations

import datetime as _dt
import json as _json
import os as _os
from pathlib import Path as _Path
from typing import Any, Dict, List, Optional, Tuple

from ledger.ledgerDB import ledgerDB


# ── Special sentinel columns added to every stmt row ─────────────────────────
LINE_COL = "_lineNo"
ROW_COL  = "_rowNm"

# Default TOTAL-row rowNm (detected automatically by _default_rowNm)
TOTAL_ROW_NM = "TOTAL"


class StmtImmutableError(RuntimeError):
    '''Raised when code attempts to mutate a stmt object after construction.'''


class stmtDB(ledgerDB):
    '''
    Base class for Constructed Financial Data Objects.

    Lifecycle:
      1. __init__        — subclass calls super().__init__(llc, **kwargs).
      2. _build()        — subclass populates self._tblID / _columns / _rows.
      3. _finalize()     — this base class normalises rows (adds _lineNo /
                           _rowNm), builds indexes, then LOCKS the instance.
      4. Any attribute write after lock → StmtImmutableError.
    '''

    # Hooks subclasses may override
    DEFAULT_TBLID: str = ""

    # ── IRS Form publication map (DataModelGuide § 4 / Phase 5) ──────────────
    # Subclasses declare which of their cells publish to which IRS form
    # logical-key.  Shape:
    #     PUBLISH_MAP: ClassVar[Dict[str, List[PubEntry]]] = {
    #         "Form1065": [PubEntry(src_row=..., src_col=..., logicalKey=...), ...],
    #     }
    # Default is empty — stmt classes without form bindings keep the
    # legacy flow undisturbed.
    PUBLISH_MAP: Dict[str, List[Any]] = {}

    def __init__(self, llc, **kwargs):
        # Pre-freeze window so super().__init__ and _build() can set attrs.
        object.__setattr__(self, "_frozen", False)

        super().__init__(llc, **kwargs)

        # Standard storage slots — subclasses populate these in _build().
        self._tblID: str = self.DEFAULT_TBLID or self.__class__.__name__
        self._columns: List[str] = []
        self._rows: List[Dict[str, Any]] = []
        self._meta: Dict[str, Any] = {}
        self._tstamp: str = _dt.datetime.now().isoformat(timespec="seconds")

        # Subclass populates the table.
        self._build(**kwargs)

        # Normalise + freeze.
        self._finalize()

    # ── Subclass hooks ───────────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        '''Subclass MUST override. Populate self._tblID, _columns, _rows.'''
        raise NotImplementedError(
            f"{self.__class__.__name__}._build() not implemented"
        )

    def _default_rowNm(self, row: Dict[str, Any], i: int) -> str:
        '''
        Default row-name derivation.  Subclasses may override.
          - If row already has _rowNm, use it.
          - If row has acctType == 'TOTAL' (case-insensitive), return 'TOTAL'.
          - Otherwise derive "<acctType>.<acct>.<acctSub>" trimmed of blanks,
            falling back to "row_{i:03d}" if nothing usable.
        '''
        if row.get(ROW_COL):
            return str(row[ROW_COL])
        at = str(row.get("acctType", "") or "").strip()
        if at.upper() == "TOTAL":
            return TOTAL_ROW_NM
        parts = [
            at,
            str(row.get("acct", "") or "").strip(),
            str(row.get("acctSub", "") or "").strip(),
        ]
        parts = [p for p in parts if p]
        return ".".join(parts) if parts else f"row_{i:03d}"

    # ── Finalization / immutability ──────────────────────────────────────────

    def _finalize(self) -> None:
        '''
        Normalise rows — add _lineNo (1-based) and _rowNm — then freeze.
        Also builds the (rowNm, colNm) → value index used by nSpaceMap().
        '''
        # Ensure _columns includes the two sentinel columns first (for DF order)
        cols = list(self._columns)
        if LINE_COL not in cols: cols = [LINE_COL] + cols
        if ROW_COL  not in cols: cols.insert(1, ROW_COL)
        self._columns = cols

        normalised: List[Dict[str, Any]] = []
        row_names_seen: Dict[str, int] = {}
        for i, raw in enumerate(self._rows, start=1):
            row = dict(raw)
            row[LINE_COL] = i
            name = self._default_rowNm(raw, i - 1)
            # disambiguate collisions: Foo, Foo#2, Foo#3 …
            if name in row_names_seen:
                row_names_seen[name] += 1
                name = f"{name}#{row_names_seen[name]}"
            else:
                row_names_seen[name] = 1
            row[ROW_COL] = name
            normalised.append(row)
        self._rows = normalised

        # Build the flat addressing index: {(rowNm, colNm): value}
        # (tblID is added lazily in nSpaceMap() so subclasses may alter it)
        self._cellIndex: Dict[Tuple[str, str], Any] = {}
        for row in self._rows:
            rn = row[ROW_COL]
            for c in self._columns:
                self._cellIndex[(rn, c)] = row.get(c)

        # Lock the instance.
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, key: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise StmtImmutableError(
                f"{self.__class__.__name__} is immutable; "
                f"attempted to set attribute {key!r}"
            )
        object.__setattr__(self, key, value)

    # ── Public common API (shared with ledger/ledgerObject) ──────────────────

    def tblID(self) -> str:
        return self._tblID

    def columns(self) -> List[str]:
        '''Ordered list of columnIDs (== column names).'''
        return list(self._columns)

    def rowNames(self) -> List[str]:
        return [r[ROW_COL] for r in self._rows]

    def load(self) -> List[Dict[str, Any]]:
        '''
        Return the constructed table rows (a shallow copy so callers
        can neither shadow-mutate nor break immutability).
        '''
        return [dict(r) for r in self._rows]

    def list(self) -> List[Dict[str, Any]]:
        '''Alias for load() to match the ui/ convention.'''
        return self.load()

    def to_DF(self):
        '''Return a pandas.DataFrame of the constructed table.'''
        try:
            import pandas as pd
        except ImportError:
            raise RuntimeError("pandas not available for to_DF()")
        if not self._rows:
            return pd.DataFrame(columns=self._columns)
        return pd.DataFrame(self._rows, columns=self._columns)

    # Override ledgerDB.toDF() so it delegates to the stmt in-memory table
    # rather than trying to re-parse self.load() as a DB list.
    def toDF(self):
        return self.to_DF()

    # ── Uniform Ledger API — stmt-aware to_agg default ───────────────────────
    #
    # stmt rows carry pre-aggregated Debit / Credit / Balance columns rather
    # than raw transaction `amt`.  When the caller does NOT supply aggDict,
    # auto-select whichever of {Debit, Credit, Balance, amt} are present so
    # that `by='Trial'` / `by='BalSh'` / `by='IncStmt'` return meaningful
    # numeric sums without requiring the client to know the stmt schema.
    _STMT_NUMERIC_COLS = ("Debit", "Credit", "Balance", "amt")

    def to_agg(self, filterDict=None, by=None, aggDict=None, pretty=False):
        if aggDict is None:
            present = [c for c in self._STMT_NUMERIC_COLS if c in self._columns]
            if present:
                aggDict = {c: "sum" for c in present}
        return super().to_agg(
            filterDict=filterDict, by=by, aggDict=aggDict, pretty=pretty,
        )

    # ── Cell-level addressing ────────────────────────────────────────────────

    def get(self, rowNm: str, colNm: str, default: Any = None) -> Any:
        return self._cellIndex.get((rowNm, colNm), default)

    def nSpaceMap(self) -> Dict[Tuple[str, str, str], Any]:
        '''
        Return a flat dict keyed by (tblID, rowNm, colNm) → value.
        This is the stmtObj-level addressing map.  For multi-table stmt
        objects (future), subclasses may override and union the cell
        indexes of each sub-table.
        '''
        tbl = self._tblID
        return {(tbl, rn, cn): v for (rn, cn), v in self._cellIndex.items()}

    # ── IRS Form publish payload ─────────────────────────────────────────────

    def forms_published(self) -> List[str]:
        '''
        Return the list of IRS form names this data object publishes to,
        per its class-level PUBLISH_MAP.
        '''
        return sorted(self.PUBLISH_MAP.keys())

    def to_form_payload(self, formNm: str) -> List[Dict[str, Any]]:
        '''
        Generate the JSON-payload rows for one IRS form.

        Walks ``self.PUBLISH_MAP[formNm]`` and, for each declared
        ``PubEntry``, pulls ``self._cellIndex[(src_row, src_col)]`` and
        emits a standardised row:

            {
              "formNm":       formNm,                 # hidden view field
              "logicalKey":   "P1_1a",
              "src_tbl":      self.tblID(),
              "src_row":      "Acct.Rev.Rent",
              "src_col":      "Balance",
              "value":        "12,000.50",            # currency-formatted
              "raw":          12000.50,               # untouched numeric
              "publish":      True,
              "fType":        "text",
              "checkedValue": None,                   # or "/1" / "/2"
              "note":         "Gross rental receipts",
            }

        Rows are produced in the order PUBLISH_MAP declares them.
        Unknown cells (row/col missing from the table) are emitted with
        ``value=""`` and ``raw=None`` — the form layer will decide whether
        that counts as publishable.
        '''
        # Lazy import avoids hard-coupling stmtDB to the irs package.
        from irs.publishMap import as_payload_row

        entries = self.PUBLISH_MAP.get(formNm, [])
        payload: List[Dict[str, Any]] = []
        tbl = self._tblID
        for entry in entries:
            raw = self._cellIndex.get((entry.src_row, entry.src_col))
            payload.append(as_payload_row(
                formNm=formNm, tblID=tbl, entry=entry, value=raw,
            ))
        return payload

    # ── Uniform Ledger API — stmt-level to_IRS Book-field dict ──────────────
    #
    # Default ``ledgerObject.to_IRS()`` returns ``list[dict]`` (one dict per
    # entity record — e.g. one owner per K-1).  That shape is correct for
    # DB-entity classes like llcOwners, but stmt* classes are *constructed
    # aggregates* (Balance Sheet, Income Stmt, Trial Balance, etc.) — their
    # contribution to IRS forms is a flat Book-field dictionary keyed by
    # form-scoped logical keys.
    #
    # Returns::
    #
    #     {
    #       "<formNm1>": { "<logicalKey>": raw_value, ... },
    #       "<formNm2>": { ... },
    #     }
    #
    # Forms with no PUBLISH_MAP entries are omitted (empty map → empty
    # top-level dict).  Downstream ``to_IRS`` orchestration layers merge
    # this with entity-level dicts (owners, customers) and LLC profile
    # extraFields (name, EIN, propertyName) to produce the final Fill-PDF
    # payload.
    def to_IRS(self):
        out: Dict[str, Dict[str, Any]] = {}
        for formNm in self.forms_published():
            payload = self.to_form_payload(formNm)
            out[formNm] = {
                row["logicalKey"]: row.get("raw")
                for row in payload
                if row.get("logicalKey")
            }
        return out

    # ── save() : write a read-only cache/snapshot ────────────────────────────

    def FN(self) -> str:
        '''
        Path to the snapshot cache file.  Located under
        <TOP>/<dirAccounting>/Stmts/<tblID>_<llcObjName>.json
        — distinct from ledgerDB's Accts/ so the live DB is never shadowed.
        '''
        try:
            top   = self.llc.TOP
            acct  = getattr(self.llc, "dirAccounting", "")
            objNm = getattr(self.llc, "objName", "")
        except Exception:
            top, acct, objNm = ".", "", "LLC"

        stmts_dir = _os.path.join(top, acct, "Stmts") if acct else _os.path.join(top, "Stmts")
        fn = _os.path.join(stmts_dir, f"{self._tblID}_{objNm}.json")
        if getattr(self, "debug", False):
            print(f"{self._tblID} stmtDB.FN: {fn}")
        return fn

    def save(self, _ignored: Any = None):
        '''
        Constructed stmt objects are immutable by contract (Q2 resolution,
        ProjectLevel3 v0.2) — ``save()`` is not a valid request.

        Callers that need an audit snapshot of the constructed table
        should use :py:meth:`snapshot` explicitly; ``save()`` always
        raises.
        '''
        from ledger.ledgerObject import InvalidRequestError
        raise InvalidRequestError('InvalidRequest; ImmutableObject')

    def snapshot(self, _ignored: Any = None) -> str:
        '''
        Opt-in audit snapshot of the constructed table.  Writes a JSON
        payload (same shape as the retired ``save()``) to
        ``<TOP>/<dirAccounting>/Stmts/<tblID>_<objName>.json``.

        This does NOT mutate the stmt object; it only writes a
        read-only sidecar.  Not called by any production path in v0.2 —
        intended for v0.3 audit-trail use.
        '''
        fn = self.FN()
        try:
            _Path(_os.path.dirname(fn)).mkdir(parents=True, exist_ok=True)
        except Exception as err:
            print(f"{self._tblID}: could not create Stmts dir: {err}")

        # Convert nSpaceMap tuple keys → JSON-safe lists
        ns_items = [
            [list(k), _json_safe(v)]
            for k, v in self.nSpaceMap().items()
        ]

        payload = {
            "tblID":      self._tblID,
            "objectName": self.__class__.__name__,
            "tstamp":     self._tstamp,
            "columns":    list(self._columns),
            "rows":       [ {k: _json_safe(v) for k, v in r.items()} for r in self._rows ],
            "nSpaceMap":  ns_items,
            "meta":       {k: _json_safe(v) for k, v in self._meta.items()},
        }
        try:
            with open(fn, "w") as fio:
                _json.dump(payload, fio, indent=4, default=str)
        except Exception as err:
            print(f"{self._tblID}: FAIL save snapshot: {fn}, {err}")
            return ""
        return fn

    # ── Iterability (inherits from ledgerObject but stmt wants rows) ─────────

    def iterator(self) -> None:
        '''No-op for stmt: rows are fixed at construction time.'''
        pass

    def __iter__(self):
        for r in self._rows:
            yield dict(r)

    def __len__(self) -> int:
        return len(self._rows)

    # ── Diagnostic / safety ──────────────────────────────────────────────────

    def meta(self) -> Dict[str, Any]:
        '''
        Default meta() combining core stmt info and any subclass-supplied
        extras placed in self._meta during _build().
        '''
        base = {
            "objectName": self.__class__.__name__,
            "tblID":      self._tblID,
            "rows":       len(self._rows),
            "columns":    list(self._columns),
            "tstamp":     self._tstamp,
            "immutable":  True,
        }
        # Subclass extras win on key collision
        base.update(self._meta or {})
        return base


# ── JSON helpers ─────────────────────────────────────────────────────────────

def _json_safe(v: Any) -> Any:
    '''Coerce pandas/numpy scalars into plain python for json.dump.'''
    if v is None:
        return None
    # pandas.Timestamp / datetime
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass
    # numpy scalars
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
        if isinstance(v, (np.bool_,)):
            return bool(v)
    except Exception:
        pass
    return v
