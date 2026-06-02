# Login & Registration Design — LLC Accounting App

Authentication and user-registration layer for the LLC Management App (`llcMgmt`).

---

## Problem Statement — Why the Current Design Fails

The original design stored `pw.json.gpg` inside the Business Repo (`LLC-WBGroup`) and
encrypted it with a **platform-specific** `LLC_GPG_PASSPHRASE`. This creates an
irreconcilable conflict:

```
Business Repo push/pull  ──▶  overwrites pw.json.gpg on the other platform
                               (file encrypted with different passphrase)
                               ──▶ gpg: decryption failed: Bad session key
                               ──▶ login broken
```

Every time local pushes changes to `LLC-WBGroup` that include a locally-encrypted
`pw.json.gpg`, PA's login breaks (and vice versa). This is what happened in `680f1ac`.

---

## Requirements

### R1 — Platform Independence
The Business Repo (`LLC-WBGroup`) must be deployable to any platform (PA, local, new
server) without breaking login on already-installed platforms.

### R2 — Single MASTER Passphrase
The operator (`llcgroupmgr`) supplies one **MASTER passphrase** per installation.
That passphrase unlocks all other per-instance secrets. It is never stored on disk
or committed to any repo.

### R3 — Per-Instance Secrets in `keys.json.gpg`
All secrets needed to run the app on a specific platform are packaged in a single
GPG-encrypted file `books/Accts/keys.json.gpg`, encrypted with the MASTER passphrase.

Contents:
```json
{
  "LLC_GPG_PASSPHRASE": "<passphrase for pw.json.gpg on this platform>",
  "LLC_SECRET_KEY":     "<Flask session secret for this platform>"
}
```

`keys.json.gpg` **IS committed to the Business Repo** — it is safe because it can
only be decrypted with the MASTER passphrase, which is never in the repo.

### R4 — `pw.json.gpg` is Instance-Local (NOT in repo)
`pw.json.gpg` is a runtime artifact — users change passwords, accounts are created
and deleted. It must **never** be committed to the Business Repo.

Add `books/Accts/pw.json.gpg` to `.gitignore` in `LLC-WBGroup`.

`pw.json.gpg` is encrypted with `LLC_GPG_PASSPHRASE` (from `keys.json.gpg`).
On a fresh install, `wsCmd.py --setup` creates it with the seed user.

### R5 — BUS Push/Pull Does Not Touch Login
Syncing the Business Repo only carries:
- Accounting data files (`*.json`)
- `keys.json.gpg` (encrypted — safe to share)

It never carries `pw.json.gpg`. Login state is isolated per-platform.

### R6 — `wsCmd.py --setup` Is the Install/Recovery Tool
`--setup` on any platform:
1. Prompts for the MASTER passphrase
2. Decrypts `keys.json.gpg` → extracts `LLC_GPG_PASSPHRASE` and `LLC_SECRET_KEY`
3. Writes these to the profile (`llcProfile_*.json` → `MultiTaskWS_Config`)
4. If `pw.json.gpg` absent → creates it with the seed user encrypted with `LLC_GPG_PASSPHRASE`
5. If `pw.json.gpg` present → verifies it decrypts correctly; if not, prompts to reset

### R7 — PA Environment Variable (Runtime Only)
PA needs `LLC_MASTER_PASSPHRASE` set in its environment tab.
At startup, `wsCmd.py` (or `wsgi.py`) reads it, decrypts `keys.json.gpg`, and
injects `LLC_GPG_PASSPHRASE` + `LLC_SECRET_KEY` into the process environment.

---

## Architecture

