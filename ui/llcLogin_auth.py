"""
llcLogin_auth.py
================
Authentication and user-registration layer for llcMgmt.

Responsibilities
────────────────
  • /login      — authenticate against the GPG-encrypted JSON user DB
  • /logout     — clear session, redirect to /login
  • /register   — new-user self-registration (Full Name, Phone, Role,
                  Username, Password); written back to the encrypted DB
  • login_required decorator — protects any route

Project layout
──────────────
    top/
    ├── accts/
    │   └── pw.json.gpg   ← GPG-encrypted user DB
    ├── ledger/
    └── ui/
        ├── llcMgmt.py
        ├── llcLogin_auth.py              ← this file
        └── templates/
            ├── login.html
            └── register.html

GPG encryption
──────────────
  Algorithm : AES-256 symmetric (no key-pair required)
  Passphrase: supplied via environment variable LLC_GPG_PASSPHRASE
  Library   : python-gnupg  (pip install python-gnupg)
  CLI tool  : gpg (GnuPG 2.x must be installed on the host)

  The plaintext DB file (pw.json.gpg) is NEVER written to
  disk. Decryption happens in-memory; re-encryption is written atomically
  via a .tmp file that is then renamed over the .gpg file.

User DB schema (one JSON object per user)
──────────────────────────────────────────
    {
      "username":   "jsmith",
      "password":   "<sha256 hex digest>",
      "full_name":  "Jane Smith",
      "phone":      "512-555-0100",
      "role":       "bookkeeper",
      "created_at": "2026-05-09T14:32:00"
    }

  Allowed roles: member | llcManager | bookkeeper | accountant

HOW TO INTEGRATE
────────────────

Step 1 — Install dependency
    pip install python-gnupg

Step 2 — Set the GPG passphrase environment variable
    export LLC_GPG_PASSPHRASE="your-strong-passphrase"
    # Add to your .env or systemd service file — never hard-code it.

Step 3 — Copy & rename the seed DB
    cp top/accts/llcUsers_llcName.json.gpg \
       top/accts/llcUsers_WBGroupLLC.json.gpg

Step 4 — Add imports to llcMgmt.py
    from flask import redirect, session, url_for, flash
    from functools import wraps
    from llcLogin_auth import make_auth_routes, login_required

Step 5 — Set a Flask secret key
    Inside llcMgmt.__init__, immediately after self.app = Flask(...):

        import os, secrets
        self.app.secret_key = os.environ.get(
            "LLC_SECRET_KEY", secrets.token_hex(32)
        )

Step 6 — Derive the LLC name and register auth routes
    Still in llcMgmt.__init__, before self._bind_routes():

        self.app._llc_version = self.version

        llc_name = getattr(getattr(self.eSession, "llc", None), "objName", "LLC")
        make_auth_routes(self.app, llc_name=llc_name)

Step 7 — Protect routes with @login_required
    In llcMgmt._bind_routes(), stack @login_required beneath every
    @app.route() that requires authentication:

        @app.route("/")
        @login_required
        def home():
            ...

    /login, /logout, and /register are public — do NOT decorate them.

Step 8 — Add sign-out link to your nav template
        <a href="{{ url_for('logout') }}">Sign out</a>

SESSION LIFETIME
────────────────
Default  : browser-session cookie (expires when browser closes)
Remember : 30 days persistent (override with PERMANENT_SESSION_LIFETIME)

    from datetime import timedelta
    self.app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
    make_auth_routes(self.app, llc_name=llc_name)
"""

import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Callable, List, Optional

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ledger import setup_paths as _sp

# ── Constants ─────────────────────────────────────────────────────────────────

ALLOWED_ROLES: List[str] = ["member", "llcManager", "bookkeeper", "accountant"]

_HERE  = Path(__file__).resolve().parent   # ui/
_TMPL  = _HERE / "templates"               # ui/templates/

# Environment variable that holds the GPG symmetric passphrase.
_GPG_PASSPHRASE_ENV = "LLC_GPG_PASSPHRASE"


# ── Password hashing ──────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    """SHA-256 hex digest of *password*."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ── GPG helpers ───────────────────────────────────────────────────────────────

def _get_passphrase() -> str:
    """
    Read the GPG passphrase from the environment.
    Raises RuntimeError if the variable is not set.
    """
    pp = os.environ.get(_GPG_PASSPHRASE_ENV, "")
    if not pp:
        raise RuntimeError(
            f"Environment variable {_GPG_PASSPHRASE_ENV} is not set. "
            "Set it before starting the server."
        )
    return pp


