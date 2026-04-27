'''
tests/ — reset-and-simplify verification service.

Each test module under this package is runnable both as a script and as a
pytest-style file.  Currently shipped tests:

    testBalSh.py    — llcAssets + llcPayables + llcReceivables source →
                      GL (Asset/Liability/Equity) → stmtBalanceSheet view.
                      All three aggregations must be bit-identical on
                      (acctMajor, acct, aType).amt.sum().

    testIncStmt.py  — llcExpRev source → GL (Income/Expense) →
                      stmtIncomeStmt view.  Same three-way equality check.

The tests verify the GL-as-single-source-of-truth invariant introduced
when stmtBalanceSheet / stmtIncomeStmt were switched to pull from
stmtGeneralLedger (Tasks #32 / #33).
'''
