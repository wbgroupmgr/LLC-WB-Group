# Login & Registration Design — LLC Accounting App

Authentication and user-registration layer for the LLC Management App (`llcMgmt`).  
Covers file layout, template design, module API, GPG encryption, integration steps,  
user DB schema, session configuration, and security notes.

---

## Project Layout

```
top/
├── accts/
│   └── pw.json.gpg    # GPG-encrypted user DB
├── ledger/                            # accounting data services
└── ui/
    ├── llcMgmt.py                     # Flask app class
    ├── llcLogin_auth.py               # auth + registration module
    └── templates/
        ├── login.html                 # sign-in page
        └── register.html             # new-member registration page
```

> The user DB is always `accts/pw.json.gpg` — a single fixed filename shared across the LLC app.

---

## Files at a Glance

| File | Role |
|---|---|
| `ui/llcLogin_auth.py` | Route factory (`/login`, `/logout`, `/register`) and `@login_required` decorator |
| `ui/templates/login.html` | Member sign-in page |
| `ui/templates/register.html` | New-member registration form |
| `accts/pw.json.gpg` | GPG-encrypted user DB (JSON array inside); auto-located by module |

---

## GPG Encryption

### Overview

The user database is stored exclusively as a **GnuPG symmetrically-encrypted binary file** (`.json.gpg`). The plaintext JSON is **never written to disk** — decryption and re-encryption happen entirely in memory using subprocess calls to the host's `gpg` binary.

| Property | Value |
|---|---|
| Encryption type | Symmetric (passphrase-based, no key-pair required) |
| Cipher algorithm | AES-256 |
| GPG tool | GnuPG 2.x (`gpg` must be on `PATH`) |
| Python library | `python-gnupg` (`pip install python-gnupg`) |
| Passphrase source | Environment variable `LLC_GPG_PASSPHRASE` |
| Write strategy | Atomic: encrypt → `.tmp` → rename over `.gpg` |

### Passphrase management

The passphrase is read at runtime from the environment. It is **never hard-coded** in source:

```bash
# development (.env file or shell)
export LLC_GPG_PASSPHRASE="your-strong-passphrase"

# production (systemd service file)
[Service]
Environment="LLC_GPG_PASSPHRASE=your-strong-passphrase"
```

If the variable is not set, `llcLogin_auth` raises a `RuntimeError` immediately on any DB access attempt, and the login/register routes flash a user-facing "service unavailable" message while logging the error server-side.

### Encryption / decryption flow

```
LOAD (read)
──────────────────────────────────────────────────────────
  disk: pw.json.gpg  (binary ciphertext)
     │
     │  gpg --decrypt --passphrase $LLC_GPG_PASSPHRASE
     ▼
  memory: plaintext JSON bytes
     │
     │  json.loads()
     ▼
  Python list[dict]   ← used by login / register logic


SAVE (write)
──────────────────────────────────────────────────────────
  Python list[dict]
     │
     │  json.dumps()
     ▼
  memory: plaintext JSON bytes
     │
     │  gpg --symmetric --cipher-algo AES256 --passphrase $LLC_GPG_PASSPHRASE
     ▼
  disk: pw.json.gpg.tmp  (new ciphertext)
     │
     │  atomic rename (.tmp → .gpg)
     ▼
  disk: pw.json.gpg  (updated)
```

### CLI reference

```bash
# Decrypt to stdout (inspect)
gpg --batch --decrypt \
    --passphrase "$LLC_GPG_PASSPHRASE" \
    accts/pw.json.gpg

# Encrypt an existing plaintext file
gpg --batch --symmetric --cipher-algo AES256 \
    --passphrase "$LLC_GPG_PASSPHRASE" \
    --output accts/pw.json.gpg \
    /tmp/users.json

# Change passphrase (decrypt → re-encrypt)
gpg --batch --decrypt --passphrase "$OLD_PP" accts/pw.json.gpg \
  | gpg --batch --symmetric --cipher-algo AES256 \
        --passphrase "$NEW_PP" \
        --output accts/pw.json.gpg
```

---

## User DB — `accts/pw.json.gpg`

### Schema — one JSON object per user (inside the encrypted file)

```json
{
  "username":   "jsmith",
  "password":   "<sha-256 hex digest of password>",
  "full_name":  "Jane Smith",
  "phone":      "512-555-0100",
  "role":       "bookkeeper",
  "created_at": "2026-05-09T14:32:00"
}
```

The decrypted file is a JSON **array** of these objects:

```json
[
  { "username": "llcgroupmgr", ... },
  { "username": "jsmith",      ... }
]
```

### Seed / template file

A pre-encrypted starter file is provided as `pw.json.gpg`.  
It was encrypted with the passphrase `LLC_GPG_PASSPHRASE` (the literal string — change this before use).

Copy and rename it for your LLC, then re-encrypt with your real passphrase:

```bash
# 1. Decrypt the template
gpg --batch --decrypt \
    --passphrase "LLC_GPG_PASSPHRASE" \
    accts/pw.json.gpg > /tmp/users.json

# 2. Edit /tmp/users.json if needed, then re-encrypt with your passphrase
gpg --batch --symmetric --cipher-algo AES256 \
    --passphrase "$LLC_GPG_PASSPHRASE" \
    --output accts/pw.json.gpg \
    /tmp/users.json

# 3. Shred the plaintext temp file
shred -u /tmp/users.json
```

The seed user inside the template:

| Field | Value |
|---|---|
| `username` | `llcgroupmgr` |
| `password` | `llcmanager` (stored as SHA-256 hash) |
| `role` | `llcManager` |
| `full_name` | `LLC Group Manager` |

**Change this password immediately after first login.**

### Password hashing

User passwords are stored as SHA-256 hex digests. The raw password never reaches disk:

```python
import hashlib
hashlib.sha256("llcmanager".encode("utf-8")).hexdigest()
# → b378de804f74ce03bfc32cf368f1982a576ae7e6665011fa6176d7cd563ebef5
```

### DB helper functions

| Function | Description |
|---|---|
| `_db_path(llc_name)` | Returns `top/accts/pw.json.gpg`; creates `accts/` if absent |
| `_load_users(llc_name)` | Decrypts in-memory → parses JSON → returns `list[dict]`; returns `[]` if file absent |
| `_save_users(llc_name, users)` | Serialises → encrypts → atomic rename; plaintext never touches disk |
| `_find_user(users, username)` | Case-insensitive username lookup |
| `_get_passphrase()` | Reads `LLC_GPG_PASSPHRASE`; raises `RuntimeError` if unset |
| `_gpg_decrypt(path, passphrase)` | Calls `gpg --decrypt` via subprocess; returns plaintext bytes |
| `_gpg_encrypt(plaintext, out_path, passphrase)` | Calls `gpg --symmetric AES256` via subprocess; writes via `.tmp` |

---

## Allowed Roles

| Role key | Description |
|---|---|
| `member` | Standard LLC member — read access |
| `llcManager` | LLC manager — full operational access |
| `bookkeeper` | Handles day-to-day transaction entry |
| `accountant` | Reviews financial statements and tax forms |

Defined in `llcLogin_auth.ALLOWED_ROLES`. Role-based access control within protected routes is not enforced by this module — add view-level checks using `session["role"]` as needed.

---

## Template Design

Both templates share a unified visual language — no external fonts, no CDN calls, no JavaScript frameworks.

### Shared design characteristics

- **Letterhead header** — LLC monogram badge, app title (`app_title`), monospaced subtitle
- **Typography** — serif body (`Georgia`) + monospaced labels/inputs (`Courier New`)
- **Color** — monochrome palette; automatic light/dark mode via `prefers-color-scheme`
- **Inputs** — 42px height, monospaced uppercase labels, blue focus ring
- **Flash messages** — color-coded: `error` (red), `success` (green), `info` (blue)
- **Footer** — contextual link left, UI version string right

### `login.html` fields

| Element | Detail |
|---|---|
| Username | Text input; re-populated on failed submit |
| Password | Password input with show/hide toggle |
| Remember me | Checkbox — sets 30-day persistent session |
| `?next=` | Hidden field — carries intended destination through login |
| Footer link | "New member? Request access" → `/register` |

### `register.html` fields

**Section 1 — Personal Information**

| Field | Type | Required |
|---|---|---|
| Full Name | `text` | yes |
| Phone Number | `tel` | yes |
| Role | `select` | yes |

**Section 2 — Account Credentials**

| Field | Type | Required | Constraint |
|---|---|---|---|
| Username | `text` | yes | min 3 characters, unique |
| Password | `password` | yes | min 6 characters |
| Confirm Password | `password` | yes | must match Password |

Inline field-level errors appear beneath each invalid field on POST. Footer: "Already registered? Sign in" → `/login`.

---

## Module API — `llcLogin_auth.py`

### `login_required(view_func)` — decorator

Redirects unauthenticated requests to `/login`, preserving `?next=`.

```python
@app.route("/")
@login_required        # ← must be immediately below @app.route
def home():
    ...
```

### `make_auth_routes(app, llc_name="LLC")` — route factory

| Parameter | Type | Default | Description |
|---|---|---|---|
| `app` | `Flask` | — | Flask instance from `llcMgmt.__init__` |
| `llc_name` | `str` | `"LLC"` | Drives the `.json.gpg` filename |

Registers `/login`, `/logout`, `/register` and appends `ui/templates/` to the Jinja2 loader chain.

### Session keys written on login

| Key | Type | Value |
|---|---|---|
| `session["logged_in"]` | `bool` | `True` |
| `session["username"]` | `str` | authenticated username |
| `session["full_name"]` | `str` | user's full name from DB |
| `session["role"]` | `str` | user's role from DB |

---

## Integration — Step by Step

### Step 1 — Install the GPG Python library

```bash
pip install python-gnupg
```

GnuPG 2.x must also be installed on the host (`apt install gnupg` / `brew install gnupg`).

### Step 2 — Set the passphrase environment variable

