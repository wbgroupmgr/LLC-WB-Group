"""
ledger/bankAgent/bkDuplicateDetector.py — Three-scope duplicate detection

Scope 1 — Intra-CSV:  duplicate tIDs within the statement being ingested;
                       RETURN_PAIR (PURCHASE RETURN matching same-vendor purchase)
Scope 2 — llcExpRev:  tID already exists in llcExpRev["records"] → DUPLICATE
Scope 3 — Full GL:    (dt, abs(amt)) pair present in llcAssets / llcPayables /
                       llcReceivables → AMOUNT_COLLISION (warning, not block)
"""
from __future__ import annotations

import datetime
import re
from typing import Any


def _make_tID(dt: str, amt: float, a_type: str) -> str:
    dc = 'C' if str(a_type).strip().lower() in ('credit', 'cr', 'c') else 'D'
    return f"{dt}_{dc}{abs(float(amt)):.2f}"


def _dt_obj(dt_str: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(dt_str, '%Y.%m.%d').date()
    except ValueError:
        return datetime.date.min


class BkDuplicateDetector:

    def __init__(self, llc=None):
        self._llc = llc

    # ── public interface ──────────────────────────────────────────────────────

    def scan(self, raw_rows: list[dict]) -> list[dict]:
        """
        Stamp each row's '_flag' field with the first matching flag:
          'DUPLICATE' | 'AMOUNT_COLLISION' | 'RETURN_PAIR' | '' (clean)
        Returns the same list (mutated in-place for efficiency).
        """
        rows = [dict(r, _flag='', _flag_detail='') for r in raw_rows]
        self._scope1_intra_csv(rows)
        self._scope2_exprev(rows)
        self._scope3_full_gl(rows)
        return rows

    # ── Scope 1 — intra-CSV ───────────────────────────────────────────────────

    def _scope1_intra_csv(self, rows: list[dict]) -> None:
        seen_tids: set[str] = set()
        for row in rows:
            tid = row.get('tID', '')
            if tid in seen_tids:
                row['_flag'] = 'DUPLICATE'
                row['_flag_detail'] = 'tID collision within CSV'
            else:
                seen_tids.add(tid)

        # RETURN_PAIR detection for non-duplicate rows
        purchases = [
            r for r in rows
            if r['_flag'] == '' and 'purchase return' not in r.get('desc', '').lower()
            and r.get('aType', '').lower() == 'credit'  # money out = purchase
        ]
        returns = [
            r for r in rows
            if r['_flag'] == '' and 'purchase return' in r.get('desc', '').lower()
        ]

        matched_purchases: set[int] = set()
        for ret in returns:
            ret_dt   = _dt_obj(ret.get('dt', ''))
            ret_amt  = abs(float(ret.get('amt', 0)))
            ret_desc = ret.get('desc', '').lower()

            # Extract vendor name from return desc (strip standard prefixes)
            ret_vendor = re.sub(
                r'^purchase return authorized on \d+/\d+ ', '', ret_desc, flags=re.I
            ).split()[0] if ret_desc else ''

            best = None
            for i, pur in enumerate(purchases):
                if i in matched_purchases:
                    continue
                if abs(float(pur.get('amt', 0))) != ret_amt:
                    continue
                pur_dt = _dt_obj(pur.get('dt', ''))
                if abs((ret_dt - pur_dt).days) > 3:
                    continue
                if ret_vendor and ret_vendor not in pur.get('desc', '').lower():
                    continue
                best = (i, pur)
                break

            if best:
                matched_purchases.add(best[0])
                ret['_flag'] = 'RETURN_PAIR'
                pur_tid = best[1].get('tID', '')
                ret['_flag_detail'] = f'matched purchase tID={pur_tid}'
            else:
                ret['_flag'] = 'RETURN_PAIR'
                ret['_flag_detail'] = 'no matching purchase found in CSV'

    # ── Scope 2 — vs llcExpRev ────────────────────────────────────────────────

    def _scope2_exprev(self, rows: list[dict]) -> None:
        er_tids = self._load_exprev_tids()
        for row in rows:
            if row['_flag'] != '':
                continue
            if row.get('tID', '') in er_tids:
                row['_flag'] = 'DUPLICATE'
                row['_flag_detail'] = 'tID found in llcExpRev'

    def _load_exprev_tids(self) -> set[str]:
        if self._llc is None:
            return set()
        try:
            from ledger.llcExpRev import llcExpRev
            recs = llcExpRev(self._llc).load()
            tids = set()
            for r in recs:
                if r.get('tID'):
                    tids.add(r['tID'])
                # Derived key (in case existing records use different format)
                try:
                    tids.add(_make_tID(r['dt'], float(r['amt']), r['aType']))
                except Exception:
                    pass
            return tids
        except Exception:
            return set()

    # ── Scope 3 — full GL AMOUNT_COLLISION ───────────────────────────────────

    def _scope3_full_gl(self, rows: list[dict]) -> None:
        """(dt, abs(amt)) pairs from llcAssets / llcPayables / llcReceivables."""
        gl_pairs: set[tuple] = self._load_gl_dt_amt_pairs()
        for row in rows:
            if row['_flag'] != '':
                continue
            key = (row.get('dt', ''), round(abs(float(row.get('amt', 0))), 2))
            if key in gl_pairs:
                row['_flag'] = 'AMOUNT_COLLISION'
                row['_flag_detail'] = f'(dt={key[0]}, amt={key[1]}) found in GL'

    def _load_gl_dt_amt_pairs(self) -> set[tuple]:
        if self._llc is None:
            return set()
        pairs: set[tuple] = set()
        try:
            from ledger.llcAssets import llcAssets
            from ledger.llcPayables import llcPayables
            from ledger.llcReceivables import llcReceivables
            for Cls in (llcAssets, llcPayables, llcReceivables):
                for r in Cls(self._llc).load():
                    try:
                        amt = round(abs(float(r['amt'])), 2)
                        if amt > 0:
                            pairs.add((r['dt'], amt))
                    except Exception:
                        pass
        except Exception:
            pass
        return pairs
