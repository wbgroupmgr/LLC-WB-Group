# Tax Preparation — High-Level Design & Workflow

**Status:** v1.1 — 2026-06-04 (terminology, 11-step workflow, propNm rule added)
**Owner:** Francisco Rojas (W&B Group, LLC)

---

## 0. Terminology

Two terms are used precisely throughout all `design_BUS_04.*` documents:

| Term | Definition |
|---|---|
| **Workflow** | The end-to-end user scenario — everything the bookkeeper does from opening the app to filing. Described in §1 as an 11-step sequence. |
| **Pipeline** | A specific technical execution path within one step of the workflow. Examples: the *FILL.pdf pipeline* (§1 steps 4/10), the *audit pipeline* (§1 step 7), the *LLCTaxAgent pipeline* (§3.2). |

A **pipeline** is always subordinate to the **workflow**. The workflow calls pipelines; pipelines never define the workflow.

---

## 0.1 propNm Rule — Every Transaction Must Carry a Property Name

**This is a ledger data-integrity invariant for a rental LLC.** Every transaction in
every source DB (`llcAssets`, `llcExpRev`, `llcPayables`, `llcReceivables`) must have
a non-empty `propNm` field. Two values are allowed:

| Transaction type | `propNm` value | `propOwner` value |
|---|---|---|
| **Rental operations** — income, expenses, depreciation, or assets tied to a specific rental property | Property identifier (e.g., `"H_805HighMesa"`) | Property owner(s) identifier |
| **LLC ordinary operations** — entity-level expenses/revenue not attributable to a specific rental property (e.g., filing fees, bank charges) | `"LLC"` | `"LLC"` |

**Why this matters for IRS forms:** The Form 8825 FILL.pdf pipeline aggregates
transactions by `propNm` to build per-property columns (one column per property on the
form). Any transaction with `propNm = ""` or `null` is silently dropped from the Form
8825 fill dict — it does not appear on the form — even though it correctly appears in
the authoritative `stmtIS`/`stmtBS` views that aggregate without a propNm filter.

**The propNm rule prevents the two-path divergence problem** (see §4.1): if every
transaction has a valid `propNm`, the per-property pipeline and the aggregate pipeline
always produce consistent totals.

**Enforcement:** All ledger entry UI forms must require `propNm`. The `Form8825Agent`
audit rules check for missing `propNm` on depreciation entries (rule F8EX-R01 fires
when `fill_dict['F079']` is blank but `IS.depreciation > 0`).

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

## 3. Tax Preparation Workflow — End-to-End

The **Tax Preparation Workflow** is the complete user scenario from app start to a
correct, filed FILL.pdf. It consists of 11 steps. Steps 4, 7, and 10 each invoke a
distinct **pipeline** (a technical execution path). All other steps are UI interactions
or state transitions.

