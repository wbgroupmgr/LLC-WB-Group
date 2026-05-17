'''
irs.mapIRS2LLC — IRS-form → LLC data-object mapper.

Responsibility
--------------
Given an IRS form instance (Form1065, Sch_K1, Form4562 …) produce a list of
``formLineDict`` rows — one for every AcroForm field (fid) on the form —
identifying which LLC financial data object can provision that field and, if
any, its current value.

Design contract
---------------
1. ``_mapIRS2LLC()`` has NO knowledge of which data object owns which fid.
2. Every data object answers a single question through ``_to_IRS(formObj)``:
   *"Which fids of this form can I fill, and with what (tbl, row, col, value)?"*
3. Data objects are polled in the authoritative CPA / IRS / rental-LLC
   priority order::

       IS → BS → Customers → Owners → LLC (profile) → GeneralLedger

   Earlier data objects claim fids first; later objects only fill unclaimed
   fids (first-write-wins).  This guarantees the most specific, most-trusted
   source authors any given cell.
4. The function uses ONLY ``ledger/`` and ``stmt/`` objects — no UI imports.
   The knowledge "which fid belongs to which data object" lives entirely
   inside the data objects themselves (each ``_to_IRS`` implementation).
5. Column-oriented forms (Sch_K-1 is one PDF per partner; Form 1065 Pg-6
   has per-partner columns) follow the order of ``llcOwners`` — the order
   each data object iterates its per-owner bindings in.

``formLineDict`` schema
-----------------------
    fid                      : "f1", "f2", …   (PDF AcroForm field id)
    loc_dataObjectClassName  : None | "stmtIncomeStmt" | "stmtBalanceSheet"
                               | "llcOwners" | "llcCustomers" | "LLC"
                               | "stmtGeneralLedger"
    loc_tbl_id               : None | str (data-object table id)
    loc_rowNm                : None | str (row name within the table)
    loc_colNm                : None | str (column name within the row)
    value                    : None | resolved cell value

Usage
-----
    from irs.Form1065      import Form1065
    from irs.mapIRS2LLC      import _mapIRS2LLC
    from ledger.LLC        import LLC

    llc   = LLC("WBGroupLLC")
    form  = Form1065(llc=llc)
    rows  = _mapIRS2LLC(form)        # list[dict] — one entry per fid

Create-once / use-N-times: the returned list is the authoritative
IRS2LLC map and can feed any downstream consumer (FILL.pdf writer, UI
view, CPA worksheet, QA cross-check).

Timestamp of creation: 2026.04.20
'''

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


# ── formLineDict ─────────────────────────────────────────────────────────────

@dataclass
class formLineDict:
    '''Row schema for the IRS2LLC map.  One per fid in the IRS form.'''
    fid: str
    loc_dataObjectClassName: Optional[str] = None
    loc_tbl_id:              Optional[str] = None
    loc_rowNm:               Optional[str] = None
    loc_colNm:               Optional[str] = None
    value:                   Any           = None


# ── Public API ───────────────────────────────────────────────────────────────

def _mapIRS2LLC(irsFormObj) -> List[Dict[str, Any]]:
    '''
    Build the IRS → LLC map for ``irsFormObj``.

    Parameters
    ----------
    irsFormObj : irsForm
        Concrete IRS form instance.  Must expose ``.llc``, ``.oID``, and
        ``_buildNSpace()`` (or a pre-computed ``nSpace`` attribute).

    Returns
    -------
    list[dict]
        One ``formLineDict`` as a plain dict per AcroForm field.
        Sorted by numeric fid suffix (f1, f2, …, f1234).
    '''
    fields = _fields_of(irsFormObj)
    fids   = sorted(fields.keys(), key=_fid_sort_key)

    # Seed: one unbound formLineDict per fid
    seeded: Dict[str, formLineDict] = {fid: formLineDict(fid=fid) for fid in fids}

    # Provide a logicalKey → fid lookup on the formObj so data objects
    # can address fields by their well-known logicalKey.
    _attach_lk_cache(irsFormObj, fields)

    # Poll data objects in authoritative CPA hierarchy order
    llc = getattr(irsFormObj, "llc", None)
    if llc is None:
        return [asdict(seeded[fid]) for fid in fids]

    for obj in _buildDataObjects(llc):
        try:
            bindings = obj._to_IRS(irsFormObj)          # type: ignore[attr-defined]
        except AttributeError:
            # Data object doesn't implement _to_IRS yet — OK, it just means
            # it provisions no IRS fields.
            continue
        except Exception as exc:
            print(f"_mapIRS2LLC: {obj.__class__.__name__}._to_IRS failed: {exc}")
            continue

        cls_name = obj.__class__.__name__
        for b in (bindings or []):
            fid = b.get("fid")
            if not fid or fid not in seeded:
                continue
            cur = seeded[fid]
            if cur.loc_dataObjectClassName is not None:
                # Earlier (higher-priority) object already claimed it.
                continue
            cur.loc_dataObjectClassName = cls_name
            cur.loc_tbl_id = b.get("tbl")   or b.get("loc_tbl_id")
            cur.loc_rowNm  = b.get("row")   or b.get("loc_rowNm")
            cur.loc_colNm  = b.get("col")   or b.get("loc_colNm")
            cur.value      = b.get("value")

    return [asdict(seeded[fid]) for fid in fids]


