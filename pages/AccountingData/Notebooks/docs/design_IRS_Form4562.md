# Design for BookToIRS — IRS Form 4562 (Depreciation and Amortization)

## 1. Overview

Form 4562 reports all depreciation and amortization deductions for the LLC.
For W&B Group (residential rental, hold-to-rent) the operative section is
**Part III Line 19h** — 27.5-year MACRS, Mid-Month convention, Straight-Line method.
Line 22 (total depreciation) flows into Form 1065 Line 16a, and Form 8825 Line 14
receives the same figure.

---

## 2. irs.Form4562 — Data & View Handling

### Architecture

`Form4562` is a thin subclass of `irsForm`, following the same pattern as `Form8825`.
It delegates all fill pipeline work to `BookToIRS` via `aid()`.  No `_FILL_MAP` is
used; per-fid values are driven entirely by the `bookNS_<src>.json` mapping tables.

```
bookNS_Profile.json  [Form4562]  →  stmtProfile.loadFillDict("Form4562")
bookNS_BS.json       [Form4562]  →  stmtBS_Tax.loadFillDict("Form4562")
bookNS_IS.json       [Form4562]  →  stmtIS_Tax.loadFillDict("Form4562")
         ↓
BookToIRS.regenerate()           →  Form4562_FILL.pdf
         ↓
ui.llcForm4562 (irs_pdf_view.html + stat chips)
```

### Key Files

| File | Role |
|---|---|
| `irs/Form4562.py` | irsForm subclass — `aid()`, `LOCATION_RULES`, `_CPA_NOTES` |
| `ui/llcForm4562.py` | Flask view wrapper — `pdf_path()`, `stats()`, `meta()` |
| `2025/bookNS_Profile.json` | Entity name / EIN / business activity fid mappings |
| `2025/bookNS_BS.json` | Placed-in-service date / building cost / MACRS constants |
| `2025/bookNS_IS.json` | §179 limit / deduction / current-year depreciation |
| `2025/YE_Tax_Records/Forms_IRS/Form4562_namespace.json` | AcroForm field catalog (323 fields, 60 with logicalKeys) |
| `2025/YE_Tax_Records/Forms_IRS/Form4562_FILL.pdf` | Pipeline output (gitignored) |

---

## 3. Field Mapping Table

### bookNS_Profile.json → Form4562

| fid | logicalKey | UAS Path | Description |
|---|---|---|---|
| f2 | P1_Hdr_Nm | Profile.entity.entity_name | LLC name |
| f3 | P1_Hdr_EIN | Profile.entity.ein | EIN |
| f4 | P1_Hdr_Biz | Profile.F1065.A_bus_act | Business activity code |

### bookNS_BS.json → Form4562

| fid | logicalKey | UAS Path | Description |
|---|---|---|---|
| f69 | P3_L19h_b | BS.placed_in_service_date | Date placed in service (M/YYYY) |
| f70 | P3_L19h_c | Acct.Fixed.Tangible.InService | Basis for depreciation (building cost) |
| f71 | P3_L19h_d | Val.27.5 | Recovery period — 27.5 yrs residential |
| f72 | P3_L19h_e | Val.MM | Convention — Mid-Month |
| f73 | P3_L19h_f | Val.S/L | Method — Straight-Line |

### bookNS_IS.json → Form4562

| fid | logicalKey | UAS Path | Description |
|---|---|---|---|
| f5 | P1_L1 | Val.1,220,000 | §179 dollar limit (2025 statutory) |
| f21 | P1_L12 | Val.0 | §179 deduction (rental property: $0) |
| f26 | P1_L17 | Val.0 | Prior-year MACRS carryover |
| f74 | P3_L19h_g | Acct.Exp.Depreciation | Current-year depreciation deduction |
| f153 | P4_L22 | Acct.Exp.Depreciation | Line 22 total → Form 1065 Line 16a |

---

## 4. placed_in_service_date Resolution

`stmtBS._earliest_in_service_date()` scans `llcAssets_<llcName>.json` for the
earliest record matching `Ledger == "Acct.Fixed.Tangible.InService"`.  It prefers
records with `propOwner == {"LLC": 100}` but falls back to any InService record
when the propOwner field has not yet been set.

The result is formatted as `M/YYYY` (e.g. `8/2025`) which IRS AcroForm field f69
accepts for the "month/year placed in service" column.

---

## 5. Val.* Literal Path Support

Both `stmtBS_Tax._resolve_acct` and `stmtIS_Tax._resolve_acct` support the
`Val.<literal>` prefix: they return the substring after `Val.` verbatim.
This lets the bookNS JSON inject IRS statutory constants (§179 limit, recovery
period, convention, method) without requiring a ledger source.

---

## 6. Standard Mapping of Books to Form 4562 — Accounting Guidance

### 6.1 Data Source Mapping

