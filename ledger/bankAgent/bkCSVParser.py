"""
ledger/bankAgent/bkCSVParser.py — Bank CSV → normalized row list

Architecture
────────────
Every bank CSV format is mapped into a single canonical schema before any
downstream code (dedup, IngestAgent, KB matching) touches the data.

NORMALIZED_COLUMNS defines that schema.  Each format contributes a
_norm_row_<fmt>() function that maps its raw column list → a normalized dict.
detect_format() identifies the format from the first non-empty row and raises
UnknownCSVFormat when it cannot — that is the extension point: add a new
_norm_row_<fmt>() and register it in _FORMAT_REGISTRY.

Supported formats (auto-detected from header / column structure):
  wf_old   — Old WF no-header export: Date, Amount, *, CheckNo, Description
  wf_new   — New WF header export:    DATE, DESCRIPTION, AMOUNT, CHECK #, STATUS
  chase    — Chase header export:     Details, Posting Date, Description, Amount, ...

Amount sign conventions (after normalization aType is always Debit|Credit):
  wf_old/wf_new  positive → Debit (income IN),  negative → Credit (expense OUT)
  chase          Details col text is primary; amount sign is fallback
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

# ── Canonical schema ──────────────────────────────────────────────────────────

NORMALIZED_COLUMNS = ['dt', 'amt', 'aType', 'desc', 'refDoc']
"""Every bank CSV format must produce dicts with exactly these keys.
  dt      — YYYY.MM.DD (normalised from raw date)
  amt     — positive float (absolute value)
  aType   — 'Debit' or 'Credit' (cash-movement direction)
  desc    — transaction description string
  refDoc  — same as desc by default; override if format has a separate memo
