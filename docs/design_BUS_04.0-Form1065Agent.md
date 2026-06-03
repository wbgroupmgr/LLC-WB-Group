# Form1065Agent — Design Document

**Status:** v0.2 — revised 2026-06-02  
**Owner:** Francisco Rojas (W&B Group, LLC)  
**Baseline docs:**
- `design_BUS_04.1-Tax_BookToIRS.md` — BookToIRS Aid tool (existing implementation)
- `docs/irs/irsForm1065_book2irsDeisng.md` — current IRS view architecture
- IRS Form 1065 Instructions (2024), Pub 541 (Partnerships), Pub 925 (Passive Activity)

---

## 1. Purpose and Scope

The **Form1065Agent** is an expert, autonomous tax compilation agent that guides a bookkeeper through the complete 2-pass pipeline to produce a filed-ready IRS Form 1065 (U.S. Return of Partnership Income) and all associated schedules (Form 8825, Form 4562, Schedule K-1 per partner, Schedules B/K/L/M-1/M-2).

It is invoked from the **Form 1065 View** via an **Action Button** ("Run Agent") and operates as a guided 4-pass workflow:

| Pass | Name | Goal |
|---|---|---|
| 1 | **Auto-Fill** | Drive BookToIRS pipeline to fill all automatically-mappable fields |
| 2 | **Audit** | Identify gaps, IRS rule violations, and fields requiring bookkeeper input |
| 3 | **Bookkeeper Dialog** | Present an issue-driven guided session to resolve every gap |
| 4 | **Finalize** | Re-run, validate, generate all PDFs, store artifacts |

---

## 2. Architectural Layer Design

The design separates **form-generic IRS services** from **Form 1065-specific logic**. This allows the generic layer to be reused by future form agents (Form 1120-S, Form 1040, etc.).

