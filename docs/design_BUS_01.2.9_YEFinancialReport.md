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
- [ ] **Form 1065 Line F**: Cash or accrual? (Cash is standard for small rental LLCs)
- [ ] **Tax year**: Confirm calendar year (Jan 1 – Dec 31) — partnerships generally required
- [ ] **First-year return**: Is this a short-period return (Aug–Dec 2025) or full year?

### B — Balance Sheet Reconciliation (Schedule L)
- [ ] **Mortgage payable**: Is the property mortgaged? If yes, principal balance as of 12/31/2025 must be on Schedule L. If cash purchase, confirm.
- [ ] **Security deposits**: Are tenant security deposits held? Must classify as Liability.
- [ ] **Partner loans**: Has any member loaned money to the LLC? Must show on Schedule L.

### C — Income & Deductions
- [ ] **Passive activity rule (IRC §469)**: Rental activity is passive by default. Members cannot deduct losses unless they have offsetting passive income or meet material participation tests.
- [ ] **County tax proration ($1,661)**: Was this a seller credit reducing basis, or a current-year expense? Affects depreciation calculation.
- [ ] **Repairs vs. improvements**: Verify all repairs/construction charges ($2,651) qualify under IRC §162; none should be capitalized improvements under §263.
- [ ] **De minimis safe harbor**: Are any expensed items over $2,500? If so, capitalize per IRS Reg. §1.263(a)-1(f).

### D — Partner / Member Issues
- [ ] **Operating Agreement**: Must be on file. Profit/loss allocation percentages must match K-1s.
- [ ] **Outside basis tracking**: Each member needs their outside basis calculated at year-end (contributions + share of income – distributions – share of losses).
- [ ] **At-risk rules (IRC §465)**: Members can only deduct losses to the extent they are at-risk. Confirm each member's at-risk amount.
- [ ] **K-1 delivery**: Schedule K-1 must be delivered to each member by the Form 1065 due date (March 15 or extension).

### E — Property & Depreciation
- [ ] **Form 4562**: Annual depreciation deduction must be reported on Form 4562. Verify $1,903 matches MACRS calculation.
- [ ] **Land segregation**: Was land value ($79,438) determined by tax assessor ratio or appraisal? Document the method.
- [ ] **Bonus depreciation (§168(k))**: Did LLC elect out? Residential rental is ineligible for bonus depreciation.
- [ ] **Cost segregation study**: For a $140k building, a cost segregation study is unlikely to be cost-effective, but confirm with CPA.