```bash
export LLC_GPG_PASSPHRASE="your-strong-passphrase"
```

### Step 3 — Prepare the user DB file

```bash
# Decrypt the provided template, re-encrypt with your passphrase, rename
gpg --batch --decrypt --passphrase "LLC_GPG_PASSPHRASE" \
    top/accts/pw.json.gpg > /tmp/users.json

gpg --batch --symmetric --cipher-algo AES256 \
    --passphrase "$LLC_GPG_PASSPHRASE" \
    --output top/accts/pw.json.gpg \
    /tmp/users.json

shred -u /tmp/users.json
```

### Step 4 — Add imports to `llcMgmt.py`

```python
from flask import redirect, session, url_for, flash
from functools import wraps
from llcLogin_auth import make_auth_routes, login_required
```

### Step 5 — Set a Flask secret key

```python
import os, secrets
self.app.secret_key = os.environ.get(
    "LLC_SECRET_KEY", secrets.token_hex(32)
)
```

### Step 6 — Register auth routes

```python
self.app._llc_version = self.version
llc_name = getattr(getattr(self.eSession, "llc", None), "objName", "LLC")
make_auth_routes(self.app, llc_name=llc_name)
```

### Step 7 — Protect routes

```python
@app.route("/")
@login_required
def home(): ...

@app.route("/view/<view_name>")
@login_required
def view(view_name): ...
```

### Step 8 — Add sign-out and user info to nav

```html
{{ session.get('full_name') }} ({{ session.get('role') }})
<a href="{{ url_for('logout') }}">Sign out</a>
```

---

## Session Configuration

| Behaviour | Default | Override |
|---|---|---|
| No "remember me" | Browser session | — |
| "Remember me" checked | 30 days | `PERMANENT_SESSION_LIFETIME` |

```python
from datetime import timedelta
self.app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
make_auth_routes(self.app, llc_name=llc_name)
```

---

## Auth & Registration Flow

```
Browser                             Flask / llcLogin_auth
  │                                   │
  │── GET /  ────────────────────────▶ @login_required fires
  │                                   │   session["logged_in"] absent
  │◀── 302 /login?next=/ ─────────────│
  │                                   │
  │── GET /login ─────────────────── ▶ render login.html
  │◀── 200 ──────────────────────────│
  │                                   │
  │── POST /login ────────────────── ▶ _load_users() → GPG decrypt → JSON parse
  │   username, password,             │   _find_user() + _hash() compare
  │   remember, next=/                │   ✗ no match → flash error, re-render
  │                                   │   ✓ match   → session written
  │◀── 302 / ────────────────────────│
  │                                   │
  │── GET / ──────────────────────── ▶ @login_required passes → home
  │◀── 200 home ─────────────────────│
  │                                   │
  │── GET /logout ────────────────── ▶ session.clear()
  │◀── 302 /login ────────────────── │
  │                                   │
  │── GET /register ──────────────── ▶ render register.html
  │◀── 200 ──────────────────────────│
  │                                   │
  │── POST /register ─────────────── ▶ validate six fields
  │   full_name, phone, role,         │   ✗ errors → re-render with messages
  │   username, password, password2   │   ✓ clean  → _load_users() decrypt
  │                                   │             _find_user() duplicate check
  │                                   │             append new_user record
  │                                   │             _save_users() → JSON → GPG encrypt → disk
  │                                   │             flash "Account created"
  │◀── 302 /login ────────────────── │
```

---

## Security Notes

- **Encrypted at rest** — the user DB is stored exclusively as AES-256 GPG ciphertext. There is no plaintext copy on disk at any time.
- **In-memory only** — decrypted JSON bytes are held in process memory for the duration of a single request and then released; they are never written to any file, log, or temp directory.
- **No plaintext passwords** — user passwords are SHA-256 hashed before being serialised. The raw value exists in memory only for the duration of the request.
- **Passphrase in environment** — `LLC_GPG_PASSPHRASE` is never committed to source control. Rotate it by decrypting with the old passphrase and re-encrypting with the new one (see CLI reference above).
- **Open-redirect guard** — the `?next=` value on login is validated: must start with `/` and not `//`.
- **Session fixation prevention** — `session.clear()` is called before writing new session data on every successful login.
- **Atomic DB writes** — `_save_users()` writes to `.tmp` then renames over `.gpg`, preventing a corrupt DB if the process is interrupted mid-write.
- **Case-insensitive usernames** — `_find_user()` lowercases both the stored and submitted username before comparing, preventing duplicate accounts differing only in case.
- **GPG error surfacing** — if the GPG binary is missing or the passphrase is wrong, `_load_users` / `_save_users` raise `RuntimeError`. The route handlers catch these, log them server-side via `app.logger.error`, and show a generic "service unavailable" flash to the browser — no internal error details are exposed to users.
- **Production hardening** — when serving over a network:

```python
app.config["SESSION_COOKIE_SECURE"]   = True    # HTTPS only
app.config["SESSION_COOKIE_HTTPONLY"] = True    # no JS access to the cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # CSRF mitigation
```