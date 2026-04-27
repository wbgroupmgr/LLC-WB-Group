# IRS Form Services  —  `irs/` package

## Overview

The `irs/` package generates filled IRS PDF forms for the LLC from live general-ledger data.  It wraps the official IRS AcroForm PDFs, maps every field to a GL data source, resolves current-year values, and writes a filled output PDF ready for CPA review.

---

## Architecture

### Design principle

One field namespace → one fillDict → one FILL PDF.

Every field discovered in the IRS template passes through a single function, `_buildFillDict(nspace)`, that assigns a **publish flag** and a **resolved value** in one pass.  There is no separate intermediate GLMap file or second resolution step.

```
IRS template PDF
      │
      ▼
_buildNSpace()         ← reads AcroForm fields, assigns fIDs, classifies fType
      │  nSpaceDict (all fields)
      ▼
_buildFillDict(nspace) ← sets publish flag + resolves value for each field
      │  fillDict (all fields, publish=True|False|"CPA:unknown", value="…")
      ▼
saveFILL(fillDict)     ← writes FILL.pdf (publish=True fields only)
                          also saves fillDict JSON automatically
```

### publish flag semantics

| publish value   | Meaning                                              | PDF action        |
|-----------------|------------------------------------------------------|-------------------|
| `True`          | Field is auto-filled from LLC financial databases    | Written to PDF    |
| `"CPA:unknown"` | Field needs CPA / accountant review before filing    | Left blank in PDF |
| `False`         | Field is not applicable or intentionally blank       | Left blank in PDF |

---

## Data sources

Financial figures for the FILL PDF are **always** drawn from the official `stmtFinancialReport` databases, never from a working `EditSession`.

| source key | Origin |
|------------|--------|
| `entity`   | `llcProfile_WBGroupLLC.json` → `profile["entity"]` |
| `F1065`    | `llcProfile_WBGroupLLC.json` → `profile["F1065"]` |
| `IS`       | `stmtFinancialReport(llc).taxData()` → `td["is_data"]` |
| `BS`       | `stmtFinancialReport(llc).taxData()` → `td["bs_data"]` |
| `owners`   | `stmtFinancialReport(llc).taxData()` → `td["owners"]` |
| `schB_default` | Hard-coded `{"No": "/2", "Yes": "/1"}` — Sched B checkbox defaults |

The `stmtFinancialReport` is instantiated internally by `_resolveTaxData()`.  No external reference to it is needed in the caller's workflow.

---

## File naming convention

All output files are written to `self.irsDir` (= `{acctDir}/YE_Tax_Records/Forms_IRS/`).

| File | Description |
|------|-------------|
| `{oID}_IRS.pdf`         | IRS blank template (input — not modified) |
| `{oID}_namespace.json`  | Field namespace — all AcroForm fields with fID, logicalKey, fType |
| `{oID}_namespace.pdf`   | Worksheet PDF — text fields show fID; checkboxes are checked |
| `{oID}_fillDict.json`   | Complete fillDict — all fields, publish flags, resolved values |
| `{oID}_FILL.pdf`        | Filled output PDF — publish=True fields written |

---

## fillDict field schema

Each entry in the fillDict:

```json
{
  "f42": {
    "fID":          "f42",
    "pdfField":     "topmostSubform[0].Page1[0].f1_6[0]",
    "shortName":    "f1_6",
    "logicalKey":   "P1_1a",
    "label":        "Gross receipts",
    "fType":        "text",
    "page":         1,
    "location":     "Form1065.Pg1.Income",
    "checkedValue": "",
    "publish":      true,
    "source":       "IS",
    "path":         "rent_income",
    "note":         "Gross rental receipts  (Acct.Rev.Rent.*)",
    "value":        "48,000.00"
  }
}
```

---

## Classes

### `irsForm`  (`irsForm.py`)

Abstract base class.  All form-specific subclasses inherit from it.

**Constructor**

```python
irsForm(llc, verbose=False)
```

`llc` is the LLC management object; `llc.acctDir(dirName='ye')` resolves `irsDir`.

**Public API**

| Method | Description |
|--------|-------------|
| `_buildNSpace() → dict` | Read IRS template; return nSpaceDict with all AcroForm fields |
| `saveNSpace(nspace)` | Save namespace JSON + worksheet PDF |
| `_buildFillDict(nspace) → dict` | **Override in subclass.** Base returns all fields with `publish=False`. Subclass applies publish flags and resolves values. |
| `saveFillDict(fillDict)` | Save complete fillDict JSON to `{oID}_fillDict.json` |
| `saveFILL(fillDict, suffix="") → str` | Write FILL PDF (publish=True fields); also calls `saveFillDict` automatically. Returns output path. |

**File-name helpers**

