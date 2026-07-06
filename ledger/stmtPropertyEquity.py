'''
ledger.stmtPropertyEquity — Constructed, immutable per-property Equity statement.

Per DataModelGuide § 2:  constructed data object, immutable once instantiated,
every row carries a _lineNo and _rowNm, every column has a columnID, and every
cell is addressable by (stmtObj / tblID / rowNm / colNm).

Inheritance:    stmtDB → ledger.ledgerDB

FIXME — MIGRATE TO GENERAL LEDGER SOURCE
----------------------------------------
This class currently sources its per-property data from ``llcAssets`` (via
capitalDist) — it has NOT yet been switched to ``stmtGeneralLedger`` as its
single source of truth.  Once the GL carries fully-expanded property × owner
capital rows, the build path below should be rewritten to pull from
``stmtGeneralLedger`` using the same pattern as
``stmtBalanceSheet._load_from_general_ledger()``.  Tracked as future work;
leaving the asset-based path in place so the property-level view keeps
functioning during the reset-and-simplify phase.

Construction inputs (exactly one path is taken, in preference order):
  1. asset_records=..., owners=...
     — explicit raw llcAssets list and owner list (fastest; used by the ui/
       wrapper so working-file edits are honoured).
  2. sources=dict(asset=..., owners=...)  — same shape, bundled.
  3. (default) Load from ledger DB   — llcAssets + llcOwners JSON under
                                       <TOP>/Accts.

After construction the instance is FROZEN; any attribute write raises
StmtImmutableError.

Row layout (two-tier, one row schema with a `row_type` discriminator):
    property-header : { row_type, propID, prop_identity, prop_nm, prop_addr,
                        prop_owners, Debit, Credit, Balance }
    data            : { row_type, propID, acctSub_ext, desc, Debit, Credit,
                        Balance, acctType, acct, Ledger, tID, dt, aType, refDB }

Columns are the union of both row types so nSpaceMap addressing is uniform.
'''

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ledger.stmtDB import stmtDB


