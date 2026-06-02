# Login & Registration Design — LLC Accounting App

Authentication and user-registration layer for the LLC Management App (`llcMgmt`).

---

## Problem Statement — Why the Original Design Failed

The original design encrypted `pw.json.gpg` with a **platform-specific**
`LLC_GPG_PASSPHRASE` and committed it to the Business Repo. When local pushed
`680f1ac`, the locally-encrypted `pw.json.gpg` overwrote PA's copy → PA could
no longer decrypt it → `gpg: decryption failed: Bad session key` → login broken.

Root cause: different passphrases on different platforms + same file in the repo.

---

## Design Decisions

### D1 — One Master Host (PA) pushes; all others pull
There is exactly **one authoritative host** — PA (PythonAnywhere). It is the only
host that ever pushes commits to the Business Repo (`LLC-WBGroup`).
Local machines and any other hosts **pull only** and never push data files.

This means `pw.json.gpg` committed by PA is always encrypted with PA's passphrase.
As long as all platforms share the **same `LLC_GPG_PASSPHRASE`** (extracted from
`keys.json.gpg`), every platform can decrypt PA's `pw.json.gpg`.

### D2 — MASTER passphrase stored in `~/.llcRentalTracker/config.json`
The MASTER passphrase lives in the existing per-host config file, not in an
environment variable. This keeps the startup sequence self-contained — `wsCmd.py`
and `wsgi.py` already read this file for LLC/year config.

```json
{
  "master_passphrase": "<MASTER_PP>",
  "default": ["WBGroupLLC", 2025],
  "llcList": [...]
}
```

**Security note:** `~/.llcRentalTracker/config.json` is a file on the host filesystem,
protected by host OS permissions (mode 600 recommended). It is never committed to any
repo.

### D3 — `pw.json.gpg` remains in the Business Repo
Because D1 ensures only PA pushes it, and D2 ensures all platforms share the same
`LLC_GPG_PASSPHRASE`, `pw.json.gpg` can safely live in the repo. Any host that
pulls gets a file it can decrypt with the same passphrase from `keys.json.gpg`.

No `.gitignore` entry needed.

---

## Requirements

### R1 — Single source of truth for user accounts
PA (master host) owns `pw.json.gpg`. User management (add/delete/change password)
is done on PA. After any user-DB change PA pushes to GitHub. Other hosts pull to
get the latest user list.

### R2 — MASTER passphrase unlocks everything
One passphrase per host, stored in `~/.llcRentalTracker/config.json`.
It unlocks `keys.json.gpg` → which provides `LLC_GPG_PASSPHRASE` + `LLC_SECRET_KEY`.

### R3 — `keys.json.gpg` is the platform-portable secrets package
```json
{
  "LLC_GPG_PASSPHRASE": "<shared passphrase for pw.json.gpg>",
  "LLC_SECRET_KEY":     "<Flask session signing secret>"
}
```

`keys.json.gpg` **IS in the Business Repo**, encrypted with the MASTER passphrase.
Same content on all platforms — the MASTER passphrase is the only per-host secret.

### R4 — `wsCmd.py --setup` is the bootstrap tool on any platform
On a new host:
1. Clone both repos
2. Set MASTER passphrase in `~/.llcRentalTracker/config.json`
3. Run `wsCmd.py --setup` — decrypts `keys.json.gpg`, verifies/creates `pw.json.gpg`
4. Start app

### R5 — Startup injects secrets automatically
`wsgi.py` (and `wsCmd.py --start`) reads `config.json`, decrypts `keys.json.gpg`,
injects `LLC_GPG_PASSPHRASE` and `LLC_SECRET_KEY` into `os.environ` before the
Flask app initialises. No platform-specific environment variables needed beyond
what's already in `config.json`.

---

## Architecture