```
┌─────────────────────────────────────────────────────────────────┐
│                         Flask UI Layer                          │
│           Form 1065 View  →  [Run Agent] Action Button          │
└───────────────────────────────┬─────────────────────────────────┘
                                │ invokes
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Form1065Agent                              │
│  (irs/Form1065Agent.py)                                         │
│                                                                 │
│  pass1_auto_fill()       — drive BookToIRS pipeline             │
│  pass2_audit()           — apply F1065-specific rule matrix     │
│  pass3_bookkeeper_dialog()— guided issue resolution             │
│  pass4_finalize()        — generate, validate, store PDFs       │
│                                                                 │
│  FORM-SPECIFIC RULES (§3.2):                                    │
│  _classify_income_streams()   — passive vs. active §469         │
│  _check_schedule_thresholds() — L / M-1 / M-2 triggers         │
│  _reconcile_m1()              — book vs. tax reconciliation     │
│  _validate_partner_allocs()   — allocations sum to 100%        │
│  _validate_k1_completeness()  — all partners have K-1           │
│  _check_partnership_rep()     — BBA representative named       │
└───────────────────────────────┬─────────────────────────────────┘
                                │ inherits from
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      IRSFormsAgent                              │
│  (irs/IRSFormsAgent.py)                  REUSABLE BASE          │
│                                                                 │
│  audit_fill_completeness(fillDict, namespace)                   │
│  run_validation_matrix(rules) → IssueList                       │
│  generate_pdf(fillDict, template_pdf, output_pdf)               │
│  store_form_artifact(pdf_path, year, form_name)                 │
│  build_bookkeeper_session(issue_list) → BookkeeperSession       │
│  format_issue(rule_id, severity, message, irs_cite, action)     │
└───────────────────────────────┬─────────────────────────────────┘
                                │ calls into
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              Existing Infrastructure (unchanged)                │
│                                                                 │
│  irs.Form1065.BookToIRS()        — fills fillDict from bookNS   │
│  ui.llcBookToIRSAid              — per-fid mapping CRUD         │
│  ledger.stmt{BS,IS,GL,Profile}   — source of truth data         │
│  books/2025/Forms/               — artifact storage             │
│  Form1065_namespace.json         — fid → meta (read-only)       │
│  bookNS_{Profile,BS,IS,GL}.json  — UAS path mappings            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 Why Two Layers

| `IRSFormsAgent` (generic) | `Form1065Agent` (specific) |
|---|---|
| Runs `BookToIRS()` for any form | Knows Form 1065's schedule structure (8825, 4562, K-1, B, K, L, M-1, M-2) |
| `audit_fill_completeness` — counts blank / Complex / filled by fid | Knows *why* a field is blank: IRS threshold rule, passive income classification, missing K-1 |
| `generate_pdf` — pypdf AcroForms fill, any template | Orders PDF generation: 8825 first, then 4562, then 1065, then K-1 per partner |
| `store_form_artifact` — saves to `books/{year}/Forms/` | Names output: `Form1065_FILL.pdf`, `Form8825_FILL.pdf`, `Sch_K1_o{oID}_FILL.pdf` |
| `build_bookkeeper_session` — renders issue list to HTML dialog | Formats Form 1065-specific guidance: cites the right IRS Publication, line, and rule |

---

## 3. IRS Form 1065 Expert Knowledge Base

This section encodes the accounting and IRS best practices that the agent must apply. These are not UI opinions — they are statutory rules.

### 3.1 Income Classification: Passive vs. Active (§469)

For a multi-member property rental LLC, rental income is **passive** by default under IRC §469(c)(2). The agent must enforce this routing:

| Income Type | IRS Destination | Form |
|---|---|---|
| Long-term residential rental | Passive activity | Form 8825 → Sched K Line 2 |
| Short-term rental with services (hotel model) | Active trade/business | Form 1065 Page 1, Lines 1–22 |
| Interest income | Portfolio income | Sched K Line 5 |
| Capital gains | Portfolio income | Sched K Lines 8–10 |
| Ordinary business income | Active | Form 1065 Page 1 |

**Agent rule:** If `Acct.Rev.Rent` (or any `Acct.Rev.*`) is mapped to Form 1065 Page 1 instead of Form 8825 / Schedule K, flag as **ERROR** with citation: *IRS Pub 925, §1; IRC §469(c)(2)*.

**W&B Group current status:** H_805HighMesa is long-term passive rental → Form 8825 only. RV_RV1 is under construction → no Form 8825 entry yet.

### 3.2 Schedule Filing Thresholds (Form 1065 Schedule B, Question 4)

The agent must check whether Schedules L, M-1, and M-2 are **required** or **optional**:

```
IF (total gross receipts ≥ $250,000 AND total assets ≥ $1,000,000):
    Schedules L, M-1, M-2 are REQUIRED
ELSE:
    Schedules L, M-1, M-2 are optional
    Schedule B, Question 4 answer: "Yes" (skip the schedules)
```

Agent action: Evaluate from IS (`total_income`) and BS (`total_assets`). Log the result in the Audit Report and pre-fill Schedule B Question 4 accordingly.

### 3.3 Schedule M-1: Book-to-Tax Reconciliation

When Schedules are required, M-1 reconciles book net income to taxable income. Key line items for a rental LLC:

| M-1 Line | Description | Source |
|---|---|---|
| Line 1 | Net income (loss) per books | IS `net_income` |
| Line 4a | Depreciation on books > tax return | Δ(book_depr − macrs_depr) |
| Line 4b | Travel & entertainment (50% rule) | Any `Acct.Exp.Meals` entries |
| Line 5 | Income on books not on return | None typical for rental LLC |
| Line 7 | Deductions on return not on books | None typical |
| Line 9 | Income (loss) per return | Result = M-1 should equal Sched K Line 1 |

Agent rule: If book depreciation ≠ MACRS depreciation on Form 4562, auto-populate M-1 Line 4a with the difference. Cite: *IRS Form 1065 Instructions, Schedule M-1 instructions*.

### 3.4 Schedule L: Balance Sheet Requirements

Schedule L must match the books exactly at year-end. Agent validation:

```
Total Assets (L Line 14, end) == BS total_assets
Total Liabilities + Capital (L Line 22) == BS total_liab_capital
Total Assets == Total Liabilities + Capital  (the fundamental equation)
```

Also: Form 1065 Page 1, Item F (Total Assets) must equal Schedule L Line 14 end-of-year.

Discrepancy → **HALT** level issue. Citation: *IRS Form 1065 Instructions, Schedule L*.

### 3.5 Partner Capital Account Analysis (Schedule M-2)

Each partner's capital account must follow the IRS tax basis method (post-2020 requirement):

```
Ending Capital = Beginning Capital
              + Capital Contributed (current year)
              + Net Income allocated to partner
              − Net Loss allocated to partner
              − Withdrawals and distributions
