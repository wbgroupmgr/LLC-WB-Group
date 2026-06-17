# DevOps Management — Three-Discipline Model & Project/Session Cadence

**Status:** ACTIVE — first version, GO given 2026-06-16
**Owner discipline:** DevOps
**Goal this framework serves:** Steady-state accounting, proven by 2 full cycles (TY2025, TY2026)

---

## 1. Disciplines, Repos and Skills

Development is an iterative and learning process whose mission is the delivery of `Smart Business Agents` that are autonomous and self directed.  Each agent's has a mission to acquire expert knowledge and develop skills within its respective discipline.   Refer to [`discipline_skills_repo.svg`](../FlowSchematics/discipline_skills_repo.svg) for an understanding how each of the following disciplines relate to each other over the development cycles.

The diagram shows a single canonical triangle — same model for every cycle (TY2025 → Q12026 → ... → TY2026):

| Edge | Disciplines | Meaning |
|---|---|---|
| Left — "Sessions / Repos" | AcctOps ↔ AppDev | Accounting workflow knowledge shapes the code; sessions & repos are the medium |
| Right — "Priorities" | AcctOps ↔ DevOps | Accounting cycle deadlines (IRS, YE close) drive project scheduling and issue priority |
| Base — "Projects (Milestones)" | AppDev ↔ DevOps | Delivery cadence — features land inside Projects, tracked as GitHub Milestones |

Center: **Smart Business Agents — Primary Mission (Acquire skills, knowledge)** — the goal that all three edges serve.

Specifically, `DevOps` is a discipline.  It is the set of practices for unifying disciplines, data (repos) and skills to continously deliver high-quality improvements in the development of smart, AI enabled agents at high velocity. It eliminates the traditional, siloed approach where developers write code and hand it off to a separate operations team to deploy and maintain. 

### 1.1 Core Best Practices

* Continuous Integration and Continuous Delivery (CI/CD): Automatically build, test, and package code changes in a shared repository to ensure they are always ready for production release. [8, 9, 10] 
* Infrastructure as Code (IaC): Manage, provision, and configure computing infrastructure using machine-readable definition files instead of manual setup. [8, 10] 
* Microservices Architecture: Design large applications as a collection of small, independent services to enable rapid, isolated updates. [8, 11] 
* Continuous Monitoring and Observability: Track real-time system performance data, application logs, and user behavior metrics to catch and diagnose incidents quickly. [8, 9] 
* Shift-Left Security (DevSecOps): Integrate automated vulnerability scanning and compliance checks early in the delivery pipeline rather than treating security as a final gate. [9, 12] 
* Cultural Alignment: Foster a shared responsibility mindset where the cross-functional team collectively owns the product from initial planning to production uptime. [13, 14] 

### 1.2 llcRentalTracker Disciplines

The goal of this doc is to strive to improve the development cycles of the `llcRentalTracker`.  There are 3 disciplines needed to be aligned -  each with its own docs home and stage numbering:

| Discipline | Docs home | Namespace (CLAUDE.md) | Concerned with |
|---|---|---|---|
| **AppDev** | `docs/Books/` | `LLC` — app architecture, data model, API (developer-facing) | The code itself: `ledger/`, `stmt/`, `irs/`, `F1065_K1/`, `ui/`, `util/` packages and how they fit together |
| **AcctOps** | `docs/BUS/` | `BUS` — business/IRS/accounting rules (operator-facing) | The accounting workflow's correctness: ledger entries, financial statements, IRS form generation, tax compliance |
| **DevOps** | `docs/DevOps/` | `DevOps` — repeatable development cycles | Prioritizing milestones and git issues to align with project and session goals.  |


The **AcctOps** is structured around the Fiscal Year Accounting Workflow and its documentation uses a `01.x–04.x` stage numbering scheme in their filenames (`design_LLC_02.5-NewPropertyAgent.md`, `design_BUS_04.6_Form1065Agent.md`, etc.). That numbering is **AcctOps's pipeline position** (core workflow → statements → IRS forms) — AppDev borrows it today but the borrow is loose; AppDev doesn't yet have a numbering scheme of its own (see §4).

