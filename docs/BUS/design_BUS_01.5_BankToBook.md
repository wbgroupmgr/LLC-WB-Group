# BankToBook Pipeline — Design

**Status:** v0.4 — 2026-06-19 (corrected agent semantics, end-user scenario, 3-scope dedup, ClassifiedRow schema)
**Owner:** Francisco Rojas (W&B Group, LLC)
**Stage:** AccountingWorkflow 01.5 — Transactional ingestion (upstream of all statements/forms)
**Related:** `design_BUS_01.5_ExpRevAgent.md`, `design_BUS_04.0_TaxPrep.md`,
`design_BUS_04.6_Form8825Agent.md`, `ui/llcBankView.py` (existing skeleton)
**GitHub:** [Issue #20](https://github.com/wbgroupmgr/llcRentalTracker/issues/20)

---

## 1. Why — Two Goals, Two Agents

The BankToBook pipeline has two distinct failure modes, each owned by a dedicated agent:

**Goal 1 — Prevent Problems Early (BankAgent — the CFO/AcctOps manager).** Nearly every downstream error in BookToIRS traces back to a mis-classification at ingestion. Two real 2025 incidents prove this:

1. **CIP mis-classification.** RV_RV1 construction purchases were ingested as `Acct.Exp.Repair` / `Acct.Exp.Other` when the property was `Acct.Fixed.Tangible.InConstruction`. IRC §263(a) requires capitalization. Error surfaced only at Form 8825 (F8EX-R05), forcing a manual ~$1,075 reclass across ~17 transactions.

2. **Refund mis-tagged to wrong property.** A $14.06 WIMBERLEY ACE purchase + its return on 2025-10-09 were split across two properties — the refund on `H_805HighMesa`, purchases on `RV_RV1`. Caught only by forensic rule F8NI-R05 in the IRS pipeline — far too late.

**Goal 2 — Smart Classification (IngestAgent — the auditor/bookkeeper).** Most bank transactions are routine and repeatable — rent income, utilities, hardware, insurance. But a subset are *special*: a property closing, a member capital investment, a mortgage payoff. The **IngestAgent** is a "smart banker" that learns the LLC's transaction patterns, auto-classifies routine rows, and surfaces special transactions for operator review.

> **Design principle: smart banker classification + prevent problems early — across the whole accounting workflow.**

---

## 2. Two-Agent Architecture

The two agents have distinct responsibilities and clearly separated layers:

```
Home View → "🏧 Bank Reconciliation"
        │
        ▼
  BankAgent  (CFO / AcctOps manager — the OUTER orchestrator)
  ┌──────────────────────────────────────────────────────────┐
  │  Owns: the end-to-end pipeline, two phases, UI surface   │
  │  Phase 1 — preview():                                    │
  │    ① BankCSVParser → raw rows                            │
  │    ② BkDuplicateDetector → flag dups + return pairs      │
  │    ③ IngestAgent.classify() per row → ClassifiedRow      │  ← IngestAgent called here
  │    ④ BkCIPGuard → override if InConstruction             │
  │    ⑤ return PreviewResult (nothing written)              │
  │  Phase 2 — commit():                                     │
  │    ⑥ skip DUPLICATE rows                                 │
  │    ⑦ enrich ClassifiedRow → full llcExpRev record        │
  │    ⑧ write to llcExpRev.records                          │
  │    ⑨ append LogHistory entry                             │
  │    ⑩ BkAuditNotifier → notify BookToIRS section agents   │
  └──────────────────────────────────────────────────────────┘
        │
        ▼
  IngestAgent  (auditor / bookkeeper — the PER-RECORD classifier)
  ┌──────────────────────────────────────────────────────────┐
  │  Owns: vendor KB, txn-type detection, perpetual learning │
  │  classify(raw_row, context) → ClassifiedRow              │
  │  learn(vendor_key, acct, sub, txn_type) → updates KB    │
  └──────────────────────────────────────────────────────────┘
```

**BankAgent** = the CFO/AcctOps manager that orchestrates the full pipeline, owns the two-phase model, and enforces regulatory rules (CIP, dedup, audit trail).
**IngestAgent** = the auditor/bookkeeper that knows how to read and classify a single bank transaction.

The BankAgent calls the IngestAgent; the IngestAgent has no knowledge of phases, pipeline, or writes.

---

## 3. BankToBook End-User Scenario

### 3.1 Entry Point — Home View

The operator starts from the **Home View**, which already shows a **"🏧 Bank Reconciliation"** button that routes to `/view/bank_reconcile`. The BankToBook pipeline extends the current read-only reconciliation view (`ui/llcBankView.py`) with the full two-phase BankAgent pipeline.

### 3.2 Full Operator Journey

```
① Home View
   └─ click "🏧 Bank Reconciliation"
        │
        ▼
② Bank Reconciliation View  (/view/bank_reconcile)
   - Lists available CSVs in BankStmts/<year>/
   - Shows last ingestion date and row count from LogHistory
   - "Select CSV" dropdown + optional "Upload New CSV" (existing /api/llcBank/upload_csv)
   - "Default propNm" dropdown (active properties from COA)
   - Click "Preview →"
        │
        ▼
③ Phase 1 — Preview  (BankAgent.preview() — nothing written)
   - BankAgent parses CSV, calls IngestAgent per row, runs CIP guard + 3-scope dedup
   - Preview table renders:
       · Auto rows (green)         — confident classification, no flags
       · Review rows (amber)       — needs operator confirmation (editable inline)
       · Flagged rows (red)        — CIP_VIOLATION, CROSS_PROP_REFUND, RETURN_PAIR
       · Duplicate rows (grey/——)  — already in GL; will be skipped on commit
       · Amount-collision (orange) — same dt+amt found elsewhere in GL; confirm before commit
   - Stats banner: "N new · N auto · N review · N flagged · N duplicate"
   - Operator edits acct / propNm inline on any row
        │
        ├── "Discard / Start Over" ──→  PreviewResult discarded; zero impact to llcExpRev / GL
        │
        └── "Commit ✓" ─────────────→
                │
                ▼
④ Phase 2 — Commit  (BankAgent.commit())
   - Skips DUPLICATE rows
   - Enriches ClassifiedRows → full llcExpRev records
   - Writes to llcExpRev.records; appends LogHistory entry
   - Notifies BookToIRS section agents (BkAuditNotifier)
        │
        ▼
⑤ Commit Confirmation
   - "N rows written · N duplicates skipped · N amount-collisions (review manually)"
   - "View General Ledger →" link to verify
   - Ingested CSV appears in the "Ingested" list; no longer shown as available
```

### 3.3 Discard Scenario

If the operator clicks "Discard" at any point, the `PreviewResult` is abandoned. Because Phase 1 is fully read-only, there is **zero impact** to `llcExpRev`, the GL, any statement, or any IRS form. The CSV file remains in `BankStmts/<year>/` available for future ingestion.

### 3.4 Existing Skeleton in `llcBankView.py`

The build extends — not replaces — the current `ui/llcBankView.py`:

| Existing | Becomes |
|---|---|
| `_parse_wf_csv()` | `BankCSVParser` (IngestAgent layer) |
| `_KW_MAP` + `_infer_acct()` | `BkVendorKB` (IngestAgent's KB) |
| `_load_er_tids()` + `_diff()` | `BkDuplicateDetector` Scope 2 (ExpRev dedup) |
| `/api/llcBank/upload_csv` | Reused as-is for CSV upload |

---

## 4. IngestAgent — The Per-Record Auditor/Bookkeeper

### 4.1 Core Responsibility

The IngestAgent classifies a **single** bank transaction into a COA account + transaction type. Called once per row by BankAgent during Phase 1. Also independently callable from the notebook, tests, or a REPL — with no knowledge of phases, pipeline, or writes.

```python
IngestAgent.classify(raw_row: RawRow, context: dict) → ClassifiedRow
IngestAgent.learn(vendor_key: str, acct: str, acctSub: str, txn_type: str)
```

### 4.2 Transaction Tiers

**Tier 1 — Routine (auto-classifiable):** recurring transactions whose vendor pattern reliably maps to one COA account.

| Vendor Signal | COA Account | acctSub | Confidence |
|---|---|---|---|
| Pedernales Electric, PEC ELEC_BILL | `Acct.Exp.Util` | Electricity | auto |
| BILL PAY Water-COMWSC | `Acct.Exp.Util` | Water | auto |
| Texas Disposal | `Acct.Exp.Util` | Trash | auto |
| Wimberley ACE, Kings Feed, Harbor Freight | `Acct.Exp.Repair` | Hardware/Supplies | auto |
| ALLSTATE IND CO INS PYMT | `Acct.Exp.Ins` | Property Insurance | auto |
| HAYS CO TX WIMBER | `Acct.Exp.Tax.Prop` | Property Tax | auto |
| TRUIST ACCTVERIFY | `Acct.Cash.Bank` | ACH Verification | auto |
| ZELLE FROM (known tenant) | `Acct.Rev.Rent` | Rental Income | auto (after learn) |

**Tier 2 — Special (always require review):** correct account depends on context the IngestAgent cannot resolve alone. `confidence: "flagged"` rows are **permanently excluded** from auto-commit eligibility.

| Signal | TxnType | COA Candidate | Confidence |
|---|---|---|---|
| `abs(amt) > 50,000` + wire | `SPECIAL_WIRE` | `Acct.Fixed.Tangible` or equity | flagged |
| `WT FED#` / `WITHDRAWAL MADE IN A BRANCH` | `SPECIAL_WIRE` | Property closing candidate | flagged |
| `ZELLE FROM` + sender = member name | `MEMBER_INVEST` | `Acct.Equity.Owner.Capital.Funds` | flagged |
| `PURCHASE RETURN` | `RETURN_PAIR` | Mirror of matched purchase | review |
| Amazon, Walmart, H-E-B, Lowe's | `ROUTINE_EXPENSE` | `Acct.Exp.Repair` or CIP | review |
| No KB match | `UNKNOWN` | `Acct.Exp.Other` | review |

### 4.3 BkVendorKB — Knowledge Base

`ledger/bankAgent/vendor_rules.json` — operator-editable, version-controlled. Seeded with real 2025 transaction patterns (Pedernales, Wimberley ACE, Allstate, COMWSC, Texas Disposal, TRUIST, Zelle, Amazon, Lowe's, WT FED#, Venmo). First-match regex.

`IngestAgent.learn()` — raises an existing rule's confidence to `"auto"` or inserts a new rule. Corrections persist to `vendor_rules.json` immediately. Rule history is tracked via git.

**Auto-commit eligibility:** when a full statement preview has zero `"review"` or `"flagged"` rows and zero BankAgent flags (CIP_VIOLATION, CROSS_PROP_REFUND), BankAgent surfaces a one-click "Auto-Commit" path — still requiring operator confirmation, but skipping the row-by-row review table.

### 4.4 ClassifiedRow — IngestAgent Working Object

`ClassifiedRow` is the IngestAgent's output for one bank row. It is **not** the final `llcExpRev` record — BankAgent enriches it at commit time with `propAddr`, `propID`, `propOwners`, `acctType`, and `tDB`.

```python
@dataclass
class ClassifiedRow:
    # ── from BankCSVParser ─────────────────────────────
    dt:         str    # "YYYY.MM.DD"
    amt:        float  # absolute value
    aType:      str    # "Debit" | "Credit" relative to acct
    desc:       str    # raw bank description
    refDoc:     str    # same as desc (bank statement line as source doc)
    tID:        str    # "{dt}_{D|C}{amt:.2f}" — dedup key

    # ── from IngestAgent (BkVendorKB + BkTxnTypeDetector) ──
    txn_type:   str    # ROUTINE_EXPENSE | RENT_INCOME | SPECIAL_WIRE | MEMBER_INVEST | ...
    acct:       str    # COA account (e.g. "Acct.Exp.Repair")
    acctSub:    str    # sub-category detail
    Ledger:     str    # contra account for double-entry (see §4.5)
    propNm:     str    # property id or "LLC" — operator sets; IngestAgent may suggest
    confidence: str    # "auto" | "review" | "flagged"
    vendor_key: str    # normalized vendor string — for KB lookup and learn()

    # ── from BankAgent (CIP guard, dedup) ──────────────
    flag:       str    # "" | "CIP_VIOLATION" | "CROSS_PROP_REFUND" | "DUPLICATE"
                       #    | "RETURN_PAIR" | "AMOUNT_COLLISION"
    refDB:      str    # "BankStmts/WBGroupLLC_WF_<date>.csv"
```

### 4.5 Ledger (Contra Account) Assignment

The IngestAgent sets `Ledger` as part of `classify()`. This completes the double-entry record:

| acct category | aType | Ledger |
|---|---|---|
| `Acct.Exp.*` (expense) | Debit | `Acct.Cash.Bank` |
| `Acct.Rev.*` (income) | Credit | `Acct.Cash.Bank` |
| `Acct.Equity.Owner.Capital.Funds` (investment) | Credit | `Acct.Cash.Bank` |
| `Acct.Fixed.Tangible.*` (asset purchase) | Debit | `Acct.Cash.Bank` |
| `Acct.Fixed.Tangible.InConstruction` (CIP) | Debit | `Acct.Cash.Bank` |
| Mortgage principal portion | Debit | `Acct.Liab.Morgage` |

Special case — mortgage payment: splits into two `ClassifiedRow`s (interest → `Acct.Exp.Int.Morg` / `Acct.Cash.Bank`; principal → `Acct.Liab.Morgage` / `Acct.Cash.Bank`).

At commit time, BankAgent adds the remaining llcExpRev fields: `propAddr`, `propID` (from `llcAssets` by propNm), `propOwners` (from `llcProfile`), `acctType` (from COA), `tDB = "llcBank"`.

---

## 5. BankAgent — The CFO/AcctOps Manager

### 5.1 Phase 1 — Preview (read-only)

```python
BankAgent.preview(csv_path: str, propNm_default: str, year: int) → PreviewResult
```

Orchestration:
1. `BankCSVParser.parse()` → `list[RawRow]`
2. `BkDuplicateDetector.scan(raw_rows, year, llc)` → mark DUPLICATE, RETURN_PAIR, AMOUNT_COLLISION
3. Per non-DUPLICATE row: `IngestAgent.classify(row, {propNm: propNm_default})` → `ClassifiedRow`
4. `BkCIPGuard.check(row.propNm, row.acct, llc)` → override if InConstruction, set `CIP_VIOLATION`
5. Return `PreviewResult {rows, flags, stats, source, ts}` — nothing written

### 5.2 Phase 2 — Commit (write)

```python
BankAgent.commit(preview: PreviewResult) → CommitResult
```

1. Validate `preview` is a `PreviewResult` — no direct CSV → commit path exists
2. Skip `flag == "DUPLICATE"` rows; surface `AMOUNT_COLLISION` rows as warnings in `CommitResult`
3. Enrich each `ClassifiedRow` → full `llcExpRev` record (propAddr, propID, propOwners, acctType, tDB)
4. Append to `llcExpRev["records"]`; append `LogHistory` entry; write JSON
5. Invalidate `eSession.books` (`BooksContext.invalidate()`)
6. Call `BkAuditNotifier.notify(committed_rows, llc)`

**Invariant:** there is no path from raw CSV to committed records in one step. The operator always sees a preview first.

### 5.3 BkCIPGuard — IRC §263(a) Enforcement

Hard override — not a suggestion. Cannot be bypassed from the UI.

```python
def check(self, propNm: str, proposed_acct: str, llc) -> tuple[str, bool]:
    """If property is InConstruction and proposed_acct is Acct.Exp.*,
    returns Acct.Fixed.Tangible.InConstruction and cip_violated=True."""
```

To clear a CIP flag, the operator must first update `llcAssets` to mark the property InService — which correctly reflects that the property has been placed in service before the cost is treated as an operating expense.

### 5.4 BkDuplicateDetector — Three-Scope Dedup

Uniqueness is checked at three scopes in order:

**Scope 1 — Within the BankStmt CSV (intra-CSV):**
- Each `tID` must be unique within the CSV being ingested
- `PURCHASE RETURN` rows: match to same-vendor / same `abs(amt)` / ±3-day purchase within the CSV
  - Matched pair with mismatched `propNm` → flag return row as `CROSS_PROP_REFUND`
  - No matching purchase found → `RETURN_PAIR` for review

**Scope 2 — Against llcExpRev (primary ledger):**
- Load all `tID`s from `llcExpRev["records"]`
- Any CSV row whose `tID` matches → `DUPLICATE` (already ingested from a prior overlapping export)

**Scope 3 — Against the full GL (cross-ledger):**
- Load `tID`s from `llcAssets`, `llcPayables`, `llcReceivables` in addition to `llcExpRev`
- A large bank withdrawal may already be journaled in `llcAssets` (e.g., the $213,936.95 property purchase was recorded in llcAssets before the CSV was imported)
- Exact `tID` match in any GL source → `DUPLICATE`
- Same `dt` + `abs(amt)` with a **different** `tID` in any GL source → `AMOUNT_COLLISION` (warning — possible data-entry vs. import race; operator must confirm before commit)

`DUPLICATE` blocks the row from commit. `AMOUNT_COLLISION` is a warning surfaced in the commit confirmation screen; the operator decides.

### 5.5 BkAuditNotifier — Post-Commit BookToIRS Notification

Writes to `books/<year>/Forms/.agent_work/IngestAgent_notifications.json`:

| Pattern in committed rows | Notifies |
|---|---|
| Any CIP row (`Acct.Fixed.Tangible.InConstruction`) | Form4562 agent — new depreciable cost basis |
| Any `Acct.Fixed.*` row | Form8825 agent — asset or rental property basis change |
| Any `Acct.Equity.Owner.Capital.*` row | SchK1 agent — capital account change |
| Any `SPECIAL_WIRE` txn_type | All section agents — significant financial event |
| `Acct.Rev.Rent` row with new `propNm` | Form8825 agent — new income property detected |

---

## 6. Data-Model Prerequisites

### 6.1 `llcExpRev_*.json` — Wrap Flat List in a Struct

Current: flat JSON array. Required:

```json
{
  "records": [ ...existing transaction dicts... ],
  "LogHistory": []
}
```

Migration: `ledger/bankAgent/migrate_exprev_schema.py`. All readers update to `d["records"]`.

### 6.2 `refDB` Provenance

- BankAgent-written rows: `"refDB": "BankStmts/WBGroupLLC_WF_<date>.csv"` (relative to `books/<year>/`)
- Manual journal entries (web editor): `"refDB": "llcBank-Manual"`
- Pre-existing records: keep `"refDB": "llcBank"` (pre-BankAgent baseline)

### 6.3 LogHistory Stanza

```json
{
  "ts": "2026-06-19T15:30:00Z",
  "source": "BankStmts/WBGroupLLC_WF_20251231.csv",
  "rows_in_csv": 54,
  "rows_new": 51,
  "rows_duplicate_exprev": 2,
  "rows_duplicate_gl": 1,
  "rows_amount_collision": 0,
  "rows_auto_classified": 46,
  "rows_flagged_review": 3,
  "rows_flagged_cip": 1,
  "rows_flagged_cross_prop": 1,
  "bankagent_version": "0.1",
  "ingestagent_version": "0.1",
  "notes": ""
}
```

---

## 7. Module Structure

```
ledger/
  bankAgent/
    __init__.py
    BankAgent.py              # BankAgent: preview() + commit() + CIP + dedup + audit
    IngestAgent.py            # IngestAgent: classify() + learn() — per-record only
    bkVendorKB.py             # BkVendorKB: pattern → COA lookup, rule persistence
    bkTxnTypeDetector.py      # BkTxnTypeDetector: Tier 2 special txn detection
    bkCSVParser.py            # BankCSVParser: WF CSV → list[RawRow]
    bkCIPGuard.py             # BkCIPGuard: IRC §263(a) InConstruction hard override
    bkDuplicateDetector.py    # BkDuplicateDetector: 3-scope dedup
    bkAuditNotifier.py        # BkAuditNotifier: post-commit BookToIRS notification
    migrate_exprev_schema.py  # one-time: flat list → {records, LogHistory}
    vendor_rules.json         # operator-editable KB

Notebooks/
  bankIngestPreview.ipynb     # diagnostic: load CSV → preview → inspect → optional commit

ui/
  llcBankView.py              # existing skeleton — extend in place
  llcBankIngest.py            # new Flask routes: /view/bank_reconcile, /api/bank/ingest/*
  templates/
    bank_ingest.html          # two-phase UI
```

### 7.1 Class Summary

| Class | Layer | Key Methods |
|---|---|---|
| `BankAgent` | Outer orchestrator | `preview(csv_path, propNm, year)`, `commit(preview)` |
| `IngestAgent` | Per-record bookkeeper | `classify(raw_row, context)`, `learn(vendor_key, ...)` |
| `BkVendorKB` | IngestAgent tool | `lookup(desc)`, `learn(key, acct, sub)`, `save()` |
| `BkTxnTypeDetector` | IngestAgent tool | `detect(desc, amt) → TxnType` |
| `BankCSVParser` | BankAgent tool | `parse(csv_path, year) → list[RawRow]` |
| `BkCIPGuard` | BankAgent tool | `check(propNm, acct, llc) → (acct, violated)` |
| `BkDuplicateDetector` | BankAgent tool | `scan(rows, year, llc) → rows_with_flags` |
| `BkAuditNotifier` | BankAgent tool | `notify(rows, llc)` |

---

## 8. `bankIngestPreview.ipynb` — Diagnostic Notebook

```python
# Cell 1 — setup
from ledger import setup_paths
setup_paths.load_bootstrap('WBGroupLLC')
from ledger.LLC import LLC
llc = LLC('WBGroupLLC', year=2025)

# Cell 2 — test IngestAgent standalone (no pipeline, no writes)
from ledger.bankAgent.IngestAgent import IngestAgent
ia = IngestAgent(llc)
row = {'desc': "PURCHASE AUTHORIZED ON 10/07 LOWE'S #159 SAN MARCOS TX",
       'amt': 27.04, 'aType': 'Debit'}
classified = ia.classify(row, context={'propNm': 'RV_RV1'})
print(classified)  # acct=Acct.Exp.Repair, confidence='review'
# BkCIPGuard (BankAgent level) will override this to CIP_VIOLATION when called in pipeline

# Cell 3 — run BankAgent full preview
from ledger.bankAgent.BankAgent import BankAgent
ba = BankAgent(llc)
preview = ba.preview('books/2025/BankStmts/WBGroupLLC_WF_20251231.csv',
                     propNm_default='H_805HighMesa', year=2025)

# Cell 4 — inspect all flags
import pandas as pd
df = pd.DataFrame([r.__dict__ for r in preview.rows])
display(df[df.flag != ''][['dt','amt','aType','desc','acct','Ledger','flag','propNm']])

# Cell 5 — IngestAgent confidence breakdown
display(df.groupby(['confidence','txn_type','acct']).size().reset_index(name='count'))

# Cell 6 — amount-collision audit (Scope 3 dedup)
display(df[df.flag == 'AMOUNT_COLLISION'][['dt','amt','desc','flag']])

# Cell 7 — commit (uncomment after reviewing)
# result = ba.commit(preview)
# print(f"Written: {result.rows_written}  Skipped: {result.rows_duplicate}")
```

---

## 9. Out of Scope (v0.1)

- ML/LLM-based classification — v0.1 uses deterministic vendor rules + history
- Direct bank API / Plaid integration — CSV only
- Multi-bank reconciliation — single Wells Fargo account
- Browser file upload in two-phase UI — upload endpoint already exists in `llcBankView`; v0.1 selects from server-local `BankStmts/`

---

*End of design_BUS_01.5_BankToBook.md — v0.4, 2026-06-19*