```

Agent validation: For each partner in `llcOwners`, verify the calculation above. Flag any partner whose ending capital is outside tolerance (±$1.00). Source: `llcOwners_WBGroupLLC.json`.

### 3.6 Schedule K-1 Completeness

Every partner in `llcOwners` must have a K-1 generated. Key K-1 boxes for a rental LLC:

| K-1 Box | Content | Source |
|---|---|---|
| Box 2 | Net rental real estate income (loss) | Form 8825 net × partner % |
| Box 5 | Interest income | IS `interest_income` × partner % |
| Box 14 | Self-employment income | $0 (rental LLC, not trade/business) |
| Box 19 | Distributions (cash) | `llcOwners` distributions |
| Box L | Partner's capital analysis | Schedule M-2 per partner |

Agent rule: If partner count in `llcOwners` ≠ number of K-1 PDFs in `books/2025/Forms/`, flag as **ERROR**.

### 3.7 Partnership Representative (BBA, post-2018)

IRS requires a Partnership Representative (PR) named on Form 1065 (BBA audit rules, effective 2018+). The agent checks:

- `Profile.F1065.partnership_representative` is non-empty
- PR's TIN / PTIN / EIN is provided
- If the LLC is a "small partnership" (≤ 100 partners, all individuals), it may elect out of BBA on Schedule B. This must be flagged for bookkeeper decision.

---

## 4. The 4-Pass Pipeline

### Pass 1 — Auto-Fill

**Trigger:** Bookkeeper clicks "Run Agent" on Form 1065 View.

**Steps:**
1. Load the UAS namespace: `bookNS_{Profile,BS,IS,GL}.json` and all `<form>_CustomMapDict` entries.
2. Execute `irs.Form1065.BookToIRS('Form1065')` — runs the existing fillDict pipeline across all form pages and schedules (8825, 4562, K-1, Schedules B/K/L/M-1/M-2).
3. Collect the result: `{fillDict, checkDict, complexDict, blankList}`.
4. Write interim fill snapshots: `bookNS_IS.json`, `bookNS_BS.json` etc. are **not modified** in Pass 1 — this pass is read-only.
5. Emit `Pass1Result`:
   ```python
   Pass1Result = {
       'form': 'Form1065',
       'tax_year': 2025,
       'filled':   int,   # fids with a resolved value
       'checked':  int,   # checkbox fids toggled
       'complex':  int,   # fids with Complex sentinel (stub not yet written)
       'blank':    int,   # fids with no mapping at all
       'fillDict': dict,  # fid → value
       'blankList': list, # fids with no mapping
   }
   ```

**Accounting best practice:** Never overwrite a finalized `_FILL.pdf` in Pass 1. Interim output goes to `books/2025/Forms/.agent_work/Form1065_pass1.json`. The IRS artifact is only written in Pass 4.

---

### Pass 2 — Audit

**Input:** `Pass1Result`

**Steps:**
1. Run `IRSFormsAgent.audit_fill_completeness()` — categorize every fid as: `filled | checked | complex | blank | cpa_unknown`.
2. Run `Form1065Agent` rule matrix (§3 rules). Emit an `IssueList`:

```
IssueList = [
    {
        'rule_id':   'F1065-R01',
        'severity':  'ERROR | WARN | INFO',
        'category':  'income_classification | schedule_threshold |
                      m1_reconciliation | k1_completeness |
                      balance_sheet | partner_alloc | pr_missing | blank_field',
        'fids':      ['F042', 'F043'],    # affected form fields
        'message':   str,                 # plain English description
        'irs_cite':  str,                 # e.g. "IRS Pub 925, §1; IRC §469(c)(2)"
        'action':    str,                 # what the bookkeeper must do
        'auto_fix':  bool,               # True if agent can resolve without input
    }
]
```

**Built-in rules:**

| Rule ID | Severity | Description | Auto-fix? |
|---|---|---|---|
| F1065-R01 | ERROR | Rental income on Page 1 instead of Form 8825 | No |
| F1065-R02 | ERROR | Schedule L: Assets ≠ Liabilities + Capital | No |
| F1065-R03 | ERROR | Partner allocations do not sum to 100% | No |
| F1065-R04 | ERROR | Partner without K-1 generated | No |
| F1065-R05 | ERROR | Partnership Representative field empty | No |
| F1065-R06 | WARN | Schedule L/M-1/M-2 threshold exceeded — schedules required | Yes (auto-fill Sched B Q4) |
| F1065-R07 | WARN | Book depreciation ≠ MACRS depreciation — M-1 adjustment needed | Yes (auto-populate M-1 Line 4a) |
| F1065-R08 | WARN | Partner capital account ending balance out of tolerance | No |
| F1065-R09 | WARN | K-1 Box 14 (self-employment) non-zero for rental LLC | No |
| F1065-R10 | INFO | Complex stubs present — custom calc methods not yet implemented | No |
| F1065-R11 | INFO | CPA:unknown fields — bookkeeper has marked as needing CPA confirmation | No |
| F1065-R12 | INFO | Blank fids — no mapping defined | No |

3. Classify issue severity into: `HALT` (ERRORs must resolve before Pass 4), `RESOLVE` (WARNs — bookkeeper decision), `REVIEW` (INFO — optional).
4. Write `Pass2Result`:
   ```python
   Pass2Result = {
       'halt_count':    int,
       'resolve_count': int,
       'review_count':  int,
       'issue_list':    IssueList,
       'schedule_thresholds': {
           'l_required': bool, 'm1_required': bool, 'm2_required': bool
       },
       'income_classification': {
           'passive_accounts': list, 'active_accounts': list
       },
   }
   ```

---

### Pass 3 — Bookkeeper Dialog

**Trigger:** After Pass 2, the agent surfaces a **Guided Session Panel** in the Form 1065 View. This is a structured, issue-by-issue workflow — not a raw list of errors.

**UI layout (inline panel, not modal):**

```
┌─────────────────────────────────────────────────────────────────────┐
│  Form1065Agent — Guided Tax Review                      Pass 3 of 4 │
├─────────────────────────────────────────────────────────────────────┤
│  Summary:  ✗ 2 HALT   ⚠ 3 RESOLVE   ℹ 4 REVIEW                     │
│                                                                     │
│  ── HALT: Must resolve before finalizing ─────────────────────────  │
│                                                                     │
│  [!] F1065-R05  Partnership Representative not named                │
│      IRS: BBA audit rules require a PR (26 U.S.C. §6223)           │
│      Fields: f1_48, f1_49 (PR Name / TIN)                           │
│      ▶  [Open Aid Dialog for F016 / F017]   [Enter PR Name inline]  │
│                                                                     │
│  [!] F1065-R03  Partner allocations sum to 98.0% (not 100%)         │
│      IRS: IRC §704(b) — all items must be allocated 100%            │
│      Partners: Rojas 50%, Smith 48%, Jones 0%  (total 98%)          │
│      ▶  [Open llcOwners Editor]                                     │
│                                                                     │
│  ── RESOLVE: Agent recommends, bookkeeper confirms ───────────────  │
│                                                                     │
│  [⚠] F1065-R07  Book depreciation ($4,200) ≠ MACRS ($3,850)         │
│      M-1 Line 4a adjustment: $350 difference                        │
│      IRS: Pub 946, MACRS half-year convention                       │
│      ▶  [Auto-apply M-1 adjustment]   [Review Form 4562]            │
│                                                                     │
│  ── REVIEW: Informational, no action required ────────────────────  │
│  ℹ  8 blank fids (no mapping) — click [View Blanks] to inspect     │
│  ℹ  3 Complex stubs pending implementation                          │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  [← Back to Pass 2 Report]          [Proceed to Pass 4 Finalize →]  │
│  (Pass 4 available only when HALT count = 0)                        │
└─────────────────────────────────────────────────────────────────────┘
```

**Resolution paths per issue type:**

| Issue Category | Resolution UI |
|---|---|
| Blank fid | Opens BookToIRS Aid dialog (per-fid, §4.4 in `design_BUS_04.1`) |
| Complex stub | Opens bookkeeper code editor hint for `_Cplx_<fid>()` stub |
| Income misrouted | Shows the offending account, the correct destination, and lets bookkeeper confirm reroute |
| Partner alloc ≠ 100% | Link to `llcOwners` editor; recalculates on save |
| PR missing | Inline text input → writes to `Profile.F1065.partnership_representative` |
| M-1 auto-adjustable | "Auto-apply" button → agent writes the M-1 adjustment to the bookNS mapping and updates fillDict |
| Schedule threshold | Displays calculation: `IS.total_income = $X, BS.total_assets = $Y → Schedules L/M-1/M-2 required/not required` |

**No issue blocks the bookkeeper from proceeding** except HALT-level issues. RESOLVE and REVIEW items may be dismissed.

---

### Pass 4 — Finalize

**Trigger:** Bookkeeper clicks "Proceed to Finalize" (only enabled when HALT count = 0).

**Steps — in order:**

1. **Final BookToIRS run** — re-execute `BookToIRS('Form1065')` with all updated bookNS + _Cplx methods. Collect final `fillDict`.
2. **Final validation** — re-run rule matrix. If any HALT issues re-emerge, abort and return to Pass 3.
3. **PDF generation order** (dependency order matters):
   - `Form8825_FILL.pdf` — must exist before Line 23a of Form 1065 can be filled
   - `Form4562_FILL.pdf` — depreciation total feeds Form 1065 and Form 8825 Line 14
   - `Form1065_FILL.pdf` — all pages (1 + schedules B, K, L, M-1, M-2)
   - `Sch_K1_o{oID}_FILL.pdf` — one per partner (n iterations)
4. **Store artifacts** — via `IRSFormsAgent.store_form_artifact()`:
   - `books/2025/Forms/Form1065_FILL.pdf`
   - `books/2025/Forms/Form8825_FILL.pdf`
   - `books/2025/Forms/Form4562_FILL.pdf`
   - `books/2025/Forms/Sch_K1_o{oID}_FILL.pdf` (per partner)
5. **Generate Completion Report** — written to `books/2025/Forms/Agent_1065_Report_{timestamp}.json`:
   ```python
   CompletionReport = {
       'tax_year': 2025,
       'generated_at': ISO_timestamp,
       'form_artifacts': [list of PDF paths],
       'fill_summary': {filled, checked, complex, blank},
       'issues_resolved': int,
       'issues_dismissed': int,
       'halt_issues_at_close': 0,  # must be 0
       'schedule_l_required': bool,
       'm1_required': bool,
       'partner_count': int,
       'k1_count': int,
   }
   ```
6. **Refresh UI** — reload Form 1065 view iframe (cache-buster `?ts=<unix_ts>`), show completion summary banner.

---

## 5. IRSFormsAgent — Reusable Base Services

`irs/IRSFormsAgent.py` — base class for all form-specific agents.

```python
class IRSFormsAgent:

    def __init__(self, llc, formNm: str, tax_year: int):
        self.llc = llc
        self.formNm = formNm
        self.tax_year = tax_year

    # ── Completeness audit ──────────────────────────────────────────
    def audit_fill_completeness(self, fillDict: dict, namespace: dict) -> dict:
        """
        Returns counts by status across all fids in namespace.
        {filled, checked, complex, blank, cpa_unknown, total}
        """

    # ── Validation framework ────────────────────────────────────────
    def run_validation_matrix(self, rules: list[dict]) -> list[dict]:
        """
        Each rule: {rule_id, check_fn, severity, message, irs_cite, auto_fix_fn}.
        Returns IssueList (§4, Pass 2).
        """

    def format_issue(self, rule_id, severity, message, irs_cite, action,
                     fids=None, auto_fix=False) -> dict:
        """Constructs a normalized issue dict for the bookkeeper session."""

    # ── PDF generation ──────────────────────────────────────────────
    def generate_pdf(self, fillDict: dict, template_pdf: Path,
                     output_pdf: Path) -> Path:
        """
        Fills AcroForm fields using pypdf.
        template_pdf: blank IRS form (e.g. Form1065_IRS.pdf)
        output_pdf:   destination (e.g. Form1065_FILL.pdf)
        Returns output_pdf path on success.
        """

    # ── Artifact storage ────────────────────────────────────────────
    def store_form_artifact(self, pdf_path: Path, year: int,
                            form_name: str) -> Path:
        """
        Copies pdf_path to books/{year}/Forms/{form_name}_FILL.pdf.
        Creates directory if absent. Returns final path.
        """

    # ── Bookkeeper session builder ──────────────────────────────────
    def build_bookkeeper_session(self, issue_list: list[dict]) -> dict:
        """
        Groups issues by severity (HALT / RESOLVE / REVIEW).
        Returns structured session dict consumed by the UI panel template.
        """
