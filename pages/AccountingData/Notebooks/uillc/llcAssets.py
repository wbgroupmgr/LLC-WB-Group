from typing import Any, Dict, List


class llcAssets:
    def __init__(self, wk):
        self.wk = wk
        self.eSession = None

    def bind_session(self, eSession) -> None:
        self.eSession = eSession

    def object_name(self) -> str:
        return getattr(getattr(self.wk, "o", None), "oID", "llcAssets")

    def _as_list(self, data: Any) -> List[Dict[str, Any]]:
        return data if isinstance(data, list) else []

    def load(self) -> List[Dict[str, Any]]:
        return self.toAcctType(self._as_list(self.wk.load()))

    def load_object(self) -> List[Dict[str, Any]]:
        return self.toAcctType(self._as_list(self.wk.o.load()))

    def save(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        payload = self.toAcctType(self._as_list(data))
        self.wk.save(payload)
        return payload

    def save_object(self, data=None) -> List[Dict[str, Any]]:
        payload = self.toAcctType(self._as_list(self.load() if data is None else data))
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

    def stats(self, content=None) -> Dict[str, Any]:
        rows = self.load() if content is None else self.toAcctType(self._as_list(content))
        acct_counts = {}
        for row in rows:
            acct = row.get("acctType", "Unknown")
            acct_counts[acct] = acct_counts.get(acct, 0) + 1

        return {
            "Transactions": len(rows),
            "AccountTypes": len(acct_counts),
            "ByAcctType": acct_counts,
        }

    def toAcctType(self, content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for row in content:
            item = dict(row)
            acct_type = item.get("acctType")
            if acct_type:
                result.append(item)
                continue

            text = " ".join(
                str(item.get(k, ""))
                for k in ["acct", "account", "type", "desc", "name", "category", "notes"]
            ).lower()

            if any(k in text for k in ["rent", "lease"]):
                acct_type = "Rental Income"
            elif any(k in text for k in ["repair", "maintenance", "fix"]):
                acct_type = "Repairs & Maintenance"
            elif any(k in text for k in ["tax", "property tax"]):
                acct_type = "Taxes"
            elif any(k in text for k in ["insurance"]):
                acct_type = "Insurance"
            elif any(k in text for k in ["mortgage", "loan", "interest"]):
                acct_type = "Financing"
            elif any(k in text for k in ["utility", "electric", "water", "gas"]):
                acct_type = "Utilities"
            elif any(k in text for k in ["asset", "equipment", "vehicle", "building"]):
                acct_type = "Asset"
            elif any(k in text for k in ["income", "revenue", "sale"]):
                acct_type = "Income"
            elif any(k in text for k in ["expense", "cost", "fee"]):
                acct_type = "Expense"
            else:
                acct_type = "Other"

            item["acctType"] = acct_type
            result.append(item)

        return result