# Release v0.4 Summary

**Branch:** `release/v0.4`
**Released:** 2026-05-12
**Baseline:** `release/v0.3`

---

## Overview

v0.4 completes the IRS tax form output pipeline, adds per-partner Schedule K-1 PDF generation, introduces the BookToIRS Aid dialog enhancements, and improves Income Statement property-level views.

---

## Features

### IRS Form 4562 — Depreciation & Amortization
- `irs.Form4562` BookToIRS pipeline: maps GL depreciation accounts to IRS Part lines
- Flask UI view for Form 4562 with Review modal showing Part disposition and depreciation reconciliation
- `design_IRS_Form4562.md`: documented De Minimis Safe Harbor, §179 exclusion, and MACRS treatment

### Schedule K-1 — Per-Partner PDF Pipeline
- Per-partner K-1 PDF generation pipeline (`F1065_K1/`)
- Member selector on IRS views to target individual partner K-1 output
- Namespace PDF button on all IRS views for direct PDF population

### BookToIRS Aid Dialog Enhancements
- Full UAS (Unified Account Schema) universe exposed in the Aid dialog
- `Profile.Form8825` as source for Form 8825 field mapping
- Edit and delete support for `IS.BookVal` literals directly in the Aid dialog
- Auto-open literal panel on entry; corrected `IS.BookVal.{key}` path generation
- `apiFlow_BookToIRS.mmdc`: sequence diagram for the BookToIRS regeneration pipeline

### Income Statement — Property Views
- `IS ByProperty`: unstacked `propNm` into column headers for side-by-side property comparison
- `IS ByPropertyDetails`: corrected sort key lambda precedence error; removed per-account subtotals
- `IS PerMemberDetails` view: per-member income allocation breakdown
- Rental / Ordinary income split in IS views
- SubTotal row for Depreciation Expense in `ByProperty` view

### Form 8825
- Dynamic per-property IS fill dict; repaired account name resolution bug
- Corrected line bases and added missing accounts in fill dict
- Fixed F091 merge and subtotals; corrected net income sign and formatting

---

## Bug Fixes

| Area | Fix |
|---|---|
| BS view | Clear `_stmt` cache on `load()` — was not refreshing after data edits |
| IS / GL view | Always rebuild stmt from live GL on `load()` — stale cache after edits |
| Aid dialog | Full UAS universe in picker (was partial); corrected value labels |
| IS ByPropertyDetails | Sort key ternary lambda precedence error caused incorrect ordering |
| Form 8825 | Dynamic per-property fill dict; missing accounts and incorrect line bases |

---

## Housekeeping

- Removed tracked Finder duplicate `Readme_Form1065-v1 2.md`
- Updated `CLAUDE.md`: added session-end merge rule and test-before-merge requirement
- Fixed Mermaid parse errors in `apiFlow_BookToIRS.mmdc` (semicolons and quotes in arrow labels)

---

## Test Status

All three test suites pass on `release/v0.4`:

```
v0.3 stmtGL test suite — PASS  (10/10)
v0.3 stmtBS test suite — PASS  (10/10)
v0.3 stmtIS test suite — PASS  (10/10)
```
