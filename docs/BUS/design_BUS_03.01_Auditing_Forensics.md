# design_BUS_03.01 — Auditing & Forensics: Earlier Is Better Than Later

**Stage:** 03 — Financial Analysis & Controls (between core accounting and IRS tax prep)
**Status:** PROPOSAL — pending review and GO

---

## 1. Problem Statement

Accounting forensics for W&B Group, LLC currently run exclusively during **Phase 4 (Tax Preparation)**, when the IRS form section agents (Form8825Agent, Form1065Agent, etc.) audit the GL as part of guided review.

This is late. By the time tax prep begins (Jan–Mar), the books have been wrong for months:
- Duplicate posts inflate expenses and distort net income for all preceding financial statements.
- Cross-property refund mis-tags understate one property's expenses and overstate another's cost basis.
- Financial decisions made during the year (distributions, capital calls, budgeting) were made on incorrect books.
- The section agents are the right expert logic — they're just deployed at the wrong point in time.

**Core principle: find errors where they are created, not 9 months later.**

---

## 2. What the Section Agents Already Catch (Phase 4)

The Form 8825 forensic rule (`F8NI-R05a…`) currently catches:

| Pattern | Flag | IRS Risk |
|---|---|---|
| Same-day, same-amount across different properties | `MULTI-PROP` | One property's expense understated; other's basis overstated. Distorts F8825 Line 21 → Sch K Line 2 → K-1 Box 2 |
| Identical (prop, acct, contra, aType) on same day/amount | `DUPLICATE` | Expense double-counted; net income wrong on IS, BS, and all IRS forms |

These rules are correct. The issue is when they run.

---

## 3. Three-Layer Control Architecture

### Layer 1 — GL Entry Prevention (Real-Time)

**When:** The instant a transaction enters `ledgerGeneral.mergeGL()`.
**What:** A lightweight pre-write validation checks for duplicate signatures before appending a GL row.
**Output:** Reject or warn — the transaction does not silently enter the books.

**Where to record:** A persistent `Accts/ledger_warnings.json`, keyed by tID. Each entry: rule, tID, date, description, status (`flagged` / `resolved`). The web editor Fix links already exist — connecting them to this store closes the loop.

**Effort:** Low. `mergeGL()` already iterates all rows; adding a duplicate-signature check is a few lines.

**Accounting authority:** IRC §446(a) — books must accurately reflect the LLC's accounting method. A duplicate entry violates this at the moment of entry, not at year-end.

---

### Layer 2 — Monthly/Quarterly Reconciliation (Periodic)

**When:** After each bank statement cycle (monthly or quarterly).
**What:** Compare GL cash balance vs. bank statement ending balance by period. Any discrepancy surfaces same-month.

**Output:** A `2025/Recon/reconciliation_log.json`, keyed by `YYYY-MM`. Each entry:
```json
{
  "period": "2025-10",
  "bank_ending_balance": 12345.67,
  "gl_ending_balance":   12289.23,
  "difference":          56.44,
  "status":              "open",
  "forensic_findings":   ["F8NI-R05b", "F8NI-R05c"],
  "notes":               ""
}
```

**What runs here:** A new `stmtReconciliation` object (same pattern as `stmtBalanceSheet`) that:
1. Reads bank statement CSVs from `books/<yr>/BankStmts/`
2. Computes GL cash balance through end of period
3. Runs the forensic rules from the section agents on that period's GL slice
4. Writes findings to `reconciliation_log.json`

**Flask route:** `GET /api/reconcile/<year>/<month>` — runs the reconciliation and returns a structured result for the web editor to display.

**Accounting authority:** Bank reconciliation is required under GAAP for any entity maintaining accrual or cash-basis books (ASC 305). IRC §446 requires books to be maintained in a manner that clearly reflects income — unreconciled cash discrepancies violate this.

---

### Layer 3 — Continuous Monitoring Agent (Always-On)

