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

### 4.1 Critical Architectural Gap: Audit ↔ PDF Disconnection

**Root cause of issue #17:** The two pipelines — Agent Audit and FILL.pdf
generation — are completely disconnected. The Agent runs, finds issues, writes
`session_state.json`, and stops. The FILL.pdf is only regenerated when the
bookkeeper manually clicks the "Commit" button in the Aid UI.

If the books are corrected but "Commit" is not run, the FILL.pdf stays stale.
There is no signal from the Agent to the generation pipeline.

### 4.2 Gap Table

| Gap ID | Description | AS-IS | TO-BE | Priority |
|---|---|---|---|---|
| **G1** | No `run_agent()` method that generates FILL.pdf after audit | `run_phases_1_2()` stops at session_state.json | Add `run_agent()` = audit + `BookToIRS.regenerate()` + verify | P1 |
| **G2** | `suggested_mapping` not wired to Aid "Fix Mapping" UI button | Field exists in `format_issue()` but UI doesn't use it | Wire `suggested_mapping` → Aid dialog pre-population | P1 |
| **G3** | MACRS formula check is INFO, not ERROR | `F45M-R05` allows $10 discrepancy as INFO | If formula vs books > $10 AND books > $100: raise ERROR; books need correction | P1 |
| **G4** | LLCTaxAgent.phase1_prepare() not wired to Form agents | Method stub in LLCTaxAgent; FormXXXXAgent.run_phases_1_2() not called | Wire phase1_prepare() to call all four FormXXXXAgent.run_agent() | P2 |
| **G5** | UI "Run Agent" button exists but no "Generate PDF" step | `/api/tax/form8825/run` calls run_phases_1_2 only | Add `/api/tax/form8825/generate` route calling BookToIRS.regenerate() | P1 |
| **G6** | Stale FILL.pdf: books corrected but PDF not regenerated | FILL.pdf is cached from last explicit regeneration run | After any books save, flag affected form PDFs as stale; show banner in UI | P2 |
| **G7** | `_build_f8825_filldict()` vs `bookNS_IS.json` dual paths | Form8825 uses custom dynamic builder; other forms use bookNS | Clarify: Form8825 is intentionally dynamic (per-property multi-column); bookNS path is for static single-value forms | P3 (design clarity) |
| **G8** | Depreciation booked as $5,246.06 (wrong amount in books) | `Acct.Exp.Depreciation` balance may reflect old entry | Books need a correcting journal entry: reduce depr to $1,903.13 MACRS; reclassify $3,343 to repairs/safe-harbor | P0 (books correction, pre-code) |

### 4.3 Gap Details

**G1 (run_agent with PDF generation):**

```python
# TO-BE: add to Form8825Agent (and all FormXXXXAgents)
def run_agent(self) -> Dict[str, Any]:
    result = self.run_phases_1_2()          # existing: audit only
    if result['overall_state'] == self.GO:
        from irs.BookToIRS import BookToIRS
        aid = BookToIRS(self.llc, 'Form8825')
        pdf_result = aid.regenerate()       # generate FILL.pdf
        result['pdf'] = pdf_result
    return result
```

**G2 (suggested_mapping → Aid UI):**
- Form8825Agent issue F8EX-R02 sets `action = "Fix bookNS_IS.json..."` as a text string
- TO-BE: also set `suggested_mapping = {'fid': 'F079', 'src': 'IS', 'path': 'IS.depreciation'}`
- Flask route returns this; frontend opens Aid dialog pre-filled with the fix

**G3 (MACRS formula as ERROR):**
- Form4562Agent F45M-R05 is currently INFO severity
- TO-BE: if `abs(macrs_computed - IS.depreciation) > 10.0`: severity = ERROR
- Action text: "Correct books: journal entry to set Acct.Exp.Depreciation = ${macrs_computed:.2f}. Current books have ${IS.depreciation:.2f}."

**G5 (UI Generate PDF route):**
- Existing: `/api/tax/form8825/run` → returns audit result only
- TO-BE: add `POST /api/tax/form8825/generate` → calls `BookToIRS('Form8825').regenerate()`
- Or merge into run_agent: if audit passes, auto-generate and return pdf stats with audit result

**G8 (Books correction — P0, pre-code):**
This must be done BEFORE any code changes. The depreciation entry needs to reflect
the correct MACRS amount ($1,903.13 for August 2025, 27.5yr S/L mid-month) per the
Form4562Agent's formula verification. The incorrect $5,246.06 should be reclassified
to `Acct.Exp.Repair` (the Safe Harbor expensing account per design_BUS_04.8_IRS_Form4562_Notes.md §1.1.1).

This is a **books correction**, not a code change. It must be done through the LLC
editor (the Flask app) before running any agent or regenerating PDFs.

---

## 5. Proposed Action Items for STEP 4

In priority order, pending bookkeeper review and GO authorization:

| Item | What | Where | Effort |
|---|---|---|---|
| **A0** | **Books correction**: correct `Acct.Exp.Depreciation` to $1,903.13 MACRS; reclassify $3,343 to `Acct.Exp.Repair` | LLC editor (`llcExpRev_WBGroupLLC.json`) | Manual ledger entry |
| **A1** | Add `suggested_mapping` to Form8825Agent F8EX-R02 and Form4562Agent F45M-R04/R05 issues | `irs/taxAgents/Form8825Agent.py`, `Form4562Agent.py` | 0.5hr |
| **A2** | Add `run_agent()` to Form8825Agent and Form4562Agent (audit + BookToIRS.regenerate) | same files | 1hr |
| **A3** | Wire `suggested_mapping` → Aid dialog pre-population in Flask UI + frontend | `ui/llcMgmt.py`, `ui/templates/` | 2hr |
| **A4** | Add `/api/tax/form8825/generate` and `/api/tax/form4562/generate` routes | `ui/llcMgmt.py` | 0.5hr |
| **A5** | Elevate Form4562Agent F45M-R05 to ERROR when formula vs books discrepancy > $10 | `irs/taxAgents/Form4562Agent.py` | 0.5hr |
| **A6** | Wire LLCTaxAgent.phase1_prepare() to call all four FormXXXXAgent.run_agent() | `irs/taxAgents/LLCTaxAgent.py` | 1hr |
| **A7** | Add "stale PDF" banner to IRS form views (flag when books were saved after last FILL.pdf) | `ui/templates/`, `ui/llcMgmt.py` | 1.5hr |

**Total estimated code effort (A1–A7): ~7 hours**
**A0 must precede all others** — wrong books make all code fixes meaningless.

---

*End of design_BUS_04.0_TaxPrep.md — v1.0, 2026-06-04*
