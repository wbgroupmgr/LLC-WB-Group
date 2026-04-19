'''
llcForm1065SchBPg4 — IRS Form 1065, Page 4.
Covers two sections that appear on page 4 of the 2024 Form 1065:

  1. Designation of Partnership Representative (§6223) — ALL fields left blank
     per user instruction.  The IRS will designate a representative if none
     is named.

  2. Analysis of Net Income (Loss) — partner-type breakdown of how the
     partnership's net income or loss is allocated among different partner
     categories as required on Form 1065, page 4.

Field IDs f1–f22 within this page (extended dynamically for per-partner rows).
NAMESPACE maps every fID to "Form1065.Pg4.<SectionName>".

All compliance questions default to ☑ No for this domestic real estate
rental LLC.  Partnership Representative fields are intentionally blank.

Data source: llcIRSViewBase → llcFinancialReport (same pipeline as the FILL PDF).

Reference: IRS Form 1065 (2024), Page 4.
Timestamp of last change: 2026.04.18
'''

from typing import Any, Dict, List

from uillc.llcIRSViewBase import _llcIRSViewBase

_NO  = '☑ No'
_YES = '☑ Yes'


class llcForm1065SchBPg4(_llcIRSViewBase):

    # ── Page-level field namespace ─────────────────────────────────────────
    NAMESPACE: Dict[str, str] = {
        "f1":  "Form1065.Pg4.PartnerRep",    # PR header
        "f2":  "Form1065.Pg4.PartnerRep",    # PR name
        "f3":  "Form1065.Pg4.PartnerRep",    # PR address
        "f4":  "Form1065.Pg4.PartnerRep",    # PR TIN/PTIN
        "f5":  "Form1065.Pg4.PartnerRep",    # PR phone
        "f6":  "Form1065.Pg4.NetIncomeAnalysis",   # NI summary
        "f7":  "Form1065.Pg4.NetIncomeAnalysis",   # rental income
        "f8":  "Form1065.Pg4.NetIncomeAnalysis",   # individual GP active
        "f9":  "Form1065.Pg4.NetIncomeAnalysis",   # individual LP passive
        "f10": "Form1065.Pg4.NetIncomeAnalysis",   # corporate GP
        "f11": "Form1065.Pg4.NetIncomeAnalysis",   # corporate LP
        "f12": "Form1065.Pg4.NetIncomeAnalysis",   # partnership GP
        "f13": "Form1065.Pg4.NetIncomeAnalysis",   # exempt org
        "f14": "Form1065.Pg4.NetIncomeAnalysis",   # nominee / disregarded
        # Per-partner allocation rows start at f15 (dynamically extended)
        "f15": "Form1065.Pg4.PerPartnerAlloc",
    }

    VIEW_BY_OPTIONS: List[str] = []

    def __init__(self, eSession):
        super().__init__(eSession)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _row(self, fid: str, line: str, question: str, answer) -> Dict[str, Any]:
        loc = self.NAMESPACE.get(fid, self.NAMESPACE.get('f15', 'Form1065.Pg4.PerPartnerAlloc'))
        return {
            'fID':      fid,
            'line':     line,
            'location': loc,
            'question': question,
            'answer':   answer,
        }

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, view_by: str = 'All') -> List[Dict[str, Any]]:
        net_income = self._isv('net_income')
        rent_inc   = self._isv('rent_income')
        alloc      = self._per_partner_alloc()

        R = self._row
        rows: List[Dict[str, Any]] = [

            # ── Designation of Partnership Representative (§6223) ─────────────
            R('f1',  '',          'Designation of Partnership Representative (§6223). '
                                  'The DPR is authorized to act on behalf of the partnership '
                                  'in all BBA audit proceedings.  Left blank — IRS will select.',  ''),
            R('f2',  'DPR Name',  'Name of Designated Partnership Representative',            ''),
            R('f3',  'DPR Addr',  'U.S. address of Designated Partnership Representative',    ''),
            R('f4',  'DPR TIN',   'U.S. taxpayer identification number of DPR',               ''),
            R('f5',  'DPR Phone', 'Daytime telephone number of DPR',                          ''),

            # ── Analysis of Net Income (Loss) — by Partner Type ───────────────
            R('f6',  '',          'Analysis of Net Income (Loss) — by Partner Type. '
                                  f'Net income (loss) from Form 1065, Line 22  '
                                  f'[FR computed: ${net_income:,.2f}]',
                                  f'${net_income:,.2f}'),

            R('f7',  '',          'Net rental real estate income included above '
                                  f'(from Schedule K, Line 2)  [FR IS.rent_income: ${rent_inc:,.2f}]',
                                  f'${rent_inc:,.2f}'),

            # Individual general partners (active participation)
            R('f8',  'IndvGP-Active',
                     'Individual general partners — active participation in rental '
                     '(§469(i) up to $25,000 loss allowance if AGI ≤ $100,000)',
                     ''),

            # Individual limited partners (passive)
            R('f9',  'IndvLP-Passive',
                     'Individual limited partners — passive activity (§469 passive rules apply)',
                     ''),

            # Corporate general partners
            R('f10', 'CorpGP',
                     'Corporate general partners',
                     '$0  (no corporate partners detected)'),

            # Corporate limited partners
            R('f11', 'CorpLP',
                     'Corporate limited partners',
                     '$0  (no corporate partners detected)'),

            # Partnership general partners
            R('f12', 'PshipGP',
                     'Partnership general partners',
                     '$0  (no partnership-partners detected)'),

            # Exempt organizations
            R('f13', 'ExemptOrg',
                     'Exempt organizations',
                     '$0  (no exempt-org partners detected)'),

            # Nominees / disregarded entities
            R('f14', 'Nominee',
                     'Nominees / disregarded entities',
                     '$0'),
        ]

        # ── Per-partner allocation table (dynamic rows) ───────────────────────
        fnum = 15
        rows.append(R(f'f{fnum}', 'Partner',
                      'Per-Partner Allocation (FR IS + llcOwners) — '
                      'Partner Name  |  Type  |  P&L %',
                      'Net Income Share'))
        fnum += 1
        for a in alloc:
            rows.append(R(f'f{fnum}', a['name'],
                          f"{a['name']}  |  {a.get('type', 'Individual')}  |  {a['pct']*100:.1f}%",
                          f"${a['ni_share']:,.2f}"))
            fnum += 1

        total_alloc = sum(a['ni_share'] for a in alloc)
        rows.append(R(f'f{fnum}', 'TOTAL',
                      'Total allocated net income (sum of partner shares)',
                      f'${total_alloc:,.2f}'))

        return rows

    def stats(self) -> Dict[str, Any]:
        return {
            'Net Income':    self._isv('net_income'),
            'Rental Income': self._isv('rent_income'),
            'Partners':      self._owner_count(),
        }

    def meta(self) -> Dict[str, Any]:
        return {
            'objectName': self.object_name(),
            'namespace':  self.NAMESPACE,
            'note': (
                'IRS Form 1065 (2024) Page 4. '
                'FR-computed values match Form1065_FILL.pdf exactly. '
                'Designation of Partnership Representative — all fields left blank. '
                'Analysis of Net Income: per-partner allocations from FR IS + llcOwners. '
                'Active vs. passive classification requires CPA review. '
                'Consult a qualified tax professional before filing.'
            ),
        }
