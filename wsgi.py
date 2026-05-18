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

# Load LLC_SECRET_KEY from the MultiTaskWS tracker stanza (primary source).
import json as _json
_mw_cfg = Path.home() / ".MultiTaskWS" / "MultiTaskWS_config.json"
if _mw_cfg.exists():
    for _t in _json.loads(_mw_cfg.read_text()).get("Trackers", []):
        if _t.get("name") == "llcRentalTracker" and _t.get("secret_key"):
            os.environ.setdefault("LLC_SECRET_KEY", _t["secret_key"])
            break

# Fallback: ~/.llcRentalTracker/.env (key=value lines, never committed to git).
_env_file = Path.home() / ".llcRentalTracker" / ".env"
if _env_file.exists():
    for _ln in _env_file.read_text().splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#") and "=" in _ln:
            _k, _, _v = _ln.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

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

from util.utilEditSession import utilEditSession
from ui.llcMgmt import llcMgmt

_eSession = utilEditSession(llcName=LLC_NAME, year=LLC_YEAR, load=True)
_mgmt = llcMgmt(_eSession)

# PythonAnywhere (and any WSGI server) looks for `application`.
application = _mgmt.app
