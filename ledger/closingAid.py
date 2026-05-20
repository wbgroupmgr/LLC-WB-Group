import math
from typing import Any, Dict, List, Optional

CAPITALIZE = 'Capitalize'
AMORTIZE   = 'Amortize'
EXPENSE    = 'Expense'


class ClosingBalanceError(ValueError):
    pass


# (keyword_lower, tax_bucket, acct) — first match wins
_RULES: List[tuple] = [
    ('sale price',              CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('contract sales price',    CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('title',                   CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('recording fee',           CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('recording charges',       CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('government recording',    CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('county tax',              CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('property tax',            CAPITALIZE, 'Acct.Fixed.Tangible.InService'),
    ('deposit or earnest',      CAPITALIZE, 'Acct.Cash.Bank'),
    ('earnest money',           CAPITALIZE, 'Acct.Cash.Bank'),
    ('option money',            CAPITALIZE, 'Acct.Equity.Owner.Capital.Funds'),
    ('cash to close',           CAPITALIZE, 'Acct.Cash.Bank'),
    ('balance due',             CAPITALIZE, 'Acct.Cash.Bank'),
    ('loan origination',        AMORTIZE,   'Acct.Liab.Morgage'),
    ('origination fee',         AMORTIZE,   'Acct.Liab.Morgage'),
    ('loan points',             AMORTIZE,   'Acct.Liab.Morgage'),
    ('appraisal fee',           AMORTIZE,   'Acct.Liab.Morgage'),
    ('hoa',                     EXPENSE,    'Acct.Exp.Operating'),
    ('homeowners association',  EXPENSE,    'Acct.Exp.Operating'),
]


def _is_null_amt(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    try:
        return float(v) == 0.0
    except Exception:
        return True


def _norm_dt(raw: str) -> str:
    if not raw:
        return raw
    return raw.replace('-', '.').replace('/', '.')


def _classify_one(row: Dict) -> Optional[Dict]:
    debit  = row.get('Debit')
    credit = row.get('Credit')
    if _is_null_amt(debit) and _is_null_amt(credit):
        return None
    if str(row.get('Description', '')).strip().lower() in ('totals', 'total'):
        return None

    aType = 'Debit' if not _is_null_amt(debit) else 'Credit'
    amt   = float(debit if aType == 'Debit' else credit)
    desc_lower = str(row.get('Description', '')).lower()

    for keyword, tax_bucket, acct in _RULES:
        if keyword in desc_lower:
            r = dict(row)
            r.update(acct=acct, Ledger=None, aType=aType, amt=amt, tax_bucket=tax_bucket)
            return r

    # Fallback: debits capitalize to property, credits reduce cash
    fallback = 'Acct.Fixed.Tangible.InService' if aType == 'Debit' else 'Acct.Cash.Bank'
    r = dict(row)
    r.update(acct=fallback, Ledger=None, aType=aType, amt=amt, tax_bucket=CAPITALIZE)
    return r


class ClosingAid:

    def classify(self, rows: List[Dict]) -> List[Dict]:
        """Map raw settlement rows to COA accounts with tax bucket classification."""
        result = []
        for row in rows:
            classified = _classify_one(row)
            if classified is not None:
                result.append(classified)
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
            raise ClosingBalanceError(
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
        asset_state = preface.get('assetState', '')
        asset_type  = preface.get('assetType', '')
        prop_owners = preface.get('propOwners', '')

        records = []
        for seq, row in enumerate(rows):
            tax_bucket = row.get('tax_bucket', CAPITALIZE)
            ref_doc    = f"{prop_nm}, Closing Docs, {tax_bucket}, {closing_doc}"
            tID        = f"{tID_prefix}_{seq + 1:02d}"

            record = {
                'tID':      tID,
                'oID':      tID_prefix,
                'dt':       dt,
                'acct':     row.get('acct', ''),
                'Ledger':   None,
                'aType':    row.get('aType', 'Debit'),
                'amt':      row.get('amt', 0.0),
                'desc':     str(row.get('Description', row.get('desc', ''))),
                'refDoc':   ref_doc,
                'propNm':   prop_nm,
                'propRef':  prop_addr,
                'acctSub':  asset_state,
                'assetType': asset_type,
                'propOwners': prop_owners,
                'tax_bucket': tax_bucket,
            }
            records.append(record)

        return records
