"""
irsNspace.py
===================
Given an IRS PDF template (e.g. 'Form1065-IRS.pdf'), generates two output files:

  1. <form>_namespace.json  — every AcroForm field in the PDF, each with:
        fID        : sequential identifier (f1 … fn)
        pdfField   : full AcroForm dotted path  (e.g. "topmostSubform[0].Page1[0].f1_01[0]")
        shortName  : leaf segment before '[' (e.g. "f1_01")
        logicalKey : logical name from keys.pdf (e.g. "P1_A")
        label      : human description from FieldNames.json
        fType      : "text" | "box" | "image"
        page       : 1-based page number
        location   : namespace string (e.g. "Form1065.Pg1.EntityInfo")

  2. <form>_namespace.pdf  — filled copy of the PDF where:
        text fields → contain their fID string (e.g. "f1")
        box (checkbox) fields → checked (on-value from /AP/N, defaults to "/1")

Usage
-----
    python formWorksheetCmd.py Form1065-IRS.pdf

    -or- from Python:
        from irs.formWorksheetCmd import FormWorksheetCmd
        cmd = FormWorksheetCmd('Form1065-IRS.pdf')
        cmd.run()

Paths
-----
All input PDFs and keys files are resolved relative to
  <repo>/pages/AccountingData/2025/YE_Tax_Records/Forms_IRS/

Output files are saved to the same folder.

Reference: Form_1065-IRS.pdf, Form_1065-keys.pdf, Form_1065-FieldNames.json
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pypdf import PdfReader, PdfWriter

# ── Locate the Forms_IRS folder relative to this file ────────────────────────
_HERE      = Path(__file__).resolve().parent          # …/Notebooks/irs/
_ACCT_DATA = _HERE.parent.parent                      # …/AccountingData/
_FORMS_DIR = _ACCT_DATA / "2025" / "YE_Tax_Records" / "Forms_IRS"


# ── Location-derivation rules (ordered — first match wins) ───────────────────
_LOCATION_RULES: List[tuple] = [
    # Page 1
    (r'^P1_Hdr',          "Form1065.Pg1.Header"),
    (r'^P1_Sign',         "Form1065.Pg1.SignHere"),
    (r'^P1_PP',           "Form1065.Pg1.PaidPreparer"),
    (r'^P1_[A-F]',        "Form1065.Pg1.EntityInfo"),
    (r'^P1_G',            "Form1065.Pg1.EntityInfo"),
    (r'^P1_H',            "Form1065.Pg1.EntityInfo"),
    (r'^P1_I',            "Form1065.Pg1.EntityInfo"),
    (r'^P1_J',            "Form1065.Pg1.EntityInfo"),
    (r'^P1_K',            "Form1065.Pg1.EntityInfo"),
    (r'^P1_(1[a-c]?|[2-8])$', "Form1065.Pg1.Income"),
    (r'^P1_(9|1[0-9]|2[0-3]|16)', "Form1065.Pg1.Deductions"),
    (r'^P1_(2[4-9]|3[0-2])', "Form1065.Pg1.TaxAndPayments"),
    (r'^P1_',             "Form1065.Pg1.Other"),
    # Pages 2–3 — Schedule B
    (r'^B_PR',            "Form1065.Pg4.PartnerRep"),
    (r'^B_',              "Form1065.Pg2-3.SchedB"),
    # Page 5 — Schedule K
    (r'^K_',              "Form1065.Pg5.SchedK"),
    # Page 6 — Schedule L / M-1 / M-2 / ANI
    (r'^L_ANI',           "Form1065.Pg6.ANI"),
    (r'^L_',              "Form1065.Pg6.SchedL"),
    (r'^M1_',             "Form1065.Pg6.SchedM1"),
    (r'^M2_',             "Form1065.Pg6.SchedM2"),
]


def _derive_location(logical_key: str) -> str:
    """Return a namespace location string for a given logical key."""
    for pattern, location in _LOCATION_RULES:
        if re.match(pattern, logical_key):
            return location
    return "Form1065.Unknown"


def _page_from_path(pdf_field: str) -> int:
    """Extract 1-based page number from XFA field path."""
    m = re.search(r'Page(\d+)\[', pdf_field)
    return int(m.group(1)) if m else 0


def _short_name(pdf_field: str) -> str:
    """Return the leaf segment of an XFA path without the [n] index."""
    leaf = pdf_field.split(".")[-1]          # e.g. "f1_01[0]"
    return leaf.split("[")[0]                # e.g. "f1_01"


def _sort_key(field_info: Dict) -> tuple:
    """Sort fields by page, then by the numeric suffix in the short name."""
    page  = field_info["page"]
    short = field_info["shortName"]          # e.g. "f2_07" or "c3_14"
    # Extract leading letter and sequence number for stable ordering
    m = re.match(r'^([a-z]+)(\d+)_(\d+)$', short)
    if m:
        prefix  = 0 if m.group(1) == 'f' else 1   # text before buttons
        seq_pg  = int(m.group(2))
        seq_num = int(m.group(3))
        return (page, seq_pg, prefix, seq_num)
    return (page, 999, 0, 0)

from irs/irsForms import irsForm
class irsNspace(irsForm:
    """
    Generates namespace.json and namespace.pdf for an IRS AcroForm PDF.

    Parameters
    ----------
    form_filename : str
        Filename of the IRS template PDF, e.g. 'Form1065-IRS.pdf'.
        Must be located in the Forms_IRS folder.
    form_name : str, optional
        Short form name used in fID namespace (default derived from filename).
    verbose : bool
        Print progress messages.
    """

    def __init__(self, form_filename: str,
                 form_name: Optional[str] = None,
                 verbose: bool = True):
        super().__init__(llc, **kwargs):
        self.formNm = kwargs.get('form', None)
        form
        self.form_filename = form_filename
        self.verbose       = kwargs.get('verbose',True)

        # Derive short form name, e.g. "Form1065" from "Form_1065-IRS.pdf"
        stem = Path(form_filename).stem                 # "Form_1065-IRS"
        base = stem.replace("-IRS", "").replace("-", "").replace("_", "")
        self.form_name = form_name or base              # "Form1065"

        # Input paths
        self.irs_pdf_path  = _FORMS_DIR / form_filename
        keys_name          = form_filename.replace("-IRS.pdf", "-keys.pdf")
        self.keys_pdf_path = _FORMS_DIR / keys_name
        fnames_name        = form_filename.replace("-IRS.pdf", "-FieldNames.json")
        self.fnames_path   = _FORMS_DIR / fnames_name

        # Output paths
        self.out_json_path = _FORMS_DIR / f"{self.form_name}_namespace.json"
        self.out_pdf_path  = _FORMS_DIR / f"{self.form_name}_namespace.pdf"

    # ── Step 1: Load all AcroForm fields from the IRS PDF ────────────────────

    def _load_irs_fields(self) -> Dict[str, Dict]:
        """
        Read all AcroForm fields from the IRS template PDF.
        Returns dict: pdfField → {pdfField, shortName, fType, page, checkedValue}
        """
        rdr    = PdfReader(str(self.irs_pdf_path))
        raw    = rdr.get_fields() or {}
        result = {}

        for fid, fobj in raw.items():
            ft      = str(fobj.get("/FT", "")).strip()
            page    = _page_from_path(fid)
            short   = _short_name(fid)

            # Skip container / group nodes (no /FT, has /Kids — they are not
            # leaf fields and cause /AP KeyErrors if you try to fill them)
            has_kids = fobj.get("/Kids") is not None
            if ft == "" and has_kids:
                ftype = "container"   # excluded from fills
            # Determine fType
            elif ft == "/Tx":
                ftype = "text"
            elif ft == "/Btn":
                ftype = "box"
            elif ft == "/Sig" or "sig" in short.lower():
                ftype = "image"
            elif ft == "":
                # Unnamed type — check /_States_ to distinguish box vs text
                states = fobj.get("/_States_")
                ftype = "box" if states else "text"
            else:
                ftype = "text"

            # Checked value for box fields
            checked_value = "/1"   # IRS Form 1065 uses /1 as the on-value
            if ftype == "box":
                states = fobj.get("/_States_", [])
                try:
                    on_vals = [str(s) for s in states if str(s) != "/Off"]
                    if on_vals:
                        checked_value = on_vals[0]
                except Exception:
                    pass

            result[fid] = {
                "pdfField":     fid,
                "shortName":    short,
                "fType":        ftype,
                "page":         page,
                "checkedValue": checked_value,
            }

        return result

    # ── Step 2: Load logical-key mapping from keys PDF ────────────────────────

    def _load_key_map(self) -> Dict[str, str]:
        """
        Read field values from the keys PDF.
        Returns dict: shortName → logicalKey  (e.g. "f1_01" → "P1_Hdr_0")
        Button fields have values like "/1", "/2" — kept as-is.
        """
        if not self.keys_pdf_path.exists():
            if self.verbose:
                print(f"  ⚠️  Keys PDF not found: {self.keys_pdf_path.name} — logicalKeys will be ''")
            return {}

        rdr    = PdfReader(str(self.keys_pdf_path))
        raw    = rdr.get_fields() or {}
        km     = {}

        for fid, fobj in raw.items():
            v = fobj.get("/V")
            if v is None:
                continue
            v_str = str(v).strip()
            if v_str and v_str != "/Off":
                short = _short_name(fid)
                km[short] = v_str

        return km

    # ── Step 3: Load label map from FieldNames.json ───────────────────────────

    def _load_label_map(self) -> Dict[str, str]:
        """Returns dict: logicalKey → label (human description)."""
        if not self.fnames_path.exists():
            if self.verbose:
                print(f"  ⚠️  FieldNames JSON not found: {self.fnames_path.name} — labels will be ''")
            return {}
        with open(self.fnames_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()}

    # ── Step 4: Build namespace dict ──────────────────────────────────────────

    def _build_namespace(self, irs_fields: Dict, key_map: Dict, label_map: Dict) -> Dict:
        """
        Assign sequential fIDs and build the namespace dict.
        Fields are sorted by (page, field_prefix, sequence) before numbering.
        """
        # Sort fields for stable sequential assignment
        sorted_fields = sorted(irs_fields.values(), key=_sort_key)

        fields_ns = {}
        fid_to_pdf = {}   # fID → pdfField (for PDF filling)

        for idx, fi in enumerate(sorted_fields, start=1):
            fid       = f"f{idx}"
            short     = fi["shortName"]
            pdf_field = fi["pdfField"]

            logical_key = key_map.get(short, "")
            # Buttons in keys.pdf have values like "/1" — these are not logical names
            if logical_key.startswith("/"):
                logical_key = ""

            label    = label_map.get(logical_key, "") if logical_key else ""
            location = _derive_location(logical_key) if logical_key else f"Form1065.Pg{fi['page']}.Unknown"

            fields_ns[fid] = {
                "fID":        fid,
                "pdfField":   pdf_field,
                "shortName":  short,
                "logicalKey": logical_key,
                "label":      label,
                "fType":      fi["fType"],
                "page":       fi["page"],
                "location":   location,
            }
            fid_to_pdf[fid] = fi

        namespace = {
            "form":         self.form_name,
            "source":       self.form_filename,
            "total_fields": len(fields_ns),
            "fields":       fields_ns,
        }
        return namespace, fid_to_pdf

    # ── Step 5: Save namespace JSON ───────────────────────────────────────────

    def _save_json(self, namespace: Dict) -> None:
        with open(self.out_json_path, "w", encoding="utf-8") as fh:
            json.dump(namespace, fh, indent=2, ensure_ascii=False)
        if self.verbose:
            print(f"  ✅  JSON saved  → {self.out_json_path.name}  "
                  f"({namespace['total_fields']} fields)")

    # ── Step 6: Fill and save namespace PDF ───────────────────────────────────

    def _save_pdf(self, namespace: Dict, fid_to_pdf: Dict) -> None:
        """
        Fill a copy of the IRS PDF:
          text fields  → their fID string  (e.g. "f1")
          box fields   → their checked_value ("/1") where supported
        Strategy:
          - Separate text and box fields; fill text fields first (always works).
          - Try filling box fields page-by-page with auto_regenerate=False;
            catch KeyError or TypeError for boxes that lack /AP and skip them.
        """
        reader = PdfReader(str(self.irs_pdf_path))
        writer = PdfWriter(clone_from=reader)

        fields_data = namespace["fields"]

        # pypdf's update_page_form_field_values matches fields by:
        #   (a) annotation /T == key  (leaf name with [n] index)
        #   (b) _get_qualified_field_name(ann) == key  (full dotted XFA path)
        #
        # We use the FULL qualified path (pdfField from get_fields()) which is
        # form (b).  Container/group nodes (fType=="container") are excluded —
        # they have /Kids and no /FT; trying to fill them triggers a /AP KeyError.
        #
        # Box fields are filled one-at-a-time to tolerate the subset of button
        # fields that lack /AP entries.

        text_fills: Dict[int, Dict[str, str]] = {}   # page → {fullPath: fid}
        box_fills:  Dict[int, Dict[str, str]] = {}   # page → {fullPath: cv}

        for fid, fd in fields_data.items():
            pdf_field = fd["pdfField"]      # full qualified XFA path
            ftype     = fd["fType"]
            page      = fd["page"]
            if page < 1 or ftype in ("container", "image"):
                continue
            if ftype == "text":
                text_fills.setdefault(page, {})[pdf_field] = fid
            elif ftype == "box":
                fi = fid_to_pdf.get(fid, {})
                cv = fi.get("checkedValue", "/1")
                box_fills.setdefault(page, {})[pdf_field] = cv

        # Fill text fields — fill all at once per page, fall back to 1-at-a-time
        text_count = 0
        for page_num, fill_dict in text_fills.items():
            try:
                writer.update_page_form_field_values(
                    writer.pages[page_num - 1],
                    fill_dict,
                    auto_regenerate=False,
                )
                text_count += len(fill_dict)
            except Exception:
                # Fall back to individual fills
                for path, val in fill_dict.items():
                    try:
                        writer.update_page_form_field_values(
                            writer.pages[page_num - 1],
                            {path: val},
                            auto_regenerate=False,
                        )
                        text_count += 1
                    except Exception:
                        pass

        # Fill box fields one-at-a-time (some lack /AP — tolerate errors)
        box_ok  = 0
        box_err = 0
        for page_num, fill_dict in box_fills.items():
            for path, value in fill_dict.items():
                try:
                    writer.update_page_form_field_values(
                        writer.pages[page_num - 1],
                        {path: value},
                        auto_regenerate=False,
                    )
                    box_ok += 1
                except Exception:
                    box_err += 1

        writer.set_need_appearances_writer(True)

        with open(self.out_pdf_path, "wb") as fh:
            writer.write(fh)

        box_count = sum(len(v) for v in box_fills.values())
        if self.verbose:
            print(f"  ✅  PDF saved   → {self.out_pdf_path.name}  "
                  f"(text={text_count}, box_ok={box_ok}/{box_count})")

