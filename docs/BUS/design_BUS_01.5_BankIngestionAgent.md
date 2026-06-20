# BankAgent + IngestAgent — Design

**Status:** v0.3 — 2026-06-19 (rewrite; two-agent architecture)
**Owner:** Francisco Rojas (W&B Group, LLC)
**Stage:** AccountingWorkflow 01.5 — Transactional ingestion (upstream of all statements/forms)
**Related:** `design_BUS_01.5_ExpRevAgent.md`, `design_BUS_04.0_TaxPrep.md`,
`design_BUS_04.6_Form8825Agent.md`
**GitHub:** [Issue #20](https://github.com/wbgroupmgr/llcRentalTracker/issues/20)

---

## 1. Why — Two Goals, Two Agents

The BankToBook pipeline has two distinct failure modes, each requiring a dedicated agent:

**Goal 1 — Smart Classification (BankAgent).** Most bank transactions are routine and repeatable — rent income, utilities, hardware, insurance. But a subset are *special*: a property closing, a member capital investment, a mortgage payoff. A naive ingestion process treats all rows the same and mis-classifies the special ones. The **BankAgent** is a "smart banker" that learns the LLC's transaction patterns and flags — or auto-routes — special transactions to the right COA account.

**Goal 2 — Prevent Problems Early (IngestAgent).** Nearly every downstream error in BookToIRS traces back to a mis-classification at ingestion. Two real 2025 incidents prove this:

1. **CIP mis-classification.** RV_RV1 construction purchases were ingested as `Acct.Exp.Repair` / `Acct.Exp.Other` when the property was `Acct.Fixed.Tangible.InConstruction`. IRC §263(a) requires capitalization. Error surfaced only at Form 8825 (F8EX-R05), forcing a manual ~$1,075 reclass across ~17 transactions.

2. **Refund mis-tagged to wrong property.** A $14.06 WIMBERLEY ACE purchase + its return on 2025-10-09 were split across two properties — the refund landed on `H_805HighMesa`, the purchases on `RV_RV1`. Caught only by forensic rule F8NI-R05 in the IRS pipeline, far too late.

The **IngestAgent** is the safety net that prevents these at the top of the funnel, before any row reaches the GL.

> **Design principle: smart banker classification + prevent problems early — across the whole accounting workflow.**

---

## 2. Two-Agent Architecture

The two agents have distinct responsibilities and compose in a clear sequence:

```
BankStmts/<year>/<date>.csv
        │
        ▼
┌──────────────────────────────────────────────┐
│  IngestAgent — Phase 1: preview()             │
│   1. BankCSVParser → raw rows                 │
│   2. BkDuplicateDetector → mark pairs + dups  │
│   3. BankAgent.classify() → ClassifiedRow     │  ← BankAgent called here
│   4. BkCIPGuard → override if InConstruction  │
│   5. return PreviewResult (nothing written)   │
└──────────────────────────────────────────────┘
        │  operator reviews preview
        ▼
┌──────────────────────────────────────────────┐
│  IngestAgent — Phase 2: commit()              │
│   6. skip DUPLICATE rows                      │
│   7. write new rows → llcExpRev.records       │
│   8. append LogHistory entry                  │
│   9. BkAuditNotifier → notify BookToIRS       │
└──────────────────────────────────────────────┘
        │
        ▼
  llcExpRev → GL → stmtIS/BS → BookToIRS → IRS forms
```

**BankAgent** = the intelligence layer (what to classify, how to learn).
**IngestAgent** = the pipeline orchestrator (sequencing, safety rules, phases, audit trail).

The IngestAgent calls the BankAgent; the BankAgent has no knowledge of the pipeline or phases.

---

## 3. BankAgent — The Inference Engine

### 3.1 Core Responsibility

The BankAgent classifies a single bank transaction into a COA account + transaction type. It is called once per row during Phase 1 of the IngestAgent pipeline. It is also callable standalone (from the notebook, from tests, from a REPL).

```
BankAgent.classify(raw_row, context) → ClassifiedRow
```

### 3.2 Transaction Types

The BankAgent recognizes two tiers of transactions:

**Tier 1 — Routine (auto-classifiable)**

| Pattern | COA Account | Notes |
|---|---|---|
| Utility vendor (Pedernales, COMWSC Water) | `Acct.Exp.Util` | recurring; auto after first match |
| Hardware/repair (Wimberley ACE, Kings Feed, Harbor Freight) | `Acct.Exp.Repair` | frequent; auto |
| Insurance (Allstate, State Farm) | `Acct.Exp.Ins` | monthly recurring |
| Management fees | `Acct.Exp.Fees.Mgmt` | periodic |
| HOA / operating (HOA, subscriptions) | `Acct.Exp.Operating` | periodic |
| Property tax (HAYS CO TX WIMBER) | `Acct.Exp.Tax.Prop` | annual |
| Rental income (Zelle from known tenant) | `Acct.Rev.Rent` | monthly; propNm from tenant table |
| Late fees, other fees | `Acct.Rev.Fees.Late` | |

**Tier 2 — Special (require operator review or context)**

| Transaction Signal | COA Account | Why Special |
|---|---|---|
| Large wire out > $50k | `Acct.Fixed.Tangible` or `Acct.Cash.Bank` | Property closing or large transfer |
| `WT FED#` / `WITHDRAWAL MADE IN A BRANCH` > $50k | `Acct.Fixed.Tangible` | Closing — route to CIP or InService |
| `WT FED#` inbound + member name | `Acct.Equity.Owner.Capital.Funds` | Member capital investment |
| Large check out (mortgage-sized) | `Acct.Liab.Morgage` split | Principal + `Acct.Exp.Int.Morg` |
| `TRUIST ACCTVERIFY` micro-deposits | `Acct.Cash.Bank` | ACH verification — not an expense |
| `Promotion Bonus` / bank incentive | `Acct.Rev.Ord.Other` | Miscellaneous income |
| Vendor Amazon / Walmart / big-box | `Acct.Exp.Repair` or flagged | Could be CIP; confirm per propNm |
| Zelle from unknown sender | Flagged | Could be investment, rent, or personal |
| `PURCHASE RETURN` | Mirror of the purchase | Must match propNm of paired purchase |

### 3.3 BkVendorKB — The Knowledge Base

`ledger/bankAgent/vendor_rules.json` — operator-editable, version-controlled:

```json
{
  "version": "0.1",
  "last_updated": "2026-06-19",
  "rules": [
    {
      "pattern": "Pedernales_Elec|PEC ELEC_BILL",
      "txn_type": "ROUTINE_EXPENSE",
      "acct": "Acct.Exp.Util",
      "acctSub": "Electricity",
      "confidence": "auto"
    },
    {
      "pattern": "BILL PAY Water-COMWSC",
      "txn_type": "ROUTINE_EXPENSE",
      "acct": "Acct.Exp.Util",
      "acctSub": "Water",
      "confidence": "auto"
    },
    {
      "pattern": "WIMBERLEY ACE|Kings Feed And Hardware|Harbor Freight",
      "txn_type": "ROUTINE_EXPENSE",
      "acct": "Acct.Exp.Repair",
      "acctSub": "Hardware/Supplies",
      "confidence": "auto"
    },
    {
      "pattern": "ALLSTATE IND CO INS PYMT",
      "txn_type": "ROUTINE_EXPENSE",
      "acct": "Acct.Exp.Ins",
      "acctSub": "Property Insurance",
      "confidence": "auto"
    },
    {
      "pattern": "HAYS CO TX WIMBER",
      "txn_type": "ROUTINE_EXPENSE",
      "acct": "Acct.Exp.Tax.Prop",
      "acctSub": "Property Tax",
      "confidence": "auto"
    },
    {
      "pattern": "Texas Disposal|TEXAS DISPOSAL",
      "txn_type": "ROUTINE_EXPENSE",
      "acct": "Acct.Exp.Util",
      "acctSub": "Trash",
      "confidence": "auto"
    },
    {
      "pattern": "ZELLE FROM",
      "txn_type": "RENT_INCOME",
      "acct": "Acct.Rev.Rent",
      "acctSub": "Rental Income",
      "confidence": "review",
      "notes": "Confirm propNm and tenant; could be member investment if sender is a member"
    },
    {
      "pattern": "AMAZON MKTPL|AMAZON.COM|WAL-MART|H-E-B",
      "txn_type": "ROUTINE_EXPENSE",
      "acct": "Acct.Exp.Repair",
      "acctSub": "Supplies",
      "confidence": "review",
      "notes": "Could be CIP if propNm is InConstruction — BkCIPGuard will override"
    },
    {
      "pattern": "LOWE'S|LOWES|LAIRD PLASTICS|RODCO STEEL|SQ \\*",
      "txn_type": "ROUTINE_EXPENSE",
      "acct": "Acct.Exp.Repair",
      "acctSub": "Materials",
      "confidence": "review",
      "notes": "Construction materials — CIP guard critical for InConstruction properties"
    },
    {
      "pattern": "WT FED#|NATIONAL FINANCIAL",
      "txn_type": "SPECIAL_WIRE",
      "acct": "Acct.Cash.Bank",
      "acctSub": "Wire Transfer",
      "confidence": "flagged",
      "notes": "Could be property acquisition, member investment, or large transfer — always review"
    },
    {
      "pattern": "WITHDRAWAL MADE IN A BRANCH",
      "txn_type": "SPECIAL_WIRE",
      "acct": "Acct.Cash.Bank",
      "acctSub": "Branch Withdrawal",
      "confidence": "flagged",
      "notes": "Large branch withdrawal — property closing candidate"
    },
    {
      "pattern": "TRUIST ACCTVERIFY",
      "txn_type": "ACH_VERIFY",
      "acct": "Acct.Cash.Bank",
      "acctSub": "ACH Verification",
      "confidence": "auto",
      "notes": "Micro-deposit pairs net to zero; mark both as ACH_VERIFY"
    },
    {
      "pattern": "VENMO ADDFUNDS",
      "txn_type": "TRANSFER",
      "acct": "Acct.Cash.Bank",
      "acctSub": "Transfer Out",
      "confidence": "review"
    }
  ]
}
```

### 3.4 Perpetual Learning

Each time an operator corrects a `confidence: "review"` or `confidence: "flagged"` row during the commit phase, the BankAgent learns:

```python
BankAgent.learn(vendor_key, confirmed_acct, confirmed_acctSub, confirmed_txn_type)
```

This either raises an existing rule's confidence to `"auto"` or inserts a new rule. Corrections are written back to `vendor_rules.json` so they apply on the next ingestion. Over time, recurring-statement rows that required review become `auto`, and the operator only sees genuinely novel patterns.

**Auto-commit eligibility:** when a full statement preview contains zero `"review"` or `"flagged"` rows and zero IngestAgent flags, the IngestAgent surfaces an "auto-commit" option — still requiring operator confirmation, but skipping the row-by-row review.

### 3.5 ClassifiedRow Output

```python
@dataclass
class ClassifiedRow:
    # from BankCSVParser
    dt:         str      # YYYY.MM.DD
    amt:        float    # negative = debit (expense), positive = credit (income)
    desc:       str      # raw bank description
    check_num:  str      # check number or ""
    tID:        str      # f"{dt}_{D|C}{abs(amt):.2f}" — dedup key

    # from BankAgent
    txn_type:   str      # ROUTINE_EXPENSE | RENT_INCOME | SPECIAL_WIRE | MEMBER_INVEST | etc.
    acct:       str      # COA account
    acctSub:    str      # sub-category
    propNm:     str      # property or "LLC" — operator sets; BankAgent may suggest
    confidence: str      # "auto" | "review" | "flagged"
    vendor_key: str      # normalized vendor string (for KB lookup/learn)

    # from IngestAgent
    flag:       str      # "" | "CIP_VIOLATION" | "CROSS_PROP_REFUND" | "DUPLICATE" | "RETURN_PAIR"
    refDB:      str      # "BankStmts/WBGroupLLC_WF_20251231.csv"
```

---

## 4. IngestAgent — The Pipeline Orchestrator

### 4.1 Core Responsibility

The IngestAgent owns the two-phase ingestion pipeline. It calls the BankAgent for classification but is solely responsible for:
- Sequencing (parse → detect → classify → guard → preview → commit)
- Safety rules (CIP enforcement, duplicate suppression, cross-property refund detection)
- Data integrity (no duplicate tIDs in `llcExpRev`)
- Audit trail (`LogHistory`, `refDB` provenance)
- Post-commit BookToIRS notification

### 4.2 Phase 1 — Preview (read-only)

```python
IngestAgent.preview(csv_path: str, propNm_default: str, year: int) → PreviewResult
```

Steps — nothing is written:

1. **`BankCSVParser.parse()`** → `list[RawRow]` from the WF CSV
2. **`BkDuplicateDetector.scan()`** → mark `DUPLICATE` rows (tID already in `llcExpRev`) and identify `PURCHASE RETURN` pairs within the CSV
3. **`BankAgent.classify()`** → `ClassifiedRow` per non-duplicate row (vendor KB lookup + txn type detection)
4. **`BkCIPGuard.check()`** → for each classified row, if `propNm` resolves to an InConstruction property and `acct` is any `Acct.Exp.*`, override `acct` to `Acct.Fixed.Tangible.InConstruction` and set `flag = "CIP_VIOLATION"`

Return:
```python
@dataclass
class PreviewResult:
    rows:   list[ClassifiedRow]
    flags:  list[str]          # human-readable flag summaries
    stats:  dict               # new, duplicate, auto, review, flagged counts
    source: str                # csv_path
    ts:     str                # ISO timestamp of preview
```

### 4.3 Phase 2 — Commit (write)

```python
IngestAgent.commit(preview: PreviewResult) → CommitResult
```

Steps:
1. Re-validate `preview` object (must be a `PreviewResult` from this agent, not raw data)
2. For each row where `flag != "DUPLICATE"`: build `llcExpRev` record and append to `records`
3. Append `LogHistory` entry
4. Write updated `llcExpRev_*.json` to disk
5. Invalidate `eSession.books` (`BooksContext.invalidate()`)
6. Call `BkAuditNotifier.notify(committed_rows, llc)` — post-commit BookToIRS notification

**Invariant:** `commit()` only accepts a `PreviewResult`. There is no path to write to `llcExpRev` from a raw CSV in a single step.

### 4.4 BkCIPGuard — IRC §263(a) Enforcement

The CIP guard is a hard override — not a suggestion. It cannot be bypassed from the UI.

```python
def check(self, propNm: str, proposed_acct: str, llc) -> tuple[str, bool]:
    """
    Returns (final_acct, cip_violated).
    If property is InConstruction and proposed_acct is Acct.Exp.*,
    returns Acct.Fixed.Tangible.InConstruction and cip_violated=True.
    """
```

The operator can only clear a CIP flag by first updating the COA (marking the property as InService in `llcAssets`), which correctly reflects that the property has been placed in service.

### 4.5 BkDuplicateDetector — Two Dimensions

**Intra-CSV purchase/return pairs:**
- Within one CSV, find each `PURCHASE RETURN` line and match to a same-vendor, same-amount purchase within a ±3-day window
- If matched pair has mismatched `propNm` → flag `CROSS_PROP_REFUND`
- If no matching purchase found → flag `RETURN_PAIR` for review

**Inter-CSV overlap (duplicate tIDs):**
- Load existing `tID` set from `llcExpRev.records`
- Any new row whose `tID` matches an existing record → flag `DUPLICATE`; skip on commit
- Some Wells Fargo CSV exports overlap at the tail; this suppresses double-ingestion silently

### 4.6 BkAuditNotifier — Post-Commit BookToIRS Notification

After a successful commit, the notifier scans the committed rows for patterns requiring downstream attention:

| Pattern in committed rows | Notifies |
|---|---|
| Any CIP-routed row | Form4562 agent — new asset cost; may affect depreciation |
| Any `Acct.Fixed.Tangible` or `Acct.Fixed.Tangible.InService` row | Form8825 agent — asset basis change |
| Any `Acct.Equity.Owner.Capital.*` row | SchK1 agent — capital account change |
| Any `Acct.Rev.Rent` row with new propNm | Form8825 agent — new income stream |
| Any `SPECIAL_WIRE` txn type | All section agents — significant financial event |

Notification in v0.1 is a log message + a JSON entry in `books/<year>/Forms/.agent_work/IngestAgent_notifications.json`. Section agents read this file at the start of their next run.

---

## 5. Data-Model Prerequisites

These schema changes are required before either agent can be built.

### 5.1 `llcExpRev_*.json` — Wrap flat list in a struct

Current: flat JSON array of 53 records.
Required: top-level object:

```json
{
  "records": [ ...existing llcExpRev transaction dicts... ],
  "LogHistory": []
}
```

One-time migration script: `ledger/bankAgent/migrate_exprev_schema.py`. All readers (`llcExpRev.py`, `stmtIS`, `stmtGL`, `stmtBS`, `ui/llcExpRev.py`) update to `d["records"]`.

### 5.2 `refDB` Provenance

Every new transaction written by the IngestAgent must carry:
- `"refDB": "BankStmts/WBGroupLLC_WF_<date>.csv"` (relative to `books/<year>/`)

Existing records retain `"refDB": "llcBank"` — they pre-date the IngestAgent and the manual entry provenance is unknown.

Manual journal entries (added via the web editor) must carry `"refDB": "llcBank-Manual"`.

### 5.3 LogHistory Stanza

```json
{
  "ts": "2026-06-19T15:30:00Z",
  "source": "BankStmts/WBGroupLLC_WF_20251231.csv",
  "rows_in_csv": 54,
  "rows_new": 51,
  "rows_duplicate": 3,
  "rows_auto_classified": 46,
  "rows_flagged_review": 3,
  "rows_flagged_cip": 1,
  "rows_flagged_cross_prop": 1,
  "bkagent_version": "0.1",
  "ingest_agent_version": "0.1",
  "notes": ""
}
```

---

## 6. Module Structure

```
ledger/
  bankAgent/
    __init__.py
    BankAgent.py              # BankAgent: classify() + learn()
    bkVendorKB.py             # BkVendorKB: pattern → COA lookup, rule persistence
    bkTxnTypeDetector.py      # BkTxnTypeDetector: ROUTINE_EXPENSE / SPECIAL_WIRE / etc.
    IngestAgent.py            # IngestAgent: preview() + commit()
    bkCSVParser.py            # BankCSVParser: WF CSV → list[RawRow]
    bkCIPGuard.py             # BkCIPGuard: IRC §263(a) InConstruction override
    bkDuplicateDetector.py    # BkDuplicateDetector: intra-CSV pairs + inter-CSV dedup
    bkAuditNotifier.py        # BkAuditNotifier: post-commit BookToIRS notification
    migrate_exprev_schema.py  # one-time migration: flat list → {records, LogHistory}
    vendor_rules.json         # operator-editable KB (seeded; grows via learn())

Notebooks/
  bankIngestPreview.ipynb     # diagnostic: load CSV → preview → inspect → optional commit

ui/
  llcBankIngest.py            # Flask routes: /api/bank/ingest/preview + /commit
  templates/
    bank_ingest.html          # two-phase UI: select CSV → review → commit
```

### 6.1 Class Summary

| Class | Key Methods | Owned By |
|---|---|---|
| `BankAgent` | `classify(raw_row, context) → ClassifiedRow`, `learn(vendor_key, ...)` | BankAgent layer |
| `BkVendorKB` | `lookup(desc)`, `learn(key, acct, sub)`, `save()` | BankAgent |
| `BkTxnTypeDetector` | `detect(desc, amt) → TxnType` | BankAgent |
| `IngestAgent` | `preview(csv_path, propNm, year) → PreviewResult`, `commit(preview) → CommitResult` | IngestAgent layer |
| `BankCSVParser` | `parse(csv_path, year) → list[RawRow]` | IngestAgent |
| `BkCIPGuard` | `check(propNm, acct, llc) → (acct, violated)` | IngestAgent |
| `BkDuplicateDetector` | `scan(rows, existing_tIDs) → rows_with_flags` | IngestAgent |
| `BkAuditNotifier` | `notify(rows, llc)` | IngestAgent |

---

## 7. `bankIngestPreview.ipynb` — Diagnostic Notebook

Located at `Notebooks/bankIngestPreview.ipynb`. Covers both agents independently and together.

```python
# Cell 1 — setup
from ledger import setup_paths
setup_paths.load_bootstrap('WBGroupLLC')
from ledger.LLC import LLC
llc = LLC('WBGroupLLC', year=2025)

# Cell 2 — test BankAgent standalone (no ingestion)
from ledger.bankAgent.BankAgent import BankAgent
agent = BankAgent(llc)
row = {'desc': 'PURCHASE AUTHORIZED ON 10/07 LOWE\'S #159 SAN MARCOS TX', 'amt': -27.04}
result = agent.classify(row, context={'propNm': 'RV_RV1'})
print(result)   # → ClassifiedRow with acct=Acct.Fixed.Tangible.InConstruction, flag=CIP_VIOLATION

# Cell 3 — run IngestAgent preview
from ledger.bankAgent.IngestAgent import IngestAgent
ingest = IngestAgent(llc)
preview = ingest.preview('books/2025/BankStmts/WBGroupLLC_WF_20251231.csv',
                         propNm_default='H_805HighMesa', year=2025)

# Cell 4 — inspect flags
import pandas as pd
df = pd.DataFrame([r.__dict__ for r in preview.rows])
display(df[df.flag != ''][['dt','amt','desc','acct','flag','propNm']])

# Cell 5 — inspect BankAgent confidence split
display(df.groupby(['confidence','txn_type','acct']).size().reset_index(name='count'))

# Cell 6 — commit (uncomment after reviewing flags above)
# result = ingest.commit(preview)
# print(result)
```

---

## 8. Flask UI Integration

Two routes in `ui/llcBankIngest.py`:

| Route | Method | Body | Response |
|---|---|---|---|
| `/api/bank/ingest/preview` | POST | `{csv_path, propNm, year}` | `PreviewResult` JSON |
| `/api/bank/ingest/commit` | POST | `{preview_token}` | `CommitResult` JSON |
| `/view/bank_ingest` | GET | — | `bank_ingest.html` |

**`bank_ingest.html` operator flow:**
1. Select CSV from `BankStmts/<year>/` dropdown (server enumerates available files)
2. Set default `propNm` (dropdown of active properties from COA/llcAssets)
3. Click Preview → loads classified rows into a table
4. Review table: editable `acct` / `propNm` per row; `CIP_VIOLATION` rows amber; `CROSS_PROP_REFUND` rows red; `DUPLICATE` rows struck-through (will be skipped)
5. Stats banner: `N auto / N review / N flagged / N duplicate`
6. If all rows are `auto` and zero flags → "Auto-Commit" button appears
7. Click Commit → POST to `/commit` → show `CommitResult` stats and LogHistory entry

---

## 9. Out of Scope (v0.1)

- ML/LLM-based classification — v0.1 uses deterministic vendor rules + history; LLM is a future enhancement
- Direct bank API / Plaid integration — CSV only
- Multi-bank reconciliation — single Wells Fargo account
- Browser file upload — v0.1 selects from server-local `BankStmts/` directory

---

*End of design_BUS_01.5_BankIngestionAgent.md — v0.3, 2026-06-19*
