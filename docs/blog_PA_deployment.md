# From Notebook to Production: Two Months Building an LLC Accounting App with Claude

*A story about real estate, double-entry bookkeeping, and the surprisingly philosophical experience of debugging session cookies - an 8hr session.*

---

## The Setup (No Pun Intended)

It started simple enough. A multi-member real estate LLC. A few rental properties. A shared need to track income, expenses, depreciation, and eventually file IRS Form 1065 with Schedule K-1s for each partner.

The existing workflow: a tangle of Jupyter notebooks, Excel sheets, and a shared Google Drive folder with files named things like `LLC-WB-Group_Final_FINAL_v3.xlsx`. Maintainable by no one. Auditable by no one. Tax-season panic every year.

The goal: a proper double-entry ledger, automated IRS form population, and a Flask web editor so any partner could review the books from anywhere — including from PythonAnywhere, so there's no server to babysit.

The plan: build it with Claude.

Two months later, we have `v0.7.0` tagged, all views live on PythonAnywhere, and I'm writing this instead of fixing bugs. That's either a good sign or dangerous overconfidence.

---

## Theme 1: Claude as Pair Programmer — The Good, The Weird, and The "Wait, What?"

Working with Claude on a months-long project is genuinely different from asking it a one-off question. You start to develop something like a shared mental model of the codebase. When I say "the GL merge order," Claude knows exactly which four sources I mean and why the order matters. That saves a lot of throat-clearing.

But here's what surprised me: the *discipline* Claude brings. Every time I was tempted to take a shortcut — hardcode a path, add a try/except that swallows errors, copy-paste a route instead of refactoring — there was this quiet voice saying "that'll work, but here's the maintenance cost." Not preachy. Just clear-eyed.

The most memorable exchange was around the IRS Form 4562 depreciation pipeline. I had a rough idea of what I needed. Claude had read the actual IRS publication. When we sat down to map LLC asset records to form line items, it wasn't me explaining accounting to Claude — it was closer to two accountants comparing notes. That shouldn't work. It did.

The weird part: context limits. A coding session is not a conversation — it has a hard ceiling. We solved this with structured handoffs: CLAUDE.md files that encode not just "what does this code do" but "what decisions have we made and why." Reading your own CLAUDE.md at the start of a session is oddly like reading a letter from your past self. *Dear future Frank, here's what you were thinking...*

---

## Theme 2: The Architecture Journey — Or, How a Jupyter Notebook Becomes a Multi-tier Business Solution

Version 0.1 started as a single Jupyter notebook with no github and 2 `core` simple json databases:
- llcAssets.json - manual entry of property purchase: simple "purchase a house"
- llcExpRev.json - bank -> expenses and revenues;  with simple pattern matching to classify transactions

By v0.7, we have 3 repositories

- **`pyMultiTaskWS`** — a web server (pythonanywhere.com) that allows multiple web apps to co-exist on 1 host. Think of it as the building that houses the apps.  Used claude to  expand my limited knowledge of web hosting. [Disciplines: hosting, WSGI, Werkzeug DispatcherMiddleware platform, provisioning multiple Flask tracker apps under one uWSGI server]. 
- **`llcRentalTracker`** — the actual LLC financial management app that implements an end to end accounting pipeline. [Discipline: accounting/IRS standards, COA, double-entry ledger, financial statements, IRS form pipeline, Flask web editor, data::service separation]
- **`LLC-WBGroup`** — This contains the Property Rental LLC business files/data - completely separate from app code..   The original collection of LLC incorporation, house purchase and rental and operating procedures.  [Discipline: rental business, LLC, accounting account ledgers/Databases, JSON ledger files, PDF outputs, bank statements.] 

Splitting the business data from the application code sounds obvious in retrospect. It was not obvious at the time. It took iterations and understanding the different disciplines to arrive at semi multi-discipline architecture drawn out across several iterations.   Key was documenting both the data flow and the code flow.  

The biggest transformation is realizing the original jupyter notebooks directory had become the God module, and methodically each discipline was split into "micro services".  Each had its own responsibilities across packages.

The accounting engine (`ledger/`) doesn't know about Flask. The statement objects (`stmt/`) are immutable (can not change) once constructed — attribute writes raise `StmtImmutableError`. The Flask layer (`ui/`) is thin wiring. The IRS pipeline (`irs/`) maps ledger accounts to form line items without touching the database.

This separation meant we could test the accounting logic independently of the web layer. When a Balance Sheet number was wrong, we knew the bug was in `ledger/` or `stmt/`, not in a template. That's boring, predictable debugging — which is exactly what you want.

---

## Theme 3: The art of learning 

In software development they have the art of `debugging` - finding & correcting faults in the code.
In accounting bookkeeping they have the art of `auditing` - finding & correcting faults in the books.
In religious communities they have the art of `santification` - finding & correcting faults in oneself.
And on and on across all disciplines. 

Every discipline has the art of `finding and correcting faults`. For AI this discipline is the `art of finding and correcting faults in learning`.  Let me explain.

I consider myself to be a mediocre software programmer, a nerd. I know a little about everything and I could claim to specialize in "data analysis". 

For the 1st time in my 70 years of life I am starting an LLC in the Property Rental business.  I know very little about LLC's, rental management, accounting, user interface and  web hosting - basically a child novice is all of these.   But the progression shows that within 1 year with AI I am pulling it off.

