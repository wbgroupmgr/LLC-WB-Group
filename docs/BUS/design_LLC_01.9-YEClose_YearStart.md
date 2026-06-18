# YE Close & YearStart — Implementation Design
**Stage:** 01.9 — Year-End & New-Year Workflow  
**Namespace:** LLC (App implementation)  
**Accounting spec:** `docs/BUS/design_BUS_01.9_YEClosing.md` (authoritative for accounting rules and Phase numbering)  
**Issue:** #35

---

## 1. Architecture Context

### 1.1 Single-DB Decision (already in production)

The business `Books` are located in `books/Accts/*.json` and use a **shared, all-years ledger** — so there are no per-year Accts directories.  The config service `setup_paths.py` sets `ACCTS_DIR = books / "Accts"` regardless of the active year.

Consequence: temporary accounts (Revenue 4xxx, Expense 5xxx) do **not** need to be explicitly
zeroed in the database. 

#### 1.1.1 Per Year DB's

When the active year is set to 2026, all GL queries filter `dt` to
`2026-*` records — income and expense rows for 2026 start at $0 automatically. 

The openning balance is based on the previous Fiscal Financial Report 
- Section 1, Financial Summary: 'Cash Position'
- Section 5, Member Capital - `Ending Capital`
- YearStart
    - `Acct.Exp.Depreciation` must start fiscal year zero'd out — **Answer:** Handled automatically by the year filter on stmtIS. The 2025 depreciation entry is dated `2025.12.31`; when stmtIS filters IS accounts (4xxx/5xxx) to `dt` starting with `2026.`, that entry is excluded. No explicit zeroing entry is needed or correct. The year filter implementation is the blocking code task.
    - `Acct.Equity.Earnings.PnL` must start year zero'd out — **Answer:** PnL (3100) is a permanent equity account — its balance carries forward. The "zero at year start" is conceptual: the YE closing entries transfer NI into Owner.Capital.Funds (Dr PnL / Cr Capital for profit), so the running PnL balance reflects cumulative allocations. The 2026 stmtIS starts at $0 NI because the year filter excludes 2025 IS entries — not because PnL is zeroed in the DB. The 2025 YE close posted the wrong direction (Credit for a profitable year); that data bug is fixed in BUS repo commit `9ed301e`.

No opening balance entries are needed for permanent accounts either; balances carry forward as the running
sum of all prior transactions.


`books/<year>/` directories hold only **filed documents** (not accounting records):
```
books/
  Accts/                    ← shared all-years GL (current)
    llcAssets_WBGroupLLC.json
    llcExpRev_WBGroupLLC.json
    llcPayables_WBGroupLLC.json
    llcReceivables_WBGroupLLC.json
    llcOwners_WBGroupLLC.json
    ChartOfAccounts_WBGroupLLC.json
  2025/
    Forms/                  ← IRS PDFs, YEFinancialReport.pdf
    BankStmts/              ← bank CSV imports
    YE_Tax_Records/         ← assembled IRS submission package
  2026/
    Forms/                  ← created during YearStart
    BankStmts/              ← created during YearStart
```

### 1.2 Open-Period Accounting (by design)

This system is intentionally **open-period**: revenue and expense accounts are never zeroed
in the DB. The BS will always show `equation_diff = NI` for the active year. `BSAuditAgent`
confirms this is correct — verdict `open_period_ni` means GL is balanced under `A = L + E + NI`.
"Balanced" verdict (zero gap) is only seen post-close in a traditional closed-period system —
not applicable here.

### 1.3 YE Closing Entries — What They Are Here

The **only** closing entries that need to be posted are:
- **Retained Earnings (RE) allocation**: Debit/Credit `Acct.Equity.Earnings.PnL` (3100) with
  net income split per member ownership percentages — one record per member tagged with `acctOwner=oID`.

These are appended to `books/Accts/llcAssets_WBGroupLLC.json` as permanent equity records
dated `YYYY-12-31`. They do NOT zero out revenue/expense accounts (that is handled by the
year filter). They DO adjust each member's capital balance in the BS.

---

## 2. Current Implementation State

| Component | Status | Gap |
|---|---|---|
| YE RE posting (single entry to 3100) | ✅ In production | Missing `acctOwner` per member |
| Per-member RE split (acctOwner field) | ❌ Not implemented | Phase 2, Gap 2 |
| BSAuditAgent | ✅ In BS view Actions menu | Already in production |
| books/Accts single-DB migration | ✅ Done | None |
| books/2026/ directory | ✅ BankStmts/ exists | Forms/ not yet created |
| Year switcher in config.json | Partial | `years: [2025]` only; 2026 not added |
| Period lock (prevent prior-year edits) | ❌ Not implemented | Phase 3 |
| YearStart UI action | ❌ Not implemented | New feature |
| YE Close dialog in IRS Submission view | ❌ Not implemented | New feature |

