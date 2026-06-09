'''
llcForm1065 — IRS Form 1065 (U.S. Return of Partnership Income).

ProjectLevel3 v0.2.4.7 — PDF-embed restructure
----------------------------------------------
The view no longer reconstructs row-by-row from ``Form1065.nSpaceMap()``.
Instead it embeds the canonical filled artifact ``Form1065_FILL.pdf`` produced
by ``irs.Form1065.saveFILL()``.  This eliminates *all* data wrangling from
the ui/ layer for tax forms — the FILL.pdf is now the single source of truth
for what the user sees, exactly mirroring what gets filed with the IRS.

Responsibilities
----------------
  * ``pdf_path()``   → absolute Path to ``Forms_IRS/Form1065_FILL.pdf``
  * ``stats()``      → top-level chips (Gross Income / Expense / NI / Assets),
                       sourced directly from ``ledger.stmtIncomeStmt`` +
                       ``ledger.stmtBalanceSheet``.  No data construction —
                       just delegated reads.
  * ``meta()``       → small descriptor surfaced by the template footer.

Anything else (row-level fillDict introspection, publish filtering) now lives
in ``tests/testIrsFillPDF.py`` and the upstream IRS pipeline.

Timestamp of last change: 2026.04.24  (v0.2.4.7 — PDF-embed restructure)
'''

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return default


# ════════════════════════════════════════════════════════════════════════════

class llcForm1065:
    '''
    Form 1065 PDF-embed view — pure UI glue.

    The page renders an inline ``<iframe>`` of ``Form1065_FILL.pdf`` plus a
    small stat-chip bar.  No row tables, no nSpaceMap, no row-by-row
    publish filtering at the view layer.
    '''

    # The form_id used by the /forms/<form_id>.pdf binary route in llcMgmt.
    FORM_ID = "Form1065"

    def __init__(self, eSession):
        self.eSession = eSession
        self._profile = None

    # ── Session lifecycle ───────────────────────────────────────────────────

    def bind_session(self, eSession) -> None:
        self.eSession = eSession
        self._profile = None

    def object_name(self) -> str:
        return self.__class__.__name__

    # ── Ledger-service accessors ────────────────────────────────────────────

    def _llc(self):
        return getattr(self.eSession, 'llc', None)

    def _stmt_profile(self):
        if self._profile is not None:
            return self._profile
        llc = self._llc()
        if llc is None:
            return None
        try:
            from ledger.stmtProfile import stmtProfile
        except ImportError:
            return None
        try:
            self._profile = stmtProfile(llc)
        except Exception:
            self._profile = None
        return self._profile

    # ── Public interface ────────────────────────────────────────────────────

    def pdf_path(self) -> Optional[Path]:
        '''Absolute path to Forms/<FORM_ID>_FILL.pdf via eSession.paths.'''
        try:
            irs_dir = Path(self.eSession.paths.irs_forms_dir)
        except Exception:
            return None
        p = irs_dir / f"{self.FORM_ID}_FILL.pdf"
        return p if p.exists() else None

    def stats(self) -> Dict[str, Any]:
        '''
        Top-level stat chips — Gross Income / Total Expense / Net Income /
        Total Assets — pulled directly from ``ledger.stmtIncomeStmt`` and
        ``ledger.stmtBalanceSheet``.
        '''
        out = {
            'Gross Income':  0.0,
            'Total Expense': 0.0,
            'Net Income':    0.0,
            'Total Assets':  0.0,
        }
        llc = self._llc()
        if llc is None:
            return out

        try:
            from ledger.stmtIS import stmtIS  as stmtIncomeStmt
            from ledger.stmtBS import stmtBS  as stmtBalanceSheet
        except ImportError:
            return out

        try:
            _is = stmtIncomeStmt(llc)
            for r in _is.load():
                at = str(r.get('acctType', ''))
                bal = _as_float(r.get('Balance'))
                if at == 'Income':
                    # Income rows store Balance = Debit − Credit (negative);
                    # flip to positive for the chip.
                    out['Gross Income']  += -bal
                elif at == 'Expense':
                    out['Total Expense'] += bal
            out['Net Income'] = _as_float(_is.get('TOTAL', 'Balance'))
        except Exception:
            pass

        try:
            _bs = stmtBalanceSheet(llc)
            for r in _bs.load():
                if str(r.get('acctType', '')) == 'Asset':
                    out['Total Assets'] += _as_float(r.get('Balance'))
        except Exception:
            pass

        return {k: round(v, 2) for k, v in out.items()}

    def meta(self) -> Dict[str, Any]:
        prof = self._stmt_profile()
        pdf  = self.pdf_path()
        return {
            'objectName':       self.object_name(),
            'formId':           self.FORM_ID,
            'agent_enabled':    True,
            'agent_key':        'form1065',
            'agent_strip_label': 'Form 1065 — Section Status',
            'pdfPath':    str(pdf) if pdf else '',
            'pdfPresent': pdf is not None,
            'sources': {
                'pdf':     'irs.Form1065.saveFILL() → Forms_IRS/Form1065_FILL.pdf',
                'stats':   'ledger.stmtIncomeStmt + ledger.stmtBalanceSheet',
                'profile': 'ledger.stmtProfile' if prof else None,
            },
            'profile': prof.meta() if prof else {},
            'note': (
                'IRS Form 1065 (2024). The view embeds the canonical '
                'Form1065_FILL.pdf produced by irs.Form1065.saveFILL(); the '
                'stat chips are read straight from the ledger stmt* layer. '
                'Consult a qualified tax professional before filing.'
            ),
        }

    # ── Legacy pass-throughs (match ui/ convention) ─────────────────────────

    def load(self, view_by: str = 'All'):
        '''No-op for the PDF-embed view; kept so api/cmd?cmd=load still works.'''
        return []

    def list(self):
        return self.load()

    def save(self, data: Any = None):
        return self.load()

    def save_object(self, data: Any = None):
        return self.load()

    def reset_from_object(self):
        return self.load()
