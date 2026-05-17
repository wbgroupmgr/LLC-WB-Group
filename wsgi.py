# wsgi.py — PythonAnywhere WSGI entry point for the LLC Management Flask app
#
# PythonAnywhere dashboard → Web tab → WSGI configuration file: point to this file.
# Python version: 3.10+
#
# Expected repo layout on PA:
#   /home/<pa-user>/LLC-WB-Group/
#       pages/AccountingData/Notebooks/   ← this file lives here
#           ledger/setup_paths.py         ← anchors all path constants
#           Accts/                        ← JSON DBs (llcAssets, llcExpRev, …)
#
import sys
from pathlib import Path

# Add Notebooks/ to sys.path so all sibling packages (ledger, stmt, ui, …) are importable.
_notebooks = Path(__file__).resolve().parent
if str(_notebooks) not in sys.path:
    sys.path.insert(0, str(_notebooks))

from util.utilEditSession import utilEditSession
from uillc.llcMgmt import llcMgmt

_eSession = utilEditSession(llcName='WBGroupLLC', load=True)
_mgmt = llcMgmt(_eSession)

# PythonAnywhere (and any WSGI server) looks for `application`.
application = _mgmt.app
