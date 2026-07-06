# BUS Corruption 2026.07.04 

Accounting Forensics of local BUS books Corruptions
1. PA BUS is at commit 3043697
2. Local BUS is at commit c963d20
3. Compare GL Trial Balance : Local :: PA
    - Asset: Acct.Fixed.Depreciation.Accum	 -1903.13
    - Expens: Acct.Exp.Depreciation    		  1903.13
    - NI diff does not equal K1 667.55
4. NEED: llcAssets missing Acct.Equity.Income.Summary journal
    - 2025.12.31	667.55	Debit	Acct.Equity.Income.Summary	Equity	Acct.Equity.Earnings.PnL	YE Net Income -> Equity per memberYE Equity
5. SUCC: Form1065 SchK1 lines 3a-11 ok (Git issue #47)


## Git Issues List

A view of all the closed git issues reflect 4 groups

1. `<40` : the BUS books have been reverted to this state, commit 3043697
2. 40-47 : these were fixed in finalizing the YE Closing and IRS Package
3. 48-51 : this was the initial attempt for YearStart and Ingestion (3 fixes, closed)
4. 53-57 : fixes started when corruption was found

| Git # | State | Abstract | 
|----|----|----|
| 57 | OPEN | BookAgent — periodic BookState trust check + monthly recon|
| 56 | OPEN | 07.04 HomeFS ; view options (wbgroupmgr)|
| 55 | OPEN | 07.03 BankStmt Ingestion needs to handle propNm on all exp√
| 54 | OPEN | 07.02 Setting YearStart balances (wbgroupmgr)|
| 53 | OPEN | Loose Control of Accounting Books (accounts) — no BookStat|
|----|----|----|
| 52 | CLOSED | 07.01 Edit Inline - type ahead columns `acct` and `Ledge|
| 51 | CLOSED | 06.30 Edit Inline UI needs improvement (wbgroupmgr)|
| 50 | CLOSED | 06.30 YearStart missing Beginning Account Value in llcAs|
| 49 | OPEN | 06.30 Edit In-line llcExpRev propNm global change (wbgroup|
| 48 | OPEN | 06.30 BankReconfilation - Upload CSV (wbgroupmgr)|
|----|----|----|
| 47 | CLOSED | 06.30 Form 1065, Sch K (pg 5) - lines 3a-11 are wrong (w|
| 46 | CLOSED | 06.29 eFile Mechanism - MeF requires a registered servic|
| 45 | CLOSED | 06.29 Accountant Feedback - periodic reconciliation repo|
| 44 | CLOSED | 06.29 Accountant feedback: per account drill down (wbgro|
| 43 | CLOSED | 06.29 - Accountant feedback: BS/IS with only balance - r|
| 42 | CLOSED | 06.26 - BankToBook - Flask Views w/ Inline preview (wbgr|
| 41 | CLOSED | 05.23 Table Action Delete - add audit trail (wbgroupmgr)|
| 40 | CLOSED | feat(BankToBook): implement BankAgent + IngestAgent two-|
|----|----|----|
| 39 | CLOSED | 05.18 - YE Acct.Exp.Depreciation (wbgroupmgr)|
| 38 | CLOSED | 05.15 - Setup SMTP on PA (wbgroupmgr)|
| 37 | OPEN | AppDev: relationship diagram — how agents/aids/packages ca|
| 36 | OPEN | AppDev: Agent & Aid inventory — catalog all agents/aids in|
| 35 | OPEN | 05.15  YE Close Books - Next Year Setup (wbgroupmgr)|
| 34 | CLOSED | 05.15 -- YE notification of members (wbgroupmgr)|
| 33 | CLOSED | Configure SMTP on PA to send reviewer notification email|
| 32 | CLOSED | 05.15 - Sync LLC-WB-Group_v0.5 -> LLC-WBGroup (wbgroupmg|
| 31 | CLOSED | 05.15 - Migrate APP, BUS to  PA Host (wbgroupmgr)|

## Claude Recovery comment 07.04 

release/v1.1 (dff1a87, 06-11) and release/v1.2 (3043697, 06-19) both branched before 9ea44e1 — neither release branch has the corrected closing entries at all. Only main does.

⚠️ 7456ac4 (K-1s emailed to members) landed before 4fdbb4e (the NI=$667.55 fix) that same day — worth double-checking whether the K-1s that went out reflect the corrected split or an earlier number. I haven't verified the actual K-1 PDF contents against this yet.

The **uncommitted part** (not in git at all)
The c4cea07 commit is stale — it predates the NI fix entirely, so it's not "the good one." The PDFs that actually matter were regenerated locally, never committed:

File	Local mtime	Relative to corruption
- WBGroupLLC_2025_YEFinancialReport.pdf	Jun 29, 11:45am	before
- Form1065_FILL.pdf	Jun 30, 11:42am	before
- manifest.json (assembled_at 12:37pm) / AccountantLetter_2025.pdf	Jun 30, 12:37pm	before
- llcAssets corruption (yeClose_2025.json locked_at)	Jun 30, 4:12pm	—
- Form1065_diagnose_state.json	Jun 30, 4:42pm	after — may reflect corrupted numbers

So: the manifest/FILL.pdf/AccountantLetter/YEFR were all assembled ~4 hours before the corruption, from the same correct book state as 9ea44e1. They're good — they just were never git add'ed/committed. The Form1065_diagnose_state.json was regenerated after the corruption, so that one specific diagnostic file may be out of sync with the PDFs sitting next to it.

One more thing worth knowing: test_efile/TEST_EFILE_README.txt confirms this is a test MeF structure only — "Actual MeF submission requires a certified ERO or software provider." So nothing has been electronically filed with the IRS yet regardless of any of this; "sent" so far means the K-1 emails to members (7456ac4) and whatever PDFs were manually shared with your accountant.

Bottom line: the PDFs you'd want to trust are the uncommitted ones on disk right now (Jun 29-30 morning), not anything in git history — c4cea07 is outdated and nothing since 9ea44e1 was ever committed. Want me to verify the K-1 PDF contents against the $667.55 split, or commit the current (correct, pre-corruption) PDF package to git before we touch llcAssets?

## CORRECTION (07.05, later): the actual endpoint is /api/tax/ye_close, not ye_apply

Confirmed by exact count match. `/api/tax/ye_close` (ui/llcMgmt.py:3813) — "Apply YE closing
entries (depr + RE) wholesale and lock the year" — unconditionally deletes ALL existing records
whose tID starts with `{year}.12.31_depr_` or `{year}.12.31_re_`, then adds only whatever the
caller's request body contained. It does NOT do per-tID replace like ye_apply does safely.

If the depreciation record wasn't included in that request's payload (plausible: ye_preview
reports it as "exists" and the UI likely only resubmits "new" items), it's deleted with nothing to
replace it. This exactly reproduces yeClose_2025.json's `records_added: 3, records_removed: 4`:
1 depreciation + 3 old RE records removed, 3 new (wrong-propNm) RE records added. This is almost
certainly the actual endpoint that ran 06-30, not ye_apply. Both endpoints still exist and both
need the propNm fix (Bug 1/2 below apply to ye_preview's record generation, which both ye_apply
and ye_close consume) — but ye_close additionally needs its delete-then-partial-replace logic
fixed: it should refuse to remove a category (depr_/re_) unless a same-category replacement is
present in the submitted records, not blanket-delete by tID-prefix regardless of payload contents.

Answered (07.05): the Income.Summary $667.55 entry (tID 2025.12.31_D667.55) is untouched by the
corruption — identical in HEAD and current file, already correctly posted since 39e4e73. It is
NOT a pre-requisite to journal before closing; it's already the first half of the close (Dr
Income.Summary / Cr Earnings.PnL), with the 3 RE entries as the second half (Dr Earnings.PnL / Cr
Owner.Capital.Funds per member). One minor data-quality nit found: it's mistagged `_is_depr: true`
(copy-paste artifact from original authoring, ledger/yeFinancialReport.py:893 will pull it into the
YE Financial Report's Depreciation table) — harmless to the trial balance, worth cleaning up.

2025 IS currently locked — yeClose_2025.json exists, written by the botched ye_close call.
util/utilEditSession.py:258 is_locked() just checks file existence. Locking should happen AFTER
verifying the close is correct, not before. Recommended: unlock via DELETE /api/admin/ye_unlock
(ui/llcMgmt.py:3886 — preserves audit trail in yeClose_2025_audit.log, unlike manually rm'ing the
file) → fix data → verify trial balance → re-lock (either by fixing ye_close and re-running it, or
writing a fresh honest lock file directly since entries are already correct post-revert).

## Root Cause: ye_preview/ye_apply bug (found 07.05)

`/api/llcAssets/ye/preview` (ui/llcMgmt.py:2902) and `/api/llcAssets/ye/apply` (ui/llcMgmt.py:3220)
are the intended mechanism for posting YE closing journals — Books-First: journals go into
llcAssets, IRS forms are regenerated FROM the books afterward. Never the reverse.

**Bug 1 — propNm regression.** ye_preview tags every YE Net-Income closing entry with the
per-property name (`"propNm": pnm`, ui/llcMgmt.py:3133), e.g. `H_805HighMesa`. Commit `4fdbb4e`
(issue #39, 06-17) explicitly fixed this: *"propNm: H_805HighMesa → LLC (YE close is LLC-level)."*
The code regressed back to per-property tagging after that fix, uncaught (no test covers it).

**Bug 2 — "already posted" check is broken as a result.** `existing_re` (ui/llcMgmt.py:2982-2988)
reads stored records' propNm (correctly "LLC") into keys like `("LLC", oID)`. The per-property loop
then checks `(pnm, oID) in existing_re` using `pnm="H_805HighMesa"` — never matches. So ye_preview
ALWAYS reports RE-closing entries as "new" even when already correctly posted — inviting a re-apply.

**Bug 3 (latent) — per-property loop is the wrong shape for RE closing.** `adjusted_ni` uses the
same company-wide `net_income` inside a loop keyed by property. With 1 property this is harmless;
with 2+ properties it would post the FULL company NI once per property (double/multi-counting).
Needs pulling the RE-closing computation out of the per-property loop before a 2nd property goes
in service.

**Depreciation is separately dangerous to auto-regenerate.** git blame shows the $1,903.13 entry
predates the #39 series (present since migration commit 680f1ac) — it was manually entered via
PropAgent from the closing statement, not computed by ye_preview's MACRS formula. The code's own
comment admits the GL-only formula "may exclude closing costs capitalised into basis" and that
"PropAgent amount is likely correct." Re-running ye_apply risks silently replacing a correct
closing-statement basis with a lower GL-only estimate.

**What actually happened 06-30:** someone (or a re-run) hit YE-Close-Apply again. The broken
"already applied" check (Bug 2) said "new." It posted 3 replacement RE entries with wrong propNm,
and the depreciation replace round-tripped badly, losing the original entry. Matches
yeClose_2025.json exactly: `records_added: 3, records_removed: 4` = 3 new wrong-propNm RE entries +
3 old correct RE entries + 1 depreciation entry removed.

**Proof the fix is right:** PA (3043697) vs local HEAD (c963d20) trial balance comparison — local
HEAD's llcAssets content is unchanged since 9ea44e1 (83373cf removed the closing entry, 9ea44e1
reverted it — net no change vs 3043697). Reverting the uncommitted local file to HEAD reproduces
PA's exact trial balance (Depreciation.Accum -1903.13, Exp.Depreciation 1903.13, Income.Summary
667.55, Total 672,945.93). Revert to HEAD, not a fresh ye_apply — a fresh apply would hit all 3
bugs above again.

## Forward Plan (drafted 07.05, awaiting go-ahead on data steps)

**Phase 0 — code fixes, no data risk (safe to do anytime)**
1. [DONE, uncommitted] wsCmd.py: `--start` now resolves year via config.json's `"default"` entry
   (matches wsgi.py/get_default()) instead of always picking the latest registered year.
2. Fix ye_preview Bug 1: hardcode `propNm: "LLC"` on RE-closing records (ui/llcMgmt.py:3133),
   not the loop's per-property `pnm`.
3. Fix ye_preview Bug 2: existing_re match must use "LLC" (or match by acctSub+oID+year only,
   ignoring propNm) so status correctly reports "exists" once posted.
4. Fix ye_preview Bug 3: move RE-closing computation out of the per-property `for pnm, pdata in
   props.items()` loop — compute once per YE close, independent of property count. Depreciation
   stays per-property (each property has its own basis).
5. Add a guard so ye_apply refuses to silently replace a manually-entered (`_is_depr`) depreciation
   record from PropAgent without an explicit operator confirmation that the closing-statement
   basis was reviewed.

**Phase 1 — restore 2025 book state to PA truth (data fix, needs explicit go-ahead each time)**
1. Revert `books/Accts/llcAssets_WBGroupLLC.json` to HEAD (c963d20) — restores the depreciation
   entry and propNm=LLC on the 3 RE-closing entries.
2. Verify: pull a fresh trial balance, confirm it matches PA's exactly (672,945.93 total).
3. Reconcile `yeClose_2025.json` (the lock file recording the botched apply) — either regenerate
   it to reflect the restored state or clearly annotate it as superseded; don't leave it describing
   a close that no longer matches the books.
4. Re-run `/api/bookState` (issue #53) and log a verified snapshot now that the state is trusted.

**Phase 2 — regenerate IRS forms FROM the restored books**
1. Regenerate Form4562, Form8825, Form1065, Sch K-1 from the corrected llcAssets/GL — never
   hand-edit the forms.
2. Cross-check against the Jun 29-30 uncommitted PDFs already on disk (built from the same
   pre-corruption book state) — should match; use as an independent verification.
3. Commit the corrected llcAssets, regenerated PDFs, and manifest together. If any bookNS_*.json
   section changed, this is a Cross-Repo Commit — LLC repo + BUS repo commits in the same session
   (see CLAUDE.md Cross-Repo Commit Rule).
4. Verify K-1 PDFs actually sent to members (commit 7456ac4, 06-17 08:37) reflect the $667.55 split
   from 4fdbb4e (06-17 23:39) — 7456ac4 landed BEFORE that fix same day; unconfirmed whether the
   emailed K-1s used the corrected numbers.

**Phase 3 — apply remaining open issues, in order**
1. **#53** (BookState) — finish the Dimension 1-4 audit; fold the ye_preview/apply bugs above into
   its scope, since they're exactly the class of "which source is truth" bug #53 was hunting.
2. **#57** (BookAgent periodic check + monthly recon) — depends on #53.
3. **#54** (YearStart 2026 balance-forward) — do only after 2025 is correctly closed; carrying
   forward a corrupted 2025 ending balance just moves the corruption into 2026.
4. **#55** (2026 ingestion propNm fix) — after YearStart, so ingested rows land in a correctly
   seeded 2026.
5. **#56** (HomeFS view fixes) — lowest urgency, cosmetic/reporting, can trail.

**Phase 4 — re-verify nothing else regressed**
1. Re-run test_stmtBS / test_stmtIS / test_stmtGL.
2. Manually confirm switching 2025⇄2026 in the UI doesn't reintroduce the wsCmd/utilWorkingDB
   year-filter issue from this session.


## GIT LLC-WBGroup




## Local BUS

- c963d20 (HEAD -> main, origin/main, origin/HEAD) fix(data): recover 53 dropped 2025 llcExpRev records lost to multi-year write-path bug
- 02b8c16 fix(#47): remove F247/F248 from Form1065 Sch K in bookNS_IS.json
- 9ea44e1 fix(#39/revert): restore YE Income.Summary closing entry to llcAssets
- b46d19d feat(#40/P0): migrate llcExpRev to {"records":[...],"LogHistory":[]} schema
- 83373cf fix(#39): remove YE Income.Summary closing entry from llcAssets
- **3043697** (origin/release/v1.2, release/v1.2) chore: untrack runtime state files — add *_diagnose_state.json and *_session_state.json to gitignore
- 70a061c refactor(#5): restructure repo — Assets → pages/Assets, retire pages/AccountingData
- 6866d79 feat(#5): Step 3A — restructure pages/Operations per TOBE design
- 39e4e73 fix(#39): add Income.Summary COA entry + YE clearing transaction
- 4fdbb4e fix(#39): correct 2025 YE RE closing entries — NI=$667.55 profit
- 7456ac4 add email per member; sent K1 to members
- 04dcf32 feat(llcOwners): add email field — null default for all 3 members
- **c4cea07** fix(BUS/2025): IRS submission package, YEFR PDFs, Accts data, diagnose state
- 228301d fix(Sch_K1): clear f19 logicalKey — force blank in FILL.pdf
- 0c2aa1c fix(Sch_K1): remove wrong F012/F013 from bookNS_Profile; track namespace




### Local GL Trial

GIT COMMIT: c963d20 
```
acctType	acct	Minor	Debit	Credit	Balance
Asset
Acct.Cash	Bank	223671.59	216905.60	6765.99
Acct.Fixed	Land	79438.41		79438.41
Acct.Fixed	Tangible.InConstruction	2532.36		2532.36
Acct.Fixed	Tangible.InService	141223.84	1660.64	139563.20
Asset Subtotal	446866.20	218566.24	228299.96
Equity
Acct.Equity	Income.Summary	667.55		667.55
Acct.Equity	Owner.Capital.Funds	100.00	226496.83	-226396.83
Equity Subtotal	767.55	226496.83	-225729.28
Income
Acct.Rev	Fees.Other	0.53	400.53	-400.00
Acct.Rev	Rent		4000.00	-4000.00
Income Subtotal	0.53	4400.53	-4400.00
Expense
Acct.Exp	Operating	135.34		135.34
Acct.Exp	Other	306.17		306.17
Acct.Exp	Repair	213.12	14.06	199.06
Acct.Exp	Util	1188.75		1188.75
Expense Subtotal	1843.38	14.06	1829.32
TOTAL
671042.80	671042.80	0.00
TOTAL Subtotal	671042.80	671042.80	0.00
TOTAL	671042.80	671042.80	0.00
```


## PA BUS

- **3043697** (HEAD -> main, origin/main, origin/HEAD) chore: untrack runtime state files — add *_diagnose_state.json and *_session_state.
json to gitignore
- 70a061c refactor(#5): restructure repo — Assets → pages/Assets, retire pages/AccountingData
- 6866d79 feat(#5): Step 3A — restructure pages/Operations per TOBE design
- 39e4e73 fix(#39): add Income.Summary COA entry + YE clearing transaction
- 4fdbb4e fix(#39): correct 2025 YE RE closing entries — NI=$667.55 profit
- 7456ac4 add email per member; sent K1 to members
- 04dcf32 feat(llcOwners): add email field — null default for all 3 members
- c4cea07 fix(BUS/2025): IRS submission package, YEFR PDFs, Accts data, diagnose state
- 228301d fix(Sch_K1): clear f19 logicalKey — force blank in FILL.pdf
- 0c2aa1c fix(Sch_K1): remove wrong F012/F013 from bookNS_Profile; track namespace.json
```

### GL Trail - Truth

GIT COMMIT: 3043697
```
acctType	acct	Minor	Debit	Credit	Balance
Asset
Acct.Cash	Bank	223671.59	216905.60	6765.99
Acct.Fixed	Depreciation.Accum		1903.13	-1903.13
Acct.Fixed	Land	79438.41		79438.41
Acct.Fixed	Tangible.InConstruction	2532.36		2532.36
Acct.Fixed	Tangible.InService	141223.84	1660.64	139563.20
Asset Subtotal	446866.20	220469.37	226396.83
Equity
Acct.Equity	Income.Summary	667.55		667.55
Acct.Equity	Owner.Capital.Funds	100.00	226496.83	-226396.83
Equity Subtotal	767.55	226496.83	-225729.28
Income
Acct.Rev	Fees.Other	0.53	400.53	-400.00
Acct.Rev	Rent		4000.00	-4000.00
Income Subtotal	0.53	4400.53	-4400.00
Expense
Acct.Exp	Depreciation	1903.13		1903.13
Acct.Exp	Operating	135.34		135.34
Acct.Exp	Other	306.17		306.17
Acct.Exp	Repair	213.12	14.06	199.06
Acct.Exp	Util	1188.75		1188.75
Expense Subtotal	3746.51	14.06	3732.45
TOTAL
672945.93	672945.93	0.00
TOTAL Subtotal	672945.93	672945.93	0.00
TOTAL	672945.93	672945.93	0.00
```