| Method | Returns |
|--------|---------|
| `FN()` | Path to `{oID}_IRS.pdf` |
| `_nspaceFN()` | Path to `{oID}_namespace.json` |
| `_fillDictFN()` | Path to `{oID}_fillDict.json` |
| `_fillFN(suffix)` | Path to `{oID}{suffix}_FILL.pdf` |

**Data helpers** (available to all subclasses)

| Method | Description |
|--------|-------------|
| `_loadProfile() → (entity, f1065)` | Load `llcProfile_WBGroupLLC.json` |
| `_loadOwners() → list` | Load `llcOwners_WBGroupLLC.json` |
| `_resolve(source, path, src_map) → str` | Walk dotted key path in src_map |
| `_fmt(v) → str` | Format numeric/string value for PDF field |
| `_loadKeyMap() → dict` | Load `{oID}-keys.pdf` (shortName → logicalKey) |
| `_loadLabelMap() → dict` | Load `{oID}-FieldNames.json` (logicalKey → label) |

**Deprecated (backward-compat only)**

| Old method | Replacement |
|------------|-------------|
| `_buildGLMap(nspace)` | `_buildFillDict(nspace)` |
| `saveGLMap(d)` | `saveFillDict(d)` |
| `_buildFILL(nspace)` | `_buildFillDict(nspace)` |

---

### `Form1065`  (`Form1065.py`)

Subclass of `irsForm` for IRS Form 1065 (U.S. Return of Partnership Income).

`self.oID = "Form1065"` — drives all file names.

**Workflow**

```python
from irs.Form1065 import Form1065
from ledger.LLC   import LLC

llc   = LLC()
f1065 = Form1065(llc=llc, verbose=True)

nspace   = f1065._buildNSpace()
f1065.saveNSpace(nspace)

fillDict = f1065._buildFillDict(nspace)
f1065.saveFILL(fillDict)   # writes FILL.pdf + fillDict JSON
```

**`_buildFillDict(nspace, is_data=None, bs_data=None)` — single-pass logic**

Applies publish flags in priority order:

1. `_FILL_MAP` entries → `publish=True`, value resolved from IS/BS/entity/F1065/owners
2. `_CPA_NOTES` entries → `publish="CPA:unknown"`, value blank
3. Schedule B `checkText` No-defaults (pattern `c{pg}_{seq}_No`) → `publish=True`, value = checkedValue
4. All remaining fields → `publish=False`, value blank

IS/BS data is loaded from `stmtFinancialReport(self.llc).taxData()` via `_resolveTaxData()`.

**`_FILL_MAP` — auto-filled fields**

Covers Page 1 (header, entity info, income, deductions, paid preparer), Page 4 (Partnership Representative), Schedule B partner count, Schedule K (Page 5), Schedule L assets and liabilities, Schedule M-1, Schedule M-2.

**`_CPA_NOTES` — CPA review fields**

Covers lines that require accountant judgment: returns & allowances (1b), COGS (2), other partnership income (4), guaranteed payments (10), Form 4797 gain/loss (6), accounting method (H), M-1 adjustment lines, M-2 beginning capital, and several Schedule L liability lines.

**`LOCATION_RULES`** — ordered regex patterns that assign a `location` path string to each field (e.g., `"Form1065.Pg1.Income"`, `"Form1065.Pg5.SchedK"`).

**Override methods** (legacy PDF filename support)

| Method | Purpose |
|--------|---------|
| `FN()` | Checks `Form1065_IRS.pdf` then falls back to `Form_1065-IRS.pdf` |
| `_loadKeyMap()` | Checks `Form1065-keys.pdf` then `Form_1065-keys.pdf` |
| `_loadLabelMap()` | Checks `Form1065-FieldNames.json` then `Form_1065-FieldNames.json` |

**Tax-data helpers**

| Method | Description |
|--------|-------------|
| `_resolveTaxData() → dict` | Instantiates `stmtFinancialReport(self.llc)`, calls `taxData()`, returns `{is_data, bs_data, owners, meta}`. Falls back to empty dicts on failure. |
| `_getFRData(fr) → dict` | Calls `fr.taxData()` and JSON-parses the result. |

---

## Extending: adding a new form

1. Create `irs/FormXXXX.py` subclassing `irsForm`.
2. Define `LOCATION_RULES` for section classification.
3. Define `_FILL_MAP` and `_CPA_NOTES` module-level dicts.
4. Override `_buildFillDict(nspace, **kwargs)`:
   - call `super()._buildFillDict(nspace)` for the base dict
   - apply your FILL_MAP and CPA_NOTES
   - resolve values from `_resolveTaxData()` or form-specific sources
5. Override `FN()` / `_loadKeyMap()` / `_loadLabelMap()` if the IRS PDF uses a non-standard name.