def _gpg_decrypt(path: Path, passphrase: str) -> bytes:
    """
    Decrypt *path* in-memory. Passphrase is passed via a pipe (fd 3) so it
    never appears in process arguments.
    """
    r_fd, w_fd = os.pipe()
    try:
        os.write(w_fd, (passphrase + "\n").encode())
        os.close(w_fd);  w_fd = -1
        result = subprocess.run(
            ["gpg", "--batch", "--yes", "--quiet",
             "--passphrase-fd", str(r_fd),
             "--decrypt", str(path)],
            capture_output=True,
            pass_fds=(r_fd,),
        )
    finally:
        if w_fd != -1:
            os.close(w_fd)
        os.close(r_fd)
    if result.returncode != 0:
        raise RuntimeError(
            f"GPG decryption failed for {path.name}: "
            + result.stderr.decode(errors="replace").strip()
        )
    return result.stdout


def _gpg_encrypt(plaintext: bytes, out_path: Path, passphrase: str) -> None:
    """
    Encrypt *plaintext* bytes with AES-256 symmetric GPG and write the result
    atomically to *out_path* (via a .tmp sibling file).  Passphrase is passed
    via a pipe (fd 3) — plaintext is only ever in memory or the .gpg file.
    """
    tmp_path = out_path.with_suffix(".tmp")
    r_fd, w_fd = os.pipe()
    try:
        os.write(w_fd, (passphrase + "\n").encode())
        os.close(w_fd);  w_fd = -1
        result = subprocess.run(
            ["gpg", "--batch", "--yes", "--quiet",
             "--symmetric", "--cipher-algo", "AES256",
             "--passphrase-fd", str(r_fd),
             "--output", str(tmp_path)],
            input=plaintext,
            capture_output=True,
            pass_fds=(r_fd,),
        )
    finally:
        if w_fd != -1:
            os.close(w_fd)
        os.close(r_fd)
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"GPG encryption failed for {out_path.name}: "
            + result.stderr.decode(errors="replace").strip()
        )
    tmp_path.replace(out_path)   # atomic rename


# ── User DB helpers ───────────────────────────────────────────────────────────

def _db_path(llc_name: str) -> Path:
    """Return Accts/pw.json.gpg, creating the directory if needed."""
    accts = _sp.ACCTS_DIR
    accts.mkdir(parents=True, exist_ok=True)
    return accts / "pw.json.gpg"


