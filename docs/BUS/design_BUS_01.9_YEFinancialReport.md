# YE Financial Report — Design & Best Practices
**File:** `docs/design_BUS_01.2.9_YEFinancialReport.md`
**Agent:** `YEFinancialReportAgent` → `ledger/yeFinancialReport.py`
**Output:** `books/{year}/Forms/WBGroupLLC_{year}_YEFinancialReport.pdf`

---

## 1. Purpose

The Year-End Financial Report (YEFR) is a professionally formatted PDF that consolidates
the LLC's full-year accounting activity into a single document suitable for:
- CPA / tax-preparer review before Form 1065 filing
- IRS audit support (substantiates Schedule L, Schedule M-2, K-1 Item L)
- Member distribution to partners per Operating Agreement

---

## 2. Report Template — Sections

### Cover Page
| Field | Source |
|---|---|
| Entity name | `llcProfile.entity.entity_name` |
| EIN | `llcProfile.entity.ein` |
| Address | `llcProfile.entity.address` |
| Tax year | `YYYY — January 1 through December 31` |
| Business activity | `llcProfile.entity.product` |
| Date prepared | `datetime.date.today()` |
| Accounting method | Cash (default) — confirm with CPA |
| Footer | "Prepared by llcRentalTracker v{version} — For Tax Review Only" |

---

### Section 1 — Financial Summary (Prose Narrative)
Plain-language summary auto-generated from live GL data. Paragraphs:

1. **Entity Overview** — LLC name, EIN, address, year of organization, business purpose,
   number of members, ownership percentages per Operating Agreement.
2. **Property Portfolio** — list each rental property (name, address, date placed in service,
   asset type, depreciable basis).
3. **Year in Review** — total gross rental income, total operating expenses, depreciation
   expense, net income/(loss), comparison note if prior-year data available.
4. **Cash Position** — ending cash balance, significant cash events (property acquisition,
   capital contributions).
5. **Depreciation Summary** — property, method, useful life, year-1 mid-month convention,
   annual deduction.
6. **Member Capital Summary** — each member's beginning capital, contributions, distributions,
   share of net income/(loss), ending capital.

---

### Section 2 — Balance Sheet
**As of December 31, {YEAR}**

```
ASSETS
  Current Assets
    Cash & Bank Accounts             $XXX,XXX
    Accounts Receivable (if any)     $      0
  Total Current Assets               $XXX,XXX

  Fixed Assets
    Land                             $XX,XXX
    Building (InService basis)       $XXX,XXX
    Less: Accumulated Depreciation  ($X,XXX)
    Assets Under Construction        $X,XXX
  Total Fixed Assets                 $XXX,XXX

TOTAL ASSETS                         $XXX,XXX

LIABILITIES
  Mortgage Payable                   $XXX,XXX
  Accounts Payable                   $    XXX
  Security Deposits Held             $      0
  Prepaid Rent Received              $      0
TOTAL LIABILITIES                    $XXX,XXX

MEMBERS' EQUITY
  [Member A] Capital Account         $XXX,XXX
  [Member B] Capital Account         $   X,XXX
  [Member C] Capital Account         $   X,XXX
  Retained Earnings (cumulative PnL) $    (XXX)
TOTAL MEMBERS' EQUITY                $XXX,XXX

TOTAL LIABILITIES + EQUITY           $XXX,XXX
——————————————————————————————————————————————
Note: Open-period accounting — BS gap = current-year Net Income/(Loss) ($XXX).
      Extended equation A = L + E + NI is balanced. See Section 3.
```

**Explanatory Notes (auto-generated):**
- Note 1: Accounting method (Cash basis)
- Note 2: Depreciation method (MACRS, 27.5yr residential, mid-month convention)
- Note 3: Asset valuation (historical cost, not market value)
- Note 4: Open-period equation explanation
- Note 5: Mortgage balance confirmation (if llcPayables has mortgage entries)

