'''
ledger.fillDict — unified IRS-form fill-dictionary builder (v0.3).

Purpose
-------
Aggregate the four v0.3 tax-mapping sources (stmtProfile + stmtGL_Tax +
stmtBS_Tax + stmtIS_Tax) into a single flat row set keyed by
``(fid, formNm)`` plus a ``source`` tag.  The output is shaped so it can
be fed directly to ``pandas.DataFrame()`` and to the downstream
``irs.pdfFill`` writer that produces a FILL.pdf for Form 1065 / Sch K-1
/ Form 4562.

Schema (one row per (fid, formNm)):
    fid     — IRS field id (e.g. "F004", "f1_4(0)", ...)
    acct    — UAS path used to resolve the value
              (e.g. "Profile.F1065.preparer_ein", "BS.total_assets",
               "IS.rent_income", "Acct.Income.RentRevenue")
    fval    — resolved value (may be str, float, int, or None)
    formNm  — section name from the bookNS file ("Form1065", "Sch_K1",
              "Form4562")
    source  — stmt-of-origin: 'Profile' | 'GL' | 'BS' | 'IS'

Resolver priority (per docs/LLC_stmtDesign.md):
    Profile  →  BS  →  IS  →  GL  (fallback)

The default ``buildFillDict()`` returns the *full* concatenated list (all
sources, including duplicate fids).  Pass ``dedupe='priority'`` to keep
only the highest-priority entry per fid (Profile beats BS beats IS beats
GL).  This matches the runtime resolver behaviour the IRS-fill consumer
expects when writing FILL.pdf cell-by-cell.

Public API
----------
    buildFillDict(llc, *, dedupe=None) -> List[Dict[str, Any]]
        Flat list-of-dicts — feed directly to pd.DataFrame().

    to_pdf(llc, *, dedupe='priority') -> pandas.DataFrame
        Same data as buildFillDict() but as a DataFrame, with
        deterministic column order [fid, acct, fval, formNm, source].

    FillDictBuilder(llc)
        Class form, exposes the same two methods plus per-stmt
        accessors (profile_entries, gl_entries, bs_entries, is_entries)
        for callers that want one slice at a time.

Usage
-----
    from ledger.LLC import LLC
    from ledger.fillDict import buildFillDict, to_pdf
    import pandas as pd

    llc = LLC('WBGroupLLC')
    fillDict = buildFillDict(llc, dedupe='priority')
    df = pd.DataFrame(fillDict)            # ← column-ordered automatically

    # Or directly:
    df = to_pdf(llc, dedupe='priority')

    # Per-form slice:
    f1065 = df[df.formNm == 'Form1065']
    schk1 = df[df.formNm == 'Sch_K1']

Per DataModelGuide § 3 this module holds NO data — every call rebuilds
the underlying immutable stmts from the LLC.

Timestamp: 2026.04.27 — v0.3.fillDict
'''

from __future__ import annotations

import json as _json
import os as _os
from typing import Any, Dict, Iterable, List, Optional


# Priority order — earlier wins when dedupe='priority'.
_SOURCE_PRIORITY = ('Profile', 'BS', 'IS', 'GL')

_FILL_COLUMNS = ['fid', 'acct', 'fval', 'formNm', 'source']


