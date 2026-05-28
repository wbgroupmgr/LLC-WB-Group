'''
ledger.auditor — GL Audit Engine  (Forensic Accounting Edition)

Forensic principles applied (see docs/design_LLC_02-GL-Audit-Forensics.md):
  1. Precision Matching  — every finding cites specific tID/tDB source records
  2. Minimal Explanation — for balance diffs, only show rows that explain the exact amount
  3. Counter-Entry Verification — SINGLE_SIDE only flags entries with no double-entry partner
  4. Extended Equation   — A = L + E + (Inc − Exp) for open (pre-close) periods
  5. Orphan Detection    — srcTID == tID signals a direct-posted entry (no toDoubleEntry pair)
  6. Consistent Details  — all affected rows carry the same standard fields

Checks (errors listed before warnings):
  TB_IMBALANCE     — Σ Debit ≠ Σ Credit in the Trial Balance
  ACCT_EQUATION    — A ≠ L + E + (Inc − Exp): accounting equation fails for non-close reasons
  ESCROW_IMBALANCE — Acct.Cash.Escrow clearing account does not net to $0
  DUP_TXN          — rows flagged ⚠ Dup (same tID across multiple source DBs)
  ZERO_AMT         — non-COA rows with amt = 0 (template/null entries)
  UNCLASSIFIED     — acctType empty or not in the 5 standard types
  BAD_ACCT_TYPE    — acctType not in {Asset,Liability,Equity,Income,Expense,Staging}
  SINGLE_SIDE      — account with entries on only one side AND no counter-entry partner
'''

from __future__ import annotations

import importlib
import itertools
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

_KNOWN_TYPES = {'Asset', 'Liability', 'Equity', 'Income', 'Expense', 'Staging'}
_SEV_ORDER   = {'error': 0, 'warning': 1}

# Map tDB string → fully-qualified class path for load()/save()
_REFDB_CLASS: Dict[str, str] = {
    'llcExpRev':      'ledger.llcExpRev.llcExpRev',
    'llcAssets':      'ledger.llcAssets.llcAssets',
    'llcPayables':    'ledger.llcPayables.llcPayables',
    'llcReceivables': 'ledger.llcReceivables.llcReceivables',
}

_ATYPE_LOWER = {'debit', 'dr', 'd'}


def _is_debit(r: Dict) -> bool:
    return str(r.get('aType', '')).strip().lower() in _ATYPE_LOWER


def _amt(r: Dict) -> float:
    return float(r.get('amt') or 0)


def _tdb(r: Dict) -> str:
    return r.get('tDB', '') or r.get('refDB', '')


def _fmt(r: Dict) -> Dict:
    '''Standard affected-record dict — consistent fields across all checks.'''
    return {
        'acct':  r.get('acct',  ''),
        'aType': r.get('aType', ''),
        'amt':   r.get('amt',   0),
        'dt':    r.get('dt',    ''),
        'desc':  (r.get('desc') or '')[:80],
        'tID':   r.get('tID',   ''),
        'srcTID':r.get('srcTID',''),
        'tDB':   _tdb(r),
    }


def _subset_summing_to(rows: List[Dict], target: float,
                       signed: bool = False) -> Optional[List[Dict]]:
    '''
    Find the smallest subset of rows whose amounts sum to target (±0.01).
    signed=True uses signed amounts (Credits negative); False uses abs values.
    Returns None if no exact subset found (or >20 rows — too expensive).
    '''
    if len(rows) > 20:
        return None
    getter = (lambda r: (_amt(r) if _is_debit(r) else -_amt(r))) if signed \
             else _amt
    for size in range(1, len(rows) + 1):
        for combo in itertools.combinations(rows, size):
            if abs(sum(getter(r) for r in combo) - target) < 0.01:
                return list(combo)
    return None


