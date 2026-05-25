import math
from typing import Any, Dict, List, Optional

CAPITALIZE = 'Capitalize'
AMORTIZE   = 'Amortize'
EXPENSE    = 'Expense'


class PropAgentBalanceError(ValueError):
    pass


# Accounts that are typically unique per closing — flag any same-acct+aType in same year
_UNIQUE_CLOSING_ACCTS = frozenset({
    'Acct.Fixed.Tangible.InService',
    'Acct.Fixed.Land',
    'Acct.Liab.Morgage',
})


# (keyword_lower, tax_bucket, acct) — first match wins.
# More specific keywords must come BEFORE broader ones (e.g. 'settlement or closing fee' before 'title').
# Validated against 805 High Mesa ALTA statement (20250820-ClosingToLedger.ipynb ccDict).
_RULES: List[tuple] = [

    # ── Purchase Price ─────────────────────────────────────────────────────────
    ('sale price',                CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('contract sales price',      CAPITALIZE, 'Acct.Fixed.Tangible.InService'),

    # ── Title / Closing / Settlement Fees ──────────────────────────────────────
    # More specific variants before the broad 'title' catch-all
    ('settlement or closing fee', CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('closing fee',               CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('settlement fee',            CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('title',                     CAPITALIZE, 'Acct.Fixed.Tangible.InService'),

    # ── Recording / E-Recording ────────────────────────────────────────────────
    # 'e-recording' before 'recording fee' — "e-recording service fee" ≠ "recording fee"
    ('e-recording',               CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('recording fee',             CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('recording charges',         CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('government recording',      CAPITALIZE, 'Acct.Fixed.Tangible.InService'),

    # ── Taxes & Prorations ─────────────────────────────────────────────────────
    # Transfer tax: buyer's cost → capitalise into basis (IRS Pub 551)
    ('transfer tax',              CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    # County/property tax proration: capitalised into acquisition cost
    ('county tax',                CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('property tax',              CAPITALIZE, 'Acct.Fixed.Tangible.InService'),

    # ── Deposits & Cash Funding ────────────────────────────────────────────────
    # Earnest/deposit/option: buyer paid before closing (out-of-pocket capital contribution).
    ('deposit or earnest',        CAPITALIZE, 'Acct.Equity.Owner.Capital.Funds'),
    ('earnest money',             CAPITALIZE, 'Acct.Equity.Owner.Capital.Funds'),
    ('option money',              CAPITALIZE, 'Acct.Equity.Owner.Capital.Funds'),
    ('cash to close',             CAPITALIZE, 'Acct.Cash.Bank'),
    ('balance due',               CAPITALIZE, 'Acct.Cash.Bank'),

    # ── Mortgage / New Loan Principal (Credit — lender funds purchase) ─────────
    # 'principal amount' and 'new loan' before 'loan origination' to avoid mis-match
    ('principal amount',          AMORTIZE,   'Acct.Liab.Morgage'),
    ('new loan',                  AMORTIZE,   'Acct.Liab.Morgage'),
    ('loan origination',          AMORTIZE,   'Acct.Liab.Morgage'),
    ('origination fee',           AMORTIZE,   'Acct.Liab.Morgage'),
    ('loan points',               AMORTIZE,   'Acct.Liab.Morgage'),
    ('appraisal fee',             AMORTIZE,   'Acct.Liab.Morgage'),

    # ── Other Capitalized Acquisition Costs (IRS Pub 551) ─────────────────────
    ('survey',                    CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('notary',                    CAPITALIZE, 'Acct.Fixed.Tangible.InService'),

    # ── Bill of Sale — Personal Property (RV, vehicle, equipment) ─────────────
    # Sales tax and registration fees are part of cost basis (IRS Pub 551)
    ('vehicle purchase price',    CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('purchase price',            CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('sales tax',                 CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('registration fee',          CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('title fee',                 CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('delivery fee',              CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('transport fee',             CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('bill of sale',              CAPITALIZE, 'Acct.Fixed.Tangible.InService'),

    # ── HOA & Immediate Expenses ───────────────────────────────────────────────
    # 'hoa' catches "HOA Transfer Fees"; 'homeowners association' catches spelled-out dues
    ('hoa',                       EXPENSE,    'Acct.Exp.Operating'),
    ('homeowners association',    EXPENSE,    'Acct.Exp.Operating'),
    ('home warranty',             EXPENSE,    'Acct.Exp.Operating'),
    ('inspection',                EXPENSE,    'Acct.Exp.Operating'),
    ('wire fee',                  EXPENSE,    'Acct.Exp.Operating'),
    ('insurance',                 EXPENSE,    'Acct.Exp.Operating'),  # first-year premium
]


def _compute_depreciation(bldg_amt: float, closing_date_str: str,
                          useful_life: float = 27.5) -> Dict:
    """MACRS straight-line, mid-month convention for residential real property."""
    try:
        s = str(closing_date_str or '').strip().replace('.', '-').replace('/', '-')
        month = int(s.split('-')[1])
        assert 1 <= month <= 12
    except Exception:
        return {}
    full_year         = round(bldg_amt / useful_life, 2)
    months_in_service = round(12.0 - month + 0.5, 1)   # mid-month: placed in service mid-M
    return {
        'depr_full_year':    full_year,
        'depr_ytd':          round(full_year * months_in_service / 12.0, 2),
        'months_in_service': months_in_service,
        'closing_month':     month,
        'useful_life':       useful_life,
        'depr_method':       f'MACRS SL Mid-Month ({useful_life}yr Residential)',
    }


def _parse_amt(v) -> Optional[float]:
    """Parse an amount value that may be a currency-formatted string like '$300,000'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = str(v).strip().replace('$', '').replace(',', '').replace(' ', '')
    if not s or s == '-':
        return None
    if s.startswith('(') and s.endswith(')'):  # accounting negative: (1,234.56)
        s = '-' + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _is_null_amt(v) -> bool:
    parsed = _parse_amt(v)
    return parsed is None or parsed == 0.0


def _norm_dt(raw: str) -> str:
    if not raw:
        return raw
    return raw.replace('-', '.').replace('/', '.')


def _classify_one(row: Dict, extra_rules: Optional[List[tuple]] = None) -> Optional[Dict]:
    # Auto-detect column format: ALTA title-company (Buyer/Seller) or standard (Debit/Credit).
    # Buyer = charges TO the buyer (DR in LLC books); Seller = credits TO the buyer (CR in LLC books).
    if 'Buyer' in row or 'Seller' in row:
        debit  = _parse_amt(row.get('Buyer'))
        credit = _parse_amt(row.get('Seller'))
    else:
        debit  = _parse_amt(row.get('Debit'))
        credit = _parse_amt(row.get('Credit'))
    if _is_null_amt(debit) and _is_null_amt(credit):
        return None
    if str(row.get('Description', '')).strip().lower() in ('totals', 'total'):
        return None

    aType = 'Debit' if not _is_null_amt(debit) else 'Credit'
    amt   = debit if aType == 'Debit' else credit
    desc_lower = str(row.get('Description', '')).lower()

    # Session rules take priority over built-in rules
    all_rules = list(extra_rules or []) + _RULES
    for keyword, tax_bucket, acct in all_rules:
        if keyword in desc_lower:
            r = dict(row)
            r.update(acct=acct, Ledger=None, aType=aType, amt=amt,
                     tax_bucket=tax_bucket, _matched=True)
            return r

    # No rule matched — use fallback but flag for user review
    fallback = 'Acct.Fixed.Tangible.InService' if aType == 'Debit' else 'Acct.Cash.Bank'
    r = dict(row)
    r.update(acct=fallback, Ledger=None, aType=aType, amt=amt,
             tax_bucket=CAPITALIZE, _matched=False)
    return r


class PropAgent:

    def classify(self, rows: List[Dict],
                 session_rules: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Map raw settlement rows to COA accounts. Sets _matched=False on rows with no rule.
        session_rules: [{keyword, tax_bucket, acct}] prepended before _RULES (highest priority).
        """
        extra: List[tuple] = []
        if session_rules:
            for sr in session_rules:
                kw = str(sr.get('keyword', '')).strip().lower()
                tb = str(sr.get('tax_bucket', CAPITALIZE))
                ac = str(sr.get('acct', 'Acct.Fixed.Tangible.InService'))
                if kw:
                    extra.append((kw, tb, ac))

        result = []
        for i, row in enumerate(rows):
            try:
                classified = _classify_one(row, extra_rules=extra)
                if classified is not None:
                    classified['_row_idx'] = i + 1
                    result.append(classified)
            except Exception as e:
                desc = str(row.get('Description', '?'))[:40]
                raise ValueError(f"Line {i + 1} — '{desc}': {e}") from e
        return result

    def toBalanceSheet(self, classified: List[Dict]) -> Dict:
        """Return debit/credit totals and balanced status."""
        debits  = sum(r['amt'] for r in classified if r.get('aType') == 'Debit')
        credits = sum(r['amt'] for r in classified if r.get('aType') == 'Credit')
        return {
            'total_debits':  round(debits, 2),
            'total_credits': round(credits, 2),
            'balanced':      round(abs(debits - credits), 2) < 0.02,
            'delta':         round(debits - credits, 2),
        }

    def propertyBasis(self, classified: List[Dict]) -> Dict:
        """Sum all Capitalize+Debit rows to determine gross property basis."""
        basis_rows = [
            r for r in classified
            if r.get('tax_bucket') == CAPITALIZE and r.get('aType') == 'Debit'
        ]
        gross = sum(r['amt'] for r in basis_rows)
        return {
            'gross_basis':  round(gross, 2),
            'basis_rows':   basis_rows,
        }

    def depreciationEstimate(self, bldg_amt: float, closing_date: str,
                             useful_life: float = 27.5) -> Dict:
        """MACRS mid-month depreciation estimate for the building portion."""
        if not bldg_amt or bldg_amt <= 0:
            return {}
        return _compute_depreciation(bldg_amt, closing_date, useful_life)

    def _apply_land_split(self, classified: List[Dict], land_pct: float) -> List[Dict]:
        """
        Replace Capitalize+Debit+InService rows with two rows:
          - Acct.Fixed.Land         (land_pct %)
          - Acct.Fixed.Tangible.InService  (remaining %)
        All other rows pass through unchanged.
        """
        if not land_pct or land_pct <= 0:
            return classified

        inservice_acct = 'Acct.Fixed.Tangible.InService'
        land_acct      = 'Acct.Fixed.Land'

        # Rows subject to split
        split_rows  = [
            r for r in classified
            if r.get('tax_bucket') == CAPITALIZE
            and r.get('aType') == 'Debit'
            and r.get('acct') == inservice_acct
        ]
        other_rows  = [
            r for r in classified
            if not (r.get('tax_bucket') == CAPITALIZE
                    and r.get('aType') == 'Debit'
                    and r.get('acct') == inservice_acct)
        ]

        total_basis = sum(r['amt'] for r in split_rows)
        land_amt    = round(total_basis * land_pct / 100.0, 2)
        bldg_amt    = round(total_basis - land_amt, 2)

        # Use first split row as template for description/metadata
        template = dict(split_rows[0]) if split_rows else {}
        orig_desc = template.get('Description', template.get('desc', 'Property Acquisition'))

        land_row = dict(template)
        land_row.update(
            acct=land_acct,
            Ledger=None,
            aType='Debit',
            amt=land_amt,
            tax_bucket=CAPITALIZE,
            Description=f'{orig_desc} — Land',
        )

        bldg_row = dict(template)
        bldg_row.update(
            acct=inservice_acct,
            Ledger=None,
            aType='Debit',
            amt=bldg_amt,
            tax_bucket=CAPITALIZE,
            Description=f'{orig_desc} — Building',
        )

        return other_rows + [land_row, bldg_row]

    def toAssetRecords(self, classified: List[Dict], preface: Dict) -> List[Dict]:
        """
        Convert classified closing rows + preface fields into llcAssets-compatible records.
        Applies land split when preface['landPct'] > 0.
        """
        bs = self.toBalanceSheet(classified)
        if not bs['balanced']:
            raise PropAgentBalanceError(
                f"Closing journal is not balanced — debits={bs['total_debits']}, "
                f"credits={bs['total_credits']}, delta={bs['delta']}"
            )

        land_pct = float(preface.get('landPct') or 0)
        rows = self._apply_land_split(classified, land_pct)

        dt         = _norm_dt(preface.get('closingDate', ''))
        closing_doc = preface.get('closingDoc', '')
        prop_nm    = preface.get('propNm', '')
        prop_addr  = preface.get('propAddr', '')
        tID_prefix = preface.get('tID_Prefix', 'closing')
        acct_sub    = preface.get('acctSub',    'Closing')   # BS grouping key
        asset_state = preface.get('assetState', 'InService') # operational lifecycle
        asset_type  = preface.get('assetType', '')
        prop_owners = preface.get('propOwners', '')
        ref_db      = preface.get('refDB', 'propAgent')

        records = []
        for seq, row in enumerate(rows):
            tax_bucket = row.get('tax_bucket', CAPITALIZE)
            ref_doc    = f"{prop_nm}, Closing Docs, {tax_bucket}, {closing_doc}"
            tID        = f"{tID_prefix}_{seq + 1:02d}"

            desc_raw = str(row.get('Description', row.get('desc', '')))
            record = {
                'tID':        tID,
                'propID':     tID,
                '_row_idx':   seq + 1,       # 1-based index used by preview + dup detection
                'dt':         dt,
                'acct':       row.get('acct', ''),
                'Ledger':     'Acct.Cash.Escrow',  # clears through escrow holding; net must be zero before commit
                'aType':      row.get('aType', 'Debit'),
                'amt':        row.get('amt', 0.0),
                'desc':       f"Purchase Property: {desc_raw}" if desc_raw else 'Purchase Property',
                'refDoc':     ref_doc,
                'refDB':      ref_db,
                'tDB':        'llcAssets',
                'propNm':     prop_nm,
                'propAddr':   prop_addr,
                'acctSub':    acct_sub,
                'assetState': asset_state,
                'assetType':  asset_type,
                'propOwners': prop_owners,
                'tax_bucket': tax_bucket,
            }
            records.append(record)

        return records

    def balance_assist(self, classified: List[Dict],
                       closing_date: str,
                       gl_rows: List[Dict]) -> Dict:
        """
        Search GL for capital-contribution funding context and (when unbalanced)
        suggest a single balancing entry.  Always returns gl_context so Step 3
        can show the funding chain even after the journal is balanced.
        """
        bs         = self.toBalanceSheet(classified)
        delta      = round(bs['delta'], 2)
        closing_dt = _norm_dt(closing_date) if closing_date else '9999.99.99'

        context = []
        for row in gl_rows:
            row_dt = _norm_dt(str(row.get('dt', '') or ''))
            if row_dt > closing_dt:
                continue
            acct   = str(row.get('acct',   '') or '')
            ledger = str(row.get('Ledger', '') or '')
            atype  = str(row.get('aType',  '') or '')
            amt    = _parse_amt(row.get('amt'))
            if not amt or amt <= 0:
                continue
            desc = str(row.get('desc', '') or '')
            # Capital contribution: acct=*Capital* CR  |  Dual: Ledger=*Capital* DR
            is_capital = (('Capital' in acct and atype == 'Credit') or
                          ('Capital' in ledger and atype == 'Debit'))
            if is_capital:
                context.append({
                    'dt':    str(row.get('dt', '')),
                    'desc':  desc[:60],
                    'acct':  acct,
                    'aType': atype,
                    'amt':   round(amt, 2),
                })

        context.sort(key=lambda r: str(r.get('dt', '')), reverse=True)
        context = context[:15]
        total_funded = round(sum(r['amt'] for r in context), 2)

        if bs['balanced']:
            return {
                'balanced':     True,
                'delta':        0,
                'gl_context':   context,
                'total_funded': total_funded,
                'covers_delta': True,
            }

        need_credit = delta > 0
        suggestion = {
            'Description': 'Cash to Close',
            'aType':       'Credit' if need_credit else 'Debit',
            'acct':        'Acct.Cash.Bank' if need_credit else 'Acct.Fixed.Tangible.InService',
            'amt':         round(abs(delta), 2),
            'tax_bucket':  CAPITALIZE,
            'Ledger':      None,
            '_matched':    True,
        } if abs(delta) > 0.02 else None

        return {
            'balanced':     False,
            'delta':        delta,
            'need_credit':  need_credit,
            'gl_context':   context,
            'total_funded': total_funded,
            'covers_delta': total_funded >= abs(delta) - 0.02,
            'suggestion':   suggestion,
        }

    def check_existing(self, classified: List[Dict], closing_date: str,
                       gl_rows: List[Dict]) -> List[Dict]:
        """
        Flag classified rows that may already exist in the GL.
        Two matching strategies (within same calendar year as closing):
          1. Exact  : aType + amt match (catches different-account dupes)
          2. Unique : for Acct.Fixed.*/Acct.Liab.Morgage, same acct+aType any amount
                      (catches re-entries at slightly different amounts, e.g. $220k vs $213k)
        Returns [{_row_idx, candidates: [{tID, dt, desc, acct}]}].
        """
        closing_dt   = _norm_dt(closing_date) if closing_date else ''
        closing_year = closing_dt[:4] if len(closing_dt) >= 4 else ''

        amt_idx:  Dict[tuple, List[Dict]] = {}   # (aType, rounded_amt) → entries
        acct_idx: Dict[tuple, List[Dict]] = {}   # (aType, acct) → entries (unique accts only)

        for gl in gl_rows:
            gl_amt   = _parse_amt(gl.get('amt'))
            if not gl_amt or gl_amt <= 0:
                continue
            gl_atype = str(gl.get('aType', '') or '')
            gl_acct  = str(gl.get('acct',  '') or '')
            gl_dt    = _norm_dt(str(gl.get('dt', '') or ''))
            if closing_year and gl_dt[:4] != closing_year:
                continue
            entry = {
                'tID':  str(gl.get('tID', '') or ''),
                'dt':   str(gl.get('dt', '')),
                'desc': str(gl.get('desc', '') or '')[:60],
                'acct': gl_acct,
            }
            amt_idx.setdefault((gl_atype, round(gl_amt, 2)), []).append(entry)
            if gl_acct in _UNIQUE_CLOSING_ACCTS:
                acct_idx.setdefault((gl_atype, gl_acct), []).append(entry)

        matches = []
        for row in classified:
            amt   = round(row.get('amt') or 0, 2)
            atype = str(row.get('aType', '') or '')
            acct  = str(row.get('acct',  '') or '')

            candidates = list(amt_idx.get((atype, amt), [])[:3])
            if not candidates and acct in _UNIQUE_CLOSING_ACCTS:
                candidates = list(acct_idx.get((atype, acct), [])[:3])

            if candidates:
                matches.append({
                    '_row_idx':   row.get('_row_idx'),
                    'candidates': candidates,
                })
        return matches
