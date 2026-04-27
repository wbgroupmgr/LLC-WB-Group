# LLC Data Flow Design

**Scope:** End-to-end data flow for the LLC accounting application, aligned
with the **Levels of Accounting Tasks** defined in
`docs/LLC_AccountingWorkflow.md`.  The diagram set covers Transactions →
Book → Analysis → Tax Preparation → Strategy → Verification.
**Phase:** ProjectLevel3 v0.2 (Book) → ProjectLevel4 v0.3 (Tax) boundary.
**Last updated:** 2026-04-26 (v0.2.4.8 — aligned to 6-level design)

---

## Why this doc exists

The per-module API reference for the IRS layer lives in
`irs/docs/irsForm1065_book2irsDeisng.md` and `irs/docs/Readme_Form1065.md`.
Those documents describe *what each class does*.  This doc instead answers
the question:

> **How does a single rent check become a number in box `P1_1a` of the
> filed Form 1065 PDF — and how does the same data underpin every
> downstream reporting, tax, and strategy artefact?**

It is the canonical overview for the v0.2 refactor that consolidated all
data wrangling into `ledger/` and replaced the ad-hoc UI loaders with a
single uniform Book API.

---

## Design notes

These are the binding rules for every diagram in this set:

1. **Diagrams are aligned with `Levels of Accounting Tasks`** as defined in
   `docs/LLC_AccountingWorkflow.md`.  The LLC accounting *services* are
   organised around the same boundaries:

   | Level | Name             | Services / artefacts                                                  |
   |------:|------------------|-----------------------------------------------------------------------|
   | 1     | Transactions     | `ledger.llc*` editable JSON DBs + `llcProfile_<LLC>.json`             |
   | 2     | Book             | `ledger.stmt*` constructed (immutable) objects — GL / BS / IS / OE / PE / Profile |
   | 3     | Analysis         | `ledger.stmtTrialBalance` (TB) + `ledger.stmtFinancialReport` (FR)    |
   | 4     | Tax Preparation  | `irs.irsForm` base + `irs.Form1065`, `irs.Sch_K_1`, `irs.Form4562`    |
   | 5     | Strategy         | *future* — Planning / Forecasting / Tax Strategy / Risk Assessment    |
   | 6     | Verification     | *future* — external audit review of financials                        |

2. **The `.mmd` files are the canonical diagram source.**  Do **not** edit:
   - `docs/llcDataFlow_HL.mmd`  (.svg)  — High-Level all-levels overview
   - `docs/llcDataFlow_L1_3.mmd` (.svg) — Levels 1–3: Transactions → Book → Analysis
   - `docs/llcDataFlow_L4_6.mmd` (.svg) — Levels 4–6: Tax Prep → Strategy → Verification

   This `.md` file is the narrative companion; the diagrams are the source
   of truth for node names and arrows.

3. **Node-prefix convention** inside the diagrams:
   - `ƒ(x)` — function / service (ledger / irs method, or any callable).
   - `🗓️` — table-shaped data object (DataFrame, dict, or row-addressable
     stmt\* object) held in memory and **passed between functions**.

   The active design intent is to **move away from save/load JSON files
   between functions** in the workflow.  JSON sources at Level 1
   (transactions / profile) and PDF sinks at Level 4 (FILL.pdf / fillDict
   cache) remain on disk because they are user-edited or filed deliverables;
   intermediate stmt\* / NSpace / fillDict objects flow as in-memory
   `🗓️` table-objects.

4. **Book → IRS FILL.pdf workflow** is now defined by the **Level 4 Tax
   Preparation** diagram (`llcDataFlow_L4_6.mmd`).  The 4-step pipeline is:

   1. `ledger.stmtProfile.getNSpace(irsFormName)` → `🗓️ bkGLNSpaceDict`
      (LLC + GL namespace, indexed by `[ObjID][Acct_UAS]`).
   2. `irsForm._buildNSpace()` reads `<FormName>_IRS.pdf` → `🗓️ taxNSpaceDict`
      (AcroForm field discovery).
   3. `irsForm._resolveTaxData()` cross-references `bkNSpaceDict` ×
      `taxNSpaceDict` → `🗓️ taxfillDict` (the final `[{F###, fval}]` map).
   4. `irsForm.savePDF(fillDict)` applies the fillDict and writes
      `<FormName>_FILL.pdf`.

   This replaces the older `_buildFillDict` / `saveFILL` two-step
   nSpaceMap-only flow.

