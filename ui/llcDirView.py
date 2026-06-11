'''llcDirView — base class for directory views (Owners, Customers, Milestones).

These are non-transaction records: no COA lookup, no acctType mapping,
no double-entry. load/save go straight to the JSON file.
'''

import json as _json
from typing import Any, Dict, List

from ui.llcRecordsView import llcRecordsView


class llcDirView(llcRecordsView):

    def load(self) -> List[Dict[str, Any]]:
        return self._as_list(self.wk.load())

    def load_object(self) -> List[Dict[str, Any]]:
        return self._as_list(self.wk.o.load())

    def save(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = self._as_list(data)
        real_fn = self.wk.o.FN()
        with open(real_fn, 'w') as fio:
            _json.dump(rows, fio, indent=4)
        self.wk.save(rows)
        return rows

    def stats(self, content=None) -> Dict[str, Any]:
        rows = self.load() if content is None else self._as_list(content)
        return {"Records": len(rows)}
