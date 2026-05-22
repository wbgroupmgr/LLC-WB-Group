# NewPropertyAgent — Implementation Design

Module Owner: App Developer  
Status: Production (v0.3)  
System: llcRentalTracker  
Business Design: `docs/design_BUS_01.5_NewPropertyAgent.md`  
Related Issue: [#6 LLC Property List Mgmt](https://github.com/wbgroupmgr/llcRentalTracker/issues/6)  
AccountingStage: Booking (02.5)

---

## Table of Contents

1. [Module Layout](#1-module-layout)
2. [Architecture](#2-architecture)
3. [Core Class — `ledger/propAgent.py`](#3-core-class--ledgerpropagentpy)
   - 3.1 Constants
   - 3.2 Rule Engine — `_RULES`
   - 3.3 Methods
4. [API Routes — `ui/llcPropAgent.py`](#4-api-routes--uillcpropagentpy)
   - 4.1 Route Table
   - 4.2 GL Sources
   - 4.3 assetList Constraint
5. [Dialog — `ui/templates/_propAgent_dialog.html`](#5-dialog--uitemplatespropagent_dialoghtml)
   - 5.1 Step Map
   - 5.2 Commit Flow
   - 5.3 Key JavaScript Functions
6. [Data Flow (End-to-End)](#6-data-flow-end-to-end)
7. [GL Integration — Single-Sided Entry](#7-gl-integration--single-sided-entry)
8. [Preface Fields Reference](#8-preface-fields-reference)
9. [Test Coverage — `tests/test_propAgent.py`](#9-test-coverage--teststest_propagentpy)
10. [Known Limitations & Future Work (Issue #6)](#10-known-limitations--future-work-issue-6)

---

## 1. Module Layout

```
ledger/propAgent.py                     Core business logic — classification, basis, journal records
ui/llcPropAgent.py                      Flask route bindings (/api/propAgent/...)
ui/templates/_propAgent_dialog.html     Multi-step modal dialog (Steps 0–4)
ui/templates/table_view.html            Button trigger: "🏠 PurchaseAid — propAgent" in llcAssets Actions menu
tests/test_propAgent.py                 40 unit tests covering all core methods
docs/design_BUS_01.5_NewPropertyAgent.md  Business / accounting spec
```

---

## 2. Architecture

```
User: "🏠 PurchaseAid — propAgent" button (llcAssets Actions menu)
        ↓
_propAgent_dialog.html   multi-step modal (Steps 0–4)
        ↓ fetch POST
ui/llcPropAgent.py       route bindings (bind_propAgent_routes)
        ↓
ledger/propAgent.py      PropAgent class — pure logic, no Flask dependency
        ↓ save()
llcAssets manager        writes to LLC-WBGroup/books/2025/Accts/llcAssets_WBGroupLLC.json
```

The `PropAgent` class (`ledger/propAgent.py`) is stateless and Flask-free — all state lives in the dialog's JavaScript IIFE.

---

## 3. Core Class — `ledger/propAgent.py`

### 3.1 Constants

```python
CAPITALIZE = 'Capitalize'
AMORTIZE   = 'Amortize'
EXPENSE    = 'Expense'

_UNIQUE_CLOSING_ACCTS = frozenset({
    'Acct.Fixed.Tangible.InService',
    'Acct.Fixed.Land',
    'Acct.Liab.Morgage',
})
```

`_UNIQUE_CLOSING_ACCTS` — for duplicate detection: same-acct+aType in same year is flagged regardless of amount.

### 3.2 Rule Engine — `_RULES`

40 `(keyword_lower, tax_bucket, acct)` tuples. First match wins. More-specific keywords precede broader ones (e.g. `'settlement or closing fee'` before `'title'`). Validated against the 805 High Mesa ALTA statement (`ccDict` in `20250820-ClosingToLedger.ipynb`). Bill of Sale rules appended for personal property (RV, vehicle, equipment).

Session-level rules passed at classify time prepend the built-in list (highest priority).

```python
all_rules = list(extra_rules or []) + _RULES
for keyword, tax_bucket, acct in all_rules:
    if keyword in desc_lower:
        ...
```

Fallback (no match): Debit rows → `Acct.Fixed.Tangible.InService` / Capitalize; Credit rows → `Acct.Cash.Bank`. Row flagged with `_matched=False` for user review (orange highlight in Step 2).

### 3.3 Methods

#### `classify(rows, session_rules=None) → List[Dict]`
- Drops rows where both Debit and Credit are null/zero
- Drops rows where `Description.lower() in ('totals', 'total')`
- Auto-detects ALTA Buyer/Seller vs. standard Debit/Credit column layout
- Sets `acct`, `aType`, `amt`, `tax_bucket`, `Ledger=None`, `_matched`, `_row_idx`

#### `toBalanceSheet(classified) → Dict`
```python
{'total_debits': float, 'total_credits': float, 'balanced': bool, 'delta': float}
```
`balanced = abs(debits - credits) < 0.02`

#### `propertyBasis(classified) → Dict`
Sums all `Capitalize + Debit` rows.
```python
{'gross_basis': float, 'basis_rows': [...]}
```
Optional land split preview computed in the API route (not in this method).

#### `_apply_land_split(classified, land_pct) → List[Dict]`
Collects all `Capitalize + Debit + Acct.Fixed.Tangible.InService` rows, sums their amounts, replaces them with two records:
- `Acct.Fixed.Land` → `total × land_pct / 100`
- `Acct.Fixed.Tangible.InService` → `total × (1 − land_pct / 100)`

All other rows pass through unchanged. Skipped entirely when `land_pct == 0` (Bill of Sale / personal property path).

#### `toAssetRecords(classified, preface) → List[Dict]`
Raises `PropAgentBalanceError` if not balanced. Calls `_apply_land_split` when `landPct > 0`. Produces one record per row in the llcAssets schema:

| Field | Source | Notes |
|---|---|---|
| `tID` | `f"{tID_Prefix}_{seq+1:02d}"` | Unique per row |
| `propID` | `tID` | Same value; property-level identifier |
| `dt` | `preface.closingDate` normalized | `YYYY-MM-DD` → `YYYY.MM.DD` |
| `acct` | From classifier | COA account path |
| `Ledger` | `'nan'` | Single-sided entry; no dual GL side |
| `aType` | `'Debit'` or `'Credit'` | |
| `amt` | From classifier | Parsed float |
| `desc` | `f"Purchase Property: {Description}"` | |
| `refDoc` | `f"{propNm}, Closing Docs, {tax_bucket}, {closingDoc}"` | Tax bucket embedded per row |
| `refDB` | `'propAgent'` | Origin marker |
| `tDB` | `'llcAssets'` | Target DB |
| `propNm` | `preface.propNm` | |
| `propAddr` | `preface.propAddr` | |
| `acctSub` | `preface.acctSub` | BS grouping key (e.g. `'Closing'`) |
| `assetState` | `preface.assetState` | Lifecycle: `InService` / `InConstruction` / etc. |
| `assetType` | `preface.assetType` | `'H'` (house), `'R'` (RV), etc. |
| `propOwners` | `preface.propOwners` | String currently; dict in Issue #6 Phase 1 |
| `tax_bucket` | From classifier | `Capitalize` / `Amortize` / `Expense` |

#### `balance_assist(classified, closing_date, gl_rows) → Dict`
Searches all 4 GL sources for capital-contribution context (rows where `acct` or `Ledger` contains `'Capital'`) prior to the closing date. Returns:
- `gl_context`: up to 15 most-recent funding rows (displayed in Step 3)
- `total_funded`: sum of context amounts
- `suggestion`: auto-suggested balancing entry (Credit `Acct.Cash.Bank` or Debit `Acct.Fixed.Tangible.InService`) when unbalanced
- `covers_delta`: True when total_funded ≥ |delta|

#### `check_existing(classified, closing_date, gl_rows) → List[Dict]`
Two duplicate-detection strategies (within the same calendar year):
1. **Exact**: `(aType, rounded_amt)` match — catches re-entries at any account
2. **Unique-account**: for accounts in `_UNIQUE_CLOSING_ACCTS`, same `(aType, acct)` regardless of amount — catches $220k mortgage re-entered as $213k

Returns `[{_row_idx, candidates: [{tID, dt, desc, acct}]}]`. Displayed in Step 2 as yellow warning rows.

---

## 4. API Routes — `ui/llcPropAgent.py`

### 4.1 Route Table

All routes registered via `bind_propAgent_routes(app, objects, sanitize)` called from `ui/llcMgmt._bind_routes()`.

| Route | Method | Request Body | Response |
|---|---|---|---|
| `/api/propAgent/classify` | POST | `{rows, session_rules?}` | `{ok, classified}` |
| `/api/propAgent/balance_sheet` | POST | `{classified}` | `{ok, total_debits, total_credits, balanced, delta}` |
| `/api/propAgent/property_basis` | POST | `{classified, landPct?}` | `{ok, gross_basis, basis_rows, land_amt?, bldg_amt?, land_pct?, bldg_pct?}` |
| `/api/propAgent/balance_assist` | POST | `{classified, closingDate}` | `{ok, balanced, delta, gl_context, total_funded, covers_delta, suggestion?}` |
| `/api/propAgent/check_existing` | POST | `{classified, closingDate}` | `{ok, matches}` |
| `/api/propAgent/commit` | POST | `{classified, preface}` | `{ok, committed, total_records}` — 422 on imbalanced |

`_safe_json()` strips float NaN/Inf before serialisation (JSON does not support these values).

### 4.2 GL Sources

All GL sources loaded for `balance_assist` and `check_existing`:
```python
for key in ('llcExpRev', 'llcAssets', 'llcPayables', 'llcReceivables'):
    gl_rows.extend(objects[key].load() or [])
```

### 4.3 assetList Constraint

Every GL row in `llcAssets` that carries a `propNm` must resolve to a registered property in `assetList`. The `commit` route will enforce this constraint in Issue #6 Phase 3: if `preface.propNm` is not present in `assetList`, the commit is rejected with a 422 and a user-visible error. Until Phase 3, propAgent registers the property at commit time via `save_asset_list()` (Issue #6 Phase 3). See [Issue #6](https://github.com/wbgroupmgr/llcRentalTracker/issues/6).

---

## 5. Dialog — `ui/templates/_propAgent_dialog.html`

Included from `table_view.html` only when `OBJ_TYPE == 'llcAssets'`. All state lives in a JavaScript IIFE.

### 5.1 Step Map

| Step | Label | Key Actions |
|---|---|---|
| **0 — Preface** | Common Fields | `closingDate`, `closingDoc`, `landPct`, `assetType`, `assetState`, `tID_Prefix`, `propNm`, `propAddr`, `propOwners`; required-field gate before Next |
| **1 — Input** | Paste Statement | Textarea (JSON array or CSV); POST `/api/propAgent/classify`; parse errors shown inline |
| **2 — Review Ledger** | Classified Rows | Editable table: Description, Debit/Credit, Tax Bucket badge (color-coded), `acct` dropdown; unmatched rows orange; duplicate-candidate warnings yellow |
| **3 — Balance Check** | Balance Assist | POST `/api/propAgent/balance_assist`; shows GL funding context + ΣDebits vs ΣCredits; `+Add` suggestion button; BALANCED gate before Commit |
| **4 — Basis & Commit** | Property Basis | POST `/api/propAgent/property_basis`; read-only basis table; land/building split preview; Commit button → POST `/api/propAgent/commit` |

### 5.2 Commit Flow

On successful commit:
1. Flash "✅ Committed N entries to the ledger. Click Done to close."
2. `_committed = true`; commit button repurposed as "✓ Done"; Back/Next hidden
3. On dialog close (`paClose()`): if `_committed` → `window.location.reload()` to show new records in the asset table

### 5.3 Key JavaScript Functions

| Function | Purpose |
|---|---|
| `propAgentOpen()` | Reset state, show backdrop |
| `paClose()` | Hide backdrop; reload page if committed |
| `paGoTo(step)` | Advance/retreat to step; trigger API calls |
| `paClassify()` | Step 1 → POST classify; populate review table |
| `paFlash(msg)` | Show/clear status message |
| `paPost(url, body)` | Thin `fetch` wrapper using `_scriptRoot` prefix |
| `paGoToInput(target)` | Used by unmatched rule-panel Back button |

---

## 6. Data Flow (End-to-End)

```
Step 0 — Preface
  preface = {closingDate, closingDoc, landPct, assetType, assetState,
              tID_Prefix, propNm, propAddr, propOwners}
        ↓
Step 1 — Paste raw rows (JSON array)
  POST /api/propAgent/classify {rows, session_rules?}
  → classified rows: acct, aType, amt, tax_bucket, Ledger=None, _matched, _row_idx
        ↓
Step 2 — User reviews/edits acct per row
  POST /api/propAgent/check_existing → highlight duplicate candidates
        ↓
Step 3 — Balance check
  POST /api/propAgent/balance_assist {classified, closingDate}
  → gl_context (funding chain), balanced flag, delta, suggestion
  If unbalanced: user adds/removes rows until balanced
        ↓
Step 4 — Basis review
  POST /api/propAgent/property_basis {classified, landPct}
  → gross_basis, land_amt, bldg_amt (if landPct > 0)
  User clicks Commit:
  POST /api/propAgent/commit {classified, preface}
    → PropAgent.toAssetRecords(classified, preface)
       • _apply_land_split() if landPct > 0
       • produce N records in llcAssets schema
    → mgr.load() + records → mgr.save()
    → llcAssets_WBGroupLLC.json updated
  → dialog shows ✅; page reloads to show new records
```

---

## 7. GL Integration — Single-Sided Entry

`Ledger = 'nan'` on every propAgent record. Two code paths handle this:

| File | Function | Guard |
|---|---|---|
| `ledger/ledgerDB.py` | `toGL()` | Filters `dfL` to exclude rows where source `Ledger` is NaN / null / string-`'nan'` before concat |
| `ledger/stmtGL.py` | `toDoubleEntry()` | Explicit nan check: skips `e2` when Ledger is `None`, `float('nan')`, or string `'nan'` |

Result: a propAgent record produces exactly 1 GL row (the `acct` side). A regular dual-entry record produces 2 GL rows. Existing behavior unchanged.

`savePayload()` in `ui/llcRecordsView.py` normalizes any null/empty/float-nan Ledger values to string `'nan'` before writing, ensuring consistency regardless of entry point.

---

## 8. Preface Fields Reference

| Field | Type | Auto-generated? | Notes |
|---|---|---|---|
| `closingDate` | date string | No | Normalized: `YYYY-MM-DD` → `YYYY.MM.DD` |
| `closingDoc` | string | No | Source document filename / reference |
| `landPct` | float 0–100 | No | Tax assessor land % — set to `0` for Bill of Sale / personal property |
| `assetType` | string | No | `'H'` house, `'R'` RV, etc. |
| `assetState` | string | No | `InService`, `InConstruction`, `Inactive`, `Other` |
| `tID_Prefix` | string | No | e.g. `p20250826-Mesa`; becomes tID prefix |
| `propNm` | string | No | Short name: `<assetType>_<ShortName>`, e.g. `H_805HighMesa` |
| `propAddr` | string | No | Full street address |
| `propOwners` | string / dict | No | `{"oID": pct}` dict (Issue #6); currently free-text |
| `acctSub` | string | Auto | Balance sheet grouping key, default `'Closing'` |
| `propID` | string | Auto | = `tID_Prefix` (property-level; same across all rows) |
| `tDB` | string | Auto | Always `'llcAssets'` |
| `refDB` | string | Auto | Always `'propAgent'` |
| `refDoc` | string | Auto | `f"{propNm}, Closing Docs, {tax_bucket}, {closingDoc}"` |

---

## 9. Test Coverage — `tests/test_propAgent.py`

40 tests, all passing. Key coverage areas:

| Area | Tests |
|---|---|
| Classification | ALTA Buyer/Seller format, standard Debit/Credit, null-row skipping, Totals row skipping, all 40 rules, fallback `_matched=False` |
| Balance sheet | Balanced, unbalanced, delta calculation |
| Property basis | Gross basis sum, land/building split (land_amt + bldg_amt = gross_basis) |
| `toAssetRecords` | Schema fields present, `tID` prefix, `refDoc` contains tax_bucket, `Ledger='nan'`, `propID=tID`, `propAddr` set, `tDB`/`refDB` set |
| Balance assist | Balanced path, unbalanced path, suggestion content |
| Duplicate detection | Exact amount match, unique-account match, cross-year exclusion |
| `check_existing` | Candidates returned, empty when no match |

---

## 10. Known Limitations & Future Work (Issue #6)

| Limitation | Issue #6 Phase |
|---|---|
| `propOwners` stored as free-text string; breaks K-1 allocation | Phase 1 / Case 1 — structured picker |
| Historical records have unparseable `propOwners` | Phase 2 / Case 2 — migration script |
| No single authoritative property registry (`assetList`) | Phase 1 — `llcAssets.py` schema v2 |
| `toAssetRecords()` does not write to `assetList` on commit | Phase 3 — `save_asset_list()` call |
| `commit` route does not validate `propNm` against `assetList` | Phase 3 — 422 guard in `bind_propAgent_routes` |
| RV property not in `llcAssets` at all | Phase 6 — manual `assetList` entry |
| Bill of Sale `landPct` not auto-set to 0 for non-real assetType | Future — Step 0 UI auto-default |

See [GitHub Issue #6](https://github.com/wbgroupmgr/llcRentalTracker/issues/6) for the full plan.