```
Business Repo (LLC-WBGroup)          App Code Repo (llcRentalTracker)
books/
  Accts/
    keys.json.gpg  ◀── IN REPO        ui/llcLogin_auth.py
    pw.json.gpg    ◀── .gitignore      wsCmd.py (--setup, --start)
    *.json (data)  ◀── IN REPO
  2025/
    Forms/         ◀── IN REPO
    BankStmts/     ◀── IN REPO


Two-layer decryption at startup:
                                                        
  MASTER passphrase (env var)                          
       │                                               
       ▼  gpg --decrypt                                
  keys.json.gpg  ──▶  { LLC_GPG_PASSPHRASE,            
                         LLC_SECRET_KEY }               
                              │                        
                              ▼  gpg --decrypt          
                         pw.json.gpg  ──▶  [users]      
```

---

## Secret Ownership per Platform

| Secret | Where stored | Who sets it |
|---|---|---|
| `LLC_MASTER_PASSPHRASE` | Platform env var (PA tab / local `.env`) | Operator |
| `LLC_GPG_PASSPHRASE` | Inside `keys.json.gpg` (repo) | `wsCmd.py --setup` |
| `LLC_SECRET_KEY` | Inside `keys.json.gpg` (repo) | `wsCmd.py --setup` |
| `pw.json.gpg` | `books/Accts/` (NOT in repo) | `wsCmd.py --setup` |

---

## File Layout (revised)

```
books/
  Accts/
    keys.json.gpg          ← IN REPO — encrypted with MASTER passphrase
    pw.json.gpg            ← .gitignore — instance-local, encrypted with LLC_GPG_PASSPHRASE
    ChartOfAccounts_*.json ← IN REPO
    llcAssets_*.json       ← IN REPO
    ...
  2025/
    Forms/                 ← IN REPO (year-specific filed docs)
    BankStmts/             ← IN REPO
```

`llcLogin_auth.py` reads `ACCTS_DIR / "pw.json.gpg"` — unchanged.

---

## `wsCmd.py --setup` Flow (revised)

```
1. Prompt:  Enter MASTER passphrase:  ___________
2. Decrypt: books/Accts/keys.json.gpg  →  { LLC_GPG_PASSPHRASE, LLC_SECRET_KEY }
3. Write:   llcProfile.json MultiTaskWS_Config → passphrase fields
4. Check:   books/Accts/pw.json.gpg exists?
     YES → test decrypt with LLC_GPG_PASSPHRASE
             ✓ OK  →  print "✓ User DB verified"
             ✗ BAD →  if --reset: delete + re-create with seed user
                      else: print "⚠ Wrong passphrase — run with --reset to recreate"
     NO  → create pw.json.gpg with seed user encrypted with LLC_GPG_PASSPHRASE
5. Done.
```

---

## `wsgi.py` / Startup Flow (revised)

```python
# On startup, inject secrets from keys.json.gpg into process env
# so llcLogin_auth can find LLC_GPG_PASSPHRASE at request time.

import os, json
from pathlib import Path

def _inject_from_keys(accts_dir: Path, master_pp: str):
    keys_file = accts_dir / "keys.json.gpg"
    if not keys_file.exists():
        return
    from ui.llcLogin_auth import _gpg_decrypt
    data = json.loads(_gpg_decrypt(keys_file, master_pp))
    for k, v in data.items():
        if k not in os.environ:          # don't override explicit env vars
            os.environ[k] = v

master = os.environ.get("LLC_MASTER_PASSPHRASE", "")
if master:
    _inject_from_keys(setup_paths.ACCTS_DIR, master)
```

---

## PA Fix Plan (immediate — no code changes needed yet)

The current PA failure: `pw.json.gpg` in `books/Accts/` is missing (or encrypted with
local passphrase). Fix on PA using existing tools:

### Step 1 — Verify PA's working password file
```bash
# On PA console:
gpg --batch --decrypt \
    --passphrase "$LLC_GPG_PASSPHRASE" \
    ~/LLC-WBGroup/books/2025/Accts/pw.json.gpg
# Should print the JSON user array. If it does, this is the good file.
```

### Step 2 — Copy it to the new path
```bash
cp ~/LLC-WBGroup/books/2025/Accts/pw.json.gpg \
   ~/LLC-WBGroup/books/Accts/pw.json.gpg
# Do NOT git add this file — it must stay out of the repo
```

