# Design for BookToIRS — IRS Form 4562 (Depreciation and Amortization)

## 1. Overview

Form 4562 reports all depreciation and amortization deductions for the LLC.
For W&B Group (residential rental, hold-to-rent) the operative section is
**Part III Line 19h** — 27.5-year MACRS, Mid-Month convention, Straight-Line method.
Line 22 (total depreciation) flows into Form 1065 Line 16a, and Form 8825 Line 14
receives the same figure.

---

### 1.1 LLC Depreciation Handling in 2025

The original books for depreciation, ie. Assets (Acct.Exp.Depreciation, Acct.Fixed.Depreciation.Accum) was incorrect. 


### 1.1.1. The True Tax Treatment (The De Minimis Safe Harbor)

* Treasury Regulation §1.263(a)-3: This governs the capitalization or expensing of improvements to tangible property.
* The Safe Harbor Rule: Under the De Minimis Safe Harbor election,
    - a taxpayer can elect to immediately expense (write off) tangible property costs up to a certain threshold (
        - $2,500 per item/invoice for unstated financial statements, 
        - or $5,000 for audited statements) rather than capitalizing them.
* Section §179:
    - As entered the expenses are not a Section 179 deduction,
    - Section 179 requires capitalizing the asset first and
    - then electing to expense it up to a annual limit on Form 4562.
    - **This can NOT BE USED BECAUSE AGI > \$100K**, fallback to MACRS
* MACRS: standard Modified Accelerated Cost Recovery System depreciation
    - MACRS spreads the cost out over a set recovery period (e.g., 5, 7, 15, 27.5, or 39 years).
* CORRECION NEEDED:
    - The $5,246.06 should have been booked directly to a Repairs & Maintenance
    - or Safe Harbor Expensing account,
    - completely bypassing the depreciation schedules.

-----------------------------
## 2. irs.Form4562 — Architecture

`Form4562` is a thin subclass of `irsForm`, following the same pattern as `Form8825`.
It delegates all fill pipeline work to `BookToIRS` via `aid()`.  No `_FILL_MAP` is
used; per-fid values are driven entirely by the `bookNS_<src>.json` mapping tables.

```
bookNS_Profile.json  [Form4562]  →  stmtProfile.loadFillDict("Form4562")
bookNS_BS.json       [Form4562]  →  stmtBS_Tax.loadFillDict("Form4562")
bookNS_IS.json       [Form4562]  →  stmtIS_Tax.loadFillDict("Form4562")
         ↓
BookToIRS.regenerate()           →  Form4562_FILL.pdf  (13 fields filled)
         ↓
ui.llcForm4562 (irs_pdf_view.html + stat chips + Review button)
```

### Key Files

| File | Role |
|---|---|
| `irs/Form4562.py` | irsForm subclass — `aid()`, `LOCATION_RULES`, `_CPA_NOTES` |
| `ui/llcForm4562.py` | Flask view wrapper — `pdf_path()`, `stats()`, `meta()` |
| `2025/bookNS_Profile.json` | Entity name / EIN / business activity fid mappings |
| `2025/bookNS_BS.json` | Placed-in-service date / building cost / MACRS constants |
| `2025/bookNS_IS.json` | §179 limit / deduction / current-year depreciation |
| `2025/YE_Tax_Records/Forms_IRS/Form4562_namespace.json` | AcroForm field catalog (323 fields, 60 with logicalKeys) — **gitignored** |
| `2025/YE_Tax_Records/Forms_IRS/Form4562_FILL.pdf` | Pipeline output — **gitignored** |

---

## 3. Field Mapping Table — 13 Fields Filled

### bookNS_Profile.json → Form4562

| fid | logicalKey | UAS Path | Resolved Value |
|---|---|---|---|
| f2 | P1_Hdr_Nm | `Profile.entity.entity_name` | W&B Group, LLC |
| f3 | P1_Hdr_EIN | `Profile.entity.ein` | 39-3842347 |
| f4 | P1_Hdr_Biz | `Profile.F1065.A_bus_act` | 531110 |

