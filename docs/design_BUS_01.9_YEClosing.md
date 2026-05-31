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
    * Member A Capital Contribution (Money they put in) -> COA (Acct.Equity.Owner.Capital.Funds.Contrib)
    * Member A Draws/Distributions (Money they took out) -> COA (Acct.Equity.Owner.Capital.Funds.Draws)
    * Member A Capital Account (Their share of cumulative profits/losses) -> COA (Acct.Equity.Owner.Capital.Funds.PnL)
* Member B Equity:: acctSub=Action(Contrib, Draw, PnL), acctOwner=B
    * Member B Capital Contribution -> -> COA (Acct.Equity.Owner.Capital.Funds.Contrib)
    * Member B Draws/Distributions -> COA (Acct.Equity.Owner.Capital.Funds.Draw)
    * Member B Capital Account -> COA (Acct.Equity.Owner.Capital.Funds.PnL)
* Member C Equity :: acctSub=Action(Contrib, Draw, PnL), acctOwner=C
    * Member C Capital Contribution -> -> COA (Acct.Equity.Owner.Capital.Funds.Contrib)
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

## Review: Gaps Between This Doc and Current Implementation

### Gap 1 — Net Loss Figure is Stale
The doc uses **-$416** throughout. The correct 2025 figure after MACRS depreciation fix is **-$393.50**
(rental income $4,400 − operating expenses $2,890.37 − MACRS depreciation $1,903.13).

### Gap 2 — COA Does Not Have Per-Member Capital Accounts
The current COA has one shared equity account: `Acct.Equity.Owner.Capital.Funds` (3010).
All three members' contributions, draws, and PnL allocations are mixed in the same bucket,
distinguished only by `propOwners` metadata — **not** by separate ledger accounts.

The doc correctly identifies the target structure but the COA needs new accounts:
```
Acct.Equity.Owner.Capital.Funds      3010  (existing — contributions, keep)
Acct.Equity.Owner.Capital.Dist       3020  (existing — distributions, keep)
Acct.Equity.Member.[oID].PnL         3110+ (NEW — per-member YE PnL allocation)
```
Without per-member PnL accounts, K-1 Item L (Capital Account Analysis) cannot be read
directly from the ledger — it must be computed from `propOwners` metadata each time.

### Gap 3 — `Acct.Equity.Earnings.PnL` Is Used as Two Different Things
The COA describes `Acct.Equity.Earnings.PnL` (3100) as "Retained Earnings (cumulative
profit or loss from previous years)". The current YE posting uses it as an **Income Summary**
(a temporary clearing account that gets debited/credited at year-end then offset to Capital).

These are conceptually different accounts. After YE posting the current balance is **+$393.50
Credit** — this represents the loss allocation that was Credited in and Debited out to Capital.
Over multiple years this account will accumulate and become misleading.

**Correct design:**
- `Acct.Equity.Earnings.PnL` = **Income Summary** (temporary, cleared to zero each YE)
- Per-member PnL accounts carry the running capital balance year-over-year

### Gap 4 — BS Still Shows -$393.50 Gap After YE Posting (by design)
The doc says "your Balance Sheet matches" after closing. **This is only true in a closed-period
system.** This system is intentionally **open-period** (revenue/expense accounts stay open for
IRS K-1 detail). The BS will always show `equation_diff = NI`. The BSAuditAgent confirms this
is expected — `verdict: open_period_ni`, GL balanced under `A = L + E + NI`.

### Gap 5 — No New-Year Opening Balance Process Defined
The doc covers closing 2025 but not opening 2026. The system needs a defined workflow for:
- Carrying forward the ending capital balance per member into `books/2026/Accts/`
- Resetting the Income Summary / PnL clearing account to $0
- Beginning balance entries for cash, fixed assets, and accumulated depreciation

### Gap 6 — YE Posting `re_atype` Direction Needs Verification Against COA
Current YE posting posts RE records as:
```
Dr Acct.Equity.Earnings.PnL (loss: Credit) / Cr Acct.Equity.Owner.Capital.Funds (loss: Debit)
```
For a **net loss**: Credit PnL, Debit Capital.Funds → reduces member capital ✓ (matches doc Step 3).
For a **net income**: Debit PnL, Credit Capital.Funds → increases member capital ✓.
Direction is correct. However, both members share the same `Acct.Equity.Owner.Capital.Funds`
account — per-member isolation requires Gap 2 to be resolved first.

### Gap 7 — K-1 Item L Capital Account Analysis Not Mapped
IRS Schedule K-1 Item L requires per-member:
- (a) Beginning capital
- (b) Capital contributed during year
- (c) Current year net income/(loss) share
- (d) Other increases/(decreases)
- (e) Withdrawals and distributions
- (f) Ending capital = (a)+(b)+(c)+(d)−(e)

The system currently has no direct ledger path to compute (a) without re-running prior-year GL.
Per-member PnL accounts (Gap 2) would make (c) and (f) ledger-readable directly.

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

### Phase 2 — COA Enhancement (before 2026 YE)
Add per-member PnL capital accounts to the COA and update all writers.

| # | Action | Files |
|---|---|---|
| 2.1 | Add `Acct.Equity.Member.{oID}.PnL` accounts to COA for each member | `ChartOfAccounts_WBGroupLLC.json` |
| 2.2 | Update YE posting: use per-member PnL account as `Ledger` (not shared Capital.Funds) | `ui/llcMgmt.py` → `ye_preview()` |
| 2.3 | Audit all existing `Acct.Equity.Owner.Capital.Funds` entries — tag `acctSub` as Contrib/Draw/PnL | `llcAssets`, `llcExpRev` |
| 2.4 | Update BS view to group equity by member (show per-member capital balance) | `ledger/stmtBS.py`, `financial_view.html` |
| 2.5 | Verify PropAgent closing still routes equity to correct member-specific accounts | `ledger/propAgent.py` |

### Phase 3 — New Year Opening Balance Workflow (2026 setup)
Define and implement the year-transition process.

| # | Action | Files |
|---|---|---|
| 3.1 | Design `YECloseAgent`: reads ending balances from 2025 GL, writes opening entries to 2026 `llcAssets` | new `ledger/yeCloseAgent.py` |
| 3.2 | Opening entries: Cash, Fixed Assets, AccumDepr, per-member Capital balances | `books/2026/Accts/llcAssets_WBGroupLLC.json` |
| 3.3 | Reset Income Summary (`Acct.Equity.Earnings.PnL`) to $0 in new year (no opening balance entry needed — it accumulates only within-year) | `ye_preview()` logic |
| 3.4 | Add `wsCmd.py --newYear 2026` command to automate the transition | `wsCmd.py` |

### Phase 4 — K-1 Item L Automation (IRS filing readiness)
Wire per-member capital accounts to K-1 Item L fields.

| # | Action | Files |
|---|---|---|
| 4.1 | Map `Acct.Equity.Member.{oID}.PnL` ending balances → K-1 Item L(f) Ending Capital | `irs/mapIRS2LLC.py` |
| 4.2 | Map `Acct.Equity.Owner.Capital.Funds` contribution entries → K-1 Item L(b) | `irs/mapIRS2LLC.py` |
| 4.3 | Map `Acct.Equity.Owner.Capital.Dist` → K-1 Item L(e) Withdrawals | `irs/mapIRS2LLC.py` |
| 4.4 | Validate: K-1 Item L(a)+(b)+(c)−(e) = L(f) for each member | `irs/Sch_K1.py` |
