'''
ui.stmtGL_View — v0.3 UI wrapper around ledger.stmtGL.stmtGL_View.

Per docs/LLC_stmtDesign.md "Design Decision v0.3":  the v0.3
``stmtGL_View`` exposes a chainable pipeline (AggBy → ViewBy → GroupBy →
SortBy → load) and convenience wrappers (``view`` / ``trial_balance``).
This module is a thin UI bridge that feeds the existing 2-frame GL page
(``templates/general_ledger_view.html``) with the same Jinja-ready
``frames()`` dict as v0.2 — so no template change is required.

    ┌──────────────────────────────────────────────┐
    │ Frame 1 — Trial Balance (aggregated)          │
    │   acctType | acct | Debit | Credit | Balance  │
    ├──────────────────────────────────────────────┤
    │ Frame 2 — Transaction Records (details)       │
    │   Status | dt | acctType | acct | ...         │
    └──────────────────────────────────────────────┘

Per DataModelGuide § 3 the wrapper holds no data — every call builds a
fresh immutable ``ledger.stmtGL.stmtGL_View`` and walks its pipeline.

Differences vs the legacy ``ui.stmtGeneralLedger`` wrapper:
  * v0.2 used ``ledger.stmtGeneralLedger`` + ``stmtTrialBalance`` (two
    independent constructed-data classes).  v0.3 collapses those into a
    single ``stmtGL_View`` whose ``trial_balance()`` is a pipeline stage,
    not a sibling stmt object.
  * The wrapper exposes the same ``frames(view_by)`` contract; the Flask
    route does not need to change.

Timestamp: 2026.04.27 — v0.3.GL.UI
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ui.llcReportEngine import llcReportEngine
from ledger.stmtGL import stmtGL_View as _stmtGL_View


class stmtGL_View:
    '''
    UI-side v0.3 General Ledger wrapper.

    Data lives in a fresh immutable ``ledger.stmtGL.stmtGL_View``.  Every
    ``frames()``/``load()``/``tb_rows()`` call rebuilds the underlying
    stmt with the with-dups GL pulled from the working session, then
    walks the pipeline for the requested ``view_by``.
    '''

    # ── Column contracts (re-exported for llcMgmt column discovery) ──────
    VIEW_COLUMNS    = ['Status', 'dt', 'acctType', 'acct', 'acctMinor', 'propNm',
                       'aType', 'amt', 'desc', 'acctSub', 'refDB']
    TB_COLUMNS      = ['acctType', 'acct', 'acctMinor', 'acctSub', 'propNm', 'Debit', 'Credit', 'Balance']
    VIEW_BY_OPTIONS = list(_stmtGL_View.VIEW_BY_OPTIONS)

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        # Cache of the most recent stmt + view_by so follow-up accessors
        # (stats / nSpaceMap / to_DF) do not re-merge the GL.
        self._stmt: Optional[_stmtGL_View] = None
        self._last_view_by: str = 'All'

    # ── Lifecycle ────────────────────────────────────────────────────────

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt    = None
        self._last_view_by = 'All'

    def object_name(self) -> str:
        return self.__class__.__name__

    def _wk_fn(self, name: str) -> Optional[str]:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return None
        tObj = wk.o
        return tObj.FN() if tObj else None

    # ── Underlying v0.3 stmt (rebuilt lazily per view_by) ────────────────

    def _ensure_stmt(self) -> _stmtGL_View:
        '''Build (or reuse) a fresh stmtGL_View from the working-file GL.'''
        if self._stmt is None:
            merged = self.engine.getGLListWithDups()
            self._stmt = _stmtGL_View(
                self.eSession.llc,
                gl_records=merged,
                resolve_dups=False,
            )
        return self._stmt

    def stmt(self) -> Optional[_stmtGL_View]:
        return self._stmt

    # ── Transaction frame (Frame 2) ──────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Pipeline: AggBy().ViewBy(view_by, include_coa_seed=False).load().
        Returns flat transaction rows under the selected view_by.
        '''
        self._stmt = None   # force rebuild from real DB on every explicit load
        s = self._ensure_stmt()
        self._last_view_by = view_by
        return s.view(view_by=view_by, include_coa_seed=False)

    def stats(self) -> Dict[str, Any]:
        '''Stats are independent of view_by — see stmtGL_View.stats().'''
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
                'Read-only.  v0.3 stmtGL_View — pipeline-based GL viewer. '
                'Trial Balance frame is the same pipeline with a GroupBy '
                'stage.  No save() (v0.3 contract); use to_json().'
            ),
            'tblID':    'GeneralLedger',
            'backend':  'ledger.stmtGL.stmtGL_View',
            'version':  'v0.3',
        }

    # ── Trial Balance frame (Frame 1) ────────────────────────────────────

    def tb_rows(self, view_by: str = 'All',
                with_totals: bool = True) -> List[Dict[str, Any]]:
        '''
        Pipeline:
            AggBy().ViewBy(view_by, include_coa_seed=True)
                   .GroupBy(['acctType','acct','acctSub'])
                   .WithTotals(with_totals)
                   .SortBy(['acctType','acct']).load()
        '''
        s = self._ensure_stmt()
        return s.trial_balance(view_by=view_by, with_totals=with_totals)

    def tb_totals(self, view_by: str = 'All') -> Dict[str, float]:
        '''
        Sum Debit / Credit / Balance over the body rows (skipping any
        TOTAL row appended by the pipeline).  Provides Diff for parity
        with v0.2 callers.
        '''
        rows = [r for r in self.tb_rows(view_by=view_by, with_totals=False)
                if r.get('acctType') != 'TOTAL']
        td = sum(float(r.get('Debit')   or 0) for r in rows)
        tc = sum(float(r.get('Credit')  or 0) for r in rows)
        tb = sum(float(r.get('Balance') or 0) for r in rows)
        return {
            'Debit':   round(td, 2),
            'Credit':  round(tc, 2),
            'Diff':    round(td - tc, 2),
            'Balance': round(tb, 2),
        }

    def tb_is_balanced(self, view_by: str = 'All',
                       tolerance: float = 0.01) -> bool:
        totals = self.tb_totals(view_by=view_by)
        return abs(totals['Debit'] - totals['Credit']) < tolerance

    # ── 2-frame bundle (Jinja-ready) ─────────────────────────────────────

    def frames(self, view_by: str = 'All') -> Dict[str, Any]:
        '''
        Build BOTH frames under the same ``view_by`` and return the
        legacy-compatible bundle.  No template change required.
        '''
        tx_rows = self.load(view_by=view_by)
        tb_rows = self.tb_rows(view_by=view_by, with_totals=True)
        # All view: aggregate by (acct, acctMinor) to get group Balance and Count,
        # then apply keep rules:
        #   Balance != 0              → KEEP
        #   Balance == 0, Count > 1   → KEEP
        #   Balance == 0, Count < 2   → DISCARD
        if view_by == 'All':
            from collections import defaultdict
            grp_bal = defaultdict(float)
            grp_cnt = defaultdict(int)
            for r in tb_rows:
                if r.get('acctType') == 'TOTAL':
                    continue
                key = (r.get('acct', ''), r.get('acctMinor', ''))
                grp_bal[key] += float(r.get('Balance') or 0)
                grp_cnt[key] += 1
            def _keep(r):
                if r.get('acctType') == 'TOTAL':
                    return True
                key = (r.get('acct', ''), r.get('acctMinor', ''))
                return grp_bal[key] != 0 or grp_cnt[key] > 1
            tb_rows = [r for r in tb_rows if _keep(r)]
        return {
            'view_by':         view_by,
            'view_by_options': list(self.VIEW_BY_OPTIONS),
            'tb': {
                'rows':        tb_rows,
                'columns':     list(self.TB_COLUMNS),
                'totals':      self.tb_totals(view_by=view_by),
                'is_balanced': self.tb_is_balanced(view_by=view_by),
            },
            'tx': {
                'rows':    tx_rows,
                'columns': list(self.VIEW_COLUMNS),
                'summary': {},  # v0.3 has no last_summary; reserved for parity.
                'stats':   self.stats(),
            },
            'meta': self.meta(),
        }

    # ── Legacy pass-throughs (load-on-demand) ────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        '''v0.3 GL has no save() — re-derive rows on demand.'''
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
        s = self._ensure_stmt()
        return s.to_json(indent=indent)

    def nSpaceMap(self):
        return self._ensure_stmt().nSpaceMap()

    def last_summary(self) -> Dict[str, Any]:
        '''Reserved for parity with v0.2; no per-load summary in v0.3.'''
        return {}