```

**Why this separation is valuable for future forms:**
- `Form8825Agent` can reuse `audit_fill_completeness`, `generate_pdf`, `store_form_artifact` — only `pass2_audit()` rules differ.
- `SchK1Agent` can reuse the full pipeline skeleton with its own partner-iteration loop.
- `Form4562Agent` can reuse all base services; only the depreciation rule matrix changes.

---

## 6. Data Sources and UAS Namespace Alignment

The agent reads only from the existing UAS namespace — no new schemas are introduced.

| Data Need | UAS Source | JSON File |
|---|---|---|
| Entity name, EIN, address, tax year | `Profile.entity.*` | `bookNS_Profile.json` |
| Form 1065 checkboxes, preparer info | `Profile.F1065.*` | `bookNS_Profile.json` |
| Rental income, total income, expenses | `IS.*` | `bookNS_IS.json` |
| Total assets, liabilities, capital | `BS.*` | `bookNS_BS.json` |
| Depreciation transactions | `GL.*` / `Acct.Depr.*` | `bookNS_GL.json` |
| Partner list, TINs, ownership % | `llcOwners_WBGroupLLC.json` | direct read (not bookNS) |
| Property list, basis, in-service date | `llcAssets_WBGroupLLC.json` | direct read |
| fid metadata (type, page, location) | `Form1065_namespace.json` | read-only |
| Current fill values | `Form1065_fillDict.json` | cache; re-generated each pass |

The agent **never directly modifies** the ledger DBs (`llcAssets`, `llcExpRev`, etc.). It reads them and modifies only the **mapping layer** (`bookNS_*.json`, `_Cplx_*` methods) when the bookkeeper approves.

---

## 7. Integration with Existing BookToIRS Aid

The Form1065Agent is an **orchestrator** that calls the existing BookToIRS Aid (§4.4 of `design_BUS_04.1`) for individual fid-level edits. It does not replace the Aid — it drives it.

```
Form1065Agent.pass3_dialog()
    │
    ├── Issue: blank fid F042 (Line 11 Repairs)
    │     → opens BookToIRSAid dialog pre-scoped to F042
    │     → operator picks source + path → Aid writes bookNS_IS.json
    │     → agent re-evaluates issue F1065-R12 for F042 → resolved
    │
    ├── Issue: F1065-R07 M-1 auto-adjustment available
    │     → agent calls Aid.createMapping(fid='M1_4a', src='IS', path='...')
    │     → writes directly (operator clicks "Auto-apply")
    │
    └── Issue: Complex stub F229 (Sched K Line 1)
          → agent opens the Aid's "Add custom map" flow for F229
          → stub generated, operator fills in calc, agent re-runs
