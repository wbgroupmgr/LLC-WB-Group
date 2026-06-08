# Plan: Schedule K-1 Per-Partner PDF Pipeline — v0.3
**Issue #4 · W&B Group LLC · Target: 3 × Sch_K1_FILL_<oID>.pdf**

Prepared: 2026-05-09
Status: PLANNING — no implementation started

---

## 0. Background & Expert Guidance

### What Schedule K-1 (Form 1065) is
Sch_K1 allocates the partnership's income/deductions/credits to each partner in
proportion to their profit/loss percentage.  Unlike Form 1065 or Form 8825, which
are single-copy partnership-level documents, there is **one K-1 per partner** —
three in W&B Group's case.

### IRS Box Mapping for a Rental Real Estate LLC (expert-reviewed)

| K-1 Box | Label | W&B Source | Formula |
|---------|-------|-----------|---------|
| Box 1 | Ordinary business income (loss) | `net_ordinary` | `0` (rental-only — no Acct.Rev.Ord.* activity) |
| Box 2 | Net rental real estate income (loss) | `net_rental` | `net_rental × partner.pct` (**NET**, not gross) |
| Box 3 | Other net rental income | — | `0` (not applicable) |
| Box 5 | Interest income | `interest_income` | `interest_income × partner.pct` |
| Box 14a | SE earnings | — | `0` (passive rental excluded from SE tax under IRC §1402(a)(1)) |
| Box 19a | Cash distributions | `distributions_cash` | `distributions_cash × partner.pct` |
| Box L1 | Beginning capital | — | `0` (first tax year 2025) |
| Box L2 | Capital contributed | `contributions` | `cash_contributions × partner.pct` |
| Box L3 | Current year net income (loss) | `net_income` | `net_income × partner.pct` |
| Box L5 | Withdrawals & distributions | `distributions_cash` | `distributions_cash × partner.pct` |
| Box L6 | Ending capital account | computed | `L2 + L3 − L5` |

**CPA-review flags (do not auto-populate):**
- Box 17 (AMT depreciation adjustment) — flag if MACRS ≠ AMT depreciation
- Box 20 (QBI / §199A information) — rental QBI election per Reg 1.199A-4
- Box 14a for Francis (96%, Manager) — if Acct.Rev.Ord.* ever has activity, SE tax may apply
- Capital account must use **tax basis** (IRS requirement since 2020)
- Cross-check: sum of all partners' L2 = total equity contributions in BS

### Partners (from llcOwners_WBGroupLLC.json)
| oID | Name | pct | Role |
|-----|------|-----|------|
| o20250801_1 | Francis X Rojas | 96% | Manager (active) |
| o20250801_2 | Alexandra Rojas | 2% | Passive member |
| o20250801_3 | Nicola Rojas | 2% | Passive member |

---

## 1. Current State Audit

### Form8825 — OPEN ITEMS (must complete before Sch_K1 delivery)
| Item | Status |
|------|--------|
| `irs/Form8825.py` exists | ✅ |
| `Form8825_IRS.pdf` in main repo | ✅ |
| `Form8825_IRS.pdf` synced to worktree | ⚠️ not confirmed |
| `Form8825_namespace.json` exists (221 fields) | ✅ exists |
| `Form8825_namespace.json` logicalKeys populated | ❌ all blank |
| `bookNS_IS.json` Form8825 section (F023–F113) | ✅ complete |
| `_build_f8825_filldict()` implemented | ✅ |
| `BookToIRS('Form8825').regenerate()` tested end-to-end | ❌ not tested |
| Fid alignment verified (f23 → F023 = Line 2a Col A) | ❌ needs verification |

**Form8825 open item detail:**
The `Form8825_namespace.json` sequential fids `f1`, `f2`, … normalize to `F001`, `F002`…
under `irsForm._normalizeFid()`.  The `_build_f8825_filldict()` returns keys like `F023`
(Line 2a, Prop A gross rents), `F024` (Prop B), etc.  For the `BookToIRS.regenerate()`
merge to work, field `f23` in the namespace must correspond to Form 8825 Line 2a,
Column A.  **This alignment must be verified against the IRS PDF AcroForm order before
declaring Form8825 complete.**