class FillDictBuilder:
    '''
    Build a unified IRS PDF-fill dictionary from the v0.3 stmt hierarchy.

    Holds no data — each accessor rebuilds the relevant stmt immutably.
    '''

    BKNS_PROFILE_FN = 'bookNS_Profile.json'

    def __init__(self, llc):
        self.llc = llc

    # ── Path helpers ────────────────────────────────────────────────────

    def _bkNS_profile_path(self) -> str:
        '''Resolve <TOP>/<dirAccounting>/<YEAR>/bookNS_Profile.json.'''
        try:
            top  = _os.path.expanduser(getattr(self.llc, 'TOP', '') or '')
            acct = getattr(self.llc, 'dirAccounting', '') or ''
            yr   = (getattr(self.llc, 'YEAR', None)
                    or getattr(self.llc, 'yr', None))
            yr   = str(int(yr)) if yr else ''
            if yr:
                return _os.path.join(top, acct, yr, self.BKNS_PROFILE_FN)
            return _os.path.join(top, acct, self.BKNS_PROFILE_FN)
        except Exception:
            return ''

    def _bkNS_profile_load(self) -> Dict[str, Any]:
        fn = self._bkNS_profile_path()
        if not fn or not _os.path.exists(fn):
            return {}
        try:
            with open(fn, 'r') as fio:
                return _json.load(fio)
        except Exception as err:                            # pragma: no cover
            print(f"fillDict: could not load {fn}: {err}")
            return {}

    # ── Per-source entry builders ───────────────────────────────────────

    def profile_entries(self) -> List[Dict[str, Any]]:
        '''
        Resolve the bookNS_Profile.json mapping against the immutable
        stmtProfile cell index.  Returns a flat list of
        {fid, acct, fval, formNm, source='Profile'} dicts — one per
        (fid, UAS) pair across every form section in the bookNS.

        UAS paths recognised:
            "Profile.<src>.<fNm>"  → stmtProfile.get(rowNm, 'value')
                                     where rowNm == acct.
        Anything else (or unresolvable) yields fval=None.
        '''
        try:
            from ledger.stmtProfile import stmtProfile
        except ImportError:                                  # pragma: no cover
            from stmtProfile import stmtProfile             # type: ignore

        try:
            prof = stmtProfile(self.llc)
        except Exception as err:                             # pragma: no cover
            print(f"fillDict: stmtProfile build failed: {err}")
            return []

        bkNS = self._bkNS_profile_load()
        out: List[Dict[str, Any]] = []
        for formNm, mappings in bkNS.items():
            if not formNm or formNm.startswith('_'):
                continue
            if not isinstance(mappings, list):
                continue
            for pair in mappings:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                fid, acct = pair[0], pair[1]
                fval = self._resolve_profile(prof, acct)
                out.append({
                    'fid':    fid,
                    'acct':   acct,
                    'fval':   fval,
                    'formNm': formNm,
                    'source': 'Profile',
                })
        return out

    @staticmethod
    def _resolve_profile(prof, acct: Any) -> Any:
        '''
        Resolve a "Profile.<src>.<fNm>" UAS path to a value via the
        immutable stmtProfile cell index.  Returns None for unrecognised
        prefixes or when the cell is absent (e.g. Profile.BookNS.* on a
        profile without a BookNS source).
        '''
        if not isinstance(acct, str) or not acct.startswith('Profile.'):
            return None
        try:
            return prof.get(acct, 'value', None)
        except Exception:
            return None

    def gl_entries(self) -> List[Dict[str, Any]]:
        '''Flat stmtGL_Tax.load() output, tagged with source='GL'.'''
        try:
            from ledger.stmtGL import stmtGL_Tax
        except ImportError:                                  # pragma: no cover
            from stmtGL import stmtGL_Tax                   # type: ignore
        try:
            tx = stmtGL_Tax(self.llc)
        except Exception as err:                             # pragma: no cover
            print(f"fillDict: stmtGL_Tax build failed: {err}")
            return []
        rows = tx.load()
        for r in rows:
            r.setdefault('source', 'GL')
        return rows

    def bs_entries(self) -> List[Dict[str, Any]]:
        '''Flat stmtBS_Tax.load() output, tagged with source='BS'.'''
        try:
            from ledger.stmtBS import stmtBS_Tax
        except ImportError:                                  # pragma: no cover
            from stmtBS import stmtBS_Tax                   # type: ignore
        try:
            tx = stmtBS_Tax(self.llc)
        except Exception as err:                             # pragma: no cover
            print(f"fillDict: stmtBS_Tax build failed: {err}")
            return []
        rows = tx.load()
        for r in rows:
            r.setdefault('source', 'BS')
        return rows

    def is_entries(self) -> List[Dict[str, Any]]:
        '''Flat stmtIS_Tax.load() output, tagged with source='IS'.'''
        try:
            from ledger.stmtIS import stmtIS_Tax
        except ImportError:                                  # pragma: no cover
            from stmtIS import stmtIS_Tax                   # type: ignore
        try:
            tx = stmtIS_Tax(self.llc)
        except Exception as err:                             # pragma: no cover
            print(f"fillDict: stmtIS_Tax build failed: {err}")
            return []
        rows = tx.load()
        for r in rows:
            r.setdefault('source', 'IS')
        return rows

    # ── Public surface ──────────────────────────────────────────────────

    def buildFillDict(self,
                      *,
                      dedupe: Optional[str] = None,
                      ) -> List[Dict[str, Any]]:
        '''
        Concatenate Profile + BS + IS + GL entries into a single flat
        list-of-dicts shaped for ``pandas.DataFrame()``.

        ``dedupe``:
          - None             — return every entry from every source
                               (default; a fid mapped in two bookNS
                               files will appear twice).
          - 'priority'       — keep only the highest-priority entry per
                               fid: Profile > BS > IS > GL.  An entry
                               whose fval is None is skipped in favour
                               of a later-source entry that resolves to
                               a real value.
          - 'priority_strict'— like 'priority' but does NOT skip None
                               values — the first source claiming the
                               fid wins regardless.

        Order of sources in the unified list (before dedupe) follows
        ``_SOURCE_PRIORITY`` so deduping is a stable single pass.
        '''
        unified: List[Dict[str, Any]] = []
        unified.extend(self.profile_entries())
        unified.extend(self.bs_entries())
        unified.extend(self.is_entries())
        unified.extend(self.gl_entries())

        if dedupe is None:
            return unified
        if dedupe not in ('priority', 'priority_strict'):
            raise ValueError(
                f"fillDict.buildFillDict: unknown dedupe='{dedupe}' — "
                f"expected None | 'priority' | 'priority_strict'.")

        prefer_resolved = (dedupe == 'priority')
        chosen: Dict[Any, Dict[str, Any]] = {}
        for r in unified:
            key = (r.get('formNm'), r.get('fid'))
            cur = chosen.get(key)
            if cur is None:
                chosen[key] = r
                continue
            # If we already have a non-None value, keep it (priority order).
            if prefer_resolved and cur.get('fval') in (None, ''):
                # current is empty — replace if new one resolves.
                if r.get('fval') not in (None, ''):
                    chosen[key] = r
            # else: first source wins (priority_strict, or already resolved).
        return list(chosen.values())

    def to_pdf(self,
               *,
               dedupe: Optional[str] = 'priority',
               ):
        '''
        Return the unified PDF-fill DataFrame.

        Columns: [fid, acct, fval, formNm, source]
        Default ``dedupe='priority'`` so the DataFrame matches what
        ``irs.pdfFill`` would actually write into a FILL.pdf (one row
        per (formNm, fid)).

        Raises ImportError if pandas is not installed.
        '''
        try:
            import pandas as pd
        except ImportError as err:                           # pragma: no cover
            raise ImportError(
                "ledger.fillDict.to_pdf() requires pandas; install "
                "pandas or call buildFillDict() for a list-of-dicts."
            ) from err
        rows = self.buildFillDict(dedupe=dedupe)
        return pd.DataFrame(rows, columns=_FILL_COLUMNS)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level convenience wrappers (functional API)
