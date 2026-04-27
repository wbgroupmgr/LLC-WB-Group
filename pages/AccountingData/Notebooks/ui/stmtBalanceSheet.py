'''
stmtBalanceSheet (ui wrapper) — zero data management; delegates to stmt/.

Per DataModelGuide § 3:  View Services hold no data construction/wrangling.
All BS data lives in the constructed, immutable ledger.stmtBalanceSheet object.

This module's only responsibilities:
  1. Pull the working-file GL records out of the session (eSession.oDict)
     via llcReportEngine, so we honour in-progress edits.
  2. Forward those records into ledger.stmtBalanceSheet(..., gl_records=…).
  3. Expose the same public surface the legacy UI used:
        load(view_by) / last_check() / stats() / meta() /
        list() / save() / save_object() / reset_from_object()

Because ledger.stmtBalanceSheet is immutable, bind_session() / load() both
construct a fresh stmt instance with the latest GL — there is no in-place
mutation of the constructed object.

Timestamp: 2026.04.19  (Phase 2 refactor — stmt/ data-object split)
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ui.llcReportEngine import llcReportEngine
from ledger.stmtBalanceSheet import stmtBalanceSheet as _stmtBalanceSheet


class stmtBalanceSheet:
    '''
    UI-side Balance Sheet wrapper.

    Data lives in a ledger.stmtBalanceSheet (immutable).  Every load() with a
    fresh view_by builds a new stmt instance so we always reflect the
    current working-file state.
    '''

    # Re-exported so existing view code can introspect it.
    VIEW_BY_OPTIONS = _stmtBalanceSheet.VIEW_BY_OPTIONS

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt:  Optional[_stmtBalanceSheet] = None
        self._check: Dict[str, Any] = {'balanced': None}

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt    = None
        self._check   = {'balanced': None}

    def object_name(self) -> str:
        return self.__class__.__name__

    def _wk_fn(self, name: str) -> Optional[str]:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return None
        tObj = wk.o
        return tObj.FN() if tObj else None

    # ── Public interface (unchanged surface) ──────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''Build a fresh immutable stmt and return its rows.'''
        gl_records = self.engine.getGLList(resolve_dups=True, force=True)
        self._stmt = _stmtBalanceSheet(
            self.eSession.llc,
            view_by=view_by,
            gl_records=gl_records,
        )
        self._check = self._stmt.last_check()
        return self._stmt.load()

    def last_check(self) -> Dict[str, Any]:
        return dict(self._check) if self._check else {}

    def stats(self) -> Dict[str, Any]:
        # Ensure at least one load() has populated the stmt.
        if self._stmt is None:
            self.load()
        return self._stmt.stats()

    def meta(self) -> Dict[str, Any]:
        # Keep the legacy UI meta() shape so the existing template renders.
        return {
            'objectName': self.object_name(),
            'sources': {
                'llcExpRev':      self._wk_fn('llcExpRev'),
                'llcAssets':      self._wk_fn('llcAssets'),
                'llcPayables':    self._wk_fn('llcPayables'),
                'llcReceivables': self._wk_fn('llcReceivables'),
            },
            'note': 'Read-only. Double-entry GL. Assets = Liabilities + Equity check applied.',
            'tblID': _stmtBalanceSheet.DEFAULT_TBLID,
            'backend': 'ledger.stmtBalanceSheet',
        }

    # ── Legacy pass-throughs (load-on-demand) ────────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        '''BS is constructed/immutable — save() just re-derives rows.'''
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()

    # ── New accessors exposing the underlying stmt ───────────────────────────

    def stmt(self) -> Optional[_stmtBalanceSheet]:
        '''Return the underlying immutable ledger.stmtBalanceSheet (may be None).'''
        return self._stmt

    def nSpaceMap(self):
        if self._stmt is None:
            self.load()
        return self._stmt.nSpaceMap() if self._stmt else {}

    def to_DF(self):
        if self._stmt is None:
            self.load()
        return self._stmt.to_DF() if self._stmt else None