### Sch_K1 — STARTING STATE
| Item | Status |
|------|--------|
| `irs/Sch_K1.py` exists (old Form1065 subclass architecture) | ✅ exists, needs extension |
| `Sch_K1_IRS.pdf` (137 AcroForm fields) | ✅ |
| `Sch_K1_namespace.json` (137 fields, no logicalKeys) | ✅ exists, logicalKeys blank |
| `Sch_K1_fillDict.json` (2 entries, 0 published) | ❌ effectively empty |
| `irsFormFieldNames.py` → `irsSchKFields` class | ✅ K-1 field definitions exist |
| `bookNS_IS.json` Sch_K1 section | ⚠️ 5 entries, partnership-level totals (not per-partner) |
| `stmtIS_TaxMember` class | ❌ does not exist |
| Per-partner FILL PDFs | ❌ none generated via v0.3 pipeline |
| Legacy per-partner PDFs (F1065_K1/YE/) | ✅ 3 PDFs from old pipeline — for reference only |

---

## 2. Architecture Decision

### Single-form-multiple-partner pattern
Unlike Form1065 / Form8825 (one PDF per LLC), Sch_K1 produces **one PDF per partner**.
The shared namespace (`Sch_K1_namespace.json`) maps field IDs to logical keys once.
Each partner's `loadFillDict('Sch_K1')` substitutes their specific values.

```
Sch_K1_IRS.pdf  →  _buildNSpace()  →  Sch_K1_namespace.json   (shared)
                                    ↓
                    stmtIS_TaxMember(partner_idx=0).loadFillDict('Sch_K1')
                    stmtIS_TaxMember(partner_idx=1).loadFillDict('Sch_K1')
                    stmtIS_TaxMember(partner_idx=2).loadFillDict('Sch_K1')
                                    ↓
                    Sch_K1_FILL_o20250801_1.pdf   (Francis  96%)
                    Sch_K1_FILL_o20250801_2.pdf   (Alexandra 2%)
                    Sch_K1_FILL_o20250801_3.pdf   (Nicola    2%)
```

### Data encapsulation rule (per issue #4)
The K-1 value mapping lives entirely in `ledger/stmtIS.py` via
`stmtIS_TaxMember._build_k1_filldict()`.  **No mapping logic in `ui/` or `irs/`.**
`irs/Sch_K1.py` delegates to `stmtIS_TaxMember` for values — it handles only
PDF I/O (namespace, fill, save).

### bookNS_IS.json role for Sch_K1
`bookNS_IS.json` Sch_K1 section remains as a documentation artifact for the
Aid UI (field advisor chips).  The runtime fill values come from
`stmtIS_TaxMember.loadFillDict('Sch_K1')`, **not** from the bookNS JSON lookup.

---

## 3. Task List

Tasks are ordered; each phase depends on the previous.

---

### Phase 0 — Form8825 Completion (prerequisite)

**T0.1 — Verify Form8825 fid alignment**
- Load `Form8825_namespace.json`, list fields f1…f221 with their AcroForm path
- Cross-check: `f23` → should be `Table_Line2a[0].Col_a` (Gross Rents, Prop A)
- Tool: `python3 -c "import json; ..."`  or a small script in `irs/taxAgents/`
- If misaligned: update `_build_f8825_filldict()` base fids or create
  `Form8825_FieldNames.json` mapping logical keys (F023) to sequential fids

**T0.2 — Run Form8825 end-to-end and inspect FILL.pdf**
- `BookToIRS(llc, 'Form8825').regenerate()` → `Form8825_FILL.pdf`
- Open PDF, verify: H_805HighMesa in Column A, RV_RV1 in Column B
- Verify F031 (income subtotal), F095 (expense subtotal), F099 (net income) per property
- Verify F103 (total rental income), F104 (total rental expense), F113 (total net)
- Document any field mismatches → fix in `_build_f8825_filldict()` or bookNS

**T0.3 — Sync Form8825_IRS.pdf to worktree if missing**
- Copy from main repo `pages/AccountingData/2025/YE_Tax_Records/Forms_IRS/`
- Confirm `BookToIRS(llc, 'Form8825')._formClass()` resolves correctly

---

### Phase 1 — K-1 Field Name Mapping

