# UI View Design — GL / IS / BS Views

**Last updated:** 2026-05-05  
**Scope:** Frame 1 (Trial Balance) · Frame 2 (Transaction Records)  
**Template:** `general_ledger_view.html` v0.2.3.6

---

## 🔵 INPUT — Server → Template (Context Variables)

These are the variables the Flask route **must inject** into `render_template(...)`:

| Variable | Type | Description |
|---|---|---|
| `obj_type` | `str` | Always `"stmtGeneralLedger"` — used to build navigation URLs |
| `view_title` | `str` | Display label (e.g. `"General Ledger"`) |
| `app_title` | `str` | Top-level app name shown in the title bar |
| `frames` | `dict` | Core data object — see shape below |
| `stats_labels` | `list[dict]` | Pre-flattened stats chips: `[{group, value, text}, ...]` |

### `frames` Object Shape

```
frames
├── view_by           str         — active filter value (e.g. "All", "Asset")
├── view_by_options   list[str]   — dropdown options for the ViewBy select
├── meta              dict        — arbitrary metadata rendered as JSON
│
├── tb                            ── Frame 1: Trial Balance
│   ├── rows          list[dict]  — each: {acctType, acct, acctMinor, propNm,
│   │                                       acctSub, Debit, Credit, Balance}
│   ├── is_balanced   bool        — drives the green/red banner
│   └── totals        dict        — {Debit: float, Credit: float, Balance: float}
│
└── tx                            ── Frame 2: Transaction Records
    ├── rows          list[dict]  — each: {Status, dt, acctType, acct, acctMinor,
    │                                       aType, amt, desc, acctSub, refDB, propNm}
    └── summary       dict        — {dup_count: int, ...}
```

### Row Dict Shapes

```python
# frames.tb.rows — each row dict  (Frame 1)
{
    "acctType":  str,
    "acct":      str,
    "acctMinor": str,   # optional; renders blank if absent
    "propNm":    str,   # optional; short property name — renders blank if absent
    "acctSub":   str,
    "Debit":     float,
    "Credit":    float,
    "Balance":   float,
}

# frames.tx.rows — each row dict  (Frame 2)
{
    "Status":    str,
    "dt":        str,
    "acctType":  str,
    "acct":      str,
    "acctMinor": str,   # optional; renders blank if absent
    "aType":     str,
    "amt":       float,
    "desc":      str,
    "acctSub":   str,
    "refDB":     str,
    "propNm":    str,   # optional; short property name — renders blank if absent
}
```

All optional fields use `row.get("<field>", "")` in the template — **missing keys render as empty cells without errors**.

---

## 📐 Frame Column Definitions

### Frame 1 — Trial Balance

**8 columns:** `acctType · acct · acctMinor · propNm · acctSub · Debit · Credit · Balance`

| # | Column | Width | Notes |
|---|---|---|---|
| 1 | `acctType` | 110 px | Section grouping key |
| 2 | `acct` | 140 px | `.acct-name` monospace style |
| 3 | `acctMinor` | 140 px | `.acct-name` monospace style |
| 4 | `propNm` | 110 px | Short property name; small font, muted colour |
| 5 | `acctSub` | 160 px | Monospace, muted colour |
| 6 | `Debit` | 120 px | Right-aligned, `amt-pos` when > 0 |
| 7 | `Credit` | 120 px | Right-aligned, `amt-pos` when > 0 |
| 8 | `Balance` | 120 px | Right-aligned, `amt-pos`/`amt-neg` |

**colspan map:**

| Row type | colspan | Covers |
|---|---|---|
| Section-header | 8 | full width |
| Subtotal label | 5 | `acctType · acct · acctMinor · propNm · acctSub` |
| Grand-total label | 5 | same |
| Empty-state | 8 | full width |

---

### Frame 2 — Transaction Records

**11 columns:** `Status · dt · acctType · acct · acctMinor · aType · amt · desc · acctSub · refDB · propNm`

| # | Column | Width | Notes |
|---|---|---|---|
| 1 | `Status` | 70 px | `.dup-flag` amber style when set |
| 2 | `dt` | 100 px | Date string |
| 3 | `acctType` | 110 px | |
| 4 | `acct` | 120 px | `.acct-name` monospace style |
| 5 | `acctMinor` | 120 px | `.acct-name` monospace style |
| 6 | `aType` | 70 px | |
| 7 | `amt` | 100 px | Right-aligned, `amt-pos`/`amt-neg` |
| 8 | `desc` | flexible | Description free-text |
| 9 | `acctSub` | 120 px | Monospace, muted colour |
| 10 | `refDB` | 90 px | Small font (12 px) |
| 11 | `propNm` | 110 px | Short property name; small font, muted colour |