```
~/.llcRentalTracker/config.json     (host filesystem, never in repo)
  └── master_passphrase  ──────────────┐
                                       ▼
Business Repo (LLC-WBGroup)     gpg --decrypt
  books/Accts/
    keys.json.gpg  (IN REPO)  ──▶  { LLC_GPG_PASSPHRASE, LLC_SECRET_KEY }
    pw.json.gpg    (IN REPO)  ──▶  [users]  (decrypted with LLC_GPG_PASSPHRASE)
    *.json (data)  (IN REPO)


Push/pull flow:

  PA (master host)                   Local / other hosts
  ──────────────────                 ───────────────────
  owns pw.json.gpg        push ───▶  GitHub repo
  manages users                      ◀─── pull
  keys.json.gpg matches              keys.json.gpg matches
  same LLC_GPG_PASSPHRASE            same LLC_GPG_PASSPHRASE
  → can decrypt pw.json.gpg         → can decrypt pw.json.gpg
```

---

## Startup Sequence (revised)

```
wsgi.py / wsCmd.py --start
  │
  ├── 1. read ~/.llcRentalTracker/config.json
  │         → master_passphrase
  │
  ├── 2. gpg --decrypt books/Accts/keys.json.gpg  (using master_passphrase)
  │         → { LLC_GPG_PASSPHRASE, LLC_SECRET_KEY }
  │
  ├── 3. os.environ["LLC_GPG_PASSPHRASE"] = ...  (if not already set)
  │   os.environ["LLC_SECRET_KEY"]      = ...
  │
  └── 4. Flask app starts → llcLogin_auth reads LLC_GPG_PASSPHRASE → decrypts pw.json.gpg
```

---

## `~/.llcRentalTracker/config.json` — revised schema

```json
{
  "master_passphrase": "<MASTER_PP — never commit this file>",
  "default": ["WBGroupLLC", 2025],
  "llcList": [
    {
      "llcName":   "WBGroupLLC",
      "dataName":  "WBGroupLLC",
      "bus_repo":  "/path/to/LLC-WBGroup",
      "books_dir": "books",
      "year":      2025
    }
  ]
}
```

`setup_paths.py` already reads this file. Adding `master_passphrase` is a one-field
addition with no impact on existing config readers (they ignore unknown keys).

---

## `wsCmd.py --setup` Flow (revised)

```
1. Read ~/.llcRentalTracker/config.json → master_passphrase
   If absent → prompt: "Enter MASTER passphrase:" → write to config.json

2. Decrypt books/Accts/keys.json.gpg using master_passphrase
   If absent or decrypt fails:
     → prompt to create keys.json.gpg (generate LLC_GPG_PASSPHRASE + LLC_SECRET_KEY,
       encrypt with master_passphrase, write + commit to Business Repo from PA)

3. Extract LLC_GPG_PASSPHRASE and LLC_SECRET_KEY from decrypted keys

4. Write LLC_GPG_PASSPHRASE + LLC_SECRET_KEY into llcProfile MultiTaskWS_Config

5. Check books/Accts/pw.json.gpg:
   ABSENT → create with seed user, encrypted with LLC_GPG_PASSPHRASE
   PRESENT, decrypts OK → print "✓ User DB verified"
   PRESENT, decrypts BAD → warn; if --reset: delete + recreate with seed user

6. Done — start with:  python3 wsCmd.py --start --llcName WBGroupLLC
```

---

## PA Fix Plan (immediate — restores login today)

### Context
- PA has `books/2025/Accts/pw.json.gpg` — encrypted with PA's `LLC_GPG_PASSPHRASE`
- PA's `$LLC_GPG_PASSPHRASE` env var is set in PA environment tab
- `books/Accts/pw.json.gpg` is missing (was not copied in migration `680f1ac`)

### Step 1 — Verify the working file on PA
```bash
# PA console:
gpg --batch --decrypt \
    --passphrase "$LLC_GPG_PASSPHRASE" \
    ~/LLC-WBGroup/books/2025/Accts/pw.json.gpg
# Should print the JSON user array — confirms the file and passphrase are correct.
```

### Step 2 — Copy to new path
```bash
cp ~/LLC-WBGroup/books/2025/Accts/pw.json.gpg \
   ~/LLC-WBGroup/books/Accts/pw.json.gpg
```