---

## 3. YE Close Workflow (UI — IRS Submission View)

### 3.1 Entry Point

YE Close is a special-purpose action. It lives in the **IRS Submission View** (`/view/tax_prep`),
not in routine accounting views, because it is a once-per-year operator action performed after
all transactions are reconciled and IRS forms are reviewed.

Location: `tax_prep.html` → Actions card → **"📅 YE Close — {YEAR}"** button  
Trigger: Only shown when active year = tax year in review (i.e., year has not been closed yet).

### 3.2 Pre-Close Checklist (shown in dialog before Apply)

The dialog opens a pre-close checklist that must all be green before Apply is enabled:

| # | Check | Source |
|---|---|---|
| C1 | All bank statements reconciled | Manual confirm checkbox |
| C2 | BSAuditAgent verdict = `open_period_ni` or `balanced` | Auto: calls `/api/bs/audit` |
| C3 | YE Financial Report generated | Auto: checks Forms/ for YEFinancialReport.pdf |
| C4 | Form 1065 FILL.pdf generated | Auto: checks IRS_Submission dir |
| C5 | All K-1s generated and delivered | Auto: checks per-member PDFs |
| C6 | Net Income figure confirmed (shown from live IS) | Displayed — operator confirms |

### 3.3 YE Close Steps (on Apply)

**Step 1 — Preview closing entries**  
Compute net income from `stmtIS` (live GL, filtered to YEAR). Show a preview table:

| Entry | Acct | acctOwner | Amount | Direction |
|---|---|---|---|---|
| RE allocation | Acct.Equity.Earnings.PnL | o20250801_1 (96%) | $NNN | Dr (loss) / Cr (income) |
| RE allocation | Acct.Equity.Earnings.PnL | o20250801_2 (2%) | $NN | Dr / Cr |
| RE allocation | Acct.Equity.Earnings.PnL | o20250801_3 (2%) | $NN | Dr / Cr |

**Step 2 — Post closing entries**  
Append the three RE records to `llcAssets_WBGroupLLC.json` via `utilWorkingDB` (safe write).
Each record:
```json
{
  "Ledger": "llcAssets",
  "aType": "Equity",
  "acct": "Acct.Equity.Earnings.PnL",
  "acctSub": "YE Net Income",
  "acctOwner": "<oID>",
  "amt": <signed_share>,
  "desc": "YE {YEAR} closing — net income allocation {pct}%",
  "dt": "{YEAR}-12-31",
  "propNm": "LLC",
  "propOwners": [<oID>],
  "tID": "YE{YEAR}_close_{oID}"
}
```

**Step 3 — Lock prior period**  
Write a lock record to `books/{YEAR}/Forms/yeClose_{YEAR}.json`:
```json
{
  "year": 2025,
  "closed_dt": "2025-12-31",
  "locked_at": "<ISO timestamp>",
  "net_income": <amount>,
  "re_entries": [<tIDs of posted closing entries>],
  "locked_by": "YECloseAgent"
}
```

**Step 4 — Redirect to BSAuditAgent**  
After successful Apply, show "✅ YE {YEAR} closed — Verify BS →" button navigating to
`/view/stmtBalanceSheet?autoAudit=1`.

### 3.4 Period Lock Enforcement

Once `books/{YEAR}/Forms/yeClose_{YEAR}.json` exists, the edit session enforces:
- Any record with `dt` starting with `{YEAR}` is **read-only** in the Flask editor
- UI shows a lock icon and "Closed — {YEAR}" badge next to the year selector
- `utilEditSession.is_locked(year)` returns True → editor shows records as read-only rows
- `PUT /api/record/...` returns HTTP 423 (Locked) if the record's year is locked

Lock check location: `util/utilEditSession.py` → `is_locked(year)` reads `yeClose_{YEAR}.json`.

---

## 4. YearStart Workflow (UI — LLC Admin)

### 4.1 Entry Point

YearStart is an admin action — it changes the app's active year configuration.
Location: **LLC Admin view** (`/view/llcAdmin`) → System section → **"🆕 Start {YEAR+1}"** button  
Trigger: Only shown after the prior year is locked (`yeClose_{YEAR}.json` exists).

### 4.2 YearStart Steps (on Confirm)

**Step 1 — Create books/{YEAR+1}/ directory structure**  
Create if missing:
```
books/{YEAR+1}/
  Forms/
  BankStmts/
```

**Step 2 — Update config.json active year**  
In `~/.llcRentalTracker/config.json`:
- Add `{YEAR+1}` to `llcList[*].years` array
- Update `default[1]` to `{YEAR+1}`

