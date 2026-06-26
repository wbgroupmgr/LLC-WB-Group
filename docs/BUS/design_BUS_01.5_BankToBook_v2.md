# BankToBook Pipeline — Design

**Status:** v0.6 — 2026-06-23 (Phase 1a Resolve + IngestAgent Aids added)
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

The operator starts from the **Home View**, which shows 3 buttons in the Transactions group:
- a **"🏧 Bank Reconciliation"** button that routes to `/view/bank_reconcile`.
- a **"📓 Bank Knowledge/Rules"** button that routes to `/view/bank_kb_rules`.
- a **"🧾 Requisitions"** button that routes to `/view/requisitions`.

The `Bank Reconcilation` is the primary task for previewing how new bank statements will be ingested into the llcExpRev ledger. 

The BankToBook pipeline extends the current read-only reconciliation view (`ui/llcBankView.py`) with the full two-phase BankAgent pipeline.

### 3.2 Full Operator Journey

- The following shows the fast path when new transaction need no KBRule or Requistion change. 
- The Preview view provides action to navigate to the IngestAgent aids.
- The operator can select the IngestAgent aides (KBRules/Requisition) buttons independently of Preview. 

```
① Home View
   |─ click "🏧 Bank Reconciliation" -> Bank Reconcilation Operator Journey (see below)
   |─ click "Bank Knowledge/Rules" -> Bank Knowledge/Rules Operator Journey (see below)
   └─ click "Requisitions" -> Requisition Operator Journey (see below
        │
        ▼
② Bank Reconciliation View  (/view/bank_reconcile - see 3.2.1)
        ▼
③ Phase 1 — Preview  (BankAgent.preview() — see 3.2.1 nothing written 
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

### 3.2.1 Bank Preview Operator Journey

- The Bank Preview view starts by showing the new records key data   
- The view uses in-line editing actions to edit, dup, delete and add patterns -- PLUS: NewRequisition, NewPattern
     - NewPattern -> navigates to KBRule view (3.2.2) and adds a KBRule patten using the selected records. 
     - NewRequisition -> will navigate to the Requisition View (3.2.3) will add records for any item checked needing requisition
- The action "Commit" writes the previewed (and inline-edited) new records to **llcExpRev** (`BankAgent.commit()`), skipping DUPLICATE rows and appending a LogHistory entry. (KBRule DB updates belong to the Bank Knowledge/Rules view, §3.2.2; Requisition DB updates belong to §3.2.3.)

````
② Bank Reconciliation View  (/view/bank_reconcile)
   - Lists available CSVs in BankStmts/<year>/
   - Shows last ingestion date and row count from LogHistory
   - "Select New BankStmt (CSV)" dropdown
        + optional "Upload New CSV" (existing /api/llcBank/upload_csv)
        + Find (look in ~/Downloads for Bank CSV files, name patterns ≤15 days old)
   - "Default propNm" dropdown (active properties from COA)
   - Click "Preview →"
        │
        ▼
③ Phase 1 — Preview  (BankAgent.preview() — nothing written)
   - BankAgent parses CSV, calls IngestAgent per row, runs CIP guard + 3-scope dedup
   - If Chg checkbox clicked - top bar shows the In Line Editing actions: Edit, Dup, Delete, Add, NewRequesition NewPattern
   - Preview table renders:
       · Auto rows (green)           — confident classification, no flags
       · Review rows (amber)         — needs operator confirmation (editable inline)
       · NEED_REQ_DOC rows (orange)  — InConstruction property; operator must supply ReqDoc [
       · RETURN_PAIR rows (amber)    — purchase return pair
       · Duplicate rows (grey/——)    — already in GL; will be skipped on commit
       · Amount-collision (orange)   — same dt+amt found elsewhere in GL; confirm before commit
   - Stats banner: "N new · N auto · N review · N need-req-doc · N duplicate"
        │
        ├── If any NEED_REQ_DOC or UNKNOWN rows → "Resolve →" opens Phase 1a
        │
        └── If zero unresolved rows → "Commit ✓" goes directly to Phase 2

````

### 3.2.2 Bank Knowledge/Rules Operator Journey

- The KBRule view starts by showing the current state of the KBRule DB.   
- The view uses in-line editing actions to edit, dup, delete and add patterns. 
- The action "Commit" will update the KBRule DB/models.
- Any action that leaves the KBRule view after changes have been made, will prompt "Ok to Leave (lose changes)?  Save?"

````
③a Phase 1b — Update Knowledge/Rules DB view
   
   NewIngestRuleAgent — declare permanent vendor patterns
      - Uses 'In-Line Editing Table View' to show the list of
           - the current patterns and its respective rules
           - propNm, acct, acctSub
           - transaction type
           - confidence levels
      - The top bar has the In Line Editing actions: Edit, Dup, Delete, Add
      - Shows review rows whose vendor pattern could be promoted to a permanent KB rule
      - Operator fills: pattern, acct, acctSub, txn_type, confidence
      - On "Save Rules": IngestAgent.learn() writes to vendor_rules.json
      - Preview re-runs with new rules applied

````

### 3.2.3 Requisition Operator Journey

- The Requisition view starts by showing the current list of the Requisition DB.   
- The view uses in-line editing actions to edit, dup, delete and add requisitions.
- NOTE: each requisition is linked to 1 and only 1 record in the GL. 
- The action "Commit" will update the requisition DB/models.
- The Ingest Agent should check whether there are any transactions (in preview and/or GL) that are missing requisition records. 
- Any action that leaves the Requisition view after changes have been made, will prompt "Ok to Leave (lose changes)?  Save?"

````
③a Phase 1c — Requisition DB view

   ReqDocAgent — document one-time service/merchandise charges
      - The top bar has the In Line Editing actions: Edit, Dup, Delete, Add
      - Shows NEED_REQ_DOC and UNKNOWN rows with no auto-classifiable pattern
      - Operator fills per row: propNm, confirmed acct, description/purpose
      - Produces req_docs_<ts>.json in books/<year>/Forms/.agent_work/
      - Preview re-runs with req_docs overrides applied

````

### 3.2.4 View Enhancements (implemented)

**Classification priority fix:** `IngestAgent.classify()` runs the **vendor KB (P1) before the Tier-2 detector (P2)**, so an operator-curated rule (e.g. `zelle from nicola rojas → RENT_INCOME`) wins over a generic heuristic guess (`ZELLE FROM <member> → MEMBER_INVEST`). Tier-2 only fires when no KB rule matches. Each classified row carries a **`pID`** = matched KB rule position (index+1), or `None`.

**Shared component (`_inline_edit_table.html`)** gained: optional `#` ordinal column (configurable label), per-column text filters, UP/DOWN row reorder (with a dirty flag that enables Save), and `addRows(rows,{check})` for pre-checked draft handoff.