### Step 3 — Commit from PA (master host pushes)
```bash
cd ~/LLC-WBGroup
git add books/Accts/pw.json.gpg
git commit -m "fix: add pw.json.gpg to books/Accts/ — master host copy"
git push
```

### Step 4 — Reload PA app → confirm login

### Step 5 — Seed `~/.llcRentalTracker/config.json` with master_passphrase on PA
```bash
# PA console — add master_passphrase to config.json:
python3 -c "
import json
from pathlib import Path
cfg_file = Path.home() / '.llcRentalTracker/config.json'
cfg = json.loads(cfg_file.read_text())
if 'master_passphrase' not in cfg:
    import getpass
    cfg['master_passphrase'] = getpass.getpass('MASTER passphrase: ')
    cfg_file.write_text(json.dumps(cfg, indent=2))
    print('Written.')
else:
    print('Already present.')
"
chmod 600 ~/.llcRentalTracker/config.json
```

---

## Remaining Work (after login is restored)

### Phase A — Create `keys.json.gpg` on PA
Generate and encrypt the keys file using PA's current secrets.
Commit from PA → all hosts can pull it.

```bash
# PA console:
python3 - << 'EOF'
import json, os, subprocess, tempfile
from pathlib import Path

accts = Path('~/LLC-WBGroup/books/Accts').expanduser()
keys  = {
    'LLC_GPG_PASSPHRASE': os.environ['LLC_GPG_PASSPHRASE'],
    'LLC_SECRET_KEY':     os.environ.get('LLC_SECRET_KEY', ''),
}
plaintext = json.dumps(keys, indent=2).encode()
master_pp = json.loads((Path.home()/'.llcRentalTracker/config.json').read_text())['master_passphrase']

# Encrypt
proc = subprocess.run(
    ['gpg','--batch','--yes','--symmetric','--cipher-algo','AES256',
     '--passphrase', master_pp, '--output', str(accts/'keys.json.gpg'), '-'],
    input=plaintext, capture_output=True
)
print('keys.json.gpg written' if proc.returncode == 0 else proc.stderr.decode())
EOF

cd ~/LLC-WBGroup
git add books/Accts/keys.json.gpg
git commit -m "feat: add keys.json.gpg — per-instance secrets bootstrap"
git push
```

### Phase B — Update `setup_paths.py`
Add `read_master_passphrase()` helper that returns `config.json["master_passphrase"]`.

### Phase C — Update `wsgi.py` startup
Add `_inject_from_keys()` call at module load time (before Flask init).

### Phase D — Update `wsCmd.py --setup`
Implement revised flow from the `--setup` section above.

### Phase E — Local setup
```bash
# Local: add master_passphrase to ~/.llcRentalTracker/config.json
# Then pull LLC-WBGroup (gets keys.json.gpg + pw.json.gpg from PA)
# wsCmd.py --setup will verify everything works
```

---

## File Ownership Summary

| File | In Repo? | Who writes it | Pushed from |
|---|---|---|---|
| `books/Accts/keys.json.gpg` | ✅ YES | `wsCmd.py --setup` (initial) | PA (master) |
| `books/Accts/pw.json.gpg` | ✅ YES | `llcLogin_auth` (user mgmt) | PA (master) |
| `books/Accts/*.json` (data) | ✅ YES | App save actions | PA (master) |
| `~/.llcRentalTracker/config.json` | ❌ NO | Operator / `wsCmd.py` | Never pushed |

---

## Setup-Maintenance Workflow

End-to-end lifecycle for the master BUS + llcRentalTracker instance and all downstream
hosts. All write operations (git push, user changes, secret generation) originate from
PA (master host). All other hosts are read-only with respect to the repo.

---

### Workflow 1 — Setup New (brand-new master instance)

Use when: fresh PA account, new LLC, or complete reinstall from scratch.

```
Prerequisites:
  • GitHub repos created: LLC-WBGroup, llcRentalTracker
  • PA account with console access
  • GPG installed on PA (gpg --version)
  • Python 3.10+, pip install -r requirements.txt done
```

