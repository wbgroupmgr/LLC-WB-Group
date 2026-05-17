'''
llcForm8825 — IRS Form 8825 (Rental Real Estate Income & Expenses of a
Partnership or S Corporation).

PDF-embed view — same architecture as ``ui.llcForm1065`` and
``ui.llcFormK1``: the page renders the canonical ``Form8825_FILL.pdf``
produced by ``irs.Form8825`` + the BookToIRS pipeline; stat chips read
top-level numbers from the ledger.

Form 8825 is the partnership-side analogue of Schedule E (Form 1040).
For a hold-to-rent LLC like W&B Group it captures Lines 1 (property
addresses), 2 (gross rents), and 3-15 (operating expenses including
depreciation on Line 14). The final Line 21 net flows into Form 1065
Schedule K, Line 2.

Timestamp of last change: 2026.05.03
'''
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return default


class llcForm8825:
    '''
    Form 8825 PDF-embed view — pure UI glue.

    The page renders an inline ``<iframe>`` of ``Form8825_FILL.pdf``
    plus a small stat-chip bar (gross rents, depreciation, net rental
    income).  The Aid modal (``ui/templates/_aid_dialog.html``) is
    available via the toolbar Aid button just like Form 1065 / K-1.
    '''

    FORM_ID = "Form8825"

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
        '''Absolute path to ``Forms/<FORM_ID>_FILL.pdf`` via eSession.paths.'''
        try:
            irs_dir = Path(self.eSession.paths.irs_forms_dir)
        except Exception:
            return None
        p = irs_dir / f"{self.FORM_ID}_FILL.pdf"
        return p if p.exists() else None

    def stats(self) -> Dict[str, Any]:
        '''Top-level stat chips — Gross Rents / Depreciation /
        Net Rental Income — pulled from ``ledger.stmtIncomeStmt``.'''
        out = {
            'Gross Rents':         0.0,
            'Depreciation':        0.0,
            'Net Rental Income':   0.0,
        }
        llc = self._llc()
        if llc is None:
            return out

        try:
            from ledger.stmtIS import stmtIS as stmtIncomeStmt
        except ImportError:
            return out

        try:
            _is = stmtIncomeStmt(llc)
            rent_total = 0.0
            depr_total = 0.0
            for r in _is.load():
                at   = str(r.get('acctType', ''))
                acct = str(r.get('acct', ''))
                bal  = _as_float(r.get('Balance'))
                if at == 'Income' and ('Rent' in acct or 'Rental' in acct):
                    # Income rows store Balance = Debit − Credit (negative);
                    # flip to positive for the chip.
                    rent_total += -bal
                if at == 'Expense' and ('Depr' in acct or 'depreciation' in acct.lower()):
                    depr_total += bal
            out['Gross Rents']        = round(rent_total, 2)
            out['Depreciation']       = round(depr_total, 2)
            # Form 8825 Line 21 ≈ Gross Rents − Total expenses (here
            # only depreciation for the simple W&B case).  The actual
            # Line 21 is auto-calculated by Acrobat when the FILL.pdf
            # is opened; this chip is just a quick sanity figure.
            out['Net Rental Income']  = round(rent_total - depr_total, 2)
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
                'pdf':     'irs.Form8825 + BookToIRS pipeline → Forms_IRS/Form8825_FILL.pdf',
                'stats':   'ledger.stmtIncomeStmt',
                'profile': 'ledger.stmtProfile' if prof else None,
            },
            'profile': prof.meta() if prof else {},
            'note': (
                'IRS Form 8825 — Rental Real Estate Income and Expenses of a '
                'Partnership or S Corporation. The view embeds the canonical '
                'Form8825_FILL.pdf produced by the BookToIRS pipeline. '
                'Line 21 (net rental income) flows into Form 1065 Schedule K, '
                'Line 2. Consult a qualified tax professional before filing.'
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
