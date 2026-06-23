"""
ledger/bankAgent/bkAuditNotifier.py — Post-commit BookToIRS notification
Writes IngestAgent_notifications.json after a successful BankAgent.commit().
"""
from __future__ import annotations

import json
import datetime
from pathlib import Path


_NOTIF_FILE = 'IngestAgent_notifications.json'


def _acct_matches(acct: str, prefix: str) -> bool:
    return acct.startswith(prefix)


class BkAuditNotifier:

    def notify(self, committed_rows: list, llc) -> Path | None:
        """
        Write notification JSON for BookToIRS section agents.
        Returns path written, or None if no rows require notification.
        """
        if not committed_rows:
            return None

        try:
            from ledger import setup_paths
            year = getattr(setup_paths, 'YEAR', 2025)
            top  = getattr(setup_paths, 'TOP', None)
            if not top:
                return None
            out_dir = Path(top) / 'books' / str(year) / 'Forms' / '.agent_work'
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None

        agents: dict[str, list] = {
            'Form4562':  [],
            'Form8825':  [],
            'SchK1':     [],
            'AllAgents': [],
        }

        for cr in committed_rows:
            acct     = getattr(cr, 'acct', '')
            txn_type = getattr(cr, 'txn_type', '')
            rec      = {
                'dt':       getattr(cr, 'dt', ''),
                'amt':      getattr(cr, 'amt', 0),
                'acct':     acct,
                'txn_type': txn_type,
                'propNm':   getattr(cr, 'propNm', ''),
                'desc':     getattr(cr, 'desc', '')[:80],
            }

            if _acct_matches(acct, 'Acct.Fixed.Tangible.InConstruction'):
                agents['Form4562'].append({**rec, 'reason': 'CIP row — new depreciable cost basis'})
            if _acct_matches(acct, 'Acct.Fixed.'):
                agents['Form8825'].append({**rec, 'reason': 'fixed asset row'})
            if _acct_matches(acct, 'Acct.Equity.Owner.Capital.'):
                agents['SchK1'].append({**rec, 'reason': 'capital account change'})
            if txn_type == 'SPECIAL_WIRE':
                agents['AllAgents'].append({**rec, 'reason': 'SPECIAL_WIRE — significant financial event'})
            if txn_type == 'RENT_INCOME':
                agents['Form8825'].append({**rec, 'reason': 'new/existing rental income'})

        # Only write if at least one agent has entries
        if not any(agents.values()):
            return None

        payload = {
            'ts':           datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'notifications': agents,
        }
        out_path = out_dir / _NOTIF_FILE
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        return out_path
