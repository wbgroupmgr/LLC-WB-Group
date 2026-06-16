# DevOps Management — Three-Discipline Model & Project/Session Cadence

**Status:** ACTIVE — first version, GO given 2026-06-16
**Owner discipline:** DevOps
**Goal this framework serves:** Steady-state accounting, proven by 2 full cycles (TY2025, TY2026)

---

## 1. Disciplines, Repos and Skills

DevOps is a discipline.  It is the set of practices for unifying disciplines, data (repos) and skills to continously deliver high-quality improvements in the development of smart, AI enabled applications at high velocity. It eliminates the traditional, siloed approach where developers write code and hand it off to a separate operations team to deploy and maintain. 




### 1.1 Core Best Practices

* Continuous Integration and Continuous Delivery (CI/CD): Automatically build, test, and package code changes in a shared repository to ensure they are always ready for production release. [8, 9, 10] 
* Infrastructure as Code (IaC): Manage, provision, and configure computing infrastructure using machine-readable definition files instead of manual setup. [8, 10] 
* Microservices Architecture: Design large applications as a collection of small, independent services to enable rapid, isolated updates. [8, 11] 
* Continuous Monitoring and Observability: Track real-time system performance data, application logs, and user behavior metrics to catch and diagnose incidents quickly. [8, 9] 
* Shift-Left Security (DevSecOps): Integrate automated vulnerability scanning and compliance checks early in the delivery pipeline rather than treating security as a final gate. [9, 12] 
* Cultural Alignment: Foster a shared responsibility mindset where the cross-functional team collectively owns the product from initial planning to production uptime. [13, 14] 

### 1.2 llcRentalTracker Disciplines

Development is an iterative and learning process.    The goal of this doc is to strive to improve the development cycles of the `llcRentalTracker`.  There are 3 disciplines needed to be aligned -  each with its own docs home and stage numbering:

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

## 2. The Three-Discipline Classification (GitHub Issues — Axis 2, revised)

Every issue gets a `discipline:` label first, before anything else:

| Label | Use for |
|---|---|
| `discipline:AppDev` | Code structure, new views/agents-as-code, UI mechanics, architecture diagrams |
| `discipline:AcctOps` | Accounting/IRS correctness, workflow design, compliance, financial statement bugs |
| `discipline:DevOps` | Session process, release cadence, deployment, config/credentials, server ops, logging |

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

**Answering "some git issues are DevOps bookkeeping items, e.g. 24, 25, ???":** the full current DevOps set is **#7, #9, #13, #18, #19, #24, #25**.

A few calls above are judgment, not certainty (#7, #11, #20 sit close to the AppDev/AcctOps line since they're implemented as code but serve an accounting-integrity or ops purpose) — correct any of these if your intent differs.

### Remaining axes (unchanged from prior proposal, now layered under discipline)

- **Type:** `type:bug` / `type:compliance` / `type:enhancement` / `type:infra` / `type:design` / `type:docs` / `type:chore`
- **Cycle/Release impact** — this axis now forks by discipline, since "cycle" only means something for AcctOps:
  - AcctOps issues → `cycle:blocking` / `cycle:debt` / `cycle:future` (ties to TY2025/TY2026 milestone proof)
  - AppDev / DevOps issues → `release:current` / `release:next` / `release:backlog` (ties to the Project/Session structure below, not an accounting cycle)

---

## 3. DevOps Structure: Project → Session

This is the part that needed defining. Two levels, mapped to release granularity:

```
Project  (major release, e.g. v2.0 → v3.0)
  ├─ start date
  ├─ list of deliverable goals — EXPECTED to be revised as new things surface
  └─ Sessions  (minor release; N sessions sometimes = 1 minor release)
        ├─ goals for this session
        └─ Close Session Protocol (already working well — unchanged):
             release name → summarize → docs → memory → CHANGELOG →
             commit → branch → issues triage
```

### Session = Minor Release (already validated — no change needed)

This repo has been running this layer successfully: `release/v1.0` through `release/v1.5`, now `release/v2.0`. Each session (or small cluster of sessions) closes with:
1. A named release branch (`release/vX.Y`)
2. A CHANGELOG entry
3. A memory update (`project_v1_milestone.md` pattern)
4. GitHub issue triage (comment + close-by-user, never auto-closed — see `feedback_issue_workflow.md`)

**No changes proposed here.** Keep doing exactly this per session.

### Project = Major Release (new layer — this is the gap)

A Project is a ~3-month horizon containing several Sessions, with:
- **StartDate**
- **A short list of deliverable goals** (3–6 items, not a sprint backlog) — explicitly allowed to drift as new issues surface mid-project; the goal list is a compass, not a contract
- **A milestone in GitHub** tying together the issues that belong to it

---

## 4. The 3-Month Roadmap (draft — adjust freely)

Built directly from the discipline + cycle-impact classification already done in this conversation. This is a template to edit, not a final plan.

### Project A — "Steady-State Foundations" (Weeks 1–5)
**Goal:** Close every AcctOps `cycle:blocking` issue so Cycle 1 (TY2025) can be certified clean.
- #35 YE Close Books / Next Year Setup
- #19 setup_paths M×N config (multi-year support — required to even start Cycle 2)
- #12 Recurring Entry Automation
- #16 stmtBS sign bug
- #28 Form 1065 SchB total_assets bug
- #11 COA Integrity Test
- #7 LLC Bus Health Agent
- #34 YE member notification
**Milestone:** `Cycle 1 — TY2025 Steady State`

### Project B — "Cycle 2 Validation + DevOps Hardening" (Weeks 5–9)
**Goal:** Run Cycle 2 (TY2026) using Project A's fixes; close DevOps process debt in parallel.
- Execute Cycle 2 end-to-end; any AcctOps bug it surfaces becomes a new `cycle:blocking` issue inside this project
- #13 wsCmd GPG docs
- #18 Server logging / pipeline tracing
- #24 / #25 Session templates
- #9 Credentials → config.json migration
**Milestone:** `Cycle 2 — TY2026 Steady State`

### Project C — "AppDev Documentation + Forward Features" (Weeks 9–13)
**Goal:** Close the AppDev structural gap (§5) and resume backlog enhancements once steady-state is proven.
- New issue: Agent & Aid inventory (catalog every agent/aid — Form1065Agent, Form8825Agent, Form4562Agent, FormSchK1Agent, LLCTaxAgent, irsRefAgent, PropAgent, planned BkAgent, planned Bus Health Agent — with one-line purpose each)
- New issue: AppDev relationship diagram (how the above components call each other / data flow between packages)
- #20 BankIngestionAgent
- #27 Auditing & Forensics (execute the existing design doc)
- #6, #10, #14, #15, #8(deferred) — backlog enhancements

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
2. Apply discipline labels to all 20 open issues per the table in §2
3. Create two GitHub Milestones: `Cycle 1 — TY2025 Steady State`, `Cycle 2 — TY2026 Steady State`; attach Project A's issue list to Milestone 1
4. File the two new AppDev issues from §5 (agent/aid inventory, relationship diagram)
5. ✅ Done — `design_WEB_01-webserver.md` moved into `docs/DevOps/`.
6. Diagram: [`docs/FlowSchematics/discipline_skills_repo.mmd`](../FlowSchematics/discipline_skills_repo.mmd) — the AcctOps/AppDev/DevOps triangle from §1.2, repeated per accounting cycle (TY2025 → 2026Q1..Q4 → TY2026) with cascading borders showing the roll-forward sequence.