def _load_users(llc_name: str) -> List[dict]:
    """
    Decrypt and parse the user DB.
    Returns [] if the file is absent; raises RuntimeError on GPG/JSON errors.
    """
    path = _db_path(llc_name)
    if not path.exists():
        return []

    passphrase = _get_passphrase()
    plaintext  = _gpg_decrypt(path, passphrase)

    try:
        data = json.loads(plaintext.decode("utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"User DB parse error ({path.name}): {exc}") from exc


def _save_users(llc_name: str, users: List[dict]) -> None:
    """
    Serialise *users* to JSON, encrypt with GPG, and write atomically.
    The plaintext JSON exists only in memory — never on disk.
    """
    path       = _db_path(llc_name)
    passphrase = _get_passphrase()
    plaintext  = json.dumps(users, indent=2, ensure_ascii=False).encode("utf-8")
    _gpg_encrypt(plaintext, path, passphrase)


def _find_user(users: List[dict], username: str) -> Optional[dict]:
    """Case-insensitive lookup by username."""
    uname = username.strip().lower()
    for u in users:
        if u.get("username", "").lower() == uname:
            return u
    return None


# ── Decorator ─────────────────────────────────────────────────────────────────

def login_required(view_func: Callable) -> Callable:
    """
    Redirect unauthenticated requests to /login, preserving the intended URL
    in ?next= so the user lands on the correct page after signing in.

    Usage (order matters — @login_required immediately under @app.route):

        @app.route("/")
        @login_required
        def home():
            ...
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


# ── Route factory ─────────────────────────────────────────────────────────────

def make_auth_routes(app: Flask, llc_name: str = "LLC") -> None:
    """
    Register /login, /logout, and /register on *app*.

    Parameters
    ----------
    app      : Flask instance from llcMgmt.__init__
    llc_name : drives the DB filename
               (e.g. "WBGroupLLC" → top/accts/llcUsers_WBGroupLLC.json.gpg)
    """
    # ── Jinja2 template path ──────────────────────────────────────────────────
    from jinja2 import ChoiceLoader, FileSystemLoader
    existing = app.jinja_loader
    extra    = FileSystemLoader(str(_TMPL))
    app.jinja_loader = (
        ChoiceLoader([existing, extra]) if existing else extra
    )

    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=30))

    # ── /login ────────────────────────────────────────────────────────────────
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("logged_in"):
            return redirect(url_for("home"))

        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password =  request.form.get("password") or ""
            remember = bool(request.form.get("remember"))

            try:
                users = _load_users(llc_name)
            except RuntimeError as exc:
                app.logger.error("Login DB error: %s", exc)
                flash("Authentication service unavailable. Contact your administrator.", "error")
                return render_template("login.html", version=getattr(app, "_llc_version", None))

            user = _find_user(users, username)

            if user and user.get("password") == _hash(password):
                session.clear()
                session["logged_in"] = True
                session["username"]  = user["username"]
                session["full_name"] = user.get("full_name", username)
                session["role"]      = user.get("role", "member")
                if remember:
                    session.permanent = True

                next_url = (
                    request.form.get("next")
                    or request.args.get("next")
                    or ""
                )
                if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("home"))

            flash("Invalid username or password.", "error")

        return render_template(
            "login.html",
            version=getattr(app, "_llc_version", None),
        )

    # ── /logout ───────────────────────────────────────────────────────────────
    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "info")
        return redirect(url_for("login"))

    # ── /register ─────────────────────────────────────────────────────────────
    @app.route("/register", methods=["GET", "POST"])
    def register():
        if session.get("logged_in"):
            return redirect(url_for("home"))

        errors: dict = {}
        form:   dict = {}

        if request.method == "POST":
            form = {
                "full_name": (request.form.get("full_name")  or "").strip(),
                "phone":     (request.form.get("phone")      or "").strip(),
                "role":      (request.form.get("role")       or "").strip(),
                "username":  (request.form.get("username")   or "").strip(),
                "password":  (request.form.get("password")   or ""),
                "password2": (request.form.get("password2")  or ""),
            }

            # ── Validation ────────────────────────────────────────────────────
            if not form["full_name"]:
                errors["full_name"] = "Full name is required."

            if not form["phone"]:
                errors["phone"] = "Phone number is required."

            if form["role"] not in ALLOWED_ROLES:
                errors["role"] = "Choose a valid role."

            if not form["username"] or len(form["username"]) < 3:
                errors["username"] = "Username must be at least 3 characters."

            if not form["password"] or len(form["password"]) < 6:
                errors["password"] = "Password must be at least 6 characters."
            elif form["password"] != form["password2"]:
                errors["password2"] = "Passwords do not match."

            # ── Duplicate-username check (requires DB access) ─────────────────
            if not errors:
                try:
                    users = _load_users(llc_name)
                except RuntimeError as exc:
                    app.logger.error("Register DB read error: %s", exc)
                    flash("Registration service unavailable. Contact your administrator.", "error")
                    return render_template(
                        "register.html",
                        roles=ALLOWED_ROLES, errors={}, form=form,
                        version=getattr(app, "_llc_version", None),
                    )
                if _find_user(users, form["username"]):
                    errors["username"] = "That username is already taken."

            # ── Persist if clean ──────────────────────────────────────────────
            if not errors:
                new_user = {
                    "username":   form["username"],
                    "password":   _hash(form["password"]),
                    "full_name":  form["full_name"],
                    "phone":      form["phone"],
                    "role":       form["role"],
                    "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                }
                users.append(new_user)
                try:
                    _save_users(llc_name, users)
                except RuntimeError as exc:
                    app.logger.error("Register DB write error: %s", exc)
                    flash("Could not save account. Contact your administrator.", "error")
                    return render_template(
                        "register.html",
                        roles=ALLOWED_ROLES, errors={}, form=form,
                        version=getattr(app, "_llc_version", None),
                    )

                flash(
                    f"Account created for {form['full_name']}. Please sign in.",
                    "success",
                )
                return redirect(url_for("login"))

        return render_template(
            "register.html",
            roles=ALLOWED_ROLES,
            errors=errors,
            form=form,
            version=getattr(app, "_llc_version", None),
        )