The **AppDev** is focused on software and AI architectural design and service development.  It strives to adhere to **Microservices Framework** in structuring the services.   Its documentation currently uses the format "design_LLC_<AcctStage>_<ServiceComponent>.md where `Service Component` is currently aligned with folder structure of the app. 

The **DevOps** has evolved during release/v0.x thru release/v1.0.  It strives to use `time` stamps to keep track of activiteis : <dateStart> and <dateEnd>, each is a prefix in the abstracto of each git issue, ie. '05.dd'.   Session-start/close templates, host(PA) deployment, credential/config management, server logging, and release cadence have been informally tagged with a <dateStart> prefix in issue titles (e.g. "05.13", "05.15") — borrowing the next available AcctOps stage number even though this work has nothing to do with the accounting pipeline. That blurs AcctOps's clean 01–04 sequence with unrelated ops bookkeeping.

**This document establishes `docs/DevOps/` as DevOps's home**, with its own organizing structure — not a numbered pipeline stage (DevOps isn't a pipeline), but a **Project → Session** hierarchy (§3).

---

## 2. GIT  Cycles, Projects and Sessions

Every issue describes a scenario, bug or `a new service` that requires some change across the application (AppDev) or BUS data (AcctOps).  Git is used to record most changes needed.   In order to be efficient and prioritize all changed - every issue will need to classified by each othe following disciplines.

| Label | Use for |
|---|---|
| `discipline:AcctOps` | DayToDay business operaetion and it related accounting/IRS correctness, workflow design, compliance, financial statement bugs |
| `discipline:AppDev` | Knownledge/Skill agents-as-code, code structure, new views, UI mechanics, architecture diagrams |
| `discipline:DevOps` | Cycles -> Projects(releases) -> Session (issues) activities, deployment, config/credentials, server ops, logging |

### Worked reclassification of current open issues

| # | Title | Discipline | Notes |
|---|---|---|---|
| 6 | LLC Property List Mgmt | AppDev | New view/feature |
| 7 | LLC Bus Health Agent (data integrity check) | DevOps | Purpose is operational integrity monitoring, not a feature |
| 8 | Column Operation Menu | AppDev | UI feature (deferred per prior scoping) |
| 9 | Move credentials → `~/.MultiTaskWS/config.json` | DevOps | Deployment/config |
| 10 | RV_RV1 Placement-in-Service Checklist | AcctOps | IRS depreciation rule workflow |
| 11 | COA Integrity Test | AcctOps | Proves books correctness — direct steady-state instrument |
| 12 | 2026 Recurring Entry Automation | AcctOps | Ledger workflow |
| 13 | wsCmd GPG Decrypt/Encrypt docs | DevOps | Deployment docs |
| 14 | Quarterly draft-mode monitoring cadence | AcctOps | Tax workflow cadence |
| 15 | Relational Graph Services re-engineer | AppDev | Architecture |
| 16 | stmtBS total_equity sign bug | AcctOps | Financial statement correctness |
| 18 | Server logging / pipeline tracing | DevOps | Operational observability |
| 19 | setup_paths M BUS × N years config | DevOps | Deployment/config architecture |
| 20 | BankIngestionAgent (BkAgent) | AcctOps | Prevents misclassification — books correctness |
| 24 | Std Start Session Template | DevOps | Session process |
| 25 | Std Close Session Template | DevOps | Session process |
| 27 | Auditing and Forensics | AcctOps | `docs/BUS/design_BUS_03.01` already exists |
| 28 | Form 1065 SchB total_assets bug | AcctOps | IRS form correctness |
| 30 | docs BookToIRS_HL_Flow shadow artifacts | AppDev | `docs/FlowSchematics/` diagram fix |
| 34 | YE notification of members | AcctOps | K-1 delivery, compliance deliverable |
| 35 | YE Close Books - Next Year Setup | AcctOps | Core accounting workflow |

#### Closed issues
FIXME: add closed issues

**Answering "some git issues are DevOps bookkeeping items, e.g. 24, 25, ???":** the full current DevOps set is **#7, #9, #13, #18, #19, #24, #25**.