---

### Section 3 — Income Statement (Profit & Loss)
**For Year Ended December 31, {YEAR}**

```
RENTAL INCOME
  Gross Rental Revenue               $X,XXX
  Other Revenue (fees, interest)     $   XXX
TOTAL REVENUE                        $X,XXX

OPERATING EXPENSES
  Repairs & Maintenance              $  XXX
  Utilities (Electric, Water, etc.)  $  XXX
  Insurance                          $  XXX
  Property Taxes                     $  XXX
  HOA / Management Fees              $  XXX
  Legal & Professional Fees          $    0
  Advertising                        $    0
  Other Operating Expenses           $  XXX
  Depreciation & Amortization        $X,XXX
TOTAL EXPENSES                       $X,XXX

NET INCOME / (LOSS)                  $(XXX)

PER-MEMBER ALLOCATION
  [Member A] (96%)                   $(XXX)
  [Member B] (2%)                    $ (XX)
  [Member C] (2%)                    $ (XX)
```

**Explanatory Notes:**
- Note 1: Depreciation ($X,XXX) per IRS MACRS Schedule (see Section 4)
- Note 2: All rental expenses are ordinary and necessary under IRC §162 / §212
- Note 3: Net loss is a passive activity loss per IRC §469 — deductible against
  passive income; excess carries forward

---

### Section 4 — Depreciation Schedule
Per-property depreciation detail for Form 4562 cross-reference:

| Property | Placed In Service | Asset Type | Depreciable Basis | Method | Life | 1st-Year Deduction |
|---|---|---|---|---|---|---|
| 805 High Mesa | 2025-08-20 | Residential | $139,563 | MACRS | 27.5yr | $1,903 |

---

### Section 5 — Member Capital Account Analysis
Per-member capital tracking for Schedule K-1 Item L:

| | Member A (96%) | Member B (2%) | Member C (2%) | Total |
|---|---|---|---|---|
| (a) Beginning capital | $0 | $0 | $0 | $0 |
| (b) Contributions | $XXX | $0 | $0 | $XXX |
| (c) Net income/(loss) share | $(XXX) | $(XX) | $(XX) | $(XXX) |
| (d) Other increases | $0 | $0 | $0 | $0 |
| (e) Withdrawals/Distributions | $0 | $0 | $0 | $0 |
| **(f) Ending capital** | **$XXX** | **$XX** | **$XX** | **$XXX** |

---

### Section 6 — Outstanding Items & CPA Notes
Auto-flagged items that require accountant or IRS attention before filing:

| # | Flag | Detail | Action Required |
|---|---|---|---|
| 1 | Mortgage balance | No mortgage liability recorded in llcPayables | Confirm purchase was cash; add mortgage if financed |
| 2 | Security deposits | No security deposit liability | Confirm deposits held or not applicable |
| 3 | Accounting method | No Form 1065 Line F election recorded in profile | Confirm Cash or Accrual with CPA |
| 4 | Operating Agreement | Profit/loss % must match filed Operating Agreement | Verify 96/2/2 split with attorney |
| 5 | Passive activity | Members likely non-material-participants | Confirm passive loss treatment; carries forward |
| 6 | First-year short period | LLC formed Aug 2025; prorated depreciation applied | Verify mid-month convention calculation |
| 7 | County tax proration | $1,661 closing credit classified as InService basis reduction | CPA should verify classification |
| 8 | HOA transfer fee | $135 expensed at closing | Verify current expense vs. capital cost |

---

## 3. PDF Generation — Implementation

**Library:** `reportlab` (v4+ already in environment)

**File location:** `books/{year}/Forms/{dataName}_{year}_YEFinancialReport.pdf`

**Class:** `YEFinancialReportAgent` in `ledger/yeFinancialReport.py`

**Constructor inputs:**
```python
agent = YEFinancialReportAgent(eSession)
path  = agent.generate()   # returns Path to output PDF
```