```

---

## 8. Flask Entry Point

**Route:** `GET /view/llcForm1065` — existing Form 1065 view.

**New UI element:** An **"Run Agent"** button in the view toolbar (alongside existing "Aid", "Namespace PDF" buttons).

```
┌──────────────────────────────────────────────────────┐
│  Form 1065 View                                       │
│  [Aid ▾]  [Namespace PDF]  [Run Agent →]              │
└──────────────────────────────────────────────────────┘
```

**New API routes:**

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/agent/form1065/pass1` | Trigger Pass 1 (auto-fill); returns `Pass1Result` |
| POST | `/api/agent/form1065/pass2` | Trigger Pass 2 (audit); returns `Pass2Result` |
| GET  | `/api/agent/form1065/session` | Returns current `BookkeeperSession` (issue list) |
| POST | `/api/agent/form1065/resolve/<rule_id>` | Mark an issue resolved (or auto-fix if flagged) |
| POST | `/api/agent/form1065/pass4` | Trigger Pass 4 (finalize); returns `CompletionReport` |
| GET  | `/api/agent/form1065/report` | Returns the last `CompletionReport` JSON |

Pass 3 does not have its own API route — it is the UI session between Pass 2 and Pass 4. Issues are resolved one-at-a-time via the existing Aid APIs and the new `/resolve/<rule_id>` endpoint.