**colspan map:**

| Row type | colspan |
|---|---|
| Empty-state | 11 |

---

## 🟢 OUTPUT — Client → Server (HTTP Requests)

Two outbound calls are triggered by user interaction — both are plain `GET` navigations (no AJAX/fetch):

### 1. ViewBy Filter Change

**Trigger:** User changes the `<select id="viewBySelect">` dropdown

```
GET /view/stmtGeneralLedger?viewBy=<selected_value>
```

- If value is `"All"` → `GET /view/stmtGeneralLedger` (no query param)
- Implemented via `applyViewBy()` → `window.location.href`

### 2. Refresh Button

**Trigger:** User clicks the **Refresh** button

```
GET /view/stmtGeneralLedger
GET /view/stmtGeneralLedger?viewBy=<current_view_by>   ← if not "All"
```

- Implemented via `buildViewUrl()` → `window.location.href`

---

## 🟡 CLIENT-SIDE ONLY (No Server Call)

| Interaction | Behavior |
|---|---|
| **JSON button** | Toggles `<details id="jsonPane">` via `togglePane()` — pure DOM |
| **Metadata row** | Native `<details>` expand/collapse |
| **Frame 1 / Frame 2 headers** | Native `<details open>` expand/collapse |

---

## Architecture Summary

```
Browser                          Flask Server
  │                                   │
  │  GET /view/stmtGeneralLedger      │
  │  ?viewBy=Asset  ──────────────►   │  render_template(
  │                                   │    "general_ledger_view.html",
  │  ◄──── HTML (frames, stats) ────  │    obj_type, view_title, app_title,
  │                                   │    frames, stats_labels
  │  [User changes ViewBy]            │  )
  │  GET /view/stmtGeneralLedger      │
  │  ?viewBy=Liability  ──────────►   │
```

The page is **fully server-side rendered** — no AJAX calls, no REST endpoints, no client-side data fetching. All interactivity is either a full-page navigation or pure HTML/DOM manipulation.

**Unchanged items:**
- CSS — no new styles added; `.acct-name` reused for `acctMinor`; muted `color:#6b7280` reused for `propNm`
- JavaScript — `applyViewBy`, `buildViewUrl`, `togglePane` unchanged
- Title bar, stats chips, metadata pane — unchanged
- Imbalance banner logic — unchanged
- JSON debug pane — unchanged (renders full `frames` object as-is)

---

## Change Log

### v0.2.3.5 — 2026-05-05

#### 1. `acct` → `acct` + `acctMinor` (both frames)

The single `acct` column was split into two distinct columns:

| Old | New col 1 | New col 2 |
|---|---|---|
| `acct` | `acct` | `acctMinor` |

Both use the `.acct-name` CSS class (monospace, `#4b5563`, 12 px).

**Frame 1 impact:** 6 → 7 columns. Colspans on section-header, subtotal, grand-total, and empty-state rows incremented accordingly.

**Frame 2 impact:** 9 → 10 columns. Empty-state colspan incremented accordingly.

#### 2. `propNm` added to Frame 2 (this release)

A new final column `propNm` (short property name, `str`) was appended to Frame 2 — Transaction Records:

- Position: column 11, after `refDB`
- Width: 110 px
- Style: `font-size:12px; color:#6b7280` (muted, consistent with `refDB`)
- Template: `row.get("propNm", "")` — optional field, blank if absent
- Empty-state colspan updated: 10 → 11
- No backend changes required to deploy

**Frame 2 impact:** 10 → 11 columns.

### v0.2.3.6 — 2026-05-05

#### `propNm` added to Frame 1 — Trial Balance

`propNm` (short property name, `str`) added to Frame 1, positioned between `acctMinor` and `acctSub` to keep numeric columns rightmost:

- Position: column 4, between `acctMinor` and `acctSub`
- Width: 110 px
- Style: `font-size:12px; color:#6b7280` (muted, consistent with Frame 2 treatment)
- Template: `row.get("propNm", "")` — optional field, blank if absent
- Section-header colspan updated: 7 → 8
- Subtotal / grand-total label colspan updated: 4 → 5
- Empty-state colspan updated: 7 → 8
- No backend changes required to deploy

**Frame 1 impact:** 7 → 8 columns.