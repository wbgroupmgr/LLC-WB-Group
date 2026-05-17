# ProjectLevel5 v0.3 — Tax Activities Project Plan

> **Scope.** Planning document only. NO code changes are made by this file.
> **Baseline.** State of the codebase after v0.2
> **Target.** Level 4 of workflow
> focus on completing a good solid  **Tax Preparedness**:
> map COA -> Book2TaxDict :: maps COA (acctType, acct) to TaxForm_fields F###
> <formObj>.mergeGL(gl) -> TaxField2GLValueDict :: maps each F### to a value, value=None if not in GL or GL.acct.bal == 0
> <formObj>.fillPDF(TaxField2GLValue) -> file irsForms/<form>_FILL.pdf
> enhance tax views to show/editTaxField2GLValueDict and frame containing PDF file (full or byPage)
> complete all of above for forms Form1065, Sch_K_1 and Form4562
---

## 0. TL;DR

* **Estimated total effort: ~??% of the remaining usage window.**
* **Answer to the single question below:** **No** — the project can be
  completed within the current usage allocation, assuming no new feature
  scope is added. See §8.

---

## 1. Level 4 scope

`LLC_AccountingWorkflow.md` defines Level 4 as *Tax Preparedness* with three
explicit deliverables:

1. Map Book data (GL) to IRS forms.
2. Reconcile IRS forms with the Books.
3. Produce Financial Reports and Letters for downstream consumers.

As an accounting/software expert I am interpreting "Level 4 complete" as the
following concrete acceptance criteria (locked in here so the project scope
is unambiguous):


## Criterias

1. **Desc**: IRS Form to COA
    - Acceptance: 
        - per form: each `Form Field` <formName,f###>  maps to a `Book Field` <ledgerObj, COA accountName | llcProfile.FieldName>
        -         - there no hard-coded page/coord logic inside any formObj, e.g. `Form1065.py` etc.
        - Satisfies the "Tax Bridge Pattern" called for in `LLC_AccountingDesign.md`.
        - NOTE: the FormField may need to reference a LLC profile field, ie. ledgerObj "llcProfile",
           - meaning a field within the LLC profile.
           - Where `FieldName` is a multi-node index into the profile Dict,
           - e.g. FieldName=node1.node2 ==> llc.__dict__.[node1][node2]
    - WHY:
        - the FormField2GLField mapping should is bound to annual Form definition
        - defined apriori by a **declarative mapping** (JSON)

2. **Desc**: A Book-to-Tax bridge needed (`irs/bookToTax.py`)
    - Acceptance:
        - service to converts Book Net Income → Taxable Income using a small, declarative adjustments table
        - (e.g. 50% Meals, T&E limits, §179 election, depreciation basis Δ).
    - Why
        - Without this, Sch-M-1 cannot be produced correctly.
3. **Desc**: A validator/test passes
    - Acceptance:
        - (`tests/testTaxReconcile.py`) enforces three invariants:
        - **(i)** Σ Sch-K-1 Item-L ending-capital = Sch-L Line 21;
        - **(ii)** Sch-M-1 Line 1 = IncStmt Net Income;
        - **(iii)** BalSh Assets = Liabilities + Equity on both sides of the year.
    - Why:
        - These are the three "closing-the-books" reconciliations every CPA runs.
4. **Desc**`FILL.pdf` regression
    - Acceptance:
        - Form1065_FILL.pdf (pg1-6) values are ALL filled in
        - formObj.to_IRS() should populate with values to enable human review/fixup. 
    - Why:
        -  Non-negotiable for tax season delivery. 
5. **Desc**: A one-click export irs.zip emit package
    - Acceptance:
        - `<YR>YE_Tax_Records/<LLC_Name>_tax_packet_<YR>.zip`created by irs/irsForm services.
        - contains complete manifest : Form1065_FILL.pdf, K-1 FILL.pdf per partner, Trial Balance CSV, Book-to-Tax bridge CSV, and a CPA/auditor cover letter (.md/.pdf).
    - Why:
        - This is the Level-5 "Letters to downstream consumers" deliverable.
6. **Desc** Updsated Design/Workflow docs
    - Acceptance:
        - are updated to match the refactor (see §6).
    - Why:
        - Keeps documentation truthful — a precondition for auditability. |

