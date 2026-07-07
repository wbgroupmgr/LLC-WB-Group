"""
ledger/bankAgent/BankAgent.py — BankToBook outer orchestrator (issue #40 P2)

Phase 1 — preview(csv_path, propNm_default, year) → PreviewResult   (read-only)
Phase 2 — commit(preview) → CommitResult                             (write)

No direct CSV → commit path. The operator always reviews a PreviewResult first.
"""
from __future__ import annotations

import json
import datetime
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ledger.bankAgent.bkCSVParser import BankCSVParser
from ledger.bankAgent.bkCIPGuard import BkCIPGuard
from ledger.bankAgent.bkDuplicateDetector import BkDuplicateDetector
from ledger.bankAgent.bkAuditNotifier import BkAuditNotifier
from ledger.bankAgent.bkReqPropGuard import BkReqPropGuard
from ledger.bankAgent.IngestAgent import IngestAgent, ClassifiedRow


# ── result objects ─────────────────────────────────────────────────────────────

@dataclass
class PreviewStats:
    total: int = 0
    auto: int = 0
    review: int = 0
    flagged: int = 0
    duplicate: int = 0
    return_pair: int = 0
    amount_collision: int = 0
    need_req_doc: int = 0
    propnm_mismatch: int = 0

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class PreviewResult:
    rows: list[ClassifiedRow]
    stats: PreviewStats
    source: str
    ts: str
    _token: str = field(default_factory=lambda: str(uuid.uuid4()), repr=False)


class PropNmMismatchError(ValueError):
    """
    Raised by commit() when one or more rows' propNm disagrees with their
    linked requisition's propNm and the caller hasn't explicitly opted to
    override (issue #55 conflict-resolution UI). Carries structured detail
    — not just a message — so the UI can offer real choices (fix the
    requisition, commit as-is, cancel) instead of a dead-end alert.
    """
    def __init__(self, mismatches: list[dict]):
        self.mismatches = mismatches
        tids = ', '.join(m['tID'] for m in mismatches)
        super().__init__(
            f'{len(mismatches)} row(s) have a propNm that disagrees with '
            f'their linked requisition: {tids}'
        )


@dataclass
class CommitResult:
    rows_written: int
    rows_duplicate: int
    rows_amount_collision: int
    source: str
    ts: str
    notif_path: str | None = None


# ── acct helpers ───────────────────────────────────────────────────────────────

def _acct_type_str(acct: str) -> str:
    if acct.startswith('Acct.Exp.'):   return 'Expense'
    if acct.startswith('Acct.Rev.'):   return 'Income'
    if acct.startswith('Acct.Equity.'): return 'Equity'
    if acct.startswith('Acct.Fixed.'): return 'Asset'
    if acct.startswith('Acct.Cash.'):  return 'Asset'
    if acct.startswith('Acct.AR.'):    return 'Asset'
    if acct.startswith('Acct.Liab.'): return 'Liability'
    return 'Other'


def _to_exprev_record(cr: ClassifiedRow, csv_filename: str) -> dict:
    """
    Convert ClassifiedRow (IngestAgent convention: acct=Expense, Ledger=Cash.Bank)
    to llcExpRev convention (acct=Acct.Cash.Bank, Ledger=Expense).
    aType is preserved from the raw CSV (describes cash movement direction).
    """
    ledger_acct = cr.acct  # the classified expense/income/equity account
    return {
        'acct':     'Acct.Cash.Bank',
        'Ledger':   ledger_acct,
        'aType':    cr.aType,
        'amt':      cr.amt,
        'desc':     cr.desc,
        'propNm':   cr.propNm,
        'acctSub':  cr.acctSub,
        'acctType': _acct_type_str(ledger_acct),
        'tID':      cr.tID,
        'tDB':      'llcBank',
        'refDoc':   cr.refDoc,
        'refDB':    f'BankStmts/{csv_filename}',
        'propAddr': None,
        'propID':   None,
        'propOwners': None,
        '_unknown': '',
        'dt':       cr.dt,
    }


# ── BankAgent ─────────────────────────────────────────────────────────────────

