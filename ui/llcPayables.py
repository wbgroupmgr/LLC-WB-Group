'''
llcPayables — Accounts Payable transaction records.

Parallels llcAssets / llcExpRev.  Each record represents an amount the
LLC owes (a liability) until it is paid.  Storage, load / save semantics,
and COA mapping all come from llcRecordsView; this subclass only names
the object type so that llcMgmt and llcReportEngine can register it.

Timestamp of last change: 2026.04.16
'''

from ui.llcRecordsView import llcRecordsView


class llcPayables(llcRecordsView):
    pass
