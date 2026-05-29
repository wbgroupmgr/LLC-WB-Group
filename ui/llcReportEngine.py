'''
ui.llcReportEngine — Session adapter for the LLC Editor web UI.

Phase 4 refactor (DataModelGuide § 3): View Services hold no data
construction.  The engine is now a thin session adapter that:

  * loads per-table JSON working-files from the eSession,
  * expands ledger records into double-entry GL via ledger.ledgerGeneral,
  * delegates Balance-Sheet / Income-Statement construction to the
    immutable constructed-data objects in `stmt/`,
  * exposes Chart-of-Accounts lookups + IRS helper aggregations used by
    the Form-1065 / K-1 flows.

All BS/IS math that previously lived here has moved to:
    ledger.stmtBalanceSheet
    ledger.stmtIncomeStmt   (+ build_per_member() for the per-member IS)

Timestamp of last change: 2026.04.19
'''

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

from ledger.stmtGL import ledgerGeneral
from ledger.stmtBS import stmtBS as _stmtBalanceSheet
from ledger.stmtIS import stmtIS as _stmtIncomeStmt


class llcReportEngine:
    '''
    Session adapter for the LLC Editor web UI.

    Usage:
        engine = llcReportEngine(eSession)
        gl_list         = engine.getGLList()
        bs_rows, check  = engine.buildBS()   # delegates to ledger.stmtBalanceSheet
        is_rows, summ   = engine.buildIS()   # delegates to ledger.stmtIncomeStmt
    '''

    def __init__(self, eSession):
        self.eSession = eSession
        self.gl = ledgerGeneral(eSession.llc)
        self._gl_cache: Optional[List[Dict]] = None

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_source(self, name: str) -> List[Dict[str, Any]]:
        wk = self.eSession.oDict.get(name)
        if wk is None:
            return []
        # Primary: working (temp) file — reflects every editor Save immediately.
        # The getBal/getBalSh lambdas that previously crashed on string amt are
        # now fixed (float coercion in ledger/llcAssets.py) so this path is safe.
        try:
            from pathlib import Path as _Path
            if _Path(wk.FN()).exists():
                wk_data = wk.load()
                if isinstance(wk_data, list) and wk_data:
                    return wk_data
        except Exception:
            pass
        # Fallback: committed real file (used on fresh starts before any edits)
        data = wk.o.load()
        return data if isinstance(data, list) else []

    def getGLList(self, resolve_dups: bool = True, force: bool = False) -> List[Dict[str, Any]]:
        '''
        Build the full General Ledger via double-entry expansion + merge.
        Result is cached per engine instance (call with force=True to refresh).

        Sources merged, in priority order (first source wins on tID collision):
            llcAssets → llcExpRev → llcPayables → llcReceivables
        '''
        if self._gl_cache is not None and not force:
            return self._gl_cache

        asset_list = self._load_source('llcAssets')
        er_list    = self._load_source('llcExpRev')
        ap_list    = self._load_source('llcPayables')
        ar_list    = self._load_source('llcReceivables')

        asset_expanded = self.gl.toDoubleEntry(asset_list)
        er_expanded    = self.gl.toDoubleEntry(er_list)
        ap_expanded    = self.gl.toDoubleEntry(ap_list)
        ar_expanded    = self.gl.toDoubleEntry(ar_list)

        # Order matters on tID collisions: first source wins the dedup.
        self._gl_cache = self.gl.mergeGL(
            [asset_expanded, er_expanded, ap_expanded, ar_expanded],
            resolve_dups=resolve_dups,
        )
        return self._gl_cache

    def getGLListWithDups(self) -> List[Dict[str, Any]]:
        '''GL list keeping all records and flagging cross-source dups.'''
        er_list    = self._load_source('llcExpRev')
        asset_list = self._load_source('llcAssets')
        ap_list    = self._load_source('llcPayables')
        ar_list    = self._load_source('llcReceivables')
        er_expanded    = self.gl.toDoubleEntry(er_list)
        asset_expanded = self.gl.toDoubleEntry(asset_list)
        ap_expanded    = self.gl.toDoubleEntry(ap_list)
        ar_expanded    = self.gl.toDoubleEntry(ar_list)
        return self.gl.mergeGL(
            [er_expanded, asset_expanded, ap_expanded, ar_expanded],
            resolve_dups=False,
        )

    def toDF(self) -> 'pd.DataFrame':
        '''Return GL as a pandas DataFrame with acctType column.'''
        if not _PANDAS_OK:
            raise ImportError('pandas is required for toDF()')
        rows = self.getGLList(resolve_dups=True)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df['amt']      = pd.to_numeric(df.get('amt'), errors='coerce').fillna(0.0)
        df['acctType'] = df['acct'].apply(lambda v: self.gl.coa._Type(v))
        return df

    # ── Balance Sheet (delegated) ────────────────────────────────────────────

    def buildBS(self, view_by: str = 'All') -> Tuple[List[Dict], Dict]:
        '''
        Thin delegator: build an immutable ledger.stmtBalanceSheet against the
        current working-file GL and return (rows, accounting-equation check).
        '''
        gl_records = self.getGLList(resolve_dups=True)
        bs = _stmtBalanceSheet(
            self.eSession.llc,
            gl_records=gl_records,
        )
        return bs.load(), bs.last_check()

    # ── Income Statement (delegated) ─────────────────────────────────────────

    def buildIS(self, view_by: str = 'All') -> Tuple[List[Dict], Dict]:
        '''
        Thin delegator: build an immutable ledger.stmtIncomeStmt against the
        current working-file GL and return (rows, net-income summary).
        '''
        gl_records = self.getGLList(resolve_dups=True)
        isstmt = _stmtIncomeStmt(
            self.eSession.llc,
            gl_records=gl_records,
        )
        return isstmt.load(), isstmt.last_summary()

    # ── COA lookup ────────────────────────────────────────────────────────────

    def coa_lookup(self, acct: str) -> Optional[Dict[str, Any]]:
        '''Return COA entry for acct, or None if not found.'''
        entry = self.gl.coa.get(acct)
        if entry is None:
            return None
        return {
            'acct':     acct,
            'acctID':   entry.get('acctID', ''),
            'acctDesc': entry.get('acctDesc', ''),
            'acctType': self.gl.coa._Type(acct),
        }

    def coa_all(self) -> List[Dict[str, Any]]:
        '''Return all COA entries as a list for autocomplete.'''
        coa_dict = self.gl.coa.load()
        result = []
        for acct, entry in coa_dict.items():
            result.append({
                'acct':     acct,
                'acctID':   entry.get('acctID', ''),
                'acctDesc': entry.get('acctDesc', ''),
                'acctType': self.gl.coa._Type(acct),
            })
        return sorted(result, key=lambda x: x.get('acctID', ''))

    # ── Owners file discovery ─────────────────────────────────────────────────

    def _find_owners_path(self) -> Optional[Path]:
        '''Discover the llcOwners JSON file from known WkNode paths.'''
        for wk in self.eSession.oDict.values():
            p = Path(wk.o.FN())
            accts_dir = p.parent
            # Pattern: llcOwners_<LLCName>.json
            for candidate in accts_dir.glob('llcOwners_*.json'):
                return candidate
        return None

    def load_owners(self) -> List[Dict[str, Any]]:
        '''Load owner records from the llcOwners JSON file.'''
        path = self._find_owners_path()
        if path is None or not path.exists():
            return []
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ── IRS / K-1 helpers ────────────────────────────────────────────────────

    @staticmethod
    def _owner_first_name(o: Dict[str, Any]) -> str:
        nm = o.get('nm', '')
        if isinstance(nm, list):
            return nm[0] if nm else o.get('oID', '')
        return str(nm) if nm else o.get('oID', '')

    def _rent_income_total(self) -> float:
        '''Sum Credit amounts for Acct.Rev.Rent entries in the GL.'''
        total = 0.0
        for r in self.getGLList(resolve_dups=True):
            if r.get('acct') != 'Acct.Rev.Rent':
                continue
            atype = str(r.get('aType', '')).strip().lower()
            if atype in ('credit', 'cr', 'c'):
                try:
                    total += float(r.get('amt', 0) or 0)
                except (TypeError, ValueError):
                    pass
        return round(total, 2)

    def _interest_expense_total(self) -> float:
        '''
        Sum Debit amounts for Acct.Exp.Other entries where
        acctSub contains "interest" OR desc contains "interest" (case-insensitive).
        '''
        total = 0.0
        for r in self.getGLList(resolve_dups=True):
            if r.get('acct') != 'Acct.Exp.Other':
                continue
            acct_sub = str(r.get('acctSub') or '').lower()
            desc     = str(r.get('desc')    or '').lower()
            if 'interest' not in acct_sub and 'interest' not in desc:
                continue
            atype = str(r.get('aType', '')).strip().lower()
            if atype in ('debit', 'dr', 'd'):
                try:
                    total += float(r.get('amt', 0) or 0)
                except (TypeError, ValueError):
                    pass
        return round(total, 2)

    def _contributions_by_owner(self) -> Dict[str, float]:
        '''
        Per-owner capital contributions: GL Credit entries to Acct.Equity.Owner.Capital.Funds
        weighted by the record's propOwners (integer %).
        '''
        result: Dict[str, float] = {}
        for r in self.getGLList(resolve_dups=True):
            if r.get('acct') != 'Acct.Equity.Owner.Capital.Funds':
                continue
            atype = str(r.get('aType', '')).strip().lower()
            if atype not in ('credit', 'cr', 'c'):
                continue
            prop_owners = r.get('propOwners')
            if not isinstance(prop_owners, dict):
                continue
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            for oID, pct in prop_owners.items():
                try:
                    result[str(oID)] = result.get(str(oID), 0.0) + amt * float(pct) / 100.0
                except (TypeError, ValueError):
                    pass
        return {k: round(v, 2) for k, v in result.items()}

    def _capital_end_year_by_owner(self) -> Dict[str, float]:
        '''
        Capital Account End of Year: GL Debit entries to Acct.Fixed.Tangible* accounts
        weighted by propOwners (integer %).  Represents partner book-value share of
        tangible fixed assets.
        '''
        result: Dict[str, float] = {}
        for r in self.getGLList(resolve_dups=True):
            acct = r.get('acct', '')
            if not acct.startswith('Acct.Fixed.Tangible'):
                continue
            atype = str(r.get('aType', '')).strip().lower()
            if atype not in ('debit', 'dr', 'd'):
                continue
            prop_owners = r.get('propOwners')
            if not isinstance(prop_owners, dict):
                continue
            try:
                amt = float(r.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            for oID, pct in prop_owners.items():
                try:
                    result[str(oID)] = result.get(str(oID), 0.0) + amt * float(pct) / 100.0
                except (TypeError, ValueError):
                    pass
        return {k: round(v, 2) for k, v in result.items()}

    # ── Net income per owner ──────────────────────────────────────────────────

    def owner_pl_allocation(self) -> List[Dict[str, Any]]:
        '''
        Allocate net income/loss to each owner based on their pct field in llcOwners.
        Returns list of {oID, name, pct, net_income_share}.
        '''
        _, is_summary = self.buildIS()
        net_income = is_summary.get('net_income', 0.0)

        owners = self.load_owners()
        result = []
        for o in owners:
            pct = float(o.get('pct', 0))
            result.append({
                'oID':              o.get('oID', ''),
                'name':             ', '.join(o.get('nm', [])),
                'status':           o.get('status', ''),
                'pct':              pct,
                'net_income_share': round(net_income * pct, 2),
            })
        return result
