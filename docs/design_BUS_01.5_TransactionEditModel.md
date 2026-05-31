# Transaction Edit Model — New Design

**File:** `docs/design_BUS_01.5_TransactionEditModel.md`
**Replaces:** current 3-button-per-row + modal dialog model in `table_view.html`
**Status:** Design / Pending GitHub Issue

---

## 1. Current Design (what exists today)

Each row in the records table has **3 per-row action buttons**:

| Button | Action |
|---|---|
| ✎ | Opens `recordEditorBackdrop` modal — edits one record at a time |
| `{}` | Opens `jsonEditorBackdrop` modal — raw JSON edit of one record |
| ✕ | `confirm()` popup → immediate single-record delete + page reload |

**Problems:**
- One record at a time — no bulk operations
- Every save triggers a full page reload (flash of content)
- 3 buttons per row clutters wide tables with many records
- Delete is instant and irreversible (confirm() is easy to mis-click)
- No way to see what has changed before committing

---

## 2. New Design Goals

| Goal | Design response |
|---|---|
| Reduce per-row clutter | Single checkbox + one Actions menu, no per-row buttons |
| Support bulk operations | Multi-select → Delete / Dup apply to all selected |
| Edit without losing context | Edit-in-place: row fields become inputs, no page leave |
| Explicit commit | All pending changes held client-side, sent in one batch on "Commit Edits" |
| Power-user JSON access | JSON dialog retained but gated to single-record only |

---

## 3. UI Component Map

```
┌─ Toolbar row ──────────────────────────────────────────────────┐
│  [☐ All]  Actions ▾  [Edit] [Delete] [Dup] [JSON]             │
│                                        (disabled until ≥1 row) │
│  ── when edits pending ──────────────────────────────────────   │
│  [Commit Edits (n)]  [Revert All]                              │
└────────────────────────────────────────────────────────────────┘
┌─ Records table ────────────────────────────────────────────────┐
│  ☐  │ Chg │ dt       │ desc        │ amt   │ acctID │ …       │
│  ☐  │  ✓  │ 2025-… │ Rent income │ 1200  │ 4100   │         │  ← clean
│  ☐  │  ~  │[2025-…]│[Rent income]│[1200] │[4100]  │         │  ← editing (amber bg)
│  ☐  │  +  │ 2025-… │ Rent income │ 1200  │ 4100   │         │  ← pending dup (green bg)
│  ☐  │  ✕  │ 2025-… │ Rent income │ 1200  │ 4100   │         │  ← pending delete (red/strikethrough)
└────────────────────────────────────────────────────────────────┘
```

---

## 4. Interaction Flow

### 4.1 Select records
- Each row has a leading `<input type="checkbox" class="row-select">` cell
- Header has a **Select All / Deselect All** master checkbox
- Selecting ≥ 1 row activates the Actions button group

### 4.2 Actions button group

Shown in toolbar. Disabled (greyed) when no rows are selected.

| Action | Min selected | Behaviour |
|---|---|---|
| **Edit** | 1 | Opens the first selected row for inline editing; if multiple selected, queues remaining rows |
| **Delete** | 1+ | Marks selected rows as `pending_delete` (red bg + strikethrough); does NOT remove yet |
| **Dup** | 1+ | Clones each selected row client-side, appends below source row, marks as `pending_add` (green bg) |
| **JSON** | exactly 1 | Opens JSON dialog for that record (disabled / shows tooltip if >1 selected) |

### 4.3 Edit in place

When Edit is triggered:
- Row's `<td>` cells become `<input>` / `<select>` elements in-place
- Row gets class `row-editing` (amber background `#fef3c7`)
- `Chg` column shows `~` (editing in progress)
- **Tab** moves focus to next editable cell; **Shift+Tab** moves back
- **Escape** reverts that row to its last committed values (client-side only)
- `tID` field: auto-regenerated from `dt` + `amt` + `aType` (existing logic, kept)
- `acctID` field: rendered as `<input list="coa-datalist">` — dropdown from COA (see §7.3)

### 4.4 Commit Edits button

Appears in toolbar as soon as any pending change exists (edit, delete, or dup).

**Label:** `Commit Edits (n)` where `n` = count of pending-changed rows.

