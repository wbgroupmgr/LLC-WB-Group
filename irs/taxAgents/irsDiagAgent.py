"""
irs/taxAgents/irsDiagAgent.py
------------------------------
IRS Diagnostic Agent — BookToIRS pipeline introspection service.

Wraps the full BookToIRS pipeline and irsRefAgent to produce:
  • diagnose()      → structured dict  (consumed by Flask /api/aid/diagnose)
  • diagnose_text() → formatted string (consumed by testForm.py)

Output is organized by Section (from irsRefAgent.SECTIONS).
Blank/None values are omitted.  No location column.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repo root is importable when called from CLI
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from irs.taxAgents.irsRefAgent import get_sections, get_reference, REFERENCES


# ── value helpers ─────────────────────────────────────────────────────────────

def _is_blank(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False


def _is_zero(val: Any) -> bool:
    if isinstance(val, (int, float)) and val == 0:
        return True
    if isinstance(val, str) and val.strip() in ("0", "0.0", "0.00"):
        return True
    return False


def _fmt(val: Any) -> str:
    if _is_blank(val):
        return "(blank)"
    if isinstance(val, float):
        if val == 0.0:
            return "0.00"
        return f"{val:,.2f}"
    return str(val)


def _normalize_fid(raw: Any) -> str:
    s = str(raw).strip()
    m = re.match(r'^[fF]?(\d+)$', s)
    return f"F{int(m.group(1)):03d}" if m else s


# ── IRSDiagAgent ─────────────────────────────────────────────────────────────

class IRSDiagAgent:
    """
    Diagnostic agent for a single IRS form.

    Usage::

        from irs.taxAgents.irsDiagAgent import IRSDiagAgent
        agent = IRSDiagAgent(llc, "Form4562")
        data  = agent.diagnose()      # dict
        text  = agent.diagnose_text() # str
    """

    def __init__(self, llc, form_name: str):
        self.llc       = llc
        self.form_name = form_name
        self._aid      = None
        self._fid_meta: Dict[str, dict] = {}

    # ── private ──────────────────────────────────────────────────────────────

    def _get_aid(self):
        if self._aid is None:
            from irs.BookToIRS import BookToIRS
            self._aid = BookToIRS(self.llc, self.form_name)
            self._aid._refreshStmtInstances()
        return self._aid

    def _get_fid_meta(self) -> Dict[str, dict]:
        if self._fid_meta:
            return self._fid_meta
        aid        = self._get_aid()
        form_cls   = aid._formClass()
        form_inst  = form_cls(llc=self.llc)

        # Auto-build namespace JSON if missing (same as regenerate()).
        try:
            df = form_inst.loadFieldsDF()
        except FileNotFoundError:
            nspace = form_inst._buildNSpace()
            form_inst.saveNSpace(nspace)
            df = form_inst.loadFieldsDF()

        for _, row in df.iterrows():
            self._fid_meta[row["fid"]] = {
                "shortName": row.get("shortName") or "",
                "pdfField":  row.get("pdfField")  or "",
                "page":      row.get("page")       or 0,
            }
        return self._fid_meta

    def _collect_all_mapped(self) -> Dict[str, dict]:
        """Return {norm_fid: {src, uas, value, shortName}} for every bookNS entry."""
        from irs.BookToIRS import AID_SOURCES
        aid      = self._get_aid()
        fid_meta = self._get_fid_meta()
        result: Dict[str, dict] = {}

        for src in AID_SOURCES:
            raw_pairs = aid.loadBookNS(src)
            if not raw_pairs:
                continue
            stmt = aid._stmtInstance(src)
            if stmt is None:
                continue
            try:
                fill_dict = stmt.loadFillDict(self.form_name) or {}
            except Exception:
                fill_dict = {}

            for fid_raw, uas in raw_pairs:
                fid  = _normalize_fid(fid_raw)
                val  = fill_dict.get(fid)
                meta = fid_meta.get(fid, {})
                if fid not in result or (result[fid]["value"] is None and val is not None):
                    result[fid] = {
                        "fid":       fid,
                        "shortName": meta.get("shortName", ""),
                        "src":       src,
                        "uas":       str(uas),
                        "value":     val,
                    }
        return result

    # ── public ───────────────────────────────────────────────────────────────

    def diagnose(self) -> dict:
        """
        Return structured diagnostic data.

        Schema::

            {
              "form":     "Form4562",
              "llc":      "WBGroupLLC",
              "year":     2025,
              "sections": [
                {
                  "id":     "PartIII-19h",
                  "name":   "Part III — Line 19h (Residential Rental MACRS)",
                  "ref_id": "F4562-19h",
                  "cite":   "IRC §168(c)(1) ...",
                  "reason": "...",
                  "fields": [
                    { "fid","shortName","src","uas","value","is_blank","is_zero" }
                  ]
                }
              ],
              "unmapped": [ {...} ]   # fids in bookNS but not in any section
            }
        """
        from ledger import setup_paths as sp

        all_mapped = self._collect_all_mapped()
        sections   = get_sections(self.form_name)
        refs       = REFERENCES.get(self.form_name, {})

        placed: set[str] = set()
        out_sections: List[dict] = []

        for sec_def in sections:
            ref_id  = sec_def.get("ref", "")
            ref_obj = refs.get(ref_id, {})
            fields: List[dict] = []

            for fid in sec_def["fids"]:
                entry = all_mapped.get(fid)
                if entry is None:
                    continue                      # fid defined in section but not in bookNS
                placed.add(fid)
                val = entry["value"]
                if _is_blank(val):
                    continue                      # skip blank values (rule 1)
                fields.append({
                    "fid":       fid,
                    "shortName": entry["shortName"],
                    "src":       entry["src"],
                    "uas":       entry["uas"],
                    "value":     val,
                    "value_fmt": _fmt(val),
                    "is_zero":   _is_zero(val),
                })

            out_sections.append({
                "id":     sec_def["id"],
                "name":   sec_def["name"],
                "ref_id": ref_id,
                "cite":   ref_obj.get("cite",   ""),
                "reason": ref_obj.get("reason", ""),
                "fields": fields,
            })

        # Anything in bookNS but not assigned to any section.
        unmapped = [
            {**entry, "value_fmt": _fmt(entry["value"]), "is_zero": _is_zero(entry["value"])}
            for fid, entry in all_mapped.items()
            if fid not in placed and not _is_blank(entry["value"])
        ]

        return {
            "form":      self.form_name,
            "llc":       getattr(sp, "DATA_NAME", "") or "",
            "year":      getattr(sp, "YEAR", None),
            "sections":  out_sections,
            "unmapped":  unmapped,
        }

    def diagnose_text(self) -> str:
        """Return a formatted multi-line string — same output as testForm.py."""
        from ledger import setup_paths as sp
        data = self.diagnose()

        W_FID = 6
        W_SN  = 10
        W_UAS = 40
        W_VAL = 18
        SEP   = "  "
        LINE  = "─" * 96

        lines: List[str] = []
        lines.append("═" * 96)
        lines.append(f"  BookToIRS Diagnostic — {data['form']}")
        lines.append(f"  LLC: {data['llc']}   Year: {data['year']}")
        lines.append(f"  bookNS dir: {sp.IRS_FORMS_DIR}")
        lines.append("═" * 96)

        for sec in data["sections"]:
            if not sec["fields"]:
                continue                          # skip empty sections
            lines.append("")
            lines.append(f"── {sec['name']}  [{sec['ref_id']}] {'─' * max(0, 72 - len(sec['name']) - len(sec['ref_id']))}")

            hdr = (f"  {'fid':{W_FID}}{SEP}{'shortName':{W_SN}}{SEP}"
                   f"{'UAS path':{W_UAS}}{SEP}{'value'}")
            lines.append(hdr)
            lines.append("  " + "─" * 88)

            for f in sec["fields"]:
                val_str = f["value_fmt"]
                if f["is_zero"]:
                    val_str += "  ← ZERO"
                lines.append(
                    f"  {f['fid']:{W_FID}}{SEP}"
                    f"{f['shortName']:{W_SN}}{SEP}"
                    f"{f['uas']:{W_UAS}}{SEP}"
                    f"{val_str}"
                )

            if sec["cite"] or sec["reason"]:
                lines.append("")
                lines.append(f"  IRS Ref [{sec['ref_id']}]: {sec['cite']}")
                # Word-wrap the reason at ~90 chars
                reason = sec["reason"]
                words  = reason.split()
                line_buf: List[str] = []
                cur_len = 0
                for w in words:
                    if cur_len + len(w) + 1 > 88:
                        lines.append("    " + " ".join(line_buf))
                        line_buf = [w]
                        cur_len  = len(w)
                    else:
                        line_buf.append(w)
                        cur_len += len(w) + 1
                if line_buf:
                    lines.append("    " + " ".join(line_buf))

        if data["unmapped"]:
            lines.append("")
            lines.append(f"── Unmapped (in bookNS, no section defined) {'─' * 50}")
            for f in data["unmapped"]:
                lines.append(
                    f"  {f['fid']:{W_FID}}{SEP}"
                    f"{f['shortName']:{W_SN}}{SEP}"
                    f"{f['uas']:{W_UAS}}{SEP}"
                    f"{f['value_fmt']}"
                )

        lines.append("")
        lines.append(LINE)

        # Books sanity check
        aid = self._get_aid()
        is_stmt = aid._stmtInstance("IS")
        bs_stmt = aid._stmtInstance("BS")
        lines.append("  Books sanity check")
        lines.append(LINE)

        if is_stmt:
            try:
                agg = is_stmt.taxAggregates()
                lines.append("  IS taxAggregates:")
                for k in ["depreciation", "total_income", "total_expenses",
                           "net_income", "rent_income", "repairs", "utilities",
                           "interest_expense", "other_deductions"]:
                    if k in agg:
                        lines.append(f"    {k:30s} = {_fmt(agg[k])}")
            except Exception as exc:
                lines.append(f"  IS taxAggregates error: {exc}")

        if bs_stmt:
            try:
                agg = bs_stmt.taxAggregates()
                lines.append("  BS taxAggregates:")
                for k in ["placed_in_service_date", "buildings", "land",
                           "accum_depr", "cash", "mortgage"]:
                    if k in agg:
                        lines.append(f"    {k:30s} = {_fmt(agg[k])}")
            except Exception as exc:
                lines.append(f"  BS taxAggregates error: {exc}")

        lines.append("")
        return "\n".join(lines)
