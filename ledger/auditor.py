'''
ledger.auditor — GL Audit Engine.

Per design_LLC_Accounting-SOP.md §2.3, the Auditor reviews the GL and
flags issues, then proposes corrective actions for the operator to approve.

Checks:
  TB_IMBALANCE   — Σ Debit ≠ Σ Credit in the Trial Balance
  DUP_TXN        — rows flagged ⚠ Dup (same tID across multiple source DBs)
  ZERO_AMT       — non-COA rows with amt = 0 (template/null entries)
  UNCLASSIFIED   — acctType empty or not in the 5 standard types
  BAD_ACCT_TYPE  — acctType present but not in {Asset,Liability,Equity,Income,Expense}
  SINGLE_SIDE    — an account has entries on only one side (Debit-only or Credit-only)
'''

from __future__ import annotations

import importlib
from collections import defaultdict
from typing import Any, Dict, List

_KNOWN_TYPES = {'Asset', 'Liability', 'Equity', 'Income', 'Expense'}

# Map refDB string → fully-qualified class path for load()/save()
_REFDB_CLASS: Dict[str, str] = {
    'llcExpRev':      'ledger.llcExpRev.llcExpRev',
    'llcAssets':      'ledger.llcAssets.llcAssets',
    'llcPayables':    'ledger.llcPayables.llcPayables',
    'llcReceivables': 'ledger.llcReceivables.llcReceivables',
}


