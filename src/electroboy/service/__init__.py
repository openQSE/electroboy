"""Compatibility API for the ElectroBoy browser service package."""

from __future__ import annotations

from . import app as _app
from . import sessions as _sessions

for _module in (_app, _sessions):
    for _name in dir(_module):
        if _name.startswith("__"):
            continue
        globals()[_name] = getattr(_module, _name)

__all__ = [_name for _name in globals() if not _name.startswith("__")]