### Step 3 — Add .gitignore entry in LLC-WBGroup
```bash
cd ~/LLC-WBGroup
echo "books/Accts/pw.json.gpg" >> .gitignore
git add .gitignore
git commit -m "chore: gitignore pw.json.gpg — instance-local, not repo artifact"
git push
```

### Step 4 — Test login
Reload the PA app and confirm login works.

---

## Remaining Work (after PA login is restored)

### Phase A — Create `keys.json.gpg` on PA
```bash
# On PA, create the keys file with the current per-platform secrets:
python3 -c "
import json, os, subprocess, tempfile
keys = {
    'LLC_GPG_PASSPHRASE': os.environ['LLC_GPG_PASSPHRASE'],
    'LLC_SECRET_KEY':     os.environ.get('LLC_SECRET_KEY', ''),
}
plaintext = json.dumps(keys).encode()
# ... encrypt with LLC_MASTER_PASSPHRASE and write to books/Accts/keys.json.gpg
"
git add books/Accts/keys.json.gpg
git commit -m "feat: add keys.json.gpg — per-instance secrets bootstrap"
git push
```

### Phase B — Update `wsCmd.py --setup`
- Read `LLC_MASTER_PASSPHRASE` (prompt if not in env)
- Decrypt `keys.json.gpg` → extract per-instance secrets
- Check/create `pw.json.gpg`

### Phase C — Update `wsgi.py` startup
- Inject `LLC_GPG_PASSPHRASE` and `LLC_SECRET_KEY` from `keys.json.gpg` at startup
- PA only needs `LLC_MASTER_PASSPHRASE` in its environment tab (not all secrets)

### Phase D — Update this doc
- Finalize after Phase A-C are implemented and tested

---

## Outstanding Questions

| # | Question | Impact |
|---|---|---|
| 1 | Should `LLC_GPG_PASSPHRASE` be the same on PA and local, or platform-specific? | If same: one `keys.json.gpg` works everywhere. If different: each platform has its own `keys.json.gpg` (more isolated but more complex) |
| 2 | Should `pw.json.gpg` be portable (same file, same passphrase on all platforms)? | Yes → simpler. Means `LLC_GPG_PASSPHRASE` is shared. Users/passwords sync via manual export |
| 3 | Where is the MASTER passphrase documented for the operator? | PA: env tab. Local: `~/.llcRentalTracker/config.json` passphrase field or `.env` |
| 4 | What happens if `keys.json.gpg` is not yet created (pre-Phase A)? | `wsgi.py` skips injection gracefully; `LLC_GPG_PASSPHRASE` must still be in env directly |

---

## Original Design (still valid — unchanged)

### User DB Schema
```json
{
  "username":   "llcgroupmgr",
  "password":   "<sha-256 hex>",
  "full_name":  "LLC Group Manager",
  "role":       "llcManager",
  "created_at": "2026-01-01T00:00:00"
}
```

### Seed User (after `--setup`)
| Field | Value |
|---|---|
| `username` | `llcgroupmgr` |
| `password` | `llcmanager` (SHA-256 stored) |
| `role` | `llcManager` |

**Change this password immediately after first login.**

### Roles
| Role | Description |
|---|---|
| `member` | Read access |
| `llcManager` | Full operational access |
| `bookkeeper` | Transaction entry |
| `accountant` | Financial review |

### GPG CLI Reference
```bash
# Decrypt to stdout (inspect)
gpg --batch --decrypt --passphrase "$LLC_GPG_PASSPHRASE" books/Accts/pw.json.gpg

# Re-encrypt with new passphrase
gpg --batch --decrypt --passphrase "$OLD_PP" books/Accts/pw.json.gpg \
  | gpg --batch --symmetric --cipher-algo AES256 \
        --passphrase "$NEW_PP" --output books/Accts/pw.json.gpg
```