---

## 9. Validation Rule Matrix — Full List

| Rule ID | Category | Severity | IRS Cite | Auto-fixable |
|---|---|---|---|---|
| F1065-R01 | Income classification | ERROR | IRC §469(c)(2); Pub 925 §1 | No |
| F1065-R02 | Balance sheet | ERROR | Form 1065 Instructions, Sched L | No |
| F1065-R03 | Partner allocation | ERROR | IRC §704(b) | No |
| F1065-R04 | K-1 completeness | ERROR | Form 1065 Instructions, §563 | No |
| F1065-R05 | Partnership Representative | ERROR | IRC §6223; BBA audit rules | No |
| F1065-R06 | Schedule thresholds | WARN | Form 1065 Instructions, Sched B Q4 | Yes — fill Sched B Q4 |
| F1065-R07 | M-1 depreciation delta | WARN | Pub 946; Form 1065 Sched M-1 | Yes — populate M-1 Line 4a |
| F1065-R08 | Partner capital tolerance | WARN | Form 1065 Instructions, Sched M-2 | No |
| F1065-R09 | K-1 Box 14 SE income | WARN | IRC §1402(a)(13); Pub 541 | No |
| F1065-R10 | Complex stubs pending | INFO | — | No |
| F1065-R11 | CPA:unknown fields | INFO | — | No |
| F1065-R12 | Blank fids | INFO | — | No |
| F1065-R13 | Form 8825 missing for active property | ERROR | Form 8825 Instructions | No |
| F1065-R14 | Form 4562 required (any depreciation claimed) | WARN | Form 4562 Instructions | Yes — trigger Form4562 gen |
| F1065-R15 | Page 1 Item F ≠ Schedule L total assets | ERROR | Form 1065 Instructions, Page 1 | Yes — sync Item F |

