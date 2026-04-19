'''
llcForm1065SchBPg3 — IRS Form 1065, Schedule B (Other Information), Page 3.
Questions 13–25: Like-kind exchanges, foreign forms, §163(j), tax shelter,
Form 3520, centralized audit regime election, and FATCA.

Field IDs f1–f16 within this page.
NAMESPACE maps every fID to "Form1065.Pg3.<PartName>".

Auto-computed (from FR database — same pipeline as FILL PDF):
  Q20: §163(j) flag triggered when IS.interest_expense > 0.

All compliance questions default to ☑ No for a domestic real estate
rental LLC with individual partners.  Items that require CPA review
or manual determination are left "" (blank).

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

Reference: IRS Form 1065 (2024), Schedule B, Questions 13–25.
Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase

_NO  = '☑ No'
_YES = '☑ Yes'


class llcForm1065SchBPg3(_llcIRSViewBase):

    # ── Page-level field namespace ─────────────────────────────────────────
    NAMESPACE: Dict[str, str] = {
        "f1":  "Form1065.Pg3.SchB.Header",
        "f2":  "Form1065.Pg3.SchB.PartVIII",   # Q13 like-kind exchange
        "f3":  "Form1065.Pg3.SchB.PartVIII",   # Q14 tenancy-in-common distribution
        "f4":  "Form1065.Pg3.SchB.PartIX",     # Q15 Form 8858 count
        "f5":  "Form1065.Pg3.SchB.PartIX",     # Q16 foreign partners / Form 8805
        "f6":  "Form1065.Pg3.SchB.PartIX",     # Q17 Form 8865 count
        "f7":  "Form1065.Pg3.SchB.PartX",      # Q18 Form 1042 withholding
        "f8":  "Form1065.Pg3.SchB.PartXI",     # Q19 §721(c) partnership
        "f9":  "Form1065.Pg3.SchB.PartXII",    # Q20 §163(j) limitation
        "f10": "Form1065.Pg3.SchB.PartXII",    # Q20a RPTOB election
        "f11": "Form1065.Pg3.SchB.PartXIII",   # Q21 tax shelter / syndicate
        "f12": "Form1065.Pg3.SchB.PartXIV",    # Q22 Form 3520
        "f13": "Form1065.Pg3.SchB.PartXV",     # Q23 centralized audit election-out
        "f14": "Form1065.Pg3.SchB.PartXV",     # Q23a pass-through partners
        "f15": "Form1065.Pg3.SchB.PartXVI",    # Q24 % held by non-individual/trust/estate
        "f16": "Form1065.Pg3.SchB.PartXVII",   # Q25 FATCA foreign financial account
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
        n_partners   = self._owner_count()
        interest_exp = self._isv('interest_expense')
        has_interest = interest_exp > 0

        R = self._row
        rows: List[Dict[str, Any]] = [
            R('f1',  '',    'Schedule B — Other Information (Pg 3, Q 13–25). '
                            'Like-kind exchanges, foreign forms, audit regime, and §163(j).', ''),

            # Q13 — Like-kind exchange
            R('f2',  '13',  'Check if, during the current or prior tax year, the partnership '
                            'distributed any property received in a like-kind exchange or '
                            'contributed such property to another partnership (§1031 / §707).',
                             _NO),

            # Q14 — Tenancy-in-common distribution
            R('f3',  '14',  'At any time during the tax year, did the partnership distribute to '
                            'any partner a tenancy-in-common or other undivided interest in '
                            'partnership property?',
                             _NO),

            # Q15 — Form 8858 count
            R('f4',  '15',  'If the partnership is required to file Form 8858 (foreign disregarded '
                            'entities / branches), enter the number of Forms 8858 attached.',
                             '0'),

            # Q16 — Foreign partners / Form 8805
            R('f5',  '16',  'Does the partnership have any foreign partners?  If "Yes," enter the '
                            'number of Forms 8805 (Foreign Partner\'s Info Statement of §1446 '
                            'Withholding Tax) filed for this partnership.',
                             _NO),

            # Q17 — Form 8865
            R('f6',  '17',  'Enter the number of Forms 8865, Return of U.S. Persons With Respect '
                            'to Certain Foreign Partnerships, attached to this return.',
                             '0'),

            # Q18 — Form 1042 withholding
            R('f7',  '18',  'Is the partnership required to file Form 1042, Annual Withholding Tax '
                            'Return for U.S. Source Income of Foreign Persons, because it has a '
                            'foreign partner subject to §1446 withholding?',
                             _NO),

            # Q19 — §721(c) partnership
            R('f8',  '19',  'Is the partnership a §721(c) partnership as defined in '
                            'Regulations §1.721(c)-1(b)(14)?',
                             _NO),

            # Q20 — §163(j) business interest limitation
            R('f9',  '20',  'Does the partnership have a §163(j) business interest expense limitation '
                            'election in effect for the current tax year?'
                            + (f'  [FR IS.interest_expense: ${interest_exp:,.2f}]' if has_interest
                               else '  [No interest expense in FR IS]'),
                             '' if has_interest else _NO),

            R('f10', '20a', '  If real estate: has the partnership made the real property trade or '
                            'business (RPTOB) election under §163(j)(7)(B) to be an electing RPTE?  '
                            '(Electing out of §163(j) requires ADS depreciation on non-residential '
                            'real property.)',
                             ''),

            # Q21 — Tax shelter / syndicate
            R('f11', '21',  'Does the partnership satisfy one or more of the following?  '
                            '(a) Is a tax shelter as defined in §6662(d)(2)(C)(ii);  '
                            '(b) Is a syndicate as described in §1256(e)(3)(B).',
                             _NO),

            # Q22 — Form 3520
            R('f12', '22',  'Is the partnership required to file Form 3520 (Annual Return To Report '
                            'Transactions With Foreign Trusts and Receipt of Certain Foreign Gifts)?',
                             _NO),

            # Q23 — Centralized audit regime election-out (§6221(b))
            R('f13', '23',  'Is the partnership electing out of the centralized partnership audit '
                            'regime under §6221(b)?  (Eligible only if ≤100 eligible partners — '
                            'all must be individuals, C corps, S corps, or estates of deceased.  '
                            f'Requires Schedule B-2.)  [Current partner count: {n_partners}]',
                             ''),

            R('f14', '23a', '  If "Yes" to Q23: does the partnership have any partners that are '
                            'pass-through entities (other than S corps per §6221(b)(1)(C))?',
                             _NO),

            # Q24 — Partner composition percentage
            R('f15', '24',  'Enter the total percentage of partnership interests held by partners '
                            'that are other than individuals, trusts, or estates.',
                             '0%  — all partners are individuals or trusts'),

            # Q25 — FATCA
            R('f16', '25',  'Did the partnership have a financial interest in or signature authority '
                            'over a foreign financial account (bank, securities, or other financial '
                            'account) in a foreign country?',
                             _NO),
        ]
        return rows

    def stats(self) -> Dict[str, Any]:
        return {
            'Partners':     self._owner_count(),
            'Interest Exp': f'${self._isv("interest_expense"):,.2f}',
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'namespace':  self.NAMESPACE,
            'note': (
                'IRS Form 1065 (2024) Schedule B, Q13–25. '
                'FR-computed values match Form1065_FILL.pdf exactly. '
                'Q20 §163(j) flag auto-set when FR IS.interest_expense > 0. '
                'Q23 centralized audit election requires attorney/CPA review. '
                'Consult a qualified tax professional before filing.'
            ),
        }
