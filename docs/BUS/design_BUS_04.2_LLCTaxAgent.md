# LLCTaxAgent — Design Document

**Status:** v0.4 — revised 2026-06-03 (Books-First Rule; cross-form audit semantics clarified; graph edges reframed as expected-equality assertions, not data-flow wiring)
**Owner:** Francisco Rojas (W&B Group, LLC)
**Baseline docs:**
- `docs/design_BUS_04.0-Form1065Agent.md` — Form 1065 orchestration agent and section agents
- `docs/design_BUS_04.1-Tax_BookToIRS.md` — BookToIRS Aid tool (existing implementation)
- `docs/design_BUS_01-AccountingWorkflow.md` — Tax Preparation within the Levels of Accounting
- IRS Form 1065 Instructions (2024), Pub 541 (Partnerships), Pub 925 (Passive Activity)

---

## 1. Purpose and Scope

The **LLCTaxAgent** is the **master tax compliance coordinator** for the LLC. It sits above all form-specific agents and operates in two modes:

- **Year-round (non-tax season):** Continuously monitors the financial books for changes that will impact tax preparation — running the pipeline in draft mode to surface issues early, before tax season pressure.
- **Tax season (Jan 1 → filing deadline):** Drives the **Form1065Agent** through its complete pipeline, then performs **cross-form validation**, assembles the final **IRS Submission Package**, and guides the bookkeeper through IRS submission.

The LLCTaxAgent is the system's "LLC accountant." It does not fill individual form fields — that is the Form1065Agent's job. It ensures the complete package is internally consistent, every required document is present, and the bookkeeper knows exactly what to submit and when.

### 1.1 Boundary with Form1065Agent

This boundary is precise and must not drift:

| Responsibility | LLCTaxAgent | Form1065Agent |
|---|---|---|
| Year-round tax health monitoring | ✓ | — |
| Drive section agents through 5-pass workflow | — | ✓ |
| Fill individual form fields (fids) | — | ✓ (section agents) |
| Source all form values from Financial Books | — | ✓ (Books-First Rule — see Form1065Agent §0) |
| Validate a single form's internal consistency | — | ✓ (section agent rules) |
| Validate **across completed forms** — check that independently books-derived values agree | ✓ | — |
| Assemble combined IRS Submission Package | ✓ | — |
| IRS submission HOWTO, tracking, communication | ✓ | — |
| MeF / e-file XML generation (future) | ✓ | — |

> **Cross-form validation is not data wiring.** When LLCTaxAgent compares Form 4562 Line 22 against Form 8825 Line 14, it is checking that two forms filled independently from the books agree — not that one form is the data source for the other. A mismatch always indicates a books-mapping error in one or both forms.

### 1.2 Position in the Levels of Accounting

The LLCTaxAgent operates at **Level 4 — Tax Preparedness** of the LLC Accounting Workflow (`design_BUS_01-AccountingWorkflow.md`). It activates after Level 3 (Analytical — financial statements closed) and feeds Level 5 (Strategic) with the completed tax picture.

```
Level 1  Transactional   ← bank / AP / AR / assets
Level 2  Book            ← GL reconciliation, COA accuracy
Level 3  Analytical      ← IS / BS / GL reports (stmtIS, stmtBS, stmtGL)
Level 4  Tax Preparedness ← LLCTaxAgent + Form1065Agent + Section Agents  ← HERE
Level 5  Strategic       ← CFO/controller decisions informed by tax outcome
Level 6  Verification    ← audit trail, CompletionReport, IRS correspondence
```

---

## 2. System Architecture — Four Tiers

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Flask UI Layer                              │
│   Home Page → [Tax Preparation] view  (year-round status panel)    │
│   /view/tax_prep  →  LLCTaxAgent dashboard                          │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ invokes
                                   ▼
