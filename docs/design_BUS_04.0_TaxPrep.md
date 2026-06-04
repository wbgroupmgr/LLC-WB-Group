# Tax Preparation — High-Level Design & Workflow

**Status:** v1.0 — 2026-06-04 (created per GitHub issue #17; Steps 1–3)
**Owner:** Francisco Rojas (W&B Group, LLC)

---

## 1. Document Inventory — `design_BUS_04.*`

All tax-preparation design documents live under `docs/` using the `BUS_04.*` namespace.
**Reorganized 2026-06-04** per issue #17 from the original flat `04.0-*` naming.

| File | Tier | Purpose |
|---|---|---|
| `design_BUS_04.0_TaxPrep.md` | Overview | **THIS FILE** — HL workflow, TO-BE design, gap analysis |
| `design_BUS_04.2_LLCTaxAgent.md` | Tier 0 | Master coordinator: cross-form audit, submission package |
| `design_BUS_04.6_Form1065Agent.md` | Tier 1 | Form 1065 (5-page return) orchestrator + section agents |
| `design_BUS_04.6_Form8825Agent.md` | Tier 1 | Form 8825 (rental income/expenses) orchestrator + section agents |
| `design_BUS_04.6_Form4562Agent.md` | Tier 1 | Form 4562 (depreciation) orchestrator + section agents |
| `design_BUS_04.6_FormSchK1Agent.md` | Tier 1 | Schedule K-1 (per-partner) orchestrator + section agents |
| `design_BUS_04.8_BookToIRS_Aid.md` | Tier 4 | BookToIRS Aid UI (mapping CRUD dialog) — generation service |
| `design_BUS_04.8_Tax_BookToIRS.md` | Tier 4 | BookToIRS original design notes |
| `design_BUS_04.8_IRS_Form4562_Notes.md` | Reference | Form 4562 IRS/accounting notes (depreciation treatment) |
| `design_BUS_04.8_IRS_SchK1_Notes.md` | Reference | Schedule K-1 IRS notes |

**Tier numbering rationale (from design_BUS_04.2_LLCTaxAgent.md):**

```
04.2 → LLCTaxAgent     (Tier 0 in code = "master coordinator")
04.6 → FormXXXXAgents  (Tier 1/2 in code = "form orchestrators + section agents")
04.8 → BookToIRS       (Tier 3/4 in code = "common services + generation")
```

---

## 2. Four-Tier Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Tier 0  LLCTaxAgent (design_BUS_04.2)                         │
│    phase1_prepare   — drive all FormXXXXAgents                 │
│    phase2_xf_audit  — cross-form equality checks (XF-R01..R05) │
│    phase3_package   — assemble IRS_Submission_{year}/          │
│    phase4_submit    — checklist + K-1 delivery tracking        │
└──────────────────────┬─────────────────────────────────────────┘
                       │ orchestrates
                       ▼
┌────────────────────────────────────────────────────────────────┐
│  Tier 1  FormXXXXAgents (design_BUS_04.6_Form*.md)            │
│    Form8825Agent   / Form4562Agent / Form1065Agent / SchK1Agent│
│    run_phases_1_2(): Pass 0 inventory → Pass 1 auto-fill →    │
│                       Pass 2 audit → session_state.json        │
└──────────────────────┬─────────────────────────────────────────┘
                       │ inherits from
                       ▼
┌────────────────────────────────────────────────────────────────┐
│  Tier 2  Section Agents (inside each FormXXXXAgent file)       │
│    AgentF8825_Properties / Income / Expenses / NetIncome       │
│    AgentF4562_Sec179 / MACRS / Summary                         │
│    AgentF1065_Info / IncStmt / Other / Distr / Reconcile / Ext │
└──────────────────────┬─────────────────────────────────────────┘
                       │ inherits from
                       ▼
┌────────────────────────────────────────────────────────────────┐
│  Tier 3  IRSFormsAgent (irs/taxAgents/IRSFormsAgent.py)        │
│    format_issue() / state_from_issues() / _forms_dir()         │
└──────────────────────┬─────────────────────────────────────────┘
                       │ calls
                       ▼
┌────────────────────────────────────────────────────────────────┐
│  Tier 4  BookToIRS (irs/BookToIRS.py) + stmtIS_Tax / stmtBS_Tax│
│    loadFillDict()   → reads bookNS_*.json + CustomMapDict      │
│    regenerate()     → builds fill DataFrame → saveFILL_FromDF()│
│    irs.Form8825.saveFILL_FromDF() → Form8825_FILL.pdf          │
└────────────────────────────────────────────────────────────────┘
```

**Books-First invariant (IRC §446 + §703):** Every IRS form value must be sourced
from `stmtIS.taxAggregates()` / `stmtBS.taxAggregates()` / `llcAssets` / `llcProfile`.
No form may read values from another form. Cross-form audit (Tier 0) verifies that
independently books-derived values agree after the fact.

---

## 3. TO-BE Tax Preparation Workflow

### 3.1 Books-to-PDF Pipeline (single form)

The intended end-to-end flow for any form (e.g., Form 8825):

```
Books (Accts/*.json)
        │
        ▼  stmtIS(llc).taxAggregates()
Books values available: IS.depreciation=$1903, IS.rent_income=$4000, ...
        │
        ▼  FormXXXXAgent.run_phases_1_2()
  Pass 0: inventory (active properties, partner count, etc.)
  Pass 1: auto-fill — stmtIS_Tax.loadFillDict('FormXXXX')
          → _build_f8825_filldict() reads GL records per property
          → fill_dict built from Acct.Exp.Depreciation, Acct.Rev.Rent, ...
  Pass 2: audit — IRS compliance rules per section agent
          → F8EX-R02: fill_dict['F079'] == IS.depreciation?  ← BOOKS CHECK
          → F45M-R05: MACRS formula amount == IS.depreciation? ← FORMULA CHECK
          → issues: [{rule_id, severity, message, suggested_mapping}]
  ──► If all ERRORs resolved: session_state = GO
        │
        ▼  [TO-BE GAP: this step must be added]
  Pass 4: generate FILL.pdf — BookToIRS.regenerate('FormXXXX')
          → stmtIS_Tax.loadFillDict('FormXXXX')  [same books, fresh read]
          → form.saveFILL_FromDF(df) → Form8825_FILL.pdf
  Pass 5: verify — read back FILL.pdf field values
          → confirm F079 == IS.depreciation
          → if match: DONE; if not: NEEDS_FIXING (re-audit)
        │
        ▼
  Form8825_FILL.pdf on disk with correct books values
```

### 3.2 Full LLCTaxAgent Cycle (all forms)

```
LLCTaxAgent.phase1_prepare()
  │
  ├── Form4562Agent.run_agent()   [TO-BE: includes generate_pdf]
  │     audit + generate Form4562_FILL.pdf
  ├── Form8825Agent.run_agent()   [TO-BE: includes generate_pdf]
  │     audit + generate Form8825_FILL.pdf
  ├── Form1065Agent.run()         [already generates PDF]
  │     audit + generate Form1065_FILL.pdf
  └── FormSchK1Agent.run_agent()  [TO-BE: includes generate_pdf]
        audit + generate Sch_K1_o{oID}_FILL.pdf × N partners
        │
        ▼
LLCTaxAgent.phase2_xf_audit()
  XF-R01: Form4562 Line 22 == Form8825 Line 14 == IS.depreciation
  XF-R02: Form8825 Line 21 == IS.net_rental == Schedule K Line 2
  XF-R03: Schedule K Line 2 × partner% == each K-1 Box 2
  XF-R04: Sum of K-1 Box 2 == Schedule K Line 2
  XF-R05: Form 1065 Page1 Lines 1–23 all $0 (pure rental LLC)
        │
        ▼
LLCTaxAgent.phase3_package()
  → IRS_Submission_{year}/ directory with all PDFs + manifest.json
```

### 3.3 Guided Review UI Flow (bookkeeper-facing)

```
UI: "Run Agent" button on /view/llcForm8825
  → POST /api/tax/form8825/run
    → Form8825Agent.run_phases_1_2()
    → return session_state (issues, state)

UI: shows issues panel
  For each ERROR issue:
    → "Fix Mapping" button → opens Aid dialog for issue.fids[0]
      (pre-populated with issue.suggested_mapping: {fid, src, path})
    → bookkeeper confirms/edits mapping → saves to bookNS_*.json
    → "Re-run Audit" revalidates

UI: all issues resolved → "Generate PDF" button active
  → POST /api/tax/form8825/generate
    → BookToIRS('Form8825').regenerate()
    → returns { fill_path, filled, blank, ts }
  → FILL.pdf iframe refreshes
```

---

## 4. Gap Analysis — AS-IS vs TO-BE

The following gaps were identified by comparing the existing implementation
against the TO-BE workflow described in §3. Each gap maps to an action item.

### 4.1 Critical Architectural Gap: Two Aggregation Paths That Can Diverge

**Root cause of issue #17 (corrected 2026-06-04):**

The books ARE authoritative and contain the correct value ($1,903.13 in
`Acct.Exp.Depreciation`). The BS and IS views read this correctly.

The problem is that the Form8825 FILL.pdf pipeline uses a **different aggregation
path** from every other display — one with a hidden `propNm` requirement — that
can silently produce a different result from the authoritative books.

**Two paths from the same books:**

```
Books (Acct.Exp.Depreciation = $1,903.13)
  │
  ├── Path A: stmtIS._aggregate_is_pandas()        [groups by acctType+acct+acctSub]
  │           → IS.depreciation = $1,903.13        ← correct, propNm-agnostic
  │           Used by: BS view, IS view, taxAggregates(), FormXXXXAgent audit
  │
  └── Path B: stmtIS._build_f8825_filldict()       [groups by acctType+acct+propNm]
              line 652: if not propNm: continue    ← SILENT DROP if propNm empty
              → F079 = blank                       ← wrong, propNm-dependent
              Used by: Form8825 FILL.pdf generation only
```

**If the depreciation ledger entry (in `llcAssets_WBGroupLLC.json`) has
`propNm` empty or missing, Path B silently drops it.** The FILL.pdf shows
blank/zero for Line 14 even though the books contain $1,903.13.

**Secondary gap:** The Form8825Agent audit (F8EX-R01) does detect this: it
compares `fill_dict['F079']` (Path B, blank) against `IS.depreciation` (Path A,
$1,903) and fires an ERROR. But the action text says "Verify bookNS_IS.json..." —
which is wrong. Form8825 completely bypasses `bookNS_IS.json` and uses the
dynamic builder. The agent identifies the symptom but gives the wrong fix.

**Stale FILL.pdf (secondary gap):** Even if propNm is correctly set, the
FILL.pdf on disk was generated before the books were last updated. There is no
mechanism to detect staleness or trigger regeneration when books change.

> **Note on G8 retraction:** An earlier draft of this document incorrectly
> asserted that the books had the wrong depreciation amount ($5,246.06) based
> on a historical note in `design_BUS_04.8_IRS_Form4562_Notes.md` §1.1.1
> ("CORRECTION NEEDED: $5,246.06"). That note documented a past correction
> that was already made. The books are at $1,903.13 (MACRS correct). The
> "wrong value" in the FILL.pdf comes from the propNm gap, not from bad books.

### 4.2 Gap Table

| Gap ID | Description | AS-IS | TO-BE | Priority |
|---|---|---|---|---|
| **G1** | No `run_agent()` method that generates FILL.pdf after audit | `run_phases_1_2()` stops at session_state.json | Add `run_agent()` = audit + `BookToIRS.regenerate()` + verify | P1 |
| **G2** | `suggested_mapping` not wired to Aid "Fix Mapping" UI button | Field exists in `format_issue()` but UI doesn't use it | Wire `suggested_mapping` → Aid dialog pre-population | P1 |
| **G3** | F8EX-R01 action text points to bookNS_IS.json — wrong for Form8825 | Agent says "check bookNS_IS.json" but Form8825 uses dynamic builder | Fix action text: "Check propNm on depreciation entry in llcAssets JSON" | P1 |
| **G4** | `propNm` missing on depreciation ledger entry → F079 blank in FILL.pdf | `_build_f8825_filldict()` silently drops entries with empty propNm | Add `propNm: "H_805HighMesa"` to depreciation entry in `llcAssets_WBGroupLLC.json` | P0 (data fix, verify first) |
| **G5** | Stale FILL.pdf: books updated but regenerate() never called | FILL.pdf is cached from last explicit run | After any books save, flag affected form PDFs as stale; show banner in UI | P2 |
| **G6** | MACRS formula check is INFO, not ERROR | `F45M-R05` allows $10 discrepancy as INFO | If formula vs books > $10 AND books > $100: raise ERROR | P2 |
| **G7** | LLCTaxAgent.phase1_prepare() not wired to Form agents | Method stub; FormXXXXAgent.run_phases_1_2() not called | Wire phase1_prepare() to call all four FormXXXXAgent.run_agent() | P2 |
| **G8** | `_build_f8825_filldict()` propNm-filter has no fallback | Silent zero when propNm missing — no warning, no fallback | Add fallback: if no per-property depr found, use IS.depreciation across single property | P1 |

### 4.3 Gap Details

**G4 (propNm missing on depreciation entry — P0 diagnostic + data fix):**

Depreciation in `llcAssets_WBGroupLLC.json` has the correct amount ($1,903.13)
but the entry may have `"propNm": ""` or `null`. Verify by checking the JSON:

```json
// Expected (correct):
{ "acct": "Acct.Exp.Depreciation", "amt": 1903.13, "propNm": "H_805HighMesa", ... }

// Likely actual (broken):
{ "acct": "Acct.Exp.Depreciation", "amt": 1903.13, "propNm": "", ... }
```

Fix: set `"propNm": "H_805HighMesa"` on the depreciation entry through the LLC editor.

**G8 (propNm fallback in `_build_f8825_filldict()` — P1 code fix):**

Even after the data fix (G4), the code should not silently drop entries:

```python
# stmtIS._build_f8825_filldict() — after building prop_vals from propNm-keyed entries
# If depreciation account has no propNm but there is exactly one active property,
# assign the depreciation to that property (single-property LLC rule):
if not any('depreciation' in pv for pv in prop_vals.values()):
    depr_total = self.taxAggregates().get('depreciation', 0.0)
    if depr_total > 0 and len(prop_vals) == 1:
        only_prop = next(iter(prop_vals))
        prop_vals[only_prop]['depreciation'] = depr_total
```

**G1 (run_agent with PDF generation):**

```python
# TO-BE: add to Form8825Agent (and all FormXXXXAgents)
def run_agent(self) -> Dict[str, Any]:
    result = self.run_phases_1_2()          # existing: audit only
    if result['overall_state'] == self.GO:
        from irs.BookToIRS import BookToIRS
        pdf_result = BookToIRS(self.llc, 'Form8825').regenerate()
        result['pdf'] = pdf_result
    return result
```

**G3 (F8EX-R01 wrong action text — fix in Form8825Agent):**
- Current: `action = "Verify bookNS_IS.json maps IS.depreciation → F079"`
- Fix: `action = "Check propNm on Acct.Exp.Depreciation entry in llcAssets JSON. Form8825 uses dynamic builder — bookNS_IS.json is NOT used for Form8825."`

**G2 (suggested_mapping → Aid UI):**
- Add `suggested_mapping = {}` (no bookNS fix needed for Form8825)
- Instead, surface a direct link to the ledger entry editor for the depreciation line

---

## 5. Proposed Action Items for STEP 4

In priority order, pending bookkeeper review and GO authorization:

| Item | What | Where | Effort |
|---|---|---|---|
| **A0** | **Diagnose + data fix**: inspect `llcAssets_WBGroupLLC.json` depreciation entry; set `propNm: "H_805HighMesa"` if missing | LLC editor or direct JSON edit | ~15 min |
| **A1** | Fix F8EX-R01 action text: replace "bookNS_IS.json" with "check propNm on depreciation entry" | `irs/taxAgents/Form8825Agent.py` | 0.5hr |
| **A2** | Add fallback in `_build_f8825_filldict()`: if no per-property depr found and single property, use `taxAggregates()['depreciation']` | `ledger/stmtIS.py` | 1hr |
| **A3** | Add `run_agent()` to Form8825Agent and Form4562Agent (audit + BookToIRS.regenerate) | `irs/taxAgents/Form8825Agent.py`, `Form4562Agent.py` | 1hr |
| **A4** | Add `/api/tax/form8825/generate` and `/api/tax/form4562/generate` routes | `ui/llcMgmt.py` | 0.5hr |
| **A5** | Elevate Form4562Agent F45M-R05 to ERROR when formula vs books discrepancy > $10 | `irs/taxAgents/Form4562Agent.py` | 0.5hr |
| **A6** | Wire LLCTaxAgent.phase1_prepare() to call all four FormXXXXAgent.run_agent() | `irs/taxAgents/LLCTaxAgent.py` | 1hr |
| **A7** | Add "stale PDF" banner to IRS form views (flag when books were saved after last FILL.pdf) | `ui/templates/`, `ui/llcMgmt.py` | 1.5hr |

**Total estimated code effort (A1–A7): ~6 hours**
**A0 is the immediate diagnostic step** — verify propNm first before any code changes.
A2 is the defensive code fix that prevents this class of silent-drop from recurring.

---

*End of design_BUS_04.0_TaxPrep.md — v1.0, 2026-06-04*
