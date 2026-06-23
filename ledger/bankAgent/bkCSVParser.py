"""
ledger/bankAgent/bkCSVParser.py — Wells Fargo CSV → list[RawRow]
Wraps ui.llcBankView._parse_wf_csv and stamps each row with its tID.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _make_tID(dt: str, amt: float, a_type: str) -> str:
    dc = 'C' if str(a_type).strip().lower() in ('credit', 'cr', 'c') else 'D'
    return f"{dt}_{dc}{abs(float(amt)):.2f}"


class BankCSVParser:
    """Parses a Wells Fargo bank-statement CSV into raw row dicts."""

    @staticmethod
    def parse(csv_path: str | Path) -> list[dict[str, Any]]:
        """Read csv_path and return sorted list of raw row dicts with tID stamped."""
        from ui.llcBankView import _parse_wf_csv

        path = Path(csv_path)
        with open(path, encoding='utf-8', errors='replace') as fh:
            rows = _parse_wf_csv(fh.read())

        for row in rows:
            row['tID'] = _make_tID(row['dt'], row['amt'], row['aType'])

        return rows  # already sorted by dt from _parse_wf_csv