On click:
1. Collect all pending rows: `{cmd, id?, payload}` per row
2. POST to `/cmd` as a **batch**: `{ cmd: "batch", ops: [...] }`
3. On success → page reload (same as current behaviour)
4. On error → show inline error banner; do NOT clear pending state

**Revert All** button (appears alongside Commit):
- Clears all pending edits client-side
- Restores all rows to their original display state
- No server round-trip
- If any row was mid-edit, closes it and restores

### 4.5 JSON action (single record)

Same modal as today (`jsonEditorBackdrop`) with two additions:
1. **Format button** — pretty-prints the JSON in the textarea (`JSON.stringify(JSON.parse(...), null, 2)`)
2. **Sanitisation on Done** — before POST, validate:
   - Parses as valid JSON
   - Contains all required keys for this `obj_type` (checked against `COLUMNS` known to the template)
   - No unexpected top-level keys outside the schema (warn, not block)
   - Numeric fields are numbers (not strings)
   - `tID` is present and non-empty
   Show inline error message in the dialog — do NOT use `alert()`.

---

## 5. Pending State Model (client-side)

```js
// pendingOps: Map<rowKey, PendingOp>
// rowKey: tID (or synthetic key for new rows)
const pendingOps = new Map();

// PendingOp shape:
{
  cmd:      "update" | "delete" | "add",   // batch cmd
  id:       "<tID>",                        // undefined for "add"
  payload:  { col: value, … },             // full row data
  srcIndex: <int>,                          // original row position in RAW_ROWS
}
```

Rules:
- **Edit** → `cmd: "update"`, `id: row.tID`, `payload`: all field values at commit time
- **Delete** → `cmd: "delete"`, `id: row.tID` (no payload needed)
- **Dup** → `cmd: "add"`, no `id`, `payload`: clone of source row with `tID` suffixed `_dup{n}`
- If user edits a row already marked `pending_delete` → silently upgrades to `update` (un-deletes it)
- If user deletes a row marked `pending_add` (a dup not yet committed) → just remove from `pendingOps` and remove the row from DOM

### tID suffix for duplicates

Current tID format: `{dt}_{±amt:0.2f}` — deterministic from date + amount.
Duplicate of the same record would collide.

**Resolution:** append `_dup{epoch_ms}` to guarantee uniqueness:
```js
function dupTID(srcTID) {
    return `${srcTID}_dup${Date.now()}`;
}
```
Server-side `cmd: "add"` already accepts any tID in the payload.

---

## 6. Batch API (`cmd: "batch"`)

### New Flask handler in `llcMgmt.py`

```python
elif cmd == "batch":
    ops = payload_data.get("ops", [])
    errors = []
    for op in ops:
        sub_cmd = op.get("cmd")
        if sub_cmd == "update":
            _merge_save(manager, [op["payload"]])
        elif sub_cmd == "add":
            _merge_save(manager, [op["payload"]])
        elif sub_cmd == "delete":
            _delete_row(manager, op["id"])
        else:
            errors.append(f"unknown sub-cmd: {sub_cmd}")
    if errors:
        return jsonify({"ok": False, "error": "; ".join(errors)})
    return jsonify({"ok": True})
```

Existing `cmd: "update"`, `cmd: "add"`, `cmd: "delete"` routes are kept for
backward compatibility (JSON dialog still uses single-op POST).

---

## 7. UI Expert Additional Recommendations

### 7.1 Dirty-state visual language

| State | Row bg | `Chg` badge | Meaning |
|---|---|---|---|
| Clean, unchanged | white | — | committed, no edits |
| Previously saved | white | ✓ | changed this session |
| Currently editing | amber `#fef3c7` | ~ | inputs open, not committed |
| Pending delete | red `#fee2e2` + strikethrough | ✕ | will be removed on commit |
| Pending dup (new) | green `#dcfce7` | + | will be added on commit |

### 7.2 Navigate-away guard

```js
window.addEventListener("beforeunload", (e) => {
    if (pendingOps.size > 0) {
        e.preventDefault();
        e.returnValue = "";  // triggers browser "Leave page?" dialog
    }
});
```
Prevents accidental loss of pending edits on accidental back/refresh.

### 7.3 COA datalist for `acctID`

The Chart of Accounts is already available in the template context.
Render once in the page as a `<datalist>`:

```html
<datalist id="coa-datalist">
  {% for acct in coa_list %}
  <option value="{{ acct.acctID }}" label="{{ acct.acctDesc }}">
  {% endfor %}
</datalist>
```

