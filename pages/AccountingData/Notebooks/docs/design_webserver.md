# LLC App — PythonAnywhere Deployment Guide

Covers the one-time setup to host the LLC Accounting Flask app on
PythonAnywhere (PA).

---

## Directory Layout on PA

```
/home/<pa-username>/
└── LLC/
    └── LLC-WB-Group/          ← git repo root (TOP)
        ├── pages/
        │   └── AccountingData/
        │       ├── Accts/
        │       │   └── pw.json.gpg    ← encrypted user DB
        │       └── Notebooks/         ← sys.path root
        │           ├── wsgi.py        ← WSGI entry point
        │           ├── setupWebServerCmd.py   ← run this once
        │           ├── init_userdb.py         ← seed-user helper
        │           ├── ledger/
        │           ├── ui/
        │           └── util/
        └── requirements.txt
```

---

## One-Time Setup — Step by Step

### Step 0 — Log into PythonAnywhere

1. Go to [pythonanywhere.com](https://www.pythonanywhere.com) and sign in.
2. **Dashboard → Web → Add a new web app**
   - Framework: **Manual configuration**
   - Python version: **3.10**
3. Keep the Web tab open — you'll paste the WSGI config in Step 4.

All remaining steps are run in a **PA Bash console**
(Dashboard → Consoles → Bash).

---

### Step 1 — Clone the repo

```bash
mkdir -p ~/LLC
cd ~/LLC
git clone https://github.com/wbgroupmgr/LLC-WB-Group.git
```

---

### Step 2 — Run the setup script

The script handles pip install, user-DB seeding, secret-key generation,
and prints the ready-to-paste WSGI config.

```bash
cd ~/LLC/LLC-WB-Group/pages/AccountingData/Notebooks
python3.10 setupWebServerCmd.py
```

The script walks through five steps interactively:

| Step | What it does |
|------|--------------|
| 1 | Prompts for `LLC_GPG_PASSPHRASE` (min 12 chars, confirmed) |
| 2 | Installs `flask pandas numpy pypdf deepdiff` via pip |
| 3 | Creates `Accts/pw.json.gpg` with seed user `llcgroupmgr / llcManager0!` |
| 4 | Generates `LLC_SECRET_KEY`; stores it in `pw.json.gpg` under user `wbgadminWS` (field: `notes`) |
| 5 | Prints the WSGI file content with paths and credentials filled in |

---

### Step 3 — Paste the WSGI configuration

In the PA **Web tab**, click the **WSGI configuration file** link.
Replace the entire file content with the block printed by the script:

```python
import sys, os

# Credentials — readable only by your PA account.
os.environ.setdefault('LLC_GPG_PASSPHRASE', '<your-passphrase>')
os.environ.setdefault('LLC_SECRET_KEY',     '<generated-64-char-hex>')

sys.path.insert(0, '/home/<pa-username>/LLC/LLC-WB-Group/pages/AccountingData/Notebooks')
from wsgi import application
```

The script prints the exact values — copy/paste as-is.

---

### Step 4 — Reload and test

1. Hit **Reload** in the PA Web tab.
2. Visit `https://<pa-username>.pythonanywhere.com`
3. Log in: `llcgroupmgr` / `llcManager0!`
4. Use `/register` to add a bookkeeper or member account.

---

## Updating the App

Whenever new code is pushed to GitHub:

```bash
cd ~/LLC/LLC-WB-Group
git pull origin main
```

Then hit **Reload** in the PA Web tab. No other steps needed.

---

## Key Files

| File | Purpose |
|------|---------|
| `Notebooks/wsgi.py` | WSGI entry point — instantiates `utilEditSession` + `llcMgmt`, exposes `application` |
| `Notebooks/setupWebServerCmd.py` | One-shot setup script (run once on PA) |
| `Notebooks/init_userdb.py` | Low-level seed helper (used by setup script; can also run standalone) |
| `Accts/pw.json.gpg` | GPG-encrypted user DB; not in git repo |
| `requirements.txt` | Python dependency list (repo root) |

---

## Security Notes

| Concern | Approach |
|---------|---------|
| GPG passphrase | Stored only in the PA WSGI file (owner-readable) and `os.environ`; never in the git repo |
| Flask secret key | Generated at setup time; stored in `pw.json.gpg` under `wbgadminWS.notes`; also in the WSGI file |
| GPG subprocess | Passphrase passed via `os.pipe()` fd — invisible in `ps aux` process listings |
| User passwords | SHA-256 hashed before storage; plaintext never written to disk |
| PA free tier | Web app sleeps after inactivity; wakes on first request (~5s delay) |

---

## User DB Schema

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

The `wbgadminWS` record adds a `notes` field that holds `LLC_SECRET_KEY`:

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

## Allowed Roles

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

- **Views** — which pages/statements the role can see
- **Fields** — read-only vs. editable transaction fields
- **DB** — `Refresh` = can trigger DB reload/new session; `Session Only` = working-file edits only, no DB write; `No Refresh` = read-only session
- **Registration** — ability to create (`New`), remove (`Delete`), or modify (`Edit`) user accounts in `pw.json.gpg`
