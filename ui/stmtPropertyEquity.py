'''
stmtPropertyEquity (ui wrapper) — zero data management; delegates to stmt/.

Per DataModelGuide § 3:  View Services hold no data construction/wrangling.
All PE data lives in the constructed, immutable ledger.stmtPropertyEquity object.

This module's only responsibilities:
  1. Pull the working-file asset records and owner list out of the session
     (eSession.oDict / llcOwners file) via llcReportEngine, so we honour
     in-progress edits.
  2. Forward those inputs into ledger.stmtPropertyEquity(asset_records=…,
     owners=…).
  3. Expose the same public surface the legacy UI used:
        load(view_by) / stats() / meta() / list() / save() / save_object() /
        reset_from_object() / bind_session()

Because ledger.stmtPropertyEquity is immutable, bind_session() / load() both
construct a fresh stmt instance — there is no in-place mutation of the
constructed object.

Timestamp: 2026.04.19  (Phase 3 refactor — stmt/ data-object split)
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ui.llcReportEngine import llcReportEngine
from ledger.stmtPropertyEquity import stmtPropertyEquity as _stmtPropertyEquity


class stmtPropertyEquity:
    '''
    UI-side Property Equity wrapper.

    Data lives in a ledger.stmtPropertyEquity (immutable).  Every load() builds
    a new stmt instance so we always reflect the current working-file state.
    '''

    # Re-exported so existing view code can introspect it.
    VIEW_COLUMNS = ['prop_identity', 'acctSub_ext', 'desc', 'Debit', 'Credit',
                    'acctType', 'acct', 'Ledger']
    VIEW_BY_OPTIONS: List[str] = list(_stmtPropertyEquity.VIEW_BY_OPTIONS)

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt:    Optional[_stmtPropertyEquity] = None
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
        '''Build a fresh immutable stmt and return its rows.'''
        asset_list = self.engine._load_source('llcAssets')
        owners     = self.engine.load_owners()

        self._stmt = _stmtPropertyEquity(
            self.eSession.llc,
            view_by=view_by,
            asset_records=asset_list,
            owners=owners,
        )
        self._summary = self._stmt.last_summary()
        return self._stmt.load()

    def stats(self) -> Dict[str, Any]:
        if self._stmt is None:
            self.load()
        return self._stmt.stats() if self._stmt else {}

    def meta(self) -> Dict[str, Any]:
        # Keep the legacy UI meta() shape so the existing template renders.
        return {
            'objectName': self.object_name(),
            'sources': {
                'llcAssets': self._wk_fn('llcAssets'),
                'llcOwners': self._find_owners_fn(),
            },
            'note':    'Read-only. Per-property equity report from llcAssets.',
            'tblID':   _stmtPropertyEquity.DEFAULT_TBLID,
            'backend': 'ledger.stmtPropertyEquity',
        }

    def _find_owners_fn(self) -> Optional[str]:
        path = self.engine._find_owners_path()
        return str(path) if path else None

    # ── Legacy pass-throughs (load-on-demand) ────────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        '''PE is constructed/immutable — save() just re-derives rows.'''
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()

    # ── New accessors exposing the underlying stmt ───────────────────────────

    def stmt(self) -> Optional[_stmtPropertyEquity]:
        '''Return the underlying immutable ledger.stmtPropertyEquity (may be None).'''
        return self._stmt

    def last_summary(self) -> Dict[str, Any]:
        return dict(self._summary) if self._summary else {}

    def nSpaceMap(self):
        if self._stmt is None:
            self.load()
        return self._stmt.nSpaceMap() if self._stmt else {}

    def to_DF(self):
        if self._stmt is None:
            self.load()
        return self._stmt.to_DF() if self._stmt else None