**Data sources (all from live GL — no stale cache):**
- `llcProfile` → entity metadata, members
- `GLAuditor.equation_summary()` → A/L/E/NI
- `stmtBS_View.view()` → balance sheet rows
- `stmtIS_View.view()` → income statement rows
- `llcOwners` → member percentages
- `llcAssets` (filtered by year) → properties + depreciation records
- `setup_paths.IRS_FORMS_DIR` → output directory

**Report style:**
- Font: Helvetica (no external font dependency)
- Colors: #1e3a8a (header), #374151 (body), #dc2626 (negative amounts)
- Page size: US Letter (8.5" × 11")
- Margins: 0.75" all sides

---

## 4. Outstanding Questions for Accountant / IRS

The following must be resolved before Form 1065 is filed:

### A — Accounting Elections
- [X] **Form 1065 Line F**: Cash or accrual? (Cash is standard for small rental LLCs)
- [X] **Tax year**: Confirm calendar year (Jan 1 – Dec 31) — partnerships generally required
- [X] **First-year return**: Is this a short-period return (Aug–Dec 2025) or full year?

### B — Balance Sheet Reconciliation (Schedule L)
- [Cash] **Mortgage payable**: Is the property mortgaged? If yes, principal balance as of 12/31/2025 must be on Schedule L. If cash purchase, confirm.
- [None] **Security deposits**: Are tenant security deposits held? Must classify as Liability.
- [None] **Partner loans**: Has any member loaned money to the LLC? Must show on Schedule L.

### C — Income & Deductions
- [ ] **Passive activity rule (IRC §469)**: Rental activity is passive by default. Members cannot deduct losses unless they have offsetting passive income or meet material participation tests.
- [Seller Credit] **County tax proration ($1,661)**: Was this a seller credit reducing basis, or a current-year expense? Affects depreciation calculation.
- [ok] **Repairs vs. improvements**: Verify all repairs/construction charges ($2,651) qualify under IRC §162; none should be capitalized improvements under §263.
- [no] **De minimis safe harbor**: Are any expensed items over $2,500? If so, capitalize per IRS Reg. §1.263(a)-1(f).

### D — Partner / Member Issues
- [x] **Operating Agreement**: Must be on file. Profit/loss allocation percentages must match K-1s.
- [x] **Outside basis tracking**: Each member needs their outside basis calculated at year-end (contributions + share of income – distributions – share of losses).
- [only member manager] **At-risk rules (IRC §465)**: Members can only deduct losses to the extent they are at-risk. Confirm each member's at-risk amount.
- [x] **K-1 delivery**: Schedule K-1 must be delivered to each member by the Form 1065 due date (March 15 or extension).

### E — Property & Depreciation
- [x] **Form 4562**: Annual depreciation deduction must be reported on Form 4562. Verify $1,903 matches MACRS calculation.
- [yes] **Land segregation**: Was land value ($79,438) determined by tax assessor ratio or appraisal? Document the method.
- [no] **Bonus depreciation (§168(k))**: Did LLC elect out? Residential rental is ineligible for bonus depreciation.
- [no] **Cost segregation study**: For a $140k building, a cost segregation study is unlikely to be cost-effective, but confirm with CPA.

---

## RV Rental Asset — IRS Treatment & Report Guidance

### Context
The LLC holds an RV (propNm = `RV_RV1`) that is being prepared for short-term rental income.
As of December 31, 2025 the asset has never been placed in service and is still carried as
`Acct.Fixed.Tangible.InConstruction`. The LLC has also expensed $1,075.11 in supply and
repair costs against this propNm.

**Current ledger balances for RV_RV1:**
| Account | Balance | Treatment |
|---|---|---|
| `Acct.Fixed.Tangible.InConstruction` | +$987.13 Dr | Capitalized pre-service costs |
| `Acct.Exp.Other` + `Acct.Exp.Repair` | +$1,075.11 Dr | Expensed repairs/supplies |