class GLAuditor:
    '''Run accounting-compliance checks on a GL record list.'''

    def __init__(self, llc, gl_records: List[Dict[str, Any]]):
        self.llc   = llc
        # Exclude COA seed rows from all checks
        self._rows = [r for r in (gl_records or []) if r.get('refDB') != 'COA']

    # ── Public API ───────────────────────────────────────────────────────

    def audit(self) -> Dict[str, Any]:
        '''Run all checks and return a structured audit report.'''
        issues: List[Dict[str, Any]] = []
        issues += self._check_tb_balance()
        issues += self._check_duplicates()
        issues += self._check_zero_amounts()
        issues += self._check_unclassified()
        issues += self._check_single_side()
        issues += self._check_escrow_balance()

        errors   = sum(1 for i in issues if i['severity'] == 'error')
        warnings = sum(1 for i in issues if i['severity'] == 'warning')
        return {
            'issues': issues,
            'summary': {
                'total':    len(issues),
                'errors':   errors,
                'warnings': warnings,
                'clean':    len(issues) == 0,
            },
        }

    def apply_corrections(self, corrections: List[Dict[str, Any]]) -> Dict[str, Any]:
        '''
        Apply auto-applicable corrections approved by the operator.
        Each item: {'code': str, 'entries': [{tID, refDB, acct, ...}]}
        Supported auto-apply codes: DUP_TXN, ZERO_AMT.
        '''
        applied: List[str] = []
        errors:  List[str] = []
        for corr in corrections:
            if corr.get('code') in ('DUP_TXN', 'ZERO_AMT'):
                result = self._remove_entries(corr.get('entries', []))
                applied += result['applied']
                errors  += result['errors']
        return {'applied': applied, 'errors': errors}

    # ── Checks ───────────────────────────────────────────────────────────

    def _check_tb_balance(self) -> List[Dict[str, Any]]:
        total_d = sum(float(r.get('amt') or 0)
                      for r in self._rows
                      if str(r.get('aType', '')).lower() in ('debit', 'dr', 'd'))
        total_c = sum(float(r.get('amt') or 0)
                      for r in self._rows
                      if str(r.get('aType', '')).lower() in ('credit', 'cr', 'c'))
        diff = round(total_d - total_c, 2)
        if abs(diff) < 0.01:
            return []

        # Per-acctType breakdown to pinpoint which group is imbalanced
        by_type: Dict[str, Dict[str, float]] = defaultdict(lambda: {'D': 0.0, 'C': 0.0})
        for r in self._rows:
            at  = r.get('acctType', '—') or '—'
            amt = float(r.get('amt') or 0)
            if str(r.get('aType', '')).lower() in ('debit', 'dr', 'd'):
                by_type[at]['D'] += amt
            else:
                by_type[at]['C'] += amt
        imbalanced = {
            at: v for at, v in by_type.items()
            if abs(round(v['D'] - v['C'], 2)) > 0.01
        }
        lines = [
            f"  {at}: Debit={v['D']:.2f}  Credit={v['C']:.2f}  diff={v['D'] - v['C']:.2f}"
            for at, v in imbalanced.items()
        ]
        return [{
            'code':     'TB_IMBALANCE',
            'severity': 'error',
            'title':    'Trial Balance Out of Equilibrium',
            'description': (
                f"Σ Debit ({total_d:.2f}) ≠ Σ Credit ({total_c:.2f}) — "
                f"difference of {diff:+.2f}.\n"
                "Imbalanced account groups:\n" + '\n'.join(lines)
            ),
            'affected': [],
            'correction': {
                'type':       'manual',
                'auto_apply': False,
                'description': (
                    f"Add a {'Credit' if diff > 0 else 'Debit'} journal entry "
                    f"of {abs(diff):.2f} to balance the books. "
                    "Identify which transaction is posted to the wrong account "
                    "or is missing its counterpart entry."
                ),
                'entries': [],
            },
        }]

    def _check_duplicates(self) -> List[Dict[str, Any]]:
        # Only flag non-zero dups; zero-amount dups are caught by ZERO_AMT
        dup_rows = [
            r for r in self._rows
            if r.get('Status') == '⚠ Dup' and abs(float(r.get('amt') or 0)) > 0.001
        ]
        if not dup_rows:
            return []
        by_tid: Dict[str, List[Dict]] = defaultdict(list)
        for r in dup_rows:
            by_tid[r.get('tID', '')].append(r)

        issues = []
        for tid, entries in by_tid.items():
            dbs = sorted({e.get('refDB', '') for e in entries})
            affected = [
                {'tID': e.get('tID'), 'acct': e.get('acct'),
                 'refDB': e.get('refDB'), 'amt': e.get('amt')}
                for e in entries
            ]
            # Keep first occurrence; remove the rest
            to_remove = [
                {'tID': e.get('tID'), 'refDB': e.get('refDB'),
                 'acct': e.get('acct'), 'lineNo': e.get('_lineNo')}
                for e in entries[1:]
            ]
            issues.append({
                'code':     'DUP_TXN',
                'severity': 'error',
                'title':    f'Duplicate Transaction: {tid}',
                'description': (
                    f"Transaction {tid} appears in multiple source DBs: "
                    f"{', '.join(dbs)}. "
                    "Only one record should exist per transaction."
                ),
                'affected': affected,
                'correction': {
                    'type':       'remove_entry',
                    'auto_apply': True,
                    'description': (
                        f"Remove duplicate entries for tID={tid} "
                        f"from secondary source DBs ({', '.join(dbs[1:])}), "
                        "keeping the first occurrence."
                    ),
                    'entries': to_remove,
                },
            })
        return issues

    def _check_zero_amounts(self) -> List[Dict[str, Any]]:
        zero_rows = [
            r for r in self._rows
            if abs(float(r.get('amt') or 0)) < 0.001
        ]
        if not zero_rows:
            return []
        affected = [
            {'tID': r.get('tID'), 'acct': r.get('acct'),
             'refDB': r.get('refDB'), 'desc': r.get('desc', '')}
            for r in zero_rows
        ]
        entries = [
            {'tID': r.get('tID'), 'refDB': r.get('refDB'),
             'acct': r.get('acct'), 'lineNo': r.get('_lineNo')}
            for r in zero_rows
        ]
        return [{
            'code':     'ZERO_AMT',
            'severity': 'warning',
            'title':    f'Zero-Amount Entries ({len(zero_rows)})',
            'description': (
                f"{len(zero_rows)} non-COA transaction(s) with amt=0. "
                "These are typically null/template rows that do not belong "
                "in the active ledger."
            ),
            'affected': affected,
            'correction': {
                'type':       'remove_entry',
                'auto_apply': True,
                'description': (
                    f"Remove {len(zero_rows)} zero-amount entries from "
                    "their respective source DBs."
                ),
                'entries': entries,
            },
        }]

    def _check_unclassified(self) -> List[Dict[str, Any]]:
        unknown = [r for r in self._rows if not r.get('acctType', '').strip()]
        bad     = [r for r in self._rows
                   if r.get('acctType', '').strip()
                   and r.get('acctType', '').strip() not in _KNOWN_TYPES]
        issues  = []
        if unknown:
            issues.append({
                'code':     'UNCLASSIFIED',
                'severity': 'warning',
                'title':    f'Unclassified Accounts ({len(unknown)})',
                'description': (
                    f"{len(unknown)} row(s) have no acctType — the account "
                    "path was not found in the Chart of Accounts. "
                    "Check for typos in the acct field."
                ),
                'affected': [
                    {'tID': r.get('tID'), 'acct': r.get('acct'),
                     'refDB': r.get('refDB')}
                    for r in unknown
                ],
                'correction': {
                    'type':       'manual',
                    'auto_apply': False,
                    'description': (
                        "Map each unclassified account to the Chart of Accounts. "
                        "Correct the acct field in the source DB."
                    ),
                    'entries': [],
                },
            })
        if bad:
            issues.append({
                'code':     'BAD_ACCT_TYPE',
                'severity': 'warning',
                'title':    f'Non-Standard acctType ({len(bad)})',
                'description': (
                    f"{len(bad)} row(s) use acctType values outside the "
                    "5 standard types (Asset / Liability / Equity / Income / Expense)."
                ),
                'affected': [
                    {'tID': r.get('tID'), 'acct': r.get('acct'),
                     'acctType': r.get('acctType'), 'refDB': r.get('refDB')}
                    for r in bad
                ],
                'correction': {
                    'type':       'manual',
                    'auto_apply': False,
                    'description': (
                        "Review each row and correct the acctType to one of "
                        "the 5 standard types using the Chart of Accounts."
                    ),
                    'entries': [],
                },
            })
        return issues

    def _check_single_side(self) -> List[Dict[str, Any]]:
        by_acct: Dict[str, Dict[str, float]] = defaultdict(lambda: {'D': 0.0, 'C': 0.0})
        for r in self._rows:
            acct = r.get('acct', '') or ''
            amt  = float(r.get('amt') or 0)
            if str(r.get('aType', '')).lower() in ('debit', 'dr', 'd'):
                by_acct[acct]['D'] += amt
            else:
                by_acct[acct]['C'] += amt

        one_sided = []
        for acct, v in by_acct.items():
            d, c = round(v['D'], 2), round(v['C'], 2)
            if d > 0 and c == 0:
                one_sided.append({'acct': acct, 'side': 'Debit-only',
                                   'Debit': d, 'Credit': 0.0})
            elif c > 0 and d == 0:
                one_sided.append({'acct': acct, 'side': 'Credit-only',
                                   'Debit': 0.0, 'Credit': c})
        if not one_sided:
            return []
        return [{
            'code':     'SINGLE_SIDE',
            'severity': 'warning',
            'title':    f'Single-Sided Account Balances ({len(one_sided)})',
            'description': (
                f"{len(one_sided)} account(s) have entries on only one side "
                "(all Debit or all Credit). This may indicate a missing "
                "counterpart dual-entry."
            ),
            'affected': one_sided,
            'correction': {
                'type':       'manual',
                'auto_apply': False,
                'description': (
                    "For each single-sided account verify whether a counterpart "
                    "entry exists under a different account. If not, add the "
                    "missing dual-entry record to the appropriate source DB."
                ),
                'entries': [],
            },
        }]

    def _check_escrow_balance(self) -> List[Dict[str, Any]]:
        '''
        Acct.Cash.Escrow is a clearing account — it MUST net to $0 after
        every complete property-purchase journal entry.
        '''
        ESCROW_ACCT = 'Acct.Cash.Escrow'
        escrow_rows = [r for r in self._rows if r.get('acct') == ESCROW_ACCT]
        if not escrow_rows:
            return []

        d = c = 0.0
        for r in escrow_rows:
            amt = float(r.get('amt') or 0)
            if str(r.get('aType', '')).lower() in ('debit', 'dr', 'd'):
                d += amt
            else:
                c += amt
        balance = round(d - c, 2)
        if abs(balance) < 0.01:
            return []

        # Sort largest-to-smallest by abs(amt) so the biggest contributors appear first.
        sorted_rows = sorted(escrow_rows, key=lambda r: abs(float(r.get('amt') or 0)), reverse=True)
        affected = [
            {
                'tID':   r.get('tID', ''),
                'refDB': r.get('refDB', ''),
                'aType': r.get('aType', ''),
                'amt':   r.get('amt', 0),
                'dt':    r.get('dt', ''),
                'desc':  (r.get('desc') or '')[:80],
            }
            for r in sorted_rows
        ]

        # Identify the imbalance direction and its accounting meaning.
        if balance < 0:  # Credit > Debit
            imbalance_explain = (
                f"Credits ({c:.2f}) exceed Debits ({d:.2f}) by {abs(balance):.2f}.\n"
                "This means cash OUTFLOWS from escrow (disbursements to sellers, "
                "closing costs, etc.) were posted but the matching cash INFLOW "
                "(funding of the escrow account) was never recorded.\n"
                "MISSING ENTRY: a Debit to Acct.Cash.Escrow offset by a Credit to\n"
                "  - Acct.Cash.Bank (LLC wire / bank transfer to escrow), OR\n"
                "  - Acct.Equity.Owner.Capital.Funds (owner contribution), OR\n"
                "  - Acct.Liab.Mortgage (loan proceeds deposited into escrow)."
            )
        else:  # Debit > Credit
            imbalance_explain = (
                f"Debits ({d:.2f}) exceed Credits ({c:.2f}) by {abs(balance):.2f}.\n"
                "Cash was recorded as FLOWING INTO escrow but the disbursements "
                "out of it are under-posted.\n"
                "MISSING ENTRY: a Credit to Acct.Cash.Escrow for the unmatched "
                "purchase line items (asset, closing costs, etc.)."
            )

        # Explain where the GL picks up escrow rows.
        source_explain = (
            "WHERE THESE ROWS COME FROM:\n"
            "The GL contains an Acct.Cash.Escrow row for every source record where:\n"
            "  (a) acct = 'Acct.Cash.Escrow'  (direct posting), OR\n"
            "  (b) Ledger = 'Acct.Cash.Escrow' (toDoubleEntry() generates the\n"
            "      counter-entry automatically — the original record uses a\n"
            "      different account as its primary acct).\n"
            "Check the tID/refDB in the affected list to trace which source DB\n"
            "record generated each row."
        )

        description = (
            f"Acct.Cash.Escrow has a non-zero balance of {balance:+.2f} "
            f"(Debit={d:.2f}, Credit={c:.2f}).\n\n"
            + imbalance_explain + "\n\n"
            + source_explain + "\n\n"
            "HOW TO FIX:\n"
            "  1. Check each row in the affected list (tID + refDB) to find\n"
            "     which source records are responsible.\n"
            "  2. If the closing journal was entered without Ledger='Acct.Cash.Escrow',\n"
            "     open PropAgent → re-commit the property closing.  PropAgent\n"
            "     sets Ledger='Acct.Cash.Escrow' on every disbursement row and\n"
            "     posts the offsetting cash-in entry automatically.\n"
            "  3. After fixing, reload the GL and re-run Audit — this issue\n"
            "     should disappear and Acct.Cash.Escrow should show $0.00."
        )

        return [{
            'code':     'ESCROW_IMBALANCE',
            'severity': 'error',
            'title':    f'Escrow Clearing Account Non-Zero (balance={balance:+.2f})',
            'description': description,
            'affected': affected,
            'correction': {
                'type':       'manual',
                'auto_apply': False,
                'description': (
                    "Re-commit the property purchase via PropAgent, which regenerates "
                    "all journal entries with Ledger='Acct.Cash.Escrow' and posts "
                    "the offsetting cash-in entry so the clearing account nets to $0."
                ),
                'entries': [],
            },
        }]

    # ── Apply helpers ────────────────────────────────────────────────────

    def _remove_entries(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        '''Remove specific tID rows from their source DBs.'''
        by_db: Dict[str, set] = defaultdict(set)
        for e in entries:
            refdb = e.get('refDB', '')
            tid   = e.get('tID', '')
            if refdb and tid:
                by_db[refdb].add(tid)

        applied: List[str] = []
        errors:  List[str] = []
        for refdb, tids in by_db.items():
            cls_path = _REFDB_CLASS.get(refdb)
            if not cls_path:
                errors.append(f"Unknown source DB: {refdb}")
                continue
            try:
                mod_name, cls_name = cls_path.rsplit('.', 1)
                mod = importlib.import_module(mod_name)
                cls = getattr(mod, cls_name)
                obj = cls(self.llc)
                records = obj.load() or []
                before  = len(records)
                records = [r for r in records if self._row_tid(r) not in tids]
                obj.save(records)
                applied.append(
                    f"Removed {before - len(records)} record(s) from {refdb}"
                )
            except Exception as err:
                errors.append(f"Error updating {refdb}: {err}")
        return {'applied': applied, 'errors': errors}

    @staticmethod
    def _row_tid(r: Dict[str, Any]) -> str:
        from ledger.stmtGL import toTid
        return r.get('tID') or toTid(r)
