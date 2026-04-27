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
        
        # Resolve irsDir from the LLC object
        self.irsDir = Path(llc.acctDir(dirName="ye")) / "Forms_IRS"

        # Derived data directories
        # irsDir = …/AccountingData/<yr>/YE_Tax_Records/Forms_IRS
        try:
            self._root_dir  = self.irsDir.parents[4]           # LLC-WB-Group/
            self._accts_dir = self.irsDir.parents[2] / "Accts" # …/AccountingData/Accts/
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

        # ── Sort and assign sequential fIDs ─────────────────────────────
        sorted_list = sorted(raw_fields.values(), key=self._sortKey)
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
            location = self._deriveLocation(logical_key) if logical_key else \
                       f"{self.oID}.Pg{fi['page']}.Unknown"

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
                    writer.pages[pg_num - 1], fills, auto_regenerate=False)
                ok += len(fills)
            except Exception:
                for path, val in fills.items():
                    try:
                        writer.update_page_form_field_values(
                            writer.pages[pg_num - 1], {path: val},
                            auto_regenerate=False)
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
        for candidate in [
            self._root_dir / "llcProfile_WBGroupLLC.json",
            self._root_dir / "pages" / "AccountingData" / "llcProfile_WBGroupLLC.json",
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
        for candidate in [
            self._accts_dir / "llcOwners_WBGroupLLC.json",
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
        """Fill a worksheet copy of the IRS PDF: text→fID, checkBox/checkText→checked."""
        irs_path  = Path(self.FN())
        out_path  = self._nspacePdfFN()
        fields    = nSpaceDict.get("fields", {})

        reader = PdfReader(str(irs_path))
        writer = PdfWriter(clone_from=reader)

        text_page:  Dict[int, Dict[str, str]] = {}
        check_page: Dict[int, Dict[str, str]] = {}

        for fd in fields.values():
            ftype = fd.get("fType", "")
            page  = fd.get("page", 0)
            pdf_field = fd["pdfField"]
            if page < 1 or ftype in ("container", "image"):
                continue
            if ftype == "text":
                text_page.setdefault(page, {})[pdf_field] = fd["fID"]
            elif ftype in ("checkBox", "checkText"):
                check_page.setdefault(page, {})[pdf_field] = fd["checkedValue"]

        txt_ok = 0
        for pg, fills in text_page.items():
            try:
                writer.update_page_form_field_values(
                    writer.pages[pg - 1], fills, auto_regenerate=False)
                txt_ok += len(fills)
            except Exception:
                for path, val in fills.items():
                    try:
                        writer.update_page_form_field_values(
                            writer.pages[pg - 1], {path: val}, auto_regenerate=False)
                        txt_ok += 1
                    except Exception:
                        pass

        chk_ok = chk_err = 0
        for pg, fills in check_page.items():
            for path, val in fills.items():
                try:
                    writer.update_page_form_field_values(
                        writer.pages[pg - 1], {path: val}, auto_regenerate=False)
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

    def _deriveLocation(self, logical_key: str) -> str:
        """Return namespace location string; subclasses define LOCATION_RULES."""
        for pattern, location in self.LOCATION_RULES:
            if re.match(pattern, logical_key):
                return location
        return self._LOCATION_DEFAULT

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

