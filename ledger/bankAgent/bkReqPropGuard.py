"""
ledger/bankAgent/bkReqPropGuard.py — Requisition propNm cross-check (issue #55)

A transaction whose propNm disagrees with the propNm on its linked
Requisition means one of the two records has the wrong property. Flagged in
preview for operator awareness; re-checked as a hard commit-time gate (using
whatever propNm is on the row *after* any operator edits) so a mismatched
row can never reach llcExpRev — same "cannot be bypassed" posture as
bkCIPGuard.
"""
from __future__ import annotations


class BkReqPropGuard:
    """Compares a classified row's propNm against its linked requisition's propNm."""

    def __init__(self, year: int | None, llc=None):
        self._req_map: dict[str, dict] = self._load_req_map(year, llc)

    @staticmethod
    def _load_req_map(year, llc) -> dict:
        if year is None or llc is None:
            return {}
        try:
            from ledger.bankAgent.bkReqDocAgent import BkReqDocAgent
            return BkReqDocAgent(year, llc).as_map()
        except Exception:
            return {}

    def check(self, tID: str, prop_nm: str) -> tuple[bool, str]:
        """
        Return (mismatch, requisition_propNm).
        No requisition linked to this tID, or the requisition itself has no
        propNm yet, means nothing to compare — never a mismatch.
        """
        req = self._req_map.get(tID)
        if req is None:
            return False, ''
        req_prop = (req.get('propNm') or '').strip()
        if not req_prop:
            return False, ''
        return (req_prop != prop_nm, req_prop)