```json
{
  "default": ["WBGroupLLC", 2026],
  "llcList": [{
    "years": [2025, 2026],
    ...
  }]
}
```

**Step 3 — Reload app context**  
Call `setup_paths.load_config(llcName, YEAR+1)` to update module globals.
Flask: trigger a server restart or reload (via WSGI touch-to-reload on PA).

**Step 4 — Confirm new year is active**  
Show success message: "✅ 2026 is now the active tax year. books/2026/ is initialized."
Home page year badge updates to 2026.

### 4.3 What Does NOT Need to Happen (single-DB design)

- No opening balance journal entries — permanent account balances carry forward automatically
- No copying of `Accts/*.json` files — they are already shared
- No clearing of revenue/expense accounts — year filter handles this
- No `YECloseAgent` class — functionality is inline in the IRS Submission view

---

## 5. Post-Close Trial Balance (Verification)

After YE Close is posted, the operator runs `BSAuditAgent` from the BS view to verify:

| Check | Expected result |
|---|---|
| `A = L + E + NI` equation | Balanced (open-period) |
| RE balance (3100) | Includes newly posted YE closing entries |
| Temporary account balances for {YEAR} | $0 for new 2026 filter (year switch confirms) |

The YE Close dialog links directly to this check via `?autoAudit=1`.

---

## 6. UI Changes Summary

| View | Change | File |
|---|---|---|
| `tax_prep.html` | Add "📅 YE Close — {YEAR}" button + YE Close dialog | `ui/templates/tax_prep.html` |
| `tax_prep.html` | Pre-close checklist with auto-checks + manual confirms | `ui/templates/tax_prep.html` |
| `llcMgmt.py` | `POST /api/tax/ye_close` — preview + apply closing entries | `ui/llcMgmt.py` |
| `llcAdmin.html` | "🆕 Start {YEAR+1}" button in System section | `ui/templates/llcAdmin.html` |
| `llcMgmt.py` | `POST /api/admin/year_start` — create dirs, update config | `ui/llcMgmt.py` |
| `utilEditSession.py` | `is_locked(year)` — reads `yeClose_{YEAR}.json` | `util/utilEditSession.py` |
| `table_view.html` | Lock badge on locked-year rows; 423 handling | `ui/templates/table_view.html` |

---

## 7. Implementation Phases

Phases map to `design_BUS_01.9_YEClosing.md` Phase numbering.

### Phase 1 — YE 2025 Close (current cycle — P1)
Minimum viable: post RE closing entries with per-member split, create lock file, add year 2026 to config.

| # | Task | File | Effort |
|---|---|---|---|
| 1.1 | Add `acctOwner` field to `toRecDict()` | `ledger/llcCOA.py` | 1 line |
| 1.2 | `POST /api/tax/ye_close` — preview + post 3 per-member RE entries | `ui/llcMgmt.py` | Medium |
| 1.3 | Write `yeClose_{YEAR}.json` lock file on Apply | `ui/llcMgmt.py` | Small |
| 1.4 | YE Close dialog in `tax_prep.html` (pre-close checklist, preview table, Apply) | `ui/templates/tax_prep.html` | Medium |
| 1.5 | `POST /api/admin/year_start` — create dirs, update config.json, set active year | `ui/llcMgmt.py` | Small |
| 1.6 | "🆕 Start 2026" button in LLC Admin view | `ui/templates/llcAdmin.html` | Small |
| 1.7 | `utilEditSession.is_locked(year)` + read-only enforcement in editor | `util/utilEditSession.py` | Small |

### Phase 2 — Per-Member Capital in BS (before 2026 YE)
See `design_BUS_01.9_YEClosing.md` §Phase 2 — 7 file changes.

### Phase 3 — K-1 Item L Automation (IRS filing readiness)
See `design_BUS_01.9_YEClosing.md` §Phase 4.

---

## 8. Files Changed in BUS Repo (books/)

| Action | Path | When |
|---|---|---|
| Create | `books/2026/Forms/` | YearStart Step 1 |
| Create | `books/2026/BankStmts/` | YearStart Step 1 |
| Create | `books/2025/Forms/yeClose_2025.json` | YE Close Step 3 |
| Append | `books/Accts/llcAssets_WBGroupLLC.json` | YE Close Step 2 (3 RE records) |

After YearStart runs, commit `LLC-WBGroup` repo and sync to PA (`wsCmd.py --sync WBGroupLLC`).

---

## 9. Out of Scope for Issue #35

- `books/2025` git branch (`release/YE2025`) — managed manually by operator after close
- Backfilling `acctOwner` on prior equity entries — Phase 2 task
- Full K-1 Item L automation — Phase 3 task
- Password-protect lock (PA-level access control is sufficient for this LLC)
