"""
ledger/bankAgent/IngestAgent.py — Per-record bank transaction classifier
No knowledge of phases, pipeline, or file writes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ledger.bankAgent.bkVendorKB import BkVendorKB
from ledger.bankAgent.bkTxnTypeDetector import BkTxnTypeDetector


@dataclass
class ClassifiedRow:
    # From raw bank row
    dt: str
    amt: float
    aType: str       # Debit | Credit — from raw CSV (cash-movement direction)
    desc: str
    refDoc: str
    tID: str         # "{dt}_D{amt:.2f}" or "{dt}_C{amt:.2f}" — dedup key

    # From IngestAgent (BkVendorKB + BkTxnTypeDetector)
    txn_type: str    # ROUTINE_EXPENSE | RENT_INCOME | SPECIAL_WIRE | MEMBER_INVEST | RETURN_PAIR | ACH_VERIFY | UNKNOWN
    acct: str        # Primary COA account (e.g. Acct.Exp.Repair, Acct.Rev.Rent)
    acctSub: str     # Sub-category detail
    Ledger: str      # Contra account — always Acct.Cash.Bank for bank-sourced rows
    propNm: str      # Set from context; operator may override
    confidence: str  # auto | review | flagged
    vendor_key: str  # Matched KB pattern (or normalized desc for no-match)

    # Set by BankAgent after dedup + CIP check
    flag: str = ''
    refDB: str = ''
    pID: int | None = None   # matched KB rule pID (index+1), or None if no KB match


def _make_tID(dt: str, amt: float, a_type: str) -> str:
    dc = 'C' if str(a_type).strip().lower() in ('credit', 'cr', 'c') else 'D'
    return f"{dt}_{dc}{abs(float(amt)):.2f}"


def _ledger_for(acct: str) -> str:
    """All bank-sourced transactions clear through Acct.Cash.Bank."""
    return 'Acct.Cash.Bank'


def _normalize_vendor_key(desc: str) -> str:
    return desc.strip().lower()[:50]


class IngestAgent:
    """
    Classifies a single bank transaction row.
    Instantiate once per session; call classify() per row.
    """

    def __init__(self, llc=None, kb_path=None):
        self._kb = BkVendorKB(kb_path)
        self._detector = BkTxnTypeDetector(self._load_member_names(llc))

    # ── member-name loading ───────────────────────────────────────────────────

    def _load_member_names(self, llc) -> list:
        if llc is None:
            return []
        try:
            from ledger import setup_paths
            accts_dir = Path(setup_paths.ACCTS_DIR)
            llc_name = getattr(llc, 'llcName', 'WBGroupLLC')
            owners_path = accts_dir / f'llcOwners_{llc_name}.json'
            if not owners_path.exists():
                return []
            with open(owners_path, encoding='utf-8') as f:
                owners = json.load(f)
            return [nm for o in owners for nm in o.get('nm', [])]
        except Exception:
            return []

    # ── classification ────────────────────────────────────────────────────────

    def classify(self, raw_row: dict, context: dict = None) -> ClassifiedRow:
        """
        Classify one raw bank row.  raw_row keys: dt, amt, aType, desc, refDoc.
        context: {'propNm': str}
        """
        context = context or {}
        propNm = context.get('propNm', '')

        dt      = raw_row['dt']
        amt     = float(raw_row['amt'])
        a_type  = str(raw_row.get('aType', 'Debit')).strip()
        desc    = str(raw_row.get('desc', ''))
        ref_doc = str(raw_row.get('refDoc', desc))
        tID     = raw_row.get('tID') or _make_tID(dt, amt, a_type)

        # Priority: P1 vendor KB (operator-curated) BEFORE P2 Tier-2 heuristics,
        # so an explicit rule (e.g. "zelle from nicola rojas" → RENT_INCOME) wins
        # over a generic detector guess (e.g. ZELLE FROM member → MEMBER_INVEST).
        pID = None
        matched = self._kb.lookup_indexed(desc)
        if matched:
            idx, rule = matched
            acct, acct_sub = rule['acct'], rule['acctSub']
            txn_type, confidence = rule['txn_type'], rule['confidence']
            vendor_key = rule['pattern']
            pID = idx + 1
            # A rule's own propNm (issue #55) is vendor-specific knowledge and
            # takes precedence over the batch's propNm_default — e.g. a bank
            # fee is always "LLC" regardless of which property's CSV it
            # appeared on. Rules that predate this field (propNm == '') fall
            # through to the batch default, unchanged from prior behavior.
            rule_propNm = (rule.get('propNm') or '').strip()
            if rule_propNm:
                propNm = rule_propNm
        else:
            # Tier 2: special transaction types (only when no KB rule matched)
            tier2 = self._detector.detect(desc, amt)
            if tier2:
                txn_type, confidence, acct = tier2
                acct_sub   = txn_type.replace('_', ' ').title()
                vendor_key = _normalize_vendor_key(desc)
            else:
                acct       = 'Acct.Exp.Other'
                acct_sub   = 'Unknown'
                txn_type   = 'UNKNOWN'
                confidence = 'review'
                vendor_key = _normalize_vendor_key(desc)

        return ClassifiedRow(
            dt=dt,
            amt=amt,
            aType=a_type,
            desc=desc,
            refDoc=ref_doc,
            tID=tID,
            txn_type=txn_type,
            acct=acct,
            acctSub=acct_sub,
            Ledger=_ledger_for(acct),
            propNm=propNm,
            confidence=confidence,
            vendor_key=vendor_key,
            flag='',
            refDB='',
            pID=pID,
        )

    # ── learning ──────────────────────────────────────────────────────────────

    def learn(self, vendor_key: str, acct: str, acct_sub: str,
              txn_type: str = 'ROUTINE_EXPENSE'):
        """Raise KB confidence to 'auto' for vendor_key and persist."""
        self._kb.learn(vendor_key, acct, acct_sub, txn_type)
