"""
pdfFill.py
===================
- Imports a PDF, discovers every AcroForm field, 
- fills each field with its own field identifier as the value, 
- saves the result, 
- tests that every field in the output contains the expected identifier.
s
Usage
-----
    python pdf_field_filler.py input.pdf filled_output.pdf

Requirements
------------
    pip install pypdf
"""

import sys
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from pathlib import Path


class pdfFill(object):
    def __init__(self, inFN, outFN, **kwargs):
        self.inFN = inFN
        self.outFN = outFN
        self.rdr = PdfReader(self.inFN)
        self.verbose = kwargs.get('verbose', False)
        self.debug = kwargs.get('debug', False)

        # Use glDict to map PDF.field to GL.value
        self.glDict = kwargs.get('glDict', None)
    
        
    
    # ─────────────────────────────────────────────────────────────────────────────
    #  STEP 1 – DISCOVER ALL FIELDS
    # ─────────────────────────────────────────────────────────────────────────────
    
    def get(self) -> dict:
        """
        Walk every page annotation to collect every AcroForm field.
    
        Returns a dict keyed by field_id:
            {
              "field_id":        str,   # full dotted name, e.g. "topmostSubform[0].f1_01[0]"
              "type":            str,   # "text" | "checkbox" | "radio" | "choice" | "unknown"
              "page":            int,   # 1-based page number
              "checked_value":   str,   # checkboxes only – the on-value, e.g. "/Yes"
              "unchecked_value": str,   # checkboxes only – always "/Off"
              "radio_options":   list,  # radio groups only – list of on-value strings
              "choice_options":  list,  # dropdowns only   – list of option strings
            }
        """
        
        raw = self.rdr.get_fields() or {}
        fields: dict = {}
    
        # ── helper: walk up /Parent chain to build dotted field id ───────────────
        def full_id(annotation) -> str | None:
            parts = []
            node = annotation
            while node:
                t = node.get("/T")
                if t:
                    parts.append(str(t))
                node = node.get("/Parent")
            return ".".join(reversed(parts)) if parts else None
    
        # ── helper: checked / unchecked values for a Btn annotation ─────────────
        def btn_values(annotation) -> tuple[str, str]:
            try:
                ap_keys = list(annotation["/AP"]["/N"].keys())
                on_vals = [v for v in ap_keys if v != "/Off"]
                on  = on_vals[0] if on_vals else "/Yes"
                off = "/Off"
                return on, off
            except Exception:
                return "/Yes", "/Off"
    
        # ── identify which top-level names are radio groups (have /Kids) ─────────
        radio_parents: set[str] = set()
        for fid, fobj in raw.items():
            if fobj.get("/Kids") and fobj.get("/FT") == "/Btn":
                radio_parents.add(fid)
    
        # ── walk every page annotation ───────────────────────────────────────────
        for page_idx, page in enumerate(self.rdr.pages):
            page_num = page_idx + 1
            for ann_ref in page.get("/Annots", []):
                try:
                    ann = ann_ref.get_object() if hasattr(ann_ref, "get_object") else ann_ref
                except Exception:
                    continue
    
                fid = full_id(ann)
                if not fid:
                    continue
    
                ft = ann.get("/FT") or (ann.get("/Parent") or {}).get("/FT")
    
                # ── radio button (child of a radio-group parent) ──────────────
                # Check if the top-level name belongs to a radio parent
                top_name = fid.split(".")[0]
                if top_name in radio_parents or fid in radio_parents:
                    try:
                        on_vals = [v for v in ann["/AP"]["/N"] if v != "/Off"]
                    except Exception:
                        on_vals = []
                    if on_vals:
                        if fid not in fields:
                            fields[fid] = {
                                "field_id":     fid,
                                "type":         "radio",
                                "page":         page_num,
                                "radio_options": [],
                            }
                        fields[fid]["radio_options"].append(on_vals[0])
                    continue
    
                # ── already recorded (multi-annotation fields) ────────────────
                if fid in fields:
                    continue
    
                if ft == "/Tx":
                    fields[fid] = {"field_id": fid, "type": "text", "page": page_num}
    
                elif ft == "/Btn":
                    on, off = btn_values(ann)
                    fields[fid] = {
                        "field_id":      fid,
                        "type":          "checkbox",
                        "page":          page_num,
                        "checked_value": on,
                        "unchecked_value": off,
                    }
    
                elif ft == "/Ch":
                    # Options may be plain strings or [export_value, display] pairs.
                    # Try /_States_ first, then /Opt directly on the annotation.
                    raw_opts = ann.get("/_States_") or ann.get("/Opt") or []
                    opts = []
                    for s in raw_opts:
                        if isinstance(s, (list, tuple)) and len(s) >= 1:
                            opts.append(str(s[0]))
                        elif s is not None:
                            opts.append(str(s))
                    # Last resort: read /Opt from the high-level field object
                    if not opts:
                        top = raw.get(fid) or raw.get(fid.split(".")[-1]) or {}
                        for s in (top.get("/Opt") or []):
                            if isinstance(s, (list, tuple)) and len(s) >= 1:
                                opts.append(str(s[0]))
                            elif s is not None:
                                opts.append(str(s))
                    fields[fid] = {
                        "field_id":     fid,
                        "type":         "choice",
                        "page":         page_num,
                        "choice_options": opts,
                    }
    
                else:
                    fields[fid] = {
                        "field_id": fid,
                        "type":     f"unknown({ft})",
                        "page":     page_num,
                    }
    
        return fields
    
    
    # ─────────────────────────────────────────────────────────────────────────────
    #  STEP 2 – CHOOSE A FILL VALUE FOR EACH FIELD TYPE
    # ─────────────────────────────────────────────────────────────────────────────
    
    def fill(self, field: dict, tsDict = None) -> str:
        """
        Return the value to write.
        • text / unknown  →  the field_id string itself
        • checkbox        →  its checked_value  (marks it ticked)
        • radio           →  first available radio option
        • choice          →  first available choice option
        """
        ftype = field["type"]
        
        # Fill default is to fill every field with field ID
        fldValue = field["field_id"]

        # Test if test fill
        if tsDict:
            tsID = tsDict[fldValue]
        else:
            tsID = None

        # ----- add text if GL field specified
        if ftype == "text" or ftype.startswith("unknown"):
            if self.glDict :
                if tsID in self.glDict:
                    # Fill GL.field value, if present, then value is returned
                    return self.glDict[tsID]
                else:
                    # self.glDict is None or tsID not in glDict
                    return None
            else:
                return fldValue

        # --- if testing form fields, add check boxes
        if tsDict:
            # track non text fields
            self.nonTextDict[fldValue] = (tsID, field['page'], ftype)
    
        # --- if GLTax doe not specify chk then ignore
        if self.glDict :
            # convert tsID to numeric - check if in chkNo, chkYes
            fldNum = int(tsID[1:])

            # Determine what GL field needs to check PDF field
            if fldNum not in self.glDict['chk']:
                # Do not check               
                return None
        
        #--- handle check fields ----
        
        if ftype == "checkbox":
            return field["checked_value"]
    
        if ftype == "radio":
            opts = field.get("radio_options", [])
            return opts[0] if opts else "/Yes"
    
        if ftype == "choice":
            opts = field.get("choice_options", [])
            return opts[0] if opts else ""
    
        return None
    
    
    # ─────────────────────────────────────────────────────────────────────────────
    #  STEP 3 – FILL & SAVE
    # ─────────────────────────────────────────────────────────────────────────────

    def fillPDF(self) -> dict:
        """
        Discover all fields, fill each with its identifier, save to output_path.
    
        Returns the field map dict  { field_id: fill_value }  for inspection.
        """
        input_path = self.inFN
        output_path = self.outFN
        
        reader = PdfReader(input_path)
        #fields = self.get(reader)
        fields = self.get()
        tsDict = {k:f"F{i}" for i,k in enumerate(fields)}
        self.nonTextDict = {}
    
        if not fields:
            raise ValueError(f"No AcroForm fields found in '{input_path}'. "
                             "The PDF may be flat / scanned.")

        bnOut = Path(output_path).name
        
        if self.debug: print(f" fillPDF Start:  Writing output to '{bnOut}' →  Form Fields: {len(fields)}\n")
    
        # Build page-grouped fill dict
        page_fills: dict[int, dict[str, str]] = {}
        fill_map:   dict[str, str]            = {}
    
        for fid, finfo in fields.items():

            v = self.fill(finfo, tsDict)
            if v is None : 
                # do nothing
                continue
            
            value = v
            ftype  = finfo["type"]
            page   = finfo["page"]
            fill_map[fid] = value
            #print("debug: fillPDF  234", fid, value, finfo)
            page_fills.setdefault(page, {})[fid] = value
            if self.debug: print(f"  {'[' + ftype + ']':<14}  p{page}  {fid[:60]:<60}  →  {value[:40]}")
    
        # Write via pypdf
        writer = PdfWriter(clone_from=reader)
    
        for page_num, field_values in page_fills.items():
            writer.update_page_form_field_values(
                writer.pages[page_num - 1],
                field_values,
                auto_regenerate=False,
            )
    
        # Tell viewers to regenerate field appearances so values are visible
        writer.set_need_appearances_writer(True)
    
        with open(output_path, "wb") as fh:
            writer.write(fh)
            
        if self.verbose: 
            print(f"\n✅  Saved → '{bnOut}'  ({len(fill_map)} fields filled)")
        return fill_map
    
    
    # ─────────────────────────────────────────────────────────────────────────────
    #  STEP 4 – TEST
    # ─────────────────────────────────────────────────────────────────────────────
    
    def test(self, expected_fill_map: dict) -> bool:
        """
        Re-open the filled PDF and assert every text field contains exactly the
        value that was written (its own field_id).
    
        Checkbox / radio / choice fields are checked to be non-empty.
    
        Prints a PASS / FAIL line per field and returns True if all pass.
        """
        filled_path = self.outFN
        
        print(f"\n🔍  Testing '{filled_path}'  ({len(expected_fill_map)} fields)\n")
    
        reader    = PdfReader(filled_path)
        raw       = reader.get_fields() or {}
        passed    = 0
        failed    = 0
        skipped   = 0
        failures  = []
    
        for fid, expected in expected_fill_map.items():
            # pypdf stores the field under its short (last-component) name in get_fields()
            # but also under the full dotted name – try both
            short_key = fid.split(".")[-1]
            fobj      = raw.get(fid) or raw.get(short_key)
    
            if fobj is None:
                print(f"  [SKIP ]  {fid[:70]}  (field not found in reader)")
                skipped += 1
                continue
    
            actual = fobj.get("/V")
            if actual is None:
                actual = ""
            # pypdf may return a NameObject ("/Yes") or a string
            actual_str = str(actual).strip()
    
            # For text fields the expected value IS the field_id
            if expected == fid:                          # text field
                ok = actual_str == expected
            else:                                        # checkbox / radio / choice
                ok = actual_str != "" and actual_str != "/Off"
    
            status = "PASS" if ok else "FAIL"
            icon   = "✅" if ok else "❌"
            print(f"  [{status}] {icon}  {fid[:60]:<62}"
                  f"  expected='{expected[:30]}'  actual='{actual_str[:30]}'")
    
            if ok:
                passed += 1
            else:
                failed += 1
                failures.append({"field": fid, "expected": expected, "actual": actual_str})
    
        print(f"\n{'─'*72}")
        print(f"  Results:  {passed} PASSED  |  {failed} FAILED  |  {skipped} SKIPPED")
    
        if failures:
            print(f"\n  ⚠️  Failed fields:")
            for f in failures:
                print(f"      • {f['field']}")
                print(f"        expected : {f['expected']}")
                print(f"        actual   : {f['actual']}")
    
        all_ok = failed == 0
        if self.verbose: print(f"\n  {'🎉 All fields verified.' if all_ok else '💥 Some fields failed verification.'}\n")
        return all_ok