"""
irs.publishMap — Shared type helpers for the per-data-object publish map.

Per DataModelGuide the "publish" relationship (financial-data cell →
IRS-form field) is declared **on the data object** as a class-level
``PUBLISH_MAP`` dict:

    class stmtIncomeStmt(stmtDB):
        PUBLISH_MAP = {
            "Form1065": [
                PubEntry(src_row="Acct.Rev.Rent",  src_col="Balance",
                         logicalKey="P1_1a", fType="text", sign=-1,
                         note="Gross rental receipts"),
                ...
            ],
        }

IRS form views (``irs.Form1065`` etc.) don't declare bindings; they only
aggregate the per-form payloads produced by each consuming data object:

    form.nSpaceMap() → {(tblID, rowNm, colNm): fillDict_minimal}

The ``to_form_payload(formNm)`` method on stmtDB (and ledgerDB) walks its
own ``PUBLISH_MAP`` and produces the JSON payload rows for that form.

Timestamp of last change: 2026.04.19
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── Field-type enumeration (mirrors irs.irsForm classification) ──────────────
F_TEXT      = "text"
F_CHECKBOX  = "checkBox"
F_CHECKTEXT = "checkText"
F_IMAGE     = "image"

# ── Publish flag values ──────────────────────────────────────────────────────
P_TRUE        = True
P_FALSE       = False
P_CPA_UNKNOWN = "CPA:unknown"


@dataclass(frozen=True)
class PubEntry:
    """
    One binding: a cell on THIS data object publishes to ONE IRS form field.

    Fields
    ------
    src_row, src_col  : Address of the cell inside the data object's
                        ``nSpaceMap()`` — the ``tblID`` component is
                        implicit (== the owning class's DEFAULT_TBLID).
    logicalKey        : The IRS form's logical-key (e.g. ``P1_1a``).
    fType             : One of {"text","checkBox","checkText","image"}.
                        Drives the UI's CPA:unknown rendering.
    sign              : Multiplier applied to numeric values before
                        formatting.  Income-statement balances are
                        stored as Debit−Credit (negative for Income
                        rows), so Form1065 lines that expect a positive
                        figure use sign=-1.
    checkedValue      : For checkBox/checkText only — the "on" export
                        value to stamp (typically ``/1`` or ``/2``).
    note              : Human description (flows to the UI ``note`` /
                        ``description`` column).
    """

    src_row:      str
    src_col:      str
    logicalKey:   str
    fType:        str = F_TEXT
    sign:         int = 1
    checkedValue: Optional[str] = None
    note:         str = ""


def apply_sign_and_format(raw: Any, sign: int = 1) -> str:
    """
    Normalise a numeric cell value for the FILL PDF.

    - ``None`` → empty string
    - numeric → apply sign, then format with thousands separator and 2dp
    - other   → ``str(raw)``

    Keeps parity with irsForm._fmt() for currency fields.
    """
    if raw is None or raw == "":
        return ""
    try:
        n = float(raw) * sign
        # Match irsForm _fmt: comma-separated, 2dp, no $ prefix.
        return f"{n:,.2f}"
    except (TypeError, ValueError):
        return str(raw)


def as_payload_row(
    *,
    formNm: str,
    tblID:  str,
    entry:  PubEntry,
    value:  Any,
) -> Dict[str, Any]:
    """
    Materialise one JSON-payload row for an irs.Form* view.

    Shape (keys are stable — UI templates bind to them):
        formNm       : str   — hidden field (point 8 of the refactor)
        logicalKey   : str
        src_tbl      : str   — the data object's tblID
        src_row      : str
        src_col      : str
        value        : str   — apply_sign_and_format(raw, entry.sign)
        publish      : True
        fType        : str
        checkedValue : str|None
        note         : str
    """
    return {
        "formNm":       formNm,
        "logicalKey":   entry.logicalKey,
        "src_tbl":      tblID,
        "src_row":      entry.src_row,
        "src_col":      entry.src_col,
        "value":        apply_sign_and_format(value, entry.sign),
        "raw":          value,
        "publish":      P_TRUE,
        "fType":        entry.fType,
        "checkedValue": entry.checkedValue,
        "note":         entry.note,
    }


__all__ = [
    "PubEntry",
    "F_TEXT", "F_CHECKBOX", "F_CHECKTEXT", "F_IMAGE",
    "P_TRUE", "P_FALSE", "P_CPA_UNKNOWN",
    "apply_sign_and_format", "as_payload_row",
]
