# Form1065Agent — Design Document

**Status:** v0.4 — revised 2026-06-02 (3-tier architecture; multi-year adaptation added)
**Owner:** Francisco Rojas (W&B Group, LLC)
**Baseline docs:**
- `design_BUS_04.1-Tax_BookToIRS.md` — BookToIRS Aid tool (existing implementation)
- `docs/irs/irsForm1065_book2irsDeisng.md` — current IRS view layer architecture
- IRS Form 1065 Instructions (2024), Pub 541 (Partnerships), Pub 925 (Passive Activity)

---

## 1. Purpose and Scope

The **Form1065Agent** is an orchestration agent that coordinates a set of expert, autonomous **Section Agents** to guide a bookkeeper through every section of IRS Form 1065 (U.S. Return of Partnership Income). Rather than one monolithic agent that knows everything about every form field, the design decomposes Form 1065 into its natural IRS sections — each section handled by a specialist agent that owns that section's fields, rules, and expert knowledge.

The **Form1065Agent** is invoked from the **Form 1065 View** via an **Action Button** ("Form Agent") and orchestrates the section agents through a 3-phase pipeline:

| Phase | Name | Goal |
|---|---|---|
| 1 | **Prepare** | Drive each section agent through Passes 1–3; arrive at IRS Ready State: GO / NO-GO per section |
| 2 | **Publish** | Drive each section agent through Pass 4 to produce one final, publishable PDF |
| 3 | **IRS Summary** | Drive each section agent through Pass 5; assemble a concise IRS Filing Summary letter |

Each section agent implements a standard **5-pass workflow**:

| Pass | Name | Goal |
|---|---|---|
| 1 | **Auto-Fill** | Drive the BookToIRS pipeline for this section's fid slice — fill all automatically-mappable fields |
| 2 | **Audit** | Identify gaps, IRS rule violations, and fields requiring bookkeeper input |
| 3 | **Bookkeeper Dialog** | Present an issue-driven guided session; finalize with IRS Ready State: **GO** or **NO-GO** |
| 4 | **Finalize** | Re-run, validate, and stamp all section fields into the final PDF |
| 5 | **Summarize** | Return a concise IRS-facing summary paragraph describing this section's key values |

The Form1065Agent does not proceed from Phase 1 → Phase 2 until every section agent reports **GO**. Phase 3 assembles all section summaries into a single `IRS_Form1065_{year}_Summary.pdf` filing letter.

---

### 1.1 IRS Form Section Agents

The design goal is to build focused, intelligent section agents — not a single monolithic agent that carries the cognitive load of all 440+ form fields. Form 1065 is a multi-page informational tax return used by partnerships and multi-member LLCs to report business income, deductions, and financial health. The core form spans 5 pages divided into five distinct sections, plus the mandatory Schedule K-1 extension.

Each section maps to one dedicated section agent:

| Section Agent | Form Coverage | IRS Pages |
|---|---|---|
| `AgentF1065_Info` | General Information — Items A–I, filing indicators | Page 1, top |
| `AgentF1065_IncStmt` | Income & Deductions — Lines 1–23 | Page 1, body |
| `AgentF1065_Other` | Schedule B — Compliance questions | Pages 2–3 |
| `AgentF1065_Distr` | Schedule K — Partners' Distributive Share | Page 4 |
| `AgentF1065_Reconcile` | Schedules L, M-1, M-2 — Financial Reconciliation | Page 5 |
| `AgentForm_Ext` | Schedule K-1 — Per-partner tax statements | Separate PDFs |

---

### 1.1.1 `AgentF1065_Info` — General Information (Page 1, Top)

This section captures the core entity identity metadata required for every partnership return.

- **Items A–I:** Business activity description, NAICS code, legal entity name, EIN, physical address, and partnership start date.
- **Filing Indicators:** Checkboxes for initial return, final return, or amended return.
- **Accounting Method:** Cash vs. Accrual designation.
- **Data source:** `Profile.entity.*` and `Profile.F1065.*` from `bookNS_Profile.json`.
- **Expert knowledge:** Entity metadata is largely static year-over-year. The main annual variable is the accounting period (tax year begin/end dates). Initial vs. final return checkboxes require bookkeeper confirmation.

---

### 1.1.2 `AgentF1065_IncStmt` — Income and Deductions (Page 1, Body)

This section is the operating Income Statement (P&L) for the entity's **regular trade or business** operations only.

- **Income (Lines 1–8):** Gross receipts, sales, and gains minus Cost of Goods Sold. **Note: Rental real estate revenue does NOT appear here** — it flows through Form 8825 to Schedule K Line 2 (§469 passive activity rules).
- **Deductions (Lines 9–21):** Wages, guaranteed payments to partners, rent paid, taxes, business interest, depreciation, and other deductions.
- **Ordinary Business Income (Line 23):** Net profit or loss from core operations.
- **Data source:** `IS.*` from `bookNS_IS.json`; depreciation from `GL.*` / `Acct.Depr.*`.
- **Expert knowledge:** The income classification rule (passive rental → Form 8825, not here) is this agent's primary guard. For a pure rental LLC, Lines 1–8 should be $0 or minimal.

---

### 1.1.3 `AgentF1065_Other` — Schedule B: Other Information (Pages 2–3)

A set of Yes/No compliance questions about the LLC's legal structure and regulatory exposure.

- **Ownership Disclosures:** Whether any domestic or foreign partner owns more than 50% interest — triggers different filing requirements.
- **Asset/Receipt Thresholds:** Determines whether the partnership must file Schedules L, M-1, and M-2 (threshold: gross receipts ≥ $250K **and** total assets ≥ $1M).
- **Partnership Representative:** Designates the BBA audit representative (required post-2018, IRC §6223).
- **Data source:** `Profile.F1065.*`, `llcOwners_WBGroupLLC.json`, IS/BS values.
- **Expert knowledge:** Schedule B is entirely driven by IRS threshold logic and entity facts — most answers are auto-computable. The Partnership Representative field is the most common gap.

---

### 1.1.4 `AgentF1065_Distr` — Schedule K: Partners' Distributive Share Items (Page 4)

The central collection point for all pass-through items. Because the partnership itself pays no federal income tax, Schedule K totals are what flow to each partner's K-1.

- **Income / Loss (Lines 1–11):** Separates passive rental income (from Form 8825), portfolio interest, dividends, and capital gains by category.
- **Deductions / Credits (Lines 12–20):** Section 179, charitable contributions, investment interest, and eligible business credits.
- **Data source:** Aggregated from Form 8825 net income, IS interest income, BS capital data, and `llcOwners` distributions.
- **Expert knowledge:** Line 2 (net rental real estate income) must equal Form 8825 Line 23. This is a cross-section dependency — `AgentF1065_Distr` cannot be GO until `AgentForm_Ext` (which drives Form 8825) is also GO.

