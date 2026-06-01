# Accounting Best Practices - YE Closing

## Learn: Why Your Balance Sheet is Imbalanced After YE Closing 

The accounting system, audit agents, is currently looking at two different timeframes simultaneously before YE and New Fiscal Period.
The Profit & Loss (P&L) for the new fiscal year needs to reset to $0.
The Balance Sheet (Equity) hasn't received the -$416 Net Income (loss) deduction yet.

Because that -$416 loss is "floating" in limbo between the P&L and the Balance Sheet, your assets are now $416 lower than your combined liabilities and equity.

## Account Best Practice Multi-member LLC

For a multi-member LLC, the recommended way is to skip Retained Earnings entirely and close the net loss directly into each partner's individual Member Capital account based on their specific profit/loss ownership percentage.
The IRS views multi-member LLCs as partnerships by default, which means the entity's equity must be tracked line-by-line for each unique human owner.
Here is the exact blueprint for handling this for a multi-member LLC.

### Step 1: Set Up The Chart of Accounts to reflect Equity Actions
Do not use a generic "Owner's Equity" account. You must split your equity section into distinct "buckets" for each member.

* Member A Equity :: acctSub=Action(Contrib, Draw, PnL), acctOwner=A
    * Member A Capital Contribution (Money they put in) -> COA (Acct.Equity.Owner.Capital.Funds)
    * Member A Draws/Distributions (Money they took out) -> COA (Acct.Equity.Owner.Capital.Funds.Draws)
    * Member A Capital Account (Their share of cumulative profits/losses) -> COA (Acct.Equity.Owner.Capital.Funds.PnL)
* Member B Equity:: acctSub=Action(Contrib, Draw, PnL), acctOwner=B
    * Member B Capital Contribution -> -> COA (Acct.Equity.Owner.Capital.Funds)
    * Member B Draws/Distributions -> COA (Acct.Equity.Owner.Capital.Funds.Draw)
    * Member B Capital Account -> COA (Acct.Equity.Owner.Capital.Funds.PnL)
* Member C Equity :: acctSub=Action(Contrib, Draw, PnL), acctOwner=C
    * Member C Capital Contribution -> -> COA (Acct.Equity.Owner.Capital.Funds)
    * Member C Draws/Distributions -> COA (Acct.Equity.Owner.Capital.Funds.Draw)
    * Member C Capital Account -> COA (Acct.Equity.Owner.Capital.Funds.PnL)

#### Assess Difference in current llcRentalTracking/COA and accounts per above

- the most obvious is that Acct.Equity.Owner.Capital.Funds is the sole account being used and entered in llcAssets and llcExpRev.
- The Acct.Equity.Owner.Capital.Funds may also be used when injesting new bank transactions (ie. within llcBank).
- The Acct.Equity.Owner.Capital.Funds is also used in PropAgent for importing closing statements.
- Consider that this a change to the Busiiness Files Git, local and PA - how best to sync once books are changed.   Assume PA books (LLC-WBGroup) are the master. 

### Step 2: Calculate the Split
You must allocate the YE PnL -$416 net loss according to the percentages written in your LLC's Operating Agreement.

* Example Assume a 60/40 split between Member A and Member B:
* Member A Share (60%): $-\$416 \times 0.60 = \mathbf{-\$249.60}$
   * Member B Share (40%): $-\$416 \times 0.40 = \mathbf{-\$166.40}$
 
#### Assess potential hits across all views
- llcAsset: NewPropAgent, YE Closing
- BS view :
- IS view by owner
- Owners View

### Step 3: Post the Multi-Member Closing Entry : PnL
To close the year, you will write a single journal entry that moves the loss from the Income Summary account and distributes it proportionately to the members.

