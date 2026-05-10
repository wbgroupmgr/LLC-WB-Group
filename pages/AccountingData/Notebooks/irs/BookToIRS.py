"""
BookToIRS — IRS Tax Mapping Bridge service layer (v0.1).

Bridge pattern implementation: translates Book accounting data to IRS form
nomenclature. Lives in irs/ to maintain separation of concerns per the
"Tax Bridge" architecture (see docs/LLC_AccountingDesign.md §2).

This service is consumed by ui.llcMgmt Flask routes (/api/aid/...)
via irs.Form<formNm> delegation.

See docs/LLC_BookToIRS_Aid.md for the full design. v0.1 delivers:
- M1 (read mapping): listSources, loadBookNS, loadCustomMapDict, etc.
- M3 (bookNS write + backup): createMapping, editMapping, deleteMapping
- M5 (regenerate FILL.pdf): regenerate()
M4 (custom-map Python source surgery) is present as raise-NotImplementedError stubs.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Sources the Aid manages.  Order = priority (Profile > BS > IS > GL).
AID_SOURCES: Tuple[str, ...] = ("Profile", "BS", "IS", "GL")
AID_PRIO:    Dict[str, int]  = {s: i for i, s in enumerate(AID_SOURCES)}

# How many JSON backups to keep per source (§8.3).
BACKUP_KEEP: int = 30

# Sentinels — mirror irsForm / stmtProfile.
CHECK_SENTINEL:   str = "CHECK"
COMPLEX_SENTINEL: str = "Complex"


# ════════════════════════════════════════════════════════════════════════════
class BookToIRS:
    """Per-LLC, per-form Book→IRS mapping bridge.

    Reads / writes:
      * ``bookNS_<src>.json`` for the four bookNS sources
      * ``<formNm>_CustomMapDict`` class attributes on the live
        ``stmt<src>_Tax`` subclasses (M4 — pending)
      * ``Form1065_namespace.json`` (read-only)

    Writes are immediate.  No in-memory pending state, no diff/revert,
    no validation gate (per §7).
    """

    def __init__(self, llc, formNm: str = "Form1065"):
        self.llc    = llc
        self.formNm = formNm
        self._stmt_instances: Dict[str, Any] = {}
        self._namespace_cache: Optional[Dict[str, Dict]] = None

    # ── Path helpers ────────────────────────────────────────────
    def _accountingDir(self) -> Path:
        """Mirrors stmt*_Tax._bkNS_path() conventions."""
        top = os.path.expanduser(getattr(self.llc, "TOP", "") or "")
        acct = getattr(self.llc, "dirAccounting", "") or ""
        yr = (
            str(getattr(self.llc, "YEAR", None) or
                 getattr(self.llc, "yr",   None) or "").strip()
        )
        base = Path(top) / acct
        return (base / yr) if yr else base

    def _bookNSPath(self, src: str) -> Path:
        return self._accountingDir() / f"bookNS_{src}.json"

    def _backupDir(self) -> Path:
        return self._accountingDir() / ".bookNS_backups"

    def _namespacePath(self) -> Path:
        try:
            irs_dir = Path(self.llc.acctDir(dirName="ye")) / "Forms_IRS"
        except Exception:
            irs_dir = self._accountingDir() / "YE_Tax_Records" / "Forms_IRS"
        return irs_dir / f"{self.formNm}_namespace.json"

    def _profilePath(self) -> Path:
        """Canonical ``llcProfile_<llcName>.json`` (the per-LLC profile JSON
        that stores ``F1065.chk[]`` — see §6 of LLC_BookToIRS_Aid.md).
        Mirrors ``stmtProfile._profile_fn()``."""
        try:
            from ledger import setup_paths  # type: ignore
            return Path(str(setup_paths.ACCTS_DIR)) / f"llcProfile_{self.llc.objName}.json"
        except Exception:
            top  = os.path.expanduser(getattr(self.llc, "TOP", "") or "")
            acct = getattr(self.llc, "dirAccounting", "") or ""
            return Path(top) / acct / "Accts" / f"llcProfile_{self.llc.objName}.json"

    # ── stmt class / instance lookup ────────────────────────────
    def _stmtClass(self, src: str):
        try:
            if src == "Profile":
                from ledger.stmtProfile import stmtProfile
                return stmtProfile
            if src == "BS":
                from ledger.stmtBS import stmtBS_Tax
                return stmtBS_Tax
            if src == "IS":
                from ledger.stmtIS import stmtIS_Tax
                return stmtIS_Tax
            if src == "GL":
                from ledger.stmtGL import stmtGL_Tax
                return stmtGL_Tax
        except ImportError:
            return None
        return None

    def _stmtInstance(self, src: str):
        if src in self._stmt_instances:
            return self._stmt_instances[src]
        cls = self._stmtClass(src)
        if cls is None:
            return None
        try:
            inst = cls(self.llc)
        except Exception:
            return None
        self._stmt_instances[src] = inst
        return inst

    def _refreshStmtInstances(self) -> None:
        """Drop the cached stmtOBJ instances AND re-read the LLC profile
        so the next access sees live disk state.

        Why both:
          * The cached stmt<src>_Tax instances hold their own JSON
            re-reads (bookNS_<src>.json) — clearing the cache forces a
            re-instantiation and re-read.
          * The LLC object holds the profile JSON in memory as
            ``self.llc.entity`` / ``self.llc.F1065`` attributes.  When
            we mutate ``Profile.F1065.chk`` via ``addToChkArray`` /
            ``removeFromChkArray`` the on-disk file changes but the
            LLC's in-memory copy does not — calling ``_Profile()``
            re-runs the loader and re-sets the attributes from disk.
        """
        self._stmt_instances.clear()
        try:
            self.llc._Profile()
        except Exception:
            pass

    # ── Read API ────────────────────────────────────────────────
    def loadNamespace(self) -> Dict[str, Dict]:
        """Returns ``Form1065_namespace.json``'s ``fields`` dict
        (keyed by ``f1`` / ``f2`` / …)."""
        if self._namespace_cache is None:
            fp = self._namespacePath()
            if not fp.exists():
                self._namespace_cache = {}
            else:
                with open(fp, "r", encoding="utf-8") as fh:
                    j = json.load(fh)
                self._namespace_cache = j.get("fields", {}) if isinstance(j, dict) else {}
        return self._namespace_cache

    # ── Source helpers ────────────────────────────────────────────
    @staticmethod
    def _src_base(src: str) -> str:
        """Normalize virtual sources to their bookNS source.
        'Profile.Form8825' and any 'Profile.*' map to 'Profile'.
        """
        if isinstance(src, str) and src.startswith("Profile."):
            return "Profile"
        return src

    def listSources(self) -> List[str]:
        """Return Aid source list including virtual form-scoped sources.
        'Profile.Form8825' appears after 'Profile' so the operator can
        browse only Form8825-relevant profile fields.
        """
        out = list(AID_SOURCES)             # Profile, BS, IS, GL
        idx = out.index("Profile") + 1 if "Profile" in out else 1
        out.insert(idx, "Profile.Form8825") # always show; paths filtered in listAllPathsWithValues
        return out

    def loadBookNS(self, src: str) -> List[List[str]]:
        """Form1065 ``[[fid, path], …]`` rows from ``bookNS_<src>.json``."""
        fp = self._bookNSPath(src)
        if not fp.exists():
            return []
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            return []
        m = d.get(self.formNm, []) or []
        return [list(p) for p in m if isinstance(p, (list, tuple)) and len(p) >= 2]

    def loadCustomMapDict(self, src: str) -> Dict[str, str]:
        """Read the live ``<formNm>_CustomMapDict`` from the running
        stmt subclass.  Returns an empty dict if the class doesn't
        define one (the v0.1 shipping baseline)."""
        cls = self._stmtClass(src)
        if cls is None:
            return {}
        attr = getattr(cls, f"{self.formNm}_CustomMapDict", None)
        return dict(attr) if isinstance(attr, dict) else {}

    # ── chk[] array — the third source layer ────────────────────
    # Profile.F1065.chk lives in llcProfile_<llcName>.json.  It is a
    # plain integer list of fids that stmtProfile.loadFillDict() uses
    # to inject CHECK_SENTINEL values (which BookToIRS then stamps as
    # X on /Tx fields or toggles ON for /Btn fields).  This is data
    # rather than a code-level mapping — neither bookNS nor
    # CustomMapDict surface it — so the Aid handles it as its own
    # source so the operator can toggle CHECK on/off without editing
    # the JSON by hand.
    def loadChkArray(self) -> List[int]:
        """Read ``Profile.<formKey>.chk`` from the LLC profile JSON.

        ``formKey`` is the section key inside the profile JSON:
          * Form1065 -> 'F1065'
          * Sch_K1   -> 'Sch_K1'   (future)
          * other    -> formNm     (1:1 fallback)
        """
        fp = self._profilePath()
        if not fp.exists():
            return []
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            return []
        sect = d.get(self._profileFormKey(), {})
        arr  = sect.get("chk", []) if isinstance(sect, dict) else []
        out: List[int] = []
        for x in arr:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out

    def isInChkArray(self, fid: str) -> bool:
        n = self._fidNum(fid)
        return n is not None and n in self.loadChkArray()

    def addToChkArray(self, fid: str) -> Dict:
        n = self._fidNum(fid)
        if n is None:
            raise ValueError(f"chk[] requires a numeric fid; got {fid!r}")
        fp = self._profilePath()
        if not fp.exists():
            raise FileNotFoundError(f"profile JSON not found at {fp}")
        with open(fp, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        sect_key = self._profileFormKey()
        sect = d.setdefault(sect_key, {})
        arr  = sect.setdefault("chk", [])
        if n not in arr:
            arr.append(n)
            arr.sort()
            self._backupProfile()
            self._atomicWriteJSON(fp, d)
        self._refreshStmtInstances()
        return self.getMapping(self._normalizeFid(fid))

    def removeFromChkArray(self, fid: str) -> Dict:
        n = self._fidNum(fid)
        if n is None:
            raise ValueError(f"chk[] requires a numeric fid; got {fid!r}")
        fp = self._profilePath()
        if not fp.exists():
            return self.getMapping(self._normalizeFid(fid))
        with open(fp, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        sect = d.get(self._profileFormKey())
        if isinstance(sect, dict) and "chk" in sect and isinstance(sect["chk"], list):
            if n in sect["chk"]:
                sect["chk"] = [x for x in sect["chk"] if x != n]
                self._backupProfile()
                self._atomicWriteJSON(fp, d)
        self._refreshStmtInstances()
        return self.getMapping(self._normalizeFid(fid))

    def toggleChkArray(self, fid: str) -> Tuple[Dict, str]:
        """Convenience: toggles fid membership in chk[].  Returns
        ``(mapping, action)`` where action is ``'added'`` or
        ``'removed'``."""
        if self.isInChkArray(fid):
            return (self.removeFromChkArray(fid), "removed")
        return (self.addToChkArray(fid), "added")

    def listFields(self, src: str) -> List[str]:
        """UAS keys the stmt<src> publishes via ``loadFillDict(formNm)``.

        These are *fid keys* (``F001``..``F440``) — the dropdown shows
        them so the operator picks an fid that the resolver currently
        emits a value for.  In practice, custom paths (``Cplx.*``,
        ``Custom.*``) are surfaced as the fid key whose entry ends up
        in the resolver dict.
        """
        try:
            stmt = self._stmtInstance(src)
            if stmt is None:
                return []
            d = stmt.loadFillDict(self.formNm) or {}
            return sorted(d.keys())
        except Exception:
            return []

    def listResolvablePaths(self, src: str) -> List[str]:
        """Legacy shim — returns path strings only.  Use listAllPathsWithValues()."""
        return [x["path"] for x in self.listAllPathsWithValues(src)]

    @staticmethod
    def _fmt_val(v) -> str:
        """Format a resolved value for Aid display (cap at 60 chars)."""
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:,.2f}"
        if isinstance(v, (int, bool)):
            return str(v)
        s = str(v).strip()
        return s[:60] if len(s) > 60 else s

    def listAllPathsWithValues(self, src: str) -> List[Dict]:
        """Full universe of UAS paths available from ``src`` with live values.

        Returns [{path, value, label}] covering:
          IS   — all IS.* taxAggregates + Acct.* COA rows live in the IS
          BS   — all BS.* taxAggregates + Acct.* COA rows live in the BS
          GL   — all Acct.* COA rows in the GL
          Profile          — all Profile.entity.* + Profile.F1065.* rows
          Profile.Form8825 — Profile.entity.* + Form8825-bookNS profile rows

        Paths already declared in bookNS for this src+form are appended if
        not already covered (handles Cplx.* and sentinel paths).
        """
        base = self._src_base(src)
        out: List[Dict] = []

        def _entry(path, v=None):
            vstr = self._fmt_val(v)
            return {"path": path, "value": vstr,
                    "label": f"{path}  ({vstr})" if vstr else path}

        if base == "IS":
            stmt = self._stmtInstance("IS")
            if stmt is not None:
                agg = stmt.taxAggregates() if hasattr(stmt, "taxAggregates") else {}
                for k in sorted(agg):
                    out.append(_entry(f"IS.{k}", agg[k]))
                try:
                    seen: set = set()
                    for r in stmt._rows:
                        a = r.get("acct", "")
                        if a.startswith("Acct.") and a not in seen:
                            seen.add(a)
                            out.append(_entry(a, stmt._resolve_acct(a)))
                except Exception:
                    pass

        elif base == "BS":
            stmt = self._stmtInstance("BS")
            if stmt is not None:
                agg = stmt.taxAggregates() if hasattr(stmt, "taxAggregates") else {}
                for k in sorted(agg):
                    out.append(_entry(f"BS.{k}", agg[k]))
                try:
                    seen = set()
                    for r in stmt._rows:
                        a = r.get("acct", "")
                        if a.startswith("Acct.") and a not in seen:
                            seen.add(a)
                            out.append(_entry(a, stmt._resolve_acct(a)))
                except Exception:
                    pass

        elif base == "GL":
            stmt = self._stmtInstance("GL")
            if stmt is not None:
                try:
                    seen = set()
                    for r in stmt._rows:
                        a = r.get("acct", "")
                        if a.startswith("Acct.") and a not in seen:
                            seen.add(a)
                            v = stmt._resolve_acct(a) if hasattr(stmt, "_resolve_acct") else None
                            out.append(_entry(a, v))
                except Exception:
                    pass

        elif base == "Profile":
            stmt = self._stmtInstance("Profile")
            if stmt is not None:
                try:
                    for r in stmt.load():
                        nm = r.get("_rowNm", "")
                        if not nm:
                            continue
                        # Profile.Form8825 virtual source: entity fields only
                        # (form-8825-specific bookNS rows added from bookNS below)
                        if src == "Profile.Form8825" and not nm.startswith("Profile.entity."):
                            continue
                        out.append(_entry(nm, r.get("value")))
                except Exception:
                    pass

        # Append bookNS paths not yet covered (Cplx.*, novel paths, etc.)
        existing_paths = {x["path"] for x in out}
        for _fid, p in self.loadBookNS(base):
            if p and p not in existing_paths:
                vstr = ""
                try:
                    vstr = self.previewValue("", base, p)
                except Exception:
                    pass
                out.append({"path": p, "value": vstr,
                            "label": f"{p}  ({vstr})" if vstr else p})
                existing_paths.add(p)

        return sorted(out, key=lambda x: x["path"])

    def previewValue(self, fid: str,
                     src: Optional[str] = None,
                     path: Optional[str] = None) -> str:
        """Live value the resolver would emit *now* for the proposed
        ``(src, path)`` — or for the existing mapping at ``fid`` if
        ``src/path`` is None.

        Mirrors the resolver semantics of ``stmtOBJ_Tax.loadFillDict``:
          - ``Cplx`` / ``Cplx.*`` paths     → return ``COMPLEX_SENTINEL``
          - ``CHECK`` sentinel paths         → return ``CHECK_SENTINEL``
          - IS / BS / GL sources             → use ``_resolve_acct(path)``
          - Profile source (no ``_resolve_acct``) → fall back to ``.get(path)``
            which is what stmtProfile uses internally to walk
            ``Profile.entity.* / Profile.F1065.* / Profile.BookNS.*``.
        """
        fid = self._normalizeFid(fid)

        if src and path:
            # ── Sentinel paths first — match loadFillDict semantics so the
            # dialog shows 'Complex' / 'CHECK' instead of '(blank)'.
            if path == CHECK_SENTINEL or path == "CHECK":
                return CHECK_SENTINEL
            if isinstance(path, str) and (path == "Cplx" or path.startswith("Cplx.")):
                return COMPLEX_SENTINEL

            # ── If the proposed (src, path) IS the current bookNS row
            # for this fid, return the live value via _liveStatus.
            # This handles the dialog-open case where the dropdowns
            # are pre-populated from getMapping's bookNS field — the
            # preview MUST equal the live value the dialog already
            # showed, even when the chosen-source path doesn't itself
            # resolve (e.g. Profile.F1065.total_assets is in the
            # Profile bookNS but the actual value comes from BS via
            # the priority chain).
            for fid_raw, current_path in self.loadBookNS(src):
                if self._normalizeFid(fid_raw) == fid and current_path == path:
                    v, _ = self._liveStatus(fid)
                    return "" if v is None else str(v)

            stmt = self._stmtInstance(src)
            if stmt is None:
                return ""

            # ── Hypothetical path: try _resolve_acct (works for
            # IS / BS / GL).
            try:
                if hasattr(stmt, "_resolve_acct"):
                    v = stmt._resolve_acct(path)
                    if v is not None:
                        return str(v)
            except Exception:
                pass

            # ── Fallback: look up the fid in this source's loadFillDict.
            try:
                d = stmt.loadFillDict(self.formNm) or {}
                v = d.get(fid)
                return "" if v is None else str(v)
            except Exception:
                return ""

        # No proposed src+path — return the live value.
        v, _ = self._liveStatus(fid)
        return "" if v is None else str(v)

    def liveStatus(self, fid: str) -> Tuple[Optional[str], str]:
        return self._liveStatus(self._normalizeFid(fid))

    def getMapping(self, fid: str) -> Dict:
        """Single-fid view: namespace meta + bookNS row (if any) +
        custom map (if any) + live value/status."""
        fid = self._normalizeFid(fid)
        ns = self.loadNamespace()
        nsmeta = ns.get(self._nsKey(fid), {})

        bookNS_hit = None
        bookNS_src = None
        for src in AID_SOURCES:
            for fid_raw, path in self.loadBookNS(src):
                if self._normalizeFid(fid_raw) == fid:
                    bookNS_hit = path
                    bookNS_src = src
                    break
            if bookNS_hit is not None:
                break

        custom_hit = None
        custom_src = None
        for src in AID_SOURCES:
            cmd = self.loadCustomMapDict(src)
            if fid in cmd:
                custom_hit = cmd[fid]
                custom_src = src
                break

        in_chk = self.isInChkArray(fid)

        lv, ls = self._liveStatus(fid)
        return {
            "fid":          fid,
            "namespace":    nsmeta,
            "bookNS":       {"source": bookNS_src, "path": bookNS_hit} if bookNS_hit else None,
            "custom":       {"source": custom_src, "method": custom_hit} if custom_hit else None,
            "chk_array":    {
                "in_array":   in_chk,
                "source":     "Profile",
                "path":       f"Profile.{self._profileFormKey()}.chk",
                "fid_number": self._fidNum(fid),
            } if in_chk or self._fidNum(fid) is not None else None,
            "live_value":   "" if lv is None else lv,
            "live_status":  ls,
        }

    def listMappings(self) -> List[Dict]:
        """Union of bookNS hits and CustomMapDict hits (per §12 Q4 — only
        fids that ARE mapped, not all 440)."""
        ns = self.loadNamespace()
        rows: Dict[str, Dict] = {}
        for src in AID_SOURCES:
            for fid_raw, path in self.loadBookNS(src):
                fid = self._normalizeFid(fid_raw)
                if not fid:
                    continue
                if fid in rows:
                    continue
                nsmeta = ns.get(self._nsKey(fid), {})
                rows[fid] = {
                    "fid":       fid,
                    "kind":      "bookNS",
                    "source":    src,
                    "path":      path,
                    "shortName": nsmeta.get("shortName"),
                    "fType":     nsmeta.get("fType"),
                    "page":      nsmeta.get("page"),
                    "location":  nsmeta.get("location"),
                }
        for src in AID_SOURCES:
            for fid_raw, methodName in self.loadCustomMapDict(src).items():
                fid = self._normalizeFid(fid_raw)
                if not fid:
                    continue
                # CustomMap takes precedence over bookNS for display purposes.
                nsmeta = ns.get(self._nsKey(fid), {})
                rows[fid] = {
                    "fid":       fid,
                    "kind":      "custom",
                    "source":    src,
                    "path":      f"Custom.{fid}",
                    "method":    methodName,
                    "shortName": nsmeta.get("shortName"),
                    "fType":     nsmeta.get("fType"),
                    "page":      nsmeta.get("page"),
                    "location":  nsmeta.get("location"),
                }
        return [rows[k] for k in sorted(rows.keys(), key=self._fidSortKey)]

    # ── Write — bookNS ─────────────────────────────────────────
    def createMapping(self, fid: str, src: str, path: str) -> Dict:
        src = self._src_base(src)   # normalize Profile.Form8825 → Profile
        if src not in AID_SOURCES:
            raise ValueError(f"unknown source: {src!r}")
        fid = self._normalizeFid(fid)
        rows = self.loadBookNS(src)
        rows = [r for r in rows if self._normalizeFid(r[0]) != fid]
        rows.append([fid, path])
        rows.sort(key=lambda r: self._fidSortKey(self._normalizeFid(r[0])))
        self._writeBookNS(src, rows)
        self._refreshStmtInstances()
        return self.getMapping(fid)

    def editMapping(self, fid: str, src: str, path: str) -> Dict:
        """Delete-then-create across all sources (§5.3)."""
        src = self._src_base(src)
        fid = self._normalizeFid(fid)
        for s in AID_SOURCES:
            existing = self.loadBookNS(s)
            kept = [r for r in existing if self._normalizeFid(r[0]) != fid]
            if len(kept) != len(existing):
                self._writeBookNS(s, kept)
        return self.createMapping(fid, src, path)

    def deleteMapping(self, fid: str) -> Dict:
        fid = self._normalizeFid(fid)
        for src in AID_SOURCES:
            rows = self.loadBookNS(src)
            kept = [r for r in rows if self._normalizeFid(r[0]) != fid]
            if len(kept) != len(rows):
                self._writeBookNS(src, kept)
        # If a Custom entry exists, soft-delete it as well (M4 hook).
        for src in AID_SOURCES:
            cmd = self.loadCustomMapDict(src)
            if fid in cmd:
                try:
                    self.removeCustomMap(fid, src)
                except NotImplementedError:
                    # M4 still pending — tolerate; bookNS entry already removed.
                    pass
                break
        self._refreshStmtInstances()
        return self.getMapping(fid)

    # ── Write — custom map (M4 — Python source surgery) ────────
    def addCustomMap(self, fid: str, src: str, note: str = "") -> Dict:
        """Spec §6.2 ``add_cplx``.

        v0.1 ships this as a NotImplementedError so the route surfaces
        a clear message.  Implementation requires marker-region regex
        on ``ledger/stmt<src>.py`` (AID-MAPS / AID-CPLX), atomic
        re-write, and ``importlib.reload`` on the leaf module.

        See spec §6.2 / §6.3 / §6.4.  The Aid Flask layer maps the
        exception to HTTP 501 with a follow-up TODO.
        """
        raise NotImplementedError(
            "Custom-map source surgery (M4) — pending. "
            "Add the entry by hand to "
            f"ledger/stmt{src}.py:{self.formNm}_CustomMapDict and define "
            f"_Cplx_{self._normalizeFid(fid)}(self, formNm) on the "
            f"stmt{src}_Tax subclass.  See docs/LLC_BookToIRS_Aid.md §6."
        )

    def removeCustomMap(self, fid: str, src: str) -> Dict:
        """Spec §6.2 ``remove_cplx`` — soft-delete from CustomMapDict.
        v0.1 stub — see ``addCustomMap`` for context."""
        raise NotImplementedError(
            "Custom-map removal (M4) — pending.  Remove the entry from "
            f"stmt{src}_Tax.{self.formNm}_CustomMapDict by hand."
        )

    def relinkCustomMap(self, fid: str, src: str) -> Dict:
        """Spec §6.2 ``relink_cplx`` — re-add a soft-deleted entry."""
        raise NotImplementedError(
            "Custom-map relink (M4) — pending.  Add the entry back to "
            f"stmt{src}_Tax.{self.formNm}_CustomMapDict by hand."
        )

    # ── Regenerate FILL.pdf (the "Commit" button) ─────────────
    def _formClass(self):
        """Resolve the ``irs.<formNm>`` class for the current ``formNm``.

        Each tax form has its own ``irs/<formNm>.py`` module exporting a
        same-named ``irsForm`` subclass.  This helper does a dynamic
        import so the Aid stays multi-form aware without a hardcoded
        dispatch table — adding a new form (e.g. ``Sch_K1``) only
        requires writing ``irs/Sch_K1.py`` per the design spec."""
        import importlib
        mod = importlib.import_module(f"irs.{self.formNm}")
        return getattr(mod, self.formNm)

    def regenerate(self) -> Dict:
        """Re-run the BookToIRS pipeline against the current on-disk
        bookNS / CustomMapDict state for ``self.formNm``.  Returns
        ``{ fill_path, pdf_fields, filled, check, complex, blank, ts }``
        for single-form modes, or ``{ partners, paths, ts }`` for Sch_K1.
        """
        self._refreshStmtInstances()
        self._namespace_cache = None

        if self.formNm == "Sch_K1":
            return self._regenerate_k1()

        # Lazy imports — these pull pandas which is heavy.
        import pandas as pd

        formClass = self._formClass()
        form = formClass(llc=self.llc)
        sources_data = []
        for src in AID_SOURCES:
            stmt = self._stmtInstance(src)
            if stmt is None:
                sources_data.append((src, {}))
                continue
            try:
                sources_data.append((src, stmt.loadFillDict(self.formNm) or {}))
            except Exception:
                sources_data.append((src, {}))

        rows = []
        for src, d in sources_data:
            for fid, fval in d.items():
                rows.append({"fid": fid, "fval": fval, "source": src})
        df_book = pd.DataFrame(rows, columns=["fid", "fval", "source"])

        def has_val(v):
            if v is None: return False
            if isinstance(v, str): return v != ""
            try: return not pd.isna(v)
            except Exception: return True

        df_book["has_val"] = df_book["fval"].apply(has_val)
        df_book["_prio"]   = df_book["source"].map(AID_PRIO).fillna(99).astype(int)
        df_book = (df_book
                   .sort_values(["fid", "has_val", "_prio"],
                                ascending=[True, False, True])
                   .drop_duplicates("fid", keep="first")
                   .drop(columns=["has_val", "_prio"])
                   .reset_index(drop=True))

        df_fields = form.loadFieldsDF()
        df = df_fields.merge(df_book, on="fid", how="left")

        def _status(v):
            if isinstance(v, str) and v == COMPLEX_SENTINEL: return "complex"
            if isinstance(v, str) and v == CHECK_SENTINEL:   return "check"
            if v is None: return "blank"
            try:
                if pd.isna(v): return "blank"
            except Exception:
                pass
            if isinstance(v, str) and v == "": return "blank"
            return "filled"
        df["status"] = df["fval"].apply(_status)

        def _value(row):
            s = row["status"]
            if s == "filled":
                v = row["fval"]
                return v if isinstance(v, str) else f"{v}"
            if s == "check":   return CHECK_SENTINEL
            if s == "complex": return COMPLEX_SENTINEL
            return None
        df["value"] = df.apply(_value, axis=1)

        out_path = form.saveFILL_FromDF(df)
        return {
            "fill_path":  str(out_path),
            "pdf_fields": int(len(df)),
            "filled":     int((df["status"] == "filled" ).sum()),
            "check":      int((df["status"] == "check"  ).sum()),
            "complex":    int((df["status"] == "complex").sum()),
            "blank":      int((df["status"] == "blank"  ).sum()),
            "ts":         int(time.time()),
        }

    # ── Per-partner K-1 pipeline ───────────────────────────────
    def _loadOwnersForK1(self) -> List[Dict]:
        """Load llcOwners JSON list for the current LLC."""
        top     = os.path.expanduser(getattr(self.llc, "TOP", "") or "")
        acct    = getattr(self.llc, "dirAccounting", "") or ""
        llcName = getattr(self.llc, "objName", "") or ""
        fn      = Path(top) / acct / "Accts" / f"llcOwners_{llcName}.json"
        if not fn.exists():
            return []
        try:
            return json.loads(fn.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _regenerate_k1(self) -> Dict:
        """Generate one Sch_K1_FILL_{oID}.pdf per partner.

        Returns ``{ partners: [{oID, fill_path, filled, blank}], paths, ts }``.
        Uses ``stmtIS_TaxMember`` for direct fid-keyed fill values,
        bypassing Sch_K1_namespace.json's blank logicalKey index.
        """
        import pandas as pd
        from ledger.stmtIS import stmtIS_TaxMember
        import importlib

        owners = self._loadOwnersForK1()
        if not owners:
            return {"partners": [], "paths": [], "ts": int(time.time())}

        mod       = importlib.import_module("irs.Sch_K1")
        formClass = getattr(mod, "Sch_K1")
        form      = formClass(llc=self.llc)
        df_fields = form.loadFieldsDF()

        results: List[Dict] = []
        paths:   List[str]  = []

        for i, owner in enumerate(owners):
            oID = owner.get("oID", f"p{i}")

            stmt     = stmtIS_TaxMember(self.llc, partner_idx=i)
            fid_vals = stmt.loadFillDict("Sch_K1")

            rows = [{"fid": fid, "fval": fval, "source": "IS"}
                    for fid, fval in fid_vals.items()]
            df_book = pd.DataFrame(rows, columns=["fid", "fval", "source"]) \
                      if rows else pd.DataFrame(columns=["fid", "fval", "source"])

            df = df_fields.merge(df_book, on="fid", how="left")

            def _status(v):
                if v is None:
                    return "blank"
                try:
                    if pd.isna(v):
                        return "blank"
                except Exception:
                    pass
                if isinstance(v, str) and v == "":
                    return "blank"
                return "filled"

            def _value(row):
                if row["status"] == "filled":
                    v = row["fval"]
                    return v if isinstance(v, str) else str(v)
                return None

            df["status"] = df["fval"].apply(_status)
            df["value"]  = df.apply(_value, axis=1)

            out_path = form.saveFILL_FromDF(df, suffix=f"_{oID}")
            filled   = int((df["status"] == "filled").sum())
            blank    = int((df["status"] == "blank" ).sum())
            results.append({"oID": oID, "fill_path": str(out_path),
                             "filled": filled, "blank": blank})
            paths.append(str(out_path))

        return {"partners": results, "paths": paths, "ts": int(time.time())}

    # ── Advisory chips (§7) ────────────────────────────────────
    def adviseChips(self,
                    fid: str,
                    src: Optional[str]  = None,
                    path: Optional[str] = None) -> List[Dict]:
        chips: List[Dict] = []
        nfid = self._normalizeFid(fid)
        ns   = self.loadNamespace()
        nsmeta = ns.get(self._nsKey(nfid))

        if nsmeta is None:
            chips.append({
                "level": "error",
                "text":  f"fid {fid} is not in {self.formNm}_namespace.json — Save will still write",
            })
            return chips

        ftype = nsmeta.get("fType")
        # Output-type / fid-type mismatches.
        if path == CHECK_SENTINEL and ftype == "text":
            chips.append({"level": "warn", "text": "Will stamp 'X' as plain text"})
        if (path is not None and path not in (CHECK_SENTINEL, None)
                and ftype in ("checkBox", "checkText")):
            chips.append({"level": "warn", "text": "Field expects /Btn toggle"})

        # bookNS path may not resolve.
        if src and path and not str(path).startswith("Custom.") and path != CHECK_SENTINEL:
            try:
                stmt = self._stmtInstance(src)
                if stmt is not None and hasattr(stmt, "_resolve_acct"):
                    v = stmt._resolve_acct(path)
                    if v is None:
                        chips.append({
                            "level": "warn",
                            "text":  "Path will return None at run time",
                        })
            except Exception:
                chips.append({
                    "level": "warn",
                    "text":  "Could not preview value (resolver raised)",
                })

        # CustomMapDict already has this fid?
        for s in AID_SOURCES:
            cmd = self.loadCustomMapDict(s)
            if nfid in cmd:
                chips.append({
                    "level": "warn",
                    "text":  f"Will overwrite existing custom map "
                             f"({s}.{cmd[nfid]})",
                })
                break

        # Higher-priority bookNS source already maps this fid.
        for s in AID_SOURCES:
            if s == src:
                continue
            for fid_raw, _path in self.loadBookNS(s):
                if self._normalizeFid(fid_raw) == nfid:
                    if AID_PRIO.get(s, 99) < AID_PRIO.get(src or "ZZ", 99):
                        chips.append({
                            "level": "warn",
                            "text":  f"`{s}`-priority entry will mask this",
                        })
                    break
        return chips

    # ── Internals ──────────────────────────────────────────────
    @staticmethod
    def _fidNum(fid: Any) -> Optional[int]:
        """``F042`` / ``f42`` / ``42`` -> ``42``.  Returns None for
        non-numeric (e.g. ``F_business_code``)."""
        if fid is None:
            return None
        s = str(fid).strip()
        m = re.match(r"^[fF]?(\d+)$", s)
        return int(m.group(1)) if m else None

    def _profileFormKey(self) -> str:
        """Profile JSON section key for this form.
        Form1065 → 'F1065'; otherwise self.formNm verbatim."""
        return "F1065" if self.formNm == "Form1065" else self.formNm

    def _backupProfile(self) -> None:
        fp = self._profilePath()
        if not fp.exists():
            return
        backup_dir = fp.parent / ".profile_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = backup_dir / f"llcProfile_{self.llc.objName}_{ts}.json"
        target.write_bytes(fp.read_bytes())
        files = sorted(
            backup_dir.glob(f"llcProfile_{self.llc.objName}_*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        for old in files[BACKUP_KEEP:]:
            try:
                old.unlink()
            except Exception:
                pass

    @staticmethod
    def _normalizeFid(fid: Any) -> str:
        if fid is None:
            return ""
        s = str(fid).strip()
        if not s:
            return ""
        m = re.match(r"^[fF]?(\d+)$", s)
        if m:
            return f"F{int(m.group(1)):03d}"
        return s

    @staticmethod
    def _nsKey(fid: str) -> str:
        """``F042`` → ``f42`` (Form1065_namespace.json keys)."""
        m = re.match(r"^F(\d+)$", fid or "")
        if m:
            return f"f{int(m.group(1))}"
        return fid

    @staticmethod
    def _fidSortKey(fid: str):
        m = re.match(r"^F(\d+)$", fid or "")
        return (0, int(m.group(1))) if m else (1, fid)

    def _liveStatus(self, fid: str) -> Tuple[Optional[str], str]:
        """Walk the BookToIRS priority resolver for one fid.
        Returns (value, status) where status ∈ {filled, check, complex, blank}."""
        for src in AID_SOURCES:
            stmt = self._stmtInstance(src)
            if stmt is None:
                continue
            try:
                d = stmt.loadFillDict(self.formNm) or {}
            except Exception:
                continue
            v = d.get(fid)
            if v is None:
                continue
            sv = v if isinstance(v, str) else str(v)
            if sv == "":
                continue
            if sv == CHECK_SENTINEL:   return (sv, "check")
            if sv == COMPLEX_SENTINEL: return (sv, "complex")
            return (sv, "filled")
        return (None, "blank")

    def _writeBookNS(self, src: str, rows: List[List[str]]) -> None:
        fp = self._bookNSPath(src)
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as fh:
                try:
                    d = json.load(fh)
                except Exception:
                    d = {}
        else:
            d = {}
        # Backup before mutating.
        if fp.exists():
            self._backupBookNS(src)
        d[self.formNm] = [list(r) for r in rows]
        self._atomicWriteJSON(fp, d)

    @staticmethod
    def _atomicWriteJSON(fp: Path, payload: Any) -> None:
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = fp.with_suffix(fp.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(fp))

    def _backupBookNS(self, src: str) -> None:
        fp = self._bookNSPath(src)
        if not fp.exists():
            return
        backup_dir = self._backupDir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = backup_dir / f"bookNS_{src}_{ts}.json"
        target.write_bytes(fp.read_bytes())
        # Rotate — keep last BACKUP_KEEP per source.
        files = sorted(
            backup_dir.glob(f"bookNS_{src}_*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        for old in files[BACKUP_KEEP:]:
            try:
                old.unlink()
            except Exception:
                pass
