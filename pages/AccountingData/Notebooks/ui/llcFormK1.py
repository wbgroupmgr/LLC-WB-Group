'''
llcFormK1 — IRS Schedule K-1 (Form 1065) — per-partner allocations.

ProjectLevel3 v0.2.4.7 — PDF-embed restructure
----------------------------------------------
Mirrors ``ui.llcForm1065``: instead of reconstructing a transposed K-1 table
from FR data, the view embeds the canonical filled artifact
``Forms_IRS/Sch_K1_FILL.pdf`` produced by ``irs.Sch_K1.saveFILL()``.

Stat chips read partner-count + Box 2 totals from the ledger and the
profile, but no row-level data construction happens here.

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


class llcFormK1:
    '''
    Schedule K-1 PDF-embed view — pure UI glue.
    '''

    FORM_ID = "Sch_K1"

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

    def _owner_count(self) -> int:
        prof = self._stmt_profile()
        if prof is None:
            return 0
        try:
            owners = prof.get('Profile', 'owners') or []
            if isinstance(owners, list):
                return len(owners)
        except Exception:
            pass
        try:
            return len(self._llc().owners or [])
        except Exception:
            return 0

    # ── Public interface ────────────────────────────────────────────────────

    def _irs_dir(self) -> Optional[Path]:
        llc = self._llc()
        if llc is None:
            return None
        try:
            return Path(llc.acctDir(dirName="ye")) / "Forms_IRS"
        except Exception:
            return None

    def pdf_path(self, oID: str = "") -> Optional[Path]:
        irs_dir = self._irs_dir()
        if irs_dir is None:
            return None
        stem = f"{self.FORM_ID}_{oID}_FILL.pdf" if oID else f"{self.FORM_ID}_FILL.pdf"
        p = irs_dir / stem
        return p if p.exists() else None

    def owners(self):
        """List of {oID, name, fill_exists} for all K-1 partners."""
        llc = self._llc()
        if llc is None:
            return []
        try:
            import json
            top     = getattr(llc, 'TOP', '') or ''
            acct    = getattr(llc, 'dirAccounting', '') or ''
            llcName = getattr(llc, 'objName', '') or ''
            fn = Path(top) / acct / 'Accts' / f'llcOwners_{llcName}.json'
            if not fn.exists():
                return []
            raw     = json.loads(fn.read_text(encoding='utf-8'))
            irs_dir = self._irs_dir()
            result  = []
            for o in raw:
                oID  = o.get('oID', '')
                nm   = o.get('nm', [])
                name = nm[0] if isinstance(nm, list) and nm else str(oID)
                fill_exists = bool(irs_dir and (irs_dir / f"Sch_K1_{oID}_FILL.pdf").exists())
                result.append({'oID': oID, 'name': name, 'fill_exists': fill_exists})
            return result
        except Exception:
            return []

    def stats(self) -> Dict[str, Any]:
        out = {
            'Partners':       self._owner_count(),
            'Rent (Box 2)':   0.0,
            'Net Income':     0.0,
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
            for r in _is.load():
                acct = str(r.get('acct', ''))
                if 'Rent' in acct or 'Rental' in acct:
                    bal = _as_float(r.get('Balance'))
                    rent_total += -bal
            out['Rent (Box 2)'] = round(rent_total, 2)
            out['Net Income']   = _as_float(_is.get('TOTAL', 'Balance'))
        except Exception:
            pass

        return out

    def meta(self) -> Dict[str, Any]:
        prof    = self._stmt_profile()
        pdf     = self.pdf_path()
        owners  = self.owners()
        irs_dir = self._irs_dir()
        ns_present = bool(irs_dir and (irs_dir / f"{self.FORM_ID}_namespace.pdf").exists())
        return {
            'objectName':   self.object_name(),
            'formId':       self.FORM_ID,
            'pdfPath':      str(pdf) if pdf else '',
            'pdfPresent':   pdf is not None,
            'owners':       owners,        # per-partner K-1 selector data
            'nsPdfPresent': ns_present,
            'sources': {
                'pdf':     'irs.Sch_K1.saveFILL() → Forms_IRS/Sch_K1_FILL.pdf',
                'stats':   'ledger.stmtIncomeStmt + ledger.stmtProfile',
                'profile': 'ledger.stmtProfile' if prof else None,
            },
            'profile': prof.meta() if prof else {},
            'note': (
                'IRS Schedule K-1 (Form 1065). The view embeds the canonical '
                'Sch_K1_FILL.pdf produced by irs.Sch_K1.saveFILL(). '
                'Consult a qualified tax professional before filing.'
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
