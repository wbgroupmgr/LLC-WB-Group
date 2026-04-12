'''
Timestampe of last change : 2026.04.11.09.28
'''

from typing import Any, Dict, List
from ledger.llcCOA import ChartOfAccounts as llcCOA    



class llcRecordsView:
    def __init__(self, wk):
        self.wk = wk
        self.eSession = None

    def bind_session(self, eSession) -> None:
        self.eSession = eSession

    def object_name(self) -> str:
        return getattr(getattr(self.wk, "o", None), "oID", self.__class__.__name__)

    def _as_list(self, data: Any) -> List[Dict[str, Any]]:
        return data if isinstance(data, list) else []

    def _to_float(self, value: Any) -> float:
        if value is None or value == "":
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        try:
            text = str(value).replace(",", "").replace("$", "").strip()
            return float(text)
        except Exception:
            return 0.0

    def _signed_amt(self, row: Dict[str, Any]) -> float:
        amt = self._to_float(row.get("amt", 0))
        a_type = str(row.get("aType", "")).strip().lower()

        if a_type in ("credit", "cr", "c"):
            return -amt
        return amt

    def toAcctType(self, transList: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Use COA to map transaction info into acctType
        coa = llcCOA(self.wk.llc)
        result = []
        for tDict in transList:
            result.append(coa.toAcctType(tDict))
        return result

    def toAcctTypeOLD(self, content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for row in content:
            item = dict(row)
            acct_type = item.get("acctType")

            if acct_type:
                result.append(item)
                continue

            text = " ".join(
                str(item.get(k, ""))
                for k in [
                    "acct", "account", "type", "desc", "name",
                    "category", "notes", "Ledger",
                    "acctMajor", "acctMinor", "acctSub"
                ]
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

    def load(self) -> List[Dict[str, Any]]:
        return self.toAcctType(self._as_list(self.wk.load()))

    def load_object(self) -> List[Dict[str, Any]]:
        return self.toAcctType(self._as_list(self.wk.o.load()))

    def _delFld(self, tDict, fldList):
        for f in fldList:
            if f in tDict : 
                del tDict[f]
        return tDict

    def savePayload(self, payload):
        # Delete derived fields from DB store
        colDel = ['acctType', 'acctMajor', 'acctMinor']
        for tDict in payload:
            self._delFld(tDict, colDel)
            
        self.wk.save(payload)
        return
        
    def save(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        payload = self.toAcctType(self._as_list(data))
        self.savePayload(payload)
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
        acct_counts: Dict[str, int] = {}
        balance = 0.0

        for row in rows:
            acct = row.get("acctType", "Unknown")
            acct_counts[acct] = acct_counts.get(acct, 0) + 1
            balance += self._signed_amt(row)

        return {
            "Transactions": len(rows),
            "AccountTypes": len(acct_counts),
            "Balance": round(balance, 2),
            "ByAcctType": acct_counts,
        }