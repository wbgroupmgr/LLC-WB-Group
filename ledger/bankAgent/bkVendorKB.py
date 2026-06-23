"""
ledger/bankAgent/bkVendorKB.py — Vendor Knowledge Base
First-match regex lookup: desc → (acct, acctSub, txn_type, confidence)
"""
import json
import re
from pathlib import Path

_KB_PATH = Path(__file__).parent / 'vendor_rules.json'


class BkVendorKB:
    """Loads, queries, and persists vendor classification rules."""

    def __init__(self, kb_path=None):
        self._path = Path(kb_path) if kb_path else _KB_PATH
        self._rules = self._load()

    def _load(self):
        if self._path.exists():
            with open(self._path, encoding='utf-8') as f:
                return json.load(f)
        return []

    def lookup(self, desc: str):
        """Return (acct, acctSub, txn_type, confidence) or None on no match."""
        dl = desc.lower()
        for rule in self._rules:
            try:
                if re.search(rule['pattern'], dl):
                    return (rule['acct'], rule['acctSub'],
                            rule['txn_type'], rule['confidence'])
            except re.error:
                if rule['pattern'] in dl:
                    return (rule['acct'], rule['acctSub'],
                            rule['txn_type'], rule['confidence'])
        return None

    def matched_pattern(self, desc: str) -> str:
        """Return the matched pattern string, or '' on no match."""
        dl = desc.lower()
        for rule in self._rules:
            try:
                if re.search(rule['pattern'], dl):
                    return rule['pattern']
            except re.error:
                if rule['pattern'] in dl:
                    return rule['pattern']
        return ''

    def learn(self, vendor_key: str, acct: str, acct_sub: str,
              txn_type: str = 'ROUTINE_EXPENSE'):
        """Raise existing rule's confidence to 'auto' or insert a new auto rule."""
        kl = vendor_key.lower()
        for rule in self._rules:
            if rule['pattern'] == kl:
                rule['acct'] = acct
                rule['acctSub'] = acct_sub
                rule['txn_type'] = txn_type
                rule['confidence'] = 'auto'
                self.save()
                return
        # Prepend new rule so it takes precedence over generic patterns
        new_rule = {
            'pattern': kl, 'acct': acct, 'acctSub': acct_sub,
            'txn_type': txn_type, 'confidence': 'auto',
        }
        self._rules.insert(0, new_rule)
        self.save()

    def save(self):
        with open(self._path, 'w', encoding='utf-8') as f:
            json.dump(self._rules, f, indent=2)

    def rules(self):
        return list(self._rules)
