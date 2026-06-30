"""
ledger/bankAgent/bkCSVParser.py — multi-bank CSV → list[RawRow]

Supported formats (auto-detected):
  Wells Fargo  — no header; columns: Date, Amount, -, CheckNo, Description
  Chase        — header row "Details,Posting Date,Description,Amount,Type,..."
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


def _is_chase_header(first_row: list[str]) -> bool:
    if not first_row:
        return False
    h = [c.strip().lower() for c in first_row]
    return h[0] in ('details', 'transaction date', 'post date')


def _parse_chase(data: str) -> list[dict[str, Any]]:
    """
    Chase checking CSV format:
      Details, Posting Date, Description, Amount, Type, Balance, Check or Slip #
    Amount sign: negative = debit (money out), positive = credit (money in).
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
        try:
            # Map by header position
            def col(name: str, fallback_idx: int) -> str:
                if headers:
                    for i, h in enumerate(headers):
                        if name in h and i < len(line):
                            return line[i].strip()
                return line[fallback_idx].strip() if fallback_idx < len(line) else ''

            raw_dt  = col('posting date', 1) or col('post date', 1) or col('transaction date', 0)
            raw_amt = col('amount', 3)
            desc    = col('description', 2)

            if not raw_dt or not raw_amt:
                continue

            amt_f = float(raw_amt.replace(',', '').replace('$', ''))
        except (ValueError, IndexError):
            continue

        # Chase: negative = debit (outflow), positive = credit (inflow)
        a_type = 'Credit' if amt_f < 0 else 'Debit'
        amt    = abs(round(amt_f, 2))
        dt     = _norm_date(raw_dt)

        rows.append({'dt': dt, 'amt': amt, 'aType': a_type, 'desc': desc, 'refDoc': desc})

    return sorted(rows, key=lambda r: r['dt'])


def _parse_wf(data: str) -> list[dict[str, Any]]:
    """Wells Fargo no-header CSV: Date, Amount, -, CheckNo, Description."""
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

        amt    = abs(raw_amt)
        a_type = 'Debit' if raw_amt >= 0 else 'Credit'
        dt     = _norm_date(raw_dt)

        rows.append({'dt': dt, 'amt': round(amt, 2), 'aType': a_type, 'desc': desc, 'refDoc': desc})

    return sorted(rows, key=lambda r: r['dt'])


class BankCSVParser:
    """Auto-detects bank format (Chase or Wells Fargo) and parses to raw row dicts."""

    @staticmethod
    def parse(csv_path: str | Path) -> list[dict[str, Any]]:
        path = Path(csv_path)
        with open(path, encoding='utf-8', errors='replace') as fh:
            data = fh.read()

        # Detect format from first non-empty row
        first_row: list[str] = []
        for line in csv.reader(io.StringIO(data)):
            if any(c.strip() for c in line):
                first_row = line
                break

        if _is_chase_header(first_row):
            rows = _parse_chase(data)
        else:
            rows = _parse_wf(data)

        for row in rows:
            row['tID'] = _make_tID(row['dt'], row['amt'], row['aType'])

        return rows
