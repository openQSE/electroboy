"""Provider-neutral IDE integration contracts."""

from .bridge import BRIDGE_PROTOCOL_VERSION, IDEBridge, IDEBridgeRegistration
from .clangd import ClangdProfileManager
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
from .egress import IDEEgressPolicyRegistry, IDEWorkspaceEgress
from .installer import ManagedRuntimeInstaller
from .manager import IDEInstanceManager
from .openvscode import OpenVSCodeProvider
from .ownership import IDEInstanceRegistry
from .resolver import ManagedRuntimeResolver, OpenVSCodeRuntimeResolver
from .sandbox import (
    CSPViolationStore,
    IDEEgressEvent,
    IDEEgressMode,
    IDEEgressPolicy,
    IDEEgressRule,
    LinuxNetworkSandbox,
    WorkspaceNetworkSandbox,
    ide_content_security_policy,
)

__all__ = [
    "CSPViolationStore",
    "BRIDGE_PROTOCOL_VERSION",
    "ClangdProfileManager",
    "IDEBridge",
    "IDEBridgeRegistration",
    "IDEEditorContext",
    "IDEEgressEvent",
    "IDEEgressMode",
    "IDEEgressPolicy",
    "IDEEgressPolicyRegistry",
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
    "IDEWorkspaceEgress",
    "ManagedRuntimeInstaller",
    "ManagedRuntimeResolver",
    "LinuxNetworkSandbox",
    "WorkspaceNetworkSandbox",
    "OpenVSCodeRuntimeResolver",
    "OpenVSCodeProvider",
    "RuntimeInstaller",
    "RuntimeResolver",
    "ide_content_security_policy",
]