Anything beyond 1-6 (e.g. state-level returns, e-file via MeF, multi-LLC
consolidation) is **explicitly out of scope** for v0.2.

---

## 2. Current-State Audit (Post-Task #35)

### What is done

| Level | Status | Evidence |
|-------|--------|----------|
| 1 Transactional | ✅ | `llcBank`, `llcAssets`, `llcExpRev`, `llcPayables`, `llcReceivables` all persist JSON, double-entry dual-account shape. |
| 2 Book | ✅ | `llcGeneralLedger` is the authoritative store; COA-seed rows render empty accounts; `include_coa_seed=True` flag in place. |
| 3 Analytical | ✅ | `llcBalanceSheet`, `llcIncomeStmt`, `llcOwnerEquity`, `llcPropertyEquity`, `llcCashFlowStmt` built; `testBalSh` / `testIncStmt` pass `GL == VIEW`. |
| 5 Tax Prep | 🟡 partial | `irs/Form1065.py`, `Sch_K1.py`, `Form4562.py`, `mapIRS2LLC.py`, `pdfFill/pdfMap/publishMap` exist. `FILL.pdf` generation regressed ~3–4 days ago. No book-to-tax bridge. No reconciliation test. |

### What is missing to hit Level 4 A–G

1.. **No Book-to-Tax bridge** — `irs/` jumps straight from financial
   statements to PDF fill. Sch-M-1 cannot be correct without this.
2. **`mapIRS2LLC.py` is code-driven**, not a JSON schema. The design doc
   explicitly calls for a JSON mapping; today the mapping is Python dicts
   embedded in form classes. This makes 2026-form updates expensive.
3. **`FILL.pdf` regression** — likely from a field-name drift in
   `irsFormFieldNames.py` or a pdfMap coordinate table after the `stmt/ →
   ledger/` import rewrite. Needs one diagnostic pass and a targeted fix.
4. **No Sch-M-2 partner-capital roll-forward** object.
5. **No reconciliation test** that asserts K-1 ∑ = Sch-L Line 21.
6. **No tax-packet emitter** (the `YE_Tax_Records/<YR>/` folder exists in
   the design; nothing writes the final bundle today).
7. **Docs are slightly out of sync**: level numbering skips 4; "Monthly
   Reconciliation" has two "Step 2" and two "Step 5" headings; `stmt/` is
   still referenced in both design and workflow docs.

---

## 3. Design Decisions (Assumptions Made Without Asking)

These lock-ins let the plan proceed without further clarification:

1. **Level numbering fix.** Workflow doc jumps 1,2,3,5,6,7. I am
   **renumbering** to 1,2,3,4,5 where:
   * 4 = *Tax Preparedness* (was mislabeled 5)
   * 5 = *Strategic (Controller/CFO)*
   * 6 = *Verification (Auditing)*
   But because the user's request names the goal "Level 4", I keep the
   **original label "Level 4 = Tax Preparedness"** in this plan doc and in
   the refactor itself. The doc-level renumbering is proposed as a
   *cosmetic* fix in §6 but held behind a one-line explanatory note.
2. **Trial Balance is a constructed object** (frozen `stmtDB`), not a
   recompute-on-read view. It is the canonical bridge between GL and every
   IRS form — so giving it a stable, testable shape is worth the tiny
   amount of extra code.
3. **Book-to-Tax bridge is declarative.** I will use a JSON file
   `Accts/bookToTax_<llc>.json` shaped as `[{acct, adjType, pct, note}]`
   so the CPA can edit it annually without code changes.
4. **PDF coords stay where they are.** Rebuilding the entire pdfMap layer
   is out of scope — I will only patch `irsFormFieldNames.py` to restore
   FILL.pdf.
5. **No e-file, no MeF, no state returns.** These are v0.3 candidates.
6. **K-1 partners** = the rows already present in `llcOwners.json`. No
   schema change to the owners object.
7. **Cover letter / audit letter** = Markdown templates rendered into PDF
   via the existing `pdf.py` pipeline. No new templating engine.
8. **Trial Balance / Book-to-Tax CSVs** — plain `csv.DictWriter`, no
   pandas dependency added.

---

