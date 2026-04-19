'''
llcReceivables — Accounts Receivable transaction records.

Parallels llcAssets / llcExpRev.  Each record represents an amount owed
TO the LLC (an asset) until it is collected.  Storage, load / save
semantics, and COA mapping all come from llcRecordsView; this subclass
only names the object type so that llcMgmt and llcReportEngine can
register it.

Timestamp of last change: 2026.04.16
'''

from uillc.llcRecordsView import llcRecordsView


class llcReceivables(llcRecordsView):
    pass