**T1.1 — Map Sch_K1 AcroForm short names to logical keys**
- The K-1 IRS PDF uses `f1_1[0]`, `f1_2[0]`… (137 leaf fields)
- `irsFormFieldNames.py` already has `irsSchKFields` with K-1 section definitions (P1/P2/P3)
- Create `Sch_K1-FieldNames.json` in `Forms_IRS/`: `{ "f1_1": "P1_Hdr_0", "f1_34": "P3_1", ... }`
- Target mapping (from AcroForm inspection and K-1 layout):

  ```
  Header (Page 1 Left):
    f1_1..f1_5   → tax year / header fields
    f1_6         → P2_E  (Partner EIN/SSN)
    f1_7         → P2_F_line1  (Partner name line 1)
    ...
    f1_14        → P2_J_P_Beg  (Profit % beginning)
    f1_15        → P2_J_P_End  (Profit % end)
    f1_16, f1_17 → Loss % beg/end
    f1_18, f1_19 → Capital % beg/end
    f1_26..f1_31 → L_Beg, L_CapContrib, L_CInc, L_Other, L_Wdwl, L_EndCao
    f1_34        → P3_1   (Box 1: Ordinary income)
    f1_35        → P3_2   (Box 2: Net rental RE income)
    f1_39        → P3_5   (Box 5: Interest income)
    ...          → P3_19  (Box 19: Distributions)
  ```

- NOTE: exact field-to-box correspondence must be verified by opening the
  AcroForm structure (pypdf walk) and cross-referencing the K-1 printed form layout.

**T1.2 — Populate Sch_K1_namespace.json logicalKeys (optional for pipeline)**
- Run `irsForm._buildNSpace()` on Sch_K1 with the FieldNames JSON loaded
- This gives `Sch_K1_namespace.json` with logicalKeys set
- Required only if the Aid UI (BookToIRS advisor chips) needs K-1 support
- The runtime fill pipeline (`_build_k1_filldict`) does not need logicalKeys

---

### Phase 2 — stmtIS_TaxMember (ledger/stmtIS.py)

**T2.1 — Add `stmtIS_TaxMember` class to `ledger/stmtIS.py`**

```python
class stmtIS_TaxMember(stmtIS_Tax):
    '''
    Per-partner K-1 provisioning view.

    Wraps stmtIS_Tax with a single partner's pct applied to all IS aggregates.
    loadFillDict('Sch_K1') returns the complete per-partner fill dict inline
    (same pattern as stmtIS_Tax._build_f8825_filldict for Form8825).
    '''
    def __init__(self, llc, partner_idx: int = 0,
                 owners: Optional[List[Dict]] = None):
        super().__init__(llc)
        self._partner_idx = partner_idx
        self._owners_override = owners  # None = load from llcOwners

    def _load_owners(self) -> List[Dict]:
        if self._owners_override is not None:
            return self._owners_override
        # load from llcOwners_<llcName>.json
        from ledger.llcOwners import llcOwners
        return llcOwners(self.llc).owners()

    def _partner(self) -> Dict:
        owners = self._load_owners()
        if self._partner_idx >= len(owners):
            raise IndexError(f"partner_idx={self._partner_idx}, only {len(owners)} partners")
        return owners[self._partner_idx]

    def loadFillDict(self, formNm: str) -> Dict[str, Any]:
        if formNm == 'Sch_K1':
            return self._build_k1_filldict()
        return super().loadFillDict(formNm)

    def _build_k1_filldict(self) -> Dict[str, Any]:
        '''
        Build per-partner K-1 fill dict.

        Returns { 'F_K1_1': 0.0, 'F_K1_2': net_rental*pct, ... }
        Keys match Sch_K1 section of bookNS_IS.json + additional profile fields.
        '''
        partner = self._partner()
        pct     = float(partner.get('pct', 0))
        agg     = self.taxAggregates()   # partnership-level totals

        net_rental   = float(agg.get('net_rental',        0))
        net_ordinary = float(agg.get('net_ordinary',       0))
        interest     = float(agg.get('interest_income',    0))
        net_income   = float(agg.get('net_income',         0))
        distributions= float(agg.get('distributions_cash', 0))
        # contributions: sourced from BS capital section (see T2.2)
        contributions = self._partner_contributions(pct)

        p_box1    = round(net_ordinary   * pct, 2)   # 0 for rental-only
        p_box2    = round(net_rental     * pct, 2)
        p_box5    = round(interest       * pct, 2)
        p_net_inc = round(net_income     * pct, 2)
        p_distrib = round(distributions  * pct, 2)
        p_contrib = contributions                     # already × pct
        p_L6      = round(p_contrib + p_net_inc - p_distrib, 2)

        # Partner identification
        nm_list = partner.get('nm', [''])
        nm      = nm_list[0] if nm_list else ''
        addr    = partner.get('addr', '')
        ein     = partner.get('ein',  '')
        pct_str = f"{pct * 100:.1f}%"

        return {
            # Profile / header fields
            'F_K1_PartnerName':   nm,
            'F_K1_PartnerAddr':   addr,
            'F_K1_PartnerEIN':    ein,
            'F_K1_J_Profit':      pct_str,
            'F_K1_J_Loss':        pct_str,
            'F_K1_J_Capital':     pct_str,
            # Income boxes
            'F_K1_1':     p_box1    if p_box1    != 0 else None,
            'F_K1_2':     p_box2    if p_box2    != 0 else None,
            'F_K1_5':     p_box5    if p_box5    != 0 else None,
            'F_K1_14a':   None,       # passive rental — no SE earnings
            'F_K1_19a':   p_distrib if p_distrib != 0 else None,
            # Capital account (Box L)
            'F_K1_L1':    None,       # first year — beginning capital = 0
            'F_K1_L2':    p_contrib  if p_contrib != 0 else None,
            'F_K1_L3':    p_net_inc  if p_net_inc != 0 else None,
            'F_K1_L5':    p_distrib  if p_distrib != 0 else None,
            'F_K1_L6':    p_L6       if p_L6      != 0 else None,
        }

    def _partner_contributions(self, pct: float) -> float:
        '''
        Resolve partner's share of cash contributions.
        Sources: BS equity / capital contributions from llcAssets cash-in records.
        Placeholder — implement in T2.2.
        '''
        return 0.0
```

