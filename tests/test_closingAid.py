"""
tests/test_closingAid.py — unit tests for ClosingAid + nan-Ledger GL fixes.

Run from the Notebooks directory:
    python -m tests.test_closingAid
"""
import math
import sys
import os
import unittest

# Ensure project root is on sys.path so ledger.* imports work.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from ledger.closingAid import (
    ClosingAid, ClosingBalanceError,
    CAPITALIZE, AMORTIZE, EXPENSE,
    _classify_one, _is_null_amt, _norm_dt,
)


# ---------------------------------------------------------------------------
# 1. ledgerDB.toGL — nan-Ledger should not produce a second GL row
# ---------------------------------------------------------------------------
class TestToGLNanLedger(unittest.TestCase):

    def _make_df(self, ledger_val):
        """Build a minimal DataFrame resembling what toGL() receives."""
        return pd.DataFrame([{
            'tID': 'p01_01', 'dt': '2025.08.20', 'acct': 'Acct.Fixed.Tangible.InService',
            'Ledger': ledger_val, 'aType': 'Debit', 'amt': 100.0, 'desc': 'test',
        }])

    def test_toGL_nan_ledger_single_entry(self):
        """A row with Ledger=NaN must produce exactly 1 GL row (no phantom ledger side)."""
        df = self._make_df(float('nan'))
        # Replicate the mask logic from ledgerDB.toGL
        _lmask = df['Ledger'].notna() & (df['Ledger'].astype(str).str.strip().str.lower() != 'nan')
        dfL = df[_lmask]
        self.assertEqual(len(dfL), 0, "dfL should be empty for NaN-Ledger rows")

    def test_toGL_real_ledger_two_entries(self):
        """A row with a valid Ledger must produce 1 dfL row (both sides post)."""
        df = self._make_df('Acct.Cash.Bank')
        _lmask = df['Ledger'].notna() & (df['Ledger'].astype(str).str.strip().str.lower() != 'nan')
        dfL = df[_lmask]
        self.assertEqual(len(dfL), 1)


# ---------------------------------------------------------------------------
# 2. stmtGL.toDoubleEntry — nan-Ledger hardening
# ---------------------------------------------------------------------------
class TestToDoubleEntryNanLedger(unittest.TestCase):

    def _hardened_ledger_acct(self, value):
        """Inline the hardened check from stmtGL.toDoubleEntry."""
        _lv = value
        return (
            '' if (_lv is None or (isinstance(_lv, float) and _lv != _lv)
                   or str(_lv).strip().lower() == 'nan')
            else str(_lv).strip()
        )

    def test_toDoubleEntry_nan_float(self):
        self.assertEqual(self._hardened_ledger_acct(float('nan')), '')

    def test_toDoubleEntry_none(self):
        self.assertEqual(self._hardened_ledger_acct(None), '')

    def test_toDoubleEntry_string_nan(self):
        self.assertEqual(self._hardened_ledger_acct('nan'), '')

    def test_toDoubleEntry_valid(self):
        self.assertEqual(self._hardened_ledger_acct('Acct.Cash.Bank'), 'Acct.Cash.Bank')


