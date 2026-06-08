'''
ledger.stmtProfile — Constructed, immutable LLC Profile statement.

Per DataModelGuide § 2:
- constructed data object, 
- immutable once instantiated,
- every row has a line number, every column has a columnID, and 
- every cell is addressable by (stmtObj / tblID / rowNm / colNm

Inheritance:    stmtDB → ledger.ledgerDB → ledger.ledgerObject
                stmtProfile_Tax →  stmtProfile

Deign Notes per ProjectLevel3 v0.2.4):
    The IRS view layer (``ui.llcIRSViewBase``) used to reach directly into
    ``llc.entity`` and ``llc.F1065`` — plain dicts loaded by LLC._Profile().
    * That violates the Architecture Guide, which requires *all* data
       construction / wrangling / shaping to live in ledger services.
    * stmtProfile encapsulates those two source dicts witin the LLC profile
    * All fields within the profile are a single, immutable, row-addressable table
    * exactly the same shape as every other stmt* object (BalanceSheet, IncomeStmt, OwnerEquity, etc.) 
    * so every IRS form view can use the uniform Ledger API to pull entity / preparer /
    business-code fields by (tblID, rowNm, colNm) triple.

Columns (beside the _lineNo / _rowNm sentinels added by stmtDB):
    acctType, acct, acctSub, value

Row convention (per user directive, v0.2.4.1):
    acct     = "<source>.<fieldName>"        e.g. "entity.entity_name"
    _rowNm   = "Profile.<source>.<fieldName>" e.g. "Profile.F1065.preparer_ein"
    _lineNo  = 1-based position within the source dict (restarts per source,
               then renumbered globally by stmtDB._finalize)

Sources (order matters — determines row order):
    1. self.llc.entity   — core entity block (ein, name, address, …)
    2. self.llc.F1065    — Form 1065-specific fields (preparer, business code, …)

After construction the instance is FROZEN; any attribute write raises
StmtImmutableError.

Timestamp of last change: 2026.04.24  (v0.2.4.1 — initial sanitised port)
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ledger.stmtDB import stmtDB


# Order matters — rows emitted in this order.
_PROFILE_SOURCES = ('entity', 'F1065')


class stmtProfile(stmtDB):
    '''
    Immutable LLC Profile statement constructed at instantiation time.

    Build inputs are pulled from the owning LLC object:
        self.llc.entity  → first block of rows
        self.llc.F1065   → second block of rows

    Both are plain dicts loaded by ``LLC._Profile()`` from
    ``Accts/llcProfile_<name>.json``.  stmtProfile does NOT re-parse the
    JSON itself — it is a pure shape-transformation over the dicts already
    materialised on the LLC.

    VIEW_BY_OPTIONS exposes the filter list ui/ modules may render; the
    same set is honored by ``_apply_view_by`` on ``load()``.
    '''

    DEFAULT_TBLID = "Profile"
    COLUMNS       = ['acctType', 'acct', 'acctSub', 'value']
    VIEW_BY_OPTIONS = ['All', 'entity', 'F1065']

    # ── Source-block row builder ─────────────────────────────────────────────

    def _profNspace(self, objNm: str, objDict: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        '''
        Transform one source dict (entity | F1065) into stmt row-dicts.

        acct     = "<objNm>.<fieldName>"
        acctSub  = "" (reserved for future sub-categorisation)
        value    = raw value from the source dict (coerced to str for JSON-safety)
        _lineNo  = 1-based position within the source dict
        _rowNm   = "Profile.<objNm>.<fieldName>" (honored by
                   stmtDB._default_rowNm so addressing is stable)
        '''
        if not objDict:
            return []
        rows: List[Dict[str, Any]] = []
        for i, fNm in enumerate(objDict.keys(), start=1):
            raw = objDict.get(fNm)
            rows.append(dict(
                acctType = 'Profile',
                acct     = f"{objNm}.{fNm}",
                acctSub  = '',
                value    = raw,
                _lineNo  = i,
                _rowNm   = f"Profile.{objNm}.{fNm}",
            ))
        return rows

    # ── stmtDB hook — ONLY place data is materialised ────────────────────────

    def _build(self, **kwargs) -> None:
        '''
        Populate the three slots stmtDB expects:
            self._tblID    : "Profile"
            self._columns  : ['acctType', 'acct', 'acctSub', 'value']
            self._rows     : rows from entity + F1065 (in that order)

        _finalize() (in stmtDB) will then:
            - add/overwrite _lineNo (1-based, global)
            - honour our pre-set _rowNm
            - build the cell index used by nSpaceMap() / get()
            - freeze the instance.
        '''
        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)

        rows: List[Dict[str, Any]] = []
        for src in _PROFILE_SOURCES:
            src_dict = getattr(self.llc, src, None) or {}
            rows.extend(self._profNspace(src, src_dict))
        self._rows = rows

        self._meta = {
            'sources':     list(_PROFILE_SOURCES),
            'entityCount': len(getattr(self.llc, 'entity', {}) or {}),
            'f1065Count':  len(getattr(self.llc, 'F1065',  {}) or {}),
            'profilePath': self._profile_fn(),
            'immutable':   True,
            'note': (
                'Row-addressable wrapper over llc.entity + llc.F1065. '
                'Data-source for IRS form header / preparer / business-code '
                'fields (see LLC._IRS_BINDINGS).  Replaces the legacy '
                'ui.llcIRSViewBase direct-dict reads.'
            ),
        }

    # ── Convenience — read-only field lookups ────────────────────────────────

    def _profile_fn(self) -> str:
        '''Best-effort path back to the source JSON (diagnostic only).'''
        try:
            from ledger import setup_paths
            import os as _os
            return _os.path.join(
                str(setup_paths.ACCTS_DIR),
                f"llcProfile_{self.llc.objName}.json",
            )
        except Exception:
            return ''

    def entity_value(self, fNm: str, default: Any = '') -> Any:
        '''Convenience wrapper — fetch entity.<fNm> via the cell index.'''
        return self.get(f"Profile.entity.{fNm}", "value", default)

    def f1065_value(self, fNm: str, default: Any = '') -> Any:
        '''Convenience wrapper — fetch F1065.<fNm> via the cell index.'''
        return self.get(f"Profile.F1065.{fNm}", "value", default)

    # ── Tax provisioning (mirrors the stmtOBJ_Tax loadFillDict contract) ─────

    BKNS_PROFILE_FN = 'bookNS_Profile.json'

    def _bkNS_profile_path(self) -> str:
        '''Resolve bookNS_Profile.json: IRS_FORMS_DIR first, then books/<yr>/Forms/.'''
        import os as _os
        try:
            from ledger import setup_paths as _sp
            if getattr(_sp, 'IRS_FORMS_DIR', None):
                return _os.path.join(str(_sp.IRS_FORMS_DIR), self.BKNS_PROFILE_FN)
        except Exception:
            pass
        try:
            top  = _os.path.expanduser(str(getattr(self.llc, 'TOP', '') or ''))
            acct = getattr(self.llc, 'dirAccounting', '') or ''
            yr   = (getattr(self.llc, 'YEAR', None)
                    or getattr(self.llc, 'yr', None))
            yr   = str(int(yr)) if yr else ''
            if yr:
                return _os.path.join(top, acct, yr, 'Forms', self.BKNS_PROFILE_FN)
            return _os.path.join(top, acct, self.BKNS_PROFILE_FN)
        except Exception:
            return ''

    def _bkNS_path(self) -> str:
        '''Alias for BookToIRS diagnostics compatibility.'''
        return self._bkNS_profile_path()

    def _bkNS_profile_load(self) -> Dict[str, Any]:
        import os as _os, json as _json
        fn = self._bkNS_profile_path()
        if not fn or not _os.path.exists(fn):
            return {}
        try:
            with open(fn, 'r') as fio:
                return _json.load(fio)
        except Exception as err:                            # pragma: no cover
            print(f"stmtProfile.loadFillDict: could not load {fn}: {err}")
            return {}

    # Sentinel emitted for fids that should toggle a /Btn ON in the FILL
    # PDF.  Mirrors irsForm.CHECK_SENTINEL — kept as a string constant so
    # ledger/ has no irs/ import dependency.
    CHECK_SENTINEL = 'CHECK'

    def loadFillDict(self, formNm: str) -> Dict[str, Any]:
        '''
        Return ``{normalized_fid: fval}`` for the requested IRS form section.

        Same v0.3 contract as ``stmtGL_Tax.loadFillDict``:
          * fids are normalized to zero-padded ``F###``;
          * UAS paths starting with ``Cplx`` -> fval = literal 'Complex';
          * Profile.<...> UAS paths are resolved against this immutable
            stmtProfile cell index;
          * any other unresolved entry -> fval = None (BLANK, not Complex).

        Plus, for ``Form1065`` only:
          * the ``Profile.F1065.chk`` list (in llcProfile_<llc>.json) is
            interpreted as fid numbers whose AcroForm /Btn checkbox should
            be toggled ON.  Each integer ``n`` in that list becomes
            ``F<nnn>: 'CHECK'`` in the returned dict (the sentinel is
            understood by ``irsForm.saveFILL_FromDF``).
          * Existing entries authored in bookNS_Profile.json are preserved;
            chk entries only fill *unmapped* fids — they will not overwrite
            an explicit text mapping.
        '''
        import re
        bkNS = self._bkNS_profile_load()
        out: Dict[str, Any] = {}
        mappings = bkNS.get(formNm, []) or []
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
            if isinstance(acct, str) and acct.startswith('Profile.'):
                try:
                    fval = self.get(acct, 'value', None)
                except Exception:
                    fval = None
            else:
                fval = None
            out[fid] = fval

        # ── chk array → CHECK sentinels (Form1065 only) ─────────────────
        if str(formNm) == 'Form1065':
            try:
                chk = self.f1065_value('chk', None)
            except Exception:
                chk = None
            if isinstance(chk, (list, tuple)):
                for n in chk:
                    try:
                        idx = int(n)
                    except Exception:
                        continue
                    if idx <= 0:
                        continue
                    fid = self._normalizeFid(idx)
                    if not fid:
                        continue
                    # Don't clobber an already-mapped fid (text mapping wins).
                    cur = out.get(fid, None)
                    if cur is None or cur == '':
                        out[fid] = self.CHECK_SENTINEL
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

    # ── ViewBy filter (used by ui/ layer) ────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Return immutable-safe row copies, optionally filtered by source.

        view_by ∈ VIEW_BY_OPTIONS — "All" returns everything; "entity" or
        "F1065" restrict to rows whose acct prefix matches that source.
        Anything else behaves like "All" (quiet default).
        '''
        rows = [dict(r) for r in self._rows]
        if view_by in (None, '', 'All'):
            return rows
        if view_by not in _PROFILE_SOURCES:
            return rows
        prefix = f"{view_by}."
        return [r for r in rows if str(r.get('acct', '')).startswith(prefix)]
