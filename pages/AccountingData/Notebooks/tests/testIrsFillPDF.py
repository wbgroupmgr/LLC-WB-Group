'''
tests.testIrsFillPDF — round-trip test for the IRS Form 1065 FILL pipeline.
v0.2.4.7

Validates that ``Form1065_FILL.pdf`` (the deliverable produced by
``irs.Form1065.saveFILL()``) carries exactly the values declared in
``Form1065_fillDict.json`` (the cache produced by
``irs.Form1065._buildFillDict()``) and that no other AcroForm fields were
touched.

The test is the canonical assertion that the IRS pipeline's three artefacts
agree:

    Form1065_IRS.pdf       — blank IRS template (no values; sometimes
                              defaults like "/Off" on checkboxes)
    Form1065_FILL.pdf      — filled deliverable
    Form1065_fillDict.json — per-field publish flags + resolved values

For every AcroForm field in the FILL.pdf:

  * If the value differs from the IRS.pdf template → the difference must
    match an entry in the fillDict whose ``publish == True`` and whose
    resolved ``value`` (after currency-formatting normalisation) equals
    the FILL.pdf value.
  * If the value is unchanged → the fillDict entry must be ``publish ∈
    {False, "CPA:unknown"}`` OR have an empty resolved ``value``.

Side-effect
-----------
Prints a ``fillMapDict`` covering every field on the form (not just the
diff) — one row per fillDict entry — so an operator can scan the full
publish picture in a single dump.

Usage
-----
    # from Notebooks/
    python -m tests.testIrsFillPDF

Exits 0 when all invariants hold, 1 otherwise.
'''

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Allow direct `python tests/testIrsFillPDF.py` invocation.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── Helpers ────────────────────────────────────────────────────────────────

_NUMSTRIP_RE = re.compile(r"[\s,$]")


def _norm_value(v: Any) -> str:
    '''
    Normalise a PDF / fillDict value into a comparable string:

      * strip whitespace, commas, dollar signs
      * convert numerics to plain "1234.56" (no thousand-separators)
      * "/Off" / "Off" → "" (PDF-checkbox unchecked default)
      * None / missing → ""
    '''
    if v is None:
        return ""
    s = str(v).strip()
    if s in ("/Off", "Off"):
        return ""
    if s == "":
        return ""
    # Strip currency / thousand separators
    stripped = _NUMSTRIP_RE.sub("", s)
    # If after stripping it's a clean number, return canonical form
    try:
        n = float(stripped)
        if abs(n - int(n)) < 1e-9:
            return f"{int(n)}"
        return f"{round(n, 2)}"
    except ValueError:
        return s


def _read_fields(pdf_path: Path) -> Dict[str, Any]:
    '''
    Read every AcroForm field's ``/V`` (value) from a PDF, keyed by the
    short logical field name.  Returns ``{shortName: value}``.
    '''
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    fields = reader.get_fields() or {}
    out: Dict[str, Any] = {}
    for name, fld in fields.items():
        try:
            v = fld.get("/V") if hasattr(fld, "get") else None
        except Exception:
            v = None
        out[str(name)] = v
    return out


