# LLC_BookToIRS_Aid — IRS Tax Mapping Aid Tool

**Status**  Draft v0.1 — for review
**Owner**   Francisco Rojas (W&B Group, LLC)
**Scope**   Aid LLC Business Manager (ie. operator) in Review and Completing IRS Tax Forms<br>
            
- a) refer to "Level 4 of Levels of Accounting Tasks" in docs/LLC_AccountingWorkFlow.md
- b) refer to "4 Level Tax Prepare, Book to IRS" data flow in docs/LLC_DataFlowDesign.md (esp. llcDataFlow_L4-6.mmdc/.svg)
- c) Add an "Aid" button to each IRS Tax View (showing the FILL.pdf) that would invoke the "Aid Book to IRS Mapping" dialogs.
        - The Aid UI asks the operator to identify a single IRS Form Field (fid)
        - The operator is shown the current state of mapping
        - The operator can then select an action button:
            - Create New Mapping,
            - Edit Current Mapping,
            - Delete Current Mapping
        - The operator then defines the changed mapping and commits the changed mapping
        - The irsBooktoIRS is invoked, leverages the new mapping and generates a new FILL.pdf

---

## 1.  Why this tool exists

Today the Book→IRS pipeline (`irsBookToIRS.ipynb` → `Form1065_FILL.pdf`) is based on a simple mapping capability:

1. The irsBooktoIRS queries each stmtOBJ_Tax.loadFillDict() to get values for a set of Form Fields it can provision.  
    - Basic 1-1 IRS Field (fid) lookup within an existing BookNS_OBJ.json table (dict) (*1)
    - Custom mapping per field (derived from the Books set of books, 1 custom function per IRS Custom Field).
2. The FillPDF just inserts the values within the FillDict into the final FILL.pdf.

(*1) - the bookNS is built at the beginning of the Tax Year, and possibly adjusted for change YTY. Generally, this mapping is based on standard and best practices of Book objects to IRS Form knowledge.

Today's set of bookNS mapping tables:

```
pages/AccountingData/2025/
    bookNS_Profile.json        # Profile.* → fid
    bookNS_BS.json             # BS.*      → fid
    bookNS_IS.json             # IS.*      → fid
    bookNS_GL.json             # Acct.*    → fid
```

Every time the IRS publishes a new Form 1065 layout, or the LLC adds a new
account/property/owner, a human must:

1. Identify which IRS field (`fid`) needs a value.
2. Pick the right `stmtOBJ_Tax` source (Profile / BS / IS / GL).
3. Pick (or invent) a UAS path (e.g. `IS.rent_income`,
   `BS.l_total_assets_end`, `Profile.F1065.preparer_ein`).
4. Edit the bookNS JSON.
5. If the value is a custom mapped value, to be computed,
    - write a `stmtOBJ_Tax._Cplx_<fid>()` stub method
    - The stub will be corrected by a LLC accounting bookkeeper (operator).
    - Add the `_Cplx` function into a "stmtOBJ_Tax.<form>_CustomMapDict[fid]"
    - The <form>_CustomMapDict[fid] controls the custom mapping
    - The stmtOBJ_Tax.loadFillDict() uses the <form>_CustomMapDict to call the set of `_Cplx` custom methods. 
6. Re-run the notebook end-to-end to verify.

The current process is error-prone (off-by-one fids, mistyped paths,
duplicate entries that silently shadow each other) and there is no
in-app visibility into what's mapped, what's blank, and what's broken.

The **Book to IRS Mapping Aid Tool** is a small CRUD UI that turns this into a
guided dialog: you pick a fid, the tool offers the legal sources and the
fields each source publishes, you commit, and the FILL.pdf regenerates.

---

## 2.  Glossary

| Term              | Meaning                                                                      |
| ----------------- | ---------------------------------------------------------------------------- |
| **fid**           | Normalized field id `F001`..`F440` from `Form1065_namespace.json`.           |
| **shortName**     | The PDF leaf name, e.g. `f1_19`, `c1_3`, `c2_5`.                              |
| **fType**         | `text` \| `checkBox` \| `checkText` \| `image`.                              |
| **bookNS source** | One of `Profile` / `BS` / `IS` / `GL`. Resolved via `_PRIO`.                 |
| **UAS path**      | Dotted accessor used by `stmtOBJ_Tax`, e.g. `BS.l_ar_beg`, `Profile.F1065.preparer_ptin`. |
| **mapping**       | One `[fid, UAS_path]` entry inside a `bookNS_<src>.json` Form1065 list.       |
| **resolver**      | Priority pick (`Profile > BS > IS > GL`) inside `BookToIRS()`.                |
| **CHECK sentinel**| Literal string `"CHECK"`. On `/Tx` fields it stamps `"X"`; on `/Btn` fields it toggles ON. |
| **Complex stub**  | `_Cplx_<fid>(self, formNm)` method on a stmtOBJ subclass. Returns `"Complex"` until edited; recognized by `_status()`. |
| **Custom map**    | A mapping whose UAS path resolves to a Complex stub (no live book value yet).|
| **fillDict / checkDict / complexDict** | The three return slices from `irsForm.BookToIRS()`. |

---

## 3.  User stories

1. **Author a brand-new mapping.** "I just added a new line item — Energy
   Efficient Buildings deduction (Line 20). Help me wire that to a book
   field and stamp it on the FILL.pdf."

2. **Fix a wrong mapping.** "F051 is showing my Line 18 Retirement Plans
   number on Line 21 Other Deductions. Let me fix the source path. Delete fid-Line 18 and add fid-Line 21."