**T2.2 — Implement `_partner_contributions()` source**
- Cash contributions live in `llcAssets` (aType=Debit on Acct.Equity.Capital or similar)
- Options:
  - A: Read from `stmtBS_Tax.taxAggregates()` equity contribution total
  - B: Read directly from `llcProfile` owners `contributions` field if present
  - C: Read from `llcAssets` records filtered by `acct == 'Acct.Equity.Capital'`
- Recommended: Option C — sum of `amt` where `aType=Debit` and `acct=Acct.Equity.Capital`, multiply by `pct`
- Cross-check: sum across all partners must equal BS total equity contributions

**T2.3 — Update `bookNS_IS.json` Sch_K1 section (documentation only)**
- Replace the 5 partnership-level entries with the full per-partner mapping table
- Mark these as "computed per-partner by stmtIS_TaxMember" in the `_doc` note
- Do NOT rely on this JSON for runtime resolution (values come from `_build_k1_filldict`)

```json
"Sch_K1": [
  ["F_K1_1",          "IS.k1_box1"],
  ["F_K1_2",          "IS.k1_box2"],
  ["F_K1_5",          "IS.k1_box5"],
  ["F_K1_14a",        "IS.k1_box14a"],
  ["F_K1_19a",        "IS.k1_box19a"],
  ["F_K1_L2",         "IS.k1_L2"],
  ["F_K1_L3",         "IS.k1_L3"],
  ["F_K1_L5",         "IS.k1_L5"],
  ["F_K1_L6",         "IS.k1_L6"]
]
```

---

### Phase 3 — irs/Sch_K1.py Extension

**T3.1 — Extend `Sch_K1.saveFILL_allPartners()` to use `stmtIS_TaxMember`**
- Refactor to delegate value resolution to `stmtIS_TaxMember(partner_idx=i)`
- Retain existing PDF I/O (namespace load, saveFILL with suffix) unchanged
- Key method: `_build_k1_filldict_for_partner(partner_idx)` calls
  `stmtIS_TaxMember(self.llc, partner_idx=i).loadFillDict('Sch_K1')`
- This returns the logical-key-keyed dict; Sch_K1 maps it to PDF field names
  via the namespace logicalKey index built in Phase 1

**T3.2 — Output naming convention**
- `Sch_K1_FILL_o20250801_1.pdf`  (Francis)
- `Sch_K1_FILL_o20250801_2.pdf`  (Alexandra)
- `Sch_K1_FILL_o20250801_3.pdf`  (Nicola)
- Retain `Sch_K1_namespace.json` as single shared file (per issue requirement)

---

### Phase 4 — BookToIRS per-partner regeneration

**T4.1 — Extend `BookToIRS.regenerate()` for Sch_K1**
- When `self.formNm == 'Sch_K1'`:
  - Load owners from `llcOwners`
  - For each partner: call `stmtIS_TaxMember(self.llc, i).loadFillDict('Sch_K1')`
  - Merge with `form.loadFieldsDF()` (namespace)
  - Call `form.saveFILL_FromDF(df, suffix=f'_{oID}')` for each partner
  - Return `{ 'paths': [...], 'partners': [...] }` summary
- Alternatively: `BookToIRS.regenerate()` for Sch_K1 calls `form.saveFILL_allPartners()`
  which already wraps the per-partner loop (refactored in T3.1)

