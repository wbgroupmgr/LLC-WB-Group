'''
llcBankView — bank CSV reconciliation view
Loads bank CSV (Wells Fargo format) from disk or via upload,
diffs against llcExpRev working JSON, and returns new transactions.

CSV format (no header): Date, Amount, -, CheckNo, Description
  e.g.: 01/15/2025,-150.00,*,101,MORTGAGE PAYMENT

Dedup key: "<dt>_<D|C><amt:0.2f>" matching ledgerGeneral.toTid logic.

Timestamp of last change: 2026.04.13
'''

import csv
import datetime
import io
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ledger pattern dict (mirrors subset of llcBank.expKWDict) — used for acct inference
_KW_MAP = [
    ("comwsc",          "Acct.Exp.Util",    "Water"),
    ("pedernales",      "Acct.Exp.Util",    "Electric"),
    ("dispre.al",       "Acct.Exp.Util",    "Waste"),
    ("allstate",        "Acct.Exp.Util",    "Insurance"),
    ("purchase authorized", "Acct.Exp.Other", "Approved Purchase"),
    ("acctverify",      "Acct.Rev.Fees.Other", "Customer payment setup"),
    ("nicola",          "Acct.Rev.Rent",    "Income.Rent"),
    ("alejandro",       "Acct.Rev.Rent",    "Income.Rent"),
    ("zelle from",      "Acct.Rev.Rent",    "Income.Rent"),
    ("purchase return", "Acct.Exp.Other",   "Return of materials"),
    ("deposit",         "Acct.Cash.Bank",   "Deposit"),
    ("withdrawal",      "Acct.Fixed.Tangible.InService", "Withdrawal"),
    ("venmo",           "Acct.Exp.Repair",  "Repair/Maintenance"),
    ("promotion bonus", "Acct.Cash.Bank",   "Bank Promotion"),
]


def _infer_acct(desc: str) -> str:
    dl = desc.lower()
    for kw, acct, _ in _KW_MAP:
        if kw in dl:
            return acct
    return "Acct.Exp.Other"


def _to_tid(dt: str, amt: float, a_type: str) -> str:
    dc = 'C' if a_type.lower() in ('credit', 'cr', 'c') else 'D'
    return f"{dt}_{dc}{abs(amt):.2f}"


def _parse_wf_csv(data: str) -> List[Dict[str, Any]]:
    '''Parse Wells Fargo CSV (no header): Date, Amount, -, CheckNo, Description'''
    rows = []
    reader = csv.reader(io.StringIO(data))
    for line in reader:
        if len(line) < 5:
            continue
        try:
            raw_dt = line[0].strip()
            raw_amt = float(line[1].strip().replace(',', ''))
            desc = line[4].strip()
        except (ValueError, IndexError):
            continue

        # Normalise date to %Y.%m.%d
        try:
            dt = datetime.datetime.strptime(raw_dt, '%m/%d/%Y').strftime('%Y.%m.%d')
        except ValueError:
            dt = raw_dt

        amt = abs(raw_amt)
        a_type = 'Debit' if raw_amt >= 0 else 'Credit'

        rows.append({
            'dt': dt,
            'amt': round(amt, 2),
            'aType': a_type,
            'desc': desc,
            'acct': _infer_acct(desc),
            'refDoc': desc,
        })

    return sorted(rows, key=lambda r: r['dt'])