### bookNS_BS.json → Form4562

| fid | logicalKey | UAS Path | Resolved Value |
|---|---|---|---|
| f69 | P3_L19h_b | `BS.placed_in_service_date` | 8/2025 |
| f70 | P3_L19h_c | `Acct.Fixed.Tangible.InService` | 437,950.81 ⚠️ includes land |
| f71 | P3_L19h_d | `Val.27.5` | 27.5 |
| f72 | P3_L19h_e | `Val.MM` | MM |
| f73 | P3_L19h_f | `Val.S/L` | S/L |

### bookNS_IS.json → Form4562

| fid | logicalKey | UAS Path | Resolved Value |
|---|---|---|---|
| f5 | P1_L1 | `Val.1,220,000` | 1,220,000 |
| f21 | P1_L12 | `Val.0` | 0 |
| f26 | P1_L17 | `Val.0` | 0 |
| f74 | P3_L19h_g | `Acct.Exp.Depreciation` | 5,246.06 ⚠️ see §6 |
| f153 | P4_L22 | `Acct.Exp.Depreciation` | 5,246.06 ⚠️ see §6 |

---

## 4. Implementation Notes — What Was Different From the Plan

### 4.1 Original Form4562.py Was Completely Broken

The pre-existing `Form4562.py` defined a `_buildFillDict()` that used a
logicalKey → fid reverse lookup (`lk_to_fid`).  But the namespace JSON had
**no logicalKeys set** on any field — all were blank.  So zero fields ever
matched and every FILL.pdf was empty.

Fix: replaced the entire class with the Form8825 pattern (`_FILL_MAP={}`,
`aid()` delegation) and added logicalKeys to the 60 relevant namespace fields.

### 4.2 bookNS fids Were Invented Strings, Not Real AcroForm IDs

The original `bookNS_*.json` Form4562 sections used invented fids like
`F_F4562_EntityName`, `F_F4562_19a_cost`, etc.  These strings do not match
any actual AcroForm field in the PDF.  The AcroForm uses sequential numeric
fids: `f2`, `f3`, `f69`, `f70`, etc.

Fix: replaced all Form4562 entries with correct numeric fids derived by
analyzing the XFA path names in `Form4562_namespace.json`.

### 4.3 Val.* — New UAS Prefix Pattern (Not in Original Plan)

MACRS constants (recovery period `27.5`, convention `MM`, method `S/L`) and
the §179 statutory limit ($1,220,000) are not in any ledger account.  The
original plan had no mechanism to inject literal strings.

Fix: added `Val.<literal>` support to both `stmtBS_Tax._resolve_acct` and
`stmtIS_Tax._resolve_acct`.  When an UAS path starts with `Val.`, the
resolver returns the substring after `Val.` verbatim.  This is now a first-class
UAS prefix alongside `Acct.*`, `BS.*`, `IS.*`, `Profile.*`.

### 4.4 propOwner Filter Fallback

The spec defined an in-service asset as:
```
Ledger == "Acct.Fixed.Tangible.InService"  AND  propOwner == {"LLC": 100}
```
But the actual `llcAssets_WBGroupLLC.json` records have `propOwner: None`
(the field has not been populated yet).

Fix: `_earliest_in_service_date()` tries the strict `{"LLC": 100}` filter first;
if that returns nothing, it falls back to any `Acct.Fixed.Tangible.InService` record.
This handles the current data without silently returning an empty date.

The propOwner field should be set to `{"LLC": 100}` on asset entry going forward
so future multi-property scenarios resolve correctly without the fallback.

### 4.5 namespace.json and FILL.pdf Are Gitignored — Live in Main Repo Only

`Form4562_namespace.json` and `Form4562_FILL.pdf` live in:
```
pages/AccountingData/2025/YE_Tax_Records/Forms_IRS/
```
This directory is gitignored.  Worktree branches do NOT contain these files.