class GLAuditor:
    '''Run accounting-compliance checks on a GL record list.'''

    def __init__(self, llc, gl_records: List[Dict[str, Any]]):
        self.llc    = llc
        # Exclude COA seed rows
        self._rows  = [r for r in (gl_records or [])
                       if _tdb(r) not in ('COA',) and r.get('tID', '').startswith('COA_') is False]
        # Index: srcTID → list of rows sharing that srcTID
        self._src_idx: Dict[str, List[Dict]] = defaultdict(list)
        for r in self._rows:
            src = r.get('srcTID', '')
            if src:
                self._src_idx[src].append(r)
        # Index: tID → row
        self._tid_idx: Dict[str, Dict] = {r.get('tID', ''): r for r in self._rows}

    # ── Public API ───────────────────────────────────────────────────────

    def audit(self) -> Dict[str, Any]:
        '''Run all checks. Errors appear before warnings.'''
        issues: List[Dict[str, Any]] = []
        issues += self._check_tb_balance()
        issues += self._check_accounting_equation()
        issues += self._check_escrow_balance()
        issues += self._check_duplicates()
        issues += self._check_zero_amounts()
        issues += self._check_unclassified()
        issues += self._check_single_side()

        issues.sort(key=lambda i: _SEV_ORDER.get(i.get('severity', 'warning'), 99))

        errors   = sum(1 for i in issues if i['severity'] == 'error')
        warnings = sum(1 for i in issues if i['severity'] == 'warning')
        return {
            'issues':  issues,
            'summary': {
                'total':    len(issues),
                'errors':   errors,
                'warnings': warnings,
                'clean':    len(issues) == 0,
            },
        }

    def apply_corrections(self, corrections: List[Dict[str, Any]]) -> Dict[str, Any]:
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
        total_d = sum(_amt(r) for r in self._rows if _is_debit(r))
        total_c = sum(_amt(r) for r in self._rows if not _is_debit(r))
        diff    = round(total_d - total_c, 2)
        if abs(diff) < 0.01:
            return []

        by_type: Dict[str, Dict[str, float]] = defaultdict(lambda: {'D': 0.0, 'C': 0.0})
        for r in self._rows:
            at = r.get('acctType', '—') or '—'
            if _is_debit(r):
                by_type[at]['D'] += _amt(r)
            else:
                by_type[at]['C'] += _amt(r)
        lines = [
            f"  {at}: Debit={v['D']:.2f}  Credit={v['C']:.2f}  diff={v['D']-v['C']:.2f}"
            for at, v in by_type.items()
            if abs(round(v['D'] - v['C'], 2)) > 0.01
        ]
        return [{
            'code':     'TB_IMBALANCE',
            'severity': 'error',
            'title':    'Trial Balance Out of Equilibrium',
            'description': (
                f"Σ Debit ({total_d:.2f}) ≠ Σ Credit ({total_c:.2f}) — "
                f"difference {diff:+.2f}.\n"
                "Imbalanced account groups:\n" + '\n'.join(lines)
            ),
            'affected': [],
            'correction': {
                'type': 'manual', 'auto_apply': False,
                'description': (
                    f"Add a {'Credit' if diff > 0 else 'Debit'} of {abs(diff):.2f} "
                    "to balance. Identify the transaction posted to the wrong account "
                    "or missing its counterpart."
                ),
                'entries': [],
            },
        }]

    def _check_accounting_equation(self) -> List[Dict[str, Any]]:
        '''
        Extended accounting equation for open periods (pre year-end close):
            Assets = Liabilities + Equity + (Income − Expenses)
        This always holds when the TB is balanced. If it fails, there are
        mis-classified accounts or truly orphaned entries (not just open Net Income).
        Net Income is shown as informational even when the equation holds.
        '''
        by_type: Dict[str, Dict[str, float]] = defaultdict(lambda: {'D': 0.0, 'C': 0.0})
        for r in self._rows:
            at = r.get('acctType', '') or ''
            if _is_debit(r):
                by_type[at]['D'] += _amt(r)
            else:
                by_type[at]['C'] += _amt(r)

        asset_bal = round(by_type['Asset']['D']     - by_type['Asset']['C'],     2)
        liab_bal  = round(by_type['Liability']['C'] - by_type['Liability']['D'], 2)
        eq_bal    = round(by_type['Equity']['C']    - by_type['Equity']['D'],    2)
        inc_bal   = round(by_type['Income']['C']    - by_type['Income']['D'],    2)
        exp_bal   = round(by_type['Expense']['D']   - by_type['Expense']['C'],   2)
        net_inc   = round(inc_bal - exp_bal, 2)

        # Extended equation: A = L + E + (Inc − Exp)
        lhs  = asset_bal
        rhs  = round(liab_bal + eq_bal + net_inc, 2)
        diff = round(lhs - rhs, 2)

        if abs(diff) < 0.01:
            return []   # Equation holds — net income explains any A vs L+E gap

        # Equation fails even with net income included.
        # Forensic: find transactions with mis-classified or unknown acctTypes
        # that contribute to the unexplained diff.
        bad_rows = [r for r in self._rows
                    if (r.get('acctType', '') or '') not in _KNOWN_TYPES
                    and (r.get('acctType', '') or '')]

        # Compute each bad row's signed impact on (A − L − E − Inc + Exp)
        def eq_impact(r: Dict) -> float:
            at  = r.get('acctType', '') or ''
            a   = _amt(r)
            deb = _is_debit(r)
            # Contribution to LHS (Assets): Asset/Debit +, Asset/Credit −
            # Contribution to RHS (L+E+NI): Liability or Equity Credit +, etc.
            # For unknown type, the row adds to neither side properly.
            if at in ('Asset',):
                return a if deb else -a
            if at in ('Liability', 'Equity'):
                return -(a if not deb else -a)
            if at == 'Income':
                return -(a if not deb else -a)
            if at == 'Expense':
                return (a if deb else -a)
            # Unknown type: entire amount is unaccounted
            return a if deb else -a

        bad_impacts = [(r, eq_impact(r)) for r in bad_rows]
        bad_total   = round(sum(v for _, v in bad_impacts), 2)

        # Try to find the minimal subset of bad rows that explains the diff
        suspects = _subset_summing_to(bad_rows, diff, signed=True)
        if suspects is None:
            suspects = bad_rows  # fallback: show all bad-type rows

        affected = sorted([_fmt(r) for r in suspects],
                          key=lambda x: abs(float(x.get('amt') or 0)), reverse=True)

        return [{
            'code':     'ACCT_EQUATION',
            'severity': 'error',
            'title':    f'Accounting Equation Fails (diff={diff:+.2f})',
            'description': (
                f"Extended equation  A = L + E + (Inc − Exp)  fails.\n"
                f"  Assets       = {asset_bal:>12.2f}\n"
                f"  Liabilities  = {liab_bal:>12.2f}\n"
                f"  Equity       = {eq_bal:>12.2f}\n"
                f"  Net Income   = {net_inc:>12.2f}  (Income {inc_bal:.2f} − Expenses {exp_bal:.2f})\n"
                f"  L+E+NI total = {rhs:>12.2f}\n"
                f"  Difference   = {diff:>+12.2f}  ← unexplained gap\n\n"
                "FORENSIC: rows below have unrecognised acctType and contribute to the gap.\n"
                "Fix: correct the acct field in the source DB so the COA can classify it."
            ),
            'affected': affected,
            'correction': {
                'type': 'manual', 'auto_apply': False,
                'description': (
                    "Correct the acct field on each affected row so it maps to a valid "
                    "COA account. Re-run Audit after saving."
                ),
                'entries': [],
            },
        }]

    def _check_escrow_balance(self) -> List[Dict[str, Any]]:
        '''
        Acct.Cash.Escrow is a clearing account — must net to $0.

        Forensic approach (highest-probability-first):
          1. Assume all existing closing-statement (PropAgent) and bank records are correct.
          2. Identify orphan entries (srcTID == tID) — direct-posted with no double-entry pair.
          3. For each large orphan, look for a PropAgent entry of the same side and close amount;
             compute the delta between them to surface a reconciliation discrepancy.
          4. If a delta matches an existing escrow entry, call it out explicitly.
          5. Rank probable causes and suggest the most likely correcting journal entry.
        '''
        ESCROW = 'Acct.Cash.Escrow'
        escrow_rows = [r for r in self._rows if r.get('acct') == ESCROW
                       and not r.get('tID', '').startswith('COA_')]
        if not escrow_rows:
            return []

        d = c = 0.0
        for r in escrow_rows:
            if _is_debit(r):
                d += _amt(r)
            else:
                c += _amt(r)
        balance = round(d - c, 2)
        if abs(balance) < 0.01:
            return []

        # Classify rows
        orphans = [r for r in escrow_rows
                   if not r.get('srcTID') or r.get('srcTID') == r.get('tID')]
        paired  = [r for r in escrow_rows if r not in orphans]

        # Find minimal suspect set
        suspects = _subset_summing_to(orphans, balance, signed=True)
        if suspects is None:
            suspects = _subset_summing_to(escrow_rows, balance, signed=True)
        if suspects is None:
            suspects = orphans if orphans else escrow_rows

        affected = sorted([_fmt(r) for r in suspects],
                          key=lambda x: abs(float(x.get('amt') or 0)), reverse=True)

        # ── Forensic reconciliation analysis ─────────────────────────────
        # For each orphan, find the closest-amount PropAgent entry on the same side
        # and compute the delta.  This surfaces bank-vs-closing discrepancies.
        recon_notes = []
        for orph in sorted(orphans, key=lambda r: _amt(r), reverse=True):
            if _amt(orph) < 0.01:
                continue
            o_amt  = _amt(orph)
            o_side = _is_debit(orph)
            o_tdb  = _tdb(orph) or orph.get('tID', '')
            # Find closest paired entry on same side
            same_side = [r for r in paired if _is_debit(r) == o_side]
            if not same_side:
                continue
            closest = min(same_side, key=lambda r: abs(_amt(r) - o_amt))
            delta = round(o_amt - _amt(closest), 2)
            if abs(delta) < 0.01:
                continue  # exact match — not a discrepancy

            pct = abs(delta) / o_amt * 100
            c_desc = (closest.get('desc') or '')[:60]
            o_desc = (orph.get('desc') or '')[:60]

            # Check if the delta matches any existing escrow entry (e.g. a fee already posted)
            delta_match = next(
                (r for r in escrow_rows
                 if abs(_amt(r) - abs(delta)) < 0.01 and r is not orph and r is not closest),
                None
            )
            delta_match_note = ''
            if delta_match:
                dm_desc = (delta_match.get('desc') or '')[:60]
                dm_side = 'Credit' if not _is_debit(delta_match) else 'Debit'
                delta_match_note = (
                    f"\n    ⚡ Delta ${abs(delta):.2f} matches an existing escrow entry:\n"
                    f"       {dm_side} ${_amt(delta_match):.2f} — \"{dm_desc}\" "
                    f"(tID: {delta_match.get('tID','')})\n"
                    f"    This suggests the bank wire INCLUDES this line item, "
                    f"which is also posted separately in the closing records."
                )

            # Build correcting journal suggestion
            if delta > 0:
                # Orphan is LARGER — closing records under-funded escrow by delta
                fix_cr = 'Acct.Cash.Escrow'
                fix_dr = 'Acct.Equity.Owner.Capital.Funds'
                fix_desc = (
                    f"Post reconciling entry to llcAssets:\n"
                    f"    DEBIT  {fix_dr}  ${abs(delta):.2f}\n"
                    f"    CREDIT {fix_cr}  ${abs(delta):.2f}\n"
                    f"  This records the ${abs(delta):.2f} difference between the bank wire "
                    f"and closing statement as an owner equity adjustment."
                )
            else:
                # Orphan is SMALLER — closing records over-funded escrow by abs(delta)
                fix_dr = 'Acct.Cash.Escrow'
                fix_cr = 'Acct.Cash.Bank'
                fix_desc = (
                    f"Post reconciling entry to llcAssets:\n"
                    f"    DEBIT  {fix_dr}  ${abs(delta):.2f}\n"
                    f"    CREDIT {fix_cr}  ${abs(delta):.2f}\n"
                    f"  This records a ${abs(delta):.2f} refund from escrow back to the bank."
                )

            recon_notes.append(
                f"\n── Bank vs Closing Reconciliation ──\n"
                f"  Bank entry  ({o_tdb}):  ${o_amt:>12.2f}  \"{o_desc}\"\n"
                f"  Closing entry:           ${_amt(closest):>12.2f}  \"{c_desc}\"\n"
                f"  Discrepancy:             ${delta:>+12.2f}  ({pct:.2f}%)"
                + delta_match_note
                + f"\n\n  HIGHEST-PROBABILITY CAUSE:\n"
                  f"  Assuming both the bank record and closing records are correct,\n"
                  f"  the ${abs(delta):.2f} difference is an unreconciled amount between them.\n"
                  f"  Recommended fix:\n    {fix_desc}"
                + f"\n\n  OTHER POSSIBLE CAUSES (lower probability):\n"
                  f"  a) The bank entry duplicates the closing entry (same cash event, "
                  f"two sources). Fix: remove the bank entry ({orph.get('tID','')}).\n"
                  f"  b) A closing-statement line item is missing from PropAgent records. "
                  f"Fix: add the missing line and re-commit via PropAgent."
            )

        # Base description
        side_note = (
            f"Debits ({d:.2f}) exceed Credits ({c:.2f}) by {balance:.2f}."
            if balance > 0 else
            f"Credits ({c:.2f}) exceed Debits ({d:.2f}) by {abs(balance):.2f}."
        )
        orphan_summary = ''
        if orphans:
            orphan_tids = '  '.join(r.get('tID', '') for r in orphans[:5])
            orphan_summary = (
                f"\n\nORPHAN ENTRIES ({len(orphans)}) — direct-posted, no double-entry pair:\n"
                f"  {orphan_tids}"
            )

        description = (
            f"Acct.Cash.Escrow balance = {balance:+.2f}  (Debit={d:.2f}, Credit={c:.2f}).\n"
            + side_note
            + orphan_summary
            + ''.join(recon_notes)
        )
        if not recon_notes:
            description += (
                "\n\nNo close-amount PropAgent match found for the orphan entry. "
                "Verify the orphan tID in the source DB and confirm it was not "
                "entered manually in place of a PropAgent commit."
            )

        corr_desc = (
            "Post the recommended reconciling journal entry to llcAssets (see description). "
            "Re-run Audit after saving to confirm Acct.Cash.Escrow nets to $0."
        ) if recon_notes else (
            "Verify each orphan entry (tID listed above). If it duplicates a PropAgent "
            "record, remove it. If it is the only record, re-commit via PropAgent."
        )

        return [{
            'code':     'ESCROW_IMBALANCE',
            'severity': 'error',
            'title':    f'Escrow Clearing Account Non-Zero (balance={balance:+.2f})',
            'description': description,
            'affected': affected,
            'correction': {
                'type': 'manual', 'auto_apply': False,
                'description': corr_desc,
                'entries': [],
            },
        }]

    def _check_duplicates(self) -> List[Dict[str, Any]]:
        dup_rows = [r for r in self._rows
                    if r.get('Status') == '⚠ Dup' and _amt(r) > 0.001]
        if not dup_rows:
            return []
        by_tid: Dict[str, List[Dict]] = defaultdict(list)
        for r in dup_rows:
            by_tid[r.get('tID', '')].append(r)

        issues = []
        for tid, entries in by_tid.items():
            dbs      = sorted({_tdb(e) for e in entries})
            affected = sorted([_fmt(e) for e in entries],
                              key=lambda x: abs(float(x.get('amt') or 0)), reverse=True)
            to_remove = [
                {'tID': e.get('tID'), 'tDB': _tdb(e),
                 'acct': e.get('acct'), 'lineNo': e.get('_lineNo')}
                for e in entries[1:]
            ]
            issues.append({
                'code':     'DUP_TXN',
                'severity': 'error',
                'title':    f'Duplicate Transaction: {tid}',
                'description': (
                    f"Transaction {tid} appears in multiple source DBs: "
                    f"{', '.join(dbs)}. Only one record should exist."
                ),
                'affected': affected,
                'correction': {
                    'type': 'remove_entry', 'auto_apply': True,
                    'description': (
                        f"Remove duplicate entries for tID={tid} from "
                        f"secondary source DBs ({', '.join(dbs[1:])}), "
                        "keeping the first occurrence."
                    ),
                    'entries': to_remove,
                },
            })
        return issues

    def _check_zero_amounts(self) -> List[Dict[str, Any]]:
        zero_rows = [r for r in self._rows if abs(_amt(r)) < 0.001]
        if not zero_rows:
            return []
        affected = sorted([_fmt(r) for r in zero_rows],
                          key=lambda x: x.get('dt', ''))
        entries  = [{'tID': r.get('tID'), 'tDB': _tdb(r),
                     'acct': r.get('acct'), 'lineNo': r.get('_lineNo')}
                    for r in zero_rows]
        return [{
            'code':     'ZERO_AMT',
            'severity': 'warning',
            'title':    f'Zero-Amount Entries ({len(zero_rows)})',
            'description': (
                f"{len(zero_rows)} transaction(s) with amt=0. "
                "Typically null/template rows that do not belong in the active ledger."
            ),
            'affected': affected,
            'correction': {
                'type': 'remove_entry', 'auto_apply': True,
                'description': f"Remove {len(zero_rows)} zero-amount entries from their source DBs.",
                'entries': entries,
            },
        }]

    def _check_unclassified(self) -> List[Dict[str, Any]]:
        unknown = [r for r in self._rows if not (r.get('acctType', '') or '').strip()]
        bad     = [r for r in self._rows
                   if (r.get('acctType', '') or '').strip()
                   and (r.get('acctType', '') or '').strip() not in _KNOWN_TYPES]
        issues  = []
        if unknown:
            issues.append({
                'code':     'UNCLASSIFIED',
                'severity': 'warning',
                'title':    f'Unclassified Accounts ({len(unknown)})',
                'description': (
                    f"{len(unknown)} row(s) have no acctType — account path not "
                    "found in Chart of Accounts. Check for typos in the acct field."
                ),
                'affected': sorted([_fmt(r) for r in unknown],
                                   key=lambda x: abs(float(x.get('amt') or 0)), reverse=True),
                'correction': {
                    'type': 'manual', 'auto_apply': False,
                    'description': "Correct the acct field in the source DB to match a COA entry.",
                    'entries': [],
                },
            })
        if bad:
            issues.append({
                'code':     'BAD_ACCT_TYPE',
                'severity': 'warning',
                'title':    f'Non-Standard acctType ({len(bad)})',
                'description': (
                    f"{len(bad)} row(s) use acctType outside the standard types "
                    "(Asset / Liability / Equity / Income / Expense / Staging)."
                ),
                'affected': sorted([_fmt(r) for r in bad],
                                   key=lambda x: abs(float(x.get('amt') or 0)), reverse=True),
                'correction': {
                    'type': 'manual', 'auto_apply': False,
                    'description': "Correct the acct field so COA can classify it to a standard type.",
                    'entries': [],
                },
            })
        return issues

    def _has_counter(self, r: Dict) -> Tuple[bool, str]:
        '''
        Return (True, reason) if a double-entry counterpart exists for row r.

        Counter-entry detection strategy (forensic):
          1. srcTID index: another GL row shares the same srcTID but uses a different acct.
             This is the authoritative signal — toDoubleEntry sets srcTID on both sides.
          2. tID sign-flip: Credit rows have negative tIDs (date_-amt.xx); look for the
             matching positive-tID Debit row and vice versa.
          3. If neither found AND the source Ledger field was 'nan'/empty → truly single-sided.
        '''
        acct   = r.get('acct', '')
        src    = r.get('srcTID', '')
        tid    = r.get('tID', '')

        # Strategy 1: srcTID cross-acct match
        if src and src != tid:  # non-orphan: srcTID was set by toDoubleEntry
            for other in self._src_idx.get(src, []):
                if other.get('acct') != acct:
                    return True, 'srcTID-pair'

        # Strategy 2: tID sign-flip
        if '_' in tid:
            parts = tid.rsplit('_', 1)
            try:
                amt_part = float(parts[1])
                flip_tid = f"{parts[0]}_{-amt_part:.2f}"
                if flip_tid in self._tid_idx and self._tid_idx[flip_tid].get('acct') != acct:
                    return True, 'tID-flip'
            except ValueError:
                pass

        return False, ''

    def _check_single_side(self) -> List[Dict[str, Any]]:
        '''
        Flag accounts with entries on only one side (all Debit or all Credit)
        where no double-entry counterpart can be found via srcTID or tID sign-flip.
        Accounts where every entry has a confirmed counter are skipped — they are
        properly balanced at the pair level even if the account shows one side only.
        '''
        by_acct_totals: Dict[str, Dict[str, float]] = defaultdict(lambda: {'D': 0.0, 'C': 0.0})
        by_acct_rows:   Dict[str, List[Dict]]        = defaultdict(list)
        for r in self._rows:
            acct = r.get('acct', '') or ''
            if _is_debit(r):
                by_acct_totals[acct]['D'] += _amt(r)
            else:
                by_acct_totals[acct]['C'] += _amt(r)
            by_acct_rows[acct].append(r)

        affected = []
        for acct, v in by_acct_totals.items():
            d, c = round(v['D'], 2), round(v['C'], 2)
            if not ((d > 0 and c == 0) or (c > 0 and d == 0)):
                continue
            side = 'Debit-only' if d > 0 else 'Credit-only'

            for r in by_acct_rows[acct]:
                has_ctr, reason = self._has_counter(r)
                if has_ctr:
                    continue  # counter confirmed — not truly single-sided
                row_dict = _fmt(r)
                row_dict['side']   = side
                row_dict['reason'] = 'orphan: srcTID=tID' if (
                    not r.get('srcTID') or r.get('srcTID') == r.get('tID')
                ) else 'no-counter-found'
                affected.append(row_dict)

        if not affected:
            return []

        affected.sort(key=lambda x: abs(float(x.get('amt') or 0)), reverse=True)
        n_accts = len({a['acct'] for a in affected})

        return [{
            'code':     'SINGLE_SIDE',
            'severity': 'warning',
            'title':    f'Single-Sided Entries Without Counter-Entry ({n_accts} account(s))',
            'description': (
                f"{len(affected)} entry/entries in {n_accts} account(s) have no "
                "confirmed double-entry counterpart.\n\n"
                "FORENSIC METHOD:\n"
                "  Counter detection uses (1) srcTID cross-account match, then\n"
                "  (2) tID sign-flip (Credit tIDs are date_-amt.xx; Debit are date_+amt.xx).\n"
                "  Entries passing either test are excluded from this list.\n\n"
                "ROOT CAUSE: rows with reason='orphan: srcTID=tID' were direct-posted\n"
                "  (not via toDoubleEntry). Check if Ledger=nan in the source record —\n"
                "  that prevents automatic counter-entry generation."
            ),
            'affected': affected,
            'correction': {
                'type': 'manual', 'auto_apply': False,
                'description': (
                    "For each affected row: open the source DB record (tDB/tID) and "
                    "verify the Ledger field is set to the counterpart account. "
                    "If Ledger is blank/nan, add it and re-commit via the appropriate Agent."
                ),
                'entries': [],
            },
        }]

    # ── Apply helpers ────────────────────────────────────────────────────

    def _remove_entries(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_db: Dict[str, set] = defaultdict(set)
        for e in entries:
            tdb = e.get('tDB', '') or e.get('refDB', '')
            tid = e.get('tID', '')
            if tdb and tid:
                by_db[tdb].add(tid)

        applied: List[str] = []
        errors:  List[str] = []
        for tdb, tids in by_db.items():
            cls_path = _REFDB_CLASS.get(tdb)
            if not cls_path:
                errors.append(f"Unknown source DB: {tdb}")
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
                applied.append(f"Removed {before - len(records)} record(s) from {tdb}")
            except Exception as err:
                errors.append(f"Error updating {tdb}: {err}")
        return {'applied': applied, 'errors': errors}

    @staticmethod
    def _row_tid(r: Dict[str, Any]) -> str:
        from ledger.stmtGL import toTid
        return r.get('tID') or toTid(r)