╔═════════════════════════════════════════════════════════════════════╗
║  TIER 0 — LLCTaxAgent  (irs/LLCTaxAgent.py)        MASTER COORD.  ║
║                                                                     ║
║  Year-round:                                                        ║
║    monitor()         — draft pipeline, catch issues early           ║
║    tax_calendar()    — key date tracking + advance alerts           ║
║                                                                     ║
║  Tax season:                                                        ║
║    phase1_prepare()  — invoke Form1065Agent.phase1–3 pipeline       ║
║    phase2_xf_audit() — cross-form validation (DAG-ordered)          ║
║    phase3_package()  — assemble IRS Submission Package              ║
║    phase4_submit()   — submission HOWTO, tracking, communication    ║
╚═══════════════════════════════════════╦═════════════════════════════╝
                                        │ delegates to
                                        ▼
╔═════════════════════════════════════════════════════════════════════╗
║  TIER 1 — Form1065Agent  (irs/Form1065Agent.py)     FORM ORCH.     ║
║                                                                     ║
║  phase1_prepare()  — drive section agents through Passes 1–3       ║
║  phase2_publish()  — drive section agents through Pass 4            ║
║  phase3_summary()  — drive section agents through Pass 5            ║
║  → delivers: Form PDFs + IRS_Form1065_{year}_Summary.pdf            ║
╚═══════════════════════════════════════╦═════════════════════════════╝
                                        │ orchestrates
                                        ▼
╔═════════════════════════════════════════════════════════════════════╗
║  TIER 2 — Section Agents (6 per form)               SPECIALISTS    ║
║                                                                     ║
║  AgentF1065_Info / IncStmt / Other / Distr / Reconcile / Ext        ║
║  Each: pass1..pass5  →  GO/NO-GO  →  fillDict slice  →  summary    ║
╚═══════════════════════════════════════╦═════════════════════════════╝
                                        │ inherits from
                                        ▼
╔═════════════════════════════════════════════════════════════════════╗
║  TIER 3 — IRSFormsAgent  (irs/IRSFormsAgent.py)    COMMON SERVICES ║
║                                                                     ║
║  audit_fill_completeness / run_validation_matrix                    ║
║  generate_pdf / store_form_artifact / build_bookkeeper_session      ║
╚═════════════════════════════════════════════════════════════════════╝
```

---

## 3. Tax Calendar and Year-Round Lifecycle

The LLCTaxAgent anchors all activity to a **tax calendar** defined in `Profile.F1065.*` (tax year begin/end, extension flag, filing history).

```
Jan 1 ──────────────── Tax Season ─────────────────────── Mar 15 ──── Extension → Sep 15
  │                                                           │                       │
  │  LLCTaxAgent.phase1_prepare()                            │  File or              │
  │    → Form1065Agent Phases 1–3                            │  extend               │  Final
  │    → all section agents: Pass 1→2→3 (bookkeeper dialog)  │                       │  filing
  │                                                           │                       │
  │  LLCTaxAgent.phase2_xf_audit()                           │                       │
  │    → cross-form validation (DAG order)                   │                       │
  │                                                           │                       │
  │  LLCTaxAgent.phase3_package()                            │                       │
  │    → assemble IRS Submission Package                      │                       │
  │                                                           │                       │
  │  LLCTaxAgent.phase4_submit()                             │                       │
  │    → guide bookkeeper through submission checklist        │                       │
