"""Provider-neutral IDE integration contracts."""

from .bridge import BRIDGE_PROTOCOL_VERSION, IDEBridge, IDEBridgeRegistration
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
from .manager import IDEInstanceManager
from .openvscode import OpenVSCodeProvider
from .ownership import IDEInstanceRegistry
from .resolver import OpenVSCodeRuntimeResolver
from .sandbox import (
    CSPViolationStore,
    IDEEgressEvent,
    IDEEgressMode,
    IDEEgressPolicy,
    IDEEgressRule,
    LinuxNetworkSandbox,
    ide_content_security_policy,
)

__all__ = [
    "CSPViolationStore",
    "BRIDGE_PROTOCOL_VERSION",
    "IDEBridge",
    "IDEBridgeRegistration",
    "IDEEditorContext",
    "IDEEgressEvent",
    "IDEEgressMode",
    "IDEEgressPolicy",
    "IDEEgressRule",
    "IDEEndpoint",
    "IDEError",
    "IDEErrorCategory",
    "IDEInstance",
    "IDEInstanceManager",
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
    "LinuxNetworkSandbox",
    "OpenVSCodeRuntimeResolver",
    "OpenVSCodeProvider",
    "RuntimeInstaller",
    "RuntimeResolver",
    "ide_content_security_policy",
]