**Step 1 — Clone both repos on PA**
```bash
cd ~
git clone https://github.com/wbgroupmgr/llcRentalTracker.git  pyTrackers/llcRentalTracker
git clone https://github.com/wbgroupmgr/LLC-WBGroup.git       LLC-WBGroup
```

**Step 2 — Register the LLC config**
```bash
cd ~/pyTrackers/llcRentalTracker
python3 wsCmd.py --newBus ~/LLC-WBGroup --year 2025
# Creates ~/.llcRentalTracker/config.json with llcList entry
```

**Step 3 — Add MASTER passphrase to config**
```bash
python3 - << 'EOF'
import json, getpass
from pathlib import Path
f   = Path.home() / '.llcRentalTracker/config.json'
cfg = json.loads(f.read_text())
cfg['master_passphrase'] = getpass.getpass('Choose MASTER passphrase: ')
f.write_text(json.dumps(cfg, indent=2))
EOF
chmod 600 ~/.llcRentalTracker/config.json
```

**Step 4 — Generate `keys.json.gpg` (first time only)**

Generates new `LLC_GPG_PASSPHRASE` and `LLC_SECRET_KEY`, encrypts with MASTER passphrase.
```bash
python3 - << 'EOF'
import json, os, secrets, subprocess
from pathlib import Path

cfg   = json.loads((Path.home()/'.llcRentalTracker/config.json').read_text())
mpp   = cfg['master_passphrase']
keys  = {
    'LLC_GPG_PASSPHRASE': secrets.token_hex(20),
    'LLC_SECRET_KEY':     secrets.token_hex(32),
}
out   = Path('~/LLC-WBGroup/books/Accts/keys.json.gpg').expanduser()
plain = json.dumps(keys, indent=2).encode()
subprocess.run(
    ['gpg','--batch','--yes','--symmetric','--cipher-algo','AES256',
     '--passphrase', mpp, '--output', str(out), '-'],
    input=plain, check=True
)
print('keys.json.gpg created. LLC_GPG_PASSPHRASE:', keys['LLC_GPG_PASSPHRASE'])
EOF
```

**Step 5 — Run `--setup` to create the seed user DB**
```bash
python3 wsCmd.py --setup --llcName WBGroupLLC
# Decrypts keys.json.gpg → creates books/Accts/pw.json.gpg with seed user llcgroupmgr
```

**Step 6 — Push both files from PA (master host)**
```bash
cd ~/LLC-WBGroup
git add books/Accts/keys.json.gpg books/Accts/pw.json.gpg
git commit -m "feat: initial keys.json.gpg and pw.json.gpg for master instance"
git push
```

**Step 7 — Configure and start the app**
```bash
cd ~/pyTrackers/llcRentalTracker
# wsgi.py mounts the app; PA web tab sets the WSGI file path
# Reload the app from PA web tab
```

**Step 8 — Login and change seed password**
```
URL: https://<pa-host>/rentalTracker/login
Username: llcgroupmgr
Password: llcmanager   ← CHANGE THIS IMMEDIATELY
```

---

### Workflow 2 — Manage Users & Passwords

All user management happens on PA (master host) through the app UI.
After any change the updated `pw.json.gpg` must be pushed to GitHub.

**Add a new user**
```
PA app → Register page → fill form → submit
→ pw.json.gpg re-encrypted automatically by llcLogin_auth
```

**Delete a user**
```
PA app → Manage Users → delete
→ pw.json.gpg re-encrypted automatically
```

**Reset a user's password**
```
PA app → Manage Users → reset password
→ pw.json.gpg re-encrypted automatically
```

**After any user change — push to GitHub from PA**
```bash
cd ~/LLC-WBGroup
git add books/Accts/pw.json.gpg
git commit -m "auth: update user DB"
git push
```

**Other hosts pick up the change**
```bash
# On local / any pull-only host:
cd ~/LLC-WBGroup && git pull
# pw.json.gpg updated — login works with new/changed credentials
# No app restart needed (llcLogin_auth decrypts on every request)
```

