# BankIngestionAgent (BkAgent) — Design

**Status:** v0.2 — 2026-06-19 (two-phase pipeline, module structure, schema changes, action plan)
**Owner:** Francisco Rojas (W&B Group, LLC)
**Stage:** AccountingWorkflow 01.5 — Transactional ingestion (upstream of all statements/forms)
**Related:** `design_BUS_01.5_ExpRevAgent.md`, `design_BUS_04.0_TaxPrep.md`,
`design_BUS_04.6_Form8825Agent.md`, `docs/FlowSchematics/BookToIRS_HL_Flow.mmd`
**GitHub:** [Issue #20](https://github.com/wbgroupmgr/llcRentalTracker/issues/20)

---

## 1. Why — Prevent Problems Early

**Core principle: every issue found downstream in BookToIRS is a fault at the *transactional step* of the accounting workflow.** By the time a mis-classification reaches Form 8825 / Form 1065, it has already polluted the GL, the IS, the BS, and every derived form. The cheapest place to catch it is at **bank-statement ingestion** — before it ever enters the ledger.

Two real 2025 incidents motivate this agent:

1. **CIP mis-classification.** RV_RV1 construction purchases were ingested as `Acct.Exp.Repair` / `Acct.Exp.Other` (operating expense) when the property was `Acct.Fixed.Tangible.InConstruction`. IRC §263(a) requires pre-placed-in-service costs to be **capitalized**, not expensed. The error surfaced only at Form 8825 (F8EX-R05 / F8NI-R04), forcing a manual ~$1,075 reclass across ~17 transactions.

2. **Refund mis-tagged to the wrong property.** A $14.06 WIMBERLEY ACE purchase + its return on 2025-10-09 were split across two properties — the refund landed on `H_805HighMesa` while the matching purchases were `RV_RV1`. This understated one property's expense and overstated the other's basis. Caught only by Form 8825 forensic rule F8NI-R05.

Both are **ingestion-time** faults. The BkAgent's job is to prevent them at the source.

---

## 2. What — The Agent

The **BankIngestionAgent (BkAgent)** sits inside the bank-statement ingestion pipeline (`BankStmts/<date>*.csv` → `llcExpRev`). It is an intelligent classifier + auditor + rule-learner that runs in a **two-phase preview/commit** model so the operator always reviews before writing to the ledger.

### 2.1 Responsibilities

1. **Infer the COA account from the bank description.** Use transaction-description history and banking best practices (vendor → category mapping), modeled on consumer finance apps (RocketMoney, Monarch Money, Copilot, YNAB). E.g. `WIMBERLEY ACE` → `Acct.Exp.Repair`; `Pedernales_Elec ELEC_BILL` → `Acct.Exp.Util`; `ALLSTATE IND CO INS PYMT` → `Acct.Exp.Ins`.

2. **Enforce the capitalization rule at ingestion.** When a transaction's `propNm` resolves to a property whose current COA state is `Acct.Fixed.Tangible.InConstruction`, the BkAgent must route the cost to CIP — NOT to any operating-expense account (IRC §263(a)). This single rule would have prevented incident #1 entirely.

3. **Detect purchase/return pairs and duplicates.** Same-amount / same-day / same-vendor clusters must carry the **same** `propNm` and net correctly. Cross-property refunds (incident #2) are flagged before they enter the ledger. Overlapping rows between successive CSV imports (e.g., two statements with a shared tail) are also caught.

4. **Post-ingestion audit + notify BookToIRS.** After each commit, the BkAgent audits the new transactions and notifies the relevant BookToIRS section agents (Form8825 / Form4562 / Form1065 / SchK1) of new patterns — closing the loop between ingestion and tax-form compliance.

5. **Learn over time.** Each resolved issue (operator confirms/corrects a classification) updates the BkAgent's vendor KB. Over time, ingestion of a recurring statement should flow **automatically** when nothing new appears — only genuinely novel patterns require operator review.

### 2.2 Design Principle

> **Prevent problems early — across the whole accounting workflow.** The BkAgent is the upstream guardrail; the BookToIRS section agents are the downstream backstop. A fault caught at ingestion never reaches a tax form.

---

## 3. Data-Model Prerequisites

These schema changes are required before the BkAgent can be built. They are valuable independently.

### 3.1 `llcExpRev_*.json` — wrap flat list in a named struct

Current schema is a flat JSON array. Needs to become a top-level object to support `LogHistory`:

```json
{
  "records": [ ...existing ExpRev transaction dicts... ],
  "LogHistory": []
}
```

Migration: one-time script wraps the existing list under `"records"`, adds `"LogHistory": []`. All readers must update to `d["records"]`.

### 3.2 `refDB` — specific provenance per transaction

Every `llcExpRev` record must have `refDB` pointing to its exact source:
- `"BankStmts/WBGroupLLC_WF_20251231.csv"` — bank-ingested (relative to `books/<year>/`)
- `"llcBank-Manual"` — operator journal entry

Current state: all 53 records carry `"refDB": "llcBank"` (generic). Migration: existing records stay as-is (they pre-date the BkAgent); only new ingested rows must carry the specific CSV path.

### 3.3 `LogHistory` stanza

Top-level `LogHistory` array in `llcExpRev_*.json`:

```json
{
  "ts": "2026-06-19T15:00:00Z",
  "source": "BankStmts/WBGroupLLC_WF_20251231.csv",
  "rows_in_csv": 54,
  "rows_new": 51,
  "rows_duplicate": 3,
  "rows_auto_classified": 48,
  "rows_flagged_for_review": 6,
  "bkagent_version": "0.1",
  "notes": "CIP capitalization enforced for RV_RV1; 1 cross-property refund flagged."
}
```

---

## 4. Pipeline Design

### 4.1 Two-Phase Preview / Commit

The BkAgent operates in two phases — operator always sees a preview before any write.

```
Phase 1 — PREVIEW (read-only)
  BankIngestAgent.preview(csv_path, propNm_default, year)
    → PreviewResult {
        rows: [ ClassifiedRow, ...],   # one per CSV line
        flags: [ FlaggedIssue, ...],   # CIP violations, cross-property refunds, duplicates
        stats: { new, duplicate, auto_classified, needs_review }
      }

Phase 2 — COMMIT (write)
  BankIngestAgent.commit(preview_result)
    → CommitResult {
        rows_written: int,
        log_entry: LogHistory,
      }
    writes: llcExpRev records + LogHistory entry
    does NOT call BookToIRS notification (separate step, post-commit)
```

**Key invariant:** `commit()` only accepts a `PreviewResult` object returned by `preview()`. It re-validates the preview token before writing — no blind commit from raw CSV.

### 4.2 ClassifiedRow Structure

```python
@dataclass
class ClassifiedRow:
    dt:         str      # YYYY.MM.DD
    amt:        float    # positive = credit, negative = debit
    desc:       str      # raw bank description
    acct:       str      # inferred COA account (e.g. "Acct.Exp.Repair")
    acctSub:    str      # sub-category detail
    propNm:     str      # property or "LLC"
    confidence: str      # "auto" | "review" | "flagged"
    flag:       str      # "" | "CIP_VIOLATION" | "CROSS_PROP_REFUND" | "DUPLICATE"
    refDB:      str      # "BankStmts/WBGroupLLC_WF_20251231.csv"
    vendor_key: str      # normalized vendor key for KB lookup/update
```

### 4.3 Duplicate Detection — Two Dimensions

**Intra-CSV pairs:** within one statement, `PURCHASE RETURN` lines must match a same-vendor purchase within a 3-day window by amount. If the paired purchase and return carry different `propNm`, flag as `CROSS_PROP_REFUND`.

**Inter-CSV overlap:** when two successive CSV exports share tail rows (bank exports often overlap by a few days), detect existing `tID`s in `llcExpRev.records` before writing. Use `tID = f"{dt}_{D|C}{abs(amt):.2f}"` as the deduplication key (matches current tID convention).

### 4.4 Pipeline Position

```
BankStmts/<year>/WBGroupLLC_WF_<date>.csv
      │
      ▼
┌──────────────────────────────────────────────────────────────────┐
│  BankIngestionAgent (BkAgent) — Phase 1: preview()               │
│   1. BankCSVParser.parse()     → raw rows                        │
│   2. BkDuplicateDetector       → mark duplicates + return pairs  │
│   3. BkVendorKB.lookup()       → candidate COA + confidence      │
│   4. BkCIPGuard.check()        → override to CIP if InConstruct  │
│   5. BkClassifier.classify()   → final ClassifiedRow per line    │
│   6. return PreviewResult (nothing written yet)                   │
└──────────────────────────────────────────────────────────────────┘
      │ operator reviews preview
      ▼
┌──────────────────────────────────────────────────────────────────┐
│  BankIngestionAgent — Phase 2: commit()                          │
│   7. re-validate PreviewResult token                             │
│   8. write new rows → llcExpRev.records (skip duplicates)        │
│   9. append LogHistory entry                                     │
│  10. notify BookToIRS section agents of new patterns             │
└──────────────────────────────────────────────────────────────────┘
      │
      ▼
  llcExpRev → GL → stmtIS/BS → BookToIRS → IRS forms
```

---

## 5. Vendor Knowledge Base (BkVendorKB)

### 5.1 `vendor_rules.json`

Operator-editable file at `ledger/bankAgent/vendor_rules.json`. Each rule maps a regex pattern to a COA account:

```json
{
  "rules": [
    {
      "pattern": "Pedernales_Elec|PEC ELEC_BILL",
      "acct": "Acct.Exp.Util",
      "acctSub": "Electricity",
      "confidence": "auto",
      "notes": "Pedernales Electric Cooperative — H_805HighMesa"
    },
    {
      "pattern": "WIMBERLEY ACE|Kings Feed And Hardware",
      "acct": "Acct.Exp.Repair",
      "acctSub": "Hardware/Supplies",
      "confidence": "auto"
    },
    {
      "pattern": "ALLSTATE IND CO INS PYMT",
      "acct": "Acct.Exp.Ins",
      "acctSub": "Property Insurance",
      "confidence": "auto"
    },
    {
      "pattern": "BILL PAY Water-COMWSC",
      "acct": "Acct.Exp.Util",
      "acctSub": "Water",
      "confidence": "auto"
    },
    {
      "pattern": "ZELLE FROM",
      "acct": "Acct.Rev.Rent",
      "acctSub": "Rental Income",
      "confidence": "review",
      "notes": "Confirm propNm and tenant for each Zelle inflow"
    },
    {
      "pattern": "AMAZON MKTPL|AMAZON.COM",
      "acct": "Acct.Exp.Repair",
      "acctSub": "Supplies",
      "confidence": "review",
      "notes": "Amazon could be repair, operating, or CIP — confirm per propNm"
    },
    {
      "pattern": "LOWE'S|LOWES|LAIRD PLASTICS|RODCO STEEL",
      "acct": "Acct.Exp.Repair",
      "acctSub": "Materials",
      "confidence": "review",
      "notes": "Construction materials — verify CIP guard for InConstruction properties"
    },
    {
      "pattern": "WITHDRAWAL MADE IN A BRANCH|eWithdrawal|eDeposit",
      "acct": "Acct.Cash.Bank",
      "acctSub": "Transfer",
      "confidence": "review"
    }
  ],
  "version": "0.1",
  "last_updated": "2026-06-19"
}
```

### 5.2 Learning Loop

When an operator corrects a `confidence: "review"` row during the commit phase, the correction is optionally fed back:

```python
BkVendorKB.learn(vendor_key, confirmed_acct, confirmed_acctSub)
```

This either raises the confidence of an existing rule to `"auto"` or inserts a new rule. Rules are written back to `vendor_rules.json` so they apply on the next ingestion. Over time, the operator's corrections encode LLC-specific knowledge permanently.

---

## 6. Module Structure

All new code lives under `ledger/bankAgent/`:

```
ledger/
  bankAgent/
    __init__.py
    bkCSVParser.py          # BankCSVParser: parse WF CSV → list[RawRow]
    bkVendorKB.py           # BkVendorKB: pattern→COA lookup + learn()
    bkCIPGuard.py           # BkCIPGuard: enforce IRC §263(a) InConstruction override
    bkDuplicateDetector.py  # BkDuplicateDetector: intra-CSV pairs + inter-CSV overlap
    bkClassifier.py         # BkClassifier: combine KB + CIP + dup → ClassifiedRow
    bankIngestAgent.py      # BankIngestAgent: preview() + commit() orchestration
    vendor_rules.json       # operator-editable KB (seed entries from §5.1)

Notebooks/
  bankIngestPreview.ipynb   # Jupyter diagnostic: load CSV → preview → inspect flags

ui/
  llcBankIngest.py          # Flask routes: /api/bank/ingest/preview + /commit
  templates/
    bank_ingest.html        # Two-phase UI: upload CSV → review table → commit
```

### 6.1 Class Responsibilities

| Class | File | Key Methods |
|---|---|---|
| `BankCSVParser` | `bkCSVParser.py` | `parse(csv_path, year) → list[RawRow]` |
| `BkVendorKB` | `bkVendorKB.py` | `lookup(desc) → (acct, acctSub, confidence)`, `learn(key, acct, sub)` |
| `BkCIPGuard` | `bkCIPGuard.py` | `check(propNm, acct, llc) → acct` — overrides to CIP if property InConstruction |
| `BkDuplicateDetector` | `bkDuplicateDetector.py` | `scan(rows, existing_tIDs) → rows_with_dup_flags` |
| `BkClassifier` | `bkClassifier.py` | `classify(raw_row, propNm, llc) → ClassifiedRow` |
| `BankIngestAgent` | `bankIngestAgent.py` | `preview(csv_path, propNm, year) → PreviewResult`, `commit(preview) → CommitResult` |

### 6.2 `BankCSVParser` — WF CSV Format

Wells Fargo CSV columns (no header row): `date, amount, *, check_num, description`

```python
# date format: "12/29/2025"  →  dt: "2025.12.29"
# amount: negative = debit (expense), positive = credit (income)
# tID convention: f"{dt}_{D if amt<0 else C}{abs(amt):.2f}"
```

### 6.3 `BkCIPGuard` — Capitalization Enforcement

```python
def check(self, propNm: str, proposed_acct: str, llc) -> str:
    """
    IRC §263(a): if the property is InConstruction, ALL costs are CIP.
    Returns corrected acct — caller must surface a CIP_VIOLATION flag
    if proposed_acct != returned acct.
    """
    if self._is_in_construction(propNm, llc):
        return "Acct.Fixed.Tangible.InConstruction"
    return proposed_acct

def _is_in_construction(self, propNm: str, llc) -> bool:
    # Query llcAssets for any active asset with propNm and
    # acct == "Acct.Fixed.Tangible.InConstruction"
```

---

## 7. Flask UI Integration

Two new routes in `ui/llcBankIngest.py`, bound in `ui/llcMgmt.py`:

| Route | Method | Description |
|---|---|---|
| `/api/bank/ingest/preview` | POST | Body: `{csv_path, propNm, year}` → returns `PreviewResult` JSON |
| `/api/bank/ingest/commit` | POST | Body: `{preview_token}` → returns `CommitResult` JSON |
| `/view/bank_ingest` | GET | Renders `bank_ingest.html` — two-phase UI |

**`bank_ingest.html`** flow:
1. Upload / select CSV from `BankStmts/<year>/`
2. Set default `propNm` (dropdown of active properties)
3. Preview table: one row per transaction, editable `acct`/`propNm`, CIP flags highlighted in amber, cross-property refunds in red
4. Operator reviews, corrects flagged rows
5. "Commit" button → POST to `/api/bank/ingest/commit`
6. Success: shows `CommitResult` stats + LogHistory entry

---

## 8. `bankIngestPreview.ipynb`

Located at `Notebooks/bankIngestPreview.ipynb`. Purpose: diagnostic and debugging tool for the BkAgent outside the web app.

```python
# Cell 1 — setup
from ledger import setup_paths
setup_paths.load_bootstrap('WBGroupLLC')
from ledger.bankAgent.bankIngestAgent import BankIngestAgent

# Cell 2 — preview a CSV
agent = BankIngestAgent(llc)
result = agent.preview('books/2025/BankStmts/WBGroupLLC_WF_20251231.csv',
                       propNm_default='H_805HighMesa', year=2025)

# Cell 3 — inspect flags
import pandas as pd
df = pd.DataFrame([r.__dict__ for r in result.rows])
display(df[df.flag != ''])   # show flagged rows

# Cell 4 — inspect auto vs review
display(df.groupby(['confidence','acct']).size().reset_index(name='count'))

# Cell 5 — commit (after manual review of flags above)
# agent.commit(result)   # uncomment to write
```

---

## 9. Out of Scope (v0.1 implementation)

- ML/LLM-based classification — v1 uses deterministic vendor→COA rules + history; LLM classifier is a later enhancement.
- Direct bank API / Plaid integration — CSV import only for now.
- Multi-bank reconciliation — single Wells Fargo account.
- Flask upload endpoint (file upload from browser) — v0.1 uses server-local CSV path; browser file upload is v0.2.

---

## 10. Build Tracking

GitHub issue: **[#20 — Build BankIngestionAgent (BkAgent)](https://github.com/wbgroupmgr/llcRentalTracker/issues/20)**

Action plan phases (see issue comment):
- **Phase 0** — Schema migration (`llcExpRev` struct, `LogHistory`)
- **Phase 1** — Core classifiers (`BankCSVParser`, `BkVendorKB`, `BkCIPGuard`, `BkDuplicateDetector`, `BkClassifier`)
- **Phase 2** — Orchestration (`BankIngestAgent.preview()` + `commit()`)
- **Phase 3** — Notebook + Flask UI
- **Phase 4** — Learning feedback loop + auto-commit mode

---

*End of design_BUS_01.5_BankIngestionAgent.md — v0.2, 2026-06-19*
