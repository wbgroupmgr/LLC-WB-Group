'''
ledger.ledgerGeneral — backwards-compatibility shim (v0.2.2.6).

The canonical ``ledgerGeneral`` class now lives in
``ledger/stmtGeneralLedger.py`` alongside ``stmtGeneralLedger``, which
consolidates the General Ledger building service and its constructed
snapshot into a single module.

This shim preserves existing imports so legacy call sites keep working:

    from ledger.ledgerGeneral import ledgerGeneral, toTid, toKAmt, toIDDict

All symbols re-export from ``ledger.stmtGeneralLedger``.
'''

from ledger.stmtGeneralLedger import (
    ledgerGeneral,
    toTid,
    toKAmt,
    toIDDict,
)

__all__ = ['ledgerGeneral', 'toTid', 'toKAmt', 'toIDDict']
