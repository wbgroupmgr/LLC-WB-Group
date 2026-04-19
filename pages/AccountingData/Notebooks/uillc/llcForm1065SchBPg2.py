'''
llcForm1065SchBPg2 — IRS Form 1065, Schedule B (Other Information), Page 2.
Questions 1–12: Entity type, ownership tests, elections, small-partnership
exception, PTP test, debt cancellation, FBAR, and §754 election.

Field IDs f1–f29 within this page.
NAMESPACE maps every fID to "Form1065.Pg2.<PartName>".

Auto-computed (from FR database — same pipeline as FILL PDF):
  Q2a: Individual/estate 50%+ ownership — analyzed from llcOwners pct
  Q2b: Corp/partnership/trust 50%+ ownership — analyzed from llcOwners memType
  Q6a: Total receipts threshold ($250K) — from IS.total_income
  Q6b: Total assets threshold ($1M)    — from BS.total_assets

All compliance questions default to "" (blank / not-checked).
☑ No  = definitively No for a domestic real estate rental LLC.
☑ Yes = computed or known-Yes answer.

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

Reference: IRS Form 1065 (2024), Schedule B, Questions 1–12.
Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase

_NO  = '☑ No'
_YES = '☑ Yes'


class llcForm1065SchBPg2(_llcIRSViewBase):

    # ── Page-level field namespace ─────────────────────────────────────────
    NAMESPACE: Dict[str, str] = {
        "f1":  "Form1065.Pg2.SchB.Header",
        "f2":  "Form1065.Pg2.SchB.PartI",       # Q1  entity type
        "f3":  "Form1065.Pg2.SchB.PartII",      # Q2a individual/estate ≥50%
        "f4":  "Form1065.Pg2.SchB.PartII",      # Q2b corp/partnership/trust ≥50%
        "f5":  "Form1065.Pg2.SchB.PartII",      # Q3  interest in another partnership
        "f6":  "Form1065.Pg2.SchB.PartII",      # Q3a(i)
        "f7":  "Form1065.Pg2.SchB.PartII",      # Q3a(ii)
        "f8":  "Form1065.Pg2.SchB.PartII",      # Q3a(iii)
        "f9":  "Form1065.Pg2.SchB.PartII",      # Q3a(iv)
        "f10": "Form1065.Pg2.SchB.PartII",      # Q3b(i)
        "f11": "Form1065.Pg2.SchB.PartII",      # Q3b(ii)
        "f12": "Form1065.Pg2.SchB.PartII",      # Q3b(iii)
        "f13": "Form1065.Pg2.SchB.PartII",      # Q3b(iv)
        "f14": "Form1065.Pg2.SchB.PartIII",     # Q4a corp/pship/trust 50%+
        "f15": "Form1065.Pg2.SchB.PartIII",     # Q4b individual/estate 50%+
        "f16": "Form1065.Pg2.SchB.PartIV",      # Q5 Form 8893 partnership-level audit
        "f17": "Form1065.Pg2.SchB.PartV",       # Q6 small-pship exception header
        "f18": "Form1065.Pg2.SchB.PartV",       # Q6a receipts < $250K
        "f19": "Form1065.Pg2.SchB.PartV",       # Q6b assets < $1M
        "f20": "Form1065.Pg2.SchB.PartV",       # Q6c K-1s on time
        "f21": "Form1065.Pg2.SchB.PartV",       # Q6d no M-3
        "f22": "Form1065.Pg2.SchB.PartVI",      # Q7 PTP
        "f23": "Form1065.Pg2.SchB.PartVI",      # Q8 debt cancellation
        "f24": "Form1065.Pg2.SchB.PartVI",      # Q9 Form 8918
        "f25": "Form1065.Pg2.SchB.PartVII",     # Q10 FBAR
        "f26": "Form1065.Pg2.SchB.PartVII",     # Q11 foreign trust
        "f27": "Form1065.Pg2.SchB.PartVIII",    # Q12a §754 election
        "f28": "Form1065.Pg2.SchB.PartVIII",    # Q12b §743(b)/§734(b) adjustment
        "f29": "Form1065.Pg2.SchB.RefData",     # reference summary
    }

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        super().__init__(eSession)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _row(self, fid: str, line: str, question: str, answer) -> Dict[str, Any]:
        return {
            'fID':      fid,
            'line':     line,
            'location': self.NAMESPACE.get(fid, ''),
            'question': question,
            'answer':   answer,
        }

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        total_assets   = self._bsv('total_assets')
        total_receipts = self._isv('total_income')
        n_partners     = self._owner_count()

        q6a = _YES if total_receipts < 250_000 else f'No — receipts ${total_receipts:,.2f} ≥ $250,000'
        q6b = _YES if total_assets   < 1_000_000 else f'No — assets ${total_assets:,.2f} ≥ $1,000,000'

        q2a = _YES if self._individual_majority_owner() else _NO
        q2b = _YES if self._entity_majority_owner()    else _NO

        R = self._row
        rows: List[Dict[str, Any]] = [
            R('f1',  '',    'Schedule B — Other Information (Pg 2, Q 1–12). '
                            'Partnership type, ownership thresholds, elections, and disclosures.', ''),

            # Q1 — Entity type
            R('f2',  '1',   'What type of entity is filing this return?  Check the applicable box.',
                             '☑ Limited Liability Company (LLC) — treated as Partnership for U.S. tax'),

            # Q2a — 50% ownership test (individual/estate)
            R('f3',  '2a',  'Did any individual or estate own, directly or indirectly, an interest of '
                            '50% or more in the profit, loss, or capital of the partnership?  '
                            '(If Yes, attach Schedule B-1.)  [Analyzed from llcOwners]',
                             q2a),

            # Q2b — 50% ownership test (corp/pship/trust/foreign)
            R('f4',  '2b',  'Did any foreign or domestic corporation, partnership (including any entity '
                            'treated as a partnership), trust, or tax-exempt organization, or any '
                            'foreign government own, directly or indirectly, an interest of 50% or more '
                            'in the profit, loss, or capital of the partnership?  '
                            '[Analyzed from llcOwners memType]',
                             q2b),

            # Q3 — Interest in another partnership / foreign disregarded entity
            R('f5',  '3',   'During the tax year, did the partnership own any interest in another '
                            'partnership or in any foreign entity that was disregarded as an entity '
                            'separate from its owner under Regs §§301.7701-2 and 301.7701-3?',
                             _NO),

            # Q3a sub-items i–iv
            R('f6',  '3a(i)',   '  (i) Interest in a domestic partnership',  _NO),
            R('f7',  '3a(ii)',  '  (ii) Interest in a foreign partnership',   _NO),
            R('f8',  '3a(iii)', '  (iii) Interest in a foreign disregarded entity (FDE)',  _NO),
            R('f9',  '3a(iv)',  '  (iv) Interest in a foreign reverse hybrid entity',      _NO),

            # Q3b sub-items i–iv
            R('f10', '3b(i)',   '  (i) The entity was a controlled foreign corporation (CFC) per §957', _NO),
            R('f11', '3b(ii)',  '  (ii) The entity was a passive foreign investment company (PFIC) per §1296', _NO),
            R('f12', '3b(iii)', '  (iii) The partnership made an election under §1295 for the entity', _NO),
            R('f13', '3b(iv)',  '  (iv) The entity was a qualified electing fund (QEF) per §1295',     _NO),

            # Q4 — Elections
            R('f14', '4',   'At any time during the tax year, did the partnership have in effect a '
                            'resolution or similar action to distribute earnings and profits to partners?',
                             _NO),

            # Q5 — Form 8893 partnership-level audit election
            R('f15', '5',   'Did the partnership file Form 8893, Election of Partnership Level Tax '
                            'Treatment, or an election under §6231(a)(1)(B)(ii) that is in effect '
                            'for this tax year?',
                             _NO),

            # Q6 — Small-partnership exception
            R('f16', '6',   'Does the partnership satisfy ALL four conditions of the §6231(a)(1)(B) '
                            'small-partnership exception? (If Yes, not required to complete '
                            'Schedules L, M-1, M-2, item F, or Schedule K-1 item L.)', ''),

            R('f17', '6a',  f'(a) Total receipts for the tax year were less than $250,000.  '
                            f'[FR computed: ${total_receipts:,.2f}]',
                             q6a),

            R('f18', '6b',  f'(b) Total assets at end of tax year were less than $1,000,000.  '
                            f'[FR computed: ${total_assets:,.2f}]',
                             q6b),

            R('f19', '6c',  '(c) Schedules K-1 are filed on or before the due date (including '
                            'extensions) for the partnership return.',
                             ''),

            R('f20', '6d',  '(d) The partnership is not filing and is not required to file '
                            'Schedule M-3.',
                             _YES),

            # Q7 — Publicly traded partnership
            R('f21', '7',   'Is this partnership a publicly traded partnership as defined in §469(k)(2)?',
                             _NO),

            # Q8 — Debt cancellation
            R('f22', '8',   'During the tax year, did the partnership have any debt that was cancelled, '
                            'forgiven, or had its principal amount reduced?',
                             _NO),

            # Q9 — Form 8918
            R('f23', '9',   'Has this partnership filed, or is it required to file, Form 8918, '
                            'Material Advisor Disclosure Statement, to provide information on any '
                            'reportable transaction?',
                             _NO),

            # Q10 — FBAR
            R('f24', '10',  'At any time during the calendar year, did the partnership have an '
                            'interest in or signature authority over a financial account in a '
                            'foreign country (FinCEN Form 114 — FBAR)?',
                             _NO),

            # Q11 — Foreign trust
            R('f25', '11',  'At any time during the tax year, did the partnership receive a '
                            'distribution from, or was it the grantor of, or transferor to, '
                            'a foreign trust?  If "Yes," the partnership may have to file '
                            'Form 3520.',
                             _NO),

            # Q12 — §754 election
            R('f26', '12a', 'Is the partnership making, or had it previously made (and not revoked), '
                            'a §754 election (optional basis adjustment on transfer or distribution '
                            'under §§734(b) and 743(b))?',
                             _NO),

            R('f27', '12b', 'Did the partnership make for this tax year an optional basis adjustment '
                            'under §743(b) or §734(b)?  If "Yes," attach a statement.',
                             _NO),

            # Reference data
            R('f28', '',    f'[Ref] Total partners / K-1s to be issued',      str(n_partners)),
            R('f29', '',    f'[Ref] Total assets per books (end of tax year)', f'${total_assets:,.2f}'),
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        return {
            'Total Assets':   f'${self._bsv("total_assets"):,.2f}',
            'Total Receipts': f'${self._isv("total_income"):,.2f}',
            'Partners':       self._owner_count(),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'namespace':  self.NAMESPACE,
            'note': (
                'IRS Form 1065 (2024) Schedule B, Q1–12. '
                'FR-computed values match Form1065_FILL.pdf exactly. '
                'Q2a/2b 50% ownership auto-analyzed from llcOwners. '
                'Q6a/6b thresholds auto-computed from FR IS/BS. '
                'Consult a qualified tax professional before filing.'
            ),
        }
