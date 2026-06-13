"""
irsForm.py
==========
Base class for all IRS form PDF services.

Simplified 4-step workflow
--------------------------
    1.  nspace   = form._buildNSpace()        # discover & classify every AcroForm field
    2.            form.saveNSpace(nspace)      # save namespace JSON + worksheet PDF
    3.  fillDict = form._buildFillDict(nspace) # assign publish flags + resolve values (one pass)
    4.            form.saveFILL(fillDict)       # write FILL.pdf  (+ saves fillDict JSON)

The old intermediate GLMap step is gone.  ``_buildFillDict`` is the single
authoritative pass: it receives the namespace, sets ``publish`` on every
field, and resolves live values for ``publish=True`` fields using the
official financial databases (IS/BS from stmtFinancialReport).

Field types (fType)
-------------------
  text      : alphanumeric text field  (/Tx in AcroForm)
  checkBox  : standard checkbox (shows X); /Btn with index [0] = Yes position
  checkText : No-answer checkbox (shows checkmark); /Btn with index [1] = No position
  image     : signature / image field  (/Sig)
  container : AcroForm group node — excluded from fillDict

publish flags
-------------
  True           : field is auto-filled from LLC financial data
  "CPA:unknown"  : field requires CPA / manual review; value left blank
  False          : field is not applicable / intentionally blank

fillDict field schema
---------------------
  {
    "fID":          str   — sequential field ID (f1, f2, …)
    "pdfField":     str   — full AcroForm path used by pypdf
    "shortName":    str   — leaf name without index, e.g. "f1_6"
    "logicalKey":   str   — human key, e.g. "P1_1a" (empty when unknown)
    "label":        str   — human description from FieldNames JSON
    "fType":        str   — text | checkBox | checkText | image
    "page":         int   — 1-based page number
    "location":     str   — section path, e.g. "Form1065.Pg1.Income"
    "checkedValue": str   — on-value for Btn fields, e.g. "/1" or "/2"
    "publish":      bool|str  — True | False | "CPA:unknown"
    "source":       str|None  — data source key: "entity"|"F1065"|"IS"|"BS"|"owners"|…
    "path":         str|None  — dotted key within that source, e.g. "rent_income"
    "note":         str   — human note / CPA instruction
    "value":        str   — resolved fill value ("" when publish ≠ True)
  }

File-naming convention (all outputs go to self.irsDir)
-------------------------------------------------------
  {oID}_IRS.pdf           — IRS blank template (input)
  {oID}_namespace.json    — field namespace
  {oID}_namespace.pdf     — worksheet PDF (fIDs + checked boxes)
  {oID}_fillDict.json     — complete fillDict with publish flags + values
  {oID}_FILL.pdf          — filled output PDF

Backward-compat aliases (deprecated — will be removed in a future release)
---------------------------------------------------------------------------
  _buildGLMap(nspace)  → _buildFillDict(nspace)
  saveGLMap(d)         → saveFillDict(d)
  _buildFILL(nspace)   → _buildFillDict(nspace)

Timestamp of last change: 2026.04.18
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader, PdfWriter


class irsForm:
    """
    Abstract base class for IRS form PDF services.

    Subclass and override:
      • LOCATION_RULES   — ordered list of (pattern, location_str) for deriving
                           a namespace location from a logicalKey.
      • _buildFillDict() — form-specific field-to-data mapping + value resolution.

    Parameters
    ----------
    llc : object
        LLC management object that exposes ``llc.acctDir(dirName='ye')``.
        ``self.irsDir`` is derived from it.
    verbose : bool
        Print progress messages during workflow steps.
    """

    # ── Subclass may override this list of (regex_pattern, location_str) ────
    LOCATION_RULES: List[Tuple[str, str]] = []

    # ── Default fallback location when no rule matches ───────────────────────
    _LOCATION_DEFAULT = "IRS.Unknown"

    def __init__(self, llc, **kwargs):
        
        self.oID     = self.__class__.__name__   # e.g. "Form1065", "Sch_K1"
        self.llc     = llc
        self.verbose = kwargs.get('verbose', False)
        if self.verbose:
            print(f"irsForm Entry: oID:{self.oID}, verbose:{self.verbose}") 
        
        # Resolve irsDir — prefer setup_paths.IRS_FORMS_DIR (books/<yr>/Forms/)
        # over the legacy YE_Tax_Records/Forms_IRS path.
        try:
            from ledger import setup_paths as _sp
            if _sp.IRS_FORMS_DIR:
                self.irsDir = Path(_sp.IRS_FORMS_DIR)
            else:
                self.irsDir = Path(llc.acctDir(dirName="ye")) / "Forms_IRS"
        except Exception:
            self.irsDir = Path(llc.acctDir(dirName="ye")) / "Forms_IRS"

        # irsDir = books/<yr>/Forms/
        # parents[0] = books/<yr>/   parents[1] = books/   parents[2] = repo root
        try:
            self._root_dir  = self.irsDir.parents[2]                  # LLC-WB-Group/
            self._accts_dir = self.irsDir.parents[1] / "Accts"        # books/Accts/ (shared)
        except IndexError:
            self._root_dir  = self.irsDir.parent
            self._accts_dir = self.irsDir.parent

    # ═══════════════════════════════════════════════════════════════════════
    #  FILE-NAME HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def FN(self) -> str:
        """Absolute path to the IRS blank template: irsDir/{oID}_IRS.pdf"""
        return str(self.irsDir / f"{self.oID}_IRS.pdf")

    def _nspaceFN(self) -> Path:
        return self.irsDir / f"{self.oID}_namespace.json"

    def _nspacePdfFN(self) -> Path:
        return self.irsDir / f"{self.oID}_namespace.pdf"

    def _fillDictFN(self) -> Path:
        return self.irsDir / f"{self.oID}_fillDict.json"

    def _glmapFN(self) -> Path:
        """Backward-compat alias → _fillDictFN()."""
        return self._fillDictFN()

    def _fillFN(self, suffix: str = "") -> Path:
        return self.irsDir / f"{self.oID}{suffix}_FILL.pdf"

    # ═══════════════════════════════════════════════════════════════════════
    #  STEP 1 — BUILD NAMESPACE
    # ═══════════════════════════════════════════════════════════════════════

    def _buildNSpace(self) -> Dict:
        """
        Read the IRS template PDF and build the namespace dict.

        Returns
        -------
        dict
            {
              "form": str,
              "source": str,
              "total_fields": int,
              "fields": {
                "f1": { fID, pdfField, shortName, logicalKey, label,
                        fType, page, location, checkedValue }, …
              }
            }
        """
        irs_path = Path(self.FN())
        if not irs_path.exists():
            raise FileNotFoundError(f"{self.oID} IRS template not found: {irs_path}")

        key_map   = self._loadKeyMap()
        label_map = self._loadLabelMap()

        # ── Read all AcroForm fields ─────────────────────────────────────
        rdr = PdfReader(str(irs_path))
        raw = rdr.get_fields() or {}

        raw_fields: Dict[str, Dict] = {}
        for fid, fobj in raw.items():
            ft       = str(fobj.get("/FT", "")).strip()
            short    = fid.split(".")[-1].split("[")[0]   # leaf without [n]
            page     = self._pageFromPath(fid)
            has_kids = fobj.get("/Kids") is not None

            # Determine fType
            if ft == "" and has_kids:
                ftype = "container"
            elif ft == "/Tx":
                ftype = "text"
            elif ft == "/Btn":
                # Yes/No distinction: [0] = Yes (checkBox), [1] = No (checkText)
                leaf  = fid.split(".")[-1]
                m_idx = re.search(r'\[(\d+)\]$', leaf)
                idx   = int(m_idx.group(1)) if m_idx else 0
                ftype = "checkText" if (short.startswith("c") and idx >= 1) else "checkBox"
            elif ft == "/Sig" or "sig" in short.lower():
                ftype = "image"
            else:
                ftype = "text"

            # Checked / on-value for button fields
            checked_value = "/1"
            if ftype in ("checkBox", "checkText"):
                states = fobj.get("/_States_", [])
                try:
                    on_vals = [str(s) for s in states if str(s) != "/Off"]
                    if on_vals:
                        checked_value = on_vals[0]
                except Exception:
                    pass

            raw_fields[fid] = {
                "pdfField":     fid,
                "shortName":    short,
                "fType":        ftype,
                "page":         page,
                "checkedValue": checked_value,
            }

        # ── Assign sequential fIDs in document (annotation) order ───────
        #
        # We rely on the iteration order of ``rdr.get_fields()`` — pypdf
        # walks the AcroForm tree depth-first, which matches the visual
        # top-to-bottom / left-to-right order the IRS authors use when
        # numbering ``f1_NN`` (text) and ``c1_NN`` (checkbox) fields.
        # The two counters interleave visually (e.g. on Page 1 the
        # sequence is …f1_16, c1_1..c1_5, c1_6[0..2], f1_17, f1_18,
        # c1_7..c1_9, f1_19…), and the iteration order preserves that
        # exactly.  Sorting by (page, text-before-button) — as the old
        # ``_sortKey`` did — broke this interleaving and pushed every
        # checkbox to the end of its page (c1_1 became f63 instead of
        # f17), erasing the Line G / Line H boxes from the visible
        # numbering.
        #
        # NOTE: container fields (AcroForm group nodes such as
        # ``topmostSubform[0]``, ``HeaderAddress_ReadOrder[0]``,
        # ``LinesA-C[0]``) are EXCLUDED from the sequential numbering.
        # They are not user-fillable; including them used to push the
        # first real text field to ``f2`` and break the bookNS author
        # convention "F001 = first text field".  Removing them from a
        # stable in-order traversal does not shift sibling order.
        sorted_list = [fi for fi in raw_fields.values()
                       if fi["fType"] != "container"]
        fields_ns: Dict[str, Dict] = {}

        for idx, fi in enumerate(sorted_list, start=1):
            fid       = f"f{idx}"
            short     = fi["shortName"]
            pdf_field = fi["pdfField"]
            ftype     = fi["fType"]

            # Logical key from keys PDF
            logical_key = key_map.get(short, "")

            if logical_key.startswith("/"):
                # Button on-value from keys PDF — synthesise logical key for
                # checkbox fields based on shortName + positional index
                if ftype in ("checkBox", "checkText") and short.startswith("c"):
                    leaf  = pdf_field.split(".")[-1]
                    m_idx = re.search(r'\[(\d+)\]$', leaf)
                    yn    = "No" if ftype == "checkText" else "Yes"
                    m_pg  = re.match(r'c(\d+)_(\d+)', short)
                    if m_pg:
                        logical_key = f"c{m_pg.group(1)}_{m_pg.group(2)}_{yn}"
                    else:
                        logical_key = ""
                else:
                    logical_key = ""

            label    = label_map.get(logical_key, "") if logical_key else ""
            # Try logical_key first (AcroForm); fall back to shortName (XFA sequential forms).
            location = (self._deriveLocation(logical_key) if logical_key
                        else self._deriveLocation(short)
                             or f"{self.oID}.Pg{fi['page']}.Unknown")

            fields_ns[fid] = {
                "fID":          fid,
                "pdfField":     pdf_field,
                "shortName":    short,
                "logicalKey":   logical_key,
                "label":        label,
                "fType":        ftype,
                "page":         fi["page"],
                "location":     location,
                "checkedValue": fi["checkedValue"],
            }

        nSpaceDict = {
            "form":         self.oID,
            "source":       irs_path.name,
            "total_fields": len(fields_ns),
            "fields":       fields_ns,
        }
        return nSpaceDict

    def saveNSpace(self, nSpaceDict: Dict) -> None:
        """Save namespace to JSON and write the worksheet PDF."""
        out_json = self._nspaceFN()
        self.irsDir.mkdir(parents=True, exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(nSpaceDict, fh, indent=2, ensure_ascii=False)
        if self.verbose:
            print(f"  ✅ namespace JSON  → {out_json.name}  ({nSpaceDict['total_fields']} fields)")

        self._saveWorksheetPDF(nSpaceDict)

    # ═══════════════════════════════════════════════════════════════════════
    #  STEP 2 — BUILD FILL DICT  (combined GLMap + value resolution)
    # ═══════════════════════════════════════════════════════════════════════

    def _buildFillDict(self, nSpaceDict: Dict) -> Dict:
        """
        Base implementation: build a complete fillDict from the namespace.

        Every non-container field is included.  In the base class every field
        gets ``publish=False`` and ``value=""``.  Subclasses override this
        method to:
          • set ``publish=True`` for fields with known GL/IS/BS mappings,
          • set ``publish="CPA:unknown"`` for fields needing accountant review,
          • resolve live ``value`` strings for ``publish=True`` fields.

        Parameters
        ----------
        nSpaceDict : dict
            Output of ``_buildNSpace()``.

        Returns
        -------
        dict  { fID: { fID, pdfField, shortName, logicalKey, label, fType,
                       page, location, checkedValue,
                       publish, source, path, note, value } }
        """
        print(f"irsForm.{self.oID} buildFillDict Entry")
        fields = nSpaceDict.get("fields", {})
        fillDict: Dict[str, Dict] = {}

        for fid, fd in fields.items():
            ftype = fd.get("fType", "")
            if ftype == "container":
                continue
            fillDict[fid] = {
                "fID":          fid,
                "pdfField":     fd.get("pdfField", ""),
                "shortName":    fd.get("shortName", ""),
                "logicalKey":   fd.get("logicalKey", ""),
                "label":        fd.get("label", ""),
                "fType":        ftype,
                "page":         fd.get("page", 0),
                "location":     fd.get("location", ""),
                "checkedValue": fd.get("checkedValue", ""),
                "publish":      False,
                "source":       None,
                "path":         None,
                "note":         "",
                "value":        "",
            }
        return fillDict

    def saveFillDict(self, fillDict: Dict) -> None:
        """
        Save the complete fillDict to ``{oID}_fillDict.json``.

        The JSON wraps the field dict with a ``meta`` summary (total,
        published, cpa_unknown, empty counts).
        """
        out_path = self._fillDictFN()
        self.irsDir.mkdir(parents=True, exist_ok=True)

        published   = sum(1 for v in fillDict.values() if v.get("publish") is True)
        cpa_unknown = sum(1 for v in fillDict.values() if v.get("publish") == "CPA:unknown")
        empty       = len(fillDict) - published - cpa_unknown

        wrapper = {
            "meta": {
                "form":        self.oID,
                "generated":   date.today().isoformat(),
                "total":       len(fillDict),
                "published":   published,
                "cpa_unknown": cpa_unknown,
                "empty":       empty,
            },
            "fields": fillDict,
        }
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(wrapper, fh, indent=2, ensure_ascii=False)
        if self.verbose:
            print(f"  ✅ fillDict JSON   → {out_path.name}  "
                  f"(published={published}, cpa={cpa_unknown}, blank={empty})")

    # ── Backward-compat aliases (deprecated) ────────────────────────────
    def _buildGLMap(self, nSpaceDict: Dict) -> Dict:
        """Deprecated — calls _buildFillDict(nSpaceDict)."""
        return self._buildFillDict(nSpaceDict)

    def saveGLMap(self, glMapDict: Dict) -> None:
        """Deprecated — calls saveFillDict(glMapDict)."""
        self.saveFillDict(glMapDict)

    def _buildFILL(self, nSpaceDict: Dict, **kwargs) -> Dict:
        """Deprecated — calls _buildFillDict(nSpaceDict)."""
        return self._buildFillDict(nSpaceDict)

    # ═══════════════════════════════════════════════════════════════════════
    #  STEP 3 — WRITE FILL PDF
    # ═══════════════════════════════════════════════════════════════════════

    def saveFILL(self, fillDict: Dict, suffix: str = "") -> str:
        """
        Write the filled PDF using all fields where ``publish=True`` and
        ``value`` is non-empty.  Also saves the fillDict JSON automatically.

        Parameters
        ----------
        fillDict : dict
            Complete output of ``_buildFillDict()``.
        suffix : str
            Optional filename suffix (e.g. "_F001" for partner K-1 variants).

        Returns
        -------
        str  Absolute path of the written PDF.
        """
        # Auto-save the fillDict JSON alongside the PDF
        self.saveFillDict(fillDict)

        irs_path = Path(self.FN())
        if not irs_path.exists():
            raise FileNotFoundError(f"IRS template not found: {irs_path}")

        out_path = self._fillFN(suffix)

        reader = PdfReader(str(irs_path))
        writer = PdfWriter(clone_from=reader)

        # Group fills by page — only publish=True with non-empty value
        page_fills: Dict[int, Dict[str, str]] = {}
        for fd in fillDict.values():
            if fd.get("publish") is not True:
                continue
            val = fd.get("value", "")
            if val is None or val == "":
                continue
            pg        = fd.get("page", 1)
            pdf_field = fd["pdfField"]
            page_fills.setdefault(pg, {})[pdf_field] = str(val)

        ok = err = 0
        for pg_num, fills in page_fills.items():
            if pg_num < 1:
                continue
            try:
                writer.update_page_form_field_values(
                    writer.pages[pg_num - 1], fills, auto_regenerate=True)
                ok += len(fills)
            except Exception:
                for path, val in fills.items():
                    try:
                        writer.update_page_form_field_values(
                            writer.pages[pg_num - 1], {path: val},
                            auto_regenerate=True)
                        ok += 1
                    except Exception:
                        err += 1

        writer.set_need_appearances_writer(True)
        with open(out_path, "wb") as fh:
            writer.write(fh)

        if self.verbose:
            print(f"  ✅ FILL PDF        → {out_path.name}  "
                  f"({ok} fields written, {err} errors)")
        return str(out_path)

    # ═══════════════════════════════════════════════════════════════════════
    #  DATA-LOADING HELPERS  (shared across subclasses)
    # ═══════════════════════════════════════════════════════════════════════

    def _loadProfile(self) -> Tuple[Dict, Dict]:
        """
        Load llcProfile JSON.

        Returns (entity_data, f1065_data).  Handles the concatenated dual-JSON
        format used by llcProfile_WBGroupLLC.json.
        """
        llc_nm = getattr(self.llc, 'objName', 'WBGroupLLC')
        for candidate in [
            self._accts_dir / f"llcProfile_{llc_nm}.json",
            self._root_dir / f"llcProfile_{llc_nm}.json",
            self._root_dir / "pages" / "AccountingData" / f"llcProfile_{llc_nm}.json",
        ]:
            if candidate.exists():
                profile_path = candidate
                break
        else:
            return {}, {}

        raw = profile_path.read_text(encoding="utf-8")
        try:
            profile = json.loads(raw)
        except json.JSONDecodeError:
            m = re.match(r'(\{.*?\})\s*\{', raw, re.DOTALL)
            try:
                profile = json.loads(m.group(1)) if m else {}
            except Exception:
                profile = {}

        entity = profile.get("entity", {})
        f1065  = profile.get("F1065",  {})

        year = profile.get("YEAR", 2025)
        if not f1065.get("tax_year"):
            f1065["tax_year"] = str(year)[2:]

        return entity, f1065

    def _loadOwners(self) -> List[Dict]:
        """Load llcOwners JSON, returns list of owner dicts."""
        llc_nm = getattr(self.llc, 'objName', 'WBGroupLLC')
        for candidate in [
            self._accts_dir / f"llcOwners_{llc_nm}.json",
        ]:
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return []

    def _fmt(self, v: Any) -> Optional[str]:
        """Format a raw GL/BS/IS value as a PDF-ready string."""
        if v is None:
            return None
        if isinstance(v, float):
            return f"{v:,.2f}" if v != 0.0 else ""
        if isinstance(v, int):
            return str(v) if v != 0 else ""
        s = str(v).strip()
        return s if s else None

    def _resolve(self, source: str, path: str, src_map: Dict) -> Optional[str]:
        """Walk a dotted key path within the named source dict."""
        obj = src_map.get(source, {}) or {}
        for key in path.split("."):
            if not isinstance(obj, dict):
                return None
            obj = obj.get(key)
        return self._fmt(obj)

    # ═══════════════════════════════════════════════════════════════════════
    #  INTERNAL PDF / KEY-MAP HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _loadKeyMap(self) -> Dict[str, str]:
        """
        Load the keys PDF (shortName → logicalKey or on-value).
        Filename: {oID}-keys.pdf or legacy Form_{formNum}-keys.pdf.
        """
        candidates = [
            self.irsDir / f"{self.oID}-keys.pdf",
            self.irsDir / f"Form_{self.oID[4:]}-keys.pdf" if self.oID.startswith("Form") else None,
            self.irsDir / "Schedule_K_1-keys.pdf" if "K1" in self.oID or "K_1" in self.oID else None,
        ]
        for p in candidates:
            if p and p.exists():
                keys_path = p
                break
        else:
            if self.verbose:
                print(f"  ⚠️  Keys PDF not found for {self.oID} — logicalKeys will be empty")
            return {}

        try:
            rdr = PdfReader(str(keys_path))
            raw = rdr.get_fields() or {}
            km: Dict[str, str] = {}
            for fid, fobj in raw.items():
                v = fobj.get("/V")
                if v is None:
                    continue
                v_str = str(v).strip()
                if v_str and v_str != "/Off":
                    short = fid.split(".")[-1].split("[")[0]
                    km[short] = v_str
            return km
        except Exception as exc:
            if self.verbose:
                print(f"  ⚠️  Keys PDF read error ({keys_path.name}): {exc}")
            return {}

    def _loadLabelMap(self) -> Dict[str, str]:
        """Load {oID}-FieldNames.json (logicalKey → label)."""
        candidates = [
            self.irsDir / f"{self.oID}-FieldNames.json",
            self.irsDir / f"Form_{self.oID[4:]}-FieldNames.json" if self.oID.startswith("Form") else None,
            self.irsDir / "Schedule_K_1-FieldNames.json" if "K1" in self.oID else None,
        ]
        for p in candidates:
            if p and p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return {str(k): str(v) for k, v in data.items()}
                except Exception:
                    pass
        if self.verbose:
            print(f"  ⚠️  FieldNames JSON not found for {self.oID} — labels will be empty")
        return {}

    def _saveWorksheetPDF(self, nSpaceDict: Dict) -> None:
        """Fill a worksheet copy of the IRS PDF: text→fID, checkBox/checkText→checked.

        Multi-line text fields are stamped with ``"<fid>\\n_xx"`` once per
        extra line so the operator can visually distinguish a multi-line
        cell from a single-line cell when reading the namespace.pdf —
        e.g. a 24pt-tall multi-line ``f3`` shows as::

            f3
            _xx

        rather than just ``f3`` (which would be ambiguous between a
        single-line field and a multi-line field with one row used).
        """
        irs_path  = Path(self.FN())
        out_path  = self._nspacePdfFN()
        fields    = nSpaceDict.get("fields", {})

        reader = PdfReader(str(irs_path))
        writer = PdfWriter(clone_from=reader)

        # ── Multi-line detection (FIX 2) ─────────────────────────────────
        # Walk every page's /Annots once and record the visible line count
        # for each text widget.  Indexed by the fully-qualified PDF field
        # path that the namespace also uses.
        SINGLE_LINE_PT = 12.0
        MULTILINE_BIT  = 1 << 12      # PDF spec Tx field flags, bit 13
        line_count: Dict[str, int] = {}
        for page in reader.pages:
            annots = page.get("/Annots")
            if annots is None:
                continue
            try:
                annots = annots.get_object()
            except Exception:
                pass
            try:
                annots_iter = list(annots)
            except Exception:
                continue
            for a_ref in annots_iter:
                try:
                    a = a_ref.get_object()
                except Exception:
                    continue
                if str(a.get("/Subtype") or "") != "/Widget":
                    continue
                # Walk parent for /FT, /Ff
                ft = a.get("/FT"); ff = a.get("/Ff")
                cur = a
                while (ft is None or ff is None) and cur is not None:
                    par = cur.get("/Parent")
                    cur = par.get_object() if par is not None else None
                    if cur is not None:
                        if ft is None: ft = cur.get("/FT")
                        if ff is None: ff = cur.get("/Ff")
                if str(ft or "") != "/Tx":
                    continue
                try:
                    ff_int = int(ff) if ff is not None else 0
                except Exception:
                    ff_int = 0
                if not (ff_int & MULTILINE_BIT):
                    continue
                rect = a.get("/Rect")
                if rect is None:
                    continue
                try:
                    x0, y0, x1, y1 = [float(v) for v in list(rect)]
                except Exception:
                    continue
                lines = max(1, round((y1 - y0) / SINGLE_LINE_PT))
                if lines <= 1:
                    continue
                # Build the fully-qualified path for this widget.
                parts: List[str] = []
                cur = a; seen: set = set()
                while cur is not None and id(cur) not in seen:
                    seen.add(id(cur))
                    t = cur.get("/T")
                    if t is not None:
                        parts.append(str(t))
                    par = cur.get("/Parent")
                    cur = par.get_object() if par is not None else None
                full = ".".join(reversed(parts))
                if full:
                    line_count[full] = lines

        text_page:  Dict[int, Dict[str, str]] = {}
        check_page: Dict[int, Dict[str, str]] = {}

        for fd in fields.values():
            ftype = fd.get("fType", "")
            page  = fd.get("page", 0)
            pdf_field = fd["pdfField"]
            if page < 1 or ftype in ("container", "image"):
                continue
            if ftype == "text":
                fid_label = fd["fID"]
                n_lines   = line_count.get(pdf_field, 1)
                stamp     = (fid_label + "\n" + "\n".join(["_xx"] * (n_lines - 1))
                             if n_lines > 1 else fid_label)
                text_page.setdefault(page, {})[pdf_field] = stamp
            elif ftype in ("checkBox", "checkText"):
                check_page.setdefault(page, {})[pdf_field] = fd["checkedValue"]

        txt_ok = 0
        for pg, fills in text_page.items():
            try:
                writer.update_page_form_field_values(
                    writer.pages[pg - 1], fills, auto_regenerate=True)
                txt_ok += len(fills)
            except Exception:
                for path, val in fills.items():
                    try:
                        writer.update_page_form_field_values(
                            writer.pages[pg - 1], {path: val}, auto_regenerate=True)
                        txt_ok += 1
                    except Exception:
                        pass

        chk_ok = chk_err = 0
        for pg, fills in check_page.items():
            for path, val in fills.items():
                try:
                    writer.update_page_form_field_values(
                        writer.pages[pg - 1], {path: val}, auto_regenerate=True)
                    chk_ok += 1
                except Exception:
                    chk_err += 1

        writer.set_need_appearances_writer(True)
        with open(out_path, "wb") as fh:
            writer.write(fh)

        total_check = sum(len(v) for v in check_page.values())
        if self.verbose:
            print(f"  ✅ namespace PDF   → {out_path.name}  "
                  f"(text={txt_ok}, checkBox={chk_ok}/{total_check})")

    @staticmethod
    def _pageFromPath(pdf_field: str) -> int:
        """Extract 1-based page number from XFA field path."""
        m = re.search(r'Page(\d+)\[', pdf_field)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _sortKey(field_info: Dict) -> tuple:
        """Sort by (page, page_seq, text-before-button, field_seq)."""
        page  = field_info["page"]
        short = field_info["shortName"]
        m     = re.match(r'^([a-z]+)(\d+)_(\d+)$', short)
        if m:
            prefix  = 0 if m.group(1) == "f" else 1
            seq_pg  = int(m.group(2))
            seq_num = int(m.group(3))
            return (page, seq_pg, prefix, seq_num)
        return (page, 999, 0, 0)

    def _deriveLocation(self, key: str) -> str:
        """Return namespace location string, or '' if no rule matches.

        Tries each (pattern, location) in LOCATION_RULES against ``key``.
        Returns the matched location string, or empty string when no rule matches
        (lets callers distinguish 'matched' from 'no match' before applying the
        per-page Unknown fallback).
        """
        for pattern, location in self.LOCATION_RULES:
            if re.match(pattern, key):
                return location
        return ""

    def _to_PDF(self, **kwargs):
        print(f"irsForm.{self.oID} _to_PDF Entry")
        
        if self.verbose:
            print("---- irsForm._to_PDF Entry")
        # ── Step 1 — Namespace ─────────────────────────────────────────
        #    Reads Form1065-IRS.pdf, discovers all 500 AcroForm fields,
        #    writes Form1065_namespace.json + Form1065_namespace.pdf
        nspaceDict = self._buildNSpace()
        if self.verbose:
            print("nSpace Created", nspaceDict.keys())
        self.saveNSpace(nspaceDict)
        
        # ── Step 2 — GL Map ────────────────────────────────────────────
        #    Maps every field to LLC data source + publish flag.
        #    Sched B Yes/No pairs → No checkText fields default to publish=True.
        #    Writes Form1065_GLMap.json
        #glmapDict = self._buildGLMap(nspaceDict)
        #print(f"glmap Created fields: {len(glmapDict.keys())}")
        #self.saveGLMap(glmapDict)
        
        # ── Step 3 — Fill Dict ─────────────────────────────────────────
        #    Resolves all publish=True fields to their fill values.
        #    Text fields: entity / F1065 / IS / BS / owners → string values
        #    Sched B No boxes: checkedValue from GLMap ("/2" etc.)
        fillDict = self._buildFillDict(nspaceDict, **kwargs) #is_data=is_data, bs_data=bs_data)
        if self.verbose:
            tstFld = kwargs.get('testField', None)
            if tstFld :
                print(f"{self.oID} _to_PDF (testField) {fillDict[tstFld]['value']}")
        
        # ── Step 4 — Write FILL PDF ───────────────────────────────────
        #    Writes Form1065_FILL.pdf  (99 fields, 0 errors)
        out_path = self.saveFILL(fillDict)
        print(f"\n  → {out_path}")
        return fillDict

    # ═══════════════════════════════════════════════════════════════════════
    #  PUBLIC API — irsBookToIRS / pandas-driven Book→IRS pipeline
    #
    #  These helpers exist so callers (e.g. notebooks, batch pipelines) can
    #  drive the FILL.pdf entirely with normalized fids and a DataFrame —
    #  without ever reaching into self.irsDir / namespace JSON / template
    #  PDF paths themselves.  The caller never needs to know whether the
    #  PDF lives, what the namespace file is named, or how to mutate
    #  AcroForm objects: it just supplies a DataFrame keyed by ``fid``.
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def normalizeFid(fid: Any) -> str:
        """
        Canonical IRS-form fid form.

            f1, F1, 1   → "F001"
            f016, F016  → "F016"
            F_K1_ein    → "F_K1_ein"  (non-numeric tokens pass through)
            None / ""   → ""
        """
        if fid is None:
            return ""
        s = str(fid).strip()
        if not s:
            return ""
        m = re.match(r"^[fF]?(\d+)$", s)
        if m:
            return f"F{int(m.group(1)):03d}"
        return s

    def loadFieldsDF(self):
        """
        Return a pandas DataFrame describing every fillable AcroForm field
        on the IRS template, with normalized ``fid`` values.

        Columns
        -------
            fid          : str   normalized fid  (e.g. "F001")
            pdf_fid      : str   original sequential fid from namespace ("f1")
            pdfField     : str   full AcroForm path used by pypdf
            shortName    : str   leaf name (e.g. "f1_06")
            fType        : str   namespace-classified type
                                   ('text'|'checkBox'|'checkText'|'image')
            pdfFT        : str   underlying AcroForm /FT  ('/Tx'|'/Btn'|...)
            page         : int   1-based page number
            checkedValue : str   on-value name for /Btn fields (e.g. "/1");
                                   empty for /Tx text fields

        ``container`` rows (group nodes) are excluded — they are not
        writable and would only pollute the merge.

        The namespace JSON is loaded from disk if it exists; otherwise the
        namespace is built from the IRS template PDF on the fly.
        """
        import pandas as pd

        ns_path = self._nspaceFN()
        if not ns_path.exists():
            raise FileNotFoundError(
                f"{self.oID}_namespace.json not found at {ns_path}. "
                "Run the form pipeline once to generate it, or call "
                "form._buildNSpace() + form.saveNSpace() explicitly."
            )
        with open(ns_path, "r", encoding="utf-8") as fh:
            ns = json.load(fh)

        # Underlying AcroForm /FT — only available by reading the PDF.
        irs_path = Path(self.FN())
        pdf_real: Dict[str, Dict] = {}
        if irs_path.exists():
            try:
                pdf_real = PdfReader(str(irs_path)).get_fields() or {}
            except Exception:
                pdf_real = {}

        rows: List[Dict[str, Any]] = []
        for pdf_fid, fld in (ns.get("fields") or {}).items():
            ftype = fld.get("fType", "text")
            if ftype == "container":
                continue
            pdfField = fld.get("pdfField") or ""
            real     = pdf_real.get(pdfField) or {}
            rows.append({
                "fid":          self.normalizeFid(pdf_fid),
                "pdf_fid":      pdf_fid,
                "pdfField":     pdfField,
                "shortName":    fld.get("shortName"),
                "fType":        ftype,
                "pdfFT":        str(real.get("/FT") or "") or None,
                "page":         int(fld.get("page") or 0),
                "checkedValue": fld.get("checkedValue") or "",
                "location":     fld.get("location") or "",
            })
        return pd.DataFrame(rows)

    # Sentinel value for "this checkbox should be ticked".  loadFillDict()
    # implementations emit this for fids that should turn /Btn fields ON.
    CHECK_SENTINEL = "CHECK"

    def saveFILL_FromDF(self, df, suffix: str = "") -> str:
        """
        Write ``{oID}{suffix}_FILL.pdf`` from a DataFrame.

        Required columns
        ----------------
            pdfField     : str     AcroForm path
            page         : int     1-based page
            pdfFT        : str     underlying field type ('/Tx', '/Btn', ...)
            value        : str|None  value to write; rows where ``value`` is
                                      None / NaN / "" are left blank.
            checkedValue : str     (optional, /Btn only) on-value to stamp
                                      when ``value`` == ``CHECK_SENTINEL``;
                                      defaults to ``"/1"`` if absent.

        Behaviour
        ---------
        * /Tx text fields receive ``str(value)``; numeric values are coerced.
        * /Btn checkbox fields are toggled ON only when ``value`` equals the
          sentinel ``"CHECK"``.  Any other string on a /Btn is ignored —
          this prevents the pypdf NameObject corruption that otherwise
          occurs when arbitrary strings are pushed onto checkbox /AS slots.
        * Other PDF field types are skipped.
        * Returns the absolute path of the written PDF.
        """
        import pandas as pd
        import math
        from pypdf.generic import NameObject, BooleanObject

        irs_path = Path(self.FN())
        if not irs_path.exists():
            raise FileNotFoundError(f"IRS template not found: {irs_path}")

        out_path = self._fillFN(suffix)
        reader   = PdfReader(str(irs_path))
        writer   = PdfWriter(clone_from=reader)

        page_text_fills: Dict[int, Dict[str, str]] = {}
        # checkbox stamps  →  list of (pdfField, on_value)  (page-agnostic)
        check_stamps: List[Tuple[str, str]] = []
        ok_text  = 0
        ok_check = 0
        for _, row in df.iterrows():
            v = row.get("value")
            if v is None:
                continue
            try:
                if isinstance(v, float) and math.isnan(v):
                    continue
            except Exception:
                pass
            sv = v if isinstance(v, str) else str(v)
            if sv == "":
                continue

            ft   = str(row.get("pdfFT") or "")
            path = row.get("pdfField") or ""
            pg   = int(row.get("page") or 0)
            if not path:
                continue

            if ft == "/Tx":
                if pg < 1:
                    continue
                # On a text field, the CHECK sentinel becomes an "X"
                # mark — IRS forms encode several "checkbox" choices
                # (Form 1065 boxes G / H / K) as plain text fields where
                # the taxpayer hand-marks an X.
                if sv == self.CHECK_SENTINEL:
                    sv = "X"
                page_text_fills.setdefault(pg, {})[path] = sv
                ok_text += 1
            elif ft == "/Btn":
                # Only the 'CHECK' sentinel toggles a checkbox ON.
                if sv != self.CHECK_SENTINEL:
                    continue
                cv = row.get("checkedValue") or "/1"
                cv = str(cv) if cv else "/1"
                if not cv.startswith("/"):
                    cv = "/" + cv
                check_stamps.append((path, cv))
                ok_check += 1
            # else: skip image / signature / unknown

        # ── text stamps ──────────────────────────────────────────────────
        # auto_regenerate=True is required so pypdf rebuilds each field's
        # appearance stream (/AP) after setting /V.  Without it, deeply
        # nested fields (Form 8825's Table_Line1.RowA.Col_a.f1_3 etc.)
        # store /V correctly but render as visually blank in viewers
        # like Preview / PDF.js because the cached appearance stream
        # still reflects the empty state.  set_need_appearances_writer
        # below catches the rest.
        for pg_num, fills in page_text_fills.items():
            if pg_num < 1 or pg_num > len(writer.pages):
                continue
            writer.update_page_form_field_values(
                writer.pages[pg_num - 1], fills, auto_regenerate=True,
            )

        # ── checkbox stamps ──────────────────────────────────────────────
        # Walk every page's annotations once and toggle /V + /AS for any
        # /Btn whose fully-qualified field path matches a CHECK sentinel.
        stamped = 0
        if check_stamps:
            stamp_by_path: Dict[str, str] = {p: v for p, v in check_stamps}
            for page in writer.pages:
                annots = page.get("/Annots")
                if annots is None:
                    continue
                # /Annots is typically an IndirectObject wrapping an ArrayObject
                try:
                    annots = annots.get_object()
                except Exception:
                    pass
                try:
                    annots_iter = list(annots)
                except Exception:
                    continue
                for annot_ref in annots_iter:
                    try:
                        annot = annot_ref.get_object()
                    except Exception:
                        continue
                    if str(annot.get("/Subtype") or "") != "/Widget":
                        continue
                    # Build fully-qualified field name by walking /Parent.
                    parts: List[str] = []
                    cur = annot
                    seen: set = set()
                    while cur is not None and id(cur) not in seen:
                        seen.add(id(cur))
                        t = cur.get("/T")
                        if t is not None:
                            parts.append(str(t))
                        par = cur.get("/Parent")
                        if par is None:
                            cur = None
                        else:
                            try:
                                cur = par.get_object()
                            except Exception:
                                cur = None
                    full = ".".join(reversed(parts))
                    if not full:
                        continue
                    on_val = stamp_by_path.get(full)
                    if on_val is None:
                        continue
                    try:
                        annot[NameObject("/V")]  = NameObject(on_val)
                        annot[NameObject("/AS")] = NameObject(on_val)
                        # Some /Btn widgets store the value on the parent
                        # field node (the leaf only carries /AS).  Mirror
                        # /V onto the parent so AcroForm consumers see the
                        # field as toggled.
                        par = annot.get("/Parent")
                        if par is not None:
                            try:
                                par_obj = par.get_object()
                                par_obj[NameObject("/V")] = NameObject(on_val)
                            except Exception:
                                pass
                        stamped += 1
                    except Exception:
                        pass

        # ── inject empty /Off appearances for orphan /Btn widgets ───────────
        # Some IRS PDF checkboxes (e.g. Form 1065 c3_4[0]) have /AP/N with
        # only a "/1" (on) stream and no "/Off" stream.  PDF viewers that
        # can't find a matching Off appearance fall back to rendering the
        # only stream present — showing a phantom checkmark even when the
        # field is /Off.  Inject a minimal blank stream for those widgets.
        _EMPTY_AP = b"q Q"   # valid PDF content stream: push/pop graphics state
        phantom_cleared = 0
        try:
            from pypdf.generic import DecodedStreamObject, DictionaryObject, ArrayObject
            for page in writer.pages:
                annots = page.get("/Annots")
                if annots is None:
                    continue
                try:
                    annots = annots.get_object()
                    annot_list = list(annots)
                except Exception:
                    continue
                for annot_ref in annot_list:
                    try:
                        annot = annot_ref.get_object()
                        if str(annot.get("/Subtype") or "") != "/Widget":
                            continue
                        if str(annot.get("/FT") or "") != "/Btn":
                            continue
                        cur_as = str(annot.get("/AS") or "")
                        if cur_as not in ("/Off", ""):
                            continue  # field is on — don't touch it
                        ap = annot.get("/AP")
                        if ap is None:
                            continue
                        ap_obj = ap.get_object()
                        n_dict = ap_obj.get("/N")
                        if n_dict is None:
                            continue
                        n_obj = n_dict.get_object() if hasattr(n_dict, "get_object") else n_dict
                        if not hasattr(n_obj, "get"):
                            continue
                        if NameObject("/Off") in n_obj:
                            continue  # already has an Off appearance
                        # Build a minimal empty stream and inject it
                        empty_stream = DecodedStreamObject()
                        empty_stream.set_data(_EMPTY_AP)
                        n_obj[NameObject("/Off")] = empty_stream
                        phantom_cleared += 1
                    except Exception:
                        pass
        except Exception:
            pass

        writer.set_need_appearances_writer(True)
        with open(out_path, "wb") as fh:
            writer.write(fh)

        if self.verbose:
            print(f"  ✅ FILL PDF (DF)  → {out_path.name}  "
                  f"({ok_text} text + {stamped} checkbox toggled / "
                  f"{ok_check} requested, {phantom_cleared} phantom /Off injected)")
        return str(out_path)