**When:** Triggered on any ledger write, or on a weekly schedule.
**What:** An independent audit agent runs all section-agent forensic rules across the full GL, not just at tax time.

**Output:** A persistent `audit_log.json` (or appended to `reconciliation_log.json`), with timestamped findings per rule. Each finding links to the tIDs that triggered it.

**The section agents are the right abstraction.** They are domain-expert rule engines for each IRS form area. The missing piece is:
1. A runner that calls them outside of guided review
2. A persistent finding store that carries state across sessions

**Flask route:** `GET /api/audit/<year>` — runs all forensic passes, persists findings, returns summary.

**Accounting authority:** IRC §703(a) — partnership income is computed at the partnership level from the partnership's books. Continuous integrity monitoring is the mechanism that keeps those books reliable.

---

## 4. Current State vs. Target State

| Control | Current | Target |
|---|---|---|
| Duplicate-post detection | Phase 4 (Tax Prep) | Phase 1 (GL Entry) |
| Cross-property refund mis-tag | Phase 4 | Phase 1 + Phase 2 (Monthly Recon) |
| Bank vs. GL cash reconciliation | Manual (not implemented) | Phase 2 (Monthly, automated) |
| Continuous book integrity | Not implemented | Phase 3 (Always-on, triggered) |
| Section agent forensics | Tax season only | Phase 4 + Phase 3 (continuous) |

---

## 5. Action Plan (Proposal)

### v1.4 — Layer 2: Monthly Reconciliation

**Tasks:**
1. Create `stmtReconciliation` in `stmt/` — reads bank CSV + GL, produces period balance comparison
2. Create `2025/Recon/reconciliation_log.json` schema and writer
3. Add Flask route `/api/reconcile/<year>/<month>`
4. Add reconciliation view to web editor (simple table: period, bank bal, GL bal, diff, status, findings)
5. Wire existing forensic rules to run per-period during reconciliation pass

**Outcome:** Monthly close becomes a 5-minute web editor review, not a year-end discovery.

---

### v1.5 — Layer 1: GL Entry Prevention

**Tasks:**
1. Add duplicate-signature check to `ledgerGeneral.mergeGL()` — warn on (date, amt, prop, acct, aType) collision
2. Create `Accts/ledger_warnings.json` schema and writer
3. Connect web editor Fix links to mark tIDs resolved in `ledger_warnings.json`
4. Surface open warnings as a persistent banner in the web editor (not just in guided review)

**Outcome:** Errors are caught the day they are entered, not discovered at tax time.

---

### v2.x — Layer 3: Continuous Monitoring Agent

**Tasks:**
1. Create `AuditAgent` — a thin runner that instantiates each section agent and calls its forensic rules on the full GL
2. Add scheduled trigger (weekly, or on ledger write via Flask post-save hook)
3. Persist findings to `audit_log.json` with timestamps and tID links
4. Add `/api/audit/<year>` route and a dashboard view

**Outcome:** Books are continuously audited. Tax prep guided review becomes a confirmation step, not a discovery step.

---

## 6. Design Constraints

- **Books-First Rule** (IRC §446 + §703): All forensic checks must read from the GL, never from IRS form output.
- **No silent fallbacks**: If `reconciliation_log.json` is missing, `/api/reconcile` fails with a clear error — it does not silently skip.
- **Section agents stay canonical**: The forensic rules live in the section agents. The reconciliation and monitoring layers call them; they do not re-implement the logic.
- **Persistence is additive**: `ledger_warnings.json`, `reconciliation_log.json`, and `audit_log.json` are append-only audit trails, not overwritten on each run.

---

## 7. Related Design Docs

- `design_BUS_01.1_AccountingDesign.md` — double-entry model and Books-First Rule
- `design_BUS_01.3-AccountingWorkflow.md` — GL generation pipeline (`mergeGL`)
- `design_BUS_04.6_Form8825Agent.md` — section agent forensic rules (current Phase 4 location)
- `design_BUS_04.2_LLCTaxAgent.md` — overall tax prep pipeline
