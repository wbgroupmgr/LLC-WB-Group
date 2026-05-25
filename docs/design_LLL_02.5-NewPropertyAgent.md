# NewPropertyAgent — Implementation Design

Module Owner: App Developer  
Status: Production (v0.3)  
System: llcRentalTracker  
Business Design: `docs/design_BUS_01.5_NewPropertyAgent.md`  
Related Issue: [#6 LLC Property List Mgmt](https://github.com/wbgroupmgr/llcRentalTracker/issues/6)  
AccountingStage: Booking (02.5)  
Last Updated: 2026-05-25

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
5. [Dialog — `ui/templates/_propAgent_dialog.html`](#5-dialog--uitemplatespropagent_dialoghtml)
   - 5.1 Step Map
   - 5.2 Key State Variables
   - 5.3 Commit Flow
   - 5.4 Key JavaScript Functions
6. [Data Flow (End-to-End)](#6-data-flow-end-to-end)
7. [GL Integration — Escrow Clearing Entry](#7-gl-integration--escrow-clearing-entry)
8. [Preface Fields Reference](#8-preface-fields-reference)
9. [PDF Report — `ui/llcPdfReport.py`](#9-pdf-report--uillcpdfreportpy)
10. [Test Coverage — `tests/test_propAgent.py`](#10-test-coverage--teststest_propagentpy)
11. [Known Limitations & Future Work (Issue #6)](#11-known-limitations--future-work-issue-6)

---

## 1. Module Layout

```
ledger/propAgent.py                       Core logic — classify, basis, journal records, depreciation
ui/llcPropAgent.py                        Flask route bindings (/api/propAgent/...)
ui/llcPdfReport.py                        PDF report generator (reportlab, landscape letter)
ui/templates/_propAgent_dialog.html       Multi-step modal dialog (Steps 0–4)
ui/templates/table_view.html              Button trigger: "🏠 PurchaseAid — propAgent" in llcAssets Actions
tests/test_propAgent.py                   40 unit tests covering all core methods
docs/design_BUS_01.5_NewPropertyAgent.md  Business / accounting spec
docs/design_LLL_02.5-NewPropertyAgent.md  This file — implementation spec
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
        ↓ auto on commit
ui/llcPdfReport.py       PDF report → Assets/{propNm}/Docs/ (path from refDoc)
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

`_UNIQUE_CLOSING_ACCTS` — for duplicate detection: same-acct+aType in same year flagged regardless of amount. `Acct.Cash.Escrow` is intentionally excluded — the escrow account appears on many normal non-closing entries.

### 3.2 Rule Engine — `_RULES`

`(keyword_lower, tax_bucket, acct)` tuples. First match wins. More-specific keywords precede broader ones (e.g. `'settlement or closing fee'` before `'title'`). Validated against the 805 High Mesa ALTA statement. Bill of Sale rules appended for personal property (RV, vehicle, equipment).

Session-level rules passed at classify time prepend the built-in list (highest priority):

```python
all_rules = list(extra_rules or []) + _RULES
for keyword, tax_bucket, acct in all_rules:
    if keyword in desc_lower:
        ...
```

**Key rule decisions:**
- `county tax` / `property tax` proration → `Acct.Fixed.Tangible.InService` / Capitalize (basis per IRS Pub 551)
- `deposit` / `earnest` / `option money` → `Acct.Equity.Owner.Capital.Funds` / Capitalize (member equity contribution)
- `hoa` / `homeowners association` → `Acct.Exp.Operating` / Expense

Fallback (no match): Debit rows → `Acct.Fixed.Tangible.InService` / Capitalize; Credit rows → `Acct.Cash.Bank`. Rows flagged `_matched=False` (orange highlight in Step 2).

### 3.3 Methods

#### `classify(rows, session_rules=None) → List[Dict]`
- Drops rows where both Debit and Credit are null/zero
- Drops rows where `Description.lower() in ('totals', 'total')`
- Auto-detects ALTA Buyer/Seller vs. standard Debit/Credit column layout
- Sets `acct`, `aType`, `amt`, `tax_bucket`, `Ledger=None`, `_matched`, `_row_idx`
- `Ledger=None` at classify time — `Acct.Cash.Escrow` assigned only in `toAssetRecords()`

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
Land split preview computed in the API route (not in this method).

#### `_apply_land_split(classified, land_pct) → List[Dict]`
Collects all `Capitalize + Debit + Acct.Fixed.Tangible.InService` rows, sums their amounts, replaces them with two records:
- `Acct.Fixed.Land` → `total × land_pct / 100`
- `Acct.Fixed.Tangible.InService` → `total × (1 − land_pct / 100)`

All other rows pass through unchanged. Skipped entirely when `land_pct == 0`.

#### `depreciationEstimate(bldg_amt, closing_date_str, useful_life=27.5) → Dict`

Delegates to `_compute_depreciation()`. Returns:
```python
{
    'depr_full_year':    float,   # bldg_amt / 27.5
    'depr_ytd':          float,   # full_year × months_in_service / 12
    'months_in_service': float,   # 12 − month + 0.5  (MACRS mid-month)
    'closing_month':     int,
    'useful_life':       float,
    'depr_method':       str,     # 'MACRS SL Mid-Month (27.5yr Residential)'
}
```
Returns `{}` if `closing_date_str` cannot be parsed.

#### `toAssetRecords(classified, preface) → List[Dict]`

Raises `PropAgentBalanceError` if not balanced. Calls `_apply_land_split` when `landPct > 0`. Produces one record per row in the llcAssets schema:

| Field | Source | Notes |
|---|---|---|
| `tID` | `f"{tID_Prefix}_{seq+1:02d}"` | Unique per row |
| `propID` | `tID` | Same value; property-level identifier |
| `_row_idx` | `seq + 1` | 1-based; used by `check_existing` dup detection |
| `dt` | `preface.closingDate` normalized | `YYYY-MM-DD` → `YYYY.MM.DD` |
| `acct` | From classifier | COA account path |
| `Ledger` | **`'Acct.Cash.Escrow'`** | Clearing account — nets to $0 when balanced |
| `aType` | `'Debit'` or `'Credit'` | |
| `amt` | From classifier | Parsed float |
| `desc` | `f"Purchase Property: {Description}"` | |
| `refDoc` | `f"{propNm}, Closing Docs, {tax_bucket}, {closingDoc}"` | Tax bucket embedded per row |
| `refDB` | `preface.refDB` or `'propAgent'` | User-supplied source DB / folder reference |
| `tDB` | `'llcAssets'` | Target DB |
| `propNm` | `preface.propNm` | |
| `propAddr` | `preface.propAddr` | |
| `acctSub` | `preface.acctSub` | BS grouping key (e.g. `'Closing'`) |
| `assetState` | `preface.assetState` | Lifecycle: `InService` / `InConstruction` / etc. |
| `assetType` | `preface.assetType` | `'H'` (house), `'R'` (RV), etc. |
| `propOwners` | `preface.propOwners` | String currently; dict in Issue #6 Phase 1 |
| `tax_bucket` | From classifier | `Capitalize` / `Amortize` / `Expense` |

#### `balance_assist(classified, closing_date, gl_rows) → Dict`
Searches all 4 GL sources for capital-contribution context prior to the closing date. Returns:
- `gl_context`: up to 15 most-recent funding rows (displayed in Step 3)
- `total_funded`: sum of context amounts
- `suggestion`: auto-suggested balancing entry when unbalanced
- `covers_delta`: True when `total_funded ≥ |delta|`

#### `check_existing(classified, closing_date, gl_rows) → List[Dict]`
Two duplicate-detection strategies (within the same calendar year):
1. **Exact**: `(aType, rounded_amt)` match — catches re-entries at any account
2. **Unique-account**: for accounts in `_UNIQUE_CLOSING_ACCTS`, same `(aType, acct)` regardless of amount

Returns `[{_row_idx, candidates: [{tID, dt, desc, acct}]}]`. Displayed in Step 4 journal as Override/Dup buttons.

---

## 4. API Routes — `ui/llcPropAgent.py`

### 4.1 Route Table

All routes registered via `bind_propAgent_routes(app, objects, sanitize)`.

| Route | Method | Key Request Fields | Key Response Fields |
|---|---|---|---|
| `/api/propAgent/classify` | POST | `rows`, `session_rules?` | `classified` |
| `/api/propAgent/balance_sheet` | POST | `classified` | `total_debits`, `total_credits`, `balanced`, `delta` |
| `/api/propAgent/property_basis` | POST | `classified`, `landPct?`, `preface`, `closingDate?` | `gross_basis`, `land_amt?`, `bldg_amt?`, `depr_full_year?`, `depr_ytd?`, `months_in_service?`, `records` |
| `/api/propAgent/balance_assist` | POST | `classified`, `closingDate` | `balanced`, `delta`, `gl_context`, `total_funded`, `covers_delta`, `suggestion?` |
| `/api/propAgent/check_existing` | POST | `classified`, `closingDate` | `matches` |
| `/api/propAgent/commit` | POST | `classified`, `preface`, `override_tids?`, `depr_record?`, `basis_data?` | `committed`, `replaced`, `total_records`, `pdf_path?`, `pdf_error?` |
| `/api/propAgent/pdf_report` | POST | `records`, `classified?`, `preface`, `basis_data`, `depr_record?`, `output_dir?` | `pdf_path` |

**`property_basis` additions**: returns `records` (post-split, llcAssets schema) so the Step 4 journal preview exactly matches what will be committed (avoids split-vs-unsplit discrepancy).

**`commit` auto-PDF**: after saving records, the commit endpoint calls `resolve_output_dir(preface)` to find the output folder from `refDoc`, then calls `generate_purchase_report()`. Returns `pdf_path` on success or `pdf_error` on failure (commit itself still succeeds).

**`pdf_report` re-save**: standalone endpoint for re-saving the PDF to a different folder. Falls back to `resolve_output_dir()` if `output_dir` is not supplied.

`_safe_json()` strips float NaN/Inf before serialisation.

### 4.2 GL Sources

All GL sources loaded for `balance_assist` and `check_existing`:
```python
for key in ('llcExpRev', 'llcAssets', 'llcPayables', 'llcReceivables'):
    gl_rows.extend(objects[key].load() or [])
```

---

## 5. Dialog — `ui/templates/_propAgent_dialog.html`

Included from `table_view.html` only when `OBJ_TYPE == 'llcAssets'`. All state lives in a JavaScript IIFE.

### 5.1 Step Map

| Step | Label | Key Actions |
|---|---|---|
| **0 — Preface** | Common Fields | `propNm`, `propAddr`, `closingDate`, `closingDoc`, `tID_Prefix`, `assetType`, `assetState`, `acctSub`, `propOwners`, **`refDB`**, `landPct`; required-field gate before Next |
| **1 — Input** | Paste Statement | Textarea (JSON array); POST `/api/propAgent/classify`; parse errors shown inline |
| **2 — Review Ledger** | Classified Rows | Editable table: #, Description, Dr/Cr, Amount, GL Account, Tax Treatment, Rule; unmatched rows orange |
| **3 — Balance Check** | Balance + Depreciation | ΣDebits vs ΣCredits; Escrow Holding Balance indicator (green=$0, red=delta); Balance Assist panel (GL funding context + suggestion); **MACRS depreciation estimate** (FY + YTD); **"YE Post?"** button to queue staging entry; balanced gate before Next |
| **4 — Basis & Commit** | Basis & Journal | POST `/api/propAgent/property_basis`; read-only basis+depr table; journal from post-split `_records`; Override/Dup toggle for duplicates; Commit → POST `/api/propAgent/commit`; PDF path shown on success; Re-save PDF panel |

### 5.2 Key State Variables

```javascript
let _classified   = [];    // last classify result (pre-split, no Ledger assigned)
let _preface      = {};    // Step 0 fields
let _balance      = {};    // balance_sheet result
let _records      = [];    // post-split records from property_basis (drives Step 4 preview)
let _sessionRules = [];    // user-added rules this session
let _rawRows      = [];    // saved for re-classify after adding a rule
let _basisData    = {};    // basis + depreciation (server-authoritative after Step 3→4)
let _deprRecord   = null;  // scheduled YE depreciation record (set by caYEPost)
let _dupDecisions = {};    // { row_idx: {mode:'override'|'dup', existing_tID} }
let _committed    = false; // true after successful commit → triggers page reload on close
```

**`_records` vs `_classified`**: `_classified` holds the original classified rows (used for commit payload). `_records` holds post-split records returned by `property_basis` — these are the exact llcAssets schema rows that will be written. The Step 4 journal renders from `_records` (not `_classified`) to show the actual committed state.

### 5.3 Commit Flow

On `caCommit()`:
1. Collect `override_tids` from `_dupDecisions` (rows in override mode)
2. POST `/api/propAgent/commit` with `{classified, preface, override_tids, depr_record, basis_data}`
3. Server: `toAssetRecords()` → `_apply_land_split()` → save to llcAssets; auto-generate PDF
4. Flash: `✅ Committed N entries. PDF saved: <path>` (or PDF error if folder not found)
5. `_committed = true`; commit button → "✓ Done" (closes dialog on click)
6. Re-save PDF panel revealed: shows auto-saved path; folder editable; "Re-save PDF" button
7. On `paClose()`: `window.location.reload()` to surface new records in asset table

**Override vs Dup**: When `check_existing` finds a duplicate candidate for a row:
- **Override** (default, green): `existing_tID` added to `override_tids` → filtered out before save → record replaced
- **Dup** (yellow): not added to `override_tids` → existing record kept; new record inserted alongside

### 5.4 Key JavaScript Functions

| Function | Purpose |
|---|---|
| `propAgentOpen()` | Reset all state, show backdrop |
| `paClose()` | Hide backdrop; reload page if `_committed` |
| `paGoTo(step)` | Advance/retreat; trigger API calls per step transition |
| `_renderReview()` | Build Step 2 classified rows table |
| `_collectReviewEdits()` | Read user edits from review table back into `_classified` |
| `_computeBasisAndDepr()` | Client-side MACRS estimate at Step 2→3 (avoids extra round-trip) |
| `_renderDeprEstimate()` | Render Step 3 depreciation box + YE Post / Remove buttons |
| `caYEPost()` | Build `_deprRecord` staging entry; re-render estimate box |
| `caYEPostRemove()` | Clear `_deprRecord` |
| `_renderBasis(data)` | Step 4 basis+depr summary box |
| `_buildCommitPreview()` | Step 4 journal table from `_records` + `_deprRecord` |
| `_renderPrefaceSummary()` | Step 4 header chips (propNm, date, refDB, …) |
| `_markExistingRows(matches)` | Inject Override/Dup buttons into status column |
| `caDupToggle(rowIdx)` | Toggle override↔dup decision; tint row |
| `caCommit()` | POST commit; handle PDF response; reveal Re-save panel |
| `_showPdfSection(autoPath)` | Reveal PDF re-save panel; pre-fill folder from auto-saved path |
| `caSavePdf()` | POST `/api/propAgent/pdf_report` with custom `output_dir` |
| `caToggleHelp()` | Show/hide Step 4 accounting guide panel |
| `paFlash(msg, isErr)` | Show/clear status message |
| `paPost(url, body)` | Thin `fetch` wrapper using `_scriptRoot` prefix |

---

## 6. Data Flow (End-to-End)

```
Step 0 — Preface
  _preface = {propNm, propAddr, closingDate, closingDoc, tID_Prefix,
               assetType, assetState, acctSub, propOwners, refDB, landPct}
        ↓
Step 1 — Paste raw rows (JSON array)
  POST /api/propAgent/classify {rows, session_rules?}
  → _classified: acct, aType, amt, tax_bucket, Ledger=None, _matched, _row_idx
        ↓
Step 2 — User reviews/edits acct per row
  POST /api/propAgent/check_existing → duplicate candidates flagged
  Client computes _computeBasisAndDepr() → _basisData (preview only)
        ↓
Step 3 — Balance check + Depreciation
  POST /api/propAgent/balance_sheet → balanced flag, delta
  POST /api/propAgent/balance_assist → GL funding context, suggestion
  Escrow balance displayed: green ($0) or red (delta)
  Depreciation estimate shown: FY + YTD (MACRS mid-month)
  Optional: caYEPost() → _deprRecord (Acct.Recurring.Exp staging entry)
  Balanced gate → Next enabled
        ↓
Step 4 — Basis & journal preview + Commit
  POST /api/propAgent/property_basis {classified, landPct, preface, closingDate}
  → basis (gross, land, bldg), depreciation (authoritative), records (post-split)
  _records = server records; _basisData updated
  _buildCommitPreview() renders from _records + _deprRecord

  User clicks Commit:
  POST /api/propAgent/commit {classified, preface, override_tids, depr_record, basis_data}
    → PropAgent.toAssetRecords(classified, preface)
         • _apply_land_split() if landPct > 0
         • Ledger = 'Acct.Cash.Escrow' on every record
         • _row_idx set for dup detection continuity
    → filter override_tids from existing records
    → mgr.save(filtered + records + [depr_record?])
    → auto-generate PDF: resolve_output_dir(preface) → generate_purchase_report()
    → return {committed, replaced, total_records, pdf_path?, pdf_error?}

  → Flash: ✅ Committed N entries. PDF saved: <path>
  → Re-save PDF panel revealed
  → paClose() → window.location.reload()
```

---

## 7. GL Integration — Escrow Clearing Entry

`Ledger = 'Acct.Cash.Escrow'` on every `toAssetRecords()` row.

| File | Function | Behaviour |
|---|---|---|
| `ledger/ledgerDB.py` | `toGL()` | Generates a paired GL row for the Ledger side; escrow rows net to $0 |
| `ledger/stmtGL.py` | `toDoubleEntry()` | Processes `Acct.Cash.Escrow` as a normal account; escrow balance appears on BS until cleared |

**Balance Sheet**: `Acct.Cash.Escrow` will show $0 after a complete, balanced purchase entry. If non-zero, it indicates an incomplete or unbalanced closing entry.

**Historical note**: Before v0.3 the design used `Ledger = 'nan'` (single-sided / one-sided compound entry). Changed to `Acct.Cash.Escrow` to make the clearing account explicit and auditable on the Balance Sheet.

`savePayload()` in `ui/llcRecordsView.py` normalizes any null/empty/float-nan Ledger values to string `'nan'` for records saved through the manual editor — this does not affect propAgent records which always have a string value in `Ledger`.

---

## 8. Preface Fields Reference

| Field | Type | User-Entered? | Notes |
|---|---|---|---|
| `propNm` | string | Yes | Short name: `<assetType>_<ShortName>`, e.g. `H_805HighMesa` |
| `propAddr` | string | Yes | Full street address |
| `closingDate` | date string | Yes | Normalized: `YYYY-MM-DD` → `YYYY.MM.DD` |
| `closingDoc` | string | Yes | Source document path, e.g. `H_805HighMesa, Closing Docs, Capitalize, Assets/805HighMesa/Docs/file.pdf` |
| `tID_Prefix` | string | Yes | e.g. `r20250825_220000`; becomes tID prefix for all records |
| `assetType` | string | Yes | `'H'` house, `'R'` RV, etc. |
| `assetState` | string | Yes | `InService`, `InConstruction`, `Inactive`, `Other` |
| `landPct` | float 0–100 | Yes | Tax assessor land % — `0` for Bill of Sale / personal property |
| `propOwners` | string / dict | Yes | `{"oID": pct}` dict (Issue #6); currently free-text |
| `refDB` | string | Yes | Source DB or document folder reference (e.g. `closingAid`, `Assets/805HighMesa`) |
| `acctSub` | string | Auto | Balance sheet grouping key, default `'Closing'` |
| `propID` | string | Auto | = `tID_Prefix` (property-level; same across all rows) |
| `tDB` | string | Auto | Always `'llcAssets'` |
| `refDoc` | string | Auto | `f"{propNm}, Closing Docs, {tax_bucket}, {closingDoc}"` per row |

**`closingDoc` path convention**: When `closingDoc` is formatted as a comma-delimited string with the last segment being a relative path (e.g. `Assets/805HighMesa/Docs/file.pdf`), `resolve_output_dir()` extracts that directory as the PDF output location.

---

## 9. PDF Report — `ui/llcPdfReport.py`

### 9.1 Purpose

Auto-generated on every commit. Provides a permanent, human-readable record of the purchase entry filed in the same folder as the source closing documents.

### 9.2 Output

- **Filename**: `{YYYY.MM.DD}_PurchaseNewProp_{propNm}.pdf`
- **Location**: resolved from `closingDoc` last comma-segment relative to `setup_paths.TOP`
- **Page size**: Landscape Letter (11 × 8.5 in) — required for the 8-column journal table
- **Library**: `reportlab` (v4.4+)

### 9.3 Report Sections

| Section | Content |
|---|---|
| Title | "New Property Purchase: YYYY.MM.DD — propNm" + generation timestamp |
| Closing Information | Preface fields: property, address, date, tID prefix, asset type/state, acctSub, owners, closing doc, refDB |
| Original Closing Settlement Lines | `classified[]` rows — mirrors Step 2 table (#, Description, Dr/Cr, Amount, GL Account, Tax Treatment, Rule) |
| Property Basis & Depreciation | Gross basis, land/building split, MACRS FY + YTD depreciation estimate |
| Journal Entries | 8 columns: Status, Date, Dr/Cr, Amount, Account, Ledger, acctSub, Description; fixed-asset rows green; YE Sched row amber |
| Accounting Guide | Two-column: Basis Frame explanation + Journal Frame explanation; Balance Sheet effect note |

### 9.4 Key Functions

```python
generate_purchase_report(records, preface, basis_data, depr_record, output_dir, classified=None) → str
```
Builds and writes the PDF. Returns the full path.

```python
resolve_output_dir(preface, top_dir=None) → str | None
```
Parses `closingDoc` (last comma-segment → relative path → directory) and resolves it against `setup_paths.TOP`. Falls back to `refDB` if it contains a path separator. Returns `None` if no usable path found (PDF generation skipped; `pdf_error` returned in commit response).

### 9.5 Emoji Limitation

Reportlab's standard fonts (Helvetica/Times) do not support emoji code points (U+1F000+). All status indicators in the PDF use plain ASCII (`New`, `YE Sched`) instead of `✓` / `📅`.

---

## 10. Test Coverage — `tests/test_propAgent.py`

40 tests, all passing. Key coverage areas:

| Area | Tests |
|---|---|
| Classification | ALTA Buyer/Seller format, standard Debit/Credit, null-row skipping, Totals row skipping, rule matching, fallback `_matched=False` |
| Classification rules | `county tax` → `Acct.Fixed.Tangible.InService`; `deposit`/`earnest` → `Acct.Equity.Owner.Capital.Funds` |
| Balance sheet | Balanced, unbalanced, delta calculation |
| Property basis | Gross basis sum, land/building split (land_amt + bldg_amt = gross_basis) |
| `toAssetRecords` | Schema fields: `tID` prefix, `refDoc` contains tax_bucket, **`Ledger='Acct.Cash.Escrow'`**, `propID=tID`, `propAddr`, `tDB`/`refDB`, `_row_idx` |
| Depreciation | `depreciationEstimate()`: FY, YTD, months_in_service for multiple closing months |
| Balance assist | Balanced path, unbalanced path, suggestion content |
| Duplicate detection | Exact amount match, unique-account match, cross-year exclusion |
| `check_existing` | Candidates returned, empty when no match |

**Key test**: `test_to_asset_records_ledger_is_escrow` — asserts `rec['Ledger'] == 'Acct.Cash.Escrow'` for every record produced by `toAssetRecords()`.

---

## 11. Known Limitations & Future Work (Issue #6)

| Limitation | Issue #6 Phase |
|---|---|
| `propOwners` stored as free-text string; breaks K-1 allocation | Phase 1 / Case 1 — structured picker |
| Historical records have unparseable `propOwners` | Phase 2 / Case 2 — migration script |
| No single authoritative property registry (`assetList`) | Phase 1 — `llcAssets.py` schema v2 |
| `toAssetRecords()` does not write to `assetList` on commit | Phase 3 — `save_asset_list()` call |
| `commit` route does not validate `propNm` against `assetList` | Phase 3 — 422 guard |
| RV property not in `llcAssets` at all | Phase 6 — manual `assetList` entry |
| Bill of Sale `landPct` not auto-set to 0 for non-real assetType | Future — Step 0 UI auto-default |
| PDF `resolve_output_dir` returns None if `closingDoc` has no path segment | Future — fallback to configurable default output dir |
| MACRS YTD estimate at purchase uses calendar month; IRS uses placed-in-service date | Accepted — estimate only; Form 4562 is authoritative |