"""


class UnknownCSVFormat(ValueError):
    """Raised when detect_format() cannot identify the CSV layout.
    Caller should add a _norm_row_<fmt>() function and register it."""
    pass


# ── Date normalizer ───────────────────────────────────────────────────────────

def _norm_date(raw: str) -> str:
    """MM/DD/YYYY → YYYY.MM.DD; returns raw string unchanged on any other format."""
    import datetime
    raw = raw.strip()
    try:
        return datetime.datetime.strptime(raw, '%m/%d/%Y').strftime('%Y.%m.%d')
    except ValueError:
        return raw


# ── Format detection ──────────────────────────────────────────────────────────

def detect_format(first_row: list[str]) -> str:
    """Identify CSV format from the first non-empty row.

    Returns one of: 'wf_old', 'wf_new', 'chase'
    Raises UnknownCSVFormat if the layout is not recognised — this is the
    extension point: inspect first_row, add a normalizer, register it below.
    """
    if not first_row:
        raise UnknownCSVFormat("CSV appears to be empty (no rows found)")

    h0 = first_row[0].strip().strip('"').lower()

    # Chase: first col header is 'details' | 'transaction date' | 'post date'
    if h0 in ('details', 'transaction date', 'post date'):
        return 'chase'

    # New WF: first col header is 'date' (quoted or unquoted, case-insensitive)
    if h0 == 'date':
        return 'wf_new'

    # Old WF: no header; first cell looks like a date MM/DD/YYYY
    import datetime
    try:
        datetime.datetime.strptime(first_row[0].strip().strip('"'), '%m/%d/%Y')
        return 'wf_old'
    except ValueError:
        pass

    raise UnknownCSVFormat(
        f"Cannot identify CSV format from first row: {first_row[:3]!r}\n"
        "Add a _norm_row_<fmt>() in bkCSVParser.py and register it in _FORMAT_REGISTRY."
    )


# ── Per-format row normalizers ────────────────────────────────────────────────
# Each function receives ONE raw row (list[str]) and returns a normalized dict
# with keys matching NORMALIZED_COLUMNS, or None to skip the row.

def _norm_row_wf_old(cols: list[str]) -> dict[str, Any] | None:
    """Old WF no-header: Date(0), Amount(1), *(2), CheckNo(3), Description(4)
    Amount: positive → Debit (income IN), negative → Credit (expense OUT).
    """
    if len(cols) < 5:
        return None
    try:
        raw_amt = float(cols[1].strip().replace(',', ''))
        desc    = cols[4].strip()
        raw_dt  = cols[0].strip()
    except (ValueError, IndexError):
        return None
    return {
        'dt':     _norm_date(raw_dt),
        'amt':    abs(round(raw_amt, 2)),
        'aType':  'Debit' if raw_amt >= 0 else 'Credit',
        'desc':   desc,
        'refDoc': desc,
    }


def _norm_row_wf_new(cols: list[str], headers: list[str]) -> dict[str, Any] | None:
    """New WF header: DATE(0), DESCRIPTION(1), AMOUNT(2), CHECK #(3), STATUS(4)
    Amount: positive → Debit (income IN), negative → Credit (expense OUT).
    """
    if len(cols) < 3:
        return None
    try:
        raw_amt = float(cols[2].strip().replace(',', '').replace('$', ''))
        desc    = cols[1].strip()
        raw_dt  = cols[0].strip()
    except (ValueError, IndexError):
        return None
    return {
        'dt':     _norm_date(raw_dt),
        'amt':    abs(round(raw_amt, 2)),
        'aType':  'Debit' if raw_amt >= 0 else 'Credit',
        'desc':   desc,
        'refDoc': desc,
    }


def _norm_row_chase(cols: list[str], headers: list[str]) -> dict[str, Any] | None:
    """Chase header: Details(0), Posting Date(1), Description(2), Amount(3), ...
    aType derived from Details column text; amount sign is fallback.
    """
    if len(cols) < 4:
        return None

    def _col(name: str, fallback: int) -> str:
        for i, h in enumerate(headers):
            if name in h and i < len(cols):
                return cols[i].strip()
        return cols[fallback].strip() if fallback < len(cols) else ''

    try:
        details = _col('details', 0).upper()
        raw_dt  = _col('posting date', 1) or _col('post date', 1) or _col('transaction date', 0)
        desc    = _col('description', 2)
        raw_amt = float(_col('amount', 3).replace(',', '').replace('$', ''))
    except (ValueError, IndexError):
        return None

    if not raw_dt or not desc:
        return None

    if details.startswith(('DEBIT', 'ACH_DEBIT', 'DEBIT_CARD', 'CHECK')):
        a_type = 'Debit'
    elif details.startswith(('CREDIT', 'ACH_CREDIT', 'DIRECT_DEP')):
        a_type = 'Credit'
    else:
        a_type = 'Debit' if raw_amt < 0 else 'Credit'

    return {
        'dt':     _norm_date(raw_dt),
        'amt':    abs(round(raw_amt, 2)),
        'aType':  a_type,
        'desc':   desc,
        'refDoc': desc,
    }


# ── Format registry ───────────────────────────────────────────────────────────
# Maps format name → (needs_headers: bool, normalizer callable)
# needs_headers=True: normalizer receives (cols, headers); False: receives (cols,)

_FORMAT_REGISTRY: dict[str, tuple[bool, Any]] = {
    'wf_old': (False, _norm_row_wf_old),
    'wf_new': (True,  _norm_row_wf_new),
    'chase':  (True,  _norm_row_chase),
}


# ── Core parser ───────────────────────────────────────────────────────────────

def _parse_wf_csv(data: str, fmt: str | None = None) -> list[dict[str, Any]]:
    """Parse bank CSV text → list of normalized row dicts sorted by dt.

    fmt — override format detection (pass detect_format() result if already known).
    Raises UnknownCSVFormat for unrecognised layouts.
    """
    reader     = list(csv.reader(io.StringIO(data)))
    nonempty   = [row for row in reader if any(c.strip() for c in row)]
    if not nonempty:
        return []

    if fmt is None:
        fmt = detect_format(nonempty[0])

    needs_headers, normalizer = _FORMAT_REGISTRY[fmt]

    headers: list[str] = []
    data_rows: list[list[str]] = nonempty

    if needs_headers:
        headers   = [c.strip().lower() for c in nonempty[0]]
        data_rows = nonempty[1:]

    rows: list[dict[str, Any]] = []
    for cols in data_rows:
        norm = normalizer(cols, headers) if needs_headers else normalizer(cols)
        if norm:
            rows.append(norm)

    return sorted(rows, key=lambda r: r['dt'])


# ── tID stamping ──────────────────────────────────────────────────────────────

def _make_tID(dt: str, amt: float, a_type: str) -> str:
    dc = 'C' if str(a_type).strip().lower() in ('credit', 'cr', 'c') else 'D'
    return f"{dt}_{dc}{abs(float(amt)):.2f}"


# ── Pandas fallback ───────────────────────────────────────────────────────────

def _parse_pandas_fallback(path: Path) -> list[dict[str, Any]]:
    """Last-resort: use pandas with column-name heuristics.
    Only called when _parse_wf_csv() returns 0 rows (not UnknownCSVFormat).
    """
    try:
        import pandas as pd
        df = pd.read_csv(path, encoding='utf-8', on_bad_lines='skip')
    except Exception:
        try:
            import pandas as pd
            df = pd.read_csv(path, encoding='latin-1', on_bad_lines='skip')
        except Exception:
            return []

    cl = {c.lower().strip(): c for c in df.columns}

    def find(*candidates: str) -> str | None:
        for c in candidates:
            for k, orig in cl.items():
                if c in k:
                    return orig
        return None

    date_col = find('posting date', 'post date', 'transaction date', 'date')
    amt_col  = find('amount')
    desc_col = find('description', 'memo', 'desc')
    det_col  = find('details', 'type')
    if not date_col or not amt_col:
        return []

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        try:
            raw_dt = str(row[date_col]).strip()
            amt_f  = float(str(row[amt_col]).replace(',', '').replace('$', ''))
            desc   = str(row[desc_col]).strip() if desc_col else ''
        except (ValueError, TypeError):
            continue
        details = str(row[det_col]).upper().strip() if det_col else ''
        if details.startswith('DEBIT'):
            a_type = 'Debit'
        elif details.startswith('CREDIT'):
            a_type = 'Credit'
        else:
            a_type = 'Debit' if amt_f < 0 else 'Credit'
        rows.append({
            'dt': _norm_date(raw_dt), 'amt': abs(round(amt_f, 2)),
            'aType': a_type, 'desc': desc, 'refDoc': desc,
        })
    return sorted(rows, key=lambda r: r['dt'])


# ── Public API ────────────────────────────────────────────────────────────────

class BankCSVParser:
    """Parse any supported bank CSV into normalized rows with tID stamped."""

    @staticmethod
    def parse(csv_path: str | Path) -> list[dict[str, Any]]:
        path = Path(csv_path)
        with open(path, encoding='utf-8', errors='replace') as fh:
            data = fh.read()

        try:
            rows = _parse_wf_csv(data)
        except UnknownCSVFormat as exc:
            # Surface the error as a logged warning; try pandas as last resort
            import warnings
            warnings.warn(f"BankCSVParser: {exc}", stacklevel=2)
            rows = _parse_pandas_fallback(path)

        # Fallback if structured parse returned nothing but didn't raise
        if not rows:
            rows = _parse_pandas_fallback(path)

        for row in rows:
            row['tID'] = _make_tID(row['dt'], row['amt'], row['aType'])

        return rows