**T4.2 — Add `regenerate_all_k1()` convenience method**
```python
def regenerate_all_k1(self) -> List[Dict]:
    """Generate K-1 PDFs for all partners. Returns list of per-partner result dicts."""
    self.formNm = 'Sch_K1'
    return self.regenerate()
```

---

### Phase 5 — Execute, Verify, Iterate

**T5.1 — Run full pipeline**
```python
from ledger.LLC import LLC
from irs.BookToIRS import BookToIRS

llc = LLC('WBGroupLLC')
result = BookToIRS(llc, 'Sch_K1').regenerate()
print(result)
```

**T5.2 — Verification checklist**
- [ ] 3 PDFs generated (one per partner)
- [ ] Francis (96%): Box 2 = net_rental × 0.96
- [ ] Alexandra (2%): Box 2 = net_rental × 0.02
- [ ] Nicola (2%): Box 2 = net_rental × 0.02
- [ ] Sum of all Box 2 values = partnership net_rental (cross-check)
- [ ] Sum of all L6 values = total partnership equity (cross-check)
- [ ] Box 1 = $0 for all partners (rental-only LLC)
- [ ] Box 14a = blank for all partners (passive rental)
- [ ] Partnership EIN and name appear in header of all 3 PDFs
- [ ] Partner name/address/EIN correct in each PDF

**T5.3 — CPA flag documentation**
- Add `_CPA_NOTES_K1` entries in `Sch_K1.py` for boxes that need CPA review:
  - Box 17: AMT depreciation adjustment
  - Box 20: QBI / §199A information
  - Box 14a (Francis): SE earnings if ordinary income ever added

---

## 4. File Change Summary

| File | Change |
|------|--------|
| `ledger/stmtIS.py` | Add `stmtIS_TaxMember` class (T2.1, T2.2) |
| `irs/Sch_K1.py` | Extend `saveFILL_allPartners()` to use stmtIS_TaxMember (T3.1) |
| `irs/BookToIRS.py` | Extend `regenerate()` for Sch_K1 multi-partner case (T4.1) |
| `2025/bookNS_IS.json` | Update Sch_K1 section (documentation only, T2.3) |
| `2025/YE_Tax_Records/Forms_IRS/Sch_K1-FieldNames.json` | **NEW** — logical key map (T1.1) |
| `2025/YE_Tax_Records/Forms_IRS/Sch_K1_namespace.json` | Update logicalKeys (T1.2, optional) |
| `docs/PLAN_SchK1_v0.3.md` | This file |

Form8825 files (Phase 0 only):
| File | Change |
|------|--------|
| `2025/YE_Tax_Records/Forms_IRS/Form8825_IRS.pdf` | Sync to worktree if missing |
| `ledger/stmtIS.py` `_build_f8825_filldict()` | Fix if fid alignment wrong (T0.1) |

---

## 5. Risks & Open Questions

| Risk | Mitigation |
|------|-----------|
| Form8825 fid alignment may be off | T0.1 verification script before touching K-1 work |
| K-1 AcroForm field order ambiguous | Walk AcroForm path names against printed K-1 layout |
| Contributions source unclear (llcAssets vs llcProfile) | Review BS equity section; choose Option C |
| First year — beginning capital (L1) = 0 assumption | Correct for 2025; add note for future years |
| Francis SE exposure if ordinary income added later | Add CPA flag; no action needed for 2025 |
| Passive loss rules for Alexandra & Nicola | K-1 itself is correct; partner applies PAL rules on 1040 |

---

## 6. Iteration Plan

The issue notes "expect several iterations to refine the mapping." Recommended sequence:

1. **Iteration 1**: Get all 3 PDFs to generate (even if some fields blank). Focus on Box 2 and L3.
2. **Iteration 2**: Add header fields (EIN, name, address, percentages, year).
3. **Iteration 3**: Add capital account (L2, L5, L6) once contributions source resolved.
4. **Iteration 4**: CPA flags for Box 17, 20.
5. **Final**: Run BookToIRS.regenerate() from Flask UI → confirm PDF output in UI.

---

## 7. Reference

- IRS Instructions for Form 1065: https://www.irs.gov/instructions/i1065
- Partner's Instructions for Schedule K-1: https://www.irs.gov/instructions/i1065sk1
- IRC §1402(a)(1): rental income excluded from SE tax
- Treas. Reg. 1.199A-4: rental QBI safe harbor election
- Tax Basis Capital Accounts: IRS Rev. Proc. 2021-50, Form 1065 instructions p.38
- Expert consultation: Sch_K1 box mapping review — session 2026-05-09
