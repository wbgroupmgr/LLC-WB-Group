'''
ledger.stmtOwnerEquity — Constructed, immutable Owner/Member Equity statement.

Per DataModelGuide § 2:  constructed data object, immutable once instantiated,
every row carries a _lineNo and _rowNm, every column has a columnID, and every
cell is addressable by (stmtObj / tblID / rowNm / colNm).

Inheritance:    stmtDB → ledger.ledgerDB

FIXME — MIGRATE TO GENERAL LEDGER SOURCE
----------------------------------------
This class currently sources its member-capital data from ``llcAssets``
(via capitalDist) — it is the ONLY remaining data object in the ledger/
layer that has not yet been switched to ``stmtGeneralLedger`` as its single
source of truth.  Once the GL carries fully-expanded stakeholder rows
(one per partner × capital COA account) the build path below should be
rewritten to pull from ``stmtGeneralLedger`` using the same pattern as
``stmtBalanceSheet._load_from_general_ledger()``.  Tracked as future work;
leaving the asset-based path in place so the Schedule K-1 / Sched-M-2
pipeline keeps functioning during the reset-and-simplify phase.

Construction inputs (exactly one path is taken, in preference order):
  1. asset_records=..., owners=..., net_income=...
     — explicit raw llcAssets list, owner list, and net-income scalar
       (fastest; used by the ui/ wrapper so working-file edits are honoured).
  2. sources=dict(asset=..., owners=..., net_income=...)
     — same shape, bundled in a dict.
  3. (default) Load from ledger DB
     — llcAssets + llcOwners JSON under <TOP>/Accts (net_income defaults to 0
       unless gl_records is also supplied, in which case it's derived from an
       Income Statement build).

After construction the instance is FROZEN; any attribute write raises
StmtImmutableError.

Columns:
    acctType, acct, acctSub, Debit, Credit, Balance

Row layout:
    For each owner (insertion order from capitalDist), one row per
    (acct, acctSub) bucket, then one "Net Income Share (x.x%)" row.
    A grand-total TOTAL row is appended last.
'''

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ledger.stmtDB import stmtDB
from irs.publishMap import PubEntry, F_TEXT


