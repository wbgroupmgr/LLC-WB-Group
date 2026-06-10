# BankIngestionAgent (BkAgent) — Design

**Status:** v0.1 — 2026-06-10 (initial spec; not yet built)
**Owner:** Francisco Rojas (W&B Group, LLC)
**Stage:** AccountingWorkflow 01.5 — Transactional ingestion (upstream of all statements/forms)
**Related:** `design_BUS_01.5_ExpRevAgent.md`, `design_BUS_04.0_TaxPrep.md`,
`design_BUS_04.6_Form8825Agent.md`, `docs/FlowSchematics/BookToIRS_HL_Flow.mmd`

---

## 1. Why — Prevent Problems Early

**Core principle: every issue found downstream in BookToIRS is a fault at the *transactional step* of the accounting workflow.** By the time a mis-classification reaches Form 8825 / Form 1065, it has already polluted the GL, the IS, the BS, and every derived form. The cheapest place to catch it is at **bank-statement ingestion** — before it ever enters the ledger.

Two real 2025 incidents motivate this agent:

1. **CIP mis-classification.** RV_RV1 construction purchases were ingested as `Acct.Exp.Repair` / `Acct.Exp.Other` (operating expense) when the property was `Acct.Fixed.Tangible.InConstruction`. IRC §263(a) requires pre-placed-in-service costs to be **capitalized**, not expensed. The error surfaced only at Form 8825 (F8EX-R05 / F8NI-R04), forcing a manual ~$1,075 reclass across ~17 transactions.

2. **Refund mis-tagged to the wrong property.** A $14.06 WIMBERLEY ACE purchase + its return on 2025-10-09 were split across two properties — the refund landed on `H_805HighMesa` while the matching purchases were `RV_RV1`. This understated one property's expense and overstated the other's basis. Caught only by the new Form 8825 forensic rule (F8NI-R05), against the bank statement as source of truth.

Both are **ingestion-time** faults. The BkAgent's job is to prevent them at the source.

---

## 2. What — The Agent

The **BankIngestionAgent (BkAgent)** sits inside the bank-statement ingestion pipeline (`BankStmts/<date>*.csv` → `llcExpRev`). It is an intelligent classifier + auditor + rule-learner.

### 2.1 Responsibilities

1. **Infer the COA account from the bank description.** Use transaction-description history and banking best practices (vendor → category mapping), modeled on consumer finance apps (RocketMoney, Monarch Money, Copilot, YNAB). E.g. `WIMBERLEY ACE` → hardware/repair; `Pedernales_Elec ELEC_BILL` → `Acct.Exp.Util`; `ALLSTATE IND CO INS PYMT` → `Acct.Exp.Insurance`.

2. **Enforce the capitalization rule at ingestion.** When a transaction's `propNm` resolves to a property whose current state is a fixed asset **InConstruction** (`Acct.Fixed.Tangible.InConstruction`), the BkAgent must route the cost to CIP — NOT to an operating-expense account (IRC §263(a)). This single rule would have prevented incident #1 entirely.

3. **Detect purchase/return pairs and duplicates.** Same-amount / same-day / same-vendor clusters (a `PURCHASE` and its `PURCHASE RETURN`) must carry the **same** `propNm` and net correctly. Cross-property refunds (incident #2) are flagged before they enter the ledger.

4. **Post-ingestion audit + notify BookToIRS.** After each statement is ingested, the BkAgent audits the new transactions and **notifies the relevant BookToIRS section agents** (Form8825 / Form4562 / Form1065 / SchK1) of new patterns that need attention — closing the loop between ingestion and tax-form compliance.

5. **Learn over time.** Each resolved issue (operator confirms/corrects a classification) updates the BkAgent's ingestion rules/knowledge. Over time, ingestion of a recurring statement should flow **automatically** when nothing new appears — only genuinely novel patterns require operator review.

### 2.2 Design principle

> **Prevent problems early — across the whole accounting workflow.** The BkAgent is the upstream guardrail; the BookToIRS section agents are the downstream backstop. A fault caught at ingestion never reaches a tax form.

---

## 3. Data-Model Requirements (prerequisites)

These ledger-schema changes are required to support the BkAgent and are valuable independently:

### 3.1 `refDB` provenance — every ExpRev transaction must cite its source

Every `llcExpRev` transaction MUST have `refDB` pointing to a **specific** source:
- `BankStmts/<bankid>_<date>.csv` — for bank-ingested transactions (the exact statement file), or
- `llcBank-Manual` — for manual journaling entered directly in ExpRev.

This makes every transaction traceable to its source of truth (the bank statement line or the manual journal), which is exactly what the forensic rules need when they say "verify against the bank statement."

### 3.2 `llcExpRev` is a perpetual ledger — add a `LogHistory` stanza

`llcExpRev_WBGroupLLC.json` is a **perpetual** ledger DB (it accumulates across years and statements). Its schema needs a top-level **`LogHistory`** stanza recording every bank-statement ingestion event:

```json
"LogHistory": [
  {
    "ts": "2026-06-10T15:00:00Z",
    "source": "BankStmts/WBGroupLLC_WF_20251231.csv",
    "rows_ingested": 54,
    "rows_auto_classified": 50,
    "rows_flagged_for_review": 4,
    "bkagent_version": "0.1",
    "notes": "CIP capitalization enforced for RV_RV1; 1 cross-property refund flagged."
  }
]
```

This gives an audit trail of what was ingested when, by which agent version, and how many rows needed human review — supporting forensic reconstruction and regression detection.

---

## 4. Pipeline Position

```
BankStmts/<date>.csv
      │
      ▼
┌──────────────────────────────────────────────────────────────┐
│  BankIngestionAgent (BkAgent)                                 │
│   1. parse CSV rows                                           │
│   2. infer COA acct from description (history + rules)        │
│   3. resolve propNm; if property is InConstruction → CIP      │
│   4. detect purchase/return pairs + duplicates (same-day/amt) │
│   5. auto-classify confident rows; queue novel rows for review│
│   6. write rows to llcExpRev (refDB = this CSV)               │
│   7. append LogHistory entry                                  │
│   8. notify BookToIRS section agents of new patterns          │
└──────────────────────────────────────────────────────────────┘
      │
      ▼
  llcExpRev  →  GL  →  stmtIS/BS  →  BookToIRS  →  IRS forms
```

The BkAgent enforces correctness at the top of the funnel; the existing section-agent forensics (F8EX-R05, F8NI-R04/R05) remain as the downstream audit that confirms nothing slipped through.

---

## 5. Out of Scope (v0.1 spec)

- ML/LLM-based classification — v1 uses deterministic vendor→COA rules + history; an LLM classifier is a later enhancement.
- Direct bank API / Plaid integration — CSV import only for now.
- Multi-bank reconciliation — single Wells Fargo account in 2025.

---

## 6. Build Tracking

GitHub issue: **[#20 — Build BankIngestionAgent (BkAgent)](https://github.com/wbgroupmgr/llcRentalTracker/issues/20)** (actionable checklist derived from §2–§3).

---

*End of design_BUS_01.5_BankIngestionAgent.md — v0.1, 2026-06-10*