Consequence: namespace edits must be applied directly to the main repo path.
When running `BookToIRS.regenerate()` from a worktree, the LLC object resolves
`TOP` via the GDrive symlink to the main repo — so bookNS JSON data is always
read from the main repo, not the worktree.  Python source code comes from the
worktree; JSON data comes from the main repo.

### 4.6 Building Basis in f70 Currently Includes Land

`Acct.Fixed.Tangible.InService` = $437,950.81 is the total cost of the property
(purchase price + closing costs).  It has not been split into building vs. land.
Land is not depreciable.  The basis entered in f70 is overstated until the land
split is applied (see §10).

---

## 5. placed_in_service_date Resolution

`stmtBS._earliest_in_service_date()` scans `llcAssets_<llcName>.json` for the
earliest `Acct.Fixed.Tangible.InService` record:

1. Try records where `propOwner == {"LLC": 100}` — preferred (multi-property safe).
2. Fall back to any InService record if the propOwner column is unpopulated.

The result is formatted as `M/YYYY` (e.g., `8/2025`).  The result is injected
into `taxAggregates()` as `placed_in_service_date` and cached on the instance.
The BS source resolver `_resolve_acct("BS.placed_in_service_date")` reads it from there.

---

## 6. Depreciation Amount — Safe Harbor vs. MACRS

⚠️ **Important**: The $5,246.06 currently in `Acct.Exp.Depreciation` is
**§1.263(a)-3 safe-harbor expensing** of pre-rental improvement costs, not a
MACRS 27.5-year schedule calculation.

| Item | Amount | Treatment |
|---|---|---|
| Safe-harbor expensed improvements | $5,246.06 | Form 8825 Line 14 ✓ |
| MACRS Year 1 estimate (4.5 months) | ~$5,972 | Form 4562 Part III Line 19h (g) — not yet booked |

The true MACRS first-year deduction for a building placed in service August 2025:
* Full year: $437,950 / 27.5 = $15,926 (gross, before land split)
* Mid-Month for August = 4.5 months: $15,926 × (4.5 / 12) = **$5,972**
* After land split (assuming ~20% land): depreciable basis ≈ $350,360 →
  Year 1 deduction ≈ **$4,779**

The $5,246.06 from safe-harbor is a reasonable proxy for testing but the CPA
must confirm which deduction method applies and whether MACRS should replace it.

---

## 7. Val.* Literal Path — UAS Protocol Extension

`Val.<literal>` is now a supported UAS prefix in `stmtBS_Tax` and `stmtIS_Tax`.

| Prefix | Resolver | Returns |
|---|---|---|
| `Val.<text>` | stmtBS_Tax, stmtIS_Tax | Literal string after `Val.` |
| `BS.<name>` | stmtBS_Tax | `taxAggregates()[name]` |
| `Acct.*` | stmtBS_Tax, stmtIS_Tax | `acct_balance(acct)` |
| `IS.<name>` | stmtIS_Tax | `taxAggregates()[name]` |
| `Profile.*` | stmtProfile | Profile JSON cell |

`Val.*` is appropriate for IRS statutory constants that change infrequently
(§179 dollar limit, MACRS life, convention codes).  It does NOT belong in
the GL or computed statement — use it only in bookNS mapping JSON.

---

## 8. Standard Mapping of Books to Form 4562 — Accounting Guidance

### 8.1 Data Source Mapping

| Source Document | Book Account (COA) | Form 4562 Destination |
|---|---|---|
| Balance Sheet | Fixed Assets: Buildings | Part III, Line 19h (c) — basis |
| Balance Sheet | Fixed Assets: Land | Exclude (not depreciable) |
| Balance Sheet | Fixed Assets: Improvements | Part III, Line 19h or Part II (Bonus) |
| General Ledger | Legal/Closing Costs | Capitalized into Asset Basis |
| General Ledger | Repair & Maintenance | Part I, Line 1 (if §179) or Form 8825 |
| Income Statement | Amortization Expense | Part VI, Line 42 |
| Income Statement | Depreciation Expense | Part III Line 19h (g) + Part IV Line 22 |

### 8.2 Workflow Steps

