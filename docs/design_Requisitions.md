# design_Requisitions.md — BankToBook Requisition System

**Namespace:** BankToBook (ledger/bankAgent)
**Stage:** 02.6 — Operator Audit / Commit Workflow
**Version:** v2.3 (2026-06)

---

## 1. What a Requisition Is

A **Requisition** is a short operator-authored record that justifies a bank transaction
that the system cannot classify automatically.

The Vendor KB handles recurring charges (utilities, mortgage, insurance) automatically.
A Requisition handles everything else — any transaction that is:

- A one-time or irregular vendor payment (contractor, hardware, supplies)
- A CIP (Construction-in-Progress) expenditure (the CIPGuard hard-flags these)
- A flagged transaction that needs human explanation before it can be booked

Without a Requisition, the transaction is still written to the books (commit writes
everything), but the Requisitions view shows it as **MISSING** — a visible audit gap.

---

## 2. Why Requisitions Exist

The books must be independently auditable. Every expense needs a paper trail showing
*why* money left the account and *what property or LLC activity it supports*.

- **KB-Rules** cover the recurring case: "Xcel Energy always → Acct.Exp.Utility / H_805HighMesa."
- **Requisitions** cover the ad-hoc case: "Invoice #1042 from contractor for drywall repair."

Together they close the audit loop:

```
Every committed bank transaction
  = covered by a KB Rule (auto)
  OR covered by a Requisition (operator-authored)
```

---

## 3. The Classification Pipeline (How NEED_REQ_DOC is Raised)

When a bank CSV is loaded into Preview, each row passes through a 5-step pipeline:

```
Step 1  bkDuplicateDetector     — flag DUPLICATE rows (already in ledger)
Step 2  bkTxnTypeDetector       — Tier 2 special detection (wires, Zelle from member, ACH verify)
Step 3  bkVendorKB              — match vendor keyword → auto-classify at confidence 'auto' or 'review'
Step 4  IngestAgent.classify()  — fallback classification if KB has no match → confidence 'review'
Step 5  bkCIPGuard              — hard override: if acct = Acct.Fixed.Tangible.InConstruction
                                  → flag = NEED_REQ_DOC, confidence = 'flagged'
```

A row gets `flag = NEED_REQ_DOC` when:
- **Step 5 (CIPGuard):** The transaction touches an InConstruction asset account. These are
  large capital expenditures that must have documentation before they increase the property basis.
- Future: any other `flagged` confidence row not resolved by Steps 1–4.

