# MultiTrack Web Platform — Architecture & PythonAnywhere Deployment

---

## 1. Concept & Architecture

### 1.1 What Is MultiTrack?

**MultiTrack** is an architected web platform where multiple independent
task-focused applications — called **Trackers** — coexist under a single
web server host. Each Tracker is fully self-contained: its own codebase,
its own user database, its own URL namespace, and its own authentication
domain. The platform scales horizontally: adding a new Tracker requires
no changes to existing ones.

This pattern is standard in enterprise web design under names such as
*application hub*, *sub-application hosting*, or *WSGI application
dispatch*. The terminology used here maps to those concepts:

| MultiTrack term | Standard web-design equivalent |
|---|---|
| **Platform** | Application hub / hosting container |
| **Dispatcher** | WSGI router / `DispatcherMiddleware` |
| **Tracker** | Mounted sub-application / bounded context |
| **Tracker Entry Point** | WSGI callable (`wsgi.py`) |
| **Mount point** | URL prefix / `APPLICATION_ROOT` |
| **Tracker ID** | Application namespace (URL slug) |

---

### 1.2 Component Hierarchy

```
PythonAnywhere Web App (MultiTrack)
│
└── Dispatcher  (DispatcherMiddleware)
    │   Routes incoming requests by URL prefix to the correct Tracker.
    │   Each unmatched prefix returns 404.
    │
    ├── /llc  ──────────────→  LLC Tracker  (WBGroup LLC Editor)
    │                              └── Flask app  ←  wsgi.py
    │
    ├── /trackHealth  ──────→  Health Tracker  (future)
    │                              └── Flask app  ←  wsgi.py
    │
    └── /trackFinance  ─────→  Finance Tracker  (future)
                                   └── Flask app  ←  wsgi.py
```

**Request flow:**

```
Browser → PA WSGI server
       → Dispatcher (strips prefix, sets SCRIPT_NAME)
       → Tracker Flask app (sees only its own sub-path)
       → Response (Flask reconstructs full URLs via SCRIPT_NAME)
```

---

### 1.3 URL Namespace

Every Tracker owns a distinct URL subtree:

```
https://wbgroup.pythonanywhere.com/<TrackerID>/
    ├── <TrackerID>/login       ← Tracker login page
    ├── <TrackerID>/            ← Tracker home (requires login)
    ├── <TrackerID>/view/<...>  ← Tracker views
    └── <TrackerID>/api/<...>   ← Tracker API
```

The `<TrackerID>` is the mount point string and must be globally unique
across the Platform. It is also used as the directory name on disk.

**Current Trackers:**

| TrackerID | URL | Application |
|---|---|---|
| `llc` | `/llc/login` | WBGroup LLC Editor |

---

### 1.4 Authentication Model

Each Tracker maintains its **own independent user database**
(`Accts/pw.json.gpg`). Users registered in one Tracker have no
access to any other. There is no cross-Tracker single sign-on at
this time. The `<TrackerID>/login` page is each Tracker's entry gate.

---

## 2. Platform Directory Layout on PA

```
/home/wbgroup/
│
├── multitrack_wsgi.py          ← Platform WSGI file (PA points here)
│
├── llc/                        ← TrackerID directory
│   └── LLC-WB-Group/           ← git repo root
│       ├── pages/
│       │   └── AccountingData/
│       │       ├── Accts/
│       │       │   └── pw.json.gpg     ← Tracker user DB (not in git)
│       │       └── Notebooks/          ← sys.path root
│       │           ├── wsgi.py         ← Tracker Entry Point
│       │           ├── setupWebServerCmd.py
│       │           ├── init_userdb.py
│       │           ├── ledger/
│       │           ├── ui/
│       │           └── util/
│       └── requirements.txt
│
├── trackHealth/                ← future TrackerID directory
│   └── <repo>/
│       └── wsgi.py             ← Tracker Entry Point
│
└── trackFinance/               ← future TrackerID directory
    └── <repo>/
        └── wsgi.py
```

**Convention:** `TrackerID == directory name under /home/wbgroup/`

---

## 3. PythonAnywhere Setup

> PA custom plan assumed: 2 web apps available.
> **Web App 1** = MultiTrack Platform.
> **Web App 2** = reserved for a separate purpose (staging, another project).

---

### 3.1 Step 0 — PA Dashboard: Create the MultiTrack Web App