# ---------------------------------------------------------------------------
# 3. ClosingAid.classify — COA account assignment
# ---------------------------------------------------------------------------
class TestClassify(unittest.TestCase):

    def setUp(self):
        self.aid = ClosingAid()

    def test_classify_assigns_coa(self):
        rows = [{'Description': 'Contract Sales Price', 'Debit': 300000, 'Credit': None}]
        result = self.aid.classify(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['acct'], 'Acct.Fixed.Tangible.InService')
        self.assertEqual(result[0]['aType'], 'Debit')
        self.assertAlmostEqual(result[0]['amt'], 300000.0)

    def test_classify_skips_null_and_totals(self):
        rows = [
            {'Description': 'Totals', 'Debit': 1000, 'Credit': None},
            {'Description': 'A line', 'Debit': None,  'Credit': None},
        ]
        result = self.aid.classify(rows)
        self.assertEqual(len(result), 0)

    def test_classify_three_buckets(self):
        rows = [
            {'Description': 'Contract Sales Price',  'Debit': 300000, 'Credit': None},
            {'Description': 'Loan Origination Fee',  'Debit': 2000,   'Credit': None},
            {'Description': 'HOA Transfer Fee',      'Debit': 200,    'Credit': None},
        ]
        result = self.aid.classify(rows)
        buckets = {r['Description']: r['tax_bucket'] for r in result}
        self.assertEqual(buckets['Contract Sales Price'], CAPITALIZE)
        self.assertEqual(buckets['Loan Origination Fee'], AMORTIZE)
        self.assertEqual(buckets['HOA Transfer Fee'],     EXPENSE)

    def test_classify_ledger_is_none(self):
        rows = [{'Description': 'Title Insurance', 'Debit': 1500, 'Credit': None}]
        result = self.aid.classify(rows)
        self.assertIsNone(result[0]['Ledger'])

    def test_classify_buyer_seller_columns(self):
        # ALTA title-company format: Buyer = Dr (charge to buyer), Seller = Cr (credit to buyer)
        rows = [
            {'Description': 'Sale Price of Property',            'Buyer': 220000.0, 'Seller': None},
            {'Description': 'Deposit or Earnest Money',          'Buyer': None,     'Seller': 5000.0},
            {'Description': 'County taxes proration',            'Buyer': None,     'Seller': 1660.64},
            {'Description': 'Title - Settlement or closing fee', 'Buyer': 625.0,    'Seller': None},
            {'Description': 'HOA Transfer Fees',                 'Buyer': 100.0,    'Seller': None},
            {'Description': 'Totals',                            'Buyer': 1234.0,   'Seller': 1234.0},
        ]
        result = self.aid.classify(rows)
        self.assertEqual(len(result), 5)           # Totals skipped
        by_desc = {r['Description']: r for r in result}
        # Buyer column → Debit
        self.assertEqual(by_desc['Sale Price of Property']['aType'], 'Debit')
        self.assertAlmostEqual(by_desc['Sale Price of Property']['amt'], 220000.0)
        self.assertEqual(by_desc['Sale Price of Property']['acct'], 'Acct.Fixed.Tangible.InService')
        # Seller column → Credit; deposit flows through escrow → Owner Capital (not bank)
        self.assertEqual(by_desc['Deposit or Earnest Money']['aType'], 'Credit')
        self.assertAlmostEqual(by_desc['Deposit or Earnest Money']['amt'], 5000.0)
        self.assertEqual(by_desc['Deposit or Earnest Money']['acct'], 'Acct.Equity.Owner.Capital.Funds')
        # Tax proration (Seller → Credit, Capitalize to basis)
        self.assertEqual(by_desc['County taxes proration']['aType'], 'Credit')
        self.assertEqual(by_desc['County taxes proration']['acct'], 'Acct.Fixed.Tangible.InService')
        # HOA fees (Buyer → Debit, Expense bucket)
        self.assertEqual(by_desc['HOA Transfer Fees']['tax_bucket'], EXPENSE)