class BankAgent:
    """Outer orchestrator for the two-phase BankToBook pipeline."""

    def __init__(self, llc):
        self._llc       = llc
        self._ia        = IngestAgent(llc)
        self._cip       = BkCIPGuard(llc)
        self._dedup     = BkDuplicateDetector(llc)
        self._notifier  = BkAuditNotifier()

    # ── Phase 1 — Preview ─────────────────────────────────────────────────────

    def preview(self, csv_path: str | Path,
                propNm_default: str = '',
                year: int | None = None) -> PreviewResult:
        """
        Parse CSV, classify every row, run dedup + CIP guard.
        Nothing is written. Returns PreviewResult for operator review.
        """
        csv_path = Path(csv_path)
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Step 1 — parse CSV
        raw_rows = BankCSVParser.parse(csv_path)

        # Step 2 — 3-scope dedup (stamps _flag on each raw row)
        scanned = self._dedup.scan(raw_rows)

        # Requisition propNm cross-check (issue #55) — loaded once per preview.
        req_guard = BkReqPropGuard(year, self._llc)

        # Step 3 — classify each non-DUPLICATE row
        result_rows: list[ClassifiedRow] = []
        stats = PreviewStats(total=len(scanned))

        for raw in scanned:
            flag = raw.get('_flag', '')
            detail = raw.get('_flag_detail', '')

            if flag == 'DUPLICATE':
                cr = self._make_passthrough(raw, flag)
                stats.duplicate += 1
                result_rows.append(cr)
                continue

            if flag == 'RETURN_PAIR':
                cr = self._ia.classify(raw, {'propNm': propNm_default})
                cr.flag = 'RETURN_PAIR'
                stats.return_pair += 1

            elif flag == 'AMOUNT_COLLISION':
                cr = self._ia.classify(raw, {'propNm': propNm_default})
                cr.flag = 'AMOUNT_COLLISION'
                stats.amount_collision += 1

            else:
                # Step 4 — classify via IngestAgent
                cr = self._ia.classify(raw, {'propNm': propNm_default})

                # Step 5 — CIP guard (hard override, no bypass)
                new_acct, cip_violated = self._cip.check(cr.propNm, cr.acct)
                if cip_violated:
                    cr.acct = new_acct
                    cr.flag = 'NEED_REQ_DOC'
                    cr.confidence = 'flagged'
                    stats.need_req_doc += 1

            # Step 6 — requisition propNm cross-check (issue #55). Runs for
            # every non-duplicate row regardless of any flag already set
            # above; a mismatch takes display precedence since it blocks
            # commit outright (see commit()'s hard gate below).
            mismatch, _req_propNm = req_guard.check(cr.tID, cr.propNm)
            if mismatch:
                cr.flag = 'PROPNM_MISMATCH'
                cr.confidence = 'flagged'
                stats.propnm_mismatch += 1

            self._count_confidence(stats, cr)
            result_rows.append(cr)

        return PreviewResult(
            rows=result_rows,
            stats=stats,
            source=csv_path.name,
            ts=ts,
        )

    # ── Phase 2 — Commit ──────────────────────────────────────────────────────

    def commit(self, preview: PreviewResult, year: int | None = None,
               override_propnm_mismatch: bool = False) -> CommitResult:
        """
        Write approved rows to llcExpRev + LogHistory.
        Skips DUPLICATE rows. AMOUNT_COLLISION rows are written with a warning.
        Invariant: only accepts a PreviewResult object (no direct CSV → commit).
        """
        if not isinstance(preview, PreviewResult):
            raise TypeError('commit() requires a PreviewResult from preview()')

        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        csv_name = preview.source
        to_write = [cr for cr in preview.rows if cr.flag != 'DUPLICATE']
        collisions = [cr for cr in to_write if cr.flag == 'AMOUNT_COLLISION']

        # Hard gate (issue #55) — re-verify propNm against linked requisitions
        # using each row's CURRENT propNm (the operator may have edited it
        # since preview). Never trust the flag computed at preview time; a
        # stale mismatch flag or a newly-introduced one must both be caught
        # here, since this is the last checkpoint before a write.
        #
        # override_propnm_mismatch is an explicit, operator-visible choice
        # made through the commit-conflict dialog (not a silent default) —
        # unlike BkCIPGuard's IRC §263 capitalization rule, a propNm/req
        # disagreement is a data-consistency check, not a legal requirement,
        # so a deliberate "commit as-is, leave the requisition alone" is a
        # legitimate operator call.
        if not override_propnm_mismatch:
            req_guard = BkReqPropGuard(year, self._llc)
            mismatches = []
            for cr in to_write:
                is_mismatch, req_propNm = req_guard.check(cr.tID, cr.propNm)
                if is_mismatch:
                    mismatches.append({'tID': cr.tID, 'propNm': cr.propNm,
                                       'req_propNm': req_propNm})
            if mismatches:
                raise PropNmMismatchError(mismatches)

        # Build llcExpRev records (convert IngestAgent convention → llcExpRev convention)
        new_records = [_to_exprev_record(cr, csv_name) for cr in to_write]

        # Append to llcExpRev (load → extend → save)
        self._write_exprev(new_records, csv_name, to_write, ts, preview)

        # BkAuditNotifier
        notif_path = self._notifier.notify(to_write, self._llc)

        return CommitResult(
            rows_written=len(new_records),
            rows_duplicate=preview.stats.duplicate,
            rows_amount_collision=len(collisions),
            source=csv_name,
            ts=ts,
            notif_path=str(notif_path) if notif_path else None,
        )

    def _write_exprev(self, new_records: list[dict], csv_name: str,
                      classified_rows: list[ClassifiedRow],
                      ts: str, preview: PreviewResult) -> None:
        """Append records and LogHistory entry to llcExpRev JSON."""
        from ledger.llcExpRev import llcExpRev

        er = llcExpRev(self._llc)
        raw = er.load_raw()
        if isinstance(raw, dict):
            existing_records = raw.get('records', [])
            existing_log     = raw.get('LogHistory', [])
        else:
            existing_records = raw if isinstance(raw, list) else []
            existing_log     = []

        # Append new records
        all_records = existing_records + new_records

        # Build LogHistory entry
        log_entry = {
            'ts':                         ts,
            'source':                     f'BankStmts/{csv_name}',
            'rows_in_csv':                preview.stats.total,
            'rows_new':                   len(new_records),
            'rows_duplicate':             preview.stats.duplicate,
            'rows_amount_collision':      preview.stats.amount_collision,
            'rows_auto_classified':       preview.stats.auto,
            'rows_flagged_review':        preview.stats.review,
            'rows_need_req_doc':          preview.stats.need_req_doc,
            'bankagent_version':          '0.2',
            'ingestagent_version':        '0.1',
            'notes':                      '',
        }
        all_log = existing_log + [log_entry]

        # Write full struct
        import os
        fn = er.FN()
        with open(fn, 'w', encoding='utf-8') as f:
            json.dump({'records': all_records, 'LogHistory': all_log}, f, indent=2)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _make_passthrough(raw: dict, flag: str) -> ClassifiedRow:
        """Minimal ClassifiedRow for a row that is pre-flagged before classify()."""
        from ledger.bankAgent.IngestAgent import _make_tID
        tID = raw.get('tID') or _make_tID(raw['dt'], raw['amt'], raw.get('aType', 'Debit'))
        return ClassifiedRow(
            dt=raw['dt'], amt=float(raw['amt']),
            aType=raw.get('aType', ''), desc=raw.get('desc', ''),
            refDoc=raw.get('refDoc', raw.get('desc', '')),
            tID=tID, txn_type='DUPLICATE',
            acct='', acctSub='', Ledger='', propNm='',
            confidence='', vendor_key='',
            flag=flag, refDB='',
        )

    @staticmethod
    def _count_confidence(stats: PreviewStats, cr: ClassifiedRow) -> None:
        if cr.confidence == 'auto':    stats.auto    += 1
        elif cr.confidence == 'review': stats.review += 1
        elif cr.confidence == 'flagged': stats.flagged += 1
