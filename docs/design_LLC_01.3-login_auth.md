# Login, Auth & Configuration Design — llcRentalTracker

**Status:** Current as of Phase 2+3 migration (June 2026).  
**Platform docs:** See [pyMultiTaskWS/docs/design_configuration.md](../../../pyMultiTaskWS/docs/design_configuration.md) and [design_setup_adminTracker.md](../../../pyMultiTaskWS/docs/design_setup_adminTracker.md) for platform-level context.

---

## 1. Design Principles

Per [design_configuration.md §1](../../../pyMultiTaskWS/docs/design_configuration.md):

- Each tracker owns its secrets in `~/.<trackerRepo>/config.json` — no cross-tracker sharing.
- `APP_GPG_PASSPHRASE` and `APP_SECRET_KEY` are unique per tracker instance.
- No fallback for required secrets — hard fail at startup if either is missing.
- PA = master host for BUS data; only PA pushes commits to `LLC-WBGroup`.

---

## 2. Three-Repo Architecture

```
pyMultiTaskWS/          ← web platform + adminTracker (one repo)
llcRentalTracker/       ← this app
LLC-WBGroup/            ← BUS data: accounting JSON, pw.json.gpg
```

At runtime each repo serves a distinct role:
- `pyMultiTaskWS` dispatches requests to mounted trackers (`/admin/`, `/rentalTracker/`).
- `llcRentalTracker` handles all `/rentalTracker/*` routes.
- `LLC-WBGroup` provides the accounting DB and the encrypted user DB (`pw.json.gpg`).

---

## 3. Config File Hierarchy

### 3.1 Platform Config — `~/.MultiTaskWS/config.json`

Owned by `pyMultiTaskWS`. Holds platform secrets and the `Trackers` routing list.

```json
{
  "WEB_SECRET_KEY": "<platform Flask key>",
  "Trackers": [
    { "name": "AdminTracker",      "mount": "/admin",         "builtin": true,  "stanza_key": "adminTracker" },
    { "name": "llcRentalTracker",  "mount": "/rentalTracker", "builtin": false, "stanza_key": "llcRentalTracker",
      "sys_path": "/home/wbgroup/pyTrackers/llcRentalTracker" }
  ],
  "adminTracker": {
    "APP_GPG_PASSPHRASE": "<adminTracker-specific passphrase>",
    "APP_SECRET_KEY":     "<adminTracker-specific key>"
  }
}
```

**Key rules:**
- External tracker stanzas (like `llcRentalTracker`) are NOT in the platform config — each tracker reads its own `~/.<tracker>/config.json`.
- `sys_path` tells the dispatcher where to find the tracker's `wsgi.py`.
- Written by `pyMultiTaskWS/wsCmd.py --setup` (platform) and populated by `llcRentalTracker/wsCmd.py --addTracker` (tracker registration).

### 3.2 Tracker Config — `~/.llcRentalTracker/config.json`

Owned exclusively by `llcRentalTracker`. This is the **sole authority** for this tracker's secrets and BUS registration. No fallback, no platform stanza needed at runtime.

```json
{
  "default": ["WBGroupLLC", 2025],
  "APP_SECRET_KEY": "<Flask session signing key — unique to this tracker>",
  "llcList": [
    {
      "llcName":            "WBGroupLLC",
      "dataName":           "WBGroupLLC",
      "bus_repo":           "/home/wbgroup/llc/LLC-WBGroup",
      "books_dir":          "books",
      "years":              [2025],
      "APP_GPG_PASSPHRASE": "<passphrase for pw.json.gpg — unique to this BUS>"
    }
  ]
}
```

