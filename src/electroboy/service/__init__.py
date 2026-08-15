"""Compatibility API for the ElectroBoy browser service package."""

from __future__ import annotations

from importlib import import_module

from . import app as _app
from . import file_browser as _file_browser
from . import sessions as _sessions

for _module in (_app, _file_browser, _sessions):
    for _name in dir(_module):
        if _name.startswith("__"):
            continue
        globals()[_name] = getattr(_module, _name)

_OPTIONAL_COMPATIBILITY_MODULES = (
    "electroboy.modules.creative_workspace",
    "electroboy.modules.document_service",
    "electroboy.modules.progress_service",
    "electroboy.workflows.software.domain",
)


def __getattr__(name: str):
    for module_name in _OPTIONAL_COMPATIBILITY_MODULES:
        try:
            module = import_module(module_name)
        except ModuleNotFoundError:
            continue
        if hasattr(module, name):
            value = getattr(module, name)
            globals()[name] = value
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [_name for _name in globals() if not _name.startswith("__")]