## 4. The Shortest-Path Plan (Minimum Work, Ordered by Dependency)

The plan is decomposed into seven subtasks (**T36 … T42**). Each is
independently deliverable and independently testable.

## Book Activities 

### Proj_v0.2.1 - clean up current code base
**Scope.** cleanup the core object classes to make Book services more self-evident, reset Form1065 Tax views so there is 1 ui.Form1065.py module that services N pages views (not 1 page view to 1 module). 
**Changes.**
1. rename stmt.llc<object> -> ledger.stmt<object
2. fix all consumers of the renamed services, ie. fix all import from old name to new name
3. ensure all ledger modules adhere to core LLC_accounting API (ledgerObject base class)
    - fObj.load() -> list of dict : per transaction dict [Dual or Single Accounts]
    - fObj.save() -> json file of the raw data (transaction records)
    - fObj.to_DF() -> pd.Dataframe :  DF of raw transaction records, index = tID
    - fObj.to_agg() -> pd.Dataframe : aggregated view of the transaction record
        - output depends on aggOption - many cases depdending on Dual/Single acct
        - output aggregated view of all transactions [dual/single Account aggregation]
        - args for to_agg()
            - filterDict=  : filter raw transactional data (select subset of transactions)
            - by=          : by aggregate data based on by= 
            - aggDict=.    : groupby().agg dict
            - pretty=      : True | False : False=Raw, True=with std refer per row, subtotal both axis
            - aggregate option "by" = 'Trial' | 'BalSh' | 'IncStmt' | 'custom'
                - Trial = ['acctType']
                - BalSh = filter records: acctType in [Asset, Liability, Equity] then agg DF by 
                - IncStmt = filter records: acctType in [Income/Expense], agg by=[acctType, acct, Ledger]
                - custom:[list]
        - the output of .to_agg() is base input for downstream pipeline to stmt<object>, primary GL.to_agg
    - fObj.to_IRS() -> json
        - input to downstream Book-To-Tax services (ie. per Book fields) 
        - downstream consumes and constructs the per IRS form binding to tax fields
