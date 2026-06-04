# LLC Task App — Web Server Design

## Overview

The LLC Editor is a **task application** that runs in two modes:

| Mode | Entry point | When to use |
|------|-------------|-------------|
| **local** | Flask dev server on this machine | Development, data entry, ad-hoc runs |
| **hosted** | Registered with MultiTaskWS dispatcher on PythonAnywhere | Shared / always-on access |

All web server management is handled by a single script:

```
pages/AccountingData/Notebooks/wsCmd.py
```

---

## wsCmd.py — Command Reference

Run from `pages/AccountingData/Notebooks/`.

### Setup (first time or reset forgotten passphrase)

```bash
python3.10 wsCmd.py --setup --llcName WBGroupLLC
python3.10 wsCmd.py --setup --reset --llcName WBGroupLLC
```

`--reset` deletes `pw.json.gpg` before setup so a fresh DB is created with the new passphrase. Use when the old passphrase is lost or the DB is corrupt. All existing user accounts are removed.

**Setup steps:**

| Step | Action |
|------|--------|
| 0 (--reset only) | Delete `pw.json.gpg` — requires typing YES |
| 1 | Prompt for `LLC_GPG_PASSPHRASE` (min 12 chars, confirmed) |
| 2 | `pip install` dependencies (flask, pandas, numpy, pypdf, deepdiff) |
| 3 | Generate `LLC_SECRET_KEY`; write `MultiTaskWS_Config` stanza to `llcProfile_WBGroupLLC.json` |
| 4 | Seed `pw.json.gpg` with default `llcgroupmgr` user; create `wbgadminWS` record |

---

### Start — local mode (Scenario A)

```bash
python3.10 wsCmd.py --start --llcName WBGroupLLC
python3.10 wsCmd.py --start --llcName WBGroupLLC --addr localhost --port 5001 --load
```

Credentials are read automatically from `llcProfile_WBGroupLLC.json → MultiTaskWS_Config`
(no `LLC_GPG_PASSPHRASE=` prefix needed after `--setup` has been run).

**Options:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--addr IP` | `127.0.0.1` | Flask bind address |
| `--port N` | `5000` | Flask port |
| `--debug` | off | Enable Flask debug mode |
| `--load` | off | Load existing working data into the session |
| `--edOpt OPT` | `llc` | Editor option: `llc` \| `llcAsset` \| `llcExpRev` |
| `--notebook` | off | Jupyter notebook display mode |

**Login URL:** `http://<addr>:<port>/login`

> **macOS / Chrome note:** Chrome 94+ blocks redirects to the bare `127.0.0.1`
> address (Private Network Access policy). Use `--addr localhost` or open
> `http://localhost:5000/login` in the browser. `curl` and non-Chrome browsers
> are unaffected.

---

### Start — hosted mode (Scenario B / placeholder)

```bash
python3.10 wsCmd.py --start --host --llcName WBGroupLLC
```

Hosted start is managed by the MultiTaskWS dispatcher. The task app is registered via `wsgi.py` and activated by the PA Web tab → Reload. This flag currently prints an informational message only.

---

## Credentials

### Primary store — llcProfile (plain JSON)

`pages/AccountingData/Accts/llcProfile_WBGroupLLC.json` holds a `MultiTaskWS_Config` stanza:

```json
"MultiTaskWS_Config": {
  "LLC_SECRET_KEY":     "<64-char hex>",
  "LLC_GPG_PASSPHRASE": "<passphrase>",
  "WebServer":          "local_FranksMacBook"
}
```

This file is plain JSON — **no passphrase required to read it**. It is the authoritative recovery source.

**Read credentials at any time:**

```bash
python3 -c "
import json
p = 'pages/AccountingData/Accts/llcProfile_WBGroupLLC.json'
cfg = json.load(open(p))['MultiTaskWS_Config']
print(json.dumps(cfg, indent=2))"
```

### Environment variables

At runtime the server reads:

| Variable | Purpose |
|----------|---------|
| `LLC_GPG_PASSPHRASE` | Decrypts / encrypts `pw.json.gpg` |
| `LLC_SECRET_KEY` | Flask session signing key |

---

## User Database

File: `pages/AccountingData/Notebooks/ui/Accts/pw.json.gpg`  
Encryption: GPG symmetric AES-256, passphrase = `LLC_GPG_PASSPHRASE`.

### Schema (per user record)

| Field | Type | Notes |
|-------|------|-------|
| `username` | str | Login name |
| `password` | str | bcrypt hash |
| `full_name` | str | Display name |
| `phone` | str | Optional |
| `role` | str | See Roles below |
| `notes` | str | Optional admin notes |
| `created_at` | ISO-8601 str | |

### Default / seed accounts

| Username | Password | Role | Purpose |
|----------|----------|------|---------|
| `llcgroupmgr` | `llcManager0!` | `llcManager` | Default login — change after first sign-in |
| `wbgadminWS` | *(none)* | `llcManager` | Admin marker; notes point to llcProfile credentials |

### Roles

| Role | Access |
|------|--------|
| `llcManager` | Full read/write access to all LLC editor views |

---

## Lessons Learned — Session 2026-06-02

### Architecture
- **Two-layer GPG secrets model**: `~/.llcRentalTracker/config.json` holds a MASTER passphrase → decrypts `keys.json.gpg` → yields `LLC_GPG_PASSPHRASE` + `LLC_SECRET_KEY` → decrypts `pw.json.gpg` (user DB). The MASTER passphrase never enters the repo; `keys.json.gpg` and `pw.json.gpg` are committed. All platforms sharing the same `LLC_GPG_PASSPHRASE` (from their local `keys.json.gpg`) can decrypt `pw.json.gpg`.
- **PA = master host rule**: Only PythonAnywhere (PA) pushes commits to the Business Repo (`LLC-WBGroup`). Local machines pull only. This ensures `pw.json.gpg` committed to the repo is always encrypted with PA's passphrase, which all platforms know via `keys.json.gpg`. Breaking this rule causes `gpg: decryption failed: Bad session key` on PA.
- **`wsCmd --newBus` bootstrap**: New-business provisioning sequence: `--newBus <path>` creates the LLC repo skeleton, copies template JSONs, runs `--setup` to generate `LLC_SECRET_KEY` and seed `pw.json.gpg`. The `--F` force flag skips confirmation prompts for CI/scripted runs.
- **Flask route registration order**: Static route patterns (`/view/yeFinancialReport`) must be registered before dynamic catch-all patterns (`/view/<obj_type>`). Flask matches routes in registration order and will never reach the static route if the dynamic one is registered first.

### Software Engineering
- **Lazy imports at CLI entry points**: `wsCmd.py` must defer any `import` that transitively pulls in `deepdiff` (or other optional heavy deps) to the function body that needs it, not the module top-level. A bare `import deepdiff` at module level will crash `wsCmd.py --start` on hosts where deepdiff is not installed, even if the start path never uses deepdiff.
- **`importlib.util.spec_from_file_location` bypasses package `__init__.py`**: Use this when a module is safe to import standalone but its package `__init__.py` has heavy transitive deps. Critical for `wsCmd.py` loading `llcMgmt.py` without triggering the full `uillc` package init.

---

## Key Files

| File | Purpose |
|------|---------|
| `wsCmd.py` | All web server management (setup + start) |
| `wsgi.py` | WSGI entry point for hosted (PA) deployment |
| `ui/Accts/pw.json.gpg` | Encrypted user DB |
| `Accts/llcProfile_WBGroupLLC.json` | Entity metadata + `MultiTaskWS_Config` credentials |
| `util/utilEditSession.py` | Session coordinator — wires LLC working files into Flask |
| `uillc/llcMgmt.py` | Flask application factory for the LLC editor |