3. **Toggle a checkbox.** "Schedule B Q4a should now answer Yes. Add a
   mapping for the c2_3 box."

4. **Delete a stale mapping.** "We retired the Profile.F1065.line_5 entry —
   delete it."

5. **Stub out a complex calc.** "F229 (Sched K Line 1) needs a custom calc
   — give me a stub I can fill in later, and stamp `Complex` for now."

6. **Bulk-commit.** "I just made eight changes. Commit them all and
   regenerate the PDF."

---

## 4.  Architecture

### 4.1  Where it lives

The Aid is invoked just like the Edit button on a transaction view: an
**Aid** button on each IRS Tax View (`/view/llcForm1065`,
`/view/llcFormK1`) opens an **inline modal dialog** scoped to one fid.

The modal is a Jinja partial (`_aid_dialog.html`) included into the
existing `irs_pdf_view.html` — there is no standalone `book_to_irs_aid.html`
page and no new top-nav `VIEW_GROUPS` entry in v0.1. The dialog talks
to the Flask app via the `/api/aid/...` routes (see §4.4).

### 4.2  Data model

Three layers, in priority order from least to most volatile:

```
┌───────────────────────────────────────────────────────────────────┐
│  Form1065_namespace.json    (read-only)                            │
│    fid → { shortName, fType, page, location, checkedValue }        │
└──────────────────────────────┬────────────────────────────────────┘
                               │ left join on fid
┌──────────────────────────────▼────────────────────────────────────┐
│  bookNS_<src>.json           (edited by this tool)                 │
│    Form1065: [ [fid, UAS_path], ... ]                              │
│  + stmtOBJ_Tax.loadFillDict() then invokes custome functions       │
│    -> stmtOBJ_Tax_Cplx_<fid>()                                     │
└──────────────────────────────┬────────────────────────────────────┘
                               │ stmtOBJ.loadFillDict() resolves UAS
┌──────────────────────────────▼────────────────────────────────────┐
│  Live LLC ledger / profile / BS / IS / GL state                    │
│    yields { fid → value | CHECK | Complex }                         │
└───────────────────────────────────────────────────────────────────┘
```

