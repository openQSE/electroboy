"""Application-facing IDE service composed from provider-neutral parts."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import urlencode

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
from .downloads import AuditedDownloadClient
from .egress import IDEEgressPolicyRegistry
from .installer import ManagedRuntimeInstaller
from .manager import IDEInstanceManager
from .neovim import NeovimProfileManager
from .openvscode import OpenVSCodeProvider
from .proxy import IDEProxySessionStore, IDEUnixProxy
from .resolver import OpenVSCodeRuntimeResolver
from .sandbox import (
    CSPViolationStore,
    IDEEgressMode,
    IDEEgressPolicy,
    WorkspaceNetworkSandbox,
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
        saved = _load_configuration(data_root)
        mode = IDERuntimeMode(
            os.environ.get(
                "ELECTROBOY_IDE_RUNTIME_MODE",
                str(saved.get("runtime_mode") or "auto"),
            ).strip().lower()
        )
        executable_text = os.environ.get(
            "ELECTROBOY_IDE_EXECUTABLE",
            str(saved.get("system_executable") or ""),
        ).strip()
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
                int(
                    os.environ.get(
                        "ELECTROBOY_IDE_MAX_INSTANCES",
                        str(saved.get("maximum_instances") or 2),
                    )
                ),
            ),
            maximum_views_per_instance=max(
                1,
                int(
                    os.environ.get(
                        "ELECTROBOY_IDE_MAX_VIEWS",
                        str(saved.get("maximum_views_per_instance") or 2),
                    )
                ),
            ),
            idle_timeout=max(
                0,
                float(
                    os.environ.get(
                        "ELECTROBOY_IDE_IDLE_TIMEOUT",
                        str(saved.get("idle_timeout", 900)),
                    )
                ),
            ),
            startup_timeout=max(
                1,
                float(
                    os.environ.get(
                        "ELECTROBOY_IDE_STARTUP_TIMEOUT",
                        str(saved.get("startup_timeout") or 30),
                    )
                ),
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
        self.download_client = AuditedDownloadClient()
        self.installer = ManagedRuntimeInstaller(
            self.resolver,
            download_client=self.download_client,
        )
        self.neovim = NeovimProfileManager(
            self.configuration.data_root,
            self.download_client,
            platform=self.resolver.platform,
            architecture=self.resolver.architecture,
        )
        default_policy = IDEEgressPolicy(
            self.configuration.egress_mode,
            audit_acknowledged=self.configuration.egress_mode
            is IDEEgressMode.AUDIT,
        )
        self.egress_policies = IDEEgressPolicyRegistry(
            self.configuration.egress_mode
        )
        self.sandbox = WorkspaceNetworkSandbox(default_policy)
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
        current = self.manager.status(workspace_id)
        if current is None or current.workspace.project_root != project_root.resolve():
            profile = self.manager.profile_for(workspace_id)
            self.sandbox.configure(
                workspace_id,
                profile,
                self.egress_policies.get(workspace_id).policy(),
            )
            self.neovim.prepare(profile)
        instance, started = self.manager.start(
            IDEWorkspace(workspace_id, project_root.resolve()),
            mode=self.configuration.runtime_mode,
            system_executable=self.configuration.system_executable,
        )
        self._ensure_context_monitor()
        return {
            "status": "started" if started else "already_running",
            "instance": instance.public_payload(),
            "view_path": _ide_view_path(instance.workspace),
            "neovim": self.neovim.diagnostics(),
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
            "view_path": _ide_view_path(instance.workspace) if instance else None,
            "runtime": self.runtime_status(),
            "sandbox": self.sandbox.availability(
                self.manager.profile_for(workspace_id)
            ),
        }
    def stop(self, workspace_id: str, reason: str = "requested") -> dict[str, object]:
        instance = self.manager.stop(workspace_id, reason)
        self.proxy_sessions.revoke_workspace(workspace_id)
        with self._view_lock:
            self._views.pop(workspace_id, None)
        with self._context_lock:
            self._context_revisions.pop(workspace_id, None)
        self._publish_context(workspace_id, None)
        if reason == "project deactivated":
            profile = self.manager.profile_for(workspace_id)
            self.sandbox.remove(profile)
            self.egress_policies.clear(workspace_id)
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
        request_id = self.provider.open_location(instance, location)
        self.manager.touch(workspace_id)
        return {
            "status": "queued",
            "request_id": request_id,
            "location": location.__dict__,
        }

    def diagnostics(self, workspace_id: str) -> dict[str, object]:
        instance = self.manager.status(workspace_id)
        profile = self.manager.profile_for(workspace_id)
        egress = self.egress_policies.get(workspace_id)
        return {
            "configuration": {
                "runtime_mode": self.configuration.runtime_mode.value,
                "egress_mode": egress.mode.value,
                "managed_profile": True,
                "theme": "ElectroBoy",
            },
            "runtime": self.resolver.diagnostics(),
            "instance": instance.public_payload() if instance else None,
            "provider_output": (
                self.provider.diagnostics(instance.instance_id) if instance else []
            ),
            "bridge": self.bridge.diagnostics(instance) if instance else None,
            "sandbox": (
                self.provider.enforcement(instance.instance_id)
                if instance
                else self.sandbox.availability(profile)
            ),
            "egress": egress.payload(),
            "egress_events": self.sandbox.events(profile),
            "csp_violations": self.csp_violations.events(workspace_id),
            "limits": {
                "maximum_instances": self.configuration.maximum_instances,
                "maximum_views_per_instance": (
                    self.configuration.maximum_views_per_instance
                ),
                "idle_timeout": self.configuration.idle_timeout,
            },
            "view_count": self._view_count(workspace_id),
            "editor_context": self.editor_context(workspace_id),
            "neovim": self.neovim.diagnostics(),
            "managed_downloads": self.download_client.events(),
        }

    def record_input_event(
        self,
        workspace_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        instance = self.manager.status(workspace_id)
        if instance is None or instance.status is not IDEInstanceStatus.READY:
            raise IDEError(
                IDEErrorCategory.NOT_READY,
                "the workspace IDE is not ready for input telemetry",
                recoverable=True,
            )
        event = self.bridge.record_input_event(instance, payload)
        return {"status": "recorded", "event": event}

    def configuration_status(self, workspace_id: str) -> dict[str, object]:
        return {
            "status": "ready",
            "provider": "openvscode",
            "configuration": _configuration_payload(self.configuration),
            "runtime": self.runtime_status(),
            "restart_required": self.manager.status(workspace_id) is not None,
        }

    def configure(
        self,
        workspace_id: str,
        values: dict[str, object],
    ) -> dict[str, object]:
        runtime_mode = IDERuntimeMode(
            str(values.get("runtime_mode") or self.configuration.runtime_mode.value)
        )
        executable_text = str(values.get("system_executable") or "").strip()
        maximum_instances = _bounded_int(
            values.get("maximum_instances"),
            "maximum_instances",
            minimum=1,
            maximum=8,
        )
        maximum_views = _bounded_int(
            values.get("maximum_views_per_instance"),
            "maximum_views_per_instance",
            minimum=1,
            maximum=8,
        )
        idle_timeout = _bounded_float(
            values.get("idle_timeout"),
            "idle_timeout",
            minimum=0,
            maximum=86400,
        )
        startup_timeout = _bounded_float(
            values.get("startup_timeout"),
            "startup_timeout",
            minimum=1,
            maximum=300,
        )
        self.configuration = replace(
            self.configuration,
            runtime_mode=runtime_mode,
            system_executable=(
                Path(executable_text).expanduser() if executable_text else None
            ),
            maximum_instances=maximum_instances,
            maximum_views_per_instance=maximum_views,
            idle_timeout=idle_timeout,
            startup_timeout=startup_timeout,
        )
        self.manager.maximum_instances = maximum_instances
        self.manager.idle_timeout = idle_timeout
        self.manager.startup_timeout = startup_timeout
        _save_configuration(self.configuration)
        return {
            **self.configuration_status(workspace_id),
            "status": "configured",
        }

    def network_status(self, workspace_id: str) -> dict[str, object]:
        instance = self.manager.status(workspace_id)
        profile = self.manager.profile_for(workspace_id)
        configured = self.egress_policies.get(workspace_id)
        return {
            **configured.payload(),
            "enforcement": (
                self.provider.enforcement(instance.instance_id)
                if instance
                else self.sandbox.availability(profile)
            ),
            "events": self.sandbox.events(profile),
            "csp_violations": self.csp_violations.events(workspace_id),
            "restart_required": bool(instance),
        }

    def configure_network(
        self,
        workspace_id: str,
        *,
        mode: str,
        rules: object,
        temporary_rules: object,
        audit_acknowledged: bool,
    ) -> dict[str, object]:
        configured = self.egress_policies.configure(
            workspace_id,
            mode=mode,
            rules=rules,
            temporary_rules=temporary_rules,
            audit_acknowledged=audit_acknowledged,
        )
        if self.manager.status(workspace_id) is None:
            profile = self.manager.profile_for(workspace_id)
            self.sandbox.configure(workspace_id, profile, configured.policy())
        return self.network_status(workspace_id)

    def clear_network_events(self, workspace_id: str) -> dict[str, object]:
        self.sandbox.clear_events(self.manager.profile_for(workspace_id))
        self.csp_violations.clear(workspace_id)
        return self.network_status(workspace_id)

    def proxy_egress_mode(self, workspace_id: str) -> IDEEgressMode:
        return self.egress_policies.get(workspace_id).mode

    def neovim_status(self) -> dict[str, object]:
        return self.neovim.status()

    def configure_neovim(
        self,
        *,
        enabled: bool,
        executable: str = "",
    ) -> dict[str, object]:
        return self.neovim.configure(enabled=enabled, executable=executable)

    def launch_neovim(self, workspace_id: str) -> dict[str, object]:
        profile = self.manager.profile_for(workspace_id)
        status = self.neovim.launch(profile)
        return {
            **status,
            "restart_required": self.manager.status(workspace_id) is not None,
        }

    def editor_context(self, workspace_id: str) -> dict[str, object] | None:
        instance = self.manager.status(workspace_id)
        if instance is None or instance.status is not IDEInstanceStatus.READY:
            return None
        context = self.bridge.context(instance)
        if context is not None:
            self._accept_context(context)
        return context.payload() if context else None

    def record_csp_violation(
        self,
        payload: object,
        workspace_id: str = "",
    ) -> dict[str, object]:
        event = self.csp_violations.record(payload, workspace_id=workspace_id)
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


def _ide_view_path(workspace: IDEWorkspace) -> str:
    query = urlencode({"folder": str(workspace.project_root)})
    return f"/ide/{workspace.workspace_id}/?{query}"


def _ide_data_root() -> Path:
    configured = os.environ.get("ELECTROBOY_IDE_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg_data).expanduser() if xdg_data else Path.home() / ".local/share"
    return (base / "electroboy").resolve()


def _configuration_path(data_root: Path) -> Path:
    return data_root / "ide" / "configuration.json"


def _load_configuration(data_root: Path) -> dict[str, object]:
    try:
        payload = json.loads(_configuration_path(data_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _configuration_payload(configuration: IDEConfiguration) -> dict[str, object]:
    payload = asdict(configuration)
    payload.pop("data_root", None)
    payload["runtime_mode"] = configuration.runtime_mode.value
    payload["system_executable"] = (
        str(configuration.system_executable) if configuration.system_executable else ""
    )
    payload["egress_mode"] = configuration.egress_mode.value
    return payload


def _save_configuration(configuration: IDEConfiguration) -> None:
    path = _configuration_path(configuration.data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    serialized = json.dumps(
        _configuration_payload(configuration),
        indent=2,
        sort_keys=True,
    )
    temporary.write_text(
        serialized + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _bounded_int(
    value: object,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _bounded_float(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number") from error
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return parsed