The `acctID` inline input uses `list="coa-datalist"` — gives type-ahead without a
custom dropdown component.

### 7.4 Field-level validation before Commit

Before the batch POST, scan all `pending_add` and `pending_update` ops:
- Required fields missing → highlight cell red, block Commit, show inline banner
- `amt` not numeric → same
- `dt` not a valid date → same

Do NOT use `alert()` anywhere in the new model — all errors show as inline banners
above the table or within the JSON dialog.

### 7.5 "Add" stays as a dedicated toolbar button

The existing ➕ **Add** button (top toolbar) is kept. Clicking Add:
1. Inserts a new blank row at the **top** of the table with all cells as inputs
2. Marks it `pending_add` immediately
3. Focuses the first editable cell (`dt`)

This is distinct from **Dup** (which clones an existing row). Users should not need
to select a row to add a net-new record.

### 7.6 Multi-row edit queue

When **Edit** is triggered with multiple rows selected, edit them sequentially:
- Open row 1 for inline editing
- When user presses **Tab** past the last cell (or presses **Enter**), auto-advance to row 2
- Show a subtle progress indicator: "Editing 1 of 3 selected"

This prevents the overwhelming UX of all rows going into edit mode simultaneously.

### 7.7 Keyboard shortcuts summary

| Key | Context | Action |
|---|---|---|
| `Tab` / `Shift+Tab` | inline edit | move between cells |
| `Enter` | inline edit (last cell) | next row in queue, or done if last |
| `Escape` | inline edit | revert this row, exit edit mode |
| `Space` | row focused (not editing) | toggle checkbox |
| `Ctrl+Enter` | any | Commit Edits (if pending ops exist) |

---

## 8. What Changes

| File | Change |
|---|---|
| `ui/templates/table_view.html` | Replace 3-button per-row with checkbox; add Actions bar; add inline edit logic; add batch pendingOps state machine; add beforeunload guard |
| `ui/templates/base.html` | Keep modal CSS (JSON dialog still uses it); add `.row-editing`, `.row-pending-delete`, `.row-pending-add` CSS |
| `ui/llcMgmt.py` | Add `cmd: "batch"` handler; keep existing single-op handlers |
| No new Flask routes | `/cmd` endpoint handles everything via `cmd` field |

The `_aid_dialog.html` and `_propAgent_dialog.html` are unaffected —
they are separate agent dialogs, not the record editor.

---

## 9. What Does NOT Change

- `cmd: "add"`, `cmd: "update"`, `cmd: "delete"` single-op POST API — kept, used by JSON dialog
- `save_object` / `save_and_publish` toolbar buttons — kept as-is
- `read_only` mode — checkboxes and Actions bar are hidden, same as current per-row button hiding
- `financial_view.html`, `general_ledger_view.html` — read-only views, unaffected
- Session DB write path (`utilWorkingDB`, `_merge_save`, `_delete_row`) — unchanged

---

## 10. Implementation Effort

*All estimates are **Claude coding hours** — focused implementation with no ramp-up.
Human programmer unfamiliar with this codebase: multiply by 3–4×.
Human programmer who knows the codebase: multiply by 1.5–2×.*

| Item | Claude hrs | Notes |
|---|---|---|
| Checkbox column + Select All | 0.5 | Simple DOM + CSS |
| Actions button group (toolbar) | 0.5 | Enable/disable state wired to selection |
| `pendingOps` state machine (JS) | 2 | Largest item — edge cases (edit-a-pending-delete, delete-a-pending-dup) |
| Inline edit row rendering | 2 | DOM swap `<td>` → `<input>` in-place, layout stability |
| COA datalist + field validation | 1 | Datalist from template context; required-field check before POST |
| Commit Edits / Revert All buttons | 1 | Batch POST + client-side state clear |
| `cmd: "batch"` Flask handler | 1 | Loop over ops, reuse existing `_merge_save` / `_delete_row` |
| JSON dialog enhancements (format + sanitise) | 1 | Pretty-print button + inline error banner |
| CSS (dirty-state colours, animations) | 0.5 | 4 row states × bg + badge |
| `beforeunload` guard + keyboard shortcuts | 0.5 | Standard browser APIs |
| **Total** | **~10 hr** | |
