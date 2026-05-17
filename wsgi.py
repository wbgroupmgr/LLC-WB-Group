# wsgi.py — PythonAnywhere WSGI entry point for the LLC Management Flask app
#
# PythonAnywhere dashboard → Web tab → WSGI configuration file: point to this file.
# Python version: 3.10+
#
# Expected repo layout on PA:
#   /home/<pa-user>/llcRentalTracker/   ← this file lives here
#       ledger/setup_paths.py           ← config-driven path constants
#
# ~/.llcRentalTracker/WBGroupLLC_2025_config.json must exist before starting.
# Update LLC_NAME and LLC_YEAR below when deploying a different year.
#
import sys
from pathlib import Path

_app_root = Path(__file__).resolve().parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

LLC_NAME = 'WBGroupLLC'
LLC_YEAR = 2025

from ledger import setup_paths as _sp
_sp.load_config(LLC_NAME, LLC_YEAR)

from util.utilEditSession import utilEditSession
from ui.llcMgmt import llcMgmt

_eSession = utilEditSession(llcName='WBGroupLLC', year=LLC_YEAR, load=True)
_mgmt = llcMgmt(_eSession)

# PythonAnywhere (and any WSGI server) looks for `application`.
application = _mgmt.app
