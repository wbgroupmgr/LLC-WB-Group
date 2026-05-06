# Form 1065 Book-to-IRS Design Document
**Module:** `irs/` — IRS Tax Aid Views  
**Files Covered:** `llcIRSViewBase.py`, `llcForm1065.py`  
**Last Updated:** 2026-04-19  
**Reference:** IRS Form 1065 (2024), DataModelGuide § 4 & § 5

---

## Table of Contents
1. [Overview](#overview)
2. [Program Architecture Diagram](#program-architecture-diagram)
3. [Data Flow Diagram](#data-flow-diagram)
4. [Module: `ui.llcIRSViewBase.py`](#module-llcIRSViewBasepy)
5. [Module: `ui.llcForm1065.py`](#module-llcForm1065py)
6. [External Dependencies Summary](#external-dependencies-summary)
7. [Key Data Structures](#key-data-structures)
8. [ViewBy Filter Logic](#viewby-filter-logic)

---

## Overview

These two modules form the **IRS Tax Aid View layer** in the LLC Editor. They bridge the gap between the LLC's internal financial records (Income Statement and Balance Sheet) and the IRS-filed Form 1065 PDF.

| File | Role |
|---|---|
| `ui.llcIRSViewBase.py` | Abstract base/mixin — loads and normalizes IS/BS/owners data |
| `ui.llcForm1065.py` | Concrete view — builds the UI row table for Form 1065, Page 1 |

The design follows the **DataModelGuide § 4 Phase 5 rebuild** pattern: instead of hard-coded field tables, the view queries `Form1065.nSpaceMap()` — a publish-aggregation keyed by `(tblID, rowNm, colNm)` triples — to generate one UI row per fillDict entry. Many-to-one bindings (one data cell → multiple PDF fields) fan out into multiple rows.

---

## Program Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        UI / Editor Layer                            │
│                   (calls load(), stats(), meta())                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │ instantiates
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      llcForm1065                                    │
│  (llcForm1065.py)                                                   │
│                                                                     │
│  PUBLIC API                                                         │
│  ├── load(view_by)        → List[Dict]  (main UI row builder)       │
│  ├── stats()              → Dict        (summary financials)        │
│  ├── meta()               → Dict        (view metadata)             │
│  └── (inherited) list(), save(), save_object(), reset_from_object() │
│                                                                     │
│  PRIVATE                                                            │
│  ├── _nSpaceMap()         → Dict        (fetches Form1065 namespace)│
│  └── _apply_view_by()     → List[Dict]  (static filter helper)     │
│                                                                     │
│  MODULE-LEVEL HELPERS                                               │
│  ├── _fid_num(fid)        → int                                     │
│  └── _fmt_cell(val,fType) → str                                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ inherits from
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     _llcIRSViewBase                                 │
│  (llcIRSViewBase.py)                                                │
│                                                                     │
│  DATA LOADERS                                                       │
│  ├── _loadFromIRS(llc)            (primary loader — priority chain) │
│  ├── _loadFromSavedFillDict(f,p)  (fast path — reads JSON cache)    │
│  └── _loadFallback(llc)           (last-resort — no Form1065)       │
│                                                                     │
│  SESSION MANAGEMENT                                                 │
│  └── bind_session(eSession)                                         │
│                                                                     │
│  VALUE HELPERS                                                      │
│  ├── _isv(key, default)   → float   (Income Statement value)        │
│  ├── _bsv(key, default)   → float   (Balance Sheet value)           │
│  ├── _ev(key, default)    → str     (Entity profile value)          │
│  └── _fv_prof(key,default)→ str     (F1065 profile value)           │
│                                                                     │
│  OWNER HELPERS                                                      │
│  ├── _owner_count()                → int                            │
│  ├── _owners_detail()              → List[Dict]                     │
│  ├── _per_partner_alloc()          → List[Dict]                     │
│  ├── _individual_majority_owner()  → bool                           │
│  └── _entity_majority_owner()      → bool                           │
│                                                                     │
│  INTERFACE STUBS                                                    │
│  ├── object_name()  → str                                           │
│  ├── list()         → List[Dict]                                    │
│  ├── save()         → List[Dict]                                    │
│  ├── save_object()  → List[Dict]                                    │
│  └── reset_from_object() → List[Dict]                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │ calls into
                             ▼
┌───────────────────────────────────────────────────────────────────┐
│                    External IRS / Ledger Layer                    │
│                                                                   │
│  irs.Form1065.Form1065(llc)                                       │
│  ├── .nSpaceMap(fillDict)     → namespace map (fID → fillDicts)   │
│  ├── ._fillDictFN()           → Path to JSON cache file           │
│  ├── ._resolveTaxData()       → {is_data, bs_data, owners}        │
│  ├── ._loadOwners()           → List[Dict]                        │
│  └── ._loadProfile()          → (entity_dict, f1065_dict)         │
│                                                                   │
│  ledger.stmtFinancialReport.stmtFinancialReport(llc)              │
│  └── .taxData()               → JSON string {is_data, bs_data}    │
│                                                                   │
│  irs.irsForm.irsForm                                              │
│  └── (base form class — used in fallback path only)               │
└───────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagram

```
  ┌──────────────┐
  │  eSession    │
  │  .llc (LLC)  │
  └──────┬───────┘
         │
         ▼
  ┌─────────────────────────────────────────────────────────┐
  │               _llcIRSViewBase.__init__                  │
  │               calls _loadFromIRS(llc)                   │
  └──────┬──────────────────────────────────────────────────┘
         │
         │   Priority 1: Saved JSON cache exists?
         ├──YES──► Form1065._fillDictFN() ──► read JSON
         │         _loadFromSavedFillDict()
         │         │
         │         ├── parse logicalKey → numeric values
         │         ├── apply _IS_MAP   → self._is   (is_data dict)
         │         ├── apply _BS_MAP   → self._bs   (bs_data dict)
         │         ├── Form1065._loadOwners()  → self._owners_list
         │         └── Form1065._loadProfile() → self._entity, self._f1065
         │
         │   Priority 2: Build fresh
         ├──NO───► Form1065._resolveTaxData()
         │         │
         │         ├── returns {is_data, bs_data, owners}
         │         ├── self._is   ← is_data
         │         ├── self._bs   ← bs_data
         │         ├── self._owners_agg ← owners
         │         ├── Form1065._loadOwners()  → self._owners_list
         │         └── Form1065._loadProfile() → self._entity, self._f1065
         │
         │   Priority 3: Fallback (no Form1065 import)
         └──ERR──► stmtFinancialReport(llc).taxData()
                   │
                   └── JSON parse → self._is, self._bs, self._owners_agg
                       irsForm._loadOwners(), ._loadProfile() if available


  ┌─────────────────────────────────────────────────────────┐
  │    llcForm1065.load(view_by)  ← UI calls this          │
  └──────┬──────────────────────────────────────────────────┘
         │
         ▼
  _nSpaceMap()
         │
         ├── instantiates Form1065(llc)
         ├── checks Form1065._fillDictFN() for JSON cache
         │      YES → load fields dict from JSON
         │      NO  → pass fillDict=None
         └── calls Form1065.nSpaceMap(fillDict=fillDict)
                │
                ▼
         { (tblID, rowNm, colNm) : [fillDict, fillDict, ...] }
                │
                ▼
  For each (triple, [fillDicts]):
    For each fillDict in list:
      emit UI row:
        {fID, page, logicalKey, location, tblID, rowNm, colNm,
         description, value, publish, fType, checkedValue}
                │
                ▼
  rows.sort(key=(page, fid_numeric_suffix))
                │
                ▼
  _apply_view_by(rows, view_by)
    ├── "All"        → return all rows unchanged
    ├── "CPA:unknown"→ rows where publish == "CPA:unknown"
    └── "Publish"    → rows where publish is True  ← DEFAULT
                │
                ▼
         List[Dict]  ──► UI Table Display
```

---

## Module: `llcIRSViewBase.py`

### Class: `_llcIRSViewBase`

Shared mixin base class for all IRS tax-aid view classes. Handles all data loading from the official financial report pipeline and exposes normalized helper methods.

**Attributes populated on init:**

| Attribute | Type | Description |
|---|---|---|
| `_is` | `dict` | Income Statement data keyed by field name (e.g. `net_income`) |
| `_bs` | `dict` | Balance Sheet data keyed by field name (e.g. `total_assets`) |
| `_owners_agg` | `dict` | Aggregated owners data: count, contributions, distributions |
| `_owners_list` | `list` | Raw list of owner/partner dicts from `llcOwners` JSON |
| `_entity` | `dict` | Entity profile info from `llcProfile` |
| `_f1065` | `dict` | Form 1065 profile settings from `llcProfile` |

---

### Data Loader Methods

#### `__init__(self, eSession)`
**Visibility:** Public constructor  
Initializes all data attributes to empty state, then calls `_loadFromIRS(llc)` if a valid LLC object is found on the session.

---

#### `_loadFromIRS(self, llc) → None`
**Visibility:** Internal  
**Primary data loader** — implements a three-tier priority chain:

1. **Priority 1 (fastest):** If `Form1065._fillDictFN()` points to an existing JSON cache file, delegates to `_loadFromSavedFillDict()`.
2. **Priority 2 (fresh build):** Calls `Form1065._resolveTaxData()` to build IS/BS/owners from `stmtFinancialReport` on the fly, then loads owners list and entity profile.
3. **Priority 3 (last resort):** On any import or runtime failure, delegates to `_loadFallback()`.

---

#### `_loadFromSavedFillDict(self, form_obj, fd_path: Path) → None`
**Visibility:** Internal  
Reads the saved `Form1065_fillDict.json` cache and reconstructs `_is` and `_bs` from it without running the full financial report. Steps:

1. Opens and parses the JSON file, isolating the `fields` dict.
2. Builds a `{logicalKey: float}` lookup by parsing numeric values from each field's `value` string.
3. Applies `_IS_MAP` — a hardcoded mapping from IRS logical keys (e.g. `P1_1a`, `P1_23`) to IS field names (e.g. `rent_income`, `net_income`).
4. Applies `_BS_MAP` — a hardcoded mapping from IRS logical keys (e.g. `L_14_2`, `L_21_2`) to BS field names (e.g. `total_assets`, `total_equity`).
5. Extracts partner count from field `P1_I` or `B_25Fm`.
6. Loads the owners list and entity profile from `Form1065._loadOwners()` / `._loadProfile()`.

**Internal constant: `_IS_MAP`** — maps 10 Income Statement logical keys to `is_data` field names.  
**Internal constant: `_BS_MAP`** — maps 13 Balance Sheet logical keys to `bs_data` field names.

---

#### `_loadFallback(self, llc) → None`
**Visibility:** Internal  
Last-resort loader used when `Form1065` cannot be imported. Attempts two independent sub-paths:

- Calls `stmtFinancialReport(llc).taxData()` directly and parses the JSON result into `_is`, `_bs`, `_owners_agg`.
- Tries to construct a dummy `irsForm` subclass to call `_loadOwners()` and `_loadProfile()` for entity/owner data.

Silently swallows all exceptions — the view degrades to empty data rather than crashing.

---

### Session Management

#### `bind_session(self, eSession) → None`
**Visibility:** Public  
Re-attaches the view to a new `eSession` object and reloads all data from scratch. Used when the editor session changes without recreating the view instance. Resets all attributes to empty then calls `_loadFromIRS()`.

---

### Value Helper Methods

#### `_isv(self, key: str, default: float = 0.0) → float`
**Visibility:** Internal  
Returns a numeric float from `self._is` (Income Statement data). Safely coerces the stored value to `float`, rounds to 2 decimal places, and returns `default` on any error.

---

#### `_bsv(self, key: str, default: float = 0.0) → float`
**Visibility:** Internal  
Returns a numeric float from `self._bs` (Balance Sheet data). Same coercion and error handling as `_isv`.

---

#### `_ev(self, key: str, default: str = "") → str`
**Visibility:** Internal  
Returns a string value from `self._entity` (entity profile dict). Returns `default` if the key is missing or the value is falsy.

---

#### `_fv_prof(self, key: str, default: str = "") → str`
**Visibility:** Internal  
Returns a string value from `self._f1065` (Form 1065 profile dict). Same behavior as `_ev`.

---

### Owner Helper Methods

#### `_owner_count(self) → int`
**Visibility:** Internal  
Returns the number of partners/members by counting `self._owners_list`.

---

#### `_owners_detail(self) → List[Dict]`
**Visibility:** Internal  
Returns per-partner detail rows. Prefers `owners_agg["detail"]` list; falls back to the raw `_owners_list` if detail is absent.

---

#### `_per_partner_alloc(self) → List[Dict]`
**Visibility:** Internal  
Computes and returns a per-partner allocation list. For each owner in `_owners_list`, calculates:
- `ni_share` — net income × ownership percentage
- `rent_share` — rent income × ownership percentage
- `distrib` — max(0, net income) × ownership percentage

Returns a list of dicts with keys: `oID`, `name`, `pct`, `type`, `status`, `ni_share`, `rent_share`, `distrib`.

---

#### `_individual_majority_owner(self) → bool`
**Visibility:** Internal  
Returns `True` if any individual, estate, or person owner holds more than 50% interest. Used for IRS filing checkbox logic.

---

#### `_entity_majority_owner(self) → bool`
**Visibility:** Internal  
Returns `True` if any corporate, partnership, trust, or exempt-organization owner holds more than 50% interest. Entity type matching is case-insensitive substring matching against: `corp`, `corporation`, `partnership`, `trust`, `llc_entity`, `exempt`, `org`, `foreign`.

---

### Interface Stub Methods

These methods provide a common interface contract for all IRS view classes. All delegate to `load()`.

| Method | Returns | Purpose |
|---|---|---|
| `object_name()` | `str` | Returns the class name — used as the view's identifier in the UI |
| `list()` | `List[Dict]` | Alias for `load()` with default parameters |
| `save(data)` | `List[Dict]` | No-op save stub — returns `load()`. IRS views are read-only. |
| `save_object(data)` | `List[Dict]` | No-op save stub — returns `load()` |
| `reset_from_object()` | `List[Dict]` | Reload stub — returns `load()` |

---

## Module: `llcForm1065.py`

### Module-Level Helpers

#### `_fid_num(fid: str) → int`
**Visibility:** Module-private helper  
Extracts the trailing numeric suffix from a PDF AcroForm field ID string (e.g. `"f59"` → `59`). Used as the sort key for PDF reading order. Returns `10_000` for empty or non-numeric fIDs so they sort to the bottom.

---

#### `_fmt_cell(val: Any, fType: str) → str`
**Visibility:** Module-private helper  
Renders a raw nSpaceMap value for display in the UI table:
- Returns `""` for `None` or empty values.
- For `checkBox` / `checkText` fields with a string value, returns the string as-is (e.g. `"/1"`, `"/2"`).
- For numeric `int` / `float` values, formats with comma thousands separator and 2 decimal places (`f"{val:,.2f}"`).
- All other values are cast to `str`.

---

### Class: `llcForm1065`

Inherits from `_llcIRSViewBase`. Builds the Form 1065 Page 1 tax-aid view by querying `Form1065.nSpaceMap()`.

**Class Attribute:**

| Attribute | Type | Value |
|---|---|---|
| `VIEW_BY_OPTIONS` | `List[str]` | `['Publish', 'All', 'CPA:unknown']` |

---

### Public API Methods

#### `load(self, view_by: str = 'Publish') → List[Dict[str, Any]]`
**Visibility:** Public — primary entry point  
Builds the complete Form 1065 UI row list. Steps:

1. Calls `self._nSpaceMap()` to get the namespace map from `Form1065`.
2. Iterates over every `(tblID, rowNm, colNm)` triple and its list of `fillDict` records — each fillDict becomes one UI row.
3. Each row dict contains: `fID`, `page`, `logicalKey`, `location`, `tblID`, `rowNm`, `colNm`, `description`, `value`, `publish`, `fType`, `checkedValue`.
4. Sorts rows by `(page ascending, fID numeric suffix ascending)` — this matches PDF top-left → bottom-right reading order.
5. Passes sorted rows to `_apply_view_by()` for filtering.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `view_by` | `str` | `'Publish'` | Filter mode: `"Publish"`, `"All"`, or `"CPA:unknown"` |

**Returns:** `List[Dict]` — one dict per PDF form field, in PDF reading order.

---

#### `stats(self) → Dict[str, Any]`
**Visibility:** Public  
Returns a summary financial snapshot for the LLC. Pulls values from the inherited `_isv()` and `_bsv()` helpers.

| Key | Source | Description |
|---|---|---|
| `Gross Income` | `_isv('total_income')` | Total income from IS |
| `Total Expense` | `_isv('total_expenses')` | Total expenses from IS |
| `Net Income` | `_isv('net_income')` | Net income from IS |
| `Total Assets` | `_bsv('total_assets')` | Total assets from BS |

---

#### `meta(self) → Dict[str, Any]`
**Visibility:** Public  
Returns static metadata about this view for UI display and debugging.

| Key | Description |
|---|---|
| `objectName` | Class name via `object_name()` |
| `viewBy` | Copy of `VIEW_BY_OPTIONS` list |
| `source` | String `"irs.Form1065.nSpaceMap()"` |
| `note` | Human-readable description of the view's data source and filing disclaimer |

---

### Internal Methods

#### `_nSpaceMap(self) → Dict[Tuple[str, str, str], List[Dict[str, Any]]]`
**Visibility:** Internal  
Fetches the Form 1065 namespace map from the `irs.Form1065.Form1065` class. Logic:

1. Retrieves `self.eSession.llc` — returns `{}` if absent.
2. Imports `Form1065` from `irs.Form1065`, falling back to a relative `sys.path` insertion if the package import fails.
3. Instantiates `Form1065(llc=llc)`.
4. Checks for a saved `Form1065_fillDict.json` via `form._fillDictFN()`. If it exists, loads the `fields` dict from it so `nSpaceMap()` can reuse cached values.
5. Calls and returns `form.nSpaceMap(fillDict=fillDict)`.
6. Returns `{}` on any exception — the view degrades gracefully to an empty table.

**Return type:** `Dict[Tuple[str, str, str], List[Dict]]`  
Keys are `(tblID, rowNm, colNm)` triples; values are lists of fillDict records.

---

#### `_apply_view_by(rows: List[Dict], view_by: str) → List[Dict]`
**Visibility:** Static internal method  
Filters the UI row list according to the selected ViewBy option:

| `view_by` value | Filter logic |
|---|---|
| `"All"` | Returns all rows unfiltered |
| `"CPA:unknown"` | Keeps only rows where `publish == "CPA:unknown"` |
| `"Publish"` (default) | Keeps only rows where `publish is True` (strict boolean — excludes `"CPA:unknown"` and `False`) |

---

## External Dependencies Summary

The following modules are imported or referenced by these two files but are **not defined within them**. All are assumed to exist in the broader application codebase.

### Required (Core Path)

| Module / Class | Import Path | Used By | Purpose |
|---|---|---|---|
| `Form1065` | `irs.Form1065` | Both files | Main IRS form object. Provides `nSpaceMap()`, `_resolveTaxData()`, `_fillDictFN()`, `_loadOwners()`, `_loadProfile()` |
| `stmtFinancialReport` | `ledger.stmtFinancialReport` | `llcIRSViewBase` | Builds Income Statement and Balance Sheet data; `.taxData()` returns JSON |
| `irsForm` | `irs.irsForm` | `llcIRSViewBase` (fallback only) | Abstract base form class. Used only in the fallback loading path to access `_loadOwners()` and `_loadProfile()` |

### Session / Entity Objects

| Object | Source | Used By | Purpose |
|---|---|---|---|
| `eSession` | Caller-provided | Both | Editor session container; `.llc` attribute must point to a valid LLC object |
| `eSession.llc` | `eSession` | Both | LLC data object; must expose `acctDir(dirName)` used by `irsForm` in the fallback path |

### Standard Library

| Module | Used By | Purpose |
|---|---|---|
| `re` | `llcForm1065` | Regex to extract numeric suffix from field IDs (`_fid_num`) |
| `json` | `llcIRSViewBase` | Reading `Form1065_fillDict.json` cache files |
| `pathlib.Path` | `llcIRSViewBase` | File path handling for the fillDict JSON cache |
| `typing` (Any, Dict, List, Tuple, Optional) | Both | Type annotations throughout |
| `sys`, `os` | Both | Fallback `sys.path` manipulation for relative imports of `Form1065` |

### Data Files (Runtime, Not Imported)

| File | Used By | Purpose |
|---|---|---|
| `Form1065_fillDict.json` | `llcIRSViewBase`, `llcForm1065` | Cached PDF fill dictionary. Located via `Form1065._fillDictFN()`. When present, avoids full financial report recalculation. |
| `Form1065_FILL.pdf` | Referenced conceptually | The filed PDF whose field values must exactly match what these views display |

---

## Key Data Structures

### nSpaceMap Entry

The central data structure passed from `Form1065.nSpaceMap()`:

```python
# Key
(tblID: str, rowNm: str, colNm: str)
# e.g. ("IncomeStmt", "TOTAL", "Balance")

# Value: list of fillDict records (one per PDF field bound to this cell)
[
    {
        "fID":          "f59",          # AcroForm field ID
        "page":         1,              # IRS page number (1-based)
        "logicalKey":   "P1_23",        # IRS logical key
        "location":     "Form1065.Pg1.Income",
        "note":         "Ordinary business income",
        "label":        "Line 23",
        "value":        42500.00,       # resolved cell value
        "publish":      True,           # True | False | "CPA:unknown"
        "fType":        "text",         # "text" | "checkBox" | "checkText" | "image"
        "checkedValue": "",             # "/1" | "/2" | "" (checkBox only)
    },
    # ... additional PDF fields bound to same data cell
]
```

### UI Row Dict

Output of `llcForm1065.load()` — one dict per PDF field:

```python
{
    "fID":          "f59",
    "page":         1,
    "logicalKey":   "P1_23",
    "location":     "Form1065.Pg1.Income",
    "tblID":        "IncomeStmt",
    "rowNm":        "TOTAL",
    "colNm":        "Balance",
    "description":  "Ordinary business income",
    "value":        "42,500.00",        # currency-formatted string
    "publish":      True,
    "fType":        "text",
    "checkedValue": "",
}
```

### `_IS_MAP` (Income Statement Logical Key → IS Field Name)

| Logical Key | IS Field Name | Line Description |
|---|---|---|
| `P1_1a` | `rent_income` | Gross receipts / rent income |
| `P1_8` | `total_income` | Total income |
| `P1_9` | `salaries` | Salaries & wages |
| `P1_11` | `repairs` | Repairs & maintenance |
| `P1_14` | `taxes_licenses` | Taxes and licenses |
| `P1_15` | `interest_expense` | Interest expense |
| `P1_16a` | `depreciation` | Depreciation |
| `P1_21` | `other_deductions` | Other deductions |
| `P1_22` | `total_expenses` | Total deductions |
| `P1_23` | `net_income` | Ordinary business income (loss) |
| `K_5` | `interest_income` | Schedule K interest income |
| `K_19a` | `distributions_cash` | Schedule K cash distributions |
| `K_2` | `rent_income` | Schedule K rent (fallback) |
| `M2_6a` | `distributions_cash` | Schedule M-2 distributions (fallback) |

### `_BS_MAP` (Balance Sheet Logical Key → BS Field Name)

| Logical Key | BS Field Name | Line Description |
|---|---|---|
| `L_1_2` | `cash` | Cash (end of year) |
| `L_2a_2` | `ar` | Accounts receivable |
| `L_9a_2` | `buildings` | Buildings & improvements |
| `L_9b_2` | `accum_depr` | Less accumulated depreciation |
| `L_11_2` | `land` | Land |
| `L_13_2` | `other_assets` | Other assets |
| `L_14_2` | `total_assets` | Total assets |
| `P1_F` | `total_assets` | Total assets (Page 1 fallback) |
| `L_15_2` | `payables` | Accounts payable |
| `L_19a_2` | `mortgage` | Mortgage/notes payable |
| `L_20_2` | `other_liab` | Other liabilities |
| `L_21_2` | `total_equity` | Partners' capital accounts |
| `L_22_2` | `total_liab_capital` | Total liabilities & capital |

---

## ViewBy Filter Logic

```
view_by = "Publish"  (default)
    └── publish is True  →  KEEP   (fields actively bound by PUBLISH_MAP)
    └── publish = False  →  DROP
    └── publish = "CPA:unknown" → DROP

view_by = "All"
    └── ALL rows returned unfiltered

view_by = "CPA:unknown"
    └── publish == "CPA:unknown" → KEEP  (fields awaiting CPA confirmation)
    └── all others → DROP
```

The `publish` field has three possible states:

| Value | Meaning |
|---|---|
| `True` | Field is actively mapped by a `PUBLISH_MAP` binding and flows to the filed PDF |
| `False` | Field exists in the form but is not currently mapped |
| `"CPA:unknown"` | Field mapping requires CPA confirmation before it can be published |

---

*End of Design Document*