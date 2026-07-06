# design_BUS_02.01 — Book Agent - the bookkeeper

**Stage:** 02
**Status:** Issue and PROPOSAL — pending review and GO

----

## Book Agent 

The accounting workflow is broken into the following activities:
| Order | Activity        | Pipelines              | Actions | Truth | 
|----|----|----|----|
| 1 | Transactional   | Operations             | Constant activities | Bank Records, Requisitions | 
| 2 | Books           | BankToBooks            | Ingestion, Journaling | RealDB | 
| 3 | Analytical      | GL, BS, IS             | Review and balancing | Immutable, GL is pivotal, Reconciliation | 
| 4 | Tax Preparation | BooksToIRS             | IRS compliance | Forms and IRS Expertise | 
| 5 | Strategic       | Long term, risk        | HomeFS, Reports, YearStart, YE |
| 6 | Verification    | Audits/Fiscal Closeout | Ext. Review | 

The main driver of changes is during the Books phase where the ledgers are constantly being updated.   The core foundation of accounting is the `Monthly Reconcilation` where the actual business and the books reconcile to ensure everything verifies and is balanced.   But **where is the "StateOfTheBooks" logged to ensure that the business can recover should some corruption occur in the future**?

Enter the `bookAgent` that coordinates all the activities (journaling, statements and reports) and assures the integrity of the Books (GL, BS, IS).  The basic idea is that there are artifacts X state.

1. RealDB ==> BookState(realDB) on date YYYY.MM.DD
2. ViewDB ==> BookState (viewDB) 


## Tracking the "State of the Books"?

**Proposal: a `BookState` snapshot, structurally identical to the existing `bookNS_integrity.json` pattern, computed at multiple levels and compared against each other.**

The bookState is computed on a **FY** - Fiscal Year basis. A given artifact (RealDB/View) may span multiple years, but the bookState filters records and balances based on a fiscal year setting. 

```jsonc
// BookState — computed on demand, not persisted per-request
{
  "objects": {
    "llcAssets":      {"sha256": "...", "mtime": "2026-07-02T14:15:06", "recordCount": 13},
    "llcExpRev":      {"sha256": "...", "mtime": "2026-07-02T14:15:06", "recordCount": 106},
    "llcPayables":    {"sha256": "...", "mtime": "2026-06-07T15:04:15", "recordCount": 4},
    "llcReceivables": {"sha256": "...", "mtime": "2026-06-07T15:04:15", "recordCount": 1},
    "GeneralLedgerDF": {"sha256": "...", "mtime": "2026-06-07T15:04:15", "recordCount": 248},
    "GL_Trial":       {"Bal_Asset" : ###.##, "Bal_Equity", ###.##, "Bal_Liability": ###.##, "Bal_FY": ###.##)}
  },
  "fiscalYear" : "2025".  <-- or "2026",
  "computedAt": "2026-07-02T14:36:00",
  "source" : "RealDB:<path>",   <-- Can be "BookView"
}
```

Each instance of this schema answers "what did RealDB for fiscalYear 202x look like at moment X." Different consumers hold onto their own instance, captured when they last built themselves, and compare it against a freshly-computed one on access:

1. **RealDB BookState** — computed fresh from `Accts/*.json` file contents right now. Cheap (four file reads + hashes), always current by construction — same role as `bus_sha` already plays in `bookNS_integrity.json`.
2. **BookView BookState** — the RealDB BookState that was true when `BooksContext.gl_rows` (and any derived stmtBS/stmtIS/stmtGL) was last computed. Stored alongside the cached snapshot (`BooksContext._source_state`). *(Dimension 1 fix.)*
3. **GL-bypass view BookState** — the same comparison, applied to `stmtPropertyEquity`/`stmtOwnerEquity`'s default construction path, so those views can at least report "I'm N edits behind BooksContext" even before the GL migration lands. *(Dimension 3 mitigation — the real fix is finishing the migration, but this makes the interim gap visible instead of silent.)*

**Staleness check** (mirrors `formDiagState.check_integrity()` exactly): `BookState.compute() != self._source_state` → the view is stale, force recompute before serving. This:
- Replaces the ad hoc single-file mtime check in `utilWorkingDB.load()` with one reusable, inspectable object.
- Can be exposed as a JSON API (`/api/bookState`) for diagnostics — the same shape `bookNS_integrity.json` already is.
- Extends naturally to the next layer down (bookNS → FILL.pdf) using the identical schema, so the whole pipeline — RealDB → BookViews (GL/BS/IS) → GL-bypass views (K-1/PropEquity) → bookNS (IRS mappings) → FILL.pdf — has one consistent integrity-check vocabulary instead of three different ad hoc mechanisms (mtime compare, SHA compare, "nothing" for BookViews and GL-bypass views).

**Home page Financial Status integration**: the Home Financial Snapshot (`api_home_snapshot`, stacked bar chart + metrics table, v1.3) is the one view every session touches first. It should call the RealDB-vs-BookView `BookState` comparison on load and surface a visible status chip:
- 🟢 **Books in sync** — BookView state matches current RealDB state.
- 🟡 **Books stale — recompute in progress** — mismatch detected, auto-triggered a `books.invalidate()` + recompute before rendering (self-healing, same as `utilWorkingDB.load()` already does for raw records).
- 🔴 **Books stale — recompute failed / mismatch after refresh** — would only happen if RealDB itself is inconsistent (e.g. mid-write from another process); worth a hard error banner rather than silently serving numbers, since this is exactly the failure mode that went undetected today.

This turns "is the app currently telling me the truth" from an invisible property the operator has no way to check into a one-glance status on the page they land on first every session.