5. **`API_BK` — the Book API.**  The Level 1–3 diagram introduces an
   `API_BK` node that represents the **cumulative Book API across the
   ledger services** (every `stmt*` is a contributor; every Analysis-level
   consumer reads through `API_BK`).  Documenting that API surface is a
   **future task** — not part of v0.2.4.8.

6. This `.md` is the place to record version history and human-readable
   commentary; the diagrams stay machine-rendered from their `.mmd`
   source.

---

## High-Level Overview

Refer to *Levels of Accounting* in `docs/LLC_AccountingWorkflow.md`.

![llcDataFlow High Level](llcDataFlow_HL.svg)

## Levels 1–3: Transactions → Book → Analysis

![llcDataFlow_L1_3](llcDataFlow_L1_3.svg)

## Levels 4–6: Tax Preparation → Strategy → Verification

![llcDataFlow_L4_6](llcDataFlow_L4_6.svg)

---

## Layer responsibilities (aligned with the 6 Levels)

| Level | Layer            | Module path                                | Responsibility                                                                                       | Mutates? |
|------:|------------------|--------------------------------------------|------------------------------------------------------------------------------------------------------|----------|
| 1     | Transactions     | `Accts/llc*_<LLC>.json`, `llcProfile_<LLC>.json` | Human-editable book-entry DBs + entity / Profile / Owners / Customers                              | ✅ edited via the UI |
| 2     | Book             | `ledger/stmt*.py`                          | Constructed immutable tables — GL / BS / IS / OE / PE / Profile                                      | ❌ `save()` raises `InvalidRequestError` |
| 3     | Analysis         | `ledger/stmtTrialBalance.py`, `ledger/stmtFinancialReport.py` | Roll-ups & cross-statement reconciliation (TB acctType aggregation; FR taxData bundle)             | ❌ read-through |
| 4     | Tax Preparation  | `irs/irsForm.py`, `irs/Form1065.py`, `irs/Sch_K_1.py`, `irs/Form4562.py` | 4-step pipeline (NSpace → BuildNSpace → ResolveTaxData → savePDF) producing `<Form>_FILL.pdf`     | ❌ idempotent — re-running rebuilds from `stmt*` |
| 5     | Strategy         | *future*                                   | Planning, Forecasting, Tax Strategy, Risk Assessment reports                                         | ❌ |
| 6     | Verification     | *future*                                   | External audit review of financials                                                                  | ❌ |

The (legacy) "UI" tier is no longer a level — `ui/` is a presentation-only
shell over Levels 2–4 services and contributes no data construction.  Tax
views since v0.2.4.7 embed the `<Form>_FILL.pdf` directly (`irs_pdf_view.html`).

---

## Book to IRS FILL.pdf

Refer to **Level 4: Tax Preparation** in `docs/llcDataFlow_L4_6.mmd`
(`.svg`).  The four pipeline steps map to these in-memory artefacts:

| Step | Producer                                   | Artefact          | Notes                                  |
|------|--------------------------------------------|-------------------|----------------------------------------|
| 1    | `ledger.stmtProfile.getNSpace(irsFormNm)`  | `🗓️ bkGLNSpaceDict` | LLC + GL NSpace, `[ObjID][Acct_UAS]`   |
| 2    | `irsForm._buildNSpace()`                   | `🗓️ taxNSpaceDict`  | AcroForm field discovery from `<F>_IRS.pdf` |
| 3    | `irsForm._resolveTaxData(bkNS, taxNS)`     | `🗓️ taxfillDict`    | Final `[{F###, fval}]`                 |
| 4    | `irsForm.savePDF(fillDict)`                | `<F>_FILL.pdf`    | Filed deliverable + `_fillDict.json` cache |

> **Migration note.**  The earlier two-step description in this doc
> (`_buildFillDict` followed by `saveFILL`, with `nSpaceMap()` returning
> `Dict[(tblID, rowNm, colNm) → List[fillDict]]`) is **superseded** by the
> Level-4 four-step pipeline above.  The `nSpaceMap()` function is retained
> in `irs/Form1065.py` for backward compatibility with the legacy
> `_buildFillDict` callsite, but it is no longer the canonical entry point.