class llcBankView:
    '''
    Read-only bank reconciliation view.
    Supports:
    - Auto-loading latest CSV from disk (derived from session paths)
    - CSV upload via /api/llcBank/upload_csv endpoint in llcMgmt
    - Diff against llcExpRev working JSON
    '''

    def __init__(self, eSession, bank_dir: Optional[str] = None):
        self.eSession = eSession
        self._bank_dir: Optional[Path] = Path(bank_dir) if bank_dir else None
        self._uploaded_rows: Optional[List[Dict[str, Any]]] = None  # set by upload handler

    def bind_session(self, eSession) -> None:
        self.eSession = eSession

    def object_name(self) -> str:
        return 'llcBank'

    # ── path resolution ───────────────────────────────────────────────────────

    def _get_bank_dir(self) -> Optional[Path]:
        if self._bank_dir and self._bank_dir.exists():
            return self._bank_dir

        # Try from LLC object attached to session
        llc = getattr(self.eSession, 'llc', None)
        if llc:
            yr = str(getattr(llc, 'yr', 2025))
            top = getattr(llc, 'TOP', None)
            dir_acct = getattr(llc, 'dirAccounting', 'books')
            if top:
                candidate = Path(top) / dir_acct / yr / 'BankStmts'
                if candidate.exists():
                    return candidate

        # Derive from llcExpRev working file path
        wk = self.eSession.oDict.get('llcExpRev')
        if wk:
            base = Path(wk.FN()).parent
            # Check AccountingData/<yr>/BankStmts
            for yr in [2026, 2025, 2024]:
                candidate = base / str(yr) / 'BankStmts'
                if candidate.exists():
                    return candidate
            # Check if base itself contains csv
            if any(f.suffix == '.csv' for f in base.iterdir() if f.is_file()):
                return base

        return None

    def _get_csv_files(self) -> List[str]:
        bank_dir = self._get_bank_dir()
        if not bank_dir:
            return []
        return sorted([
            str(f) for f in bank_dir.iterdir()
            if f.is_file() and f.suffix.lower() == '.csv'
        ])

    def _load_latest_csv(self) -> Tuple[List[Dict[str, Any]], bool]:
        '''Returns (bank_rows, csv_was_found).'''
        csv_files = self._get_csv_files()
        if not csv_files:
            return [], False
        latest = csv_files[-1]
        try:
            with open(latest, 'r', encoding='utf-8', errors='replace') as f:
                return _parse_wf_csv(f.read()), True
        except Exception as e:
            print(f"llcBankView: error reading {latest}: {e}")
            return [], False

    # ── dedup logic ───────────────────────────────────────────────────────────

    def _load_er_tids(self) -> set:
        wk = self.eSession.oDict.get('llcExpRev')
        if not wk:
            return set()
        data = wk.load()
        if not isinstance(data, list):
            return set()
        tids = set()
        for row in data:
            stored = row.get('tID')
            if stored:
                tids.add(stored)
            # Also add derived key in case tID format differs
            try:
                amt = float(row.get('amt', 0) or 0)
                a_type = str(row.get('aType', 'Debit'))
                tids.add(_to_tid(row.get('dt', ''), amt, a_type))
            except Exception:
                pass
        return tids

    def _diff(self, bank_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        '''Return bank rows not in llcExpRev.'''
        er_tids = self._load_er_tids()
        new_rows = []
        for row in bank_rows:
            tid = _to_tid(row['dt'], row['amt'], row['aType'])
            if tid not in er_tids:
                r = dict(row)
                r['tID'] = tid
                new_rows.append(r)
        return new_rows

    # ── upload interface ──────────────────────────────────────────────────────

    def load_from_csv_data(self, csv_data: str) -> List[Dict[str, Any]]:
        '''Parse uploaded CSV text, diff against llcExpRev, return new rows.'''
        bank_rows = _parse_wf_csv(csv_data)
        self._uploaded_rows = self._diff(bank_rows)
        return self._uploaded_rows

    # ── public interface ──────────────────────────────────────────────────────

    def load(self) -> List[Dict[str, Any]]:
        # Use previously uploaded rows if available
        if self._uploaded_rows is not None:
            return self._uploaded_rows

        # Otherwise load latest CSV from disk
        bank_rows, found = self._load_latest_csv()
        if not found:
            return []
        return self._diff(bank_rows)

    def stats(self) -> Dict[str, Any]:
        rows = self.load()
        csv_files = self._get_csv_files()
        debit_total = sum(r['amt'] for r in rows if r.get('aType') == 'Debit')
        credit_total = sum(r['amt'] for r in rows if r.get('aType') == 'Credit')
        return {
            'NewTransactions': len(rows),
            'NewDebits': round(debit_total, 2),
            'NewCredits': round(credit_total, 2),
            'CSVFilesFound': len(csv_files),
        }

    def meta(self) -> Dict[str, Any]:
        bank_dir = self._get_bank_dir()
        csv_files = self._get_csv_files()
        wk = self.eSession.oDict.get('llcExpRev')
        return {
            'objectName': self.object_name(),
            'bankDir': str(bank_dir) if bank_dir else None,
            'csvFiles': [os.path.basename(f) for f in csv_files],
            'llcExpRevWorking': wk.FN() if wk else None,
            'note': 'Shows bank transactions not yet in llcExpRev working file.',
        }

    def bank_dir_str(self) -> Optional[str]:
        d = self._get_bank_dir()
        return str(d) if d else None

    def csv_files(self) -> List[str]:
        return self._get_csv_files()

    def csv_loaded(self) -> bool:
        return bool(self._get_csv_files()) or (self._uploaded_rows is not None)

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        self._uploaded_rows = None
        return self.load()