**Bank Preview:**
- Remembers the last disk CSV (sessionStorage) and **auto-refreshes** the preview on return — so KB/Requisition edits are reflected immediately without manual reload.
- Columns: leading `#`, `tID`, **`Conf:pID`** (`<confidence>:p<pID>` or `:na`), **`ReqID`** (linked requisition rID or `na`).
- Title-bar nav actions: **Knowledge/Rules** and **Requisitions** (jump between views); selection-bar **NewPattern / NewRequisition** hand-offs unchanged.

**Bank Knowledge/Rules:**
- **`pID`** ordinal column; **column filters** on pattern/account/sub; **UP/DOWN reorder** (order = first-match precedence, persisted on Save); **Return to Preview** action.

**Requisitions:**
- **`rID`** column. CIP transactions still missing a requisition are **auto-added as `rID="Need"` drafts (auto-checked)** — not written to the DB until Save (replaces the prior "missing" info-list). **Return to Preview** action.

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

### 4.4 IngestAgent Aids — Phase 1a Resolve Tools

The LLC has one bank account covering N properties. The IngestAgent cannot resolve `propNm` for ad-hoc service or merchandise charges without operator input. Phase 1a provides two aids:

#### NewIngestRuleAgent

Promotes repeating vendor patterns to permanent KB rules. When the operator sees the same vendor appear across multiple statements as "review", they declare a rule:

```json
{
  "pattern": "(?i)allstate ins co",
  "acct": "Acct.Exp.Ins",
  "acctSub": "Property Insurance",
  "txn_type": "ROUTINE_EXPENSE",
  "confidence": "auto"
}
```

`IngestAgent.learn()` writes this to `vendor_rules.json` and the preview re-runs. Future statements auto-classify this vendor without operator intervention.

#### ReqDocAgent

Documents one-time charges (checks, hardware runs, contractor payments, Amazon/Lowe's receipts) that cannot be inferred from the bank description alone. Each ReqDoc answers:

1. **propNm** — which property does this cost belong to?
2. **acct** — confirmed COA account (may confirm `NEED_REQ_DOC` → InConstruction, or override to a different acct)
3. **notes** — human description of the service or item purchased

```json
{
  "tID": "2026.01.23_C2730.86",
  "propNm": "H_805HighMesa",
  "acct": "Acct.Fixed.Tangible.InConstruction",
  "acctSub": "Labor",
  "notes": "Check #104: subcontractor — framing and rough carpentry"
}
```

ReqDocs are stored in `books/<year>/Forms/.agent_work/req_docs_<ts>.json`. They feed back into BankAgent.preview() as overrides — rows with a matching `tID` in req_docs use the operator-supplied `propNm` and `acct` instead of the IngestAgent's guess.

**Why not just edit inline?** Inline edits in the preview table are ephemeral (lost if the session is discarded). ReqDocs are persisted — they survive a discard, can be audited, and are re-applied if the same CSV is re-ingested.

#### propNm Resolution Strategy

| Row type | propNm source |
|---|---|
| Recurring utility (electric, water, trash) | `propNm_default` passed to `preview()` |
| Rent income (Zelle from known tenant) | KB lookup → propNm from context |
| MEMBER_INVEST (Zelle from member) | `"LLC"` — equity transaction |
| Ad-hoc service / merchandise | **ReqDoc required** |
| SPECIAL_WIRE | Operator must set in ReqDoc |

### 4.6 ClassifiedRow — IngestAgent Working Object

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
    flag:       str    # "" | "NEED_REQ_DOC" | "CROSS_PROP_REFUND" | "DUPLICATE"
                       #    | "RETURN_PAIR" | "AMOUNT_COLLISION"
    refDB:      str    # "BankStmts/WBGroupLLC_WF_<date>.csv"
```

### 4.7 Ledger (Contra Account) Assignment

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
    bkReqDocAgent.py          # BkReqDocAgent: requisition DB CRUD (1 req ↔ 1 GL tID) [Phase C]
    migrate_exprev_schema.py  # one-time: flat list → {records, LogHistory}
    vendor_rules.json         # operator-editable KB

Notebooks/
  bankIngestPreview.ipynb     # phased regression harness — created P0, extended P1–P4

ui/
  llcBankView.py              # existing read-only skeleton — CSV listing helpers reused
  llcBankIngest.py            # Flask routes binding for the 3 BankToBook views + APIs
  templates/
    _inline_edit_table.html   # SHARED inline-edit component (issue #8 model) — all 3 views
    bank_preview.html         # Bank Reconciliation / Preview  (/view/bank_reconcile)   [Phase A]
    bank_kb_rules.html        # Bank Knowledge/Rules           (/view/bank_kb_rules)    [Phase B]
    requisitions.html         # Requisitions                   (/view/requisitions)     [Phase C]
```

**3-view separation (v2):** the former single `bank_ingest.html` two-phase UI is replaced by three independent views, each with its own Commit. They share ONE inline-edit implementation (`_inline_edit_table.html`) rather than each reinventing editing — the root cause of the v1 P3/P4 regression that was reverted.

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

## 8. `bankIngestPreview.ipynb` — Phased Regression Harness

The notebook is **created in P0** and **extended in each subsequent phase**. It serves as both a development tool and a regression harness — each phase must keep the 2025 baseline cells green before adding new capability.

### 8.1 Structure

```
P0 baseline cells (B1–B5)   — 2025 BankToBook using existing llcBankView (no agents yet)
P1 extension cells (P1a–P1b) — IngestAgent: compat check + 2026 run
P2 extension cells (P2a–P2b) — BankAgent: compat check + 2026 run
P3 extension cells (P3a–P3b) — Full pipeline including optional commit
```

Cells accumulate — earlier cells always run first. The P0 baseline is the ground truth against which all later phases are compared.

### 8.2 P0 Baseline Cells — 2025 BankToBook (existing code, no agents)

```python
# B1 — Setup
from ledger import setup_paths
setup_paths.load_bootstrap('WBGroupLLC')
from ledger.LLC import LLC
import pandas as pd

llc_2025 = LLC('WBGroupLLC', year=2025)
CSV_2025 = 'books/2025/BankStmts/WBGroupLLC_WF_20251231.csv'

# B2 — Import 2025 BankStmt using existing llcBankView (no write)
from ui.llcBankView import llcBankView, _parse_wf_csv
with open(CSV_2025) as f:
    raw_rows_2025 = _parse_wf_csv(f.read())

bk_df_2025 = pd.DataFrame(raw_rows_2025)
print(f"2025 BankStmt: {len(bk_df_2025)} rows")
display(bk_df_2025.head(10))

# B3 — Produce llcExpRev in-memory DataFrame (simulated, no write)
# Only rows that are NEW (not already in llcExpRev) — using existing _diff() logic
from util.utilEditSession import utilEditSession
# Load tIDs from live llcExpRev to find what's already ingested
from ledger.llcExpRev import llcExpRev as LlcExpRev
er_obj = LlcExpRev(llc_2025)
existing_tids = {r.get('tID') for r in er_obj.load()}

simulated_er_2025 = bk_df_2025[~bk_df_2025['tID'].isin(existing_tids)].copy()
print(f"Simulated new ExpRev rows: {len(simulated_er_2025)}")
display(simulated_er_2025[['dt','amt','aType','acct','desc']].head(20))

# B4 — Produce GL in-memory DataFrame from BankStmt rows
# Double-entry expansion: each row → debit leg + credit leg
def to_gl_rows(er_df):
    rows = []
    for _, r in er_df.iterrows():
        acct   = r.get('acct', 'Acct.Exp.Other')
        ledger = 'Acct.Cash.Bank'   # contra for all BankStmt rows
        rows.append({**r, 'entry': 'primary', 'gl_acct': acct})
        rows.append({**r, 'entry': 'contra',  'gl_acct': ledger,
                     'aType': 'Credit' if r['aType']=='Debit' else 'Debit'})
    return pd.DataFrame(rows)

gl_df_2025 = to_gl_rows(simulated_er_2025)
print(f"GL rows (double-entry): {len(gl_df_2025)}")
display(gl_df_2025[['dt','gl_acct','aType','amt','desc']].head(20))

# B5 — Trial balance from GL DataFrame
def trial_balance(gl_df):
    tb = gl_df.copy()
    tb['signed'] = tb.apply(
        lambda r: r['amt'] if r['aType']=='Debit' else -r['amt'], axis=1)
    return (tb.groupby('gl_acct')['signed']
              .sum()
              .reset_index(name='net_balance')
              .sort_values('net_balance'))

tb_2025 = trial_balance(gl_df_2025)
print(f"Trial balance total (should be 0 if balanced): {tb_2025['net_balance'].sum():.2f}")
display(tb_2025)
```

### 8.3 P1 Extension Cells — IngestAgent Backward Compat + 2026

```python
# P1a — [COMPAT] Re-classify 2025 BankStmt via IngestAgent; compare to P0 baseline
from ledger.bankAgent.IngestAgent import IngestAgent
ia = IngestAgent(llc_2025)

classified_2025 = [ia.classify(r.to_dict(), context={'propNm': 'H_805HighMesa'})
                   for _, r in bk_df_2025.iterrows()]
ia_df_2025 = pd.DataFrame([c.__dict__ for c in classified_2025])

# Compare acct assignments vs B3 baseline — flag any differences
diff = ia_df_2025.merge(simulated_er_2025[['tID','acct']], on='tID', suffixes=('_ia','_baseline'))
changes = diff[diff['acct_ia'] != diff['acct_baseline']]
print(f"P1 compat: {len(changes)} acct changes vs P0 baseline (expected: 0 for Tier 1 rows)")
display(changes[['tID','desc','acct_baseline','acct_ia','confidence']])

# P1b — [2026] Classify 2026 BankStmt via IngestAgent
llc_2026 = LLC('WBGroupLLC', year=2026)
CSV_2026 = 'books/2026/BankStmts/WBGroupLLC_WF_20260313.csv'
with open(CSV_2026) as f:
    raw_rows_2026 = _parse_wf_csv(f.read())

ia_2026 = IngestAgent(llc_2026)
classified_2026 = [ia_2026.classify(r, context={'propNm': 'H_805HighMesa'})
                   for r in raw_rows_2026]
ia_df_2026 = pd.DataFrame([c.__dict__ for c in classified_2026])
display(ia_df_2026.groupby(['confidence','txn_type','acct']).size().reset_index(name='count'))
```

### 8.4 P2 Extension Cells — BankAgent Backward Compat + 2026

```python
# P2a — [COMPAT] BankAgent.preview() on 2025 → verify rows match P1 IngestAgent output
from ledger.bankAgent.BankAgent import BankAgent
ba_2025 = BankAgent(llc_2025)
preview_2025 = ba_2025.preview(CSV_2025, propNm_default='H_805HighMesa', year=2025)

ba_df_2025 = pd.DataFrame([r.__dict__ for r in preview_2025.rows])
compat_check = ba_df_2025.merge(ia_df_2025[['tID','acct']], on='tID', suffixes=('_ba','_ia'))
changes = compat_check[compat_check['acct_ba'] != compat_check['acct_ia']]
print(f"P2 compat: {len(changes)} acct changes vs P1 baseline (expected: only CIP overrides)")
display(changes[['tID','desc','acct_ia','acct_ba','flag']])

# P2b — [2026] Full BankAgent preview on 2026 CSV + inspect flags
ba_2026 = BankAgent(llc_2026)
preview_2026 = ba_2026.preview(CSV_2026, propNm_default='H_805HighMesa', year=2026)

ba_df_2026 = pd.DataFrame([r.__dict__ for r in preview_2026.rows])
print(preview_2026.stats)
display(ba_df_2026[ba_df_2026['flag'] != ''][['dt','amt','aType','desc','acct','Ledger','flag','propNm']])
display(ba_df_2026[ba_df_2026['flag'] == 'AMOUNT_COLLISION'][['dt','amt','desc','flag']])

# P3a — [COMPAT] Verify 2025 trial balance unchanged after IngestAgent + BankAgent
gl_df_2025_p2 = to_gl_rows(ba_df_2025[ba_df_2025['flag'] != 'DUPLICATE'])
tb_2025_p2 = trial_balance(gl_df_2025_p2)
print(f"P2 2025 trial balance total: {tb_2025_p2['net_balance'].sum():.2f}")
delta = tb_2025_p2.merge(tb_2025, on='gl_acct', suffixes=('_p2','_p0'))
display(delta[abs(delta['net_balance_p2'] - delta['net_balance_p0']) > 0.01])

# P3b — [2026] Full GL + trial balance for 2026 preview
gl_df_2026 = to_gl_rows(ba_df_2026[ba_df_2026['flag'] != 'DUPLICATE'])
tb_2026 = trial_balance(gl_df_2026)
print(f"2026 trial balance total: {tb_2026['net_balance'].sum():.2f}")
display(tb_2026)

# Commit cell — uncomment after reviewing P2b flags above
# result = ba_2026.commit(preview_2026)
# print(f"Written: {result.rows_written}  Skipped: {result.rows_duplicate}")
```

---

## 9. Out of Scope (v0.1)

- ML/LLM-based classification — v0.1 uses deterministic vendor rules + history
- Direct bank API / Plaid integration — CSV only
- Multi-bank reconciliation — single Wells Fargo account
- Browser file upload in two-phase UI — upload endpoint already exists in `llcBankView`; v0.1 selects from server-local `BankStmts/`

---

*End of design_BUS_01.5_BankToBook.md — v0.5, 2026-06-19*
