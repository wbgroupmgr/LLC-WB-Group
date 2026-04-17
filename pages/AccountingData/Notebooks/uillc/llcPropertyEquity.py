'''
llcPropertyEquity — per-property equity / transaction report.

Groups llcAssets transactions by propID and presents a two-tier layout:
  • Property header row  — identity string + Debit/Credit balance
  • Transaction detail rows — one per source record

Column spec:
  Col 1  : property identity string  (propNm + propAddr + ownerNames)  [header row only]
  Col 2  : acctSub / tID-extension
  Col 3  : desc
  Col 4  : Debit   (amt when aType == Debit)
  Col 5  : Credit  (amt when aType == Credit)
  Col 6  : acctType
  Col 7  : acct
  Col 8  : Ledger

Timestamp of last change: 2026.04.16
'''

from typing import Any, Dict, List, Optional

from uillc.llcReportEngine import llcReportEngine


class llcPropertyEquity:

    VIEW_COLUMNS = ['prop_identity', 'acctSub_ext', 'desc', 'Debit', 'Credit',
                    'acctType', 'acct', 'Ledger']

    def __init__(self, eSession):
        self.eSession = eSession
        self.engine   = llcReportEngine(eSession)
        self._owners_cache: Optional[Dict[str, str]] = None

    # ── helpers ────────────────────────────────────────────────────────────────

    def _load_owners_map(self) -> Dict[str, str]:
        '''Return {oID: first_name_string} from the llcOwners file.'''
        if self._owners_cache is not None:
            return self._owners_cache
        owners = self.engine.load_owners()
        result: Dict[str, str] = {}
        for o in owners:
            oid = str(o.get('oID', ''))
            nm  = o.get('nm', '')
            if isinstance(nm, list):
                nm = nm[0] if nm else oid
            result[oid] = str(nm) if nm else oid
        self._owners_cache = result
        return result

    def _owner_names_str(self, prop_owners: Any) -> str:
        '''Resolve propOwners dict → comma-joined owner names (pct%).'''
        if not isinstance(prop_owners, dict):
            return ''
        owners_map = self._load_owners_map()
        parts = []
        for oid, pct in prop_owners.items():
            nm = owners_map.get(str(oid), str(oid))
            try:
                pct_str = f'{float(pct):.0f}%'
            except (TypeError, ValueError):
                pct_str = str(pct)
            parts.append(f'{nm} ({pct_str})')
        return ', '.join(parts)

    @staticmethod
    def _tID_extension(tID: str) -> str:
        '''
        Extract extension from a tID in form "<prefix>-<extension>".
        e.g. "a20250826-Cash1" → "Cash1"
        '''
        s = str(tID or '')
        idx = s.rfind('-')
        return s[idx + 1:] if idx >= 0 else s

    @staticmethod
    def _is_debit(atype: str) -> bool:
        return str(atype).strip().lower() in ('debit', 'dr', 'd')

    # ── main build ─────────────────────────────────────────────────────────────

    def _build_report(self) -> List[Dict[str, Any]]:
        '''
        Load llcAssets records, group by propID, produce a flat list of rows
        alternating between property-header rows and transaction detail rows.
        '''
        asset_list: List[Dict[str, Any]] = self.engine._load_source('llcAssets')

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for rec in asset_list:
            pid = str(rec.get('propID') or rec.get('tID') or '')
            if pid not in groups:
                groups[pid] = []
            groups[pid].append(rec)

        rows: List[Dict[str, Any]] = []

        for pid, recs in groups.items():
            first      = recs[0]
            prop_nm    = str(first.get('propNm',  '') or '')
            prop_addr  = str(first.get('propAddr', '') or '')
            owners_str = self._owner_names_str(first.get('propOwners'))
            identity   = ' | '.join(part for part in [prop_nm, prop_addr, owners_str] if part)

            total_debit  = 0.0
            total_credit = 0.0
            for rec in recs:
                try:
                    amt = float(rec.get('amt', 0) or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                if self._is_debit(rec.get('aType', '')):
                    total_debit  += amt
                else:
                    total_credit += amt
            balance = round(total_debit - total_credit, 2)

            rows.append({
                'row_type':      'property-header',
                'propID':        pid,
                'prop_identity': identity,
                'prop_nm':       prop_nm,
                'prop_addr':     prop_addr,
                'prop_owners':   str(first.get('propOwners', '')),
                'Debit':         round(total_debit,  2),
                'Credit':        round(total_credit, 2),
                'Balance':       balance,
                'acctSub_ext':   '',
                'desc':          '',
                'acctType':      '',
                'acct':          '',
                'Ledger':        '',
            })

            for rec in recs:
                try:
                    amt = float(rec.get('amt', 0) or 0)
                except (TypeError, ValueError):
                    amt = 0.0

                is_db  = self._is_debit(rec.get('aType', ''))
                debit  = round(amt, 2) if is_db  else 0.0
                credit = round(amt, 2) if not is_db else 0.0

                acct_sub     = str(rec.get('acctSub') or '')
                tid_ext      = self._tID_extension(rec.get('tID', ''))
                acct_sub_ext = f'{acct_sub} / {tid_ext}' if acct_sub else tid_ext

                rows.append({
                    'row_type':      'data',
                    'propID':        pid,
                    'prop_identity': '',
                    'prop_nm':       '',
                    'prop_addr':     '',
                    'prop_owners':   '',
                    'acctSub_ext':   acct_sub_ext,
                    'desc':          str(rec.get('desc',    '') or ''),
                    'Debit':         debit,
                    'Credit':        credit,
                    'Balance':       round(debit - credit, 2),
                    'acctType':      str(rec.get('acctType', '') or ''),
                    'acct':          str(rec.get('acct',     '') or ''),
                    'Ledger':        str(rec.get('Ledger',   '') or ''),
                    'tID':           str(rec.get('tID',      '') or ''),
                    'dt':            str(rec.get('dt',       '') or ''),
                    'aType':         str(rec.get('aType',    '') or ''),
                    'refDB':         str(rec.get('refDB',    '') or ''),
                })

        return rows

    # ── public interface ───────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        rows = self._build_report()
        if view_by and view_by != 'All':
            target    = view_by.lower()
            keep_pids: set = set()
            for r in rows:
                if r['row_type'] == 'property-header':
                    if target in r.get('prop_identity', '').lower() or \
                       target in r.get('propID', '').lower():
                        keep_pids.add(r['propID'])
            rows = [r for r in rows if r.get('propID') in keep_pids]
        return rows

    def stats(self) -> Dict[str, Any]:
        rows    = self._build_report()
        headers = [r for r in rows if r['row_type'] == 'property-header']
        details = [r for r in rows if r['row_type'] == 'data']
        total_d = round(sum(r['Debit']  for r in headers), 2)
        total_c = round(sum(r['Credit'] for r in headers), 2)
        return {
            'Properties':   len(headers),
            'Transactions': len(details),
            'TotalDebit':   total_d,
            'TotalCredit':  total_c,
            'NetBalance':   round(total_d - total_c, 2),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': 'llcPropertyEquity',
            'note':       'Read-only. Per-property equity report from llcAssets.',
        }

    def object_name(self) -> str:
        return 'llcPropertyEquity'

    def list(self) -> List[Dict[str, Any]]:
        return self.load()

    def save(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def save_object(self, data: Any = None) -> List[Dict[str, Any]]:
        return self.load()

    def reset_from_object(self) -> List[Dict[str, Any]]:
        return self.load()