```

### 3.1 Non-Tax Season: Quarterly Draft Monitoring

Outside of tax season, the LLCTaxAgent runs a **draft pipeline quarterly** (see GitHub issue #14). Draft mode is read-only — no PDFs are written, no `bookNS_*.json` is modified.

Each quarterly run:
1. Execute Form1065Agent Phase 1, Passes 1–2 only (auto-fill + audit; no bookkeeper dialog).
2. Collect the `IssueList` from every section agent.
3. Update the **Tax Health Dashboard** on `/view/tax_prep`:
   - Fields that will need bookkeeper attention at tax season
   - Missing data to collect before YE close (PR TIN, partner contributions, property in-service dates)
   - IRS rule or form changes for the upcoming tax year
4. Alert (in-app) if any ERROR-severity issues appear — these need attention before they become tax-season blockers.

### 3.2 Key Tax Dates (W&B Group, Calendar Year LLC)

| Date | Event | LLCTaxAgent action |
|---|---|---|
| **Apr 1** | Q1 quarterly draft run | Draft pipeline; update Tax Health Dashboard |
| **Jul 1** | Q2 quarterly draft run | Draft pipeline; flag YE-prep issues |
| **Oct 1** | Q3 quarterly draft run | Most important non-season run — 5 months before deadline |
| Jan 1 | Tax season begins; Q4 run | Switch from draft to active mode |
| Jan 31 | K-1 mail deadline (if early desired) | Alert: K-1 PDFs due; trigger Form1065Agent if not started |
| Mar 15 | Form 1065 filing deadline | Alert: package must be assembled; file or extend |
| Mar 15 | Schedule K-1 delivery deadline to partners | Alert: K-1 PDFs must be mailed/delivered |
| Apr 15 | Partners' individual return deadline | INFO: downstream dependency on K-1 delivery |
| Sep 15 | Extended Form 1065 deadline | Final filing if extension filed Mar 15 |

---

## 4. LLCTaxAgent — The Four Phases

### Phase 1 — Prepare (with Pass 0: Form Inventory)

Phase 1 begins with **Pass 0** — a lightweight inventory exchange that establishes the compliance checklist before any form work begins. This keeps the form list dynamic (driven by both IRS rules and the actual books) rather than hardcoded.

#### Pass 0: Form Inventory Protocol

```
LLCTaxAgent
    │
    │── Pass 0 ──► Form1065Agent.inventory()
    │                     │
    │                     │── AgentForm_Ext.inventory()
    │                     │     ├── Top-down  (IRS rules):
    │                     │     │   Form 1065 always required
    │                     │     │   Form 8825 if any active rental property
    │                     │     │   Form 4562 if any depreciation claimed
    │                     │     │   Schedule K-1 × partner count
    │                     │     │
    │                     │     └── Bottom-up (books scan):
    │                     │         llcAssets → active property count → 8825 columns
    │                     │         llcAssets → depreciation exists? → 4562 required
    │                     │         llcOwners → partner count → N × K-1
    │                     │         llcAssets → under-construction? → INFO note only
    │                     │
    │                     └── returns FormInventory
    │
    └── LLCTaxAgent.compliance_checklist ← FormInventory