---

### Workflow 3 — Sync Login Auth with Bus GitHub

This workflow covers keeping login state consistent across hosts after PA changes.

**Normal sync (after user changes on PA)**
```
PA: user change made in app
   → pw.json.gpg updated on PA filesystem
   → git add + commit + push (PA console, see Workflow 2)
   → GitHub repo updated

Local/other: git pull
   → gets latest pw.json.gpg from PA
   → immediately usable (same LLC_GPG_PASSPHRASE from keys.json.gpg)
```

**What NEVER needs syncing**
```
LLC_GPG_PASSPHRASE  — lives in keys.json.gpg (already in repo)
LLC_SECRET_KEY      — lives in keys.json.gpg (already in repo)
master_passphrase   — lives in ~/.llcRentalTracker/config.json (never in repo,
                       must be set manually on each host during initial setup)
```

**Keys rotation (rare — e.g., security incident)**
```
1. On PA: generate new keys.json.gpg (new LLC_GPG_PASSPHRASE + LLC_SECRET_KEY)
2. Re-encrypt pw.json.gpg with new LLC_GPG_PASSPHRASE
3. git add keys.json.gpg pw.json.gpg && git commit && git push
4. All hosts: git pull + app restart
5. Each host: wsCmd.py --setup to re-inject new secrets into local profile
```

---

### Workflow 4 — Dev Work (code changes)

**Rule: Dev work NEVER touches `pw.json.gpg` or `keys.json.gpg`.**

These files live in `LLC-WBGroup` (Business Repo). Dev work lives in `llcRentalTracker`
(App Code Repo). The repos are separate by design.

**What each repo holds**

| `llcRentalTracker` (code) | `LLC-WBGroup` (data) |
|---|---|
| Python, HTML, CSS, Markdown | `*.json` accounting data |
| NO `.gpg` files, NO data | `keys.json.gpg` ← pushed by PA only |
| Dev: branch, commit, push anytime | `pw.json.gpg`  ← pushed by PA only |

**Local dev session — safe pattern**
```bash
# 1. Pull latest code
cd ~/pyTrackers/llcRentalTracker && git pull

# 2. Pull latest data (gets PA's pw.json.gpg — never modify it locally)
cd ~/LLC-WBGroup && git pull

# 3. Verify local login works (optional sanity check)
gpg --batch --decrypt \
    --passphrase "$(python3 -c "import json; from pathlib import Path; \
      print(json.loads((Path.home()/'.llcRentalTracker/config.json').read_text())['master_passphrase'])")" \
    ~/LLC-WBGroup/books/Accts/keys.json.gpg

# 4. Make code changes in llcRentalTracker — safe to commit/push anytime
# 5. NEVER: git add *.gpg   NEVER: modify books/Accts/pw.json.gpg
```

**If dev accidentally modifies `pw.json.gpg` or `keys.json.gpg`**
```bash
# Reset to last GitHub version immediately:
cd ~/LLC-WBGroup
git checkout -- books/Accts/pw.json.gpg
git checkout -- books/Accts/keys.json.gpg
# These files should never be locally modified
```

---

### Workflow 5 — Recover Keys & Passwords

**Scenario A — Forgot a user's password (normal user)**
```
Option 1 (preferred): Any llcManager logs in → Manage Users → reset password
Option 2: llcgroupmgr logs in → Manage Users → reset password
```