4. create test.testledgerAPI.py -- that calls all of the 'safe' API's  (safe = no modification of master DB)
5. merge ledgerGeneral into stmtGeneralLedger (after rename)
6. refractor setup_path into LLC profile, ie. llcProfile_<llcCName>.json (LLC=WBGroupLLC
**Done when.**
1. ensure that to_agg provides 1 row for every account per acctType, defined per COA, with a balance value.
**Token % estimate:** ~**?%**.


### Proj_v0.2.2 — Introduce `stmtTrialBalance` class as subclass of llcGeneralLedger (constructed stmt, frozen)
**Scope.** Thin class within llcGeneralLedger module; aggregates GL data with all COA accounts
`(acctMajor, acct)` into Debit/Credit columns; no new data source.
**Changes.** 1  class within stmtGeneralLeder module
2. `llcFinancialReport` to included it from ledger.stmtGeneralLedger import stmtTrialBalance
3. add  unit test  to test.testLedgerAPI.py that asserts Σ Debits = Σ Credits within EPS.
4. enhance view GeneralLedger to have 2 frames: TrailBalance (newFrame) then TransactionRecords (current table).  Each can be colapsable.  Connect the ViewBy options into the stmtGL.to_agg() parameters. 
**Done when.** 1. `stmtTrialBalance(llc)._rows` yields exactly one row per non-zero `(acctMajor, acct)` 
2. test that the set of acct per acctType equals the COA definition (ie. accts per acctType)
2. the zero-sum test passes.
**Token % estimate:** ~**?%**.

#### save release v0.2 to github

## Tax Activities 

#### start branch release/v0.3

### Proj_v0.3.1 - Clean up irs code base
**Scope.**
**Changes.**
**Done when.** 
**Token % estimate:** ~**7%**.

### Proj_v0.3.1 - Clean up irs code base
**Scope.**
**Changes.**
**Done when.** 
**Token % estimate:** ~**7%**.

### Proj_v0.3.1 - Clean up irs code base
**Scope.**
**Changes.**
**Done when.** 
**Token % estimate:** ~**7%**.


### Proj_v0.2.5 — Introduce Book-to-Tax bridge for all 3 tax forms
**Scope.** New `irs/bookToTax.py` class that loads
`Accts/bookToTax_<llc>.json` (seed with 50%-Meals and §179 placeholders),
exposes `bookNetIncome()`, `adjustments()`, `taxableIncome()`, and emits
a Sch-M-1 row list.
**Changes.** 1 new JSON seed (`Accts/bookToTax_WBGroupLLC.json`), 1 new
Python module, 1 wiring change in `irs/Form1065.py` to consume
bookToTax output instead of computing Sch-M-1 inline.
**Done when.** `bookToTax.taxableIncome()` = `bookNetIncome() + Σ
adjustments()` and the result flows into Form 1065 Sch-M-1 Line 1.
**Token % estimate:** ~**7%**.

#
### Proj_v0.2.4 — Fix `FILL.pdf` regression (unblocks everything downstream)
**Scope.** Diagnose why Form 1065 PDF no longer populates. The prime
suspect is stale import paths or field-name drift introduced during the
`stmt/ → ledger/` rewrite.
**Changes.** ≤ 3 files: `irs/Form1065.py`, `irs/irsFormFieldNames.py`,
possibly `irs/pdfFill.py`. No data-model change.
**Done when.** `python -m irs.formWorksheetCmd --fill` produces a
readable FILL.pdf with non-zero fields on Page 1 + Sch-L.
**Token % estimate:** ~**?%**.


## - Provision Form1065.py 

### T39 — Add `irs/Sch_M2.py` (partner-capital roll-forward)
**Scope.** Build Sch-M-2 from (Beginning Capital + Contributions + Net
Income − Distributions = Ending Capital), sourcing from `llcOwnerEquity`
which already carries the per-partner capital series.
**Changes.** 1 new module, 1 mapping stanza in `mapIRS2LLC.py`, re-use
`pdfFill` shim.
**Done when.** Sch-M-2 Line 9 = Σ K-1 Item-L ending capital = Sch-L
Line 21 (also the reconciliation test in T40).
**Token % estimate:** ~**5%**.

### T40 — Reconciliation test suite (`tests/testTaxReconcile.py`)
**Scope.** Three-invariant test matching acceptance criterion D:
1. Σ K-1 Item-L ending capital == Sch-L Line 21.
2. Sch-M-1 Line 1 == IncStmt Net Income per Books.
3. Sch-L Assets == Liabilities + Equity (both columns).
**Changes.** 1 new test file, re-uses `_aggHelpers`.
**Done when.** All three invariants are green for `WBGroupLLC` FY2025.
**Token % estimate:** ~**5%**.

### T41 — Tax-packet emitter (`irs/taxPacket.py`)
**Scope.** Python CLI that, given `(llc, year)`:
* copies Form1065 FILL.pdf, per-partner K-1 FILL.pdf,
* writes Trial Balance CSV and bookToTax CSV,
* renders `docs/templates/CPA_CoverLetter.md` → PDF via `pdf.py`,
* zips all of it into `YE_Tax_Records/<YR>/tax_packet_<YR>.zip`.
**Changes.** 1 new module + 1 cover-letter Markdown template.
**Done when.** `python -m irs.taxPacket WBGroupLLC 2025` produces the
zip and the zip opens cleanly with all five artifacts.
**Token % estimate:** ~**6%**.

### T42 — Docs refresh (`LLC_AccountingDesign.md`, `LLC_AccountingWorkflow.md`)
**Scope.** Apply the changes enumerated in §6 below.
**Changes.** Doc-only; no code touched.
**Done when.** Both docs (a) reflect `ledger/` (not `stmt/`), (b) fix
level/section numbering, (c) describe the Trial Balance + Book-to-Tax +
Tax-Packet pipeline, (d) reference the reconciliation test as a gate.
**Token % estimate:** ~**4%**.

### Sequencing

```
T36 (fix PDF)  ──┐
T37 (TrialBal) ──┼──►  T38 (BookToTax) ──►  T39 (Sch-M-2) ──►  T40 (Tests) ──►  T41 (Packet) ──►  T42 (Docs)
```

T36 and T37 are independent and could be interleaved; everything else is
strictly sequential because each downstream task consumes its predecessor.

### Total token estimate

| Subtask | % |
|---------|---|
| T36 — PDF regression fix | 6 |
| T37 — Trial Balance stmt | 4 |
| T38 — Book-to-Tax bridge | 7 |
| T39 — Sch-M-2            | 5 |
| T40 — Reconciliation tests | 5 |
| T41 — Tax-packet emitter | 6 |
| T42 — Docs refresh       | 4 |
| Contingency / diagnostic | 5 |
| **TOTAL** | **~42%** |

---

## 5. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | `FILL.pdf` regression is deeper than a field-name typo (e.g. the `pdfMap` JSON itself is stale). | Medium | Blocks T38+. | Time-box T36 at 6% — if not fixed in that window, fall back to emitting the Trial Balance + Sch-L numeric CSV as the Level-5 deliverable while PDF is investigated separately. |
| R2 | Book-to-Tax JSON schema drifts against what the CPA wants to edit. | Low | Annual rework. | Keep the schema to five columns and document it inline in `bookToTax_WBGroupLLC.json`. |
| R3 | Trial Balance + Sch-L disagree due to missing COA-seed accounts. | Low | Test fails. | `include_coa_seed=True` is already in place; the Trial Balance constructor uses that flag. |
| R4 | K-1 item-L for multi-class partners (GP/LP) is more complex than a flat sum. | Low for WBGroup (single class). | Only matters when a new LLC joins. | Out of scope for v0.2. |
| R5 | IRS 2026 forms change field names. | Medium (seasonal). | Annual. | T42 doc update explicitly flags the `pdfMap` JSON as the annual-update surface. |

---

## 6. Proposed Enhancements to Design / Workflow Docs (T42 detail)

### `LLC_AccountingWorkflow.md`

1. **Level numbering.** Current text lists levels 1, 2, 3, 5, 6, 7 (skipping
   4). Renumber to 1, 2, 3, 4, 5, 6 where 4 = Tax Preparedness — but add a
   one-line "formerly Level 4" note so historic references don't break.
   *This doc keeps the "Level 4" label because the user's request names it.*
2. **Monthly Reconciliation sections.** Two "#### 2" and two "#### 5"
   headings. Renumber cleanly as 1. GL & COA → 2. Trial Balance →
   3. Financial Statements → 4. Book-to-Tax Bridge → 5. IRS Form Mapping →
   6. Final Review / FILL.pdf → 7. Tax Packet Emission.
3. **Insert a new "Book-to-Tax Bridge" subsection** before Form 1065
   mapping, describing `bookToTax.py` and the declarative JSON.
4. **Replace the Form 1065 table's "COA Standard Account Name" column**
   with UAS names (`Acct.Rev.Rental`, `Acct.Exp.Depreciation`, etc.) —
   this is the FIXME already flagged in the doc.
5. **Fix the table row** "Sch L, Line 16 | BalSh | Accounts Payable" —
   currently has a missing `|` that breaks Markdown rendering.
6. **Add an explicit "Level 4 Exit Criteria" block** mirroring §1 of this
   plan doc.

### `LLC_AccountingDesign.md`

1. **Remove all references to `stmt/`** — the code lives under `ledger/`
   since Task #30. Specifically: §3 "Ledger components" block (lines
   139–148) still says `stmt/stmtFinancialReport.py` etc.; replace with
   `ledger/llcFinancialReport.py`, `ledger/llcTrialBalance.py` (new),
   `ledger/llcBalanceSheet.py`, `ledger/llcIncomeStmt.py`, etc.
