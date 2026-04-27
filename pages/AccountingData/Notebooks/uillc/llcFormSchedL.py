"""
uillc.llcFormSchedL — Compatibility shim (Phase 4 DataModelGuide refactor).

The real implementation moved to ui.llcFormSchedL as part of the ui/ refactor
(DataModelGuide § 3 — View Services hold no data construction).  This
shim re-exports the public surface so existing callers importing from
``uillc.llcFormSchedL`` keep working unchanged.

Timestamp of last change: 2026.04.19
"""

from ui.llcFormSchedL import *  # noqa: F401,F403
from ui import llcFormSchedL as _ui_mod

# Re-export the module-level __all__ if the target defined one, so that
# ``from uillc.llcFormSchedL import X`` continues to resolve names the target
# chose to export explicitly.
try:
    __all__ = list(_ui_mod.__all__)  # type: ignore[attr-defined]
except AttributeError:
    __all__ = [n for n in dir(_ui_mod) if not n.startswith("_")]
