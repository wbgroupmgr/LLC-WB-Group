"""
ledger/bankAgent/bkCIPGuard.py — IRC §263(a) InConstruction hard override
Cannot be bypassed from the UI; operator must change llcAssets to InService first.
"""
from __future__ import annotations


_CIP_ACCT = 'Acct.Fixed.Tangible.InConstruction'


class BkCIPGuard:
    """
    Detects properties with active InConstruction records and overrides any
    Acct.Exp.* classification to Acct.Fixed.Tangible.InConstruction.
    """

    def __init__(self, llc=None):
        self._cip_props: set[str] = self._load_cip_props(llc)

    def _load_cip_props(self, llc) -> set[str]:
        """Return set of propNm values that have any InConstruction record in llcPayables."""
        if llc is None:
            return set()
        try:
            from ledger.llcPayables import llcPayables
            recs = llcPayables(llc).load()
            return {
                r['propNm']
                for r in recs
                if r.get('acct') == _CIP_ACCT and r.get('propNm')
            }
        except Exception:
            return set()

    def check(self, prop_nm: str, proposed_acct: str) -> tuple[str, bool]:
        """
        If property is InConstruction and proposed_acct is Acct.Exp.*,
        redirect to Acct.Fixed.Tangible.InConstruction.
        Returns (final_acct, cip_violated).
        """
        if prop_nm in self._cip_props and proposed_acct.startswith('Acct.Exp.'):
            return _CIP_ACCT, True
        return proposed_acct, False

    @property
    def cip_properties(self) -> set[str]:
        return frozenset(self._cip_props)
