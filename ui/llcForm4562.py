'''
llcForm4562 — IRS Form 4562 (Depreciation and Amortization).

PDF-embed view — same architecture as ui.llcForm8825: the page renders
the canonical Form4562_FILL.pdf produced by irs.Form4562 + the BookToIRS
pipeline; stat chips read key figures from the ledger.

Form 4562 reports all MACRS depreciation for the LLC's rental properties.
For W&B Group the key line is Part III Line 19h (27.5-year residential
rental, MM convention, S/L method).  Line 22 (total depreciation) flows
into Form 1065 Line 16a and Form 8825 Line 14.

Timestamp of last change: 2026.05.12
'''
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return default


class llcForm4562:
    '''
    Form 4562 PDF-embed view — pure UI glue.

    Renders an inline <iframe> of Form4562_FILL.pdf plus stat chips
    (Building Cost / Current-Year Depreciation / Accumulated Depreciation).
    Aid dialog available via the toolbar Aid button.
    '''

    FORM_ID = "Form4562"

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
        '''Absolute path to Forms_IRS/Form4562_FILL.pdf for the current LLC.'''
        llc = self._llc()
        if llc is None:
            return None
        try:
            irs_dir = Path(llc.acctDir(dirName="ye")) / "Forms_IRS"
        except Exception:
            return None
        p = irs_dir / f"{self.FORM_ID}_FILL.pdf"
        return p if p.exists() else None

    def stats(self) -> Dict[str, Any]:
        '''Stat chips — Building Cost / Current-Year Depreciation / Accumulated Depreciation.'''
        out = {
            'Building Cost':             0.0,
            'Current-Year Depreciation': 0.0,
            'Accumulated Depreciation':  0.0,
        }
        llc = self._llc()
        if llc is None:
            return out

        try:
            from ledger.stmtBS import stmtBS_Tax
            from ledger.stmtIS import stmtIS_Tax
        except ImportError:
            return out

        try:
            bs = stmtBS_Tax(llc)
            out['Building Cost']            = _as_float(bs.acct_balance('Acct.Fixed.Tangible.InService'))
            out['Accumulated Depreciation'] = _as_float(bs.acct_balance('Acct.Fixed.Depreciation.Accum'))
        except Exception:
            pass

        try:
            is_ = stmtIS_Tax(llc)
            out['Current-Year Depreciation'] = _as_float(is_.acct_balance('Acct.Exp.Depreciation'))
        except Exception:
            pass

        return out

    def meta(self) -> Dict[str, Any]:
        prof = self._stmt_profile()
        pdf  = self.pdf_path()
        return {
            'objectName': self.object_name(),
            'formId':     self.FORM_ID,
            'pdfPath':    str(pdf) if pdf else '',
            'pdfPresent': pdf is not None,
            'sources': {
                'pdf':     'irs.Form4562 + BookToIRS pipeline → Forms_IRS/Form4562_FILL.pdf',
                'stats':   'ledger.stmtBS_Tax + ledger.stmtIS_Tax',
                'profile': 'ledger.stmtProfile' if prof else None,
            },
            'profile': prof.meta() if prof else {},
            'note': (
                'IRS Form 4562 — Depreciation and Amortization. '
                'Part III Line 19h: 27.5-year MACRS residential rental (MM, S/L). '
                'Line 22 (total depreciation) flows into Form 1065 Line 16a and '
                'Form 8825 Line 14. Consult a qualified tax professional before filing.'
            ),
        }

    # ── Legacy pass-throughs ────────────────────────────────────────────────
    def load(self, view_by: str = 'All'):
        return []

    def list(self):
        return self.load()

    def save(self, data: Any = None):
        return self.load()

    def save_object(self, data: Any = None):
        return self.load()

    def reset_from_object(self):
        return self.load()
