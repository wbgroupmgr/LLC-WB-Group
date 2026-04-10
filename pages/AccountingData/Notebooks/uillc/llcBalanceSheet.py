from typing import Any, Dict, List


class llcBalanceSheet:
    def __init__(self, wk):
        self.wk = wk
        self.eSession = None

    def bind_session(self, eSession) -> None:
        self.eSession = eSession

    def object_name(self) -> str:
        return getattr(getattr(self.wk, "o", None), "oID", "llcBalanceSheet")

    def _as_list(self, data: Any) -> List[Dict[str, Any]]:
        return data if isinstance(data, list) else []

    def load(self) -> List[Dict[str, Any]]:
        return self._as_list(self.wk.load())

    def load_object(self) -> List[Dict[str, Any]]:
        return self._as_list(self.wk.o.load())

    def save(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        payload = self._as_list(data)
        self.wk.save(payload)
        return payload

    def save_object(self, data=None) -> List[Dict[str, Any]]:
        payload = self._as_list(self.load() if data is None else data)
        self.wk.o.save(payload)
        return payload

    def reset_from_object(self) -> List[Dict[str, Any]]:
        payload = self.load_object()
        self.wk.save(payload)
        return payload

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def meta(self) -> Dict[str, Any]:
        return {
            "objectName": self.object_name(),
            "workingFile": self.wk.FN(),
            "objectFile": self.wk.o.FN(),
        }

    def stats(self) -> Dict[str, Any]:
        return {
            "objectName": self.object_name(),
            "status": "View Under Construction",
            "workingFile": self.wk.FN(),
            "objectFile": self.wk.o.FN(),
        }