```
STEP 1  Start App
          → Flask app starts; eSession initialised with LLC data

STEP 2  User Edit / New Transaction
          → User enters or edits a transaction via the editor UI
          → DB updated (llcAssets / llcExpRev / llcPayables / llcReceivables)
          → GL re-derives from updated DB; stmtIS / stmtBS reflect new state
          ⚠ propNm MUST be set on every transaction (see §0.1)

STEP 3  Select IRS FormXXXX View
          → User navigates to /view/llcForm8825 (or 4562, 1065, K-1)
          → View loads: displays existing FILL.pdf (may be stale after step 2)

STEP 4  ── FILL.pdf Pipeline ──────────────────────────────────────────────
          → Triggered by: "⟳ Refresh FILL.pdf" button (or first page load if
            no PDF exists yet)
          → BookToIRS(llc, formNm).regenerate()
              stmtIS_Tax.loadFillDict(formNm)
                Form8825: _build_f8825_filldict() — per-property from GL records
                Others:   bookNS_IS.json static mapping → UAS path resolution
              → fill DataFrame → form.saveFILL_FromDF() → FormXXXX_FILL.pdf

STEP 5  Display View
          → iframe renders the freshly generated FormXXXX_FILL.pdf
          → stat chips show IS.depreciation, IS.rent_income, IS.net_rental
            (from taxAggregates() — ALWAYS the authoritative values)

STEP 6  Select "Run Agent"
          → User clicks "▶ Run Form Agent" button in the agent status strip

STEP 7  ── Form Audit Pipeline ────────────────────────────────────────────
          → FormXXXXAgent.run_phases_1_2()
              Pass 0: Inventory (active properties, placed-in-service dates)
              Pass 1: Auto-Fill — loadFillDict(formNm) — same data as step 4
              Pass 2: Audit — IRS compliance rules per section agent
                  e.g. F8EX-R01: fill_dict['F079'] == IS.depreciation?
                  e.g. F45M-R05: MACRS formula amount == IS.depreciation?
              → session_state.json written
              → issues list: [{rule_id, severity, message, fids,
                               suggested_mapping, action}]
          → Agent strip shows GO / NEEDS_FIXING badges per section
          → Guided Review page available if any issues found

STEP 8  UI Interactions — Issue Resolution
          → For each ERROR/WARN issue, bookkeeper has two correction paths:

          PATH A — Books correction (propNm or amount wrong in the ledger):
            → UI shows transactions tDB/tID that needs editing. 
            → Open ledger editor → fix the transaction (propNm, amount, acct)
            → DB updated → GL updated → stmtIS reflects new value
            → Return to STEP 4 (Refresh FILL.pdf) to see corrected value
            → fix next error

          PATH B — BookToIRS mapping correction (wrong fid→UAS mapping):
            → Click "🛠 Aid" → Aid dialog opens for the flagged fid
                → FIXME: need better Aid, 
                → instead of a single Form Field, show table of all fields per section agent that
                → edit UI table and submit --> updates bookNS entry or custom map
            → Save persists to bookNS_*.json immediately
            → fix next error

STEP 9  Submit Bookkeeper Dialog
          → "Commit" in bookkeeper UI calls BookToIRS.regenerate() (same as step 4)
          → After resolving all ERRORs, bookkeeper acknowledges the session
          → session_state.json updated to GO

STEP 10 ── FILL.pdf Pipeline (repeat) ─────────────────────────────────────
          → Same as STEP 4: Refresh FILL.pdf after all corrections applied
          → "⟳ Refresh FILL.pdf" button OR automatic after Aid "Done"

STEP 11 Display View (corrected)
          → iframe renders updated FormXXXX_FILL.pdf with correct values
          → Stat chips confirm values match books
          → LLCTaxAgent cross-form audit can now compare all completed forms
```

### 3.1 FILL.pdf Pipeline Detail (Steps 4 and 10)

Single entry point for ALL forms: `BookToIRS(llc, formNm).regenerate()`

```
BookToIRS(llc, 'Form8825').regenerate()           ← ONE entry point, any formNm
  │
  ├── stmtIS_Tax(llc).loadFillDict('Form8825')
  │     └── Form8825 (special case): _build_f8825_filldict()
  │           → _aggregate_by_property(gl_records)   ← per-property layout
  │           ⚠ REQUIRES propNm on each GL record (see §0.1 propNm rule)
  │           ⚠ Silent-drop bug: entries with propNm='' are skipped (see G8)
  │     └── Other forms: bookNS_*.json → UAS path resolution
  │           → taxAggregates() or acct_balance() via _resolve_acct()
  │
  ├── stmtBS_Tax / stmtProfile / stmtGL_Tax (via BookToIRS priority resolver)
  │
  ├── Build fill DataFrame → form.saveFILL_FromDF(df) → FormXXXX_FILL.pdf
  │
  └── Returns: { fill_path, filled, check, complex, blank, ts }
```

**Two-path problem (to be resolved — see G9):** The Form8825 path uses
`_aggregate_by_property()` which groups by `propNm` and can produce values that
diverge from `taxAggregates()` (the authoritative source). All other forms resolve
dollar values through `taxAggregates()` or direct UAS path lookup — both of which
are propNm-agnostic. The fix (G8 fallback + G9 unification) is described in §4.3.

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
| **G9** | Two aggregation paths can diverge: `_build_f8825_filldict()` vs `taxAggregates()` | Form8825 uses propNm-keyed aggregation; all other forms use propNm-agnostic UAS resolution | Unify: `_build_f8825_filldict()` must get dollar values from `taxAggregates()` (authoritative); only use `_aggregate_by_property` for column PLACEMENT (which property in which column) | P1 |
| **G10** | Refresh FILL.pdf button missing from all IRS form views | Bookkeeper must open Aid dialog and click "Commit" to regenerate | ✅ DONE 2026-06-04: "⟳ Refresh FILL.pdf" added to pdf-toolbar and Actions menu in `irs_pdf_view.html` | DONE |

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
| **A2b** | Unify paths (G9): refactor `_build_f8825_filldict()` to use `taxAggregates()` for dollar values; `_aggregate_by_property()` for column assignment only | `ledger/stmtIS.py` | 2hr |
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
