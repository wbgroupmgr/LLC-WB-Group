from typing import Any, Dict, List

from uillc.llcAssets import llcAssets


class llcExpRev:
    def __init__(self, wk):
        self.wk = wk
        self.eSession = None

    def bind_session(self, eSession) -> None:
        self.eSession = eSession

    def object_name(self) -> str:
        return getattr(getattr(self.wk, "o", None), "oID", "llcExpRev")

    def _as_list(self, data: Any) -> List[Dict[str, Any]]:
        return data if isinstance(data, list) else []

    def _assets_helper(self) -> llcAssets:
        if self.eSession is not None:
            assets_wk = self.eSession.get("llcAssets") or self.eSession.get("llcAsset")
            if assets_wk is not None:
                helper = llcAssets(assets_wk)
                helper.bind_session(self.eSession)
                return helper

        helper = llcAssets(self.wk)
        helper.bind_session(self.eSession)
        return helper

    def load(self) -> List[Dict[str, Any]]:
        rows = self._as_list(self.wk.load())
        return self._assets_helper().toAcctType(rows)

    def load_object(self) -> List[Dict[str, Any]]:
        rows = self._as_list(self.wk.o.load())
        return self._assets_helper().toAcctType(rows)

    def save(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        payload = self._assets_helper().toAcctType(self._as_list(data))
        self.wk.save(payload)
        return payload

    def save_object(self, data=None) -> List[Dict[str, Any]]:
        payload = self._assets_helper().toAcctType(self._as_list(self.load() if data is None else data))
        self.wk.o.save(payload)
        return payload

    def reset_from_object(self) -> List[Dict[str, Any]]:
        payload = self.load_object()
        self.wk.save(payload)
        return payload

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def list_records(self) -> List[Dict[str, Any]]:
        return self.load()

    def meta(self) -> Dict[str, Any]:
        return {
            "objectName": self.object_name(),
            "workingFile": self.wk.FN(),
            "objectFile": self.wk.o.FN(),
        }

    def stats(self) -> Dict[str, Any]:
        rows = self.load()
        acct_counts = {}
        for row in rows:
            acct = row.get("acctType", "Unknown")
            acct_counts[acct] = acct_counts.get(acct, 0) + 1

        return {
            "objectName": self.object_name(),
            "Transactions": len(rows),
            "AccountTypes": len(acct_counts),
            "ByAcctType": acct_counts,
            "workingFile": self.wk.FN(),
            "objectFile": self.wk.o.FN(),
        }