---

### 1. Asset Classification — Personal Property, Not Real Property
An RV held for rental to guests is **personal property** (IRC §1245), NOT real property
(IRC §1250). This distinction controls:
- Depreciation life and method (5-year MACRS vs. 27.5-year residential)
- Whether bonus depreciation is available (yes for personal property in 2025)
- IRS Form 4562 classification (Part II — MACRS, 5-year, vs. Part III — residential)
- Whether the rental activity is passive (depends on average rental period)

---

### 2. Depreciation — When Placed in Service (5-Year MACRS)
The RV is NOT depreciable until it is **placed in service** — the date it is first available
for rental in a rentable condition. No depreciation may be claimed while InConstruction.

**When placed in service, apply:**

| Rule | Detail |
|---|---|
| MACRS asset class | 00.22 (Automobiles/Taxis) or 57.0 (Distributive trades) → **5-year property** |
| Method | 200% declining balance (if >50% business use) |
| Convention | Half-year convention (or mid-quarter if >40% of assets placed in Q4) |
| Year-1 rate | 20% × 200% DB = 40% (before half-year convention) → **20%** first year |
| Bonus depreciation | **60% first-year bonus** available in 2025 for 5-year personal property (TCJA phase-out schedule) |
| Listed property (§280F) | RVs > 6,000 lbs GVWR are generally NOT subject to §280F luxury caps, but business-use percentage **must be documented** |

**Example (if placed in service in 2026):**
- Capitalized basis at service date: ~$987 + any additional capitalized costs
- 60% bonus depr. (if available in 2026) + regular MACRS on remainder

---

### 3. Rental Activity Type — Passive vs. Active (Critical for Loss Deduction)
The IRS treatment of rental income/loss from an RV depends on the **average rental period**:

| Avg. Rental Period | IRC Rule | Activity Type | Loss Treatment |
|---|---|---|---|
| **≤ 7 days** | IRC §469(j)(8)(A) | **NOT a rental activity** — treated as active business | Losses offset active income; not subject to passive rules |
| **8–30 days + substantial services** | IRC §469(c)(2) | Active business (hotel-like) | Schedule C equivalent; not passive |
| **> 30 days** | Default rental rule | **Passive activity** | Loss carries forward; deductible only against passive income or on sale |

**Recommendation:** Short-term RV rentals (VRBO, RV rentals platforms) typically average
≤7 days per rental. If this LLC rents the RV for average periods ≤7 days, the activity is
**NOT passive** — losses can offset ordinary income immediately. The CPA must confirm the
rental period pattern before filing.

---

### 4. Expenses Booked Before In-Service Date
The $1,075.11 in `Acct.Exp.Other` and `Acct.Exp.Repair` for RV_RV1 was expensed in 2025.
**IRS rule:** Expenses incurred to bring an asset to its intended use BEFORE it is placed
in service must be **capitalized** to the asset basis, not deducted currently
(IRS Reg. §1.263(a)-1; UNICAP rules §263A for certain taxpayers).

**Analysis of the $1,075.11:**
- Lowe's, ACE Hardware, Harbor Freight → likely fit-out/preparation supplies → **capitalize**
- Amazon parts → preparation or maintenance → **capitalize** if pre-service
- H-E-B ($108) → consumables/supplies → borderline; **capitalize** if directly related to
  placing the RV in rentable condition

**Recommendation:** CPA should reclassify the $1,075.11 from `Acct.Exp.*` to
`Acct.Fixed.Tangible.InConstruction` (increasing the basis to ~$2,062) before filing.
This increases the depreciable basis when eventually placed in service.

---

### 5. Separate Activity Grouping
The RV rental and the house rental (H_805HighMesa) are likely **separate activities**
under Temp. Reg. §1.469-4T unless a grouping election is made. Separate activity treatment means:
- Losses from one cannot offset income from the other (before netting)
- Material participation is tested separately for each activity
- If the RV is a non-passive activity (avg rental ≤7 days), the grouping question is moot for
  loss purposes but affects how income is reported on Schedule K-1