| Source Document | Book Account (COA) | Form 4562 Destination |
|---|---|---|
| Balance Sheet | Fixed Assets: Buildings | Part III, Line 19h (c) — basis |
| Balance Sheet | Fixed Assets: Land | Exclude (land is not depreciable) |
| Balance Sheet | Fixed Assets: Improvements | Part III, Line 19h or Part II (Bonus) |
| General Ledger | Legal/Closing Costs | Capitalized into Asset Basis |
| General Ledger | Repair & Maintenance | Part I, Line 1 (if Section 179) or 8825 |
| Income Statement | Amortization Expense | Part VI, Line 42 |
| Income Statement | Depreciation Expense | Part III Line 19h (g) + Part IV Line 22 |

### 6.2 Workflow Steps

1. **Identify Assets**: Extract all entries from "Fixed Asset" accounts in the GL.
2. **Separate Land**: Identify the land portion from the purchase price (property tax
   assessment ratio).  Critical: do not depreciate land.
3. **Placed in Service Date**: Use the date the property was ready and available for
   rent, not the purchase date.
4. **Categorize Life**: Residential = 27.5 years; appliances = 5 years;
   land improvements (fences/driveways) = 15 years.
5. **Calculate Basis**: Purchase Price + Closing Costs + Improvements − Land Value.

---

## 7. Expert Tips & Issues to Watch

* **"Placed in Service" Trap**: If renovations ran past the purchase date, depreciation
  cannot begin until the property was ready for rent.
* **Mid-Month Convention**: For residential property the IRS assumes mid-month entry
  regardless of the actual closing date.
* **Repairs vs. Improvements**: Pre-rent repairs must be capitalized; they cannot be
  expensed on Form 8825.
* **Section 179 vs. Bonus**: §179 is generally unavailable for residential rental
  buildings; Bonus Depreciation may apply to 5-year assets (appliances).
* **Safe Harbor Improvements**: Amounts expensed under §1.263(a)-3 safe harbor appear
  on Form 8825, not Form 4562 Part III.  The current `Acct.Fixed.Depreciation.Accum`
  balance ($5,246.06) reflects safe-harbor expensing, not MACRS.

---

## 8. Dummy Form 4562: Year 1 Scenario

Scenario: $220k Purchase, includes $5k Improvements.
Assume Land Value is 20% ($44,000).

* Depreciable Basis: $220,000 − $44,000 = $176,000.
* Date Placed in Service: 10/01/Year 1.

### Part III: MACRS Depreciation (Section B)

| Line | (a) Classification | (b) Date | (c) Basis | (d) Period | (e) Conv | (f) Method | (g) Deduction |
|---|---|---|---|---|---|---|---|
| 19h | Residential Rental | 10/01/Y1 | $176,000 | 27.5 yrs | MM | S/L | $1,333 |

How the math works:
1. $176,000 / 27.5 years = $6,400 (full year).
2. Mid-Month Convention for October start = 2.5 months.
3. ($6,400 / 12) × 2.5 = $1,333.33.

---

## 9. CPA Review Fields

Fields in `Form4562._CPA_NOTES` are surfaced in the **Review** modal
(toolbar button `🔍 Review` on the irs_pdf_view.html page).  These are
never auto-filled by the BookToIRS pipeline.  Key advisory fields:

* **P3_L19h_c** (f70 basis): Land value must be excluded before entry.
  Auto land-split is a **planned future enhancement** (see §10).
* **P2_L14** (Line 14): Special depreciation allowance / bonus — CPA review.
* **P3_L20c** (Line 20c): 5-year property (appliances) — bonus may apply.
* **P3_L20f** (Line 20f): 15-year property (land improvements).

---

## 10. Future Task — Automatic Land Value Split

**Status**: Deferred.

The building-cost basis entered in f70 currently equals `Acct.Fixed.Tangible.InService`
(the full purchase price including land).  Land is not depreciable and must be excluded.

**Planned enhancement**: Automatically compute the land/building split using the
county property tax assessment ratio (land assessed value ÷ total assessed value)
and store the result as a new ledger aggregate `BS.building_basis_net_land`.  The
f70 mapping in `bookNS_BS.json` would then switch from `Acct.Fixed.Tangible.InService`
to `BS.building_basis_net_land`.

**Trigger**: After integrating Form 4562 ASIS books and confirming the property tax
assessment data is accessible from the ledger.

Until then, the CPA Advisory note on f70 prompts manual review.

---

## 11. Final Summary for W&B Group LLC

* **Form 4562**: Reports the current-year MACRS depreciation (Part III Line 19h,
  Line 22).
* **Form 8825**: The Line 22 figure flows to Line 14 (Depreciation).
* **Form 1065**: Line 22 flows to Line 16a.
* **Land Value**: Ensure the General Ledger shows a separate `Acct.Fixed.Land`
  account so it is not accidentally included in the depreciable basis.