---

## What changed across v0.2 (book vs. tax boundary)

| Concern | v0.1 (pre-refactor) | v0.2 (current) |
|---|---|---|
| Where is data wrangling? | Scattered across `ui/llcIRSViewBase.py` loaders, `stmtFinancialReport.taxData()`, and per-view helpers | **Only in `ledger/`** — `stmt*` objects build themselves from source JSON; UI is a pure consumer |
| How does the view read `llc.entity` / `llc.F1065`? | Direct dict reads in `_llcIRSViewBase._ev` / `_fv_prof` | `ledger.stmtProfile` — row-addressable `stmtDB` subclass, same uniform API as every other `stmt*` |
| How is Form 1065 rendered in the UI? | Five separate Flask views (`llcForm1065SchBPg2/3/4`, `llcForm1065SchKPg5`, `llcForm1065Pg6`) each constructing rows | **PDF embed** (v0.2.4.7) — `ui.llcForm1065` and `ui.llcFormK1` serve `<Form>_FILL.pdf` inline; no row-table reconstruction |
| How are IS/BS values sourced for stats? | `stmtFinancialReport.taxData()` (requires `llc.bk` initialization) | Direct `stmtIncomeStmt` + `stmtBalanceSheet` queries (no `llc.bk` dependency) |
| Income-row sign convention | Depended on taxData JSON post-processing | Explicit: `stmtIncomeStmt` stores `Balance = Debit − Credit`; Income rows have negative Balance; views flip sign at display time |
| Cross-service API surface | Implicit via direct `stmt*` imports | **`API_BK`** — cumulative Book API node introduced in `llcDataFlow_L1_3.mmd` (formal documentation pending) |

---

## One transaction, end-to-end

Trace a single rent payment of **\$1,200** booked on 2025-06-15 all the way
through the pipeline (Levels 1 → 4):

1. **Book entry (Level 1)** — user adds a row to
   `Accts/llcExpRev_WBGroupLLC.json` via the Exp/Revenue editor:
   `{dt: "2025-06-15", amt: 1200.00, aType: "Credit",
   acct: "Rental_Income", acctType: "Income",
   desc: "June rent — unit 3"}`.
2. **GL expansion (Level 2)** — `ledger.stmtGeneralLedger` reads that
   JSON on instantiation, runs `toDoubleEntry()`, and emits **two** GL
   rows: one Credit against `Rental_Income`, one Debit against the
   corresponding cash account.  Rows are immutable after `_finalize()`.
3. **Trial Balance roll-up (Level 3)** — `ledger.stmtTrialBalance` sums
   by `acctType`, so `Income.Rental_Income` rolls up alongside other
   revenue accounts.
4. **Income statement (Level 2)** — `ledger.stmtIncomeStmt` filters GL
   rows to `acctType ∈ {Income, Expense}`, giving the per-account
   Balance column.
5. **Book NSpace (Level 4 step 1)** —
   `ledger.stmtProfile.getNSpace("Form1065")` produces `🗓️ bkGLNSpaceDict`
   indexed by `[ObjID][Acct_UAS]`, including the `Rental_Income`
   aggregate.
6. **Form NSpace (Level 4 step 2)** — `irs.Form1065._buildNSpace()`
   reads `Form1065_IRS.pdf` and produces `🗓️ taxNSpaceDict` listing every
   AcroForm field with its `(fID, logicalKey, page, location, fType)`.
7. **Resolve (Level 4 step 3)** — `irs.Form1065._resolveTaxData()`
   cross-references `bkNSpaceDict × taxNSpaceDict`, producing the final
   `🗓️ taxfillDict` where `f41 → 1200.00` for `P1_1a` (Rents).
8. **Save (Level 4 step 4)** — `irs.Form1065.savePDF(taxfillDict)` writes
   `Form1065_FILL.pdf` (filed deliverable) and the `_fillDict.json` cache
   used by the UI tax-view embed.
9. **UI display** — `ui.llcForm1065` serves the rendered
   `Form1065_FILL.pdf` inline via the `/forms/Form1065.pdf` route — no
   row-by-row reconstruction at the view layer.

---

## Invariants the diagrams enforce