Finding faults in the books versus asking AI to find the faults -- THE MAJOR INSIGHT.  A case in point.   In building the General Ledger, I first relied on my data analysis skills to ask claud to generate a dataframe/excel spreadsheet from aggregating all the transaction.   This is all a General Ledger is.  Simple, right?

Well then I learned about "dual entry" accounting requirements, ie. the best practice as the means to ensure `the financial books` were in order.   Dual entry is a devil requiring one to develop quantum skills in multiple universes.  The concept is simple - for every transaction against the bank, one has to record its dual entry into its associated "account" (assets, equity, liability).  Then one finds there are standard Charts of Account naming practices. Ok, I can manage this. 

Sorry, i get bogged down in the details.   

So after lots of learning, and faults in my learning I get the General Ledger view working -- but there is a simple rule of GL.  The Debits must equal the Credits.   Think of it simply: the transactions against the bank has match the recording in the financial accounts (assets, equity and liabilities). Then I learned about `Trial Balance` which is to aggregate all the accounts to simplify the view of all the transaction per accounts. 

After composing the the GL and generating the trial balance - the golden rule of my LLC GL shows that my Debits does not equal my Credits!  Spent several days seeking... then the art of learning AI sparks.   I asked claude AI to develop an "auditor service" that I can invoke from the GL view and to report where it suspects the inbalance is.

Eurika!  The report found the duplicate transactions across 2 different databases.   This allowed me to fix it. 

The insight to develop the `auditor service` reflects the `art of learning` with claude AI. Overall, we are all novice in dealing with AI as a co-worker.  This too is the art of learning. 

---

## Theme 4: The Deployment Gauntlet — Everything That Can Go Wrong Under uWSGI

Here's where the project got *educational*.

PythonAnywhere.com is a hosting service.  It runs your app under `uWSGI` - an open source hosting service.  For novice, think of WSGI as "the host" that routes internet traffic to your app.   It is a LOT of techie lingo and technology.   Having three worker processes to distribute workload. uWSGI uses preforking: the master process initializes the app, then forks three workers. This is great for performance. 

Learning about `secret key` - a long random identifier for each app.   It is terrible if your Flask `secret_key` is `secrets.token_hex(32)` — random at initialization time.

What happens: Worker 1 handles your login POST, sets a session cookie signed with key `abc123`. Worker 2 handles the next request with key `xyz789`. Session invalid. Not logged in. Redirect to `/login`. 

This is where claude AI has it max value.   It chased this bug through three other layers first:

**Layer 1:** Templates with hardcoded paths (`action="/login"`, `href="/logout"`). Under `DispatcherMiddleware`, your app is mounted at `/rentalTracker`. Hardcoded `/login` goes to the root server. Fixed with `url_for()` everywhere.

**Layer 2:** `request.path` doesn't include the mount prefix. `SCRIPT_NAME=/rentalTracker` is stripped before Flask sees the request. So `redirect(url_for("login", next=request.path))` stores `/` as the return URL, and after login you're redirected to the MultiTaskWS home page, not your app. Fixed with `request.script_root + request.path`.

**Layer 3:** The `before_request` guard fires during Werkzeug's trailing-slash redirect, when `request.endpoint` is `None`. The guard was treating this as a protected request and injecting a `next=/login/` loop. Fixed with `if not request.endpoint: return`.

**Layer 4:** The actual session bug. Three fixes in, login still broken. Added structured logging. Saw the startup message: `secret_key_src=derived`. All three workers deriving different keys. Fixed by reading `WEB_SECRET_KEY` from `~/.MultiTaskWS/MultiTaskWS_config.json` — which MultiTaskWS already generates and manages.

**Layer 5:** `LLC_GPG_PASSPHRASE` not set. The user database is GPG-encrypted. The passphrase is stored in the LLC profile JSON (written by `wsCmd.py --setup`), loaded by the LLC object (`_Profile` does `setattr` for every key), accessible as `eSession.llc.MultiTaskWS_Config["LLC_GPG_PASSPHRASE"]`. Injected into env in `llcMgmt.__init__`. Done.

**Layer 6:** IRS form views showing "Not Found." The PDF iframe src was `f"/forms/Form8825.pdf"` — same hardcoded-path bug, different file. Fixed with `url_for("serve_irs_pdf", form_id=form_nm)`.

Total time debugging deployment: approximately four sessions. Total lines changed: under 50. The lesson: distributed systems surface assumptions your code makes about running in a single process with full path control. Every assumption you haven't made explicit will bite you in production.

---

## What's Next

With all the accounting books now in place, the actual LLC bookkeeping can begin to ensure all the transactions are journaled correctly and the final sheets are balanced.   Reconcile bank statements, enter transactions, balance the books, generate the K-1s.

The app exists to do exactly this. That's a strange feeling — building a tool for months and then actually using it for its intended purpose.

Once the books are balanced and the IRS forms filled in, we will declare release/v1.0 -- MAJOR RELEASE. 

The next milestone: v2.0 will be about data quality — bank reconciliation, audit trail, and the kind of double-checking that accountants do before they hand anything to the IRS.

We'll also be cleaning up the codebase. Two months of active development leaves fingerprints: a function that should be a method, a constant that should be config, a comment that explains what the code does instead of why. None of it is broken. All of it could be better.

---

*W&B Group, LLC — Built with Claude Code. Tested in production. Probably fine.*

*`v0.7.0` tagged 2026-05-18.*