---

### 6. Required Documentation for IRS
| Document | Purpose |
|---|---|
| RV purchase contract / title | Establishes cost basis and acquisition date |
| Date-first-available-for-rent record | Establishes in-service date for depreciation |
| Rental agreement / platform records (VRBO, etc.) | Documents average rental period for activity classification |
| Business use log | Required if GVWR ≤ 6,000 lbs (listed property §280F) |
| Receipts for all $2,062 in costs | Supports capitalized basis |

---

### 7. Report Template Changes for RV / InConstruction Assets

#### Section 1 — Property Portfolio (fix)
Split into two paragraphs:
1. **Active Rental Properties** (InService): "The LLC held the following rental properties..."
2. **Assets Under Development** (InConstruction): "The following assets are in preparation
   and have not yet been placed in service as of December 31, {year}. No depreciation has
   been taken. These assets will be placed in service when available for rental use."

#### Section 3 — Income Statement (fix)
Add a **Per-Property Expense Summary** table that attributes expenses by `propNm`:
- Shows that $1,075.11 relates to RV_RV1 (pre-service costs)
- Shows that house expenses relate to H_805HighMesa

#### Section 4 — Depreciation (fix)
Add a second sub-table **"Assets Not Yet In Service"** listing InConstruction assets with:
- propNm, description, capitalized basis, date first cost incurred
- Note: "No depreciation — not yet placed in service"

#### Section 6 — CPA Flags (additions)
Add RV-specific flags:
| Flag | Action |
|---|---|
| RV not yet in service | Document in-service date when ready for rental |
| $1,075.11 expensed pre-service | CPA should reclassify to InConstruction basis |
| Activity type unknown | Determine average rental period to classify as passive vs. active |
| Listed property check | Confirm GVWR > 6,000 lbs to avoid §280F luxury limits |
| Bonus depreciation election | Decide whether to take 60% bonus in year placed in service |
| Separate activity grouping | CPA advise on grouping election with H_805HighMesa |

---

### 8. Code Bugs in YEFinancialReportAgent (to fix)

**Bug 1 — `_prop_list()` scans only `self._assets` (llcAssets)**
The RV InConstruction entries ARE in llcAssets so the propNm appears, but expenses
(in llcExpRev with propNm=RV_RV1) are not loaded, causing:
- The prose says "rental properties" but the RV is not in service
- No per-property expense attribution possible

**Fix:** Load all source DBs for propNm discovery; classify each propNm by its account types.

**Bug 2 — No distinction between InService and InConstruction in Section 1**
`_prop_list()` returns a flat list with no asset-state information. The prose says
"LLC held the following rental properties" — incorrect for InConstruction assets.

**Fix:** `_prop_list()` returns two lists: `active` (InService accounts) and
`construction` (InConstruction-only). Section 1 prose uses separate paragraphs.

**Bug 3 — Section 4 Depreciation shows "No depreciation posted" when InConstruction exists**
When no `_is_depr` record exists (RV not yet in service), the depreciation section is blank.
It should show the InConstruction assets as a "not yet in service" sub-table.

**Fix:** Add a second table in Section 4 for InConstruction assets.

**Change summary — `ledger/yeFinancialReport.py`:**
| Method | Change |
|---|---|
| `_load_all_sources()` | NEW — loads llcAssets + llcExpRev records into combined list |
| `_prop_list()` | Returns `{active: [...], construction: [...]}` dict, scans all GL records |
| `_section1_summary()` | Two paragraphs: active properties + assets under development |
| `_prop_expense_summary()` | NEW — per-propNm expense breakdown from GL |
| `_section4_depreciation()` | Adds InConstruction sub-table with "no depreciation" note |
| `_section6_flags()` | Dynamic RV/InConstruction flags added |