class stmtPropertyEquity(stmtDB):
    '''
    Immutable per-property equity report constructed at instantiation time.
    '''

    DEFAULT_TBLID = "PropertyEquity"

    # Display columns expected by property_equity.html (table_view superset).
    # The template reads row.data.get('<key>', ''), so rows that don't use a
    # field simply omit / leave it blank.
    COLUMNS = [
        'row_type',
        'propID', 'prop_identity', 'prop_nm', 'prop_addr', 'prop_owners',
        'acctSub_ext', 'desc',
        'Debit', 'Credit', 'Balance',
        'acctType', 'acct', 'Ledger',
        'tID', 'dt', 'aType', 'refDB',
    ]

    VIEW_BY_OPTIONS: List[str] = []

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(self,
                 llc,
                 view_by: str = 'All',
                 asset_records: Optional[List[Dict[str, Any]]] = None,
                 owners:        Optional[List[Dict[str, Any]]] = None,
                 sources:       Optional[Dict[str, Any]] = None,
                 **kwargs):
        self._init_view_by       = view_by
        self._init_asset_records = asset_records
        self._init_owners        = owners
        self._init_sources       = sources

        super().__init__(llc, **kwargs)

    # ── Main build pipeline ──────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        # FIXME: switch source from llcAssets → stmtGeneralLedger once the GL
        # carries per-property stakeholder capital rows.  See module-level
        # FIXME block above.  stmtBalanceSheet / stmtIncomeStmt already pull
        # from GL; this class plus stmtOwnerEquity are the last holdouts.
        asset_records = self._init_asset_records
        owners        = self._init_owners

        if (asset_records is None or owners is None) and self._init_sources:
            if asset_records is None:
                asset_records = self._init_sources.get('asset')
            if owners is None:
                owners = self._init_sources.get('owners')

        if asset_records is None or owners is None:
            da, do = self._load_default_sources()
            if asset_records is None: asset_records = da
            if owners        is None: owners        = do

        rows, summary = self._build_report(asset_records or [], owners or [])

        # Apply view_by filter (substring match on propID or prop_identity).
        view_by = (self._init_view_by or 'All').strip()
        if view_by and view_by != 'All':
            target = view_by.lower()
            keep_pids: set = set()
            for r in rows:
                if r.get('row_type') == 'property-header':
                    if (target in str(r.get('prop_identity', '')).lower()
                            or target in str(r.get('propID', '')).lower()):
                        keep_pids.add(r.get('propID'))
            rows = [r for r in rows if r.get('propID') in keep_pids]

        # Populate stmtDB slots.
        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "view_by":     view_by,
            "properties":  summary.get('properties', 0),
            "transactions": summary.get('transactions', 0),
            "sourceMode": (
                "asset_records" if self._init_asset_records is not None
                else "sources"  if self._init_sources is not None
                else "ledgerDB"
            ),
            "note": "Read-only. Per-property equity report from llcAssets.",
        }
        self._summary = summary

    # ── Source loading (default path: read ledger DB files) ──────────────────

    def _load_default_sources(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        asset_list: List[Dict[str, Any]] = []
        owner_list: List[Dict[str, Any]] = []

        try:
            from ledger.llcAssets import llcAssets as _Assets
            obj = _Assets(self.llc)
            data = obj.load()
            if isinstance(data, list):
                asset_list = data
        except Exception as err:
            print(f"stmtPropertyEquity: could not load ledger.llcAssets: {err}")

        try:
            from ledger.llcOwners import llcOwners as _Owners
            obj = _Owners(self.llc)
            data = obj.load()
            if isinstance(data, list):
                owner_list = data
        except Exception as err:
            print(f"stmtPropertyEquity: could not load ledger.llcOwners: {err}")

        return asset_list, owner_list

    # ── Helpers (ported from uillc.stmtPropertyEquity) ────────────────────────

    @staticmethod
    def _owners_map_from_list(owner_list: List[Dict[str, Any]]) -> Dict[str, str]:
        '''Return {oID: first_name_string} from an llcOwners list.'''
        result: Dict[str, str] = {}
        for o in (owner_list or []):
            oid = str(o.get('oID', ''))
            nm  = o.get('nm', '')
            if isinstance(nm, list):
                nm = nm[0] if nm else oid
            result[oid] = str(nm) if nm else oid
        return result

    @staticmethod
    def _owner_names_str(prop_owners: Any, owners_map: Dict[str, str]) -> str:
        '''Resolve propOwners dict → comma-joined owner names (pct%).'''
        if not isinstance(prop_owners, dict):
            return ''
        parts: List[str] = []
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
        '''Extract extension from a tID in form "<prefix>-<extension>".'''
        s = str(tID or '')
        idx = s.rfind('-')
        return s[idx + 1:] if idx >= 0 else s

    @staticmethod
    def _is_debit(atype: str) -> bool:
        return str(atype).strip().lower() in ('debit', 'dr', 'd')

    # ── Main build ───────────────────────────────────────────────────────────

    def _build_report(self,
                      asset_list: List[Dict[str, Any]],
                      owner_list: List[Dict[str, Any]]
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        '''
        Build the flat list of rows (alternating property-header / data rows).
        Bit-for-bit parity with uillc.stmtPropertyEquity._build_report.
        '''
        owners_map: Dict[str, str] = self._owners_map_from_list(owner_list)

        # Group by propNm — the consistently-populated per-property identifier
        # (enforced going forward by issue #64's ownership-rule gate). propID
        # is not a genuine shared per-property key in existing data: it is
        # either empty or a copy of that individual record's own tID, which
        # would put every transaction in its own single-row group (issue #69).
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for rec in asset_list:
            pid = str(rec.get('propNm') or rec.get('propID') or rec.get('tID') or '')
            groups.setdefault(pid, []).append(rec)

        rows: List[Dict[str, Any]] = []

        for pid, recs in groups.items():
            first      = recs[0]
            prop_nm    = str(first.get('propNm',   '') or '')
            prop_addr  = str(first.get('propAddr', '') or '')
            owners_str = self._owner_names_str(first.get('propOwners'), owners_map)
            identity   = ' | '.join(p for p in [prop_nm, prop_addr, owners_str] if p)

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
                'tID':           '',
                'dt':            '',
                'aType':         '',
                'refDB':         '',
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

        headers = [r for r in rows if r.get('row_type') == 'property-header']
        details = [r for r in rows if r.get('row_type') == 'data']
        total_d = round(sum(r['Debit']  for r in headers), 2)
        total_c = round(sum(r['Credit'] for r in headers), 2)
        summary = {
            'properties':   len(headers),
            'transactions': len(details),
            'total_debit':  total_d,
            'total_credit': total_c,
            'net_balance':  round(total_d - total_c, 2),
        }
        return rows, summary

    # ── Row-name derivation (override) ───────────────────────────────────────

    def _default_rowNm(self, row: Dict[str, Any], i: int) -> str:
        '''
        property-header → <propID>
        data row        → <propID>.<tID>   (falls back to sequential)
        '''
        rt  = row.get('row_type', '')
        pid = str(row.get('propID', '') or '')
        if rt == 'property-header':
            return pid or f"header_{i:03d}"
        # data row
        tid = str(row.get('tID', '') or '')
        if pid and tid:
            return f"{pid}.{tid}"
        if pid:
            return f"{pid}.row_{i:03d}"
        return super()._default_rowNm(row, i)

    # ── UI conveniences (read-only) ──────────────────────────────────────────

    def last_summary(self) -> Dict[str, Any]:
        return dict(self._summary) if getattr(self, '_summary', None) else {}

    def stats(self) -> Dict[str, Any]:
        s = self.last_summary() or {}
        return {
            'Properties':   s.get('properties',   0),
            'Transactions': s.get('transactions', 0),
            'TotalDebit':   s.get('total_debit',  0.0),
            'TotalCredit':  s.get('total_credit', 0.0),
            'NetBalance':   s.get('net_balance',  0.0),
        }
