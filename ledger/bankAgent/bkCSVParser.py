"""
ledger/bankAgent/bkCSVParser.py — multi-bank CSV → list[RawRow]

Supported formats (auto-detected):
  Chase        — header row "Details,Posting Date,Description,Amount,Type,..."
                 Details col: DEBIT = money out, CREDIT = money in.
  Wells Fargo  — no header; columns: Date, Amount, -, CheckNo, Description
                 Amount sign: positive = debit (out), negative = credit (in).

If both structured parsers return 0 rows, falls back to pandas read_csv()
using column-name heuristics for the date/amount/description fields.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any


def _make_tID(dt: str, amt: float, a_type: str) -> str:
    dc = 'C' if str(a_type).strip().lower() in ('credit', 'cr', 'c') else 'D'
    return f"{dt}_{dc}{abs(float(amt)):.2f}"


def _norm_date(raw: str) -> str:
    """MM/DD/YYYY → YYYY.MM.DD; pass through anything else."""
    import datetime
    raw = raw.strip()
    try:
        return datetime.datetime.strptime(raw, '%m/%d/%Y').strftime('%Y.%m.%d')
    except ValueError:
        return raw


def _detect_header_format(first_row: list[str]) -> str:
    """Return 'chase', 'wf_new', or 'wf_old' based on the first CSV row."""
    if not first_row:
        return 'wf_old'
    h0 = first_row[0].strip().lower()
    if h0 in ('details', 'transaction date', 'post date'):
        return 'chase'
    # New WF format: header row starting with "DATE" (quoted or not)
    if h0 in ('date',):
        return 'wf_new'
    return 'wf_old'


def _parse_chase(data: str) -> list[dict[str, Any]]:
    """
    Chase checking CSV:
      Details, Posting Date, Description, Amount, Type, Balance, Check or Slip #
    Details col: DEBIT = money leaving account; CREDIT = money arriving.
    """
    rows: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(data))
    headers: list[str] | None = None

    for line in reader:
        if not any(c.strip() for c in line):
            continue
        if headers is None:
            headers = [c.strip().lower() for c in line]
            continue
        if len(line) < 4:
            continue

        def col(name: str, fallback: int) -> str:
            for i, h in enumerate(headers or []):
                if name in h and i < len(line):
                    return line[i].strip()
            return line[fallback].strip() if fallback < len(line) else ''

        try:
            details = col('details', 0).upper()
            raw_dt  = col('posting date', 1) or col('post date', 1) or col('transaction date', 0)
            desc    = col('description', 2)
            raw_amt = col('amount', 3)
            if not raw_dt or not raw_amt:
                continue
            amt_f = float(raw_amt.replace(',', '').replace('$', ''))
        except (ValueError, IndexError):
            continue

        # Primary signal: Details column text; back up with amount sign
        if details.startswith('DEBIT') or details in ('ACH_DEBIT', 'DEBIT_CARD', 'CHECK'):
            a_type = 'Debit'
        elif details.startswith('CREDIT') or details in ('ACH_CREDIT', 'DIRECT_DEP'):
            a_type = 'Credit'
        else:
            # Fall back to sign: Chase negative = money out = Debit
            a_type = 'Debit' if amt_f < 0 else 'Credit'

        rows.append({
            'dt': _norm_date(raw_dt),
            'amt': abs(round(amt_f, 2)),
            'aType': a_type,
            'desc': desc,
            'refDoc': desc,
        })

    return sorted(rows, key=lambda r: r['dt'])


def _parse_wf_new(data: str) -> list[dict[str, Any]]:
    """New Wells Fargo header CSV: DATE, DESCRIPTION, AMOUNT, CHECK #, STATUS.
    Amount sign: positive = Debit (income IN), negative = Credit (expense OUT).
    """
    rows: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(data))
    headers: list[str] | None = None
    for line in reader:
        if not any(c.strip() for c in line):
            continue
        if headers is None:
            headers = [c.strip().lower() for c in line]
            continue
        if len(line) < 3:
            continue
        try:
            raw_dt  = line[0].strip()
            desc    = line[1].strip()
            raw_amt = float(line[2].strip().replace(',', '').replace('$', ''))
        except (ValueError, IndexError):
            continue
        a_type = 'Debit' if raw_amt >= 0 else 'Credit'
        rows.append({
            'dt': _norm_date(raw_dt),
            'amt': abs(round(raw_amt, 2)),
            'aType': a_type,
            'desc': desc,
            'refDoc': desc,
        })
    return sorted(rows, key=lambda r: r['dt'])


def _parse_wf(data: str) -> list[dict[str, Any]]:
    """Old Wells Fargo no-header CSV: Date, Amount, -, CheckNo, Description.
    Amount sign: positive = Debit (income IN), negative = Credit (expense OUT).
    """
    rows: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(data))
    for line in reader:
        if len(line) < 5:
            continue
        try:
            raw_dt  = line[0].strip()
            raw_amt = float(line[1].strip().replace(',', ''))
            desc    = line[4].strip()
        except (ValueError, IndexError):
            continue
        # WF: positive = debit (expense out), negative = credit (income in)
        a_type = 'Debit' if raw_amt >= 0 else 'Credit'
        rows.append({
            'dt': _norm_date(raw_dt),
            'amt': abs(round(raw_amt, 2)),
            'aType': a_type,
            'desc': desc,
            'refDoc': desc,
        })
    return sorted(rows, key=lambda r: r['dt'])


def _parse_pandas_fallback(path: Path) -> list[dict[str, Any]]:
    """Last-resort: use pandas to read any CSV and map columns by name heuristic."""
    try:
        import pandas as pd
        df = pd.read_csv(path, encoding='utf-8', on_bad_lines='skip')
    except Exception:
        try:
            import pandas as pd
            df = pd.read_csv(path, encoding='latin-1', on_bad_lines='skip')
        except Exception:
            return []

    rows: list[dict[str, Any]] = []
    cols_lower = {c.lower().strip(): c for c in df.columns}

    def find_col(*candidates: str) -> str | None:
        for c in candidates:
            for k, orig in cols_lower.items():
                if c in k:
                    return orig
        return None

    date_col = find_col('posting date', 'post date', 'transaction date', 'date')
    amt_col  = find_col('amount')
    desc_col = find_col('description', 'memo', 'desc')
    det_col  = find_col('details', 'type')

    if not date_col or not amt_col:
        return []

    for _, row in df.iterrows():
        try:
            raw_dt = str(row[date_col]).strip()
            raw_amt_s = str(row[amt_col]).replace(',', '').replace('$', '').strip()
            amt_f = float(raw_amt_s)
            desc = str(row[desc_col]).strip() if desc_col else ''
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
            'dt': _norm_date(raw_dt),
            'amt': abs(round(amt_f, 2)),
            'aType': a_type,
            'desc': desc,
            'refDoc': desc,
        })

    return sorted(rows, key=lambda r: r['dt'])


class BankCSVParser:
    """Auto-detects bank CSV format and parses to raw row dicts."""

    @staticmethod
    def parse(csv_path: str | Path) -> list[dict[str, Any]]:
        path = Path(csv_path)
        with open(path, encoding='utf-8', errors='replace') as fh:
            data = fh.read()

        first_row: list[str] = []
        for line in csv.reader(io.StringIO(data)):
            if any(c.strip() for c in line):
                first_row = line
                break

        fmt = _detect_header_format(first_row)
        if fmt == 'chase':
            rows = _parse_chase(data)
        elif fmt == 'wf_new':
            rows = _parse_wf_new(data)
        else:
            rows = _parse_wf(data)

        # Pandas fallback if structured parsers produced nothing
        if not rows:
            rows = _parse_pandas_fallback(path)

        for row in rows:
            row['tID'] = _make_tID(row['dt'], row['amt'], row['aType'])

        return rows