```

`FormInventory` (returned by `AgentForm_Ext.inventory()`):
```python
FormInventory = {
    'required_forms':     ['Form1065', 'Form8825', 'Form4562'],
    'required_k1_count':  int,           # = len(llcOwners)
    'active_properties':  ['H_805HighMesa'],
    'under_construction': ['RV_RV1'],    # INFO only — excluded from forms
    'schedules_required': {
        'L': bool, 'M1': bool, 'M2': bool   # from Sched B Q4 threshold
    },
    'notes':              [str, ...],    # bookkeeper advisories
}
```

The `compliance_checklist` derived from `FormInventory` becomes the **master completeness gate** for Phase 2.

#### Pass 0 Rationale: Why Top-Down + Bottom-Up?

The form list is not constant. IRS rules define the baseline ("always file Form 1065") but the LLC's own books alter scope:
- A property placed in service adds a Form 8825 column and triggers Form 4562.
- A new partner adds a K-1.
- An under-construction asset (RV_RV1) is explicitly excluded until `status: active`.

Without Pass 0, the system would either hardcode the form list (fragile) or discover missing forms only after the package is assembled (too late). Pass 0 costs one lightweight scan of `llcAssets` and `llcOwners` — it pays for itself immediately.

#### Phase 1 Continuation (after Pass 0)

Once the compliance checklist is established, LLCTaxAgent invokes Form1065Agent's full pipeline:

```python
form1065_agent = Form1065Agent(llc, tax_year=self.tax_year)
form_inventory  = form1065_agent.inventory()      # Pass 0
self.compliance_checklist = form_inventory
result = form1065_agent.run()                     # Form1065Agent Phases 1→2→3
```

`Form1065Agent.run()` returns a `FormPackage`:
```python
FormPackage = {
    'tax_year':          int,
    'form_ready':        bool,       # True when all section agents GO
    'pdf_artifacts': {
        'Form1065':      Path,       # the 5-page Form 1065 — only artifact from this agent
    },
    'ext_artifacts': {               # ADVICE only — text for the bookkeeper, no PDFs
        'Form4562':      str,        # "Form 4562 required. Use Form4562Agent or prepare manually."
        'Form8825':      str,        # "Form 8825 required (1 property). Use Form8825Agent or manually."
        'Sch_K1':        str,        # "3 K-1s required. Use SchK1Agent or prepare manually."
    },
    'summary_letter':    Path,       # IRS_Form1065_{year}_Summary.pdf
    'completion_report': Path,       # Agent_1065_Report_{ts}.json
    'halt_overrides':    list,
}
```

LLCTaxAgent does not proceed to Phase 2 until `form_ready == True` (or bookkeeper explicitly overrides).

---

### Phase 2 — Cross-Form Audit and Package Completeness

> **Books-First invariant:** All IRS form values are sourced from the Financial Books, never from another IRS form (see Form1065Agent §0). Phase 2 cross-form audit checks that independently books-derived values agree across completed forms. A mismatch is always a books-mapping error — the fix is to correct the books mapping, not to wire one form's output into another form's input.

> **Scope note (v1.0):** Field-level cross-form equality checks (XF-R01 through XF-R03) are implemented as comparisons of completed fill-dict values against the canonical book source. Full Relational Graph Services automation (GitHub issue #15) is a future enhancement.

#### 4.1 Completeness Check

**v1.0 scope:** `Form1065Agent` produces only `Form1065_FILL.pdf`. Extension forms (Form 8825, Form 4562, Schedule K-1) are produced manually by the bookkeeper (guided by `ext_artifacts` advice) or by future specialized agents. LLCTaxAgent's Phase 2 completeness check operates in two modes:

**Mode A — Form 1065 completeness (v1.0):**
```python
# Only Form1065 is auto-generated in v1.0
assert 'Form1065' in FormPackage['pdf_artifacts'], "Form 1065 not produced"
assert FormPackage['pdf_artifacts']['Form1065'].exists(), "Form 1065 empty"
```

**Mode B — Full package check (surfaced as advisory, not HALT):**
```python
# Extension forms — check if manually provided in books/{year}/Forms/
for form_name in compliance_checklist['required_forms']:
    if form_name == 'Form1065':
        continue                          # already checked in Mode A
    manual_path = FORMS_DIR / f"{form_name}_FILL.pdf"
    if not manual_path.exists():
        surface_advisory(f"{form_name} not yet present in Forms/. "
                         f"See ext_artifacts for guidance.")