---

### 1.1.5 `AgentF1065_Reconcile` — Schedules L, M-1, M-2 (Page 5)

The financial reconciliation section — an audit trail ensuring the books tie exactly to the tax return.

- **Schedule L (Balance Sheet):** Beginning and end-of-year asset, liability, and partner capital balances directly from the LLC books.
- **Schedule M-1 (Book-to-Tax Reconciliation):** Explains every difference between book net income and taxable income (depreciation timing, non-deductible items, etc.).
- **Schedule M-2 (Partners' Capital Analysis):** Tracks each partner's capital account from January 1 to December 31.
- **Data source:** `BS.*` from `bookNS_BS.json`, depreciation delta from Form 4562, `llcOwners` contributions/distributions.
- **Expert knowledge:** This section is only required if the Schedule B threshold is crossed. The agent first checks whether these schedules are required, then fills or skips accordingly. Schedule M-2 must use the **tax basis method** (required post-2020).

---

### 1.1.6 `AgentForm_Ext` — Schedule K-1 (Per-Partner, Separate PDFs)

While not physically part of the Form 1065 pages, the Schedule K-1 is mandatory for every partner. It isolates each partner's share of the Schedule K totals for use on their personal returns.

- **K-1 Box 2:** Net rental real estate income/loss (from Form 8825 net × partner %).
- **K-1 Box 5:** Interest income × partner %.
- **K-1 Box 14:** Self-employment income — $0 for a passive rental LLC.
- **K-1 Box 19:** Cash distributions from `llcOwners`.
- **K-1 Box L:** Partner's capital account analysis (tax basis method, matching M-2).
- **No K-2 / K-3:** The LLC has no foreign partners or international assets — K-2/K-3 disclosures are not required.
- **Output:** One `Sch_K1_o{oID}_FILL.pdf` per partner stored in `books/{year}/Forms/`.

`AgentForm_Ext` also drives the **Form 8825** and **Form 4562** subsidiary forms, since their outputs feed directly into Schedule K Line 2 and Schedule K-1. These are dependencies for `AgentF1065_Distr`.

---

### 1.1.7 IRS References

| # | Source |
|---|---|
| [1] | [IRS Form 1065 Instructions PDF](https://www.irs.gov/pub/irs-pdf/i1065.pdf) |
| [2] | [IRS About Form 1065](https://www.irs.gov/forms-pubs/about-form-1065) |
| [3] | [IRS Form 1065 PDF (blank)](https://www.irs.gov/pub/irs-pdf/f1065.pdf) |
| [4] | [IRS Schedule K-1 (Form 1065) PDF](https://www.irs.gov/pub/irs-pdf/f1065sk1.pdf) |
| [5] | [IRS Schedules K-2 and K-3 Requirements](https://www.irs.gov/businesses/small-businesses-self-employed/form-1065-schedules-k-2-and-k-3-filing-requirements) |
| [6] | [IRS Instructions Schedule K-3](https://www.irs.gov/pub/irs-pdf/i1065s23.pdf) |
| [7] | IRS Publication 541 — Partnerships |
| [8] | IRS Publication 925 — Passive Activity and At-Risk Rules |
| [9] | IRS Publication 946 — How to Depreciate Property |

---

## 2. Architectural Layer Design

The system is organized into three tiers. Each tier has a single responsibility and calls only downward.

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Flask UI Layer                            │
│         Form 1065 View  →  [Form Agent] Action Button               │
│         /view/agent/form1065  →  Pass 3 Guided Review Page          │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ invokes
                                   ▼
╔═════════════════════════════════════════════════════════════════════╗
║  TIER 1 — Form1065Agent  (irs/Form1065Agent.py)     ORCHESTRATOR   ║
║                                                                     ║
║  phase1_prepare()   — sequence section agents through Passes 1–3   ║
║  phase2_publish()   — sequence section agents through Pass 4        ║
║  phase3_summary()   — sequence section agents through Pass 5        ║
║                        + assemble IRS_Form1065_Summary.pdf          ║
║                                                                     ║
║  _check_all_go()    — gate: all sections must be GO before Phase 2  ║
║  _resolve_dependencies() — Form 8825/4562 before Sched K            ║
║  _build_summary_letter() — merge 6 section summaries → PDF letter   ║
╚═══════════════════════════════════════╦═════════════════════════════╝
                                        │ orchestrates
                    ┌───────────────────┼───────────────────────┐
                    ▼                   ▼                       ▼
      ┌─────────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
      │  AgentF1065_Info    │  │ AgentF1065_Other  │  │ AgentF1065_Reconcile │
      │  (Page 1, top)      │  │ (Schedule B)      │  │ (Scheds L/M-1/M-2)  │
      └─────────────────────┘  └──────────────────┘  └──────────────────────┘
      ┌─────────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
      │  AgentF1065_IncStmt │  │ AgentF1065_Distr  │  │ AgentForm_Ext        │
      │  (Page 1, Lines 1-23│  │ (Schedule K)      │  │ (K-1s, 8825, 4562)  │
      └─────────────────────┘  └──────────────────┘  └──────────────────────┘

      Each section agent implements the same 5-pass interface:
        pass1_auto_fill() → Pass1Result
        pass2_audit()     → Pass2Result (IssueList)
        pass3_dialog()    → IRSReadyState {GO | NO-GO}
        pass4_finalize()  → fills fids, stores PDF artifacts
        pass5_summarize() → str  (IRS-facing summary paragraph)

                                        │ all section agents inherit from
                                        ▼
╔═════════════════════════════════════════════════════════════════════╗
║  TIER 3 — IRSFormsAgent  (irs/IRSFormsAgent.py)    COMMON SERVICES ║
║                                                                     ║
║  audit_fill_completeness(fillDict, namespace) → {filled, blank, …} ║
║  run_validation_matrix(rules)                 → IssueList           ║
║  generate_pdf(fillDict, template, output)     → Path                ║
║  store_form_artifact(pdf, year, form_name)    → Path                ║
║  build_bookkeeper_session(issue_list)         → BookkeeperSession   ║
║  format_issue(rule_id, severity, …)           → dict                ║
╚═══════════════════════════════════════╦═════════════════════════════╝
                                        │ calls into
                                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Existing Infrastructure (unchanged)                    │
│                                                                     │
│  irs.Form1065.BookToIRS()        — fills fillDict from bookNS       │
│  ui.llcBookToIRSAid              — per-fid mapping CRUD             │
│  ledger.stmt{BS,IS,GL,Profile}   — source-of-truth data             │
│  books/{year}/Forms/             — artifact storage                 │
│  Form1065_namespace.json         — fid → meta (read-only)           │
│  bookNS_{Profile,BS,IS,GL}.json  — UAS path mappings                │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 2.1 Three Tiers — Why Not Two

| Tier | Class | Responsibility | Reusable across forms? |
|---|---|---|---|
| **1** | `Form1065Agent` | Sequence 6 section agents through 3 phases; gate on GO; assemble final PDF + summary | No — specific to Form 1065 structure |
| **2** | `AgentF1065_*` / `AgentForm_Ext` | Own a specific section's fid slice, rules, and expert IRS knowledge | No — specific to each section's content |
| **3** | `IRSFormsAgent` | Generic PDF fill, completeness audit, validation matrix runner, artifact storage | **Yes** — any IRS form agent inherits this |

The critical insight: a future `Form8825Agent` or `Form4562Agent` would be Tier 1 orchestrators with their own Tier 2 section agents — all sharing the same Tier 3 common services. No code changes needed in Tier 3 to add a new form.

---

### 2.2 Section Agent Namespace Slices

Each section agent owns a non-overlapping slice of `Form1065_namespace.json`. The orchestrator routes fids to the correct section agent by `tblID` (table identifier in the namespace).

| Section Agent | Namespace `tblID` values owned | Approximate fid count |
|---|---|---|
| `AgentF1065_Info` | `Entity`, `Profile`, `FilingIndicators` | ~30 fids (Items A–I, checkboxes) |
| `AgentF1065_IncStmt` | `IncomeStmt`, `Deductions` | ~80 fids (Lines 1–23 + sub-lines) |
| `AgentF1065_Other` | `SchedB` | ~60 fids (Yes/No questions) |
| `AgentF1065_Distr` | `SchedK` | ~80 fids (Lines 1–23 of Sched K) |
| `AgentF1065_Reconcile` | `SchedL`, `SchedM1`, `SchedM2` | ~100 fids |
| `AgentForm_Ext` | `SchedK1`, `Form8825`, `Form4562` | ~120 fids (per-partner × N) |

---

## 3. IRS Expert Knowledge Base — Per Section Agent

Each section agent encapsulates the IRS rules relevant to its section only. Cross-section rules are enforced by the Tier 1 orchestrator.

---

### 3.1 `AgentF1065_Info` Expert Rules

| Rule | IRS Requirement | Source |
|---|---|---|
| EIN present and 9-digit | Required on every return | `Profile.entity.ein` |
| NAICS code populated | Required; rental residential = 531110 | `Profile.entity.naics` |
| Accounting method checked (Cash or Accrual) | One box must be checked | `Profile.F1065.acctg_method` |
| Tax year begin/end dates match fiscal year | Must match books | `Profile.entity.tax_year_*` |
| Initial / Final / Amended — only one checked | Mutually exclusive | `Profile.F1065.chk[*]` |
| Partnership Representative named | Required post-2018, IRC §6223 | `Profile.F1065.partnership_rep` |

**W&B Group:** First tax year 2025 → `initial_return = True`. Accounting method = Accrual (matches books).

---

### 3.2 `AgentF1065_IncStmt` Expert Rules

| Rule ID | Rule | IRS Cite |
|---|---|---|
| IS-R01 | `Acct.Rev.Rent` must NOT appear on Lines 1–8 — routes to Form 8825 | IRC §469(c)(2); Pub 925 §1 |
| IS-R02 | Lines 1–8 should be $0 for a pure rental LLC | Form 1065 Instructions, Line 1a |
| IS-R03 | Line 23 (Ordinary Business Income) = Line 8 − Line 22 | Arithmetic check |
| IS-R04 | Guaranteed payments to partners (Line 10) must match `llcOwners` guaranteed payment field | IRC §707(c) |
| IS-R05 | Depreciation on Line 16a must match Form 4562 total (dependency on `AgentForm_Ext`) | Form 4562 Instructions |

---

### 3.3 `AgentF1065_Other` Expert Rules

| Rule ID | Rule | IRS Cite |
|---|---|---|
| OT-R01 | Schedule B Q4: if gross receipts < $250K **or** total assets < $1M → answer "Yes" (skip Scheds L/M-1/M-2) | Form 1065 Instructions, Sched B |
| OT-R02 | Partnership Representative (PR) name + TIN populated | IRC §6223; Treas. Reg. §301.6223-1 |
| OT-R03 | Q5: Any partner that is a disregarded entity? Must disclose | Form 1065 Instructions, Sched B Q5 |
| OT-R04 | Q21: Is this a BBA partnership that wants to elect out of centralized audit? (≤100 partners, all individuals) — bookkeeper decision | IRC §6221(b) |
| OT-R05 | Ownership >50%: individual majority owner check and entity majority owner check | Form 1065 Instructions, Sched B Q2-3 |

---

### 3.4 `AgentF1065_Distr` Expert Rules

| Rule ID | Rule | IRS Cite |
|---|---|---|
| KD-R01 | Schedule K Line 2 must equal Form 8825 Line 23 (net rental income) — cross-agent dependency | Form 8825 Instructions |
| KD-R02 | Schedule K Line 5 (interest income) must match IS `interest_income` | Sched K Instructions |
| KD-R03 | Sum of all K-1 Box 2 allocations must equal Schedule K Line 2 | IRC §704(b) |
| KD-R04 | Schedule K Line 19a (distributions) must match sum of `llcOwners` distributions | IRC §731 |
| KD-R05 | No self-employment income on Line 14 for a passive rental LLC | IRC §1402(a)(13); Pub 541 |

**Dependency:** `AgentF1065_Distr` cannot reach GO until `AgentForm_Ext` is GO (Form 8825 Line 23 is needed for KD-R01).

---

### 3.5 `AgentF1065_Reconcile` Expert Rules

| Rule ID | Rule | IRS Cite |
|---|---|---|
| RC-R01 | Schedule L required only if OT-R01 threshold is crossed; otherwise skip | Sched B Q4 outcome |
| RC-R02 | Sched L total assets (end, Line 14) = BS `total_assets` | Form 1065 Instructions, Sched L |
| RC-R03 | Sched L total liabilities + capital (Line 22) = BS `total_liab_capital` | Sched L arithmetic |
| RC-R04 | Sched L Line 14 (end) = Form 1065 Page 1 Item F | Form 1065 Instructions |
| RC-R05 | M-1 Line 1 = IS `net_income` (book basis) | Sched M-1 Instructions |
| RC-R06 | M-1 Line 4a = book depreciation − MACRS depreciation (auto-fixable) | Pub 946; Sched M-1 |
| RC-R07 | M-1 Line 9 (taxable income) must equal Schedule K Line 1 | Sched M-1 arithmetic |
| RC-R08 | M-2 uses tax basis method (not §704(b) or GAAP basis) | Post-2020 IRS requirement |
| RC-R09 | Each partner's M-2 ending capital = beg + contributions + net income − distributions (±$1.00 tolerance) | Sched M-2 Instructions |

---

### 3.6 `AgentForm_Ext` Expert Rules

| Rule ID | Rule | IRS Cite |
|---|---|---|
| EX-R01 | One K-1 PDF generated per partner in `llcOwners` | Form 1065 Instructions, §563 |
| EX-R02 | K-1 Box 2 = Form 8825 net × partner ownership % | IRC §704(b) |
| EX-R03 | K-1 Box 14 (SE income) = $0 for passive rental LLC | IRC §1402(a)(13) |
| EX-R04 | K-1 Box L capital (end) matches M-2 per-partner ending capital | Sched K-1, Box L |
| EX-R05 | Form 8825: one column per active property; under-construction properties excluded (§168) | Form 8825 Instructions |
| EX-R06 | Form 4562 required if any depreciation is claimed; Part II MACRS for residential property | Form 4562 Instructions |
| EX-R07 | MACRS 27.5-year straight-line for residential rental; mid-month convention in year placed in service | IRC §168; Pub 946 Table A-7a |
| EX-R08 | No K-2/K-3: no foreign partners or international assets | Confirmed out of scope |

---

## 4. The 5-Pass Pipeline (Per Section Agent)

All 6 section agents implement the same interface. Each pass is self-contained — the orchestrator calls them in sequence.

---

### Pass 1 — Auto-Fill

**Input:** LLC session, tax year, section's fid slice from namespace.

**Steps:**
1. Load `bookNS_{Profile,BS,IS,GL}.json` and `<form>_CustomMapDict` entries relevant to this section.
2. Execute `BookToIRS(formNm)` scoped to this section's fid slice.
3. Collect `{fillDict, checkDict, complexDict, blankList}` for section fids only.
4. Write interim snapshot to `books/{year}/Forms/.agent_work/{section}_pass1.json` — read-only pass, does not modify `bookNS_*.json` or any source file.
5. Return `Pass1Result`:

```python
Pass1Result = {
    'section':   str,    # e.g. 'AgentF1065_Info'
    'tax_year':  int,
    'filled':    int,    # fids with a resolved value
    'checked':   int,    # checkbox fids toggled
    'complex':   int,    # fids with Complex sentinel
    'blank':     int,    # fids with no mapping
    'fillDict':  dict,   # fid → value for this section
    'blankList': list,
}
```

---

### Pass 2 — Audit

**Input:** `Pass1Result`.

**Steps:**
1. Run `IRSFormsAgent.audit_fill_completeness()` — categorize every section fid: `filled | checked | complex | blank | cpa_unknown`.
2. Run this section agent's rule set (§3.x). Emit an `IssueList`.
3. Classify issue severity: `HALT` (ERRORs), `RESOLVE` (WARNs with auto-fix available), `REVIEW` (INFO).
4. Return `Pass2Result`:

```python
Pass2Result = {
    'section':        str,
    'halt_count':     int,
    'resolve_count':  int,
    'review_count':   int,
    'issue_list':     IssueList,   # list of issue dicts
    'ready_state':    'NO-GO',     # always NO-GO until Pass 3 clears it
}
```

**IssueList entry schema:**
```python
{
    'rule_id':   str,                # e.g. 'IS-R01'
    'severity':  'ERROR|WARN|INFO',
    'section':   str,                # owning section agent
    'fids':      list[str],          # affected fids
    'message':   str,                # plain English
    'irs_cite':  str,                # statutory reference
    'action':    str,                # what bookkeeper must do
    'auto_fix':  bool,               # True if agent can resolve without input
}
```

---

### Pass 3 — Bookkeeper Dialog → IRS Ready State

**Trigger:** The Form1065Agent Phase 1 opens the `/view/agent/form1065` dedicated page, which presents all section issues grouped by section agent and severity.

**Per-section dialog panel:**

```
┌──────────────────────────────────────────────────────────────────────┐
│  AgentF1065_Other — Schedule B                       Ready: NO-GO    │
├──────────────────────────────────────────────────────────────────────┤
│  ✗ 1 HALT   ⚠ 1 RESOLVE   ℹ 0 REVIEW                                │
│                                                                      │
│  [!] OT-R02  Partnership Representative not named                    │
│      IRS: IRC §6223 — PR required for all BBA partnerships           │
│      Fields: f1_48 (PR Name), f1_49 (PR TIN)                        │
│      ▶  [Open Aid Dialog — f1_48 / f1_49]                            │
│                                                                      │
│  [⚠] OT-R01  Schedules L/M-1/M-2 not required (below threshold) [✓]  │
│      IS.total_income = $18,200 < $250K; BS.total_assets = $320K < $1M│
│      Auto-fix: check Schedule B Q4 "Yes" (skip schedules)            │
│                                                                      │
│                       [Apply Auto-fixes]    Ready State: ✗ NO-GO    │
└──────────────────────────────────────────────────────────────────────┘
```

**Transition to GO:** A section reaches IRS Ready State **GO** when `halt_count == 0` (all HALT issues resolved or explicitly overridden by the bookkeeper with acknowledgement). RESOLVE and REVIEW items do not block GO.

**HALT override:** The bookkeeper may override a HALT by clicking "Acknowledge and Override" on that issue. Override is logged with timestamp in the `CompletionReport` under `halt_issues_overridden`.

**Auto-fix batch:** Each section panel has an "Apply Auto-fixes" button that applies all `[✓]`-selected RESOLVE auto-fixable issues for that section in one operation.

---

### Pass 4 — Finalize

**Trigger:** Form1065Agent Phase 2 — all sections are GO.

**Steps per section agent:**
1. Re-execute `BookToIRS(formNm)` for this section's fid slice with all updated mappings.
2. Re-run Pass 2 rule matrix — if any HALT re-emerges, abort Phase 2 and return to Phase 1.
3. Return the validated `fillDict` slice to the orchestrator.

**Orchestrator assembly (Form1065Agent.phase2_publish):**

```
PDF generation order (dependency chain):
  1. Form4562_FILL.pdf         ← depreciation totals needed by Form 8825 and Form 1065
  2. Form8825_FILL.pdf         ← net rental income needed by Sched K Line 2
  3. Form1065_FILL.pdf         ← all 5 pages (all section fillDicts merged)
  4. Sch_K1_o{oID}_FILL.pdf   ← one per partner (N iterations)
```

All PDFs stored via `IRSFormsAgent.store_form_artifact()` → `books/{year}/Forms/`.

---

### Pass 5 — Summarize

**Trigger:** Form1065Agent Phase 3 — all PDFs generated.

**Each section agent returns a summary paragraph** for inclusion in the IRS Filing Summary letter. Example:

```
AgentF1065_Info summary:
  "W&B Group, LLC (EIN: XX-XXXXXXX) files Form 1065 for tax year
   ending December 31, 2025. This is the partnership's initial return.
   Accounting method: Accrual. NAICS: 531110 (Lessors of Residential
   Buildings). Partnership Representative: Francisco Rojas."

AgentF1065_IncStmt summary:
  "No ordinary business income is reported on Form 1065 Page 1. All
   rental activity is classified as passive under IRC §469 and reported
   on Form 8825. Total deductions attributable to LLC operations: $0."
```

The orchestrator assembles all 6 paragraphs into `IRS_Form1065_{year}_Summary.pdf` and stores it in `books/{year}/Forms/`.

---

## 5. Form1065Agent — Orchestration Detail

`irs/Form1065Agent.py` — Tier 1 orchestrator. Inherits `IRSFormsAgent` for common services.

```python
class Form1065Agent(IRSFormsAgent):

    SECTION_AGENTS = [
        AgentF1065_Info,
        AgentF1065_IncStmt,
        AgentF1065_Other,
        AgentF1065_Distr,
        AgentF1065_Reconcile,
        AgentForm_Ext,
    ]

    def phase1_prepare(self) -> PhaseResult:
        """
        Drives each section agent through Passes 1–3.
        Returns overall GO/NO-GO and per-section breakdown.
        Stops at Pass 3 UI — waits for bookkeeper to resolve all issues.
        """

    def phase2_publish(self) -> PhaseResult:
        """
        Only called when _check_all_go() is True.
        Drives Pass 4 in dependency order:
          1. AgentForm_Ext.pass4()     (Form4562 + Form8825 + K-1s)
          2. AgentF1065_IncStmt.pass4()
          3. AgentF1065_Other.pass4()
          4. AgentF1065_Distr.pass4()  (after AgentForm_Ext — needs Form 8825 Line 23)
          5. AgentF1065_Info.pass4()
          6. AgentF1065_Reconcile.pass4()
        Merges all section fillDicts → generate_pdf(Form1065_FILL.pdf)
        """

    def phase3_summary(self) -> PhaseResult:
        """
        Drives Pass 5 for each section agent.
        Assembles summary paragraphs → build_summary_letter()
        Generates IRS_Form1065_{year}_Summary.pdf
        """

    def _check_all_go(self) -> bool:
        """Returns True only if every section agent's ready_state == GO."""

    def _resolve_dependencies(self) -> list:
        """
        Returns section agents in Pass 4 execution order,
        respecting: AgentForm_Ext before AgentF1065_Distr.
        """

    def _build_summary_letter(self, summaries: dict) -> Path:
        """Assembles 6 summary paragraphs into a PDF letter."""
```

### 5.1 Phase 1 — Prepare: Orchestration Sequence

```
Form1065Agent.phase1_prepare()
    │
    ├── for each section_agent in SECTION_AGENTS:
    │     section_agent.pass1_auto_fill()   → Pass1Result
    │     section_agent.pass2_audit()       → Pass2Result
    │
    ├── aggregate all IssueList → BookkeeperSession
    ├── navigate to /view/agent/form1065 (Pass 3 UI page)
    │
    ├── [Bookkeeper resolves issues per section]
    │     Each "Apply Auto-fixes" → POST /api/agent/form1065/autofix?section=X
    │     Each HALT override   → POST /api/agent/form1065/resolve/<rule_id>
    │
    ├── for each section, section_agent.pass3_dialog() returns GO | NO-GO
    │
    └── when _check_all_go():
          → [Proceed to Phase 2 — Publish] button becomes active
```

### 5.2 Phase 2 — Publish: PDF Generation

```
Form1065Agent.phase2_publish()
    │
    ├── AgentForm_Ext.pass4()
    │     ├── generate Form4562_FILL.pdf
    │     ├── generate Form8825_FILL.pdf
    │     └── generate Sch_K1_o{oID}_FILL.pdf (×N partners)
    │
    ├── AgentF1065_IncStmt.pass4()   ─┐
    ├── AgentF1065_Other.pass4()      │ fill their fid slices
    ├── AgentF1065_Distr.pass4()      │ (uses Form8825 Line 23 output)
    ├── AgentF1065_Info.pass4()       │
    └── AgentF1065_Reconcile.pass4() ─┘
          │
          └── merge all fillDicts
                → generate_pdf(Form1065_IRS.pdf → Form1065_FILL.pdf)
                → store_form_artifact()
                → write CompletionReport JSON
```

### 5.3 Phase 3 — IRS Summary Letter

```
Form1065Agent.phase3_summary()
    │
    ├── for each section_agent: section_agent.pass5_summarize() → paragraph str
    │
    └── _build_summary_letter({
            'info':      "W&B Group, LLC (EIN ...) ...",
            'income':    "No ordinary business income ...",
            'other':     "Schedule B completed. Schedules L/M-1/M-2 not required ...",
            'distr':     "Net rental income: $X allocated per §704(b) ...",
            'reconcile': "Not required per Schedule B Q4 ...",
            'ext':       "3 Schedule K-1s generated. Form 8825: 1 property. Form 4562: ...",
        })
        → IRS_Form1065_2025_Summary.pdf
```

---

## 6. IRSFormsAgent — Common Services (Tier 3)

`irs/IRSFormsAgent.py` — base class inherited by all section agents and the Form1065Agent orchestrator.

```python
class IRSFormsAgent:

    def __init__(self, llc, formNm: str, tax_year: int):
        self.llc = llc
        self.formNm = formNm
        self.tax_year = tax_year

    # ── Completeness audit ──────────────────────────────────────────
    def audit_fill_completeness(self, fillDict: dict, namespace: dict) -> dict:
        # Returns {filled, checked, complex, blank, cpa_unknown, total}

    # ── Validation framework ────────────────────────────────────────
    def run_validation_matrix(self, rules: list[dict]) -> list[dict]:
        # Each rule: {rule_id, check_fn, severity, message, irs_cite, auto_fix_fn}
        # Returns IssueList

    def format_issue(self, rule_id, severity, message, irs_cite,
                     action, fids=None, auto_fix=False) -> dict:
        # Constructs normalized issue dict

    # ── PDF generation ──────────────────────────────────────────────
    def generate_pdf(self, fillDict: dict, template_pdf: Path,
                     output_pdf: Path) -> Path:
        # pypdf AcroForms fill; returns output_pdf path

    # ── Artifact storage ────────────────────────────────────────────
    def store_form_artifact(self, pdf_path: Path, year: int,
                            form_name: str) -> Path:
        # → books/{year}/Forms/{form_name}_FILL.pdf

    # ── Bookkeeper session ──────────────────────────────────────────
    def build_bookkeeper_session(self, issue_list: list[dict]) -> dict:
        # Groups issues by severity {HALT, RESOLVE, REVIEW}
        # Returns structured session dict for UI template
```

**Reuse value:** Any future IRS form agent (`Form8825Agent`, `Form4562Agent`, `SchK1Agent`) inherits all of these services without modification. Only the Tier 1 orchestrator and Tier 2 section agents are form-specific.

---

## 7. Data Sources and UAS Namespace Alignment

Section agents read only from the existing UAS namespace. No new schemas are introduced.

| Data Need | UAS Source | File | Used By |
|---|---|---|---|
| Entity name, EIN, address, tax year | `Profile.entity.*` | `bookNS_Profile.json` | `AgentF1065_Info` |
| Form 1065 checkboxes, preparer, PR | `Profile.F1065.*` | `bookNS_Profile.json` | `AgentF1065_Info`, `AgentF1065_Other` |
| Rental income, total income, expenses | `IS.*` | `bookNS_IS.json` | `AgentF1065_IncStmt` |
| Total assets, liabilities, capital | `BS.*` | `bookNS_BS.json` | `AgentF1065_Reconcile` |
| Depreciation transactions | `GL.*` / `Acct.Depr.*` | `bookNS_GL.json` | `AgentF1065_IncStmt`, `AgentForm_Ext` |
| Partner list, TINs, ownership %, distributions | `llcOwners_WBGroupLLC.json` | direct read | `AgentF1065_Distr`, `AgentForm_Ext` |
| Property list, basis, in-service date, status | `llcAssets_WBGroupLLC.json` | direct read | `AgentForm_Ext` |
| fid metadata (type, page, location, tblID) | `Form1065_namespace.json` | read-only | all section agents (for fid slice routing) |
| Current fill values cache | `Form1065_fillDict.json` | re-generated each pass | all section agents |

**Write boundary:** Section agents never directly modify the ledger DBs (`llcAssets`, `llcExpRev`, etc.). They modify only the **mapping layer** (`bookNS_*.json`, `_Cplx_*` methods) when the bookkeeper approves via the BookToIRS Aid.

---

## 8. Integration with BookToIRS Aid

Section agents are **orchestrators** over the existing BookToIRS Aid (§4 of `design_BUS_04.1-Tax_BookToIRS.md`) for individual fid-level edits. The Aid is not replaced — it is driven by the section agents.

```
AgentF1065_Other.pass3_dialog()
    │
    ├── Issue OT-R02: PR field blank (f1_48, f1_49)
    │     → deep-link to BookToIRSAid.dialog(fid='f1_48')
    │     → bookkeeper enters PR name → Aid writes bookNS_Profile.json
    │     → section agent re-runs pass2_audit() → OT-R02 resolved
    │
AgentF1065_Reconcile.pass3_dialog()
    │
    ├── Issue RC-R06: M-1 Line 4a auto-fix (book depr ≠ MACRS)
    │     → included in "Apply Auto-fixes" batch
    │     → agent calls Aid.createMapping(fid='M1_4a', src='IS', path='...')
    │     → writes bookNS_IS.json directly (bookkeeper batch-approved)
    │
AgentF1065_IncStmt.pass3_dialog()
    │
    └── Issue IS-R01: Rent income misrouted to Pg1
          → shows offending account, correct destination (Form 8825 via AgentForm_Ext)
          → bookkeeper confirms reroute → Aid deletes wrong mapping, adds correct one
```

---

## 9. Flask Entry Points and API Routes

### UI Entry Points

| URL | Purpose |
|---|---|
| `GET /view/llcForm1065` | Form 1065 view — existing; "Form Agent" button added to toolbar |
| `GET /view/agent/form1065` | Pass 3 Guided Review page — new dedicated page |

### API Routes

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/agent/form1065/start` | Start Phase 1: run Passes 1+2 for all sections; returns aggregated `BookkeeperSession` |
| GET  | `/api/agent/form1065/session` | Returns current session: all sections with their issue lists and ready states |
| POST | `/api/agent/form1065/autofix` | Batch apply RESOLVE auto-fixes for selected rule IDs; body: `{section, rule_ids: []}` |
| POST | `/api/agent/form1065/resolve/<rule_id>` | Mark one issue resolved or overridden (HALT override requires `override: true` in body) |
| GET  | `/api/agent/form1065/status` | Returns per-section GO/NO-GO and overall Phase 1 status |
| POST | `/api/agent/form1065/publish` | Trigger Phase 2 (all sections GO required, or `halt_override` flag); returns `CompletionReport` |
| POST | `/api/agent/form1065/summary` | Trigger Phase 3; returns summary letter PDF path |
| GET  | `/api/agent/form1065/report` | Returns the last `CompletionReport` JSON |

---

## 10. Validation Rule Matrix — Complete List

Rules are grouped by owning section agent. The orchestrator aggregates all rules into the unified bookkeeper session.

### `AgentF1065_Info` Rules

| Rule ID | Severity | Description | Auto-fix? |
|---|---|---|---|
| IF-R01 | ERROR | EIN missing or malformed | No |
| IF-R02 | WARN | NAICS code blank (rental residential = 531110) | Yes — suggest 531110 |
| IF-R03 | ERROR | Accounting method checkbox not set | No |
| IF-R04 | ERROR | Partnership Representative not named | No |
| IF-R05 | WARN | Initial/Final/Amended: no box checked | No |

### `AgentF1065_IncStmt` Rules

| Rule ID | Severity | Description | Auto-fix? |
|---|---|---|---|
| IS-R01 | ERROR | Rental income mapped to Page 1 Lines 1–8 (must be Form 8825) | No |
| IS-R02 | WARN | Lines 1–8 non-zero for rental-only LLC — confirm active income source | No |
| IS-R03 | ERROR | Line 23 arithmetic error (Line 8 − Line 22 ≠ Line 23) | Yes — recalculate |
| IS-R04 | WARN | Guaranteed payments (Line 10) ≠ llcOwners guaranteed payments | No |
| IS-R05 | WARN | Line 16a depreciation ≠ Form 4562 total (cross-agent dependency) | No |

### `AgentF1065_Other` Rules

| Rule ID | Severity | Description | Auto-fix? |
|---|---|---|---|
| OT-R01 | WARN | Schedule B Q4: Sched L/M-1/M-2 threshold check | Yes — fill Q4 |
| OT-R02 | ERROR | Partnership Representative field empty | No |
| OT-R03 | INFO | Q5: Disregarded entity partner — disclosure may be needed | No |
| OT-R04 | INFO | Q21 BBA opt-out: bookkeeper decision required | No |
| OT-R05 | WARN | Ownership >50% questions unanswered | No |

### `AgentF1065_Distr` Rules

| Rule ID | Severity | Description | Auto-fix? |
|---|---|---|---|
| KD-R01 | ERROR | Sched K Line 2 ≠ Form 8825 Line 23 (dependency on AgentForm_Ext) | No |
| KD-R02 | WARN | Sched K Line 5 ≠ IS interest income | Yes — sync from IS |
| KD-R03 | ERROR | Sum of K-1 Box 2 ≠ Schedule K Line 2 | No |
| KD-R04 | WARN | Sched K Line 19a ≠ sum of llcOwners distributions | No |
| KD-R05 | WARN | Line 14 SE income non-zero for passive rental LLC | No |

### `AgentF1065_Reconcile` Rules

| Rule ID | Severity | Description | Auto-fix? |
|---|---|---|---|
| RC-R01 | INFO | Schedules L/M-1/M-2 skipped (below threshold — correct) | — |
| RC-R02 | ERROR | Sched L total assets (end) ≠ BS total_assets | No |
| RC-R03 | ERROR | Sched L Line 22 ≠ BS total_liab_capital | No |
| RC-R04 | ERROR | Page 1 Item F ≠ Sched L Line 14 end | Yes — sync Item F |
| RC-R05 | WARN | M-1 Line 1 ≠ IS net_income | No |
| RC-R06 | WARN | Book depr ≠ MACRS depr → M-1 Line 4a delta | Yes — populate M-1 L4a |
| RC-R07 | ERROR | M-1 Line 9 ≠ Schedule K Line 1 | No |
| RC-R08 | WARN | M-2 capital basis method not confirmed as tax basis | No |
| RC-R09 | WARN | Partner ending capital out of tolerance (±$1.00) | No |

### `AgentForm_Ext` Rules

| Rule ID | Severity | Description | Auto-fix? |
|---|---|---|---|
| EX-R01 | ERROR | K-1 count ≠ partner count in llcOwners | No |
| EX-R02 | ERROR | K-1 Box 2 allocation × partners ≠ Sched K Line 2 | No |
| EX-R03 | WARN | K-1 Box 14 non-zero for passive rental LLC | No |
| EX-R04 | WARN | K-1 Box L ending capital ≠ M-2 per-partner ending | No |
| EX-R05 | INFO | Under-construction asset excluded from Form 8825 (§168 compliant) | — |
| EX-R06 | WARN | Depreciation claimed but Form 4562 not generated | Yes — trigger 4562 gen |
| EX-R07 | ERROR | MACRS rate applied incorrectly (check mid-month convention) | No |

---

## 11. Accounting Best Practices

These principles govern every section agent's decisions. They are not preferences — they are statutory requirements or IRS audit triggers.

1. **Passive-first for rental income (§469)** — assume rental income is passive unless services evidence shows otherwise. For W&B Group, all income is passive → Form 8825, not Page 1.
2. **Form 8825 drives Schedule K** — Schedule K Line 2 is a derived value, not a manual entry. It comes from Form 8825 Line 23. This dependency is enforced by the orchestrator's Phase 2 order.
3. **Tax basis capital accounts (post-2020)** — Schedule K-1 Box L and Schedule M-2 must use the tax basis method. GAAP or §704(b) book basis is no longer acceptable for IRS reporting.
4. **M-1 discipline** — every dollar of difference between book income and taxable income must appear on Schedule M-1. Missing M-1 entries are a common automated IRS matching trigger.
5. **K-1 completeness** — every partner receives a K-1, even if their share is $0. Missing K-1s generate automatic §6698 penalties.
6. **MACRS only** — residential rental property uses MACRS 27.5-year straight-line with mid-month convention. No straight-line book depreciation on the tax return.
7. **Audit trail** — the `CompletionReport` and the IRS Summary Letter are the agent's audit trail. Both are stored alongside the PDFs in `books/{year}/Forms/`.
8. **Minimum disclosure, maximum correctness** — only file what the IRS requires for this entity size and activity type. Do not add schedules that are not required. (Decision 4: Sched L/M-1/M-2 skipped when below threshold.)

---

## 12. Multi-Year Adaptation

The IRS updates Form 1065 instructions annually. Field layouts, thresholds, and checkbox logic change. This chapter describes how to keep the agent current across tax years with minimal rework.

### 12.1 What Changes Year-to-Year

| Component | Change frequency | Mechanism |
|---|---|---|
| `Form1065_namespace.json` (fid→meta map) | Low — IRS rarely renumbers fields | Update once when IRS publishes new form PDF; re-run namespace extractor |
| `bookNS_{Profile,BS,IS,GL}.json` (UAS path mappings) | Medium — new lines, new account mappings | Edit via BookToIRS Aid; most changes are additive |
| Section agent rule matrices (§10) | Medium — thresholds change, new questions | Update rule constants in each section agent file |
| PDF templates (`Form1065_IRS.pdf`, etc.) | Annual — IRS publishes new year's blank forms | Replace template PDF; verify AcroForm field names haven't changed |
| Pass 5 summary text templates | Low — entity facts change, not structure | Update `Profile.entity.*` and `Profile.F1065.*` data |

### 12.2 Annual Update Checklist

At the start of each new tax year (typically January–February when IRS releases new forms):

```
1. Download new IRS forms:
   - Form1065_IRS_{year}.pdf
   - Form8825_IRS_{year}.pdf
   - Form4562_IRS_{year}.pdf
   - Sch_K1_IRS_{year}.pdf

2. Run namespace extractor → generate new Form1065_namespace_{year}.json
   - Compare to prior year: identify added, removed, renamed fids
   - Update bookNS_*.json for any renamed fids (use BookToIRS Aid)

3. Update rule matrix constants per section agent:
   - OT-R01: verify Sched B Q4 thresholds ($250K / $1M) — unchanged since 2019 but confirm
   - RC-R08: confirm M-2 tax basis method still required (post-2020 permanent)
   - EX-R07: confirm MACRS table (Pub 946, Table A-7a) rate for first year

4. Update IRS citation strings in rule dicts to reference the new year's instructions

5. Run smoke pass on prior-year data (2025) to verify no regressions

6. Update bookNS_{Profile,BS,IS,GL}.json for any new Profile.F1065.* fields
   (e.g. new checkbox on Schedule B for a new regulatory question)
```

### 12.3 Namespace Diff Process

When fid names change between IRS form versions, the namespace diff identifies the impact:

```python
# Pseudo-code for annual namespace diff
old_ns = load_namespace('Form1065_namespace_2025.json')
new_ns = load_namespace('Form1065_namespace_2026.json')

added   = new_ns.keys() - old_ns.keys()     # new fids → need new bookNS entries
removed = old_ns.keys() - new_ns.keys()     # deleted fids → clean up bookNS
renamed = {o: n for o, n in fuzzy_match(old_ns, new_ns) if o != n}  # update bookNS keys

# For each renamed fid: update bookNS_*.json using BookToIRS Aid's editMapping()
```

The `diff_report_{year}.json` is stored in `books/{year}/Forms/.agent_work/` as part of the annual tax prep record.

### 12.4 Stable vs. Volatile Section Agents

| Section Agent | Year-to-year stability | Reason |
|---|---|---|
| `AgentF1065_Info` | **High** — very stable | Entity identity fields rarely change format |
| `AgentF1065_IncStmt` | **Medium** — moderately stable | Line numbers are stable; occasional new deduction lines |
| `AgentF1065_Other` | **Low** — changes every few years | IRS adds new compliance questions to Schedule B (e.g. new BBA questions in 2018, new beneficial ownership disclosures in 2023) |
| `AgentF1065_Distr` | **Medium** — moderately stable | Schedule K structure is stable; new credit lines added occasionally |
| `AgentF1065_Reconcile` | **High** — very stable | L/M-1/M-2 structure unchanged since 2018 |
| `AgentForm_Ext` | **Medium** — depends on K-1 changes | K-1 boxes stable; K-2/K-3 additions were a major change (2021–2022) |

**Implication:** `AgentF1065_Other` is the highest-maintenance section agent. Its rule matrix should be reviewed first each tax year against the new Schedule B instructions.

### 12.5 Versioned Rule Sets (Future Enhancement)

For years when the rule matrix changes substantially, rules can be versioned by tax year:

```
irs/rules/
    F1065_rules_2025.json    ← current
    F1065_rules_2026.json    ← next year (when available)
```

Each section agent loads its rules from the file matching `self.tax_year`. This allows prior-year amended returns to use the correct rule set without code changes.

This is an **out-of-scope enhancement** for v1.0 — in v1.0, rules are hardcoded in each section agent class and updated in-place annually.

---

## 13. Implementation Milestones

| Step | Deliverable | Est. Effort |
|---|---|---|
| M1 | `IRSFormsAgent` (Tier 3): `audit_fill_completeness`, `run_validation_matrix`, `generate_pdf`, `store_form_artifact`, `build_bookkeeper_session` | 1 day |
| M2 | 6 Section Agent shells (Tier 2): class skeletons, namespace slice routing, 5-pass interface stubs, fid ownership maps | 1 day |
| M3 | `Form1065Agent` (Tier 1): `phase1_prepare`, `phase2_publish`, `phase3_summary`, `_check_all_go`, `_resolve_dependencies`, `_build_summary_letter` | 1 day |
| M4 | Pass 1 + Pass 2 per section agent: auto-fill wired to `BookToIRS()`, full rule matrix (§10) implemented with IRS cites | 2 days |
| M5 | Pass 3 UI: `/view/agent/form1065` page, per-section panels, batch auto-fix, HALT override, Aid dialog deep-links | 1.5 days |
| M6 | Pass 4 + Pass 5 per section agent: finalize fillDicts, PDF generation in dependency order, summary paragraphs | 1 day |
| M7 | Flask API routes (`/api/agent/form1065/*`), "Form Agent" toolbar button on Form 1065 view, `CompletionReport`, Summary Letter PDF | 0.5 day |
| M8 | Smoke pass: full 3-phase pipeline on W&B Group 2025 data — verify all PDFs, CompletionReport, and Summary Letter | 0.5 day |
| **Total** | | **~8.5 days** |

---

## 14. Design Decisions — Recorded 2026-06-02

All five open questions from v0.2 review are **locked**.

| # | Question | Decision | Impact |
|---|---|---|---|
| 1 | Pass 3 UI placement | **Separate page** `/view/agent/form1065` | M5 builds a dedicated Flask view + template |
| 2 | Auto-fix authorization | **Batch** — "Apply Auto-fixes" per section; individual `[✓]` checkboxes for deselection | `POST /api/agent/form1065/autofix?section=X` takes selected rule IDs |
| 3 | HALT gate | **Allow override** — strong warning; bookkeeper proceeds with acknowledgement; `halt_issues_overridden` in CompletionReport | No hard-block; `/publish` accepts `halt_override=true` |
| 4 | RV_RV1 under-construction | **IRS minimum** — INFO only; excluded from Form 8825 and Form 4562 until `status: active` (§168 compliant) | EX-R05 is INFO, not ERROR |
| 5 | Schedule K-3 (foreign partners) | **Not applicable** — no foreign partners; K-2/K-3 out of scope | EX-R08 enforces this; removed from rule matrix |

**Accounting rationale for Decision 4:** IRS §168(a) allows MACRS only in the year the asset is placed in service. Reporting premature depreciation is the violation — not reporting a not-yet-active asset. Do minimum = do correct.

**Accounting rationale for Decision 3:** The bookkeeper holds professional responsibility and may know of external corrections the agent cannot see. The audit trail (`CompletionReport`) preserves accountability without removing authority.

---

## 15. Out of Scope (v1.0)

- **AI-assisted field classification** — the LLM `llcIRS_AIAgent` concept (§15 in `design_BUS_04.1`) is a future capability. v1.0 uses deterministic rules only.
- **Multi-LLC** — single LLC (`WBGroupLLC`) scope.
- **E-file / MeF submission** — agent produces filled PDFs for human filing. No IRS electronic submission.
- **Prior-year comparison** — no "compare 2024 vs 2025" diff view.
- **Other form agents** — `Form8825Agent`, `Form4562Agent` as standalone orchestrators are future work. In v1.0 these forms are handled by `AgentForm_Ext` inside the Form 1065 pipeline.
- **Schedule K-3** — no foreign partners; K-3 not applicable.
- **Versioned rule sets** — v1.0 rules are hardcoded per section agent; JSON-based rule versioning is a §12.5 future enhancement.

---

*End of Design Document — v0.4, 2026-06-02*