**Schema rules:**
- `APP_SECRET_KEY` is top-level (per-tracker, one Flask signing key).
- `APP_GPG_PASSPHRASE` is inside the stanza (per-BUS, encrypts that BUS's `pw.json.gpg`).
- `years` is an array (supports multiple fiscal years per BUS).
- `master_passphrase` and `keys.json.gpg` are **removed** — they were a prior design workaround.

---

## 4. Startup Sequence

```
pyMultiTaskWS/wsgi.py  (PA WSGI entry point)
  │
  ├─ WsCmd().make_application()
  │     ├─ Load ~/.MultiTaskWS/config.json
  │     ├─ Mount adminTracker at /admin (builtin)
  │     └─ For each external Tracker in Trackers list:
  │           importlib.exec_module(sys_path/wsgi.py)
  │           → mounts at t["mount"]
  │
  └─ llcRentalTracker/wsgi.py  (exec'd by dispatcher)
        │
        ├─ setup_paths.load_config(LLC_NAME, LLC_YEAR)
        │     ← reads ~/.llcRentalTracker/config.json
        │     ← sets TOP, ACCTS_DIR, IRS_FORMS_DIR, YEAR, SECRETS
        │
        ├─ _inject_secrets()
        │     ← SECRETS["APP_GPG_PASSPHRASE"] → os.environ["LLC_GPG_PASSPHRASE"]
        │     ← config["APP_SECRET_KEY"]       → os.environ["LLC_SECRET_KEY"]
        │     ← hard RuntimeError if either is missing (no silent fallback)
        │
        ├─ path validation (bus_repo + Accts/ must exist on disk)
        │
        └─ llcMgmt(eSession).app  → Flask app mounted at /rentalTracker
              └─ app.secret_key ← os.environ["LLC_SECRET_KEY"]
```

### 4.1 Session Cookie Config

```python
# llcMgmt.__init__
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # send on top-level nav (popup/new-tab)
app.config["SESSION_COOKIE_PATH"]     = "/"      # all paths on this domain
```

Sessions are **always permanent** (expiry-dated cookie):
- Without "Remember me": 8-hour expiry.
- With "Remember me": 30-day expiry.

Non-permanent session cookies are unreliable across new browser windows and popup tabs — always use permanent.

---

## 5. Setup Workflows

### 5.1 New PA Instance (full setup from scratch)

```bash
# ── Step 1: Platform setup ───────────────────────────────────────────────────
cd ~/pyMultiTaskWS
python3 wsCmd.py --setup
# → creates ~/.MultiTaskWS/config.json (WEB_SECRET_KEY, adminTracker stanza)
# PA Web tab: point WSGI config to ~/pyMultiTaskWS/wsgi.py → Reload

# ── Step 2: Clone BUS repo ───────────────────────────────────────────────────
mkdir ~/llc && cd ~/llc
git clone https://github.com/wbgroupmgr/LLC-WBGroup.git

# ── Step 3: Register BUS + set tracker passphrase ────────────────────────────
mkdir ~/pyTrackers && cd ~/pyTrackers
git clone https://github.com/wbgroupmgr/llcRentalTracker.git
cd llcRentalTracker

python3 wsCmd.py --newBus ~/llc/LLC-WBGroup --year 2025 --llcName WBGroupLLC
# → prompts: Enter APP_GPG_PASSPHRASE (unique to this tracker — not shared with adminTracker)
# → creates ~/.llcRentalTracker/config.json with llcList stanza + APP_GPG_PASSPHRASE

# ── Step 4: Generate APP_SECRET_KEY + create user DB ─────────────────────────
python3 wsCmd.py --setup --llcName WBGroupLLC
# → generates APP_SECRET_KEY
# → writes complete secrets to ~/.llcRentalTracker/config.json
# → creates LLC-WBGroup/books/Accts/pw.json.gpg (seed user)
# → registers llcRentalTracker in ~/.MultiTaskWS/config.json Trackers list

# ── Step 5: Register tracker routing in platform ─────────────────────────────
python3 wsCmd.py --addTracker
# → adds llcRentalTracker entry (sys_path, mount, stanza_key) to ~/.MultiTaskWS/config.json
# NOTE: --setup now calls addTracker automatically; run --addTracker if missed

# ── Step 6: Push pw.json.gpg from PA (master host) ───────────────────────────
cd ~/llc/LLC-WBGroup
git add books/Accts/pw.json.gpg
git commit -m "auth: initial user DB"
git push

# ── Step 7: Reload PA + login ─────────────────────────────────────────────────
# PA Web tab → Reload
# https://<pa-host>/rentalTracker/login
# Seed user: llcgroupmgr / llcManager0!  ← CHANGE IMMEDIATELY
```

### 5.2 Local Dev Setup

```bash
cd /path/to/llcRentalTracker
python3 wsCmd.py --newBus /path/to/LLC-WBGroup --year 2025 --llcName WBGroupLLC
# → enter SAME APP_GPG_PASSPHRASE as PA (needed to decrypt PA's pw.json.gpg)
# → creates ~/.llcRentalTracker/config.json

python3 wsCmd.py --setup --llcName WBGroupLLC
# → generates a LOCAL APP_SECRET_KEY (different from PA — fine for dev)
# → does NOT write pw.json.gpg (pull from BUS repo — local never writes it)

cd /path/to/LLC-WBGroup && git pull   # gets PA's pw.json.gpg

cd /path/to/llcRentalTracker
python3 wsCmd.py --start --llcName WBGroupLLC --year 2025 --port 5000 --load
```

### 5.3 Add a New Fiscal Year

```bash
cd ~/pyTrackers/llcRentalTracker
python3 wsCmd.py --newBus ~/llc/LLC-WBGroup --year 2026 --llcName WBGroupLLC
# → appends 2026 to existing stanza: years: [2025, 2026]
# PA Web tab → Reload
```

### 5.4 Stale .pyc After Git Pull (symptom: 500 on login with KeyError)

After a git pull that changes `setup_paths.py`, stale bytecode may run old code against the new config schema:

```bash
find /home/wbgroup/pyTrackers/llcRentalTracker -name "*.pyc" -delete
find /home/wbgroup/pyTrackers/llcRentalTracker -name "__pycache__" -type d -exec rm -rf {} +
# PA Web tab → Reload
```

---

## 6. Secret Naming Convention

| Secret | Key Name | Location | Scope |
|---|---|---|---|
| Flask session cookie | `APP_SECRET_KEY` | top-level in `~/.llcRentalTracker/config.json` | per-tracker |
| GPG passphrase for `pw.json.gpg` | `APP_GPG_PASSPHRASE` | inside llcList stanza | per-BUS |
| Platform Flask key | `WEB_SECRET_KEY` | `~/.MultiTaskWS/config.json` | platform-wide |
| adminTracker GPG | `APP_GPG_PASSPHRASE` | adminTracker stanza in `~/.MultiTaskWS/config.json` | adminTracker |

At runtime, `wsgi.py` maps:
- `APP_GPG_PASSPHRASE` → `os.environ["LLC_GPG_PASSPHRASE"]`
- `APP_SECRET_KEY` → `os.environ["LLC_SECRET_KEY"]`

---

## 7. File Ownership

| File | In Repo | Who writes | Pushed from |
|---|---|---|---|
| `books/Accts/pw.json.gpg` | ✅ BUS repo | `llcLogin_auth` (user mgmt) | **PA only** |
| `books/Accts/*.json` | ✅ BUS repo | App save actions | **PA only** |
| `~/.llcRentalTracker/config.json` | ❌ Never | `wsCmd.py --newBus/--setup` | Never pushed |
| `~/.MultiTaskWS/config.json` | ❌ Never | `pyMultiTaskWS/wsCmd.py --setup` | Never pushed |
| `keys.json.gpg` | **Removed** | — was a prior-design workaround | — |

---

## 8. User DB Schema

```json
{
  "username":   "llcgroupmgr",
  "password":   "<sha-256 hex of password>",
  "full_name":  "LLC Group Manager",
  "role":       "llcManager",
  "created_at": "2026-01-01T00:00:00"
}
```

Seed user (created by `--setup`): `llcgroupmgr` / `llcManager0!` — **change on first login**.

### Roles

| Role | Access |
|---|---|
| `llcManager` | Full operational access |
| `bookkeeper` | Transaction entry |
| `accountant` | Financial review |
| `member` | Read-only |

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/rentalTracker/login` returns 404 | Tracker not in platform Trackers list | Run `wsCmd.py --addTracker` + Reload |
| 500 on login with `KeyError: 'year'` | Stale `.pyc` after git pull | Delete `__pycache__` dirs + Reload |
| PDF popup redirects to login | Non-permanent session cookie | Fixed in v1.0: session always permanent |
| `APP_GPG_PASSPHRASE missing` RuntimeError | `~/.llcRentalTracker/config.json` malformed | Run `wsCmd.py --newBus` again |
| Namespace JSON not found | First run; auto-builds from IRS PDF | Run `python3 testForm.py --form <Form>` once |

---

## 10. Prior Design (superseded — do not implement)

The prior design used `master_passphrase` + `keys.json.gpg` as an intermediate layer.
This was a workaround for the missing `llcRentalTracker` platform stanza (Bug 1 in
`issue_trackerConfigSetup.md`). The Phase 2+3 migration eliminated this layer entirely.

**Removed artifacts:**
- `books/Accts/keys.json.gpg` — deleted from BUS repo.
- `master_passphrase` in `~/.llcRentalTracker/config.json` — field removed.
- `LLC_GPG_PASSPHRASE` / `LLC_SECRET_KEY` in `llcProfile MultiTaskWS_Config` — removed.

The `issue_trackerConfigSetup.md` document in `pyMultiTaskWS/docs/` is the complete
migration log and is retained for historical reference.