```

Mode B advisories are surfaced on the `/view/tax_prep` dashboard as **NEXT STEPS** — they do not block Phase 3 package assembly. The bookkeeper may drop manually-prepared PDFs into `books/{year}/Forms/` and re-run Phase 2 to have them included in the submission package.

#### 4.2 Knowledge Seeding: `graphRelational.json`

As a **side effect** of Phase 2, LLCTaxAgent seeds `books/Accts/graphRelational.json` with the known cross-form **expected-equality assertions** discovered during this pipeline run. These are not data-flow wiring edges — they are audit assertions: "these two independently books-derived values must be equal." This builds the knowledge base that will power future automated cross-form validation.

```python
# Each cross-form equality assertion (NOT a data-flow edge — both sides are books-derived)
graph_edges = [
    {
        # Form 4562 Line 22 and Form 8825 Line 14 should both equal IS.depreciation
        'book_src':    'IS.depreciation',
        'assert_eq': ['Form4562.Line22', 'Form8825.Line14'],
        'rule':      'XF-R01',
    },
    {
        # Form 8825 Line 23 and Schedule K Line 2 should both equal IS.net_rental
        'book_src':    'IS.net_rental',
        'assert_eq': ['Form8825.Line23', 'SchedK.Line2'],
        'rule':      'XF-R02',
    },
    {
        # Each K-1 Box 2 should equal IS.net_rental × that partner's llcOwners.pct
        'book_src':    'IS.net_rental × llcOwners.pct',
        'assert_eq': ['SchedK.Line2', 'SchedK1.Box2'],
        'rule':      'XF-R03',
    },
]
# Appended to graphRelational.json; equality checked by phase2_xf_audit() at this run
```

`graphRelational.json` is append-only in v1.0. It accumulates over tax years and becomes the raw material for the Relational Graph Services re-engineering. **The `book_src` field is the canonical reference — if `assert_eq` members disagree, the fix is always to correct the books mapping of the outlier, never to copy a value between forms.**

#### 4.3 Cross-Form Audit Rules

Each XF rule compares two independently books-derived form values. All rules read from completed fill dicts — they do not modify any form. If a rule fails, the bookkeeper must correct the books mapping of the outlier value (not copy one form into the other).

| Rule | Forms Compared | Canonical Book Source | Description |
|---|---|---|---|
| **XF-R01** | Form 4562 Line 22 vs Form 8825 Line 14 | `IS.depreciation` (`Acct.Exp.Depreciation`) | Both must equal the depreciation expense booked in the IS. |
| **XF-R02** | Form 8825 Line 23 vs Schedule K Line 2 | `IS.net_rental` | Net rental income after all rental expenses must agree across both forms. |
| **XF-R03** | Schedule K Line 2 × partner % vs K-1 Box 2 (each partner) | `IS.net_rental × llcOwners.pct` | Each K-1 Box 2 must equal the partnership-level Schedule K Line 2 scaled by that partner's ownership %. |
| **XF-R04** | Form 1065 Line 16a vs Form 4562 Line 22 | `IS.depreciation` | Depreciation claimed on Form 1065 must equal Form 4562 total — both sourced from books. |
| **XF-R05** | Schedule L Line 14 (end) vs BS `total_assets` | `BS.total_assets` | Schedule L must tie to the Balance Sheet — both from books. |

**Failure action for all XF rules:** Find which form has the incorrect books mapping via BookToIRS Aid (`/api/aid/*`) and correct the mapping so that form independently produces the correct books value.

#### 4.4 Dependency Order (Generation Order Only — Not Data Flow)

Forms must be fully generated before cross-form audit can compare them. This is a **sequencing requirement for audit readiness**, not a data-flow dependency (all values come from books, not from prior forms in this list).

```
Form 4562 generated → Form 8825 generated → Form 1065 generated → Schedule K-1 × N generated
                                    ↓
                    LLCTaxAgent phase2_xf_audit() — compare all completed fill dicts
```

---

### Phase 3 — IRS Submission Package Assembly

Once cross-form audit passes (or overrides are acknowledged), LLCTaxAgent assembles the **IRS Submission Package**.

#### Package Contents

```
books/{year}/Forms/IRS_Submission_{year}/
├── manifest.json                           ← file inventory + SHA-256 checksums
│
│   ── Auto-generated by Form1065Agent ──
├── Form1065_FILL.pdf                       ← 5-page Form 1065 (auto)
├── IRS_Form1065_{year}_Summary.pdf         ← filing summary letter (auto)
│
│   ── Manually placed by bookkeeper (guided by ext_artifacts advice) ──
│   ── OR auto-generated by future specialized agents ──
├── Form4562_FILL.pdf                       ← Form4562Agent (future) or manual
├── Form8825_FILL.pdf                       ← Form8825Agent (future) or manual
├── Sch_K1_o{oID}_FILL.pdf                  ← SchK1Agent (future) or manual (×N)
│
│   ── Supporting documents ──
└── YEFinancialReport_{year}.pdf            ← from YE closing (stmtFinancialReport)
```

#### Manifest

```python
manifest = {
    'tax_year':          int,
    'assembled_at':      ISO_timestamp,
    'filing_entity':     'W&B Group, LLC',
    'ein':               str,
    'form_type':         'Form 1065',
    'period_end':        'YYYY-12-31',
    'extension_filed':   bool,
    'filing_deadline':   'YYYY-03-15',   # or YYYY-09-15 if extended
    'halt_overrides':    list,
    'artifacts': [
        {'file': 'Form1065_FILL.pdf',          'sha256': str, 'source': 'auto',   'required': True},
        {'file': 'Form8825_FILL.pdf',          'sha256': str, 'source': 'manual', 'required': True},
        {'file': 'Form4562_FILL.pdf',          'sha256': str, 'source': 'manual', 'required': True},
        {'file': 'Sch_K1_o*.pdf',             'sha256': str, 'source': 'manual', 'required': True, 'count': N},
        {'file': 'IRS_Form1065_*_Summary.pdf', 'sha256': str, 'source': 'auto',   'required': False},
        {'file': 'YEFinancialReport_*.pdf',    'sha256': str, 'source': 'manual', 'required': False},
    ]
}
```

`source: 'manual'` items appear as NEXT STEPS on `/view/tax_prep` until they are present in `books/{year}/Forms/`. Once present, LLCTaxAgent picks them up, computes SHA-256, and includes them in the manifest automatically.

Storage: `books/{year}/Forms/IRS_Submission_{year}/manifest.json`

---

### Phase 4 — Submission

This phase is **informational and checklist-driven** — the agent does not electronically file (MeF/e-file is out of scope for v1.0). It provides expert knowledge on what to do and tracks status.

The LLCTaxAgent guides the bookkeeper through the final IRS submission workflow, per below:

1. Work thru all the IRS Forms till they are all GO.  (FormXXX_Agent and the set of section agents).
2. Select Submit IRS - that will open the LLCTaxAgent's "IRS Submission Agent" view (Submit view).
3. The submit view provides the following frames:
    - IRS Submission Checklist view that behaves like the form "Guided Review"
        - show each check item,
        - action items needed and aids to help complete the item.
    - Accountant Preview Letter
        - creates an Accountant Notification Letter (pdf) requesting the accountant to preview the IRS package
        - instructions on how to login and review the IRS submission package contents online. 
    - IRS Submission - commit to create the IRS package (per Phase 3)
        - builds IRS submiossion package
        - puts IRS submission package onto final delivery folder
        - Send package to IRS electronically or describes steps needed to accomplish this
             (this will be hard to test... as we can only send once). 


#### Submission Checklist (surfaced in `/view/tax_prep`)

```
IRS Submission Checklist — Form 1065, Tax Year 2025

PACKAGE READY
  ✓ Form 1065 (all pages)
  ✓ Form 8825 (1 property)
  ✓ Form 4562 (depreciation schedule)
  ✓ Schedule K-1 × 3 partners
  ✓ IRS Filing Summary Letter
  ✓ Manifest (SHA-256 verified)

SUBMISSION OPTIONS
  □ Mail to IRS (paper)
      Address: Department of the Treasury
               Internal Revenue Service
               Ogden, UT 84201-0011
      Deadline: Mar 15, 2026 (postmark)
      Recommended: Certified mail, return receipt

  □ Electronic filing via tax software (TurboTax Business, Drake, etc.)
      Import completed PDFs into software of choice
      Note: LLCTaxAgent v1.0 does not support direct MeF transmission

PARTNER K-1 DELIVERY
  □ Mail Schedule K-1 to each partner by Mar 15
      Partner 1: [name, address from llcOwners]
      Partner 2: [name, address from llcOwners]
      Partner 3: [name, address from llcOwners]

POST-SUBMISSION TRACKING
  □ Record filing date in Profile.F1065.filed_date
  □ Store IRS confirmation / certified mail tracking number
  □ Set calendar reminder: Sep 15, 2026 (extended deadline, if applicable)
```

#### Submission Status Tracking

LLCTaxAgent persists submission status in `Profile.F1065.*`:
```json
{
  "filed_date":       "YYYY-MM-DD",
  "filed_method":     "mail | efiled | pending",
  "tracking_number":  "...",
  "extension_filed":  false,
  "k1_delivered":     {"oID_1": "YYYY-MM-DD", "oID_2": "...", "oID_3": "..."}
}
```

---

## 5. Tax Preparation View (Flask UI)

A **"Tax Preparation"** link is added to the home page navigation, alongside the existing accounting and IRS form views.

**Route:** `GET /view/tax_prep`

**Dashboard layout:**

```
┌──────────────────────────────────────────────────────────────────────┐
│  W&B Group LLC — Tax Preparation                     TY 2025 Active  │
├──────────────────────────────────────────────────────────────────────┤
│  Filing Deadline: Mar 15, 2026           Extension filed: No         │
│  Days remaining: 102                                                  │
│                                                                      │
│  ─── Form 1065 Package ────────────────────────────────────────────  │
│  Phase 1 — Prepare:    ● IN PROGRESS  (3/6 sections GO)              │
│  Phase 2 — Publish:    ○ NOT STARTED                                 │
│  Phase 3 — Summary:    ○ NOT STARTED                                 │
│                                                                      │
│  ─── Cross-Form Audit ─────────────────────────────────────────────  │
│  XF-R01 Form4562 → Form8825 depr:   ✓ Pass                           │
│  XF-R02 Form8825 → SchedK Line 2:   ✗ FAIL — $120 discrepancy        │
│                                                                      │
│  ─── Submission Package ───────────────────────────────────────────  │
│  Status: NOT READY (Phase 1 in progress)                             │
│                                                                      │
│  [Run Form Agent →]    [View Cross-Form Audit]    [View Checklist]   │
└──────────────────────────────────────────────────────────────────────┘
```

**New API routes:**

| Method | Route | Purpose |
|---|---|---|
| GET  | `/api/tax/status` | Returns current phase, section GO counts, xf-audit results, package status |
| POST | `/api/tax/prepare` | Invoke Form1065Agent.run(); returns `FormPackage` when complete |
| POST | `/api/tax/xf_audit` | Run cross-form validation; returns XF `IssueList` |
| POST | `/api/tax/package` | Assemble IRS Submission Package; returns manifest |
| POST | `/api/tax/submission/update` | Record filed_date, method, tracking number, K-1 delivery dates |
| GET  | `/api/tax/report` | Returns last manifest.json |

---

## 6. Data Sources

LLCTaxAgent reads from sources already established by Form1065Agent. No new data files are introduced.

| Need | Source | File |
|---|---|---|
| Tax year, filing deadlines | `Profile.entity.*`, `Profile.F1065.*` | `llcProfile_WBGroupLLC.json` |
| Submission history, filed_date | `Profile.F1065.*` (written by Phase 4) | `llcProfile_WBGroupLLC.json` |
| Cross-form audit values — read from completed fill dicts for equality comparison only; LLCTaxAgent does NOT use one form's fill dict as input to another | `Form4562_fillDict.json`, `Form8825_fillDict.json` (read-only, post-completion) | `books/{year}/Forms/` |
| Partner delivery addresses | `llcOwners_WBGroupLLC.json` | direct read |
| YE Financial Report | `stmtFinancialReport` | `books/{year}/Forms/` |

---

## 7. Out of Scope (v1.0)

- **MeF / e-file XML generation** — The IRS MeF system requires structured XML and a certified e-file transmitter. This is a significant compliance and technical investment. Phase 4 in v1.0 is a checklist and guidance system only. MeF is the most valuable future enhancement.
- **IRS correspondence ingestion** — Processing IRS notice letters (CP notices, audit letters) is a future capability noted in §1 scope.
- **Multi-form orchestration** — If the LLC ever files Form 1120-S or other returns, LLCTaxAgent can host additional FormXXXXAgents. Tier 0 orchestrates any number of form agents. Not built in v1.0.
- **Extension filing automation** — Filing Form 7004 (extension) is a manual step. LLCTaxAgent alerts the bookkeeper to the deadline; it does not generate or file Form 7004 in v1.0.

---

## 8. Implementation Milestones

| Step | Deliverable | Est. Effort |
|---|---|---|
| M1 | `LLCTaxAgent` class shell: tax calendar, draft mode `monitor()`, phase method stubs | 0.5 day |
| M2 | Phase 1: invoke `Form1065Agent.run()`, receive `FormPackage`, surface on dashboard | 0.5 day |
| M3 | Phase 2: cross-form DAG, 5 XF rules, bookkeeper resolution (HALT/override pattern) | 1 day |
| M4 | Phase 3: `IRS_Submission_{year}/` directory assembly, `manifest.json` with SHA-256 | 0.5 day |
| M5 | Phase 4: submission checklist view, K-1 delivery tracking, `Profile.F1065.*` persistence | 0.5 day |
| M6 | `/view/tax_prep` dashboard: phase status, xf-audit, deadline countdown, action buttons | 1 day |
| M7 | Draft mode `monitor()`: monthly cron-style auto-run, Tax Health panel on home page | 0.5 day |
| **Total** | | **~4.5 days** |

*These milestones assume Form1065Agent v1.0 is already implemented (prerequisite).*

---

*End of Design Document — v0.4, 2026-06-03*
