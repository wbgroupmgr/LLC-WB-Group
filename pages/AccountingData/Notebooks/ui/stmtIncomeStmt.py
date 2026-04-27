'''
stmtIncomeStmt (ui wrapper) — zero data management; delegates to stmt/.

Per DataModelGuide § 3:  View Services hold no data construction/wrangling.
All IS data lives in the constructed, immutable ledger.stmtIncomeStmt object.

This module's only responsibilities:
  1. Pull the working-file GL records out of the session (eSession.oDict)
     via llcReportEngine, so we honour in-progress edits.
  2. Forward those records into ledger.stmtIncomeStmt(..., gl_records=…).
  3. Expose the same public surface the legacy UI used:
        load(view_by) / load_per_member() / last_summary() / stats() /
        meta() / list() / save() / save_object() / reset_from_object()

Because ledger.stmtIncomeStmt is immutable, bind_session() / load() both
construct a fresh stmt instance with the latest GL — there is no in-place
mutation of the constructed object.

Timestamp: 2026.04.19  (Phase 2 refactor — stmt/ data-object split)
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ui.llcReportEngine import llcReportEngine
from ledger.stmtIncomeStmt import stmtIncomeStmt as _stmtIncomeStmt


class stmtIncomeStmt:
    '''
    UI-side Income Statement wrapper.

    Data lives in a ledger.stmtIncomeStmt (immutable).  Every load() with a
    fresh view_by builds a new stmt instance so we always reflect the
    current working-file state.
    '''

    # Re-exported so existing view code can introspect it.
    VIEW_BY_OPTIONS = _stmtIncomeStmt.VIEW_BY_OPTIONS

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt:    Optional[_stmtIncomeStmt] = None
        self._summary: Dict[str, Any] = {}

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt    = None
        self._summary = {}

    def object_name(self) -> str:
        return self.__class__.__name__

    def _wk_fn(self, name: str) -> Optional[str]:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return None
        tObj = wk.o
        return tObj.FN() if tObj else None

    # ── Public interface (unchanged surface) ─────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Build a fresh immutable stmt and return its rows.  When
        view_by == 'PerMember', returns an empty list — use load_per_member()
        for the per-owner allocation layout (different row schema).
        '''
        if view_by == 'PerMember':
            self._summary = {}
            return []

        gl_records = self.engine.getGLList(resolve_dups=True, force=True)
        self._stmt = _stmtIncomeStmt(
            self.eSession.llc,
            view_by=view_by,
            gl_records=gl_records,
        )
        self._summary = self._stmt.last_summary()
        return self._stmt.load()

    def load_per_member(self) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
        '''
        Return IS with per-owner allocation columns.

        Returns (rows, owner_names, summary) — same shape the legacy UI
        expected.  Owners come from llcReportEngine.load_owners() so the
        session's llcOwners file drives the allocation.
        '''
        gl_records = self.engine.getGLList(resolve_dups=True, force=True)
        owners     = self.engine.load_owners()
        self._stmt = _stmtIncomeStmt(
            self.eSession.llc,
            view_by='PerMember',
            gl_records=gl_records,
            owners=owners,
        )
        rows, owner_names, summary = self._stmt.build_per_member(owners=owners)
        self._summary = summary
        return rows, owner_names, summary

    def last_summary(self) -> Dict[str, Any]:
        return dict(self._summary) if self._summary else {}

    def stats(self) -> Dict[str, Any]:
        # Ensure at least one load() has populated the stmt.
        if self._stmt is None:
            self.load()
        # If the current stmt is a PerMember build, stats() may read 0 rows;
        # fall back to a canonical All build just for the stats panel.
        try:
            return self._stmt.stats()
        except Exception:
            self.load('All')
            return self._stmt.stats() if self._stmt else {}

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
            'note': 'Read-only. Double-entry GL. Income / Expense groups. Balance = Net Income.',
            'tblID': _stmtIncomeStmt.DEFAULT_TBLID,
            'backend': 'ledger.stmtIncomeStmt',
        }

    # ── Legacy pass-throughs (load-on-demand) ────────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        '''IS is constructed/immutable — save() just re-derives rows.'''
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()

    # ── New accessors exposing the underlying stmt ───────────────────────────

    def stmt(self) -> Optional[_stmtIncomeStmt]:
        '''Return the underlying immutable ledger.stmtIncomeStmt (may be None).'''
        return self._stmt

    def nSpaceMap(self):
        if self._stmt is None:
            self.load()
        return self._stmt.nSpaceMap() if self._stmt else {}

    def to_DF(self):
        if self._stmt is None:
            self.load()
        return self._stmt.to_DF() if self._stmt else None
