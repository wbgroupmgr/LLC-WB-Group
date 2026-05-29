'''
Timestampe of last change : 2026.04.11.09.28
'''

import math
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


    def load(self) -> List[Dict[str, Any]]:
        return self.toAcctType(self._as_list(self.wk.load()))

    def load_object(self) -> List[Dict[str, Any]]:
        return self.toAcctType(self._as_list(self.wk.o.load()))

    def _delFld(self, tDict, fldList):
        for f in fldList:
            if f in tDict : 
                del tDict[f]
        return tDict

    @staticmethod
    def _clean_value(v: Any) -> Any:
        '''Replace float NaN/Inf (from COA pandas lookups) with None so JSON stays valid.'''
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    def savePayload(self, payload):
        # acctType is computed by toAcctType() before every save and is now persisted.
        # acctMajor / acctMinor remain transient (COA lookup artefacts) and are stripped.
        colDel = ['acctMajor', 'acctMinor']
        for tDict in payload:
            self._delFld(tDict, colDel)
            # Sanitise NaN / Inf that COA pandas lookups can inject (e.g. acctSub)
            for k in list(tDict.keys()):
                tDict[k] = self._clean_value(tDict[k])
            # Normalise Ledger: null/empty/'nan'/float-nan all → string 'nan'
            # so toGL() mask works uniformly and the UI displays 'nan' not blank.
            if 'Ledger' in tDict:
                lv = tDict['Ledger']
                if lv is None or (isinstance(lv, str) and lv.strip().lower() in ('nan', '')):
                    tDict['Ledger'] = 'nan'
            # Coerce amt to float so getBal/getBalSh never receive a string
            if 'amt' in tDict:
                try:
                    tDict['amt'] = float(tDict['amt'] or 0)
                except (TypeError, ValueError):
                    tDict['amt'] = 0.0

        # Write to real (committed) DB — the authoritative source of truth.
        # Immutable stmt objects (stmtGL, stmtBS, stmtIS …) read from here,
        # so this write must succeed for GL/Audit to see the change on Refresh.
        import json as _json
        real_fn = self.wk.o.FN()
        with open(real_fn, 'w') as _fio:
            _json.dump(payload, _fio, indent=4)

        # Mirror to working (temp) file so the editor view stays consistent.
        self.wk.save(payload)
        return

    def save(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Strip acctType from every record so toAcctType() always runs a fresh
        # COA lookup for all rows — never preserves a potentially stale value.
        raw = self._as_list(data)
        for row in raw:
            row.pop('acctType', None)
        payload = self.toAcctType(raw)
        self.savePayload(payload)
        return payload

    def save_object(self, data=None) -> List[Dict[str, Any]]:
        # sync temp → real; payload arg is kept for backward compatibility
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