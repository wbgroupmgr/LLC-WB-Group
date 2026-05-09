'''
ui.stmtIS_View — v0.3 UI wrapper around ledger.stmtIS.stmtIS_View.

Per docs/LLC_stmtDesign.md "Design Decision v0.3":  the v0.3
``stmtIS_View`` exposes a chainable pipeline (AggBy → ViewBy → GroupBy →
SortBy → load) plus convenience wrappers ``view(view_by)`` and
``per_member(owners)``.  This module is a thin UI bridge that feeds the
existing IS template (``financial_view.html`` for the single-frame view,
``is_member_view.html`` for the per-member view) — so no template change
is required.

Per DataModelGuide § 3 the wrapper holds no data — every load() builds a
fresh immutable ``ledger.stmtIS.stmtIS_View`` and walks its pipeline.

Differences vs the legacy ``ui.stmtIncomeStmt`` wrapper:
  * v0.2 took ``view_by`` at construction time.  v0.3 constructs once
    with the unfiltered aggregated row set and applies ``view_by`` (and
    the per-member propagation) per-call via the pipeline.
  * Same public surface — ``load(view_by)`` returns rows,
    ``load_per_member()`` returns (rows, owner_names, summary),
    ``last_summary()`` and ``stats()`` unchanged.

Timestamp: 2026.04.27 — v0.3.IS.UI
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ui.llcReportEngine import llcReportEngine
from ledger.stmtIS import stmtIS_View as _stmtIS_View


class stmtIS_View:
    '''
    UI-side v0.3 Income Statement wrapper.

    Holds a fresh immutable ``ledger.stmtIS.stmtIS_View``; rebuilt only
    when ``bind_session()`` / ``reset_from_object()`` is called.
    '''

    VIEW_BY_OPTIONS = list(_stmtIS_View.VIEW_BY_OPTIONS)

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt:    Optional[_stmtIS_View] = None
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

    # ── Underlying v0.3 stmt (rebuilt lazily) ────────────────────────────

    def _ensure_stmt(self) -> _stmtIS_View:
        if self._stmt is None:
            gl_records = self.engine.getGLList(resolve_dups=True, force=True)
            self._stmt = _stmtIS_View(
                self.eSession.llc,
                gl_records=gl_records,
            )
            self._summary = self._stmt.last_summary()
        return self._stmt

    def stmt(self) -> Optional[_stmtIS_View]:
        return self._stmt

    # ── Public surface (same as v0.2) ────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Pipeline:
            AggBy().ViewBy(view_by).SortBy(['acctType','acct','acctSub'])
                   .WithTotals(True).load()

        ``view_by='PerMember'`` returns an empty list — use
        ``load_per_member()`` for the per-owner allocation layout.
        '''
        if view_by == 'PerMember':
            return []
        s = self._ensure_stmt()
        rows = s.view(view_by=view_by, with_totals=True)
        self._summary = s.last_summary()
        return rows

    def load_by_property(self,
                         view_by: str = 'ByProperty'
                         ) -> 'Tuple[List[Dict], List[str], Dict]':
        '''
        Property-unstacked IS: propNm values become column headers.

        Returns (rows, prop_names, summary) — same shape as load_per_member().
        Each row has Balance + one column per unique propNm.
        '''
        from ledger.stmtIS import _Pipeline
        s = self._ensure_stmt()
        gl_records = getattr(s, '_gl_records', []) or []
        rows, prop_names = _Pipeline._unstack_by_property(gl_records, view_by)
        summary = s.last_summary()
        self._summary = summary
        return rows, prop_names, summary

    def load_per_member(self
                        ) -> Tuple[List[Dict[str, Any]], List[str],
                                   Dict[str, Any]]:
        '''
        Per-owner Income Statement (Sch_K_1 row schema).

        Returns (rows, owner_names, summary) — same shape the legacy UI
        expected.  Owners come from ``llcReportEngine.load_owners()``.
        '''
        s = self._ensure_stmt()
        owners = self.engine.load_owners()
        rows, owner_names, summary = s.per_member(owners=owners)
        self._summary = summary
        return rows, owner_names, summary

    def last_summary(self) -> Dict[str, Any]:
        return dict(self._summary) if self._summary else {}

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
                'Read-only.  v0.3 stmtIS_View — pipeline-based IS viewer. '
                'Sourced from v0.3 stmtGL (COA-seeded).  Income / Expense '
                'groups; Balance row carries Net Income.  '
                'No save() (v0.3 contract); use to_json().'
            ),
            'tblID':   'IncomeStmt',
            'backend': 'ledger.stmtIS.stmtIS_View',
            'version': 'v0.3',
        }

    # ── Legacy pass-throughs (load-on-demand) ────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        '''v0.3 IS has no save() — re-derive rows on demand.'''
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
        nSpaceMap — that one lives on stmtIS_Tax).  Kept for v0.2-era
        callers.
        '''
        s = self._ensure_stmt()
        try:
            return s.nSpaceMap()
        except Exception:
            return {}
