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

# Load WEB_SECRET_KEY from MultiTaskWS config.
# Prefer the per-tracker stanza (cfg["rentalTracker"]["WEB_SECRET_KEY"]);
# fall back to the top-level WEB_SECRET_KEY.
import json as _json
_mw_cfg = Path.home() / ".MultiTaskWS" / "MultiTaskWS_config.json"
if _mw_cfg.exists():
    _mw = _json.loads(_mw_cfg.read_text())
    _secret = (_mw.get("rentalTracker", {}).get("WEB_SECRET_KEY")
               or _mw.get("WEB_SECRET_KEY"))
    if _secret:
        os.environ.setdefault("LLC_SECRET_KEY", _secret)

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
