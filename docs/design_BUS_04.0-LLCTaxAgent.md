# LLCTaxAgent — Design Document

**Status:** v0.2 — revised 2026-06-02 (aligned with Form1065Agent v0.4; 4-tier architecture)
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
| Validate a single form's internal consistency | — | ✓ (section agent rules) |
| Validate **across forms** (e.g. Form 4562 → Form 8825) | ✓ | — |
| Assemble combined IRS Submission Package | ✓ | — |
| IRS submission HOWTO, tracking, communication | ✓ | — |
| MeF / e-file XML generation (future) | ✓ | — |

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

### 3.1 Non-Tax Season: Draft Mode Monitoring

Between Sep 15 and Dec 31, the LLCTaxAgent runs a **draft pipeline** monthly:

1. Execute Form1065Agent Phase 1 (Passes 1–2 only — auto-fill + audit, no bookkeeper dialog).
2. Collect the `IssueList` from every section agent.
3. Surface a **Tax Health Dashboard** on the `/view/tax_prep` page:
   - Fields that will need bookkeeper attention come tax season
   - IRS rule changes published for the upcoming tax year
   - Missing data that should be collected before Dec 31 (e.g. PR TIN, partner capital contributions)
4. Do **not** write any PDFs or modify `bookNS_*.json` in draft mode — read-only.

### 3.2 Key Tax Dates (W&B Group, Calendar Year LLC)

| Date | Event | LLCTaxAgent action |
|---|---|---|
| Jan 1 | Tax season begins | Switch from draft to active mode |
| Jan 31 | K-1 mail deadline (if desired early) | Alert: K-1 PDFs due; trigger Form1065Agent if not started |
| Mar 15 | Form 1065 filing deadline | Alert: package must be assembled; file or file extension |
| Mar 15 | Schedule K-1 delivery deadline to partners | Alert: K-1 PDFs must be mailed/delivered |
| Apr 15 | Partners' individual return deadline | INFO: downstream dependency on K-1 delivery |
| Sep 15 | Extended Form 1065 deadline | Final filing if extension filed Mar 15 |
| Oct 1 | Non-season draft mode resumes | Begin monthly monitoring for next tax year |

---

## 4. LLCTaxAgent — The Four Phases

### Phase 1 — Prepare

**Delegates entirely to Form1065Agent.** The LLCTaxAgent invokes:

```python
form1065_agent = Form1065Agent(llc, tax_year=self.tax_year)
result = form1065_agent.run()   # executes Form1065Agent Phases 1→2→3
```

`Form1065Agent.run()` returns a `FormPackage`:
```python
FormPackage = {
    'tax_year':     int,
    'form_ready':   bool,         # True if all section agents reached GO
    'pdf_artifacts': {
        'Form4562':    Path,
        'Form8825':    Path,
        'Form1065':    Path,
        'Sch_K1':      {oID: Path, ...},    # per partner
    },
    'summary_letter': Path,       # IRS_Form1065_{year}_Summary.pdf
    'completion_report': Path,    # Agent_1065_Report_{ts}.json
    'halt_overrides': list,       # any overridden HALT issues
}
```

LLCTaxAgent does not proceed to Phase 2 until `form_ready == True` (or bookkeeper explicitly overrides).

---

### Phase 2 — Cross-Form Audit

After Form1065Agent delivers its package, LLCTaxAgent runs its own **cross-form validation** — rules that span multiple forms and cannot be enforced by any single section agent.

#### 4.1 Cross-Form Dependency Graph (DAG)

The forms have a strict data dependency order. The LLCTaxAgent enforces this as a Directed Acyclic Graph:

```
[llcAssets — property basis, in-service date, MACRS class]
        │
        ▼
[Form 4562]  ─── depreciation total ──────────────────────────────┐
        │                                                          │
        ▼                                                          ▼
[Form 8825]  ─── net rental income (Line 23) ──► [Form 1065 Sched K Line 2]
                                                          │
                                                          ▼
                                              [Schedule K-1 per partner]
```

Execution order: Form 4562 → Form 8825 → Form 1065 → Schedule K-1 (× N partners)

#### 4.2 Cross-Form Validation Rules

| Rule ID | Source | Target | Check | Failure |
|---|---|---|---|---|
| XF-R01 | Form 4562 total depreciation | Form 8825 Line 14 (each property) | Sum of 4562 MACRS lines for each property = 8825 Line 14 | HALT |
| XF-R02 | Form 8825 Line 23 (net rental) | Form 1065 Sched K Line 2 | Must match exactly | HALT |
| XF-R03 | Form 1065 Sched K (all lines) | Sum of K-1 Box values (all partners) | Each K-1 box sum = corresponding Sched K line | HALT |
| XF-R04 | Form 1065 Sched L Line 14 end | Form 1065 Page 1 Item F | Must match exactly | HALT (auto-fixable) |
| XF-R05 | IS `total_income` + BS `total_assets` | Schedule B Q4 threshold decision | Consistent with Sched L/M-1/M-2 filing decision | WARN |

Cross-form rules are HALT-severity unless noted. The bookkeeper may override any HALT (same pattern as Form1065Agent section agents).

---

### Phase 3 — IRS Submission Package Assembly

Once cross-form audit passes (or overrides are acknowledged), LLCTaxAgent assembles the **IRS Submission Package**.

#### Package Contents

```
books/{year}/Forms/IRS_Submission_{year}/
├── manifest.json                           ← file inventory + SHA-256 checksums
├── Form4562_FILL.pdf
├── Form8825_FILL.pdf
├── Form1065_FILL.pdf
├── Sch_K1_o{oID}_FILL.pdf                  ← one per partner
├── IRS_Form1065_{year}_Summary.pdf         ← filing summary letter
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
    'halt_overrides':    list,           # audit trail of any HALT overrides
    'artifacts': [
        {'file': 'Form1065_FILL.pdf',   'sha256': str, 'required': True},
        {'file': 'Form8825_FILL.pdf',   'sha256': str, 'required': True},
        {'file': 'Form4562_FILL.pdf',   'sha256': str, 'required': True},
        {'file': 'Sch_K1_o*.pdf',       'sha256': str, 'required': True, 'count': N},
        {'file': 'IRS_Form1065_*_Summary.pdf', 'sha256': str, 'required': False},
        {'file': 'YEFinancialReport_*.pdf',    'sha256': str, 'required': False},
    ]
}
```

Storage: `books/{year}/Forms/IRS_Submission_{year}/manifest.json`

---

### Phase 4 — Submission

The LLCTaxAgent guides the bookkeeper through the final IRS submission workflow. This phase is **informational and checklist-driven** — the agent does not electronically file (MeF/e-file is out of scope for v1.0). It provides expert knowledge on what to do and tracks status.

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
| Cross-form values (Form 4562 → Form 8825) | `fillDict` from FormPackage | `Form4562_fillDict.json`, `Form8825_fillDict.json` |
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

*End of Design Document — v0.2, 2026-06-02*
