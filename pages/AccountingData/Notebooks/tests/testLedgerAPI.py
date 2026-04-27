'''
tests.testLedgerAPI — unit tests for the Uniform Ledger API (v0.2).

Verifies the API contract declared on ``ledger.ledgerObject`` (v0.2.2.3)
and implemented by ``ledgerDB`` (v0.2.2.4) + ``stmtDB`` (v0.2.2.5):

    load()        → list[dict]
    save(tList)   → None               (stmt* raises InvalidRequestError)
    to_DF()       → pandas.DataFrame
    to_agg(...)   → {'table': DataFrame, 'extraFields': dict}
                    by ∈ {'Trial', 'BalSh', 'IncStmt',
                          'custom:[cols]', list[str], None}
    to_IRS()      → list[dict]         (default — one dict per entity)
                    stmt* overrides    → dict[formNm → dict[logicalKey → value]]

Primary invariants (all must hold):

    T1. Every class returns a pandas.DataFrame from ``to_DF()``.
    T2. Every class returns the 2-key dict ``{'table', 'extraFields'}`` from
        ``to_agg()``.
    T3. ``to_agg(by='Trial')`` groups strictly by ``acctType``.
    T4. ``to_agg(by='BalSh')`` contains only A/L/E rows post-filter.
    T5. ``to_agg(by='IncStmt')`` contains only Income/Expense rows.
    T6. ``to_agg(by='custom:[acct]')`` groups by exactly ``['acct']``.
    T7. ``to_agg(by=['acct','aType'])`` accepts a raw list.
    T8. ``to_IRS()`` on an entity DB (llcOwners) returns a non-empty
        ``list[dict]`` with entity-ID keys.
    T9. ``to_IRS()`` on a stmt* class returns a ``dict[formNm → dict]``.
    T10. ``stmt*.save()`` raises ``InvalidRequestError`` with the exact
         message ``'InvalidRequest; ImmutableObject'``.

Usage
-----
    # from the Notebooks/ directory
    python -m tests.testLedgerAPI

Exits 0 when all 10 invariants pass, 1 otherwise.
'''

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

import pandas as pd


# Allow direct `python tests/testLedgerAPI.py` invocation.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── Test registry / runner ──────────────────────────────────────────────────

_TESTS: List[Tuple[str, Callable[..., bool]]] = []


def _register(name: str):
    '''Decorator: add a test to the registry.'''
    def _deco(fn):
        _TESTS.append((name, fn))
        return fn
    return _deco


def _build_llc():
    from ledger.LLC import LLC
    return LLC('WBGroupLLC')


# ── T1 ──────────────────────────────────────────────────────────────────────

@_register("T1 — to_DF() returns a pandas.DataFrame on every class")
def t1_to_df_returns_dataframe(llc) -> bool:
    from ledger.llcAssets       import llcAssets
    from ledger.llcExpRev       import llcExpRev
    from ledger.llcPayables     import llcPayables
    from ledger.llcReceivables  import llcReceivables
    from ledger.llcOwners       import llcOwners
    from ledger.stmtBalanceSheet import stmtBalanceSheet
    from ledger.stmtIncomeStmt   import stmtIncomeStmt
    from ledger.stmtGeneralLedger import stmtGeneralLedger

    classes = [llcAssets, llcExpRev, llcPayables, llcReceivables, llcOwners,
               stmtBalanceSheet, stmtIncomeStmt, stmtGeneralLedger]
    for Cls in classes:
        obj = Cls(llc)
        df = obj.to_DF()
        assert isinstance(df, pd.DataFrame), f"{Cls.__name__}.to_DF() → {type(df)}"
    return True


# ── T2 ──────────────────────────────────────────────────────────────────────

@_register("T2 — to_agg() returns {'table','extraFields'} dict")
def t2_to_agg_contract(llc) -> bool:
    from ledger.llcAssets        import llcAssets
    from ledger.stmtBalanceSheet import stmtBalanceSheet
    for Cls in (llcAssets, stmtBalanceSheet):
        obj = Cls(llc)
        r = obj.to_agg()
        assert isinstance(r, dict), f"{Cls.__name__}.to_agg() → {type(r)}"
        assert set(r.keys()) == {'table', 'extraFields'}, f"{Cls.__name__}: keys={list(r.keys())}"
        assert isinstance(r['table'], pd.DataFrame), f"{Cls.__name__}.to_agg()['table'] → {type(r['table'])}"
        assert isinstance(r['extraFields'], dict), f"{Cls.__name__}.to_agg()['extraFields'] → {type(r['extraFields'])}"
    return True


# ── T3 ──────────────────────────────────────────────────────────────────────

@_register("T3 — by='Trial' groups strictly by acctType")
def t3_trial_groupby(llc) -> bool:
    from ledger.llcExpRev import llcExpRev
    obj = llcExpRev(llc)
    tbl = obj.to_agg(by='Trial')['table']
    assert 'acctType' in tbl.columns, f"Trial table missing acctType col; got {list(tbl.columns)}"
    # No duplicate acctType values → implies groupby collapsed correctly
    assert tbl['acctType'].is_unique, f"Trial acctType non-unique: {tbl['acctType'].tolist()}"
    return True


