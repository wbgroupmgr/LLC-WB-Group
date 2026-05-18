# From Notebook to Production: Two Months Building an LLC Accounting App with Claude

*A story about real estate, double-entry bookkeeping, and the surprisingly philosophical experience of debugging session cookies at 3am.*

---

## The Setup (No Pun Intended)

It started simple enough. A multi-member real estate LLC. A few rental properties. A shared need to track income, expenses, depreciation, and eventually file IRS Form 1065 with Schedule K-1s for each partner.

The existing workflow: a tangle of Jupyter notebooks, Excel sheets, and a shared Google Drive folder with files named things like `LLC-WB-Group_Final_FINAL_v3.xlsx`. Maintainable by no one. Auditable by no one. Tax-season panic every year.

The goal: a proper double-entry ledger, automated IRS form population, and a Flask web editor so any partner could review the books from anywhere — including from PythonAnywhere, so there's no server to babysit.

The plan: build it with Claude.

Two months later, we have `v0.3.0` tagged, all views live on PythonAnywhere, and I'm writing this instead of fixing bugs. That's either a good sign or dangerous overconfidence.

---

## Theme 1: Claude as Pair Programmer — The Good, The Weird, and The "Wait, What?"

Working with Claude on a months-long project is genuinely different from asking it a one-off question. You start to develop something like a shared mental model of the codebase. When I say "the GL merge order," Claude knows exactly which four sources I mean and why the order matters. That saves a lot of throat-clearing.

But here's what surprised me: the *discipline* Claude brings. Every time I was tempted to take a shortcut — hardcode a path, add a try/except that swallows errors, copy-paste a route instead of refactoring — there was this quiet voice saying "that'll work, but here's the maintenance cost." Not preachy. Just clear-eyed.

The most memorable exchange was around the IRS Form 4562 depreciation pipeline. I had a rough idea of what I needed. Claude had read the actual IRS publication. When we sat down to map LLC asset records to form line items, it wasn't me explaining accounting to Claude — it was closer to two accountants comparing notes. That shouldn't work. It did.

The weird part: context limits. A coding session is not a conversation — it has a hard ceiling. We solved this with structured handoffs: CLAUDE.md files that encode not just "what does this code do" but "what decisions have we made and why." Reading your own CLAUDE.md at the start of a session is oddly like reading a letter from your past self. *Dear future Frank, here's what you were thinking...*

---

## Theme 2: The Architecture Journey — Or, How a Jupyter Notebook Became Three Git Repos

Version 0.1 was a single Jupyter notebook. By v0.3, we have:

- **`pyMultiTaskWS`** — a Werkzeug DispatcherMiddleware platform that mounts multiple Flask tracker apps under one uWSGI server. Think of it as the building that houses the apps.
- **`llcRentalTracker`** — the actual LLC financial management app. Double-entry ledger, financial statements, IRS form pipeline, Flask web editor.
- **`LLC-WBGroup`** — the business data repo. JSON ledger files, PDF outputs, bank statements. Completely separate from app code.

Splitting the business data from the application code sounds obvious in retrospect. It was not obvious at the time. It took a dedicated architecture session where we drew out the data flow, realized the notebooks directory had become a God module, and methodically split responsibilities across packages.

The accounting engine (`ledger/`) doesn't know about Flask. The statement objects (`stmt/`) are immutable once constructed — attribute writes raise `StmtImmutableError`. The Flask layer (`ui/`) is thin wiring. The IRS pipeline (`irs/`) maps ledger accounts to form line items without touching the database.

This separation meant we could test the accounting logic independently of the web layer. When a Balance Sheet number was wrong, we knew the bug was in `ledger/` or `stmt/`, not in a template. That's boring, predictable debugging — which is exactly what you want.

---

## Theme 3: The Deployment Gauntlet — Everything That Can Go Wrong Under uWSGI

Here's where the project got *educational*.

PythonAnywhere runs your app under uWSGI with three worker processes. uWSGI uses preforking: the master process initializes the app, then forks three workers. This is great for performance. It is terrible if your Flask `secret_key` is `secrets.token_hex(32)` — random at initialization time.

What happens: Worker 1 handles your login POST, sets a session cookie signed with key `abc123`. Worker 2 handles the next request with key `xyz789`. Session invalid. Not logged in. Redirect to `/login`. 

We chased this bug through three other layers first:

**Layer 1:** Templates with hardcoded paths (`action="/login"`, `href="/logout"`). Under `DispatcherMiddleware`, your app is mounted at `/rentalTracker`. Hardcoded `/login` goes to the root server. Fixed with `url_for()` everywhere.

**Layer 2:** `request.path` doesn't include the mount prefix. `SCRIPT_NAME=/rentalTracker` is stripped before Flask sees the request. So `redirect(url_for("login", next=request.path))` stores `/` as the return URL, and after login you're redirected to the MultiTaskWS home page, not your app. Fixed with `request.script_root + request.path`.

**Layer 3:** The `before_request` guard fires during Werkzeug's trailing-slash redirect, when `request.endpoint` is `None`. The guard was treating this as a protected request and injecting a `next=/login/` loop. Fixed with `if not request.endpoint: return`.

**Layer 4:** The actual session bug. Three fixes in, login still broken. Added structured logging. Saw the startup message: `secret_key_src=derived`. All three workers deriving different keys. Fixed by reading `WEB_SECRET_KEY` from `~/.MultiTaskWS/MultiTaskWS_config.json` — which MultiTaskWS already generates and manages.

**Layer 5:** `LLC_GPG_PASSPHRASE` not set. The user database is GPG-encrypted. The passphrase is stored in the LLC profile JSON (written by `wsCmd.py --setup`), loaded by the LLC object (`_Profile` does `setattr` for every key), accessible as `eSession.llc.MultiTaskWS_Config["LLC_GPG_PASSPHRASE"]`. Injected into env in `llcMgmt.__init__`. Done.

**Layer 6:** IRS form views showing "Not Found." The PDF iframe src was `f"/forms/Form8825.pdf"` — same hardcoded-path bug, different file. Fixed with `url_for("serve_irs_pdf", form_id=form_nm)`.

Total time debugging deployment: approximately four sessions. Total lines changed: under 50. The lesson: distributed systems surface assumptions your code makes about running in a single process with full path control. Every assumption you haven't made explicit will bite you in production.

---

## What's Next

Tomorrow: 2025 bookkeeping. Reconcile bank statements, enter transactions, balance the books, generate the K-1s.

The app exists to do exactly this. That's a strange feeling — building a tool for months and then actually using it for its intended purpose.

The next milestone: v0.4 will be about data quality — bank reconciliation, audit trail, and the kind of double-checking that accountants do before they hand anything to the IRS.

We'll also be cleaning up the codebase. Two months of active development leaves fingerprints: a function that should be a method, a constant that should be config, a comment that explains what the code does instead of why. None of it is broken. All of it could be better.

---

*W&B Group, LLC — Built with Claude Code. Tested in production. Probably fine.*

*`v0.3.0` tagged 2026-05-18.*