---

## 10. Accounting Best Practices Summary

These principles govern every agent decision:

1. **Passive-first classification** — assume rental income is passive (§469) unless evidence of services shows otherwise.
2. **Form 8825 primacy** — for a rental LLC, Form 8825 is the primary tax schedule. Form 1065 Page 1 is largely informational for rental LLCs; the real numbers are in Form 8825 → Schedule K → K-1.
3. **Tax basis capital accounts** — IRS now requires tax-basis capital reporting (post-2020). Do not use §704(b) or GAAP basis on Schedule K-1, Item L.
4. **M-1 discipline** — every difference between book income and taxable income must appear on Schedule M-1. Missing M-1 adjustments are a common audit trigger.
5. **K-1 completeness** — every partner must receive a K-1 even if their share is $0. Missing K-1s trigger automatic penalties.
6. **MACRS over book depreciation** — the IRS generally does not accept straight-line depreciation for tax purposes on real property acquired after 1986. MACRS 27.5-year (residential) or 39-year (commercial) applies.
7. **Audit trail** — the `CompletionReport` generated in Pass 4 is the agent's audit trail. Store it alongside the PDFs in `books/2025/Forms/`.

---

## 11. Implementation Milestones

| Step | Deliverable | Est. Effort |
|---|---|---|
| M1 | `IRSFormsAgent` base class: `audit_fill_completeness`, `run_validation_matrix`, `generate_pdf`, `store_form_artifact`, `build_bookkeeper_session` | 1 day |
| M2 | `Form1065Agent` shell: 4-pass entry points, pass1 auto-fill wired to existing `BookToIRS()` | 0.5 day |
| M3 | Pass 2 audit — implement all 15 rules in §9 with IRS cites; emit `Pass2Result` | 1.5 days |
| M4 | Pass 3 UI — "Guided Session Panel" in Form 1065 view; per-issue resolution wiring to BookToIRS Aid | 1.5 days |
| M5 | Pass 4 — PDF generation order (8825 → 4562 → 1065 → K-1s), artifact storage, `CompletionReport` | 1 day |
| M6 | Flask routes (`/api/agent/form1065/*`), "Run Agent" toolbar button, progress indicators | 0.5 day |
| M7 | Smoke pass: run full 4-pass pipeline on W&B Group 2025 data, verify all PDFs and CompletionReport | 0.5 day |
| **Total** | | **~6.5 days** |