# ── Helpers exposed for data objects ────────────────────────────────────────

def _lk_to_fid(irsFormObj) -> Dict[str, str]:
    '''
    Return the ``logicalKey → fid`` lookup for this form.  Built once
    per formObj and cached as ``formObj._lk_to_fid_cache``.

    Data-object ``_to_IRS`` methods can use this to resolve IRS logical
    keys (e.g. "P1_23", "L_21_2", "K1_PtName") to the form's AcroForm
    fid without having to walk the namespace themselves.
    '''
    cache = getattr(irsFormObj, "_lk_to_fid_cache", None)
    if cache is not None:
        return cache
    fields = _fields_of(irsFormObj)
    _attach_lk_cache(irsFormObj, fields)
    return getattr(irsFormObj, "_lk_to_fid_cache", {})


# ── Internal helpers ────────────────────────────────────────────────────────

_FID_NUM_RE = re.compile(r"(\d+)")


def _fid_sort_key(fid: str):
    m = _FID_NUM_RE.search(str(fid))
    return (int(m.group(1)) if m else 10_000, str(fid))


def _fields_of(irsFormObj) -> Dict[str, Dict[str, Any]]:
    '''
    Return ``{fid: nspaceEntry}`` for an irsForm-like object.  Honours a
    pre-computed ``nSpace`` attribute if present; otherwise calls
    ``_buildNSpace()`` (which reads the AcroForm PDF).
    '''
    ns = getattr(irsFormObj, "nSpace", None)
    if ns is None:
        try:
            ns = irsFormObj._buildNSpace()
        except Exception as exc:
            print(f"_mapIRS2LLC: _buildNSpace failed: {exc}")
            return {}
    return ns.get("fields", ns) or {}


def _attach_lk_cache(irsFormObj, fields: Dict[str, Dict[str, Any]]) -> None:
    if getattr(irsFormObj, "_lk_to_fid_cache", None) is not None:
        return
    lk2fid: Dict[str, str] = {}
    for fid, fd in fields.items():
        lk = fd.get("logicalKey") or ""
        if lk and lk not in lk2fid:
            lk2fid[lk] = fid
        # Also index by shortName as a fallback (covers forms whose
        # logicalKey wasn't populated from the keys PDF).
        sn = fd.get("shortName") or ""
        if sn and sn not in lk2fid:
            lk2fid.setdefault(sn, fid)
    try:
        irsFormObj._lk_to_fid_cache = lk2fid
    except Exception:
        # formObj might be frozen — callers will fall back to building
        # the cache locally.
        pass


def _buildDataObjects(llc) -> List[Any]:
    '''
    Instantiate the authoritative data-object chain for ``llc`` in the
    CPA / IRS priority order::

        IS → BS → Customers → Owners → LLC (profile) → GeneralLedger

    Missing optional dependencies are skipped silently so a partially
    populated LLC still yields a usable map.
    '''
    objs: List[Any] = []

    # 1. Income Statement (highest authority for P&L lines)
    try:
        from ledger.stmtIS import stmtIS as stmtIncomeStmt
        objs.append(stmtIncomeStmt(llc))
    except Exception as exc:
        print(f"_buildDataObjects: stmtIncomeStmt skipped: {exc}")

    # 2. Balance Sheet (authority for assets / liabilities / equity)
    try:
        from ledger.stmtBS import stmtBS as stmtBalanceSheet
        objs.append(stmtBalanceSheet(llc))
    except Exception as exc:
        print(f"_buildDataObjects: stmtBalanceSheet skipped: {exc}")

    # 3. Customers / A/R (authority for customer-side ledger questions)
    try:
        from ledger.llcCustomers import llcCustomers
        objs.append(llcCustomers(llc))
    except Exception as exc:
        print(f"_buildDataObjects: llcCustomers skipped: {exc}")

    # 4. Owners (authority for partner identity, %, capital account)
    try:
        from ledger.llcOwners import llcOwners
        objs.append(llcOwners(llc))
    except Exception as exc:
        print(f"_buildDataObjects: llcOwners skipped: {exc}")

    # 5. LLC profile — the llc object itself publishes entity/F1065 data
    objs.append(llc)

    # 6. General Ledger — fallback for anything not claimed above
    try:
        from ledger.stmtGL import stmtGL as stmtGeneralLedger
        objs.append(stmtGeneralLedger(llc))
    except Exception as exc:
        print(f"_buildDataObjects: stmtGeneralLedger skipped: {exc}")

    return objs
