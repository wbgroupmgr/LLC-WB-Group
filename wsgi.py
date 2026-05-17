# wsgi.py — PythonAnywhere WSGI entry point for the LLC Management Flask app
#
# PythonAnywhere dashboard → Web tab → WSGI configuration file: point to this file.
# Python version: 3.10+
#
# Expected repo layout on PA:
#   /home/<pa-user>/llcRentalTracker/   ← this file lives here
#       ledger/setup_paths.py           ← config-driven path constants
#
# ~/.llcRentalTracker/WBGroupLLC_config.json must exist before starting.
#
import sys
from pathlib import Path

_app_root = Path(__file__).resolve().parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

from ledger import setup_paths as _sp
_sp.load_config('WBGroupLLC')

from util.utilEditSession import utilEditSession
from ui.llcMgmt import llcMgmt

_eSession = utilEditSession(llcName='WBGroupLLC', load=True)
_mgmt = llcMgmt(_eSession)

# PythonAnywhere (and any WSGI server) looks for `application`.
application = _mgmt.app