The new `_Cplx_<fid>()` is added as a method on the per-source
`stmtOBJ_Tax` *subclass* (e.g. `stmtIS_Tax`, not the base class).
`stmtOBJ_Tax.loadFillDict()` walks `<form>_CustomMapDict` and calls each
`_Cplx_<fid>` method to provision the final value into the FillDict it
returns. The `_Cplx` function is straightforward — it extracts values
from one or more stmtOBJ (potentially llcOBJ's, e.g. member list).

### 4.3  Service layer (new module)

`ui/llcBookToIRSAid.py`

```
class BookToIRSAid:
    def __init__(self, llc, formNm='Form1065'):
        self.llc       = llc
        self.formNm    = formNm
        self.namespace = self._loadNamespace()      # fid → meta (read-only)

    # ── Read ──────────────────────────────────────────────────────
    def listMappings(self)      -> list[dict]    # fids in bookNS ∪ <form>_CustomMapDict
    def getMapping  (self, fid) -> dict           # current source/path/value/status
    def listSources (self)      -> list[str]      # ['Profile','BS','IS','GL']
    def listFields  (self, src) -> list[str]      # UAS paths the stmtOBJ publishes
    def previewValue(self, fid, src=None, path=None) -> str

    # ── Write — each persists IMMEDIATELY + hot-reloads ───────────
    # No in-memory pending state.  No diff/revert.  No validation gate.
    # Output kind (text vs checkbox) is derived from namespace[fid].fType,
    # so write methods do not take a `kind` argument.
    def createMapping  (self, fid, src, path)       -> dict   # bookNS_<src>.json write
    def editMapping    (self, fid, src, path)       -> dict   # bookNS rewrite (delete-then-create at disk level)
    def deleteMapping  (self, fid)                  -> dict   # bookNS row delete
    def addCustomMap   (self, fid, src, note='')    -> dict   # writes <form>_CustomMapDict + new _Cplx_<fid> stub
    def removeCustomMap(self, fid, src)             -> dict   # soft-delete: dict entry removed, method preserved
    def relinkCustomMap(self, fid, src)             -> dict   # re-add dict entry pointing at an existing _Cplx_<fid>

    # ── Regenerate ────────────────────────────────────────────────
    def regenerate(self) -> dict:
        # Re-runs irsForm(Form1065).BookToIRS('Form1065') and returns
        # { fill_path, pdf_fields, filled, check, complex, blank }.
        # Disk state is already current — there is nothing to "commit".
```

The service is stateless across requests. There is no in-memory diff,
no pending list, no batched commit. Each write method persists to disk
and hot-reloads the affected stmt module before returning. The
`regenerate()` call is what the **Commit** button triggers (see §5.5 /
§8.4) — it produces a fresh FILL.pdf from whatever is currently on disk.

### 4.4  Flask routes

| Method | Route                                     | Purpose                                                            |
| ------ | ----------------------------------------- | ------------------------------------------------------------------ |
| GET    | `/api/aid/mappings`                       | Returns mapped fids (bookNS ∪ `<form>_CustomMapDict`) as JSON. (Used by the v0.2 grid; v0.1 dialog uses `/mapping/<fid>`.) |
| GET    | `/api/aid/mapping/<fid>`                  | Returns one fid's current mapping + live value.                     |
| GET    | `/api/aid/sources`                        | Returns `['Profile','BS','IS','GL']`.                              |
| GET    | `/api/aid/fields/<src>`                   | Returns the UAS paths the stmtOBJ publishes.                        |
| GET    | `/api/aid/preview?fid=…&src=…&path=…`     | Returns the live value for the proposed mapping (no write).         |
| POST   | `/api/aid/mapping`                        | Create one bookNS mapping. **Persists immediately to `bookNS_<src>.json`.** |
| PUT    | `/api/aid/mapping/<fid>`                  | Edit one bookNS mapping. **Persists immediately.**                  |
| DELETE | `/api/aid/mapping/<fid>`                  | Delete one bookNS mapping. **Persists immediately.**                |
| POST   | `/api/aid/custom`                         | Register a custom map. **Edits `stmt<src>.py` and hot-reloads.**    |
| DELETE | `/api/aid/custom/<fid>`                   | Soft-delete a custom map (remove from `<form>_CustomMapDict`; method body preserved). |
| POST   | `/api/aid/custom/<fid>/relink`            | Re-link a previously soft-deleted `_Cplx_<fid>` method.             |
| POST   | `/api/aid/regenerate`                     | Re-run `BookToIRS()` and return the new `pdf_fields / filled / check / complex / blank` totals. (The "Commit" button.) |

There is **no `/api/aid/diff`, `/api/aid/revert`, or `/api/aid/commit`
batched endpoint** — each write persists on its own.

All POST/PUT/DELETE endpoints return the updated fid row so the
front-end can splice it into the dialog without a full reload.

---

## 5.  UI flow

### 5.1  Main grid  *(deferred to v0.2)*

A single sortable / filterable Grid.js table that left-joins the
namespace with the current bookNS:

| fid   | page | shortName | fType   | line / location           | source  | UAS path                  | live value      | status   | actions |
|-------|------|-----------|---------|---------------------------|---------|---------------------------|-----------------|----------|---------|
| F016  |  1   | f1_16     | text    | F1065.LineF.TotalAssets   | BS      | BS.total_assets           | 4 200 000.00    | filled   | ✏️ 🗑    |
| F017  |  1   | c1_1      | checkBox| F1065.LineG.InitialReturn |  —      |  —                        |  —              | blank    | ➕      |
| F018  |  1   | c1_2      | checkBox| F1065.LineG.FinalReturn   | Profile | Profile.F1065.chk[2]      | CHECK           | check    | ✏️ 🗑    |
| F042  |  1   | f1_31     | text    | F1065.Line11.Repairs      | IS      | IS.repairs                | 0               | filled   | ✏️ 🗑    |
| F229  |  5   | f5_01     | text    | SchK.Line1.OrdIncome      | Custom  | Custom.F229               | Complex         | complex  | ✏️ 🗑    |
| ...   | ...  | ...       | ...     | ...                       | ...     | ...                       | ...             | ...      | ...     |

Filter chips at the top: `All / Filled / Check / Complex / Blank` and
`Page 1 / 2 / 3 / 4 / 5 / 6`. v0.1 ships the per-fid dialog only (see
§5.2 onward); this grid is the v0.2 follow-up surface for browsing the
full mapping table.

### 5.2  Create dialog (`➕` on a blank fid)

**Output type is read-only** — it is derived from
`namespace[fid].fType` (text / checkBox / checkText / image) and
displayed for situational awareness only. The operator does not pick
it; the dialog adapts based on it.

```
┌─────────────────────────────────────────────────────────────────┐
│  Create mapping for fid F042  (page 1 — f1_31 — Line 11 Repairs)│
├─────────────────────────────────────────────────────────────────┤
│  Output type :   text   (from namespace[F042].fType)            │
│                                                                 │
│  Source      :  [ Profile  ▼ ]  ← Profile / BS / IS / GL         │
│                                                                 │
│  Field       :  [ — pick — ▼ ]                                   │
│      Profile.F1065.repairs                                      │
│      Profile.entity.repairs_pct                                 │
│      …                                                          │
│      ➕ Add custom map (Complex stub)                           │
│                                                                 │
│  Live value  :  $0.00                  (refresh on field change)│
│                                                                 │
│  Note        :  [ optional free text                  ]          │
├─────────────────────────────────────────────────────────────────┤
│                                       [ Cancel ]   [ Save ]     │
└─────────────────────────────────────────────────────────────────┘
```

Behaviour:

1. The fid is locked — chosen by the row/picker that opened the dialog.
2. Source dropdown defaults to `Profile`. Changing it reloads the Field
   dropdown via `/api/aid/fields/<src>`.
3. Field dropdown shows every UAS path the chosen `stmtOBJ` publishes
   (the keys of `loadFillDict(formNm)` plus any fid already declared in
   `<formNm>_CustomMapDict` for that source).
4. The last entry of the Field dropdown is always **➕ Add custom map**.
   Picking it disables the path autocomplete and shows a small "Stub
   note" textbox. On Save, the tool calls
   `addCustomMap(fid, src, note)` which:

      a. Looks for an existing `_Cplx_<fid>` method in the source file
         (orphaned from a previous soft-delete). If one exists, the
         dialog **refuses to add a new stub** and offers `Re-link`
         instead — the dict entry is added pointing at the existing
         method body.
      b. Otherwise, appends a fresh stub at the bottom of the
         `stmt<src>_Tax` subclass (inside the `# ── AID-CPLX ──` /
         `# ── /AID-CPLX ──` markers):

         ```python
         # AUTO-GENERATED — edit the body, not the signature.
         def _Cplx_F042(self, formNm):
             """Custom mapping for Form1065 fid F042 (Line 11 Repairs).
             note: <free-text note>
             """
             return 'Custom'
         ```

      c. Adds `"F042": "_Cplx_F042"` to `<formNm>_CustomMapDict`, which
         lives at the **top of the `stmt<src>_Tax` subclass** inside the
         `# ── AID-MAPS ──` / `# ── /AID-MAPS ──` markers.

      d. Multi-form orchestration: the same subclass holds one dict per
         form (`Form1065_CustomMapDict`, `Sch_K1_CustomMapDict`,
         `Form4562_CustomMapDict`, …). The Aid passes `formNm` so the
         dispatcher picks the right dict.

      e. **No `stmt<src>.py` backup is taken.** Per the v0.1 decision,
         the operator is responsible for source-control hygiene
         (Python source surgery happens in-place; recover via git).
         JSON files (`bookNS_<src>.json`) *are* still backed up — see
         §8.3.

   Stub auto-append is the default for new custom maps.

5. **Output type = checkBox / checkText.** When namespace says the fid
   is a `/Btn` field, the Field dropdown is filtered to paths the
   stmtOBJ resolver is known to emit `CHECK_SENTINEL` for (e.g.
   `Profile.F1065.chk[*]`). For sources without such a path, the only
   option becomes **➕ Add custom map**, with the stub returning
   `self.CHECK_SENTINEL` instead of `'Custom'`.

6. **Save** persists the change to disk immediately and reloads the
   dialog with the new state. There is no "pending" banner — the row
   is already on disk.

### 5.3  Edit dialog (`✏️` on a mapped fid)

Same form as Create, but pre-populated. Three sub-actions live in the
dialog:

- **Change the field within the current source** — only the Field
  dropdown changes.
- **Change source + field** — both dropdowns change. Implementation-wise
  this is a delete-then-create at the disk level (one bookNS rewrite).
- **Promote to custom map** — same as the Create flow's "Add custom map"
  branch.

`Save` writes to disk immediately and updates the row in the dialog.
The `live value` column refreshes via `/api/aid/preview` so the
operator can see what the new mapping will publish *before* hitting
Save.

### 5.4  Delete dialog (`🗑️` on a mapped fid)

A small confirm modal:

```
Delete mapping  F042 → IS.repairs ?

bookNS path  →  removes the row from bookNS_IS.json.  The PDF field
                will go blank unless another (lower-priority) bookNS
                source provides a value for F042.

Custom map   →  removes the F042 entry from
                stmtIS_Tax.Form1065_CustomMapDict so loadFillDict()
                stops calling _Cplx_F042.  The _Cplx_F042 method body
                is preserved in the source file so the operator can
                re-link it later from the Edit dialog.

                                       [ Cancel ]   [ Delete ]
```

### 5.5  Commit (Regenerate FILL.pdf)

There is **no pending-changes banner** in v0.1 — every Create / Edit /
Delete already persisted to disk when the operator clicked Save. The
**Commit** button (label kept for operator-workflow consistency) just
calls `/api/aid/regenerate`, which executes:

1. **Regenerate**
   - Re-run `irsForm(Form1065).BookToIRS('Form1065')`.
   - Surface the new `pdf_fields / filled / check / complex / blank`
     totals in a flash banner.
   - Refresh the `Form1065_FILL.pdf` iframe in the IRS Tax view (via
     `?ts=<unix_ts>` cache-buster reload).

If the run errors (e.g. a hand-written `_Cplx_F229` raises), the Aid
surfaces the traceback in the flash banner; disk state is unaffected.

**Future ("offline") regeneration path.** Hot-reloading edited
`stmt<src>.py` modules in a long-running Flask process is a known
fragility (see §6.3). Once the operator declares the mapping set
"finalized", the recommended path is to run `irsGenCmd.py` (a small
CLI scheduled for v0.2) in a fresh Python process. v0.1 keeps the
in-app `regenerate()` for convenience.

---

## 6.  Custom-map mechanics

The custom-mapping path is implemented entirely **inside** the
`stmtOBJ_Tax` subclass — there is no separate JSON registry. Two
pieces of state per source file:

1. **`<form>_CustomMapDict`** — class attribute. A `dict[fid → method-name]`
   that the dispatcher walks during `loadFillDict()`.
2. **`_Cplx_<fid>(self, formNm)`** — instance method on the same class.
   Returns a scalar value, the `CHECK_SENTINEL` (for checkbox toggles),
   or `COMPLEX_SENTINEL` while still a stub.

Both pieces live in the source file
`pages/AccountingData/Notebooks/ledger/stmt<src>.py` (one of
`stmtProfile`, `stmtBS`, `stmtIS`, `stmtGL`). The Aid edits these
sections via textual surgery within marked regions:

```python
class stmtIS_Tax(stmtIS, stmtOBJ_Tax):

    # ── AID-MAPS ──── auto-generated; only the Aid tool edits below ──
    Form1065_CustomMapDict = {
        "F229": "_Cplx_F229",
    }
    Sch_K1_CustomMapDict = {}
    # ── /AID-MAPS ────────────────────────────────────────────────────

    # ── AID-CPLX ──── auto-generated stubs; edit method bodies freely
    def _Cplx_F229(self, formNm):
        \"\"\"Form1065 fid F229 — Sched K Line 1 Ord Income.

        Generated 2026-05-01 by the Book→IRS Aid tool.
        Note: needs partner-share split.
        \"\"\"
        return self.COMPLEX_SENTINEL
    # ── /AID-CPLX ────────────────────────────────────────────────────
```

### 6.1  How the dispatcher reads it

`stmtOBJ_Tax.loadFillDict(formNm)` already builds its return dict from
two passes — these stay unchanged:

```python
def loadFillDict(self, formNm):
    out = {}

    # 1. Static bookNS lookup  (1-1 fid → UAS_path)
    for fid, path in self._loadBookNS(formNm):
        out[self._normalizeFid(fid)] = self._eval(path)

    # 2. Custom-map dispatch
    cmd = getattr(self, f"{formNm}_CustomMapDict", {})
    for fid, methodName in cmd.items():
        method = getattr(self, methodName, None)
        if method is None:
            out[self._normalizeFid(fid)] = self.COMPLEX_SENTINEL
            continue
        out[self._normalizeFid(fid)] = method(formNm)

    return out
```

A fid that has both a bookNS entry and a `<form>_CustomMapDict` entry
inside the same source ends up with the CustomMap value (second pass
overwrites). Across sources, `BookToIRS()` still applies the priority
`Profile > BS > IS > GL`.

### 6.2  Aid edit primitives (Python source surgery)

| Primitive | Effect |
| --- | --- |
| `add_cplx(src, formNm, fid, note)` | Add `"<fid>": "_Cplx_<fid>"` to `<formNm>_CustomMapDict`; append a stub `_Cplx_<fid>(self, formNm)` that returns `COMPLEX_SENTINEL`. |
| `remove_cplx(src, formNm, fid)`    | Remove the entry from `<formNm>_CustomMapDict` only. The `_Cplx_<fid>` method body is **preserved**, with a `# DEPRECATED YYYY-MM-DD — re-link via <formNm>_CustomMapDict to revive` banner prepended so the operator can re-link later. |
| `relink_cplx(src, formNm, fid)`    | Re-add a previously removed dict entry by pointing back at the still-present method body. |
| `rename_cplx(src, formNm, old_fid, new_fid)` | Update both the dict key and the method name in lock-step. |

All four primitives use marker-based regex (`# ── AID-MAPS ──` / `# ──
/AID-MAPS ──` and the matching `AID-CPLX` pair). Hand-written code
outside the markers is never touched.

### 6.3  Hot-reload after every edit

After writing `stmt<src>.py`, the Aid does:

```python
import importlib, ledger.stmtIS
importlib.reload(ledger.stmtIS)
self.llc.refresh_stmt(src)        # re-instantiate the running stmtOBJ
```

`refresh_stmt(src)` rebuilds the cached `stmtIS_Tax(llc)` instance so
subsequent `BookToIRS()` runs see the new method. Without the
re-instantiation, `getattr(self, "_Cplx_F229")` on the *old* instance
still resolves to nothing.

### 6.4  Soft-delete preserves work

When the operator removes a custom map, the dict entry goes but the
method stays. Two reasons:

- **The method body is hand-written work** — the operator (or AI
  assistant) may have spent real effort on the calc, and a year-end
  re-run might want it back.
- **Recovery is one click.** The Edit dialog lists "previously deleted
  stubs found in this source file" and offers `Re-link` to re-add the
  dict entry without writing a new stub.

The deprecated method banner is a single comment line; over time these
accumulate as a low-cost archaeological log of past mappings.

---

## 7.  Advisory checks (not gating)

There is **no commit-blocking validation**. The operator owns
correctness. The Aid surfaces advisory chips inside the per-fid dialog
so the operator can self-correct *before* hitting Save:

| Check                                                                    | Surface                                          |
| ------------------------------------------------------------------------ | ------------------------------------------------ |
| fid not in `Form1065_namespace.json`                                     | Red banner "fid unknown — Save will still write" |
| Output picked = Checkbox but namespace says fType=`text`                 | Yellow chip "Will stamp 'X' as plain text"       |
| Output picked = Text but namespace says fType=`checkBox`                 | Yellow chip "Field expects /Btn toggle"          |
| bookNS path doesn't exist as a key on `<src>.loadFillDict(formNm)`       | Yellow chip "Path will return None at run time"  |
| `<form>_CustomMapDict` already contains this fid                         | Yellow chip "Will overwrite existing custom map" |
| Same fid is mapped under another bookNS source with higher priority      | Yellow chip "`Profile`-priority entry will mask this" |
| `bookNS_<src>.json` has duplicate fids (pre-existing)                     | Yellow chip "Duplicate in this source — last wins" |

Save always succeeds. The chip stays visible on the row in the optional
v0.2 grid view so the operator has a running list of items to revisit.

---

## 8.  Persistence & atomicity

Each Create / Edit / Delete writes immediately to disk. **No in-memory
pending state, no batching, no revert.** Closing the dialog at any
point leaves the disk in a consistent state.

### 8.1  Two write targets

| Operation                               | File touched                                                | Mechanism                  |
| --------------------------------------- | ----------------------------------------------------------- | -------------------------- |
| Create / Edit / Delete bookNS entry     | `pages/AccountingData/2025/bookNS_<src>.json`               | JSON rewrite               |
| Create / Edit / Delete custom map       | `pages/AccountingData/Notebooks/ledger/stmt<src>.py`        | Python source surgery (marker-region regex) |

### 8.2  Atomic write helper

```python
def _atomic_write(path, payload):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
```

Used for both JSON and Python paths.

### 8.3  Backups

Backups are taken **only for `bookNS_<src>.json`**. Python source
edits to `stmt<src>.py` do **not** create an Aid-side backup —
recovery for those is via git (the operator's source-control hygiene
is the safety net).

| Source        | Backup folder                                                       |
| ------------- | ------------------------------------------------------------------- |
| bookNS JSON   | `pages/AccountingData/2025/.bookNS_backups/` (ISO-timestamped, last 30) |
| stmt Python   | *(no Aid backup — use git)*                                          |

Restore is manual: copy the JSON file back over the live one, or
`git checkout` the Python file. (No in-app revert in v0.1 — the "no
validation" stance means the operator is in charge.)

### 8.4  Commit = re-generate only

The `Commit` button at the end of a session is **not** a persistence
step (state is already on disk). It just calls
`irsForm(Form1065).BookToIRS('Form1065')` and reports the new
`pdf_fields / filled / check / complex / blank` totals. If the run
errors (e.g. a hand-written `_Cplx_F229` raises), the Aid surfaces the
traceback in a flash banner; the bookNS / stmt files are unchanged.

The button could equally be labelled **Regenerate FILL.pdf** — it is
kept as "Commit" for consistency with the operator's workflow language.

---

## 9.  Integration with the existing pipeline

- **Entry point.** An "Aid" button appears in the toolbar of each IRS
  Tax view (`/view/llcForm1065`, `/view/llcFormK1`). Clicking opens
  the per-fid dialog. 
- **Fid pickers.**  The dialog accepts a fid in three ways:
    1. Typed into a search box (`F042` / `f1_31` / "Line 11" all
       resolve to fid F042 via the namespace).
    2. Picked from a small list of fids that already have mappings on
       the current page.
    3. Picked from a "blank-on-this-page" list when the operator wants
       to author a new mapping.
- **PDF refresh.** After Commit, the Form 1065 view's `<iframe>` URL
  gets `?ts=<unix_ts>` appended and reloads. The notebook
  `irsBookToIRS.ipynb` continues to work unchanged.

---

## 10.  Out-of-scope for v0.1

- **All-fids browser grid.** The §5 grid is deferred to v0.2; v0.1 ships
  with the per-fid dialog only.
- **Multi-form editing.** v0.1 handles `Form1065`. Sch_K1, Form 4562,
  etc. follow once the Form 1065 flow is stable. The
  `<form>_CustomMapDict` shape already supports multi-form, so the
  underlying mechanics extend cleanly.
- **Multi-LLC.** Single-LLC scope (`WBGroupLLC`).
- **Diff view across tax years.** No "compare 2024 vs 2025 mappings".
- **Bulk import / CSV upload.** Operators edit one fid at a time.
- **Role-based access.** Single-operator tool; auth inherits whatever
  the host Flask app provides.
- **Validation gate.** No commit-blocking checks (see §7).
- **In-app revert / undo.** Recovery is via the timestamped backup
  folders (see §8.3).
- **Diagnostics tab** for namespace anomalies (deferred per §12 Q5).

---

## 11.  Usage estimate

Single-LLC, single-operator scope. Numbers are conservative bounds.

| Activity                                  | Frequency                | Mappings touched per session |
| ----------------------------------------- | ------------------------ | ---------------------------- |
| Initial bookNS author (one-time)          | Once per LLC             | 150 – 250                    |
| Annual Form 1065 prep                     | Once / year (Mar)        | 5 – 25                       |
| K-1 / Sched-K reconciliation              | 1 – 2 / year             | 5 – 15                       |
| Quarterly check-up                        | 4 / year                 | 0 – 3                        |
| IRS form-layout migration (new tax year)  | 1 / year                 | 10 – 40                      |
| Ad-hoc bug fixes after a dry-run          | 5 – 15 / year            | 1 – 3                        |

**Aggregate per year (steady-state, post-bootstrap):**

- Sessions: **10 – 25**
- Total mapping edits: **40 – 120**
- Total Commit (regenerate-FILL.pdf) clicks: **10 – 25**
- Median commit size: **3 – 6 mapping changes per session**
- Average regeneration time (BookToIRS + saveFILL_FromDF): **2 – 4 sec**

**Disk footprint:**

- Per `bookNS_<src>.json`: ~4 – 12 KB (4 source files = ~30 KB total)
- Per `stmt<src>.py` AID-MAPS / AID-CPLX regions: ~10 – 40 lines per
  active custom map; ~5 KB max per source file beyond hand-written code
- 30-deep `.bookNS_backups/`: ~1 – 3 MB
- Total Aid-managed disk: **< 5 MB** (Python source recovery is via
  git, not Aid backups)

**Concurrency:** None. Single browser tab, single operator. The Flask
app is run locally (`localhost:5050`) by the LLC manager. No locking
needed beyond the atomic-write step.

**Performance budget:**

- Per-fid dialog open: **< 200 ms** (one namespace lookup + one
  loadFillDict pass on the relevant stmtOBJ).
- Live-value preview: **< 50 ms** (single `getattr` chain).
- bookNS JSON write + backup: **< 100 ms**.
- Python source surgery + atomic write + `importlib.reload` +
  re-instantiate stmtOBJ: **< 500 ms**.
- Commit (re-run BookToIRS + iframe refresh): **2 – 4 sec** end-to-end.

---

## 12.  Open questions for review

1. **Where should `bookNS_Custom_<src>.json` live?** Proposed:
   `pages/AccountingData/2025/`. Alternative: a year-agnostic
   `pages/AccountingData/Custom/`. ANSWER: DO NOT USE bookNS_Custon_<src>.json, modify stmtOBJ_Tax class with `_Cplx` method per field.
2. **Auto-append Python stubs by default, or opt-in?** Proposed:
   opt-in checkbox, default OFF. Most "Custom" entries can stay as
   registry-only `Complex` placeholders until a calc is needed. ANSWER: auto-append 
3. **Should "delete" be soft-delete (move to a graveyard list) or hard
   delete?** Proposed: hard delete + 30-deep timestamped backup folder. ANSWER: see above, alter the <form>_CustomMapDict.  Do not delete method. 
4. **Show all 440 fids by default, or only fids with bookNS hits?**
   Proposed: all fids, default-filtered to "Mapped + Pending"; toggle
   chip to surface "Blank" rows. ANSWER: show fids in bookNS and in <form>_CustomMapDict.
5. **Should the Aid tool also surface namespace anomalies** (duplicate
   shortNames across pages, container nodes, `image` fields)? Proposed:
   surface in a separate `Diagnostics` tab in v0.2. ANSWER: separate diagnostic

---

## 13.  Implementation milestones

The simpler "no-state-machine, no-validation, dialog-only" v0.1 fits in
roughly half the original budget.

| Step | Deliverable                                                                                       | Est. effort |
| ---- | ------------------------------------------------------------------------------------------------- | ----------- |
| M1   | `BookToIRSAid` service: read fid namespace meta, list bookNS entries, list `<form>_CustomMapDict` entries, return live value | 0.5 day  |
| M2   | "Aid" button on IRS Tax view (Form 1065 + Sch K-1) + per-fid dialog scaffold (HTML/JS, fid picker) | 0.5 day  |
| M3   | Create / Edit / Delete actions on bookNS_<src>.json (atomic write + 30-deep backup)                | 0.5 day  |
| M4   | Custom-map source surgery: AID-MAPS / AID-CPLX region read+write in `stmt<src>.py`, atomic write, `importlib.reload`, stmtOBJ re-instantiation, orphan-stub detection (decision #5) | 1 day    |
| M5   | Advisory chip surface (§7), Commit = re-run BookToIRS + `<iframe>` refresh                          | 0.25 day |
| M6   | Smoke pass: text-bookNS create, checkbox-bookNS create, custom-map create, edit, delete, soft-delete revive, commit | 0.5 day  |
| **Total** |                                                                                              | **~3.25 days** |

Out-of-scope follow-ups (v0.2+):

- Full all-fids grid view (≈1 day).
- Diagnostics tab for namespace anomalies (≈0.5 day).
- Multi-form orchestration (Sch K-1, Form 4562) (≈0.5 day).

---

## 14.  Acceptance checklist (v0.1)

- [ ] On `/view/llcForm1065`, an **Aid** button appears in the toolbar.
- [ ] Clicking **Aid** opens a fid picker (typed search + page-scoped
      lists).
- [ ] Picking a fid (e.g. `F042`) shows the namespace meta
      (`page=1 short=f1_31 fType=text line="Line 11 Repairs"`), the
      current mapping (bookNS row or `<form>_CustomMapDict` entry), and
      the live value `BookToIRS()` would publish today.
- [ ] **Create — bookNS path.** Pick `Source: IS` + `Path: IS.repairs`
      + Save → `bookNS_IS.json` is rewritten, the previous file lands in
      `.bookNS_backups/`, and the dialog re-loads showing the new state.
- [ ] **Create — custom map.** Pick "Add custom map" + Save → a new
      entry lands in `<formNm>_CustomMapDict` *and* a `_Cplx_F042` stub
      is appended in `stmt<src>.py` between the AID markers (no Python
      backup taken — recovery is via git); `importlib.reload` runs; the
      dialog re-loads showing `status=complex`. If a `_Cplx_F042` method
      already exists in the file, the dialog refuses to add a new stub
      and offers **Re-link** instead (decision #5).
- [ ] **Edit.** Switching source / path / promoting to custom map
      writes immediately to disk; no in-memory pending state.
- [ ] **Delete — bookNS.** Removes the `[fid, path]` entry from
      `bookNS_<src>.json`; dialog re-loads showing `status=blank` (or
      whichever lower-priority source now wins).
- [ ] **Delete — custom map.** Removes the `<form>_CustomMapDict[fid]`
      entry; the `_Cplx_<fid>` method body is **preserved** with a
      `# DEPRECATED YYYY-MM-DD` banner; dialog offers `Re-link` to revive.
- [ ] **Output type is read-only** in the dialog, derived from
      `namespace[fid].fType`. When fType is `checkBox` / `checkText`,
      the Field dropdown filters to CHECK_SENTINEL-emitting paths or
      forces a custom map; the resulting mapping toggles `/Btn` on
      checkbox fids and stamps `X` on text fids that opt-in to CHECK.
- [ ] **Commit** re-runs `BookToIRS('Form1065')`, refreshes the embedded
      PDF iframe (`?ts=<unix_ts>`), and shows the
      `pdf_fields / filled / check / complex / blank` summary in a flash
      banner. Errors during the run surface a traceback; disk state is
      unaffected.
- [ ] Backup folder `.bookNS_backups/` accumulates timestamped JSON
      snapshots, capped at 30. (No Python backup folder per decision #3.)
- [ ] All four bookNS sources reachable in the dialog; each lists the
      UAS paths its `loadFillDict()` would currently emit, plus the
      paths declared in `<form>_CustomMapDict`.
- [ ] Advisory chips (§7) appear on type-mismatch / shadowed-priority /
      duplicate-fid conditions; **none** of them block Save.

---

## 15.  Future direction — `llcIRS_AIAgent`

The BookToIRS v0.1 is an early version of an `llcIRS_AIAgent`
concept. The idea is that the `llcIRS_AIAgent` should accumulate
expert knowledge on how to map Financial Book knowledge (`ledger/*`)
into IRS Tax forms.

For example, the current BookToIRS for BS maps `Acct.Rev.Rent` into
form Line 1a-c. But newly discovered knowledge about IRS rules on
Ordinary Income (Active) vs Rental Income (Passive) says that
(a) we should classify Incomes differently and that
`Acct.Rev.Rent` should only go into Sch_K of form 1065 (need
verification).

The knowledge and application of these rules is important. Thus,
the BookToAid services (`BookToIRS()` and the `BookToIRS.aid`
dialogs) should encapsulate this IRS ruling — which ultimately is
captured in the IRS Instruction document. This advanced
`llcIRS_AIAgent` is for a future version.

For now, the `bookNS_<src>.json` per `stmt<src>_Tax`, the
`<form>_CustomMapDict` + `_Cplx_<fid>()` method set, and the
`Profile.<form>.chk[]` array are the foundation for the
`llcIRS_AIAgent`.

### 15.1  Light outline — building blocks

Five layers, roughly in build order:

1. **Knowledge substrate (the data v0.1 already produces).**
   Every confirmed mapping is one of:
   - a `bookNS_<src>.json` row  (1-1 source-path-to-fid),
   - a `<form>_CustomMapDict` entry pointing at a `_Cplx_<fid>()`
     calc, or
   - a `Profile.<form>.chk[]` entry (CHECK sentinel).
   Treat this set as the agent's **fact base** — every fact has a
   provenance (who/what put it there, when) and a cite-link to
   the IRS rule it implements.

2. **Rule corpus (the IRS source of truth).**
   Embed and chunk:
   - Form 1065 Instructions (annual PDF, ~60 pages).
   - Schedule K-1 / B / L / M-1 / M-2 / K-3 instructions.
   - Pub 535 (Business Expenses), Pub 541 (Partnerships),
     Pub 925 (Passive Activity Limits), Pub 946 (Depreciation).
   - Internal Revenue Code §469 (passive activity), §704
     (partner's distributive share), §168 (MACRS).
   Index with a vector store (FAISS / sqlite-vec) keyed by
   `(form, line, paragraph)` so a citation can resolve back to a
   specific page.

3. **Classification reasoning layer (the agent itself).**
   For each ambiguous book-side account (e.g. `Acct.Rev.Rent`),
   the agent answers: *"Which form line(s) accept this entry,
   under what conditions?"* It returns a candidate mapping plus a
   citation. Two-shot loop:
     - first pass = LLM proposes  (with retrieved IRS context),
     - second pass = LLM critiques its own proposal against
       counter-examples in the corpus.
   The Active-vs-Passive split for rental income is a textbook
   example of the kind of distinction this layer must surface
   instead of silently deferring to the human.

4. **Aid dialog integration (light add to v0.2/v0.3).**
   A new "Ask the Agent" button on the per-fid dialog → the
   agent looks at the fid's namespace meta + the LLC's current
   book accounts and proposes a mapping with a cited rule. The
   operator accepts / edits / rejects; on accept, the v0.1 write
   primitives (already shipped) persist the result. The agent
   never writes directly — every commit is operator-mediated.

5. **Feedback loop / regression tests.**
   Capture the operator's accept/reject decisions and any manual
   overrides as an evaluation set. A new IRS-form-year drop
   (annual) re-runs the eval set; mappings whose citation no
   longer resolves to a current paragraph are flagged for review.
   Over years, the eval set becomes the LLC's institutional
   memory of past tax decisions.

### 15.2  Pre-existing work — quick lay of the land

This is *not* a deep survey, just where to start looking when v0.2
work begins:

- **Commercial tax software** (TurboTax Business, H&R Block
  Premium, Lacerte, ProSeries, Drake, UltraTax CS). All of them
  encode IRS form mappings in their interview screens, but the
  rules are proprietary and operator-driven (the human answers
  questions; the software fills the form). They are *not* agentic
  in the sense above — no autonomous reasoning over the
  instructions PDF.
- **Open-source ledger / classification tools.** `hledger`,
  `beancount`, `ledger-cli` have account-classification rules and
  some have report templates but none reason about an IRS form
  per se. `pacioli` has some ontology work in this direction.
- **Tax-LLM research papers.** A small but growing literature on
  retrieval-augmented LLM tax assistants (e.g. work coming out of
  CodeX / Stanford Legal Informatics, MIT-CSAIL on regulatory
  reasoning). Most published prototypes target individual 1040,
  not partnership 1065.
- **Anthropic / OpenAI agentic frameworks.** Claude tool-use,
  Computer Use, MCP, LangGraph, AutoGen. Any of these could host
  the reasoning loop in §15.1 step 3. The `claude-agent-sdk`
  and `tool_use` API are the most direct fit because the agent
  would mostly be issuing structured calls (lookup-rule →
  classify → write-mapping) rather than free-form chat.
- **IRS-side machine-readable artifacts.** The IRS publishes
  some XML schemas for e-file (MeF) and MEF Schemas Guide
  documents. These describe fid layout but **not** the
  classification rules — useful as a sanity-check on the
  namespace fid set, not as a rule corpus.
- **Anthropic Skills (existing).** The `pdf` / `xlsx` / `docx`
  skills inside this repo are scaffolding examples for how a
  task-specialized agent capability is packaged. An
  `llc-irs-mapping` skill would follow the same pattern: a
  SKILL.md describing tools + protocol, with Aid's existing
  routes as the action surface.

### 15.3  Suggested first step (when v0.2 work begins)

Pick **one** known classification ambiguity (the
Active-vs-Passive rental example above is a good candidate),
write the rule down in plain English with a citation
(Pub 925 §1, §469(c)(2)), and prototype the §15.1-step-3
reasoning loop on that *single* case. Do not generalize until
that one round-trip — *book account → cited rule → recommended
mapping → operator accept → bookNS row written* — works
end-to-end. Everything else (corpus indexing, eval set,
feedback loop) is scaffolding around that core round-trip and
can be built incrementally once the loop pays off.