# ─────────────────────────────────────────────────────────────────────────────

def buildFillDict(llc,
                  *,
                  dedupe: Optional[str] = None,
                  ) -> List[Dict[str, Any]]:
    '''
    Functional shortcut for ``FillDictBuilder(llc).buildFillDict(...)``.
    Returns a flat list-of-dicts suitable for ``pd.DataFrame()``.

    See ``FillDictBuilder.buildFillDict`` for the dedupe semantics.
    '''
    return FillDictBuilder(llc).buildFillDict(dedupe=dedupe)


def to_pdf(llc,
           *,
           dedupe: Optional[str] = 'priority',
           ):
    '''
    Functional shortcut for ``FillDictBuilder(llc).to_pdf(...)``.
    Returns a pandas DataFrame with columns
    ``[fid, acct, fval, formNm, source]``.
    '''
    return FillDictBuilder(llc).to_pdf(dedupe=dedupe)


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test:  python -m ledger.fillDict
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':                                   # pragma: no cover
    import sys
    try:
        from ledger.LLC import LLC
    except ImportError:
        from LLC import LLC                                  # type: ignore
    name = sys.argv[1] if len(sys.argv) > 1 else 'WBGroupLLC'
    llc  = LLC(name)
    rows = buildFillDict(llc, dedupe='priority')
    by_form: Dict[str, int] = {}
    by_src:  Dict[str, int] = {}
    for r in rows:
        by_form[r.get('formNm', '?')] = by_form.get(r.get('formNm', '?'), 0) + 1
        by_src[r.get('source', '?')]  = by_src.get(r.get('source', '?'), 0) + 1
    print(f"fillDict for {name}: {len(rows)} rows")
    print(f"  by form:   {by_form}")
    print(f"  by source: {by_src}")
    if rows:
        print("  sample[0]:", rows[0])
