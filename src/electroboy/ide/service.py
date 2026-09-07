"""Application-facing IDE service composed from provider-neutral parts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .artifacts import load_runtime_manifest
from .domain import (
    IDEError,
    IDEErrorCategory,
    IDEInstanceStatus,
    IDELocation,
    IDERuntimeMode,
    IDEWorkspace,
)
from .installer import ManagedRuntimeInstaller
from .manager import IDEInstanceManager
from .openvscode import OpenVSCodeProvider
from .resolver import OpenVSCodeRuntimeResolver
from .sandbox import (
    CSPViolationStore,
    IDEEgressMode,
    IDEEgressPolicy,
    LinuxNetworkSandbox,
)


@dataclass(frozen=True)
class IDEConfiguration:
    """Operator-controlled IDE runtime and lifecycle settings."""

    data_root: Path
    runtime_mode: IDERuntimeMode = IDERuntimeMode.AUTO
    system_executable: Path | None = None
    egress_mode: IDEEgressMode = IDEEgressMode.DENY
    maximum_instances: int = 2
    idle_timeout: float = 900
    startup_timeout: float = 30

    @classmethod
    def from_environment(cls) -> IDEConfiguration:
        data_root = _ide_data_root()
        mode = IDERuntimeMode(
            os.environ.get("ELECTROBOY_IDE_RUNTIME_MODE", "auto").strip().lower()
        )
        executable_text = os.environ.get("ELECTROBOY_IDE_EXECUTABLE", "").strip()
        egress_mode = IDEEgressMode(
            os.environ.get("ELECTROBOY_IDE_EGRESS_MODE", "deny").strip().lower()
        )
        return cls(
            data_root=data_root,
            runtime_mode=mode,
            system_executable=(
                Path(executable_text).expanduser() if executable_text else None
            ),
            egress_mode=egress_mode,
            maximum_instances=max(
                1,
                int(os.environ.get("ELECTROBOY_IDE_MAX_INSTANCES", "2")),
            ),
            idle_timeout=max(
                0,
                float(os.environ.get("ELECTROBOY_IDE_IDLE_TIMEOUT", "900")),
            ),
            startup_timeout=max(
                1,
                float(os.environ.get("ELECTROBOY_IDE_STARTUP_TIMEOUT", "30")),
            ),
        )


class IDEService:
    """Coordinate runtime, process, policy, and public IDE operations."""

    def __init__(self, configuration: IDEConfiguration | None = None) -> None:
        self.configuration = configuration or IDEConfiguration.from_environment()
        manifest = load_runtime_manifest()
        self.resolver = OpenVSCodeRuntimeResolver(
            manifest,
            self.configuration.data_root,
        )
        self.installer = ManagedRuntimeInstaller(self.resolver)
        policy = IDEEgressPolicy(
            self.configuration.egress_mode,
            audit_acknowledged=self.configuration.egress_mode
            is IDEEgressMode.AUDIT,
        )
        self.sandbox = LinuxNetworkSandbox(policy)
        self.provider = OpenVSCodeProvider(process_launcher=self.sandbox)
        self.manager = IDEInstanceManager(
            self.provider,
            self.resolver,
            self.installer,
            self.configuration.data_root,
            maximum_instances=self.configuration.maximum_instances,
            idle_timeout=self.configuration.idle_timeout,
            startup_timeout=self.configuration.startup_timeout,
        )
        self.csp_violations = CSPViolationStore()

    def runtime_status(self) -> dict[str, object]:
        try:
            runtime = self.resolver.resolve(
                self.configuration.runtime_mode,
                system_executable=self.configuration.system_executable,
            )
            return {
                "status": "disabled" if runtime is None else "ready",
                "runtime": runtime.payload() if runtime else None,
                "resolution": self.resolver.diagnostics(),
            }
        except IDEError as error:
            return {
                "status": "missing"
                if error.recoverable
                else "unavailable",
                "runtime": None,
                "resolution": self.resolver.diagnostics(),
                "error": error.payload(),
            }

    def install(self) -> dict[str, object]:
        runtime = self.installer.install()
        return {"status": "ready", "runtime": runtime.payload()}

    def start(self, workspace_id: str, project_root: Path) -> dict[str, object]:
        instance, started = self.manager.start(
            IDEWorkspace(workspace_id, project_root.resolve()),
            mode=self.configuration.runtime_mode,
            system_executable=self.configuration.system_executable,
        )
        return {
            "status": "started" if started else "already_running",
            "instance": instance.public_payload(),
            "view_path": f"/ide/{workspace_id}/",
        }

    def status(self, workspace_id: str) -> dict[str, object]:
        instance = self.manager.status(workspace_id)
        return {
            "status": instance.status.value if instance else "stopped",
            "instance": instance.public_payload() if instance else None,
            "runtime": self.runtime_status(),
            "sandbox": self.sandbox.availability(),
        }

    def stop(self, workspace_id: str, reason: str = "requested") -> dict[str, object]:
        instance = self.manager.stop(workspace_id, reason)
        return {
            "status": "stopped",
            "instance": instance.public_payload() if instance else None,
        }

    def open_location(
        self,
        workspace_id: str,
        location: IDELocation,
    ) -> dict[str, object]:
        instance = self.manager.status(workspace_id)
        if instance is None or instance.status is not IDEInstanceStatus.READY:
            raise IDEError(
                category=IDEErrorCategory.NOT_READY,
                message="start the workspace IDE before opening a location",
                recoverable=True,
            )
        self.provider.open_location(instance, location)
        self.manager.touch(workspace_id)
        return {"status": "opened", "location": location.__dict__}

    def diagnostics(self, workspace_id: str) -> dict[str, object]:
        instance = self.manager.status(workspace_id)
        return {
            "runtime": self.resolver.diagnostics(),
            "instance": instance.public_payload() if instance else None,
            "provider_output": (
                self.provider.diagnostics(instance.instance_id) if instance else []
            ),
            "sandbox": (
                self.provider.enforcement(instance.instance_id)
                if instance
                else self.sandbox.availability()
            ),
            "egress_events": self.sandbox.events(),
            "csp_violations": self.csp_violations.events(),
            "limits": {
                "maximum_instances": self.configuration.maximum_instances,
                "idle_timeout": self.configuration.idle_timeout,
            },
        }

    def record_csp_violation(self, payload: object) -> dict[str, object]:
        event = self.csp_violations.record(payload)
        return {"status": "recorded" if event else "ignored"}

    def close(self) -> None:
        self.manager.stop_all()


def _ide_data_root() -> Path:
    configured = os.environ.get("ELECTROBOY_IDE_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg_data).expanduser() if xdg_data else Path.home() / ".local/share"
    return (base / "electroboy").resolve()