# ---------------------------------------------------------------------------
# 4. ClosingAid.toBalanceSheet
# ---------------------------------------------------------------------------
class TestBalanceSheet(unittest.TestCase):

    def setUp(self):
        self.aid = ClosingAid()

    def _make_rows(self):
        return [
            {'aType': 'Debit',  'amt': 303700.0, 'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
            {'aType': 'Credit', 'amt': 220000.0, 'acct': 'Acct.Liab.Morgage',             'tax_bucket': AMORTIZE},
            {'aType': 'Credit', 'amt': 83700.0,  'acct': 'Acct.Cash.Bank',                'tax_bucket': CAPITALIZE},
        ]

    def test_balance_sheet_balanced(self):
        result = self.aid.toBalanceSheet(self._make_rows())
        self.assertTrue(result['balanced'])
        self.assertAlmostEqual(result['total_debits'],  303700.0)
        self.assertAlmostEqual(result['total_credits'], 303700.0)

    def test_balance_sheet_unbalanced(self):
        rows = self._make_rows()
        rows[0]['amt'] = 999.0   # break the balance
        result = self.aid.toBalanceSheet(rows)
        self.assertFalse(result['balanced'])


# ---------------------------------------------------------------------------
# 5. ClosingAid.propertyBasis
# ---------------------------------------------------------------------------
class TestPropertyBasis(unittest.TestCase):

    def setUp(self):
        self.aid = ClosingAid()

    def test_property_basis_components(self):
        classified = [
            {'aType': 'Debit',  'amt': 300000.0, 'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
            {'aType': 'Debit',  'amt': 1500.0,   'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
            {'aType': 'Debit',  'amt': 2000.0,   'acct': 'Acct.Liab.Morgage',             'tax_bucket': AMORTIZE},
            {'aType': 'Credit', 'amt': 100.0,    'acct': 'Acct.Cash.Bank',                'tax_bucket': CAPITALIZE},
        ]
        result = self.aid.propertyBasis(classified)
        # Only Capitalize+Debit rows count toward basis
        self.assertAlmostEqual(result['gross_basis'], 301500.0)
        self.assertEqual(len(result['basis_rows']), 2)


# ---------------------------------------------------------------------------
# 6. ClosingAid.toAssetRecords — schema & naming
# ---------------------------------------------------------------------------
class TestToAssetRecords(unittest.TestCase):

    def setUp(self):
        self.aid = ClosingAid()
        self._classified = [
            {'Description': 'Contract Sales Price', 'aType': 'Debit',  'amt': 250000.0,
             'acct': 'Acct.Fixed.Tangible.InService', 'Ledger': None, 'tax_bucket': CAPITALIZE},
            {'Description': 'Cash To Close',        'aType': 'Credit', 'amt': 250000.0,
             'acct': 'Acct.Cash.Bank',               'Ledger': None, 'tax_bucket': CAPITALIZE},
        ]
        self._preface = {
            'propNm':      'H_805HighMesa',
            'propAddr':    '805 High Mesa Dr',
            'closingDate': '2025-08-26',
            'closingDoc':  'ALTA_2025.pdf',
            'tID_Prefix':  'p20250826-Mesa',
            'assetType':   'Residential',
            'assetState':  'InService',
            'propOwners':  'Member A',
            'landPct':     0,
        }

    def test_to_asset_records_schema(self):
        records = self.aid.toAssetRecords(self._classified, self._preface)
        required = {'tID', 'dt', 'acct', 'Ledger', 'aType', 'amt', 'desc', 'refDoc', 'propNm', 'tax_bucket'}
        for rec in records:
            self.assertTrue(required.issubset(rec.keys()), f"Missing keys in {rec}")

    def test_to_asset_records_tid_prefix(self):
        records = self.aid.toAssetRecords(self._classified, self._preface)
        self.assertEqual(records[0]['tID'], 'p20250826-Mesa_01')
        self.assertEqual(records[1]['tID'], 'p20250826-Mesa_02')

    def test_to_asset_records_refDoc_has_bucket(self):
        records = self.aid.toAssetRecords(self._classified, self._preface)
        for rec in records:
            self.assertIn(rec['tax_bucket'], rec['refDoc'])
            self.assertIn('H_805HighMesa', rec['refDoc'])
            self.assertIn('ALTA_2025.pdf', rec['refDoc'])

    def test_to_asset_records_ledger_is_none(self):
        records = self.aid.toAssetRecords(self._classified, self._preface)
        for rec in records:
            self.assertIsNone(rec['Ledger'])

    def test_to_asset_records_raises_on_imbalance(self):
        bad = [self._classified[0]]   # debit only, no credit
        with self.assertRaises(ClosingBalanceError):
            self.aid.toAssetRecords(bad, self._preface)


# ---------------------------------------------------------------------------
# 7. ClosingAid._apply_land_split
# ---------------------------------------------------------------------------
class TestLandSplit(unittest.TestCase):

    def setUp(self):
        self.aid = ClosingAid()
        self._rows = [
            {'aType': 'Debit',  'amt': 200000.0, 'acct': 'Acct.Fixed.Tangible.InService',
             'tax_bucket': CAPITALIZE, 'Description': 'Purchase Price'},
            {'aType': 'Credit', 'amt': 200000.0, 'acct': 'Acct.Cash.Bank',
             'tax_bucket': CAPITALIZE, 'Description': 'Cash To Close'},
        ]

    def test_land_split_two_records(self):
        result = self.aid._apply_land_split(self._rows, land_pct=20.0)
        accts = [r['acct'] for r in result]
        self.assertIn('Acct.Fixed.Land',                 accts)
        self.assertIn('Acct.Fixed.Tangible.InService',   accts)
        # Credit row passes through unchanged
        credit_rows = [r for r in result if r['aType'] == 'Credit']
        self.assertEqual(len(credit_rows), 1)

    def test_land_split_amounts(self):
        result = self.aid._apply_land_split(self._rows, land_pct=20.0)
        land = next(r for r in result if r['acct'] == 'Acct.Fixed.Land')
        bldg = next(r for r in result if r['acct'] == 'Acct.Fixed.Tangible.InService')
        self.assertAlmostEqual(land['amt'], 40000.0)
        self.assertAlmostEqual(bldg['amt'], 160000.0)

    def test_land_split_zero_pct_passthrough(self):
        result = self.aid._apply_land_split(self._rows, land_pct=0)
        self.assertEqual(result, self._rows)


# ---------------------------------------------------------------------------
# 8. ClosingAid.balance_assist
# ---------------------------------------------------------------------------
class TestBalanceAssist(unittest.TestCase):

    def setUp(self):
        self.aid = ClosingAid()
        # Unbalanced closing: 300k debit, only 80k credit
        self._classified = [
            {'aType': 'Debit',  'amt': 300000.0, 'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
            {'aType': 'Credit', 'amt': 80000.0,  'acct': 'Acct.Cash.Bank',                'tax_bucket': CAPITALIZE},
        ]
        # GL rows: two capital contributions before closing, one after
        self._gl_rows = [
            {'dt': '2025.07.01', 'desc': 'Member A contribution', 'acct': 'Acct.Equity.Owner.Capital.Funds', 'Ledger': None,               'aType': 'Credit', 'amt': 150000.0},
            {'dt': '2025.07.15', 'desc': 'Member B contribution', 'acct': 'Acct.Cash.Bank',                  'Ledger': 'Acct.Equity.Owner.Capital.Funds', 'aType': 'Debit',  'amt': 100000.0},
            {'dt': '2025.09.01', 'desc': 'Post-closing capital',  'acct': 'Acct.Equity.Owner.Capital.Funds', 'Ledger': None,               'aType': 'Credit', 'amt': 50000.0},
        ]
        self._closing_date = '2025-08-26'

    def test_balanced_returns_context(self):
        # When balanced, balance_assist still returns gl_context for the funding chain display
        balanced = [
            {'aType': 'Debit',  'amt': 100.0, 'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
            {'aType': 'Credit', 'amt': 100.0, 'acct': 'Acct.Cash.Bank',                'tax_bucket': CAPITALIZE},
        ]
        result = self.aid.balance_assist(balanced, self._closing_date, self._gl_rows)
        self.assertTrue(result['balanced'])
        self.assertEqual(result['delta'], 0)
        self.assertIn('gl_context', result)    # always present now
        self.assertIn('total_funded', result)

    def test_unbalanced_returns_context(self):
        result = self.aid.balance_assist(self._classified, self._closing_date, self._gl_rows)
        self.assertFalse(result['balanced'])
        self.assertAlmostEqual(result['delta'], 220000.0)   # 300k - 80k

    def test_gl_context_excludes_post_closing(self):
        result = self.aid.balance_assist(self._classified, self._closing_date, self._gl_rows)
        # Post-closing row (2025.09.01) must be excluded
        dates = [r['dt'] for r in result['gl_context']]
        self.assertNotIn('2025.09.01', dates)
        self.assertEqual(len(result['gl_context']), 2)

    def test_total_funded(self):
        result = self.aid.balance_assist(self._classified, self._closing_date, self._gl_rows)
        self.assertAlmostEqual(result['total_funded'], 250000.0)  # 150k + 100k

    def test_covers_delta(self):
        result = self.aid.balance_assist(self._classified, self._closing_date, self._gl_rows)
        # 250k funded >= 220k delta
        self.assertTrue(result['covers_delta'])

    def test_suggestion_is_credit_when_debits_exceed(self):
        result = self.aid.balance_assist(self._classified, self._closing_date, self._gl_rows)
        s = result['suggestion']
        self.assertIsNotNone(s)
        self.assertEqual(s['aType'], 'Credit')
        self.assertAlmostEqual(s['amt'], 220000.0)
        self.assertEqual(s['acct'], 'Acct.Cash.Bank')

    def test_suggestion_is_debit_when_credits_exceed(self):
        flipped = [
            {'aType': 'Credit', 'amt': 300000.0, 'acct': 'Acct.Cash.Bank',                'tax_bucket': CAPITALIZE},
            {'aType': 'Debit',  'amt': 80000.0,  'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
        ]
        result = self.aid.balance_assist(flipped, self._closing_date, self._gl_rows)
        s = result['suggestion']
        self.assertIsNotNone(s)
        self.assertEqual(s['aType'], 'Debit')
        self.assertAlmostEqual(s['amt'], 220000.0)

    def test_no_suggestion_when_within_tolerance(self):
        # delta=0.01 is within the $0.02 tolerance → treated as balanced → no suggestion key
        nearly = [
            {'aType': 'Debit',  'amt': 100.00, 'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
            {'aType': 'Credit', 'amt': 99.99,  'acct': 'Acct.Cash.Bank',                'tax_bucket': CAPITALIZE},
        ]
        result = self.aid.balance_assist(nearly, self._closing_date, [])
        self.assertTrue(result['balanced'])
        self.assertNotIn('suggestion', result)


# ---------------------------------------------------------------------------
# 9. ClosingAid.check_existing
# ---------------------------------------------------------------------------
class TestCheckExisting(unittest.TestCase):

    def setUp(self):
        self.aid = ClosingAid()
        self._closing_date = '2025-08-26'
        self._classified = [
            {'_row_idx': 1, 'aType': 'Debit',  'amt': 220000.0, 'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
            {'_row_idx': 2, 'aType': 'Credit', 'amt': 5000.0,   'acct': 'Acct.Equity.Owner.Capital.Funds', 'tax_bucket': CAPITALIZE},
            {'_row_idx': 3, 'aType': 'Credit', 'amt': 625.0,    'acct': 'Acct.Fixed.Tangible.InService', 'tax_bucket': CAPITALIZE},
        ]
        self._gl_rows = [
            {'tID': 'r20250825_01', 'dt': '2025.08.25', 'aType': 'Debit',  'amt': 220000.0, 'acct': 'Acct.Fixed.Tangible.InService', 'desc': 'Sale Price existing'},
            {'tID': 'r20250101_01', 'dt': '2025.01.01', 'aType': 'Debit',  'amt': 1000.0,   'acct': 'Acct.Exp.Operating',            'desc': 'Unrelated expense'},
            {'tID': 'r20240101_01', 'dt': '2024.01.01', 'aType': 'Debit',  'amt': 220000.0, 'acct': 'Acct.Fixed.Tangible.InService', 'desc': 'Prior year — excluded'},
        ]

    def test_finds_same_year_match(self):
        matches = self.aid.check_existing(self._classified, self._closing_date, self._gl_rows)
        row_indices = [m['_row_idx'] for m in matches]
        self.assertIn(1, row_indices)  # $220k Debit matches

    def test_excludes_different_year(self):
        matches = self.aid.check_existing(self._classified, self._closing_date, self._gl_rows)
        # The 2024 row must not be returned as a candidate
        for m in matches:
            for c in m['candidates']:
                self.assertNotEqual(c['tID'], 'r20240101_01')

    def test_no_false_positive_on_different_atype(self):
        matches = self.aid.check_existing(self._classified, self._closing_date, self._gl_rows)
        # Row 2 ($5000 Credit) has no GL match → not flagged
        row_indices = [m['_row_idx'] for m in matches]
        self.assertNotIn(2, row_indices)

    def test_candidate_fields_present(self):
        matches = self.aid.check_existing(self._classified, self._closing_date, self._gl_rows)
        self.assertTrue(len(matches) > 0)
        c = matches[0]['candidates'][0]
        for field in ('tID', 'dt', 'desc', 'acct'):
            self.assertIn(field, c)

    def test_empty_gl_returns_no_matches(self):
        matches = self.aid.check_existing(self._classified, self._closing_date, [])
        self.assertEqual(matches, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
