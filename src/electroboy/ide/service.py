"""Application-facing IDE service composed from provider-neutral parts."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .artifacts import load_runtime_manifest
from .bridge import IDEBridge
from .domain import (
    IDEEditorContext,
    IDEEndpoint,
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
from .proxy import IDEProxySessionStore, IDEUnixProxy
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
    maximum_views_per_instance: int = 2
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
            maximum_views_per_instance=max(
                1,
                int(os.environ.get("ELECTROBOY_IDE_MAX_VIEWS", "2")),
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

    def __init__(
        self,
        configuration: IDEConfiguration | None = None,
        *,
        context_callback: Callable[[str, IDEEditorContext | None], None] | None = None,
    ) -> None:
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
        self.bridge = IDEBridge()
        self.provider = OpenVSCodeProvider(
            process_launcher=self.sandbox,
            bridge=self.bridge,
        )
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
        self.proxy_sessions = IDEProxySessionStore()
        self.proxy = IDEUnixProxy(self.configuration.egress_mode)
        self._views: dict[str, dict[str, float]] = {}
        self._view_lock = threading.RLock()
        self._view_timeout = 45.0
        self._context_callback = context_callback
        self._context_revisions: dict[str, int] = {}
        self._context_lock = threading.RLock()
        self._context_stop = threading.Event()
        self._context_thread: threading.Thread | None = None

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
        self._ensure_context_monitor()
        return {
            "status": "started" if started else "already_running",
            "instance": instance.public_payload(),
            "view_path": f"/ide/{workspace_id}/",
        }

    def status(
        self,
        workspace_id: str,
        project_root: Path | None = None,
    ) -> dict[str, object]:
        instance = self.manager.status(workspace_id)
        if (
            instance is not None
            and project_root is not None
            and instance.workspace.project_root != project_root.resolve()
        ):
            self.stop(workspace_id, "active project changed")
            instance = None
        return {
            "status": instance.status.value if instance else "stopped",
            "instance": instance.public_payload() if instance else None,
            "runtime": self.runtime_status(),
            "sandbox": self.sandbox.availability(),
        }

    def stop(self, workspace_id: str, reason: str = "requested") -> dict[str, object]:
        instance = self.manager.stop(workspace_id, reason)
        self.proxy_sessions.revoke_workspace(workspace_id)
        with self._view_lock:
            self._views.pop(workspace_id, None)
        with self._context_lock:
            self._context_revisions.pop(workspace_id, None)
        self._publish_context(workspace_id, None)
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
            "configuration": {
                "runtime_mode": self.configuration.runtime_mode.value,
                "egress_mode": self.configuration.egress_mode.value,
                "managed_profile": True,
                "theme": "ElectroBoy",
            },
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
                "maximum_views_per_instance": (
                    self.configuration.maximum_views_per_instance
                ),
                "idle_timeout": self.configuration.idle_timeout,
            },
            "view_count": self._view_count(workspace_id),
            "editor_context": self.editor_context(workspace_id),
        }

    def editor_context(self, workspace_id: str) -> dict[str, object] | None:
        instance = self.manager.status(workspace_id)
        if instance is None or instance.status is not IDEInstanceStatus.READY:
            return None
        context = self.bridge.context(instance)
        if context is not None:
            self._accept_context(context)
        return context.payload() if context else None

    def record_csp_violation(self, payload: object) -> dict[str, object]:
        event = self.csp_violations.record(payload)
        return {"status": "recorded" if event else "ignored"}

    def proxy_endpoint(self, workspace_id: str) -> IDEEndpoint:
        instance = self.manager.status(workspace_id)
        if instance is None or instance.status is not IDEInstanceStatus.READY:
            raise IDEError(
                IDEErrorCategory.NOT_READY,
                "IDE instance is not ready",
                recoverable=True,
            )
        return self.provider.endpoint(instance)

    def attach_view(self, workspace_id: str, view_id: str) -> dict[str, object]:
        requested = view_id.strip()
        if not requested:
            raise ValueError("IDE view ID is required")
        instance = self.manager.status(workspace_id)
        if instance is None or instance.status is not IDEInstanceStatus.READY:
            raise IDEError(
                IDEErrorCategory.NOT_READY,
                "IDE instance is not ready",
                recoverable=True,
            )
        now = time.monotonic()
        with self._view_lock:
            views = self._views.setdefault(workspace_id, {})
            self._prune_views(views, now)
            if (
                requested not in views
                and len(views) >= self.configuration.maximum_views_per_instance
            ):
                raise IDEError(
                    IDEErrorCategory.INSTANCE_LIMIT,
                    "maximum IDE view count reached for this workspace",
                    recoverable=True,
                )
            views[requested] = now
            count = len(views)
        self.manager.touch(workspace_id)
        return {"status": "attached", "view_id": requested, "view_count": count}

    def detach_view(self, workspace_id: str, view_id: str) -> dict[str, object]:
        with self._view_lock:
            views = self._views.get(workspace_id, {})
            views.pop(view_id.strip(), None)
            if not views:
                self._views.pop(workspace_id, None)
            count = len(views)
        return {"status": "detached", "view_count": count}

    def _view_count(self, workspace_id: str) -> int:
        now = time.monotonic()
        with self._view_lock:
            views = self._views.get(workspace_id, {})
            self._prune_views(views, now)
            return len(views)

    def _prune_views(self, views: dict[str, float], now: float) -> None:
        for view_id, seen_at in list(views.items()):
            if now - seen_at >= self._view_timeout:
                views.pop(view_id, None)

    def close(self) -> None:
        self._context_stop.set()
        if self._context_thread is not None:
            self._context_thread.join(timeout=2)
        self.manager.stop_all()

    def _ensure_context_monitor(self) -> None:
        if self._context_thread is not None and self._context_thread.is_alive():
            return
        self._context_stop.clear()
        self._context_thread = threading.Thread(
            target=self._monitor_context,
            name="electroboy-ide-context",
            daemon=True,
        )
        self._context_thread.start()

    def _monitor_context(self) -> None:
        while not self._context_stop.wait(0.2):
            for instance in self.manager.registry.values():
                try:
                    context = self.bridge.context(instance)
                    if context is not None:
                        self._accept_context(context)
                except Exception:
                    continue

    def _accept_context(self, context: IDEEditorContext) -> None:
        with self._context_lock:
            previous = self._context_revisions.get(context.workspace_id, -1)
            if context.revision <= previous:
                return
            self._context_revisions[context.workspace_id] = context.revision
        self._publish_context(
            context.workspace_id,
            context if context.path else None,
        )

    def _publish_context(
        self,
        workspace_id: str,
        context: IDEEditorContext | None,
    ) -> None:
        if self._context_callback is not None:
            self._context_callback(workspace_id, context)


def _ide_data_root() -> Path:
    configured = os.environ.get("ELECTROBOY_IDE_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg_data).expanduser() if xdg_data else Path.home() / ".local/share"
    return (base / "electroboy").resolve()