# ── T4 ──────────────────────────────────────────────────────────────────────

@_register("T4 — by='BalSh' contains only Asset/Liability/Equity rows")
def t4_balsh_filter(llc) -> bool:
    from ledger.llcAssets import llcAssets
    obj = llcAssets(llc)
    tbl = obj.to_agg(by='BalSh')['table']
    if tbl.empty:
        return True   # vacuously OK
    actual = set(tbl['acctType'].unique())
    allowed = {'Asset', 'Liability', 'Equity'}
    assert actual.issubset(allowed), f"BalSh contains non-BS acctTypes: {actual - allowed}"
    return True


# ── T5 ──────────────────────────────────────────────────────────────────────

@_register("T5 — by='IncStmt' contains only Income/Expense rows")
def t5_incstmt_filter(llc) -> bool:
    from ledger.llcExpRev import llcExpRev
    obj = llcExpRev(llc)
    tbl = obj.to_agg(by='IncStmt')['table']
    if tbl.empty:
        return True
    actual = set(tbl['acctType'].unique())
    allowed = {'Income', 'Expense'}
    assert actual.issubset(allowed), f"IncStmt contains non-IS acctTypes: {actual - allowed}"
    return True


# ── T6 ──────────────────────────────────────────────────────────────────────

@_register("T6 — by='custom:[acct]' groups by the single column ['acct']")
def t6_custom_by(llc) -> bool:
    from ledger.llcExpRev import llcExpRev
    obj = llcExpRev(llc)
    tbl = obj.to_agg(by='custom:[acct]')['table']
    assert 'acct' in tbl.columns, f"custom:[acct] missing acct col; got {list(tbl.columns)}"
    # ACCT should be unique per row (groupby collapsed)
    assert tbl['acct'].is_unique, f"custom:[acct] rows not collapsed: {tbl['acct'].tolist()}"
    return True


# ── T7 ──────────────────────────────────────────────────────────────────────

@_register("T7 — by=['acct','aType'] (raw list) is accepted")
def t7_list_by(llc) -> bool:
    from ledger.llcExpRev import llcExpRev
    obj = llcExpRev(llc)
    tbl = obj.to_agg(by=['acct', 'aType'])['table']
    assert 'acct'  in tbl.columns
    assert 'aType' in tbl.columns
    # (acct, aType) rows should be unique
    combo = tbl[['acct', 'aType']].drop_duplicates()
    assert len(combo) == len(tbl), "list-by groupby did not collapse (acct,aType)"
    return True


# ── T8 ──────────────────────────────────────────────────────────────────────

@_register("T8 — to_IRS() on llcOwners returns entity-dict-list")
def t8_to_irs_entities(llc) -> bool:
    from ledger.llcOwners import llcOwners
    obj = llcOwners(llc)
    r = obj.to_IRS()
    assert isinstance(r, list), f"llcOwners.to_IRS() → {type(r)} (want list)"
    assert len(r) > 0, "llcOwners.to_IRS() returned empty list"
    first = r[0]
    assert isinstance(first, dict), f"llcOwners.to_IRS()[0] → {type(first)}"
    assert len(first) == 1, f"llcOwners.to_IRS()[0] should have exactly 1 key (entityID); got {list(first.keys())}"
    entity_key = next(iter(first))
    body = first[entity_key]
    assert isinstance(body, dict), f"entity body → {type(body)}"
    # The body should look like an owner record (contain 'nm' or 'oID')
    assert ('nm' in body) or ('oID' in body), f"owner body missing 'nm'/'oID': {list(body.keys())}"
    return True


# ── T9 ──────────────────────────────────────────────────────────────────────

@_register("T9 — stmt*.to_IRS() returns dict[formNm → dict[logicalKey → value]]")
def t9_to_irs_stmt(llc) -> bool:
    from ledger.stmtIncomeStmt import stmtIncomeStmt
    obj = stmtIncomeStmt(llc)
    r = obj.to_IRS()
    assert isinstance(r, dict), f"stmtIncomeStmt.to_IRS() → {type(r)} (want dict)"
    # stmtIncomeStmt publishes to Form1065 per the PUBLISH_MAP
    if not r:
        # Empty dict is legal when PUBLISH_MAP is empty, but on this project
        # stmtIncomeStmt has Form1065 bindings — fail if empty here.
        raise AssertionError("stmtIncomeStmt.to_IRS() returned empty dict; "
                             "expected at least 'Form1065' keys.")
    for formNm, payload in r.items():
        assert isinstance(formNm, str), f"form key → {type(formNm)}"
        assert isinstance(payload, dict), f"{formNm} payload → {type(payload)}"
        # logicalKeys are strings
        for lk in payload.keys():
            assert isinstance(lk, str), f"logicalKey → {type(lk)}"
    return True


# ── T10 ─────────────────────────────────────────────────────────────────────

