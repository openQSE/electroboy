"""Provider-neutral IDE integration contracts."""

from .contracts import IDEProvider, RuntimeInstaller, RuntimeResolver
from .domain import (
    IDEEditorContext,
    IDEEndpoint,
    IDEError,
    IDEErrorCategory,
    IDEInstance,
    IDEInstanceStatus,
    IDELocation,
    IDEProfile,
    IDERuntime,
    IDERuntimeMode,
    IDERuntimeOrigin,
    IDEWorkspace,
)
from .installer import ManagedRuntimeInstaller
from .ownership import IDEInstanceRegistry
from .resolver import OpenVSCodeRuntimeResolver

__all__ = [
    "IDEEditorContext",
    "IDEEndpoint",
    "IDEError",
    "IDEErrorCategory",
    "IDEInstance",
    "IDEInstanceRegistry",
    "IDEInstanceStatus",
    "IDELocation",
    "IDEProfile",
    "IDEProvider",
    "IDERuntime",
    "IDERuntimeMode",
    "IDERuntimeOrigin",
    "IDEWorkspace",
    "ManagedRuntimeInstaller",
    "OpenVSCodeRuntimeResolver",
    "RuntimeInstaller",
    "RuntimeResolver",
]
