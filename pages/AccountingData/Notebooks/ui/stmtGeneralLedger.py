'''
stmtGeneralLedger (ui wrapper) — zero data management; delegates to ledger/.

Per DataModelGuide § 3:  View Services hold no data construction/wrangling.
All GL data lives in the constructed, immutable ledger.stmtGeneralLedger
object, and the Trial Balance aggregation lives in
ledger.stmtGeneralLedger.stmtTrialBalance (sibling class in the same module).
This module is a thin UI bridge that feeds the 2-frame GL page:

    ┌──────────────────────────────────────────────┐
    │ Frame 1 — Trial Balance (aggregated)          │
    │   acctType | acct | Debit | Credit | Balance  │
    ├──────────────────────────────────────────────┤
    │ Frame 2 — Transaction Records (details)       │
    │   Status | dt | acctType | acct | ...         │
    └──────────────────────────────────────────────┘

Both frames honour the same ViewBy selection.  Responsibilities:
  1. Pull the working-file GL-with-dups list out of the session via
     llcReportEngine (so we honour in-progress edits AND keep cross-source
     duplicate flags).
  2. Forward into ledger.stmtGeneralLedger(view_by=…, gl_records=…) for the
     transaction frame, and into ledger.stmtTrialBalance(view_by=…, …) for
     the Trial Balance frame.
  3. Expose the legacy single-frame surface (load / stats / meta / list /
     save / save_object / reset_from_object / bind_session) PLUS the new
     2-frame accessors (trial_balance / tb_rows / tb_totals / frames).

Because both stmt objects are immutable, every load()/tb_rows() call builds
a fresh stmt instance.

Timestamp: 2026.04.24  (v0.2.3.4 — 2-frame GL view, Flask/Jinja only)
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ui.llcReportEngine import llcReportEngine
from ledger.stmtGeneralLedger import (
    stmtGeneralLedger as _stmtGL,
    stmtTrialBalance as _stmtTB,
)


class stmtGeneralLedger:
    '''
    UI-side General Ledger wrapper.

    Data lives in two immutable ledger objects:
      * ledger.stmtGeneralLedger   — transaction-level GL rows
      * ledger.stmtTrialBalance    — aggregated trial-balance rows

    Every load() / tb_rows() / frames() call builds fresh instances with the
    requested view_by and returns their rows.  The wrapper caches the most
    recent stmt objects so follow-up accessor calls (stats, meta, to_DF,
    is_balanced, etc.) do not re-execute the merge/aggregation.
    '''

    # ── Column contracts (re-exported for llcMgmt column discovery) ──────
    VIEW_COLUMNS    = ['Status', 'dt', 'acctType', 'acct', 'aType', 'amt',
                       'desc', 'acctSub', 'refDB']
    TB_COLUMNS      = ['acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance']
    VIEW_BY_OPTIONS = list(_stmtGL.VIEW_BY_OPTIONS)

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        # Transaction-frame cache
        self._stmt:    Optional[_stmtGL] = None
        self._summary: Dict[str, Any] = {}
        # Trial-Balance-frame cache
        self._tb:      Optional[_stmtTB] = None
        # Last requested view_by (so Flask doesn't have to re-pass it when
        # it asks for the second frame)
        self._last_view_by: str = 'All'

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._stmt    = None
        self._tb      = None
        self._summary = {}
        self._last_view_by = 'All'

    def object_name(self) -> str:
        return self.__class__.__name__

    def _wk_fn(self, name: str) -> Optional[str]:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return None
        tObj = wk.o
        return tObj.FN() if tObj else None

    # ── Transaction frame (Frame 2) ──────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        '''
        Build a fresh immutable stmtGeneralLedger with the requested view_by
        and return its transaction rows.  We pre-compute the with-dups merged
        GL via the engine so the stmt never reloads the DB itself — honouring
        working-file edits.
        '''
        merged = self.engine.getGLListWithDups()
        self._stmt = _stmtGL(
            self.eSession.llc,
            view_by=view_by,
            gl_records=merged,
            resolve_dups=False,
        )
        self._summary = self._stmt.last_summary()
        self._last_view_by = view_by
        # Invalidate TB cache — it must be rebuilt under the same view_by.
        self._tb = None
        return self._stmt.load()

    def stats(self) -> Dict[str, Any]:
        # Stats always reflect the unfiltered GL — build an 'All' stmt.
        merged = self.engine.getGLListWithDups()
        stmt_all = _stmtGL(
            self.eSession.llc,
            view_by='All',
            gl_records=merged,
            resolve_dups=False,
        )
        return stmt_all.stats()

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
                'Read-only. Double-entry expanded GL built by merging '
                'llcAssets + llcExpRev + llcPayables + llcReceivables. '
                'Cross-source dups flagged ⚠ Dup. Trial Balance aggregates '
                'the same GL via ledger.stmtTrialBalance.'
            ),
            'tblID':    _stmtGL.DEFAULT_TBLID,
            'tb_tblID': _stmtTB.DEFAULT_TBLID,
            'backend':  'ledger.stmtGeneralLedger + stmtTrialBalance',
        }

    # ── Trial Balance frame (Frame 1) ────────────────────────────────────

    def trial_balance(self, view_by: str = 'All') -> _stmtTB:
        '''
        Build a fresh immutable stmtTrialBalance under the requested view_by
        and cache it.  Subsequent tb_rows() / tb_totals() / is_balanced()
        calls reuse the cached instance until view_by changes.
        '''
        if self._tb is None or view_by != self._last_view_by:
            self._tb = _stmtTB(self.eSession.llc, view_by=view_by)
            self._last_view_by = view_by
        return self._tb

    def tb_rows(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        return self.trial_balance(view_by=view_by).load()

    def tb_totals(self, view_by: str = 'All') -> Dict[str, float]:
        '''
        Return {'Debit', 'Credit', 'Balance', 'Diff'} under view_by.

        ``stmtTrialBalance.totals()`` returns Debit/Credit/Diff; we
        supplement with a Balance sum derived from the loaded rows so the
        template has a single, uniform totals dict to render.
        '''
        tb = self.trial_balance(view_by=view_by)
        try:
            base = dict(tb.totals())
        except AttributeError:
            base = {}
        rows = tb.load()
        base.setdefault('Debit',   sum(float(r.get('Debit')   or 0) for r in rows))
        base.setdefault('Credit',  sum(float(r.get('Credit')  or 0) for r in rows))
        base.setdefault('Diff',    base['Debit'] - base['Credit'])
        base['Balance'] = sum(float(r.get('Balance') or 0) for r in rows)
        return base

    def tb_is_balanced(self, view_by: str = 'All') -> bool:
        tb = self.trial_balance(view_by=view_by)
        try:
            return bool(tb.is_balanced())
        except AttributeError:
            totals = self.tb_totals(view_by=view_by)
            return abs(totals['Debit'] - totals['Credit']) < 0.01

    # ── 2-frame bundle (one call returns everything the template needs) ──

    def frames(self, view_by: str = 'All') -> Dict[str, Any]:
        '''
        Build BOTH frames under the same ``view_by`` in one pass and return
        a Jinja-ready bundle:

            {
              "view_by":          str,
              "view_by_options":  list[str],
              "tb": {
                "rows":       list[dict],
                "columns":    list[str],
                "totals":     {"Debit": ..., "Credit": ..., "Balance": ...},
                "is_balanced": bool,
              },
              "tx": {
                "rows":       list[dict],
                "columns":    list[str],
                "summary":    dict,
                "stats":      dict,
              },
              "meta":             dict,
            }

        The Flask route just passes this dict straight into Jinja.
        '''
        tx_rows = self.load(view_by=view_by)
        tb_rows = self.tb_rows(view_by=view_by)

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
                'summary': dict(self._summary) if self._summary else {},
                'stats':   self.stats(),
            },
            'meta': self.meta(),
        }

    # ── Legacy pass-throughs (load-on-demand) ────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        '''GL is constructed/immutable — save() just re-derives rows.'''
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()

    # ── New accessors exposing the underlying stmt objects ───────────────

    def stmt(self) -> Optional[_stmtGL]:
        '''Return the underlying immutable ledger.stmtGeneralLedger (may be None).'''
        return self._stmt

    def tb_stmt(self) -> Optional[_stmtTB]:
        '''Return the underlying immutable ledger.stmtTrialBalance (may be None).'''
        return self._tb

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
