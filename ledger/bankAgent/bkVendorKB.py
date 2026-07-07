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
        m = self.lookup_indexed(desc)
        if m is None:
            return None
        _idx, rule = m
        return (rule['acct'], rule['acctSub'], rule['txn_type'], rule['confidence'])

    def lookup_indexed(self, desc: str):
        """Return (index, rule) of the first matching rule, or None. Index is the
        0-based position in the ordered rule list — the operator-facing pID is index+1."""
        import re as _re
        # Collapse runs of whitespace so "NICOLA  ROJAS" matches pattern "nicola rojas"
        dl = _re.sub(r'\s+', ' ', desc.lower().strip())
        for i, rule in enumerate(self._rules):
            try:
                if re.search(rule['pattern'], dl):
                    return (i, rule)
            except re.error:
                if rule['pattern'] in dl:
                    return (i, rule)
        return None

    def matched_pattern(self, desc: str) -> str:
        """Return the matched pattern string, or '' on no match."""
        import re as _re
        dl = _re.sub(r'\s+', ' ', desc.lower().strip())
        for rule in self._rules:
            try:
                if re.search(rule['pattern'], dl):
                    return rule['pattern']
            except re.error:
                if rule['pattern'] in dl:
                    return rule['pattern']
        return ''

    def learn(self, vendor_key: str, acct: str, acct_sub: str,
              txn_type: str = 'ROUTINE_EXPENSE', propNm: str = ''):
        """Raise existing rule's confidence to 'auto' or insert a new auto rule."""
        kl = vendor_key.lower()
        for rule in self._rules:
            if rule['pattern'] == kl:
                rule['acct'] = acct
                rule['acctSub'] = acct_sub
                rule['txn_type'] = txn_type
                rule['confidence'] = 'auto'
                if propNm:
                    rule['propNm'] = propNm
                self.save()
                return
        # Prepend new rule so it takes precedence over generic patterns
        new_rule = {
            'pattern': kl, 'acct': acct, 'acctSub': acct_sub,
            'txn_type': txn_type, 'confidence': 'auto', 'propNm': propNm,
        }
        self._rules.insert(0, new_rule)
        self.save()

    def save(self):
        with open(self._path, 'w', encoding='utf-8') as f:
            json.dump(self._rules, f, indent=2)

    def rules(self):
        return list(self._rules)

    _FIELDS = ('pattern', 'acct', 'acctSub', 'txn_type', 'confidence', 'propNm')

    def set_rules(self, rules: list) -> list:
        """Replace the whole rule set (operator KB-edit Save). Validates each rule
        has a non-empty pattern + acct; normalizes to the 6 KB fields and saves.

        propNm (issue #55 — every pattern should be associated with a specific
        propNm, either a property id or the "LLC" entity-level sentinel) is
        NOT hard-required here: existing rules predate this field, and a
        replace-all save must not silently delete a working classification
        rule just because the operator hasn't assigned it a property yet.
        Missing propNm is instead surfaced in the KB Rules UI (a visible
        "needs property" state) so it gets filled in deliberately.
        """
        clean = []
        for r in rules:
            pattern = (r.get('pattern') or '').strip()
            acct    = (r.get('acct') or '').strip()
            if not pattern or not acct:
                continue  # skip incomplete rows
            clean.append({
                'pattern':    pattern,
                'acct':       acct,
                'acctSub':    (r.get('acctSub') or '').strip(),
                'txn_type':   (r.get('txn_type') or 'ROUTINE_EXPENSE').strip(),
                'confidence': (r.get('confidence') or 'review').strip(),
                'propNm':     (r.get('propNm') or '').strip(),
            })
        self._rules = clean
        self.save()
        return list(self._rules)