@_register("T10 — stmt*.save() raises InvalidRequestError")
def t10_stmt_save_raises(llc) -> bool:
    from ledger.ledgerObject     import InvalidRequestError
    from ledger.stmtBalanceSheet import stmtBalanceSheet
    from ledger.stmtIncomeStmt   import stmtIncomeStmt

    for Cls in (stmtBalanceSheet, stmtIncomeStmt):
        obj = Cls(llc)
        try:
            obj.save([])
        except InvalidRequestError as e:
            msg = str(e)
            assert msg == 'InvalidRequest; ImmutableObject', \
                f"{Cls.__name__}.save() raised InvalidRequestError with wrong msg: {msg!r}"
            continue
        except Exception as e:
            raise AssertionError(
                f"{Cls.__name__}.save() raised {type(e).__name__} not InvalidRequestError: {e}"
            )
        raise AssertionError(f"{Cls.__name__}.save() did NOT raise")
    return True


# ── T11 (Trial Balance — zero-sum invariant relative to GL) ─────────────────

@_register("T11 — stmtTrialBalance totals match stmtGeneralLedger sums")
def t11_tb_totals_match_gl(llc) -> bool:
    '''
    The Trial Balance is a pure pivot of the GL — so Σ Debit and Σ Credit
    in the TB must equal the corresponding sums from the GL (with COA
    seeds included) across the classic A/L/E/I/E buckets.
    '''
    from ledger.stmtGeneralLedger import stmtGeneralLedger, stmtTrialBalance
    import pandas as pd

    gl = stmtGeneralLedger(llc, view_by='All', include_coa_seed=True)
    gl_df = gl.to_DF()
    if 'acctType' in gl_df.columns and 'aType' in gl_df.columns and 'amt' in gl_df.columns:
        classic = {'Asset', 'Liability', 'Equity', 'Income', 'Expense'}
        slice_ = gl_df[gl_df['acctType'].isin(classic)]
        amt = pd.to_numeric(slice_['amt'], errors='coerce').fillna(0.0)
        gl_debit  = round(float(amt[slice_['aType'] == 'Debit' ].sum()), 2)
        gl_credit = round(float(amt[slice_['aType'] == 'Credit'].sum()), 2)
    else:
        gl_debit = gl_credit = 0.0

    tb = stmtTrialBalance(llc)
    t = tb.totals()
    d_match = abs(t['Debit']  - gl_debit)  < 0.01
    c_match = abs(t['Credit'] - gl_credit) < 0.01
    assert d_match, f"TB Debit {t['Debit']} ≠ GL Debit {gl_debit}"
    assert c_match, f"TB Credit {t['Credit']} ≠ GL Credit {gl_credit}"
    return True


# ── T12 (Trial Balance — COA completeness) ───────────────────────────────────

@_register("T12 — stmtTrialBalance covers every classifiable COA account")
def t12_tb_coa_completeness(llc) -> bool:
    '''
    Because stmtTrialBalance sources from a COA-seeded GL, every COA
    account with a classifiable acctType (A/L/E/I/E) must appear as at
    least one TB row (possibly with Debit=Credit=0).
    '''
    from ledger.stmtGeneralLedger import stmtTrialBalance
    from ledger.llcCOA            import ChartOfAccounts

    coa = getattr(llc, 'coa', None) or ChartOfAccounts(llc)
    coa_dict = coa.load() or {}
    classic = {'Asset', 'Liability', 'Equity', 'Income', 'Expense'}

    expected = set()
    for acct in coa_dict.keys():
        try:
            at = coa._Type(acct)
        except Exception:
            at = ''
        if at in classic:
            expected.add(acct)

    tb = stmtTrialBalance(llc)
    df = tb.to_DF()
    actual = set(df[df['acctType'] != 'TOTAL']['acct'].tolist())
    missing = expected - actual
    assert not missing, f"TB missing {len(missing)} COA accounts: {sorted(missing)[:10]}"
    return True


# ── Runner ──────────────────────────────────────────────────────────────────

def run_all(llc=None) -> Dict[str, Any]:
    '''
    Run every registered test.  Returns a report dict::

        { 'ok': bool, 'passed': [...], 'failed': [(name, err), ...], 'n': int }
    '''
    if llc is None:
        llc = _build_llc()

    passed: List[str] = []
    failed: List[Tuple[str, str]] = []

    for name, fn in _TESTS:
        try:
            ok = fn(llc)
            if ok:
                passed.append(name)
            else:
                failed.append((name, 'returned False'))
        except Exception as err:
            tb = traceback.format_exc(limit=2)
            failed.append((name, f"{type(err).__name__}: {err}\n{tb}"))

    return {
        'ok':     len(failed) == 0,
        'passed': passed,
        'failed': failed,
        'n':      len(_TESTS),
    }


def _report(res: Dict[str, Any]) -> int:
    n_ok = len(res['passed'])
    n_fail = len(res['failed'])
    print(f"testLedgerAPI: {n_ok}/{res['n']} passed")
    for name in res['passed']:
        print(f"  PASS  {name}")
    for name, err in res['failed']:
        print(f"  FAIL  {name}")
        for ln in err.strip().splitlines():
            print(f"        {ln}")
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    res = run_all()
    sys.exit(_report(res))
