# wsgi.py — PythonAnywhere WSGI entry point for the LLC Management Flask app
#
# PythonAnywhere dashboard → Web tab → WSGI configuration file: point to this file.
# Python version: 3.10+
#
# Expected repo layout on PA:
#   /home/<pa-user>/llcRentalTracker/   ← this file lives here
#       ledger/setup_paths.py           ← config-driven path constants
#
# ~/.llcRentalTracker/config.json must exist with a "default" stanza before starting.
# Run:  python3 wsCmd.py --newBus <bus_repo_path> --year <year>
#       python3 wsCmd.py --setup
#
import os
import sys
from pathlib import Path

_app_root = Path(__file__).resolve().parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

from ledger import setup_paths as _sp

_default = _sp.get_default()
if _default is None:
    raise RuntimeError(
        f"No default LLC in {_sp.CONFIG_FILE}. "
        "Run: python3 wsCmd.py --newBus <path> --year <year>"
    )
LLC_NAME, LLC_YEAR = _default
_sp.load_config(LLC_NAME, LLC_YEAR)

# Inject LLC_SECRET_KEY and LLC_GPG_PASSPHRASE from ~/.llcRentalTracker/config.json.
# SOLE SOURCE — no fallback. Hard fail if either key is missing.
#   APP_SECRET_KEY (top-level)             → LLC_SECRET_KEY env var  (per-tracker)
#   llcList[LLC_NAME].APP_GPG_PASSPHRASE   → LLC_GPG_PASSPHRASE env var  (per-BUS)

def _inject_secrets() -> None:
    _cfg = _sp.read_config()
    _sk  = _cfg.get("APP_SECRET_KEY", "")
    _pp  = _sp.SECRETS.get("APP_GPG_PASSPHRASE", "")
    if not _pp:
        raise RuntimeError(
            f"[wsgi] FATAL: APP_GPG_PASSPHRASE missing for '{LLC_NAME}' in {_sp.CONFIG_FILE}.\n"
            "  Run: python3 wsCmd.py --newBus <path> --year <year> --llcName <name>"
        )
    if not _sk:
        raise RuntimeError(
            f"[wsgi] FATAL: APP_SECRET_KEY missing from {_sp.CONFIG_FILE}.\n"
            "  Run: python3 wsCmd.py --setup --llcName <name>"
        )
    os.environ.setdefault("LLC_GPG_PASSPHRASE", _pp)
    os.environ.setdefault("LLC_SECRET_KEY", _sk)

_inject_secrets()

# Hard startup validation — fail NOW if the configured paths don't exist on disk.
# Never serve the app with a wrong bus_repo; surface the error immediately.
_top  = _sp.TOP
_acct = _sp.ACCTS_DIR
if not _top or not Path(_top).exists():
    raise RuntimeError(
        f"[wsgi] FATAL: bus_repo not found on disk: {_top}\n"
        f"  Loaded from: {_sp.CONFIG_FILE}\n"
        f"  Fix: update bus_repo in {_sp.CONFIG_FILE} to the correct path on this machine.\n"
        f"  Then reload the web app."
    )
if not Path(_acct).exists():
    raise RuntimeError(
        f"[wsgi] FATAL: Accts/ directory not found: {_acct}\n"
        f"  TOP={_top} exists but books/Accts/ is missing.\n"
        f"  Check that books_dir is correct in {_sp.CONFIG_FILE}."
    )

# Wire Python root logger → stderr so BookToIRS/agent INFO logs appear in the PA server log.
import logging as _logging
_logging.basicConfig(
    level=_logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

import traceback as _tb

try:
    from util.utilEditSession import utilEditSession
    from ui.llcMgmt import llcMgmt

    _eSession = utilEditSession(llcName=LLC_NAME, year=LLC_YEAR, load=True)
    _mgmt     = llcMgmt(_eSession)
    application = _mgmt.app


except Exception as _startup_err:
    # Emit full traceback to the uWSGI log so PA's error tab shows it.
    _tb.print_exc()
    # Expose a minimal WSGI app that returns the traceback as plain text
    # so the PA "browser" preview also shows the error.
    _tb_text = _tb.format_exc()
    def application(environ, start_response):
        body = f"LLC Startup Error:\n\n{_tb_text}".encode()
        start_response("500 Internal Server Error",
                       [("Content-Type", "text/plain"),
                        ("Content-Length", str(len(body)))])
        return [body]
