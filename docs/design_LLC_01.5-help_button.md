# Help Button — Design Recommendation

## Goal
Every view has a **?** button that opens context-sensitive help (GitHub Markdown docs)
and a feedback link (email to llcgroupmgr).

---

## Approach: Slide-in Panel (no page navigation)

A `<details>`-style slide-in drawer that renders GitHub Markdown inline.
No new routes. No page reload. User stays in context.

### 1. Flask route — `/help/<doc_name>`

```python
@app.route("/help/<doc_name>")
@login_required
def help_doc(doc_name: str):
    """Return rendered HTML for a docs/*.md file."""
    import re, markdown
    allowed = re.compile(r'^[\w\-]+$')
    if not allowed.match(doc_name):
        abort(404)
    md_path = Path(__file__).resolve().parent.parent / "docs" / f"{doc_name}.md"
    if not md_path.exists():
        abort(404)
    html = markdown.markdown(md_path.read_text(), extensions=["tables", "fenced_code"])
    return jsonify({"html": html})
```

Add `markdown` to `requirements.txt`.

### 2. Per-view help mapping

In `llcMgmt.py`, add a dict mapping `obj_type` → doc name:

```python
HELP_DOCS = {
    "llcAssets":          "design_LLC_App-Accounting",
    "llcExpRev":          "design_LLC_AccountingWorkflow",
    "stmtGeneralLedger":  "design_ui_GLViews",
    "stmtBalanceSheet":   "design_LLC_Accounting-SOP",
    "stmtIncomeStmt":     "design_LLC_Accounting-SOP",
    "llcForm1065":        "design_LLC_BookToIRS_Aid",
    "llcForm8825":        "design_IRS_Form4562",
    "llcFormK1":          "design_IRS_Sch_K1",
    # default fallback:
    "_default":           "utilEditorLLC-UserGuide",
}
```

Pass `help_doc=HELP_DOCS.get(obj_type, HELP_DOCS["_default"])` to every template.

### 3. Base template — help drawer + button

In `base.html` `<body>`, add once:

```html
<!-- Help drawer -->
<div id="help-drawer" style="
    position:fixed; right:0; top:0; height:100vh; width:min(480px,90vw);
    background:white; box-shadow:-4px 0 20px rgba(0,0,0,.2);
    overflow-y:auto; padding:20px; z-index:500;
    transform:translateX(100%); transition:transform .25s ease;
">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <strong>Help</strong>
    <button onclick="closeHelp()" style="background:none;border:none;font-size:20px;cursor:pointer">✕</button>
  </div>
  <div id="help-content" class="markdown-body"></div>
  <hr style="margin:20px 0">
  <p style="font-size:13px">
    💬 <strong>Feedback / suggestions:</strong>
    <a href="mailto:wbgroupmgr@gmail.com?subject=llcRentalTracker feedback">wbgroupmgr@gmail.com</a>
  </p>
</div>

<script>
function openHelp(docName) {
    fetch(`{{ url_for('help_doc', doc_name='__DOC__') }}`.replace('__DOC__', docName))
        .then(r => r.json())
        .then(d => {
            document.getElementById('help-content').innerHTML = d.html;
            document.getElementById('help-drawer').style.transform = 'translateX(0)';
        });
}
function closeHelp() {
    document.getElementById('help-drawer').style.transform = 'translateX(100%)';
}
</script>
```

### 4. Help button in title-panel toolbar

Each view template already has a `.toolbar-row`. Add:

```html
<button class="btn btn-secondary"
        title="Help for this view"
        onclick="openHelp('{{ help_doc }}')">?</button>
```

### 5. Feedback collection via email

The mailto link in the drawer pre-fills subject line. For richer feedback (screenshots,
structured form), a future enhancement could POST to `/api/feedback` which appends
to a `feedback_log.json` — but email is sufficient for now.

---

## What to write in the docs

Each help doc should follow this template:

```
# <View Name>

## What this view shows
One paragraph.

## How to use it
Numbered steps for the common workflow.

## Fields explained
Table: Field | Meaning | Example

## Common questions
Q&A bullet list.

## Related views
Links to related docs.
```

---

## Implementation effort

| Item | Effort |
|------|--------|
| Flask `/help/<doc_name>` route | 30 min |
| `base.html` drawer + script | 1 hr |
| Per-view `help_doc=` in route | 30 min |
| Write 5 core help docs | 2-3 hrs |

Total: ~half day. Recommend as a v0.3.1 task before bookkeeping season
brings new users to the app.