2. **Add `ledger/llcTrialBalance.py`** to the component list.
3. **Add `irs/bookToTax.py`, `irs/Sch_M2.py`, `irs/taxPacket.py`** to the
   IRS Services list.
4. **Add a new "§5 Tax Preparedness Layer"** subsection enumerating A–G
   from §1 of this plan doc as the permanent exit gates for Level 4.
5. **Fix typo `smtGeneralLedger.py`** → `llcGeneralLedger.py`.
6. **Re-number the Validation Protocol** to four rules:
   1. Zero-Sum Rule — `GL.Debits == GL.Credits`.
   2. Equity Linkage — `ΔRE == IncStmt.NetIncome`.
   3. K-1 Consistency — `Σ K-1.ItemL == SchL.Line21`.
   4. Book-to-Tax Reconciliation — `bookToTax.taxableIncome ==
      SchM1.Line10` (new).

### `DataModel.md`

Minor: add `llcTrialBalance` to "Constructed Financial Data Objects".

---

## 7. Open Questions (Answered Here via Expert Assumptions)

> Per the user's instruction: I do **not** ask any of these of the user.
> Each is answered with the best accounting/software assumption so the
> project can proceed.

**Q1. Should Sch-M-1 adjustments live in a JSON file or be hard-coded?**
**A1.** JSON file (`Accts/bookToTax_<llc>.json`). Tax law changes yearly;
keeping it out of code lets the CPA edit it without a deploy.