```python
class Form4562(irsForm):
    LOCATION_RULES = [...]
    _FILL_MAP  = {...}
    _CPA_NOTES = {...}

    def _buildFillDict(self, nSpaceDict, **kwargs):
        fillDict = super()._buildFillDict(nSpaceDict)
        # apply maps, resolve values ...
        return fillDict
```

---

---

### `Sch_K1`  (`Sch_K1.py`)

Subclass of `Form1065`.  Generates one Schedule K-1 PDF per partner.

`self.oID = "Sch_K1"` — drives all file names.

**Workflow**

```python
from irs.Sch_K1 import Sch_K1
from ledger.LLC import LLC

llc  = LLC()
k1   = Sch_K1(llc=llc, verbose=True)

nspace = k1._buildNSpace()
k1.saveNSpace(nspace)

# Single partner (partner_idx=0):
fillDict = k1._buildFillDict(nspace, partner_idx=0)
k1.saveFILL(fillDict, suffix="_PartnerName")

# All partners at once:
k1.saveFILL_allPartners(nspace)   # creates one PDF per partner
```

**Per-partner computation** — for each owner in `owners.detail`:
- Box 1 ordinary income/loss = `(net_income − rent_income) × pct`
- Box 2 rental income = `rent_income × pct`
- Box 5 interest = `interest_income × pct`
- Box 19 distributions = `max(0, net_income) × pct`
- Capital end year = `contrib + ni_share − distributions`

Data is always drawn from the same `_resolveTaxData()` pipeline as Form1065.

---

### `Form4562`  (`Form4562.py`)

Subclass of `irsForm`.  Generates the IRS Form 4562 (Depreciation and Amortization) PDF.

`self.oID = "Form4562"` — drives all file names.

**Workflow**

```python
from irs.Form4562 import Form4562
from ledger.LLC   import LLC

llc   = LLC()
f4562 = Form4562(llc=llc, verbose=True)

nspace   = f4562._buildNSpace()
f4562.saveNSpace(nspace)

fillDict = f4562._buildFillDict(nspace)
f4562.saveFILL(fillDict)   # writes FILL.pdf + fillDict JSON
```

**Key auto-filled lines** (from `stmtFinancialReport`):

| Line | Source | Description |
|------|--------|-------------|
| 19a (c) | BS.buildings | Cost / basis of residential rental property |
| 19a (g) | IS.depreciation | Current-year MACRS deduction |
| 22 | IS.depreciation | Total depreciation → Form 1065 Line 16a |
| 42 | IS.depreciation | Total deductions (simplified) |

§179, bonus depreciation, listed property, and amortization lines are marked `publish="CPA:unknown"`.

---

### `_llcIRSViewBase`  (`uillc/llcIRSViewBase.py`)

Shared mixin / base class for all 10 LLC Editor "IRS tax aid" view files.
Replaces direct `llcReportEngine` usage so that editor views display the
**exact same values** as the filed FILL PDF.

**Load priority:**
1. Saved `Form1065_fillDict.json` (fastest — values already resolved)
2. Fresh build from `stmtFinancialReport(llc).taxData()`

**Helper methods:**

| Method | Returns |
|--------|---------|
| `_isv(key)` | Numeric float from `is_data` |
| `_bsv(key)` | Numeric float from `bs_data` |
| `_ev(key)` | String from `entity` profile |
| `_fv_prof(key)` | String from `F1065` profile |
| `_owner_count()` | Number of partners |
| `_per_partner_alloc()` | List of `{oID, name, pct, type, ni_share, rent_share, distrib}` |
| `_individual_majority_owner()` | True if any individual holds >50% |
| `_entity_majority_owner()` | True if any corp/trust holds >50% |

**Consumer view files** (all now subclass `_llcIRSViewBase`):
- `llcForm1065.py` — Page 1 income / deductions
- `llcFormK1.py` — Schedule K-1 per-partner table
- `llcFormSchedL.py` — Schedule L balance sheet
- `llcFormSchedM1.py` — Schedule M-1 reconciliation
- `llcFormSchedM2.py` — Schedule M-2 capital accounts
- `llcForm1065SchKPg5.py` — Schedule K page 5
- `llcForm1065Pg6.py` — Page 6 (L + M-1 + M-2)
- `llcForm1065SchBPg2.py` — Schedule B Q1–12
- `llcForm1065SchBPg3.py` — Schedule B Q13–25
- `llcForm1065SchBPg4.py` — Page 4 (Partner Rep + NI Analysis)

---

## Key files

```
irs/
├── irsForm.py            Base class — workflow engine + shared helpers
├── Form1065.py           Form 1065 service (this LLC's primary return)
├── Sch_K1.py             Schedule K-1 (per-partner) — subclass of Form1065
├── Form4562.py           Depreciation & Amortization — subclass of irsForm
└── irs.readme.md         This document

uillc/
└── llcIRSViewBase.py     Shared mixin for all 10 LLC Editor IRS view classes
```

---

*Last updated: 2026-04-18*