**Scenario B — Forgot llcgroupmgr password (only admin locked out)**
```bash
# On PA console — decrypt pw.json.gpg, edit the hash, re-encrypt:
python3 - << 'EOF'
import json, hashlib, subprocess, os
from pathlib import Path

cfg   = json.loads((Path.home()/'.llcRentalTracker/config.json').read_text())
mpp   = cfg['master_passphrase']
keys  = json.loads(subprocess.run(
    ['gpg','--batch','--decrypt','--passphrase', mpp,
     str(Path('~/LLC-WBGroup/books/Accts/keys.json.gpg').expanduser())],
    capture_output=True, check=True).stdout)
gpg_pp = keys['LLC_GPG_PASSPHRASE']

pw_file = Path('~/LLC-WBGroup/books/Accts/pw.json.gpg').expanduser()
users   = json.loads(subprocess.run(
    ['gpg','--batch','--decrypt','--passphrase', gpg_pp, str(pw_file)],
    capture_output=True, check=True).stdout)

new_password = input('New password for llcgroupmgr: ')
for u in users:
    if u['username'] == 'llcgroupmgr':
        u['password'] = hashlib.sha256(new_password.encode()).hexdigest()
        print('Updated.')

plaintext = json.dumps(users, indent=2).encode()
subprocess.run(
    ['gpg','--batch','--yes','--symmetric','--cipher-algo','AES256',
     '--passphrase', gpg_pp, '--output', str(pw_file), '-'],
    input=plaintext, check=True)

# Push updated pw.json.gpg
subprocess.run(['git','-C', str(pw_file.parent.parent.parent),
                'add', str(pw_file)], check=True)
subprocess.run(['git','-C', str(pw_file.parent.parent.parent),
                'commit', '-m', 'auth: reset llcgroupmgr password'], check=True)
subprocess.run(['git','-C', str(pw_file.parent.parent.parent),
                'push'], check=True)
print('Done — login with new password.')
EOF
```

**Scenario C — Forgot `LLC_GPG_PASSPHRASE` (but have MASTER passphrase)**
```bash
# Decrypt keys.json.gpg to read it
gpg --batch --decrypt \
    --passphrase "<MASTER_PP>" \
    ~/LLC-WBGroup/books/Accts/keys.json.gpg
# Prints LLC_GPG_PASSPHRASE and LLC_SECRET_KEY in plain JSON
```

**Scenario D — Forgot MASTER passphrase**
```
Option 1: Read it from ~/.llcRentalTracker/config.json
    python3 -c "import json; from pathlib import Path; \
      print(json.loads((Path.home()/'.llcRentalTracker/config.json').read_text())['master_passphrase'])"

Option 2 (config.json lost): keys.json.gpg is unrecoverable.
    → Run full Workflow 1 (Setup New) with a new MASTER passphrase
    → Generate new keys.json.gpg and pw.json.gpg
    → Users must be re-registered
```

**Scenario E — `pw.json.gpg` corrupted or accidentally modified locally**
```bash
# Restore PA's authoritative version:
cd ~/LLC-WBGroup
git checkout -- books/Accts/pw.json.gpg
# OR pull from GitHub if local already committed:
git pull
```

**Scenario F — Need to move to a new PA account or host**
```
1. Clone both repos onto new host
2. Copy ~/.llcRentalTracker/config.json from old host (contains master_passphrase)
   OR re-add master_passphrase manually (Workflow 1, Step 3)
3. python3 wsCmd.py --setup --llcName WBGroupLLC
   → decrypts keys.json.gpg → verifies pw.json.gpg → ready
4. Start app
   (No key regeneration needed — same keys.json.gpg from repo)
```

---

## Original Design (unchanged sections)

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
# Decrypt to stdout
gpg --batch --decrypt --passphrase "$LLC_GPG_PASSPHRASE" books/Accts/pw.json.gpg

# Decrypt keys.json.gpg (uses MASTER passphrase)
gpg --batch --decrypt --passphrase "<MASTER_PP>" books/Accts/keys.json.gpg

# Re-encrypt pw.json.gpg with new passphrase
gpg --batch --decrypt --passphrase "$OLD_PP" books/Accts/pw.json.gpg \
  | gpg --batch --symmetric --cipher-algo AES256 \
        --passphrase "$NEW_PP" --output books/Accts/pw.json.gpg
```

### Auth Flow (unchanged)
```
POST /login
  → _load_users() → gpg --decrypt pw.json.gpg (using LLC_GPG_PASSPHRASE from env)
  → json.loads() → find user → hash(password) compare
  → session written → 302 home
```