A few calls above are judgment, not certainty (#7, #11, #20 sit close to the AppDev/AcctOps line since they're implemented as code but serve an accounting-integrity or ops purpose) — correct any of these if your intent differs.

### Remaining axes (unchanged from prior proposal, now layered under discipline)

- **Type:** `type:bug` / `type:compliance` / `type:enhancement` / `type:infra` / `type:design` / `type:docs` / `type:chore`
- **Cycle/Release impact** — this axis now forks by discipline, since "cycle" only means something for AcctOps:
  - AcctOps issues → `cycle:blocking` / `cycle:debt` / `cycle:future` (ties to TY2025/TY2026 milestone proof)
  - AppDev / DevOps issues → `release:current` / `release:next` / `release:backlog` (ties to the Project/Session structure below, not an accounting cycle)

---

## 3. DevOps Structure: Project → Session

Two levels, mapped to release granularity:

```
Cycle (e.g. TY2025, Q12026, TY2026)
  └─ Project  (the work to complete a cycle — maps to a GitHub Milestone)
      ├─ Prioritized issue list  [P1], [P2], [P3] ...
      ├─ Review plan → GO at project level
      └─ Sessions  (Claude executes N issues in priority order, across sessions as needed)
            ├─ Start Session: pick up next highest-priority open issue in the Project
            ├─ Iterate: implement → test → iterate
            └─ Close Session Protocol (unchanged):
                 release name → summarize → docs → memory → CHANGELOG →
                 commit → branch → issues triage
```

### Project-Level GO Model (new — replaces per-session scoping)

A Project is planned once:
1. Identify all issues for the cycle, assign priorities [P1] (must-have) → [P4] (nice-to-have)
2. Review the priority list → **GO at project level**
3. Claude picks up **next open [P1] issue** at session start — no per-issue confirmation needed
4. Sessions close normally (CHANGELOG, branch, push) — Claude resumes at next priority on next session start
5. Project closes when all [P1] and [P2] issues are resolved; [P3]/[P4] carry forward or are dropped

**Implication:** if a [P3] issue is not wrong, it is simply lower priority — it stays on the list and gets picked up when [P1]/[P2] work is clear. No item is "deferred" — everything has a priority.

### Session = Minor Release (unchanged)

This repo has been running this layer successfully: `release/v1.0` through `release/v1.5`, now `release/v2.0`. Each session closes with:
1. A named release branch (`release/vX.Y`)
2. A CHANGELOG entry
3. A memory update (`project_v1_milestone.md` pattern)
4. GitHub issue triage (comment + close-by-user, never auto-closed — see `feedback_issue_workflow.md`)

### Project = Cycle Milestone

A Project aligns to one accounting cycle phase (TY2025, Q12026, SS2026, TY2026) with:
- **A prioritized issue list** (the §4 roadmap entries)
- **A GitHub Milestone** tying the issues together
- **An explicit GO** — the signal that Claude can start executing across sessions without re-confirming scope

---

## 4. Cycle Roadmap

Cycle sequence:
```
TY2025  →  Q12026  →  Q2–Q4 2026  →  TY2026  →  Repeat
```

Each cycle = one Project. Each Project has a prioritized issue list. Priority scale:
- **[P1]** — blocks cycle completion; must be done before cycle milestone can close
- **[P2]** — significantly improves cycle quality; strong preference to close in-cycle
- **[P3]** — useful but non-blocking; pick up when P1/P2 work is clear
- **[P4]** — nice to have; carries forward if not reached

---

### Project TY2025 — "YE Close + IRS Submission"
**Goal:** Close the TY2025 accounting cycle cleanly — books balanced, IRS forms correct, K-1s delivered.  
**Status:** 📋 DRAFT — scope pending accountant review. Priority list below is proposed; finalize before GO.

| Priority | Issue | Title | Notes |
|---|---|---|---|
| P1 | #34 | YE member notification | K-1 delivery — compliance deliverable |
| P1 | #35 | YE Close Books / Next Year Setup | Core workflow — gates everything else |
| P1 | #16 | stmtBS total_equity sign bug | BS must balance before YE close |
| P1 | #28 | Form 1065 SchB total_assets bug | IRS form must be correct before submission |
| P2 | #19 | setup_paths M×N config | Required to open TY2026 books post-close |
| P3 | #11 | COA Integrity Test | Validates books correctness at cycle-close |
| P3 | #07 | LLC Bus Health Agent | Operational integrity monitoring |
| P4 | #12 | Recurring Entry Automation | Reduces manual work for Q12026 |

**Milestone:** `Cycle TY2025 — YE Close + IRS Submission`  
**GO condition:** Accountant review complete + user confirms priority list above.

---

### Project Q12026 — "Cycle Q12026 Validation + DevOps Hardening"
**Goal:** Run Q12026 cycle end-to-end using TY2025 fixes; harden DevOps process debt in parallel.

| Priority | Issue | Title | Notes |
|---|---|---|---|
| P1 | — | Execute Q12026 cycle | Any AcctOps bug found = new P1 inside this project |
| P1 | #20 | BankIngestionAgent | Prevents ledger misclassification — books integrity |
| P2 | #18 | Server logging / pipeline tracing | Observability during live cycle run |
| P2 | #9 | Credentials → config.json migration | Deployment hygiene |
| P3 | #13 | wsCmd GPG Decrypt/Encrypt docs | Deployment docs |
| P3 | #24 / #25 | Session templates | Process improvement |

**Milestone:** `Cycle Q12026 — Q1 Reconciled, Financial Report, IRS Preview`

---

### Project SS2026 — "Steady State 2026 + AppDev Documentation"
**Goal:** Close the AppDev structural gap (§5); resume backlog enhancements once steady-state is proven.

| Priority | Issue | Title | Notes |
|---|---|---|---|
| P1 | New | Agent & Aid inventory | Catalog all agents/aids with one-line purpose each |
| P1 | New | AppDev relationship diagram | Data flow between packages — lives in `docs/Books/` |
| P2 | #27 | Auditing & Forensics | Execute existing design doc |
| P3 | #6, #10, #14, #15 | Feature backlog | Pick up in priority order |
| P4 | #8 | Column Operation Menu | UI feature — needs design decisions answered first |

**Milestone:** `Steady State 2026 — AppDev Documented`

---

## 5. Known Gap: AppDev Stage Numbering

Unlike AcctOps (clean `01.x–04.x` pipeline stages, confirmed across `docs/BUS/`), AppDev's numbering in `docs/Books/` is borrowed and inconsistent — files like `design_LLC_02-Accounting-SOP.md` are accounting-flavored content sitting in the AppDev folder. This is **existing, accepted overlap**, not something this document tries to resolve.

What AppDev is missing, called out explicitly per your note:
1. **A complete inventory of all agents and aids** — no single file lists Form1065Agent / Form8825Agent / Form4562Agent / FormSchK1Agent / LLCTaxAgent / irsRefAgent / PropAgent / (planned) BkAgent / (planned) Bus Health Agent in one place.
2. **A relationship diagram** showing how these agents/aids/packages call each other and pass data.

Both are tracked as new issues under Project C (§4) rather than attempted inside this DevOps document — they belong in `docs/Books/`, not here.

---

## 6. Steady-State Definition of Done (carried forward, unchanged)

- 2 consecutive GitHub Milestones closed: `Cycle 1 — TY2025` and `Cycle 2 — TY2026`
- Zero manual JSON patches outside the documented edit-session workflow during either cycle
- COA Integrity Test (#11) and Bus Health Agent (#7) both pass with no findings at cycle-close
- No `cycle:blocking` issue opened during a cycle that wasn't also closed within that same cycle

---

## 7. Next Steps

1. Create GitHub labels: `discipline:AppDev`, `discipline:AcctOps`, `discipline:DevOps`, `cycle:blocking`, `cycle:debt`, `cycle:future`, `release:current`, `release:next`, `release:backlog`
2. Apply discipline + priority labels to all open issues per §2 and §4 tables
3. Create GitHub Milestones matching §4 cycle names; attach Project TY2025 issue list to `Cycle TY2025 — YE Close + IRS Submission`
4. **Accountant review → finalize TY2025 priority list → GO at project level** — Claude will execute P1→P2→P3 across sessions without re-confirming scope
5. File the two new AppDev issues from §5 (agent/aid inventory, relationship diagram) — assign to Project SS2026