def _load_fill_dict(json_path: Path) -> Dict[str, Dict[str, Any]]:
    '''
    Load Form1065_fillDict.json and return a flat ``{fID → entry}`` map.
    Tolerates both new format ``{"fields": {fID: {...}}}`` and legacy
    direct ``{fID: {...}}``.
    '''
    with open(json_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return raw.get("fields", raw) if isinstance(raw, dict) else {}


def _by_pdf_field(fill_dict: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    '''
    Index the fillDict by the AcroForm path (``pdfField``) used as the key
    in ``PdfReader.get_fields()``.  Falls back to ``shortName`` when
    ``pdfField`` is absent so the test still works on older fillDicts.
    '''
    out: Dict[str, Dict[str, Any]] = {}
    for fid, entry in fill_dict.items():
        if not isinstance(entry, dict):
            continue
        key = entry.get("pdfField") or entry.get("shortName") or fid
        # carry the fID alongside so the report can still print it
        rec = dict(entry)
        rec.setdefault("fID", fid)
        out[str(key)] = rec
    return out


# ── Build the LLC + locate artefacts ──────────────────────────────────────

def _build_llc():
    from ledger.LLC import LLC
    return LLC('WBGroupLLC')


def _artifact_paths(llc) -> Dict[str, Path]:
    irs_dir = Path(llc.acctDir(dirName="ye")) / "Forms_IRS"
    return {
        "irs":      irs_dir / "Form1065_IRS.pdf",
        "fill":     irs_dir / "Form1065_FILL.pdf",
        "fillDict": irs_dir / "Form1065_fillDict.json",
    }


# ── Tests ──────────────────────────────────────────────────────────────────

def _diff_and_validate(llc) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    '''
    Run the round-trip diff and validation.

    Returns
    -------
    fillMapDict : dict[fID → row]
        Full per-field map covering every fillDict entry.  Each row
        contains:
            fID, logicalKey, page, location, label,
            pdfField, fType, publish,
            templateValue, fillValue, dictValue,
            isDiff, status
    errors : list[str]
        Human-readable assertion failures.
    '''
    paths = _artifact_paths(llc)
    for tag, p in paths.items():
        assert p.exists(), f"missing artefact: {tag} → {p}"

    template = _read_fields(paths["irs"])
    filled   = _read_fields(paths["fill"])
    fd       = _load_fill_dict(paths["fillDict"])
    by_pdf   = _by_pdf_field(fd)

    # The two PDFs must share the AcroForm field set
    if set(template.keys()) != set(filled.keys()):
        only_in_fill = sorted(set(filled.keys()) - set(template.keys()))[:5]
        only_in_tpl  = sorted(set(template.keys()) - set(filled.keys()))[:5]
        raise AssertionError(
            f"AcroForm field set drift between IRS.pdf and FILL.pdf "
            f"(only-in-FILL preview: {only_in_fill}; "
            f"only-in-IRS preview: {only_in_tpl})"
        )

    fill_map: Dict[str, Dict[str, Any]] = {}
    errors:   List[str] = []

    for pdf_field in sorted(filled.keys()):
        tpl_val_raw = template.get(pdf_field)
        fil_val_raw = filled.get(pdf_field)
        tpl_norm    = _norm_value(tpl_val_raw)
        fil_norm    = _norm_value(fil_val_raw)
        is_diff     = tpl_norm != fil_norm

        entry      = by_pdf.get(pdf_field, {})
        fid        = entry.get("fID", "")
        publish    = entry.get("publish", None)
        dict_val   = entry.get("value", "")
        dict_norm  = _norm_value(dict_val)

        status = "ok"
        if is_diff:
            # FILL.pdf changed this field — it MUST be backed by the fillDict
            if not entry:
                status = "diff-without-dict-entry"
                errors.append(
                    f"{pdf_field}: FILL.pdf changed value to {fil_val_raw!r} "
                    f"but no fillDict entry exists"
                )
            else:
                if publish is not True:
                    status = "diff-but-publish-not-true"
                    errors.append(
                        f"{pdf_field} (fID={fid}): FILL.pdf shows "
                        f"{fil_val_raw!r} but fillDict.publish={publish!r} "
                        f"(must be True)"
                    )
                elif dict_norm != fil_norm:
                    status = "value-mismatch"
                    errors.append(
                        f"{pdf_field} (fID={fid}): FILL.pdf={fil_val_raw!r} "
                        f"≠ fillDict.value={dict_val!r}"
                    )
        else:
            # No change — either field is unpublished (False/CPA:unknown)
            # or its resolved value is empty.
            if entry and publish is True and dict_norm not in ("", fil_norm):
                status = "publish-true-but-not-applied"
                errors.append(
                    f"{pdf_field} (fID={fid}): fillDict.publish=True with "
                    f"value={dict_val!r} but FILL.pdf still has "
                    f"{fil_val_raw!r}"
                )

        if entry or is_diff:
            fill_map[fid or pdf_field] = {
                "fID":           fid,
                "logicalKey":    entry.get("logicalKey", ""),
                "page":          entry.get("page", 0),
                "location":      entry.get("location", ""),
                "label":         entry.get("label", "") or entry.get("note", ""),
                "pdfField":      pdf_field,
                "fType":         entry.get("fType", ""),
                "publish":       publish,
                "templateValue": tpl_val_raw,
                "fillValue":     fil_val_raw,
                "dictValue":     dict_val,
                "isDiff":        is_diff,
                "status":        status,
            }

    return fill_map, errors


# ── Test functions (mirrors testLedgerAPI registry style) ──────────────────

_TESTS: List[Tuple[str, Any]] = []


def _register(name: str):
    def _deco(fn):
        _TESTS.append((name, fn))
        return fn
    return _deco


@_register("F1 — Form1065 IRS/FILL/fillDict artefacts exist")
def f1_artefacts_exist(llc) -> bool:
    paths = _artifact_paths(llc)
    for tag, p in paths.items():
        assert p.exists(), f"missing {tag} at {p}"
    return True


@_register("F2 — IRS.pdf and FILL.pdf share the same AcroForm field set")
def f2_same_field_set(llc) -> bool:
    paths = _artifact_paths(llc)
    tpl = set(_read_fields(paths["irs"]).keys())
    fil = set(_read_fields(paths["fill"]).keys())
    assert tpl == fil, (
        f"field-set drift: only-in-fill={sorted(fil-tpl)[:5]} "
        f"only-in-tpl={sorted(tpl-fil)[:5]}"
    )
    return True


@_register("F3 — Every FILL.pdf change matches a fillDict.publish=True entry")
def f3_round_trip(llc) -> bool:
    _, errs = _diff_and_validate(llc)
    if errs:
        head = "\n  ".join(errs[:8])
        more = f"\n  …(+{len(errs)-8} more)" if len(errs) > 8 else ""
        raise AssertionError(f"{len(errs)} round-trip discrepancies:\n  {head}{more}")
    return True


@_register("F4 — Every fillDict.publish=True entry is reflected in FILL.pdf")
def f4_publish_applied(llc) -> bool:
    fill_map, _ = _diff_and_validate(llc)
    bad = [r for r in fill_map.values()
           if r["publish"] is True and r["status"] != "ok"]
    assert not bad, f"{len(bad)} publish=True entries not applied: " \
        f"first={bad[0]['pdfField']} status={bad[0]['status']}"
    return True


# ── Runner ─────────────────────────────────────────────────────────────────

def run_all(llc=None) -> Dict[str, Any]:
    if llc is None:
        llc = _build_llc()

    passed: List[str] = []
    failed: List[Tuple[str, str]] = []

    for name, fn in _TESTS:
        try:
            ok = fn(llc)
            if ok:
                passed.append(name)
            else:
                failed.append((name, "returned False"))
        except Exception as err:
            tb = traceback.format_exc(limit=2)
            failed.append((name, f"{type(err).__name__}: {err}\n{tb}"))

    # ── Always emit the full fillMapDict, even on failure ──────────────────
    try:
        fill_map, _ = _diff_and_validate(llc)
        # Sort by (page, fID-numeric) for human-readable scan order
        def _fid_num(fid: str) -> int:
            m = re.search(r"(\d+)", fid or "")
            return int(m.group(1)) if m else 10_000

        ordered = sorted(
            fill_map.items(),
            key=lambda kv: (int(kv[1].get("page") or 0), _fid_num(kv[0])),
        )
        fill_map_sorted = {k: v for k, v in ordered}

        diff_count    = sum(1 for r in fill_map_sorted.values() if r.get("isDiff"))
        publish_true  = sum(1 for r in fill_map_sorted.values() if r.get("publish") is True)
        publish_cpa   = sum(1 for r in fill_map_sorted.values() if r.get("publish") == "CPA:unknown")
        publish_false = sum(1 for r in fill_map_sorted.values() if r.get("publish") is False)

        print()
        print("=" * 72)
        print(f"fillMapDict — Form 1065 (entries: {len(fill_map_sorted)})")
        print("=" * 72)
        print(f"  changed in FILL.pdf  : {diff_count}")
        print(f"  publish=True         : {publish_true}")
        print(f"  publish='CPA:unknown': {publish_cpa}")
        print(f"  publish=False        : {publish_false}")
        if diff_count == 0 and publish_true == 0:
            print(f"  NOTE: round-trip is currently vacuous — re-run the IRS "
                  f"pipeline\n        (_buildFillDict + saveFILL) to populate "
                  f"the FILL.pdf, then\n        re-run this test for the "
                  f"meaningful diff.")
        print("=" * 72)
        print(json.dumps(fill_map_sorted, indent=2, default=str))
        print("=" * 72)
    except Exception as err:
        print(f"\n(unable to emit fillMapDict: {err})")

    return {
        "ok":     len(failed) == 0,
        "passed": passed,
        "failed": failed,
        "n":      len(_TESTS),
    }


def _report(res: Dict[str, Any]) -> int:
    n_ok = len(res["passed"])
    print(f"\ntestIrsFillPDF: {n_ok}/{res['n']} passed")
    for name in res["passed"]:
        print(f"  PASS  {name}")
    for name, err in res["failed"]:
        print(f"  FAIL  {name}")
        for ln in err.strip().splitlines()[:6]:
            print(f"        {ln}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    res = run_all()
    sys.exit(_report(res))