1. **Identify Assets**: Extract all entries from "Fixed Asset" accounts in the GL.
2. **Separate Land**: Identify the land portion (property tax assessment ratio).
   Critical: do not depreciate land.
3. **Placed in Service Date**: Use the date the property was ready for rent, not the
   purchase date.
4. **Categorize Life**: Residential = 27.5 yrs; appliances = 5 yrs;
   land improvements (fences/driveways) = 15 yrs.
5. **Calculate Basis**: Purchase Price + Closing Costs + Improvements − Land Value.

---

## 9. Expert Tips & Issues to Watch

* **"Placed in Service" Trap**: Depreciation cannot begin until the property is
  ready for rent, even if purchased earlier.
* **Mid-Month Convention**: IRS assumes mid-month entry regardless of actual
  closing date.
* **Repairs vs. Improvements**: Pre-rent repairs must be capitalized, not expensed
  on Form 8825.
* **§179 vs. Bonus**: §179 is generally unavailable for residential rental buildings.
  Bonus may apply to 5-year assets (appliances).
* **Safe Harbor Improvements**: §1.263(a)-3 safe-harbor amounts go on Form 8825,
  not Form 4562 Part III.  The current books carry $5,246.06 this way.

---

## 10. Dummy Form 4562: Year 1 Scenario

Scenario: $220k Purchase, includes $5k Improvements.
Assume Land Value is 20% ($44,000).  Depreciable Basis: $176,000.
Date Placed in Service: 10/01/Year 1.

### Part III: MACRS Depreciation (Section B)

| Line | (a) Classification | (b) Date | (c) Basis | (d) Period | (e) Conv | (f) Method | (g) Deduction |
|---|---|---|---|---|---|---|---|
| 19h | Residential Rental | 10/01/Y1 | $176,000 | 27.5 yrs | MM | S/L | $1,333 |

1. $176,000 / 27.5 = $6,400 full year.
2. October start (MM) = 2.5 months.
3. $6,400 × (2.5 / 12) = **$1,333**.

---

## 11. CPA Review Fields

Fields in `Form4562._CPA_NOTES` appear in the `🔍 Review` modal on the
IRS view toolbar.  They are never auto-filled by the pipeline.

* **P3_L19h_c** (f70 basis): land must be excluded — currently overstated; see §10.
* **P2_L14** (Line 14): bonus depreciation — CPA review for new property.
* **P3_L20c** (Line 20c): 5-year property (appliances) — bonus may apply.
* **P3_L20f** (Line 20f): 15-year property (land improvements — driveways, fences).
* **P6_L40** (Line 40): amortization of startup/org costs.

---

## 12. Future Task — Automatic Land Value Split

**Status**: Deferred.

f70 currently maps to `Acct.Fixed.Tangible.InService` = $437,950.81 (gross,
includes land).  Land is not depreciable and must be excluded from the basis.

**Planned enhancement**: Compute the land/building split from the county
property tax assessment ratio and store it as `BS.building_basis_net_land`.
Switch f70 mapping from `Acct.Fixed.Tangible.InService` to
`BS.building_basis_net_land`.

**Trigger**: After integrating Form 4562 ASIS books and confirming property tax
assessment data is accessible from the ledger.

---

## 13. Final Summary for W&B Group LLC (2025)

| Item | Value | Notes |
|---|---|---|
| Building cost (f70) | $437,950.81 | Includes land — CPA must split |
| Placed in service (f69) | 8/2025 | Earliest InService record |
| Recovery period (f71) | 27.5 yrs | Residential rental |
| Convention (f72) | MM | Mid-Month |
| Method (f73) | S/L | Straight-Line |
| Depreciation deduction (f74/f153) | $5,246.06 | Safe-harbor proxy — CPA confirm |
| §179 limit (f5) | $1,220,000 | 2025 statutory |
| §179 deduction (f21) | $0 | Not available for rental |

**Form 4562** → Line 22 ($5,246.06) → **Form 1065** Line 16a → **Form 8825** Line 14.