Rows with `confidence = 'auto'` are **excluded** from the NEED-rows that auto-populate
the Requisitions view (recurring charges don't need a requisition).

---

## 4. Storage

Requisitions are persisted per-year in:

```
books/<year>/BankStmts/req_docs_<year>.json
```

Each record has these fields:

| Field      | Description |
|------------|-------------|
| `tID`      | Transaction ID — same key used in llcExpRev and the GL |
| `dt`       | Transaction date (YYYY-MM-DD) |
| `req_date` | Date the requisition was created by the operator |
| `amt`      | Dollar amount |
| `desc`     | Bank statement description |
| `acct`     | Ledger account (e.g. `Acct.Fixed.Tangible.InConstruction`) |
| `propNm`   | Property name (e.g. `H_805HighMesa` or `LLC`) |
| `purpose`  | Short description of what was purchased / why |
| `notes`    | Optional extended notes (contractor invoice #, etc.) |

---

## 5. Operator Workflow

### 5.1 Normal BankToBook cycle (end-to-end)

```
1. Upload bank CSV → Preview view
   - System classifies all rows
   - Rows with confidence='auto' are green (KB-covered, no action needed)
   - Rows with confidence='review' or 'flagged' need operator attention

2. Review Preview
   - Fix any mis-classified rows inline (edit acct, propNm, acctSub)
   - NEED-rows (CIPGuard flagged) are listed at bottom as "Needs Requisition"

3. Commit ALL
   - All rows written to llcExpRev (no filter — even NEED_REQ_DOC rows are committed)
   - Commit writes a LogHistory audit entry for the CSV file

4. Open Requisitions view  (nav: BankToBook → Requisitions)
   - MISSING table shows all CIP transactions in the ledger without a requisition
   - For each MISSING row: fill in Purpose and Notes, click ➕ to save
   - Once a requisition is saved the row moves from MISSING → the requisition table

5. Done — every committed transaction is now either KB-covered or has a requisition
```

### 5.2 Requisitions view — how to operate it

The Requisitions view has three sections:

**Top: Year selector**
- Defaults to the active fiscal year
- Change with `?year=YYYY` URL param or the in-page selector

**Middle: MISSING Requisitions table**
- Lists all ledger transactions that have `InConstruction` in their account path
  but have no matching requisition record
- Columns: Date · Amount · Description · Property · Account · Purpose (editable)
- Click **➕** on a row to create a requisition from the pre-filled data
- You can edit Purpose inline before saving

**Bottom: Requisition records table**
- All saved requisitions for the selected year
- Columns: tID · Date · Req Date · Amount · Description · Property · Account · Purpose · Notes
- Click **✎** to edit any field inline
- Click **⎘** to duplicate a record (useful for multi-month contractor invoices)
- Click **✕** to delete

### 5.3 Editing a requisition

Every field except `tID` is editable after save. To update:

1. Click **✎** on the row
2. The row goes into inline-edit mode — all cells become input fields
3. Edit Purpose or Notes (most common)
4. Click **✓** to save or **✗** to cancel

Changes are saved immediately to `req_docs_<year>.json`.

### 5.4 Adding a requisition manually

For transactions that were committed without going through Preview (manual entry via
the Assets or ExpRev editor), you can add a requisition directly:

1. Open Requisitions view
2. Scroll to the bottom of the Requisition table
3. Click **➕ New** (empty row)
4. Fill in: tID (from the GL), Date, Amount, Description, propNm, Account, Purpose
5. Save

The tID must match the transaction's tID in the ledger exactly, or it will not link.

---

## 6. CIPGuard — How It Triggers NEED_REQ_DOC

`bkCIPGuard.check(propNm, acct)` runs on every classified row during Preview.

It fires when:
- The classified account is `Acct.Fixed.Tangible.InConstruction` (or any sub-account)
- AND the `propNm` is a real property (not `LLC` overhead)

When it fires:
- `cr.acct` is left unchanged (the InConstruction account is correct)
- `cr.flag = 'NEED_REQ_DOC'`
- `cr.confidence = 'flagged'`

The row is committed normally — CIPGuard does NOT block the commit. It only signals
that a requisition is required afterward.

---

## 7. Requisition vs KB Rule — When to Use Each

| Situation | Use |
|-----------|-----|
| Utility bill, every month, same vendor | KB Rule (auto) |
| Mortgage payment | KB Rule (auto) |
| One-time contractor invoice | Requisition |
| Home Depot purchase for a property | Requisition |
| Capital expenditure (roof, HVAC, flooring) | Requisition (CIPGuard auto-flags) |
| Rent payment from tenant | KB Rule (Zelle from tenant → RENT_INCOME) |
| Zelle from LLC member (capital contribution) | Both: KB Rule classifies, Requisition documents purpose |

If you find yourself adding the same vendor to Requisitions month after month, add a
KB Rule instead so it auto-classifies. Use the **KB-Rules view** → **➕ New Rule**.

---

## 8. Audit Compliance

For a rental real estate LLC, the IRS expects documentation for every capital
expenditure (IRC §263). Requisitions are this app's implementation of that requirement.

At year-end, before filing Form 8825 / Form 4562:
1. Open Requisitions view for the tax year
2. Verify the MISSING table is empty (all CIP transactions have requisitions)
3. Review Purpose/Notes on each InConstruction row — these feed the depreciation schedule
4. If any row is mis-classified (should be expensed, not capitalized), fix the account
   in the ExpRev editor, then delete the requisition

**The Requisitions view is part of the YE Close checklist.**  
Do not close the year until MISSING = 0.

---

## 9. Code Map

| File | Role |
|------|------|
| `ledger/bankAgent/bkReqDocAgent.py` | Storage CRUD — `BkReqDocAgent.add()`, `update()`, `set_all()` |
| `ledger/bankAgent/bkCIPGuard.py` | Detection — flags CIP rows during Preview |
| `ledger/bankAgent/BankAgent.py` | Orchestrator — calls CIPGuard at Step 5, counts `need_req_doc` |
| `ui/llcBankIngest.py` | Routes — `/view/requisitions`, `/api/bank/reqdocs` GET/POST, `_missing_reqs()` |
| `ui/templates/requisitions.html` | View — MISSING table + saved requisitions table |
| `books/<year>/BankStmts/req_docs_<year>.json` | Persisted records |
