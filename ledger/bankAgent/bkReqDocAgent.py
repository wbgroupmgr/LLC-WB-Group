"""
ledger/bankAgent/bkReqDocAgent.py — Requisition Document DB (audit trail)

Every bank transaction that cannot be fully explained by a KB vendor rule
requires a Requisition: a short operator-authored record explaining what was
purchased, for which property, and for what business purpose. Each requisition
is linked to exactly one GL transaction by tID.

  KB-Rules + Requisitions = complete audit coverage:
    - Recurring bills (utilities, insurance, rent) → KB rule
    - Ad-hoc purchases (hardware, contractor, one-time charges) → Requisition

Storage: books/<year>/BankStmts/req_docs_<year>.json
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path


def _req_docs_path(year: int, llc=None) -> Path:
    try:
        from ledger import setup_paths
        top   = setup_paths.TOP
        books = setup_paths.BOOKS_DIR or 'books'
        if top:
            p = Path(top) / books / str(year) / 'BankStmts'
            p.mkdir(parents=True, exist_ok=True)
            return p / f'req_docs_{year}.json'
    except Exception:
        pass
    return Path(f'/tmp/req_docs_{year}.json')


_FIELDS = ('tID', 'dt', 'req_date', 'amt', 'desc', 'acct', 'propNm', 'purpose', 'notes')


class BkReqDocAgent:
    """CRUD manager for the year's requisition document database (1 req ↔ 1 GL tID)."""

    def __init__(self, year: int, llc=None):
        self._year = year
        self._path = _req_docs_path(year, llc)
        self._docs: list[dict] = self._load()

    # ── persistence ────────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if self._path.exists():
            with open(self._path, encoding='utf-8') as f:
                return json.load(f)
        return []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, 'w', encoding='utf-8') as f:
            json.dump(self._docs, f, indent=2)

    # ── read ───────────────────────────────────────────────────────────────────

    def all(self) -> list[dict]:
        return list(self._docs)

    def lookup(self, tID: str) -> dict | None:
        return next((d for d in self._docs if d.get('tID') == tID), None)

    def as_map(self) -> dict[str, dict]:
        return {d['tID']: d for d in self._docs if d.get('tID')}

    # ── write ───────────────────────────────────────────────────────────────────

    def add(self, tID: str, dt: str, amt: float, desc: str,
            acct: str, propNm: str, purpose: str, notes: str = '',
            req_date: str = '') -> dict:
        """Upsert one requisition (replaces existing tID)."""
        entry = {
            'tID':      tID,
            'dt':       dt,
            'req_date': req_date or '',
            'amt':      float(amt or 0),
            'desc':     (desc or '')[:120],
            'acct':     acct,
            'propNm':   propNm,
            'purpose':  purpose,
            'notes':    notes,
            'created':  datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._docs = [d for d in self._docs if d.get('tID') != tID]
        self._docs.append(entry)
        self.save()
        return entry

    def update(self, tID: str, **kwargs) -> dict | None:
        allowed = set(_FIELDS) - {'tID'}
        for doc in self._docs:
            if doc.get('tID') == tID:
                for k, v in kwargs.items():
                    if k in allowed:
                        doc[k] = v
                self.save()
                return doc
        return None

    def delete(self, tID: str) -> bool:
        before = len(self._docs)
        self._docs = [d for d in self._docs if d.get('tID') != tID]
        if len(self._docs) < before:
            self.save()
            return True
        return False

    def set_all(self, docs: list) -> list:
        """Replace-all save from the Requisition editor. Each doc needs a tID
        (the GL link) and a propNm (issue #55 — every requisition must be
        associated with a specific property) — incomplete rows are skipped.
        Preserves/creates 'created'."""
        existing = self.as_map()
        clean = []
        for d in docs:
            tID = (d.get('tID') or '').strip()
            propNm = (d.get('propNm') or '').strip()
            if not tID or not propNm:
                continue
            prior = existing.get(tID, {})
            clean.append({
                'tID':      tID,
                'dt':       (d.get('dt') or '').strip(),
                'req_date': (d.get('req_date') or '').strip(),
                'amt':      float(d.get('amt') or 0),
                'desc':     (d.get('desc') or '')[:120],
                'acct':     (d.get('acct') or '').strip(),
                'propNm':   (d.get('propNm') or '').strip(),
                'purpose':  (d.get('purpose') or '').strip(),
                'notes':    (d.get('notes') or '').strip(),
                'created':  prior.get('created')
                            or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
        self._docs = clean
        self.save()
        return list(self._docs)

    @property
    def path(self) -> Path:
        return self._path