* Debit: Member A Capital Account — $249.60 (Reduces Member A's equity)
* Debit: Member B Capital Account — $166.40 (Reduces Member B's equity)
* Credit: Income Summary — $416.00 (Zeroes out the P&L loss)

GL Status Check: Total Debits $(\$249.60 + \$166.40 = \$416)$ perfectly equal Total Credits $(\$416)$. Your General Ledger stays in perfect balance, your P&L resets to zero, and your Balance Sheet matches.

#### Assess potential hits across all views
- llcAsset: YE closing
- BS view : BalSheetAudit

### Why This Is Crucial for the IRS
When you file your multi-member LLC tax return (Form 1065), you must issue a Schedule K-1 to each member.

* The Schedule K-1 requires you to report each partner's "Capital Account Analysis" (Item L).
* By closing the books directly to individual Member Capital accounts, the ending balances on your Balance Sheet will perfectly match the exact numbers required on each member's K-1.

#### Assess potential hits across all views

- Advanced: consider how data within Books NS can be fed into downstream IRS form preparation.
- Think of smart way to automate the feeds.

---

## Architecture Decision: YE Posting + BSAuditAgent — One Dialog or Two?

### Question
Should the BSAuditAgent (currently in the BS view Actions menu) be merged into the
YE Closing dialog in llcAssets, or kept as a separate tool?

### Decision: Keep Separate — Link Them With a Post-Apply Handoff

**Rationale:**

| Concern | YE Posting (llcAssets) | BSAuditAgent (BS view) |
|---|---|---|
| Operation type | **Write** — appends records to `llcAssets` | **Read-only** — reads full GL across all 4 source DBs |
| Scope | Single source DB (`llcAssets`) | Full GL (Assets + ExpRev + Payables + Receivables) |
| When useful | Once per year at year-end | Any time — mid-year, post-edit, pre-filing |
| User intent | "Post my closing entries" | "Is my BS correct right now?" |

Merging them into one dialog would:
- Create a dialog that both **writes data** and **audits results** — hard to reason about
- Make `Apply` ambiguous (does it post? does it audit? both?)
- Remove the ability to run BSAuditAgent independently mid-year
- Violate the separation between source-DB write actions and GL-wide read diagnostics

This is consistent with how professional accounting software works: journal entry posting
and report verification are always separate steps.

### Implementation: Smooth UX Handoff (not a merge)

After YE `Apply` succeeds, the dialog closes and the success message includes a
**"✅ Posted — Verify BS →"** button that navigates to the BS view with
`?autoAudit=1` in the URL, causing the BSAuditAgent to open automatically.

The user experiences a seamless two-step flow without the tools being architecturally coupled:

```
llcAssets view
  └─ 📅 YE Posting dialog
       └─ [Apply Selected]
            └─ ✅ Posted 4 records
               [Go to BS Audit →]  ← navigates to /view/stmtBalanceSheet?autoAudit=1
                    └─ BS view auto-opens 🔍 BSAuditAgent
                         └─ 🟡 open_period_ni — GL balanced A=L+E+NI ✓
```

### When to Implement
Phase 2 (see Change Plan below) — after per-member COA accounts are in place, the
BSAuditAgent will be more informative (showing per-member capital balances). The
handoff URL parameter (`?autoAudit=1`) is a small addition to both the YE apply
success handler and the BS view page-load script.

---

## Review: Gaps Between This Doc and Current Implementation

### Gap 1 — Net Loss Figure is Stale
The doc uses **-$416** throughout. The correct 2025 figure after MACRS depreciation fix is **-$393.50**
(rental income $4,400 − operating expenses $2,890.37 − MACRS depreciation $1,903.13).

### Gap 2 — No Per-Member Tracking on Equity Records
The current COA has one shared equity account: `Acct.Equity.Owner.Capital.Funds` (3010).
All three members' contributions, draws, and PnL allocations are mixed in the same bucket,
distinguished only by `propOwners` metadata and free-text `desc`.

**Decision: use `acctOwner` + `acctSub` fields — do NOT add per-member COA accounts.**

Keep the existing COA account structure. Add an `acctOwner` field (the member's `oID`) to
every equity-related transaction record, and standardise `acctSub` values for equity actions:

| `acct` | `acctOwner` | `acctSub` | Meaning |
|---|---|---|---|
| `Acct.Equity.Owner.Capital.Funds` | `o20250801_1` | `Contrib` | Francis contribution |
| `Acct.Equity.Owner.Capital.Funds` | `o20250801_1` | `YE Net Income` | Francis YE PnL share |
| `Acct.Equity.Owner.Capital.Dist`  | `o20250801_2` | `Draw` | Alexandra distribution |

This avoids COA proliferation (3 members × 3 action types = 9 new accounts), keeps the
COA stable regardless of member changes, and lets the BS/IS/K-1 filter by `acctOwner` at
query time.

### Gap 3 — `Acct.Equity.Earnings.PnL` Role Clarified
With the single-DB decision (see Gap 5), `Acct.Equity.Earnings.PnL` (3100) naturally
accumulates all YE closing entries across years:
- 2025 YE loss: Credit +$393.50 → running balance = $393.50 credit
- 2026 YE income: Debit $X → balance adjusts accordingly

The net balance = **cumulative retained earnings** — exactly what the COA description says
("Cumulative profit or loss from previous years"). This account does NOT need to be cleared
to zero each year. Gap 3 is resolved by the single-DB design.

### Gap 4 — BS Still Shows -$393.50 Gap After YE Posting (by design)
The doc says "your Balance Sheet matches" after closing. **This is only true in a closed-period
system.** This system is intentionally **open-period** (revenue/expense accounts stay open for
IRS K-1 detail). The BS will always show `equation_diff = NI`. The BSAuditAgent confirms this
is expected — `verdict: open_period_ni`, GL balanced under `A = L + E + NI`.

### Gap 5 — New-Year Opening Balances Are Not Needed (Single DB Decision)
**Decision: keep a single set of `Accts/*.json` files across all years.**

Change filesystem structure:
```
FROM: books/<year>/Accts/*.json   (separate files per year)
TO:   books/Accts/*.json          (one file for all years, filtered by dt at query time)
```

`Forms/` and `BankStmts/` remain year-organised (they are filed documents, not
accounting records):
```
books/
  Accts/                  ← shared across all years
    llcAssets_WBGroupLLC.json
    llcExpRev_WBGroupLLC.json
    ...
  2025/
    Forms/                ← year-specific (PDFs)
    BankStmts/            ← year-specific
  2026/
    Forms/
    BankStmts/
```

With a single DB, **no opening-balance entries are needed**. The GL at any date is the
running total of all prior transactions in the same file. AccumDepr, Capital balances,
and Cash all carry forward automatically. The year switcher changes the query filter
(`dt` starts with year), not the file path. `YECloseAgent` is not needed.

### Gap 6 — YE Posting `re_atype` Direction Is Correct
Current YE posting:
```
Loss:   Cr Acct.Equity.Earnings.PnL / Dr Acct.Equity.Owner.Capital.Funds  ✓
Income: Dr Acct.Equity.Earnings.PnL / Cr Acct.Equity.Owner.Capital.Funds  ✓
```
Direction matches Step 3 of this doc. The only remaining issue is adding `acctOwner`
to each RE record so per-member capital can be queried directly (Gap 2).

### Gap 7 — K-1 Item L Capital Account Analysis
IRS Schedule K-1 Item L requires per-member:
- (a) Beginning capital — sum of all equity records for `acctOwner=oID` through prior Dec 31
- (b) Capital contributed — `acctSub=Contrib`, `acctOwner=oID`, current year
- (c) Current year net income/(loss) share — `acctSub=YE Net Income`, `acctOwner=oID`, current year
- (d) Other increases/(decreases) — other equity entries for `acctOwner=oID`
- (e) Withdrawals/distributions — `acct=Acct.Equity.Owner.Capital.Dist`, `acctOwner=oID`
- (f) Ending capital = (a)+(b)+(c)+(d)−(e)

With `acctOwner` on every equity record and single DB, all six lines are direct GL queries —
no metadata reconstruction required.

---

## Change Plan

### Phase 1 — Immediate (YE 2025, books already correct)
No code changes needed. Current YE posting is functionally correct for 2025 filing.
The -$393.50 BS gap is expected (open-period). BSAuditAgent confirms GL is balanced.

| # | Action | Where |
|---|---|---|
| 1.1 | Confirm YE entries in PA match: depr $1,903.13 (Aug MACRS), RE loss split 96/2/2 | PA books / llcAssets |
| 1.2 | Run BSAuditAgent → verify `verdict: open_period_ni`, no GL errors | BS view → Actions |
| 1.3 | Generate K-1 from IS per-member view — members report -$393.50 loss proportionally | IS PerMember view |

### Phase 2 — `acctOwner` Field: Per-Member Equity Tracking (before 2026 YE)
Add `acctOwner` field to the record schema and backfill existing equity entries.
No new COA accounts. No COA file changes.

**Codebase impact — 7 files:**

| # | Action | File | Scope |
|---|---|---|---|
| 2.1 | Add `acctOwner = kwargs.get('acctOwner', np.nan)` to `toRecDict()` | `ledger/llcCOA.py` | 1 line |
| 2.2 | Add `"acctOwner": oID` to every RE record in `ye_preview()` | `ui/llcMgmt.py` | 1 line |
| 2.3 | Add `"acctOwner": oID` to equity records in PropAgent closing | `ui/llcPropAgent.py` | Small |
| 2.4 | Backfill `acctOwner` on existing `Acct.Equity.Owner.Capital.Funds` entries (3 records: FRojas contribution, balance-start, equity-other) | `books/Accts/llcAssets_WBGroupLLC.json` | Data |
| 2.5 | Update `stmtBS_View.view()` to group equity rows by `acctOwner` when present; show per-member sub-rows in BS equity section | `ledger/stmtBS.py` | Medium |
| 2.6 | Add `acctOwner` filter to `stmtOwnerEquity` per-member view | `ledger/stmtOwnerEquity.py` | Small |
| 2.7 | Add handoff: after YE Apply success, show "✅ Posted — Verify BS →" button navigating to `/view/stmtBalanceSheet?autoAudit=1`; add page-load `autoAudit` handler to BS view | `ui/templates/table_view.html`, `financial_view.html` | Small |

### Phase 3 — Single DB Across All Years (filesystem restructure)
Move `Accts/*.json` out of year subdirectories into a shared `books/Accts/` directory.
`Forms/` and `BankStmts/` remain year-organised (filed documents, not accounting records).
No opening-balance entries needed — GL history is continuous; year filter = `dt` prefix.

**Codebase impact — 8 files + 1 data migration:**

| # | Action | File | Scope |
|---|---|---|---|
| 3.1 | Change `ACCTS_DIR = books / str(yr) / "Accts"` → `books / "Accts"` | `ledger/setup_paths.py` | 2 lines |
| 3.2 | Add optional `year: int` param to `load()`; filter records where `dt` starts with `str(year)` | `ledger/ledgerDB.py` | Small |
| 3.3 | Pass `year` filter when loading DBs for GL construction | `util/utilEditSession.py` | Small |
| 3.4 | Pass `year` filter through `llcReportEngine.getGLList()` | `ui/llcReportEngine.py` | Small |
| 3.5 | Update `wsCmd.py` path config; remove `--newYear` command (no longer needed) | `wsCmd.py` | Small |
| 3.6 | Update `~/.llcRentalTracker/config.json`: `year` becomes active-filter only, not path component | config | Config |
| 3.7 | Year switcher on home page changes query param, not directory | `ui/templates/home.html` | Small |
| 3.8 | Update IRS form path helpers (`irsForm.py`, `BookToIRS.py`) — `ACCTS_DIR` now shared; `IRS_FORMS_DIR` stays year-specific | `irs/irsForm.py`, `irs/BookToIRS.py` | Small |
| 3.9 | **Data migration**: merge `books/2025/Accts/*.json` + any `books/2026/Accts/*.json` into `books/Accts/*.json`; commit to LLC-WBGroup repo | `books/Accts/` | One-time |

### Phase 4 — K-1 Item L Automation (IRS filing readiness)
Wire per-member equity records (filtered by `acctOwner` + `acctSub`) to K-1 Item L fields.
Depends on Phase 2 (`acctOwner` present) and Phase 3 (full history in single DB).

| # | Action | File | K-1 Line |
|---|---|---|---|
| 4.1 | Sum all equity records `acctOwner=oID`, `dt < YYYY-01-01` → beginning capital | `irs/mapIRS2LLC.py` | Item L(a) |
| 4.2 | Sum `acctSub=Contrib`, `acctOwner=oID`, current year → contributions | `irs/mapIRS2LLC.py` | Item L(b) |
| 4.3 | Sum `acctSub=YE Net Income`, `acctOwner=oID`, current year → NI share | `irs/mapIRS2LLC.py` | Item L(c) |
| 4.4 | Sum `acct=Acct.Equity.Owner.Capital.Dist`, `acctOwner=oID`, current year → distributions | `irs/mapIRS2LLC.py` | Item L(e) |
| 4.5 | Compute L(f) = L(a)+L(b)+L(c)−L(e); validate against running balance | `irs/Sch_K1.py` | Item L(f) |
| 4.6 | Populate K-1 PDF Item L fields from computed values | `irs/Sch_K1.py` | PDF fill |