1. Go to [pythonanywhere.com](https://www.pythonanywhere.com) → sign in.
2. **Dashboard → Web tab → Add a new web app**
   - Domain: `wbgroup.pythonanywhere.com` (default)
   - Framework: **Manual configuration**
   - Python version: **3.10**
3. In the **Code** section of the Web tab:
   - **WSGI configuration file** field → change the path to:
     ```
     /home/wbgroup/multitrack_wsgi.py
     ```
   - **Source code** → `/home/wbgroup/`
4. Leave the page open — you will paste the WSGI content in Step 3.

---

### 3.2 Step 1 — PA Bash Console: Clone and Set Up Each Tracker

Open a **Bash console** (Dashboard → Consoles → Bash).

**For the LLC Tracker (first time only):**

```bash
# Create the TrackerID directory and clone
mkdir -p ~/llc
cd ~/llc
git clone https://github.com/wbgroupmgr/LLC-WB-Group.git

# Run the interactive setup script
cd LLC-WB-Group/pages/AccountingData/Notebooks
python3.10 setupWebServerCmd.py
```

`setupWebServerCmd.py` handles:

| Step | Action |
|------|--------|
| 1 | Prompts for `LLC_GPG_PASSPHRASE` (min 12 chars) |
| 2 | Installs `flask pandas numpy pypdf deepdiff` via pip |
| 3 | Seeds `Accts/pw.json.gpg` with `llcgroupmgr / llcManager0!` |
| 4 | Generates `LLC_SECRET_KEY`; stores in `pw.json.gpg` under `wbgadminWS.notes` |
| 5 | Prints credentials to embed in the Platform WSGI file |

Save the printed credentials — you need them in the next step.

---

### 3.3 Step 2 — Create the Platform WSGI File

In the Bash console:

```bash
nano ~/multitrack_wsgi.py
```

Paste and fill in the values printed by `setupWebServerCmd.py`:

```python
import sys, os
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.exceptions import NotFound

# ── LLC Tracker ───────────────────────────────────────────────────────────────
os.environ.setdefault('LLC_GPG_PASSPHRASE', '<passphrase-from-setup-script>')
os.environ.setdefault('LLC_SECRET_KEY',     '<secret-key-from-setup-script>')
sys.path.insert(0, '/home/wbgroup/llc/LLC-WB-Group/pages/AccountingData/Notebooks')
from wsgi import application as llc_app

# ── Future Trackers (uncomment when ready) ────────────────────────────────────
# os.environ.setdefault('HEALTH_GPG_PASSPHRASE', '...')
# os.environ.setdefault('HEALTH_SECRET_KEY',     '...')
# sys.path.insert(0, '/home/wbgroup/trackHealth/<repo>/...')
# from wsgi import application as health_app

# ── Dispatcher ────────────────────────────────────────────────────────────────
application = DispatcherMiddleware(NotFound(), {
    '/llc':          llc_app,
    # '/trackHealth':  health_app,
    # '/trackFinance': finance_app,
})
```

> **Security:** `multitrack_wsgi.py` is readable only by your PA account
> (file mode 600 by default). This is the only place credentials are stored
> in plaintext — keep it out of any git repo.

---

### 3.4 Step 3 — Reload and Test

1. PA **Web tab → Reload** button.
2. Visit `https://wbgroup.pythonanywhere.com/llc/login`
3. Log in: `llcgroupmgr` / `llcManager0!`

---

### 3.5 Adding a Future Tracker

```bash
# 1. Console: create TrackerID dir, clone, run its setup script
mkdir -p ~/trackHealth
cd ~/trackHealth
git clone https://github.com/wbgroupmgr/<health-repo>.git
cd <health-repo>/...
python3.10 setupWebServerCmd.py

# 2. Edit ~/multitrack_wsgi.py — uncomment/add the Tracker block
nano ~/multitrack_wsgi.py

# 3. PA Web tab → Reload
```

---

### 3.6 Updating a Tracker

```bash
cd ~/llc/LLC-WB-Group
git pull origin main
```

Then **PA Web tab → Reload**. No WSGI file changes needed.

---

## 4. Tracker Developer Guidelines

The LLC Editor is the **reference implementation** for building a Tracker.
Any new Tracker must follow these conventions to integrate cleanly with
the Dispatcher.

### 4.1 Required: `wsgi.py` Entry Point

Every Tracker repo must expose a `wsgi.py` at its `sys.path` root that:
1. Adds its own package root to `sys.path`
2. Initialises any session/config objects
3. Exposes `application` — a WSGI callable (the Flask `app` object)

```python
# Tracker wsgi.py pattern
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from <tracker>.session import init_session
from <tracker>.app import AppClass

_session = init_session(...)
_mgmt    = AppClass(_session)
application = _mgmt.app        # ← Flask app object
```

### 4.2 Required: No Hardcoded URL Paths in Templates

When Flask is mounted at a sub-path via `DispatcherMiddleware`, the
WSGI server sets `SCRIPT_NAME` (e.g., `/llc`). Flask's `url_for()`
picks this up automatically and generates correct absolute URLs.
**Hardcoded path strings do not.**

| Pattern | Mounted at `/llc` result | Correct? |
|---|---|---|
| `action="/login"` | Posts to `/login` (wrong root) | ✗ |
| `href="/logout"` | Navigates to `/logout` (wrong root) | ✗ |
| `action="{{ url_for('login') }}"` | Posts to `/llc/login` | ✓ |
| `href="{{ url_for('logout') }}"` | Navigates to `/llc/logout` | ✓ |
| `window.location.href = "/logout"` | Navigates to `/logout` (JS, wrong) | ✗ |
| `window.location.href = "{{ url_for('logout') }}"` | `/llc/logout` | ✓ |

> **Action item for LLC Tracker:** Templates `login.html`, `register.html`,
> `base.html`, and `home.html` contain hardcoded paths that must be converted
> to `url_for()` calls before the Dispatcher mount is activated.

### 4.3 Required: `setupWebServerCmd.py`

Every Tracker must provide a setup script that:
- Prompts for the Tracker's GPG passphrase
- Installs pip dependencies
- Seeds the Tracker's user DB
- Generates and stores `SECRET_KEY`
- Prints the WSGI block to add to `multitrack_wsgi.py`

### 4.4 Required: Isolated User DB

Each Tracker stores its user database at `Accts/pw.json.gpg` **within
its own repo**. Passphrases and secret keys are distinct per Tracker.
A user registered in one Tracker does not exist in another.

### 4.5 Recommended: Tracker ID Convention

- Short, lowercase, URL-safe slug: `llc`, `health`, `finance`
- Used consistently as: directory name, mount point, and pip package name
- No hyphens (use underscores in Python package names)

### 4.6 Recommended: Dependency Isolation

Trackers share the same PA Python environment. To avoid version
conflicts, prefer pinning major versions in `requirements.txt` and
avoiding overlapping package name conflicts.

---

## 5. Key Files Reference

| File | Scope | Purpose |
|------|-------|---------|
| `~/multitrack_wsgi.py` | Platform | Dispatcher config; mounts all Trackers; holds env vars |
| `<tracker>/wsgi.py` | Tracker | WSGI entry point; exposes `application` |
| `<tracker>/setupWebServerCmd.py` | Tracker | One-shot interactive setup for PA |
| `<tracker>/init_userdb.py` | Tracker | Low-level seed helper |
| `<tracker>/Accts/pw.json.gpg` | Tracker | Encrypted user DB (not in git) |
| `<tracker>/requirements.txt` | Tracker | Python dependencies |

---

## 6. Security Notes

| Concern | Approach |
|---------|---------|
| Credentials in WSGI | `multitrack_wsgi.py` is owner-readable only; never committed to git |
| GPG passphrase | Per-Tracker env var; passed to subprocess via `os.pipe()` (invisible in `ps`) |
| Flask secret key | Generated at setup; stored in `pw.json.gpg` under `wbgadminWS.notes` |
| User passwords | SHA-256 hashed; plaintext never written to disk |
| Cross-Tracker isolation | Separate user DBs, separate passphrases, separate Flask secret keys |

---

## 7. User DB Schema

`Accts/pw.json.gpg` decrypts to a JSON array. Standard user record:

```json
{
  "username":   "llcgroupmgr",
  "password":   "<sha256-hex>",
  "full_name":  "WBGroup LLC",
  "phone":      "",
  "role":       "llcManager",
  "created_at": "2026-01-01T00:00:00"
}
```

The `wbgadminWS` record stores the web server secret key:

```json
{
  "username":   "wbgadminWS",
  "password":   "",
  "full_name":  "webserver admin",
  "role":       "llcManager",
  "notes":      "<64-char-hex-secret-key>",
  "created_at": "..."
}
```

---

## 8. Role Permissions

> **Note:** Permission enforcement is a future implementation item.
> The table below defines the intended policy; no role-based restrictions
> are active in the current codebase.

| Role | Views | Fields | DB | Registration |
|------|-------|--------|----|--------------|
| `llcManager` | View All | All | Refresh | New, Delete, Edit |
| `member` | View All | View Only | No Refresh | No access |
| `bookkeeper` | View All | Edit | Session Only | No access |
| `accountant` | View All | View Only | No Refresh | No access |
| `wbgadminWS` | View All | View Only | No Refresh | New, Delete, Edit |

**Column definitions:**

- **Views** — which pages/statements the role can access
- **Fields** — read-only vs. editable transaction fields
- **DB** — `Refresh` = can reload/new-session; `Session Only` = working-file edits, no DB write; `No Refresh` = read-only session
- **Registration** — ability to `New` / `Delete` / `Edit` user accounts in `pw.json.gpg`
