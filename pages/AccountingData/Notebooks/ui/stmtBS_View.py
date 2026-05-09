'''
ui.stmtBS_View — v0.3 UI wrapper around ledger.stmtBS.stmtBS_View.

Per docs/LLC_stmtDesign.md "Design Decision v0.3":  the v0.3
``stmtBS_View`` exposes a chainable pipeline (AggBy → ViewBy → GroupBy →
SortBy → load) plus a ``view(view_by)`` convenience wrapper.  This module
is a thin UI bridge that feeds the existing ``financial_view.html``
template with the same single-frame surface as the legacy
``ui.stmtBalanceSheet`` — so no template change is required.

Per DataModelGuide § 3 the wrapper holds no data — every load() builds a
fresh immutable ``ledger.stmtBS.stmtBS_View`` and walks its pipeline.

Differences vs the legacy ``ui.stmtBalanceSheet`` wrapper:
  * v0.2 took ``view_by`` at construction time (filter baked in).  v0.3
    constructs once with the unfiltered aggregated row set and applies
    ``view_by`` per-call via the pipeline.
  * Same public surface — ``load(view_by)`` returns rows, ``last_check()``
    returns the accounting-equation dict, ``stats()`` and ``meta()``
    unchanged.

Timestamp: 2026.04.27 — v0.3.BS.UI
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ui.llcReportEngine import llcReportEngine
from ledger.stmtBS import stmtBS_View as _stmtBS_View


class stmtBS_View:
    '''
    UI-side v0.3 Balance Sheet wrapper.

    Holds a fresh immutable ``ledger.stmtBS.stmtBS_View`` (rebuilt only
    when ``bind_session()`` is called or working-file edits invalidate
    the cache).
    '''

    VIEW_BY_OPTIONS = list(_stmtBS_View.VIEW_BY_OPTIONS)

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt:  Optional[_stmtBS_View] = None
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

    # ── Underlying v0.3 stmt (rebuilt lazily) ────────────────────────────

    def _ensure_stmt(self) -> _stmtBS_View:
        if self._stmt is None:
            gl_records = self.engine.getGLList(resolve_dups=True, force=True)
            self._stmt = _stmtBS_View(
                self.eSession.llc,
                gl_records=gl_records,
            )
            self._check = self._stmt.last_check()
        return self._stmt

    def stmt(self) -> Optional[_stmtBS_View]:
        return self._stmt

    # ── Public surface (same as v0.2) ────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Pipeline:
            AggBy().ViewBy(view_by).SortBy(['acctType','acct','acctSub'])
                   .WithTotals(True).load()
        '''
        self._stmt = None   # always rebuild from live GL on each explicit load
        s = self._ensure_stmt()
        rows = s.view(view_by=view_by, with_totals=True)
        # Refresh cached check (reflects this stmt instance).
        self._check = s.last_check()
        return rows

    def last_check(self) -> Dict[str, Any]:
        return dict(self._check) if self._check else {}

    def stats(self) -> Dict[str, Any]:
        return self._ensure_stmt().stats()

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'sources': {
                'llcExpRev':      self._wk_fn('llcExpRev'),
                'llcAssets':      self._wk_fn('llcAssets'),
                'llcPayables':    self._wk_fn('llcPayables'),
                'llcReceivables': self._wk_fn('llcReceivables'),
            },
            'note': (
                'Read-only.  v0.3 stmtBS_View — pipeline-based BS viewer. '
                'Sourced from v0.3 stmtGL (COA-seeded).  '
                'Assets = Liabilities + Equity check applied.  '
                'No save() (v0.3 contract); use to_json().'
            ),
            'tblID':   'BalanceSheet',
            'backend': 'ledger.stmtBS.stmtBS_View',
            'version': 'v0.3',
        }

    # ── Legacy pass-throughs (load-on-demand) ────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        '''v0.3 BS has no save() — re-derive rows on demand.'''
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        self._stmt = None
        return self.load()

    # ── Optional accessors ───────────────────────────────────────────────

    def to_DF(self):
        s = self._ensure_stmt()
        try:
            return s.to_DF()
        except Exception:
            return None

    def to_json(self, indent: int = 2) -> str:
        return self._ensure_stmt().to_json(indent=indent)

    def taxAggregates(self) -> Dict[str, float]:
        return self._ensure_stmt().taxAggregates()

    def nSpaceMap(self):
        '''
        Legacy stmtDB cell-index nSpaceMap (NOT the v0.3 IRS-form
        nSpaceMap — that one lives on stmtBS_Tax).  Kept for v0.2-era
        callers that walk the cell index.
        '''
        s = self._ensure_stmt()
        try:
            return s.nSpaceMap()
        except Exception:
            return {}