- **One-way flow.**  Arrows never point backwards from a higher level to a
  lower one.  The only writes outside `Forms_IRS/` are user-driven edits
  to the Level-1 JSON DBs.
- **`stmt*` is the only data source for Level 4.**  IRS forms never open
  Level-1 source JSON directly; they go through `stmtProfile.getNSpace()`
  and (for stats) through `stmtFinancialReport` / `stmtTrialBalance`.
- **UI holds no data.**  Since v0.2.4.7 every tax view embeds the canonical
  `<Form>_FILL.pdf` and reads stat chips directly from `stmtIncomeStmt` +
  `stmtBalanceSheet`.  No row-table reconstruction.
- **Every cell is addressable.**  Every `stmt*` row carries
  `(tblID, rowNm, colNm)`; every `taxfillDict` entry carries
  `(fID, logicalKey, tblID, rowNm, colNm)`.  Any number on the filed PDF
  traces back to the exact book transaction that produced it.
- **In-memory hand-off, on-disk anchors.**  Per design note 3, only Level-1
  inputs and Level-4 outputs persist as files; intermediate
  `bkGLNSpaceDict` / `taxNSpaceDict` / `taxfillDict` flow as in-memory
  `🗓️` objects.

---

## Inconsistencies between the prior `.md` and the new `.mmd` files

These are the gaps surfaced when reconciling the previous version of this
doc against the canonical `.mmd` source.  They are listed for transparency;
the doc body above has been rewritten to match the diagrams, so each item
below is *resolved in the current text* but worth flagging because legacy
references may still appear in cross-linked docs / notebooks / code
comments.

1. **Doc title / scope.**  The previous title was *"IRS Form 1065 —
   Book-to-IRS Data Flow"*; the diagrams cover **all six levels** of the
   accounting workflow, not just F1065.  Title is now *"LLC Data Flow
   Design"*.
2. **HL diagram filename mismatch.**  The previous body linked
   `llcDataFlowHL.svg`; the file on disk is `llcDataFlow_HL.svg`
   (underscore).  Fixed in the *High-Level Overview* section above.
3. **Layer count.**  The previous *Layer responsibilities* table used 5
   rows centred on `Source / Ledger / IRS / UI / Filed artifacts`.  The
   `.mmd` set is organised around the **6 Levels of Accounting Tasks**;
   the table has been re-keyed accordingly.
4. **Book-to-IRS workflow description.**  The previous body documented a
   two-step `_buildFillDict` / `saveFILL` flow with a single
   `nSpaceMap()` function.  The `llcDataFlow_L4_6.mmd` defines a
   **four-step pipeline** (`getNSpace` → `_buildNSpace` →
   `_resolveTaxData` → `savePDF`) with three distinct in-memory
   artefacts (`bkGLNSpaceDict`, `taxNSpaceDict`, `taxfillDict`).  The new
   *Book to IRS FILL.pdf* section reflects this.
5. **Legacy Level-3 wording.**  Earlier text said *"`stmtFinancialReport`
   composes from `stmt*` under the hood, yielding `is_data['rent_income']`"*.
   The diagram now places `stmtFinancialReport` and `stmtTrialBalance`
   together at **Level 3 (Analysis)** and treats them as consumers of the
   shared `API_BK`, not as data constructors.
6. **UI tier removed from the layer model.**  The previous *Invariants*
   block described `ui.llcForm1065` "caching a `stmtProfile` for stats and
   calling `Form1065.nSpaceMap()` + sub-view `.load()` methods".  After
   v0.2.4.7 the UI tax views are PDF embeds with no row construction; the
   invariants list has been updated.
7. **Module reference for Tax Prep.**  The note "all data construction
   happens in ledger services (v0.2.4)" is correct but incomplete; the
   diagrams add `irs.irsForm` (base class) explicitly to Level 4
   alongside `Form1065`, `Sch_K_1`, `Form4562`.
8. **`API_BK` is new.**  The Level-1–3 diagram introduces an `API_BK`
   node not present in the prior `.md`.  Per design note 5, it represents
   the cumulative Book API surface across the `ledger.stmt*` services and
   will be documented separately in a future task.
9. **Node prefix convention is new.**  Per design note 3, the diagrams
   use `ƒ(x)` for services and `🗓️` for table-objects.  The old `.md`
   used inline-code names with no consistent prefix.
