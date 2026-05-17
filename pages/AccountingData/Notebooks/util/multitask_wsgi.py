import sys, os
from pathlib import Path
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.exceptions import NotFound

# ── pyMultiTaskWS root (multitrack/ + adminTracker/ importable from here) ─────
_pkg = '/home/wbgroup/pyMultiTaskWS'
if _pkg not in sys.path:
    sys.path.insert(0, _pkg)

# ── Tracker registry (shown on AdminTracker home page) ────────────────────────
import adminTracker.registry as _reg
_reg.TRACKERS = [
    {
        "name":        "AdminTracker",
        "mount":       "/admin",
        "url":         "/admin/",
        "description": "Platform administration — user management & tracker index",
        "status":      "online",
    },
    {
        "name":        "LLC Accounting",
        "mount":       "/llc",
        "url":         "/llc/login",
        "description": "W&B Group LLC — double-entry ledger & IRS forms",
        "status":      "online",
    },
]

# ── AdminTracker ──────────────────────────────────────────────────────────────
os.environ.setdefault('MULTITRACK_GPG_PASSPHRASE', 'mylord,myredeemer,myrock')
os.environ.setdefault('WEB_SECRET_KEY', 'e7bb41b6121bb86c8e698531b8e23682aff69bfb095031122dda1f32acc56ff4')
from adminTracker.wsgi import application as admin_app

# ── LLC Tracker (uncomment after running LLC setup) ───────────────────────────
# os.environ.setdefault('LLC_GPG_PASSPHRASE', '<llc-passphrase>')
# os.environ.setdefault('LLC_SECRET_KEY',     '<llc-secret-key>')
# sys.path.insert(0, '/home/wbgroup/llc/LLC-WB-Group/pages/AccountingData/Notebooks')
# from wsgi import application as llc_app

# ── Dispatcher ────────────────────────────────────────────────────────────────
application = DispatcherMiddleware(NotFound(), {
    '/admin': admin_app,
    # '/llc':   llc_app,
})