class stmtOwnerEquity(stmtDB):
    '''
    Immutable Owner Equity constructed at instantiation time.

    VIEW_BY_OPTIONS is exposed so ui modules can reuse the same list of
    view-by filters they presented under the uillc layer.
    '''

    DEFAULT_TBLID = "OwnerEquity"
    COLUMNS = ['acctType', 'acct', 'acctSub', 'Debit', 'Credit', 'Balance']
    VIEW_BY_OPTIONS: List[str] = []

    # ── Form 1065 publish map (DataModelGuide § 4 / Phase 5) ─────────────────
    #
    # The TOTAL row's Balance column is the sum of all member capital
    # balances + their net-income shares — i.e. partners' capital accounts
    # at end of year.  That matches Form 1065:
    #   • Sched L L21 col(d) — Partners' capital accounts — end of year
    #   • Sched M-2 L9      — Balance at end of year
    #
    # Per-member contribution/distribution breakdowns (for M2_2a / M2_6a
    # etc.) are NOT bound here because they require filtering by owner and
    # account type; irs.Form1065.nSpaceMap() falls back to the legacy
    # ``_FILL_MAP`` + ``stmtFinancialReport`` aggregator for those keys.
    PUBLISH_MAP = {
        "Form1065": [
            PubEntry(src_row="TOTAL", src_col="Balance",
                     logicalKey="L_21_2", fType=F_TEXT, sign=+1,
                     note="Sched L L21 col(d) — Partners' capital accts EOY"),
            PubEntry(src_row="TOTAL", src_col="Balance",
                     logicalKey="M2_9",   fType=F_TEXT, sign=+1,
                     note="Sched M-2 L9 — Balance at end of year"),
        ],
    }

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(self,
                 llc,
                 asset_records: Optional[List[Dict[str, Any]]] = None,
                 owners:        Optional[List[Dict[str, Any]]] = None,
                 net_income:    Optional[float] = None,
                 sources:       Optional[Dict[str, Any]] = None,
                 gl_records:    Optional[List[Dict[str, Any]]] = None,
                 **kwargs):
        # Stash construction inputs so _build() can use them.
        # (Normal attribute writes — class is not yet frozen.)
        self._init_asset_records = asset_records
        self._init_owners        = owners
        self._init_net_income    = net_income
        self._init_sources       = sources
        self._init_gl_records    = gl_records

        # stmtDB.__init__ runs _build() then freezes the instance.
        super().__init__(llc, **kwargs)

    # ── Main build pipeline ──────────────────────────────────────────────────

    def _build(self, **kwargs) -> None:
        # FIXME: switch source from llcAssets → stmtGeneralLedger once the GL
        # carries per-stakeholder capital rows.  See module-level FIXME block
        # above.  stmtBalanceSheet / stmtIncomeStmt already pull from GL; this
        # class is the last holdout that reads llcAssets directly.
        asset_records = self._init_asset_records
        owners        = self._init_owners
        net_income    = self._init_net_income

        if (asset_records is None or owners is None or net_income is None) and self._init_sources:
            if asset_records is None:
                asset_records = self._init_sources.get('asset')
            if owners is None:
                owners = self._init_sources.get('owners')
            if net_income is None:
                net_income = self._init_sources.get('net_income')

        if asset_records is None or owners is None:
            da, do = self._load_default_sources()
            if asset_records is None: asset_records = da
            if owners        is None: owners        = do

        if net_income is None:
            net_income = self._derive_net_income(self._init_gl_records)

        rows, summary = self._aggregate_oe(asset_records, owners, float(net_income or 0.0))

        # Populate stmtDB slots.
        self._tblID   = self.DEFAULT_TBLID
        self._columns = list(self.COLUMNS)
        self._rows    = rows
        self._meta    = {
            "net_income":  round(float(net_income or 0.0), 2),
            "member_count": summary.get('members', 0),
            "sourceMode": (
                "asset_records" if self._init_asset_records is not None
                else "sources"  if self._init_sources is not None
                else "ledgerDB"
            ),
            "note": (
                "Capital distribution from llcAssets.propOwners (integer %). "
                "Net Income Share from llcOwners.pct (decimal). "
                "Section headers = member names."
            ),
        }
        # Keep a convenience handle; stmtDB will freeze us shortly.
        self._summary = summary

    # ── Source loading (default path: read ledger DB files) ──────────────────

    def _load_default_sources(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        '''
        Default: load raw llcAssets + llcOwners directly from the ledger layer.
        The UI wrapper will normally bypass this by passing explicit inputs.
        '''
        asset_list: List[Dict[str, Any]] = []
        owner_list: List[Dict[str, Any]] = []

        try:
            from ledger.llcAssets import llcAssets as _Assets
            obj = _Assets(self.llc)
            data = obj.load()
            if isinstance(data, list):
                asset_list = data
        except Exception as err:
            print(f"stmtOwnerEquity: could not load ledger.llcAssets: {err}")

        try:
            from ledger.llcOwners import llcOwners as _Owners
            obj = _Owners(self.llc)
            data = obj.load()
            if isinstance(data, list):
                owner_list = data
        except Exception as err:
            print(f"stmtOwnerEquity: could not load ledger.llcOwners: {err}")

        return asset_list, owner_list

    def _derive_net_income(self, gl_records: Optional[List[Dict[str, Any]]]) -> float:
        '''
        If caller supplied a gl_records list, build a fresh immutable
        ledger.stmtIncomeStmt from it and pull net_income from its summary.
        Otherwise return 0.0 (no side effects, no implicit DB reads).
        '''
        if not gl_records:
            return 0.0
        try:
            from ledger.stmtIS import stmtIS as _IS
            isStmt = _IS(self.llc, gl_records=gl_records)
            ni = isStmt.last_summary().get('net_income', 0.0)
            return float(ni or 0.0)
        except Exception as err:
            print(f"stmtOwnerEquity: could not derive net_income: {err}")
            return 0.0

    # ── OE aggregation (bit-for-bit port of uillc.stmtOwnerEquity.load) ───────

    def _aggregate_oe(self,
                      asset_list: List[Dict[str, Any]],
                      owners_data: List[Dict[str, Any]],
                      net_income: float
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        '''
        Build per-member capital distribution rows from raw llcAssets +
        llcOwners, mirroring uillc.stmtOwnerEquity.load().
        '''
        expanded = self._capital_dist(asset_list, owners_data)

        if not expanded:
            return [], {'members': 0, 'net_income': round(net_income, 2)}

        # Group by (o_oID, acct, acctSub) → sum amt; preserve owner insertion order.
        owner_names: Dict[str, str] = {}
        buckets: Dict[tuple, float] = defaultdict(float)

        for rec in expanded:
            o_oID    = rec.get('o_oID', '')
            o_nm     = rec.get('o_nm', o_oID)
            acct     = rec.get('acct', '')
            acct_sub = str(rec.get('acctSub') or '')
            try:
                amt = float(rec.get('amt', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if o_oID not in owner_names:
                owner_names[o_oID] = o_nm
            buckets[(o_oID, acct, acct_sub)] += amt

        owner_pct_map = {str(o.get('oID', '')): float(o.get('pct', 0.0) or 0.0)
                         for o in owners_data}

        rows: List[Dict[str, Any]] = []

        for o_oID, o_nm in owner_names.items():
            # Account rows for this member, sorted by (acct, acctSub).
            member_acct_rows = sorted(
                ((acct, acct_sub, total_amt)
                 for (oid, acct, acct_sub), total_amt in buckets.items()
                 if oid == o_oID),
                key=lambda x: (x[0], x[1])
            )

            for acct, acct_sub, total_amt in member_acct_rows:
                bal = round(total_amt, 2)
                rows.append({
                    'acctType': o_nm,                       # member → section header
                    'acct':     acct,
                    'acctSub':  acct_sub,
                    'Debit':    round(bal,  2) if bal >= 0 else 0.0,
                    'Credit':   round(-bal, 2) if bal < 0  else 0.0,
                    'Balance':  bal,
                })

            # Net income share row for this member.
            pct_pl   = owner_pct_map.get(o_oID, 0.0)
            ni_share = round(net_income * pct_pl, 2)
            rows.append({
                'acctType': o_nm,
                'acct':     f'Net Income Share ({pct_pl * 100:.1f}%)',
                'acctSub':  '',
                'Debit':    0.0,
                'Credit':   0.0,
                'Balance':  ni_share,
            })

        # Grand TOTAL row.
        total_d = round(sum(r['Debit']   for r in rows), 2)
        total_c = round(sum(r['Credit']  for r in rows), 2)
        total_b = round(sum(r['Balance'] for r in rows), 2)
        rows.append({
            'acctType': 'TOTAL', 'acct': '', 'acctSub': '',
            'Debit': total_d, 'Credit': total_c, 'Balance': total_b,
        })

        summary = {
            'members':     len(owner_names),
            'net_income':  round(net_income, 2),
            'total_debit':  total_d,
            'total_credit': total_c,
            'total_balance': total_b,
        }
        return rows, summary

    @staticmethod
    def _capital_dist(asset_list: List[Dict[str, Any]],
                      owner_list: List[Dict[str, Any]]
                      ) -> List[Dict[str, Any]]:
        '''
        In-module re-implementation of llcOwners.capitalDist() that does not
        need an eSession / ledger DB.  Takes raw lists in, returns a flat list
        of expanded dicts with o_-prefixed owner fields and owner-weighted amt.
        '''
        oDict: Dict[str, Dict[str, Any]] = {
            str(o.get('oID', '')): o for o in (owner_list or [])
        }

        def _new_owner(oID: str) -> Dict[str, Any]:
            return {
                'oID': oID, 'nm': [oID], 'addr': '',
                'status': 'Unknown', 'memType': '', 'pct': 1.0, 'kw': [],
            }

        out: List[Dict[str, Any]] = []
        for tDict in (asset_list or []):
            propOwners = tDict.get('propOwners')
            if not isinstance(propOwners, dict):
                continue

            for oID, oPct in propOwners.items():
                ownerDict = oDict.get(str(oID)) or _new_owner(str(oID))

                o_fields: Dict[str, Any] = {'o_oID': ownerDict.get('oID', str(oID))}
                for k, v in ownerDict.items():
                    if k != 'oID':
                        o_fields[f'o_{k}'] = v
                if isinstance(o_fields.get('o_nm'), list):
                    nm_list = o_fields['o_nm']
                    o_fields['o_nm'] = nm_list[0] if nm_list else str(oID)

                mDict = {**tDict, **o_fields}
                try:
                    raw_amt = float(tDict.get('amt', 0) or 0)
                    mDict['amt'] = round(raw_amt * float(oPct) / 100.0, 4)
                except (TypeError, ValueError):
                    mDict['amt'] = 0.0

                out.append(mDict)
        return out

    # ── Row-name derivation (override) ───────────────────────────────────────

    def _default_rowNm(self, row: Dict[str, Any], i: int) -> str:
        '''
        Owner Equity rows use the member name as the section key, so the
        default "<acctType>.<acct>.<acctSub>" derivation naturally produces
        "<Member>.<acct>.<acctSub>".  That's exactly what we want — just
        delegate to the base class.  TOTAL row is detected as usual.
        '''
        return super()._default_rowNm(row, i)

    # ── UI conveniences (read-only) ──────────────────────────────────────────

    def last_summary(self) -> Dict[str, Any]:
        '''Summary captured at construction time.'''
        return dict(self._summary) if getattr(self, '_summary', None) else {}

    def stats(self) -> Dict[str, Any]:
        rows    = self.load()
        total   = next((r for r in rows if r.get('acctType') == 'TOTAL'), {})
        members = len({r['acctType'] for r in rows
                       if r.get('acctType') not in ('', 'TOTAL')})
        return {
            'Members':       members,
            'Total Balance': total.get('Balance', 0),
        }