---

## 12. Out of Scope (v1.0)

- **AI-assisted classification** — the LLM-powered `llcIRS_AIAgent` concept (§15 in `design_BUS_04.1`) is a future capability. This v1.0 agent uses deterministic rules only.
- **Multi-LLC** — single LLC (`WBGroupLLC`) scope.
- **E-file / MeF submission** — agent produces the filled PDFs for human filing. No IRS electronic submission in this scope.
- **Prior-year comparison** — no "compare 2024 vs 2025" diff view.
- **Form 1120-S or 1040** — `IRSFormsAgent` base is designed to support these; the subclasses are not built in this milestone.

---

## 13. Open Questions for Review

1. **Pass 3 UI placement:** Should the Guided Session Panel open as an inline panel within the Form 1065 view, or as a separate `/view/agent/form1065` page? Inline keeps context; separate page gives more room for the issue list.

2. **Auto-fix authorization:** When the agent can auto-fix an issue (e.g. M-1 Line 4a), should it require a single "Auto-apply" click per issue, or a single "Apply all auto-fixes" batch button? Recommend: per-issue click for auditability.

3. **HALT gate:** Should HALT-level issues hard-block the "Run Agent" button from proceeding to Pass 4, or display a strong warning and allow override? Recommend: hard-block — ERRORs that reach the IRS are penalties/rejections.

4. **RV_RV1 in-progress:** How does the agent handle an asset with `status: under_construction`? Recommend: INFO-level note that Form 8825 will not include RV_RV1 until status changes to `active`. No ERROR.

5. **Schedule K-3:** For tax year 2022+, partners may request Schedule K-3 for international tax purposes. Should the agent check if any partner has foreign tax exposure? Recommend: flag as CPA:unknown if any `Profile.entity.country` ≠ "US".

---

*End of Design Document — v0.2, 2026-06-02*
