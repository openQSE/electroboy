"""Workspace-scoped IDE instance lifecycle management."""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from .contracts import IDEProvider, RuntimeInstaller, RuntimeResolver
from .domain import (
    IDEError,
    IDEErrorCategory,
    IDEInstance,
    IDEInstanceStatus,
    IDEProfile,
    IDERuntimeMode,
    IDEWorkspace,
)
from .ownership import IDEInstanceRegistry


class IDEInstanceManager:
    """Own one supervised provider instance per ElectroBoy workspace."""

    def __init__(
        self,
        provider: IDEProvider,
        resolver: RuntimeResolver,
        installer: RuntimeInstaller,
        data_root: Path,
        *,
        maximum_instances: int = 2,
        idle_timeout: float = 900,
        startup_timeout: float = 30,
    ) -> None:
        self.provider = provider
        self.resolver = resolver
        self.installer = installer
        self.data_root = data_root.expanduser().resolve()
        self.maximum_instances = max(1, maximum_instances)
        self.idle_timeout = max(0, idle_timeout)
        self.startup_timeout = max(0.1, startup_timeout)
        self.registry = IDEInstanceRegistry()
        self._last_used: dict[str, float] = {}
        self._workspace_locks: dict[str, threading.Lock] = {}
        self._lock = threading.RLock()

    def start(
        self,
        workspace: IDEWorkspace,
        *,
        mode: IDERuntimeMode = IDERuntimeMode.MANAGED,
        system_executable: Path | None = None,
    ) -> tuple[IDEInstance, bool]:
        lock = self._workspace_lock(workspace.workspace_id)
        with lock:
            current = self.registry.get(workspace.workspace_id)
            if current is not None:
                if current.workspace.project_root == workspace.project_root:
                    status = self.provider.status(current)
                    if status in (
                        IDEInstanceStatus.STARTING,
                        IDEInstanceStatus.READY,
                    ):
                        self.touch(workspace.workspace_id)
                        if status is not current.status:
                            current = current.with_status(status)
                            self.registry.update(current)
                        return current, False
                self.stop(workspace.workspace_id, "active project changed")
            self.cleanup_idle()
            if len(self.registry.values()) >= self.maximum_instances:
                raise IDEError(
                    IDEErrorCategory.INSTANCE_LIMIT,
                    f"maximum live IDE instance count is {self.maximum_instances}",
                    recoverable=True,
                )
            try:
                runtime = self.resolver.resolve(
                    mode,
                    system_executable=system_executable,
                )
            except IDEError as error:
                if (
                    mode in (IDERuntimeMode.AUTO, IDERuntimeMode.MANAGED)
                    and error.category is IDEErrorCategory.RUNTIME_MISSING
                ):
                    runtime = self.installer.install()
                else:
                    raise
            if runtime is None:
                raise IDEError(
                    IDEErrorCategory.DISABLED,
                    "IDE runtime is disabled",
                )
            instance = self.provider.start(
                workspace,
                runtime,
                self.profile_for(workspace.workspace_id),
            )
            self.registry.claim(instance)
            try:
                ready = self.provider.wait_until_ready(
                    instance,
                    self.startup_timeout,
                )
            except Exception:
                self.registry.release(workspace.workspace_id, instance.instance_id)
                raise
            self.registry.update(ready)
            self.touch(workspace.workspace_id)
            return ready, True

    def status(self, workspace_id: str) -> IDEInstance | None:
        instance = self.registry.get(workspace_id)
        if instance is None:
            return None
        status = self.provider.status(instance)
        if status is not instance.status:
            instance = instance.with_status(status)
            self.registry.update(instance)
        return instance

    def touch(self, workspace_id: str) -> None:
        with self._lock:
            self._last_used[workspace_id] = time.monotonic()

    def stop(self, workspace_id: str, reason: str = "requested") -> IDEInstance | None:
        instance = self.registry.get(workspace_id)
        if instance is None:
            return None
        stopped = self.provider.stop(instance, reason)
        self.registry.release(workspace_id, instance.instance_id)
        with self._lock:
            self._last_used.pop(workspace_id, None)
        return stopped

    def cleanup_idle(self, *, now: float | None = None) -> list[str]:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            expired = [
                workspace_id
                for workspace_id, last_used in self._last_used.items()
                if current_time - last_used >= self.idle_timeout
            ]
        for workspace_id in expired:
            self.stop(workspace_id, "idle timeout")
        return expired

    def stop_all(self, reason: str = "service shutdown") -> None:
        for instance in self.registry.values():
            self.stop(instance.workspace.workspace_id, reason)

    def profile_for(self, workspace_id: str) -> IDEProfile:
        identity = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:20]
        root = self.data_root / "ide" / "workspaces" / identity
        return IDEProfile(
            root=root,
            user_data=root / "user-data",
            extensions=root / "extensions",
            server_data=root / "server-data",
            logs=root / "logs",
        )

    def _workspace_lock(self, workspace_id: str) -> threading.Lock:
        with self._lock:
            return self._workspace_locks.setdefault(workspace_id, threading.Lock())