10. **Strategy / Verification levels.**  Levels 5 and 6 (Strategy &
    Verification) appear in `llcDataFlow_HL.mmd` and
    `llcDataFlow_L4_6.mmd` but were absent from the prior `.md` entirely.
    They are listed as *future* in the design notes above.
11. **Pg2-6 sub-views.**  The previous *What changed in v0.2* table
    described a "consolidated Pg2–6 collapsible-frames page" rendered by
    `form1065_view.html`.  That intermediate consolidation (v0.2.4.5)
    was itself superseded by the v0.2.4.7 PDF-embed design; the current
    table reflects the final state.
12. **Doc filename with typo.**  The "See also" reference points at
    `irs/docs/irsForm1065_book2irsDeisng.md` ("Deisng" is a known typo
    in the existing repo; intentionally preserved to keep the link
    valid).

---

## Open follow-ups

- **Document `API_BK`** (the cumulative Book API surface) — *future task,
  per design note 5.*
- **FILL.pdf is currently empty for all forms.**  The `Form1065_fillDict.json`
  on disk has 440 entries with `publish=False` and empty values, and both
  `Form1065_IRS.pdf` and `Form1065_FILL.pdf` carry zero filled fields.
  The new `tests/testIrsFillPDF.py` (v0.2.4.7) detects this state and
  prints a vacuous-round-trip notice.  Fixing the empty FILL.pdf is the
  **next task** and is intentionally out of scope for this doc revision.
- **Levels 5 & 6** (Strategy, Verification) need module owners.

---

## VERSION

| Tag       | Date       | Change |
|-----------|------------|--------|
| v0.2.4.6  | 2026-04-24 | Initial Form-1065-only "Book-to-IRS Data Flow" doc with embedded diagram. |
| v0.2.4.7  | 2026-04-24 | Tax-view restructure: UI now embeds `<Form>_FILL.pdf`; sibling page-slice views retired; `tests/testIrsFillPDF.py` added. |
| v0.2.4.8  | 2026-04-26 | **This revision.** Doc retitled to *"LLC Data Flow Design"*. Aligned with `Levels of Accounting Tasks` (6 levels). Diagram source split into `llcDataFlow_HL.mmd`, `llcDataFlow_L1_3.mmd`, `llcDataFlow_L4_6.mmd` (canonical, **not** edited by this doc). Adopted node-prefix convention (`ƒ(x)` / `🗓️`) and the in-memory hand-off principle (move away from save/load JSON between functions). Book-to-IRS workflow re-described as the **Level-4 four-step pipeline** (`getNSpace` → `_buildNSpace` → `_resolveTaxData` → `savePDF`) producing `bkGLNSpaceDict` / `taxNSpaceDict` / `taxfillDict`. Introduced `API_BK` placeholder for the cumulative Book API surface (formal doc deferred). Levels 5 (Strategy) and 6 (Verification) listed as future. Inconsistencies between the prior `.md` and the canonical `.mmd` files explicitly enumerated. |

---

## See also

- `docs/LLC_AccountingWorkflow.md` — defines the **6 Levels of Accounting
  Tasks** that anchor every diagram in this set.
- `docs/LLC_AccountingDesign.md` — book-level architecture (Level 1 →
  Level 2 detail).
- `docs/llcDataFlow_HL.mmd` / `.svg` — high-level diagram (canonical).
- `docs/llcDataFlow_L1_3.mmd` / `.svg` — Levels 1–3 detail (canonical).
- `docs/llcDataFlow_L4_6.mmd` / `.svg` — Levels 4–6 detail (canonical).
- `irs/docs/irsForm1065_book2irsDeisng.md` — per-class IRS API surface
  and pre-refactor architecture diagram (kept for historical reference).
- `irs/docs/Readme_Form1065.md` — legacy IRS workflow (`_buildNSpace` /
  `saveNSpace` / `_buildFillDict` / `saveFILL`); to be reconciled with
  the Level-4 four-step pipeline in a follow-up.
- `docs/ProjectLevel4_v0.3 Tax Activites.md` — upcoming Phase-3 tax work
  (K-1 generation, CPA review handoff) that builds on this pipeline.
- `tests/testIrsFillPDF.py` — round-trip integrity test for Level-4
  artefacts (IRS.pdf vs FILL.pdf vs fillDict.json).
