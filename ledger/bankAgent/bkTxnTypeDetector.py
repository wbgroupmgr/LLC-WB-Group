"""
ledger/bankAgent/bkTxnTypeDetector.py — Tier 2 special transaction detection
Overrides vendor KB for transactions that always require operator review.
"""
import re

_WIRE_PATTERNS = [r'wt fed#', r'withdrawal made in a branch']
_RETURN_PATTERNS = [r'purchase return']
_ACH_VERIFY_PATTERNS = [r'acctverify']

# Transactions above this amount are always SPECIAL_WIRE regardless of desc
_LARGE_AMT_THRESHOLD = 50_000.0


class BkTxnTypeDetector:
    """
    Detects Tier 2 special transaction types. Checked BEFORE vendor KB.
    Returns (txn_type, confidence, suggested_acct) or None.
    """

    def __init__(self, member_names: list = None):
        # Each name lowercased for substring matching against 'ZELLE FROM ...'
        self._member_names = [n.lower() for n in (member_names or [])]

    def detect(self, desc: str, amt: float):
        """
        Return (txn_type, confidence, suggested_acct) if Tier 2 rule fires,
        else None.  Tier 2 rules are evaluated in priority order.
        """
        dl = desc.lower()

        # Large-amount wire or branch withdrawal — always flagged
        if abs(amt) >= _LARGE_AMT_THRESHOLD:
            return ('SPECIAL_WIRE', 'flagged', 'Acct.Fixed.Tangible.InService')
        if any(re.search(p, dl) for p in _WIRE_PATTERNS):
            return ('SPECIAL_WIRE', 'flagged', 'Acct.Fixed.Tangible.InService')

        # Zelle from a known LLC member — may be capital contribution
        if 'zelle from' in dl:
            for name in self._member_names:
                if name in dl:
                    return ('MEMBER_INVEST', 'flagged',
                            'Acct.Equity.Owner.Capital.Funds')

        # Purchase return — needs propNm cross-check (CROSS_PROP_REFUND handled by BkDuplicateDetector)
        if any(re.search(p, dl) for p in _RETURN_PATTERNS):
            return ('RETURN_PAIR', 'review', 'Acct.Exp.Other')

        # ACH micro-deposit verification — auto, near-zero net impact
        if any(re.search(p, dl) for p in _ACH_VERIFY_PATTERNS):
            return ('ACH_VERIFY', 'auto', 'Acct.Cash.Bank')

        return None