**Q2. Should Trial Balance be a persistent `Accts/` artifact or a
recomputed stmt?**
**A2.** Constructed stmt only — consistent with the "stateless logic"
principle in the design doc. Persisting it would violate append-only.

**Q3. What about state income tax, property tax, self-employment tax?**
**A3.** Out of scope for v0.2. Mentioned in §6 roadmap but not
implemented.

**Q4. Should the CPA cover letter be dynamic (pulls LLC name, FY, partner
list) or static boilerplate?**
**A4.** Dynamic — a Markdown template with `{{llc_name}}`, `{{year}}`,
`{{partners}}` placeholders, rendered at packet-emit time.

**Q5. Do we need e-file (MeF) for Form 1065?**
**A5.** No. Paper/PDF filing is accepted for partnerships under 100
partners (IRS threshold). WBGroup is far below that.

**Q6. Should the Tax Packet include Form 4562 (Depreciation)?**
**A6.** Yes — it's already built. Add it to the packet with zero extra
work.

**Q7. How are non-deductible items (50% Meals) represented?**
**A7.** As rows in `bookToTax.json` with `adjType: 'non-deductible'` and
`pct: 50`. The bridge applies them to Sch-M-1 Line 4.

**Q8. Does the user want interactive PDF editing?**
**A8.** No — the design doc specifically mentions providing an "Edit
button on each field item mapping to allow human customization on a
small set" *within the UI*, not a live PDF editor. Out of scope for v0.2.

**Q9. Should there be a UI view for the Tax Packet?**
**A9.** Phase 2. For v0.2 a CLI is sufficient and reduces token load.

**Q10. How do we handle a partner who joins mid-year?**
**A10.** `llcOwners.json` already has `startDate`/`endDate` fields; the
K-1 roll-forward uses prorated ownership. Confirmed against
`ledger/llcOwners.py` — no schema change needed.

---

## 8. Will Additional Usage Be Needed?

**Answer: No.**

**Justification.** The remaining work is ~42% of current usage (with a
5% contingency included). The codebase is already at Level 3 (Analytical)
and has ~60% of the Level-5 pieces present — the refactor is mostly
plumbing and reconciliation, not new data-model design. The only risk
item that could force a request for additional usage is R1 (PDF
regression turns out to be deep `pdfMap` work); that is mitigated by a
time-boxed fallback in T36. Under all other scenarios the project
completes within the current allocation.

If the user adds scope beyond acceptance criteria A–G (e-file, state
returns, multi-LLC consolidation, interactive PDF editing), additional
usage **will** be required — those are explicitly v0.3 features and are
not priced into the 42% estimate.

---

## 9. Appendix — Minimal File Manifest for Level 4 Completion

New files (7):
```
ledger/llcTrialBalance.py
irs/bookToTax.py
irs/Sch_M2.py
irs/taxPacket.py
Accts/bookToTax_WBGroupLLC.json
tests/testTrialBalance.py
tests/testTaxReconcile.py
docs/templates/CPA_CoverLetter.md
```

Modified files (≤ 6):
```
irs/Form1065.py            # consume bookToTax; wire Sch-M-2
irs/irsFormFieldNames.py   # FILL.pdf regression fix
irs/mapIRS2LLC.py          # add Sch-M-2 mapping stanza
ledger/llcFinancialReport.py   # include Trial Balance
docs/LLC_AccountingDesign.md
docs/LLC_AccountingWorkflow.md
```

Touched lines total estimate: **≤ 600 LOC** across the eleven-ish files
above — well within the shortest-path bar.
