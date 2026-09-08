"""Workspace ownership guard for IDE instances."""

from __future__ import annotations

from threading import RLock

from .domain import IDEError, IDEErrorCategory, IDEInstance


class IDEInstanceRegistry:
    """Store at most one provider instance for each ElectroBoy workspace."""

    def __init__(self) -> None:
        self._instances: dict[str, IDEInstance] = {}
        self._lock = RLock()

    def get(self, workspace_id: str) -> IDEInstance | None:
        with self._lock:
            return self._instances.get(workspace_id)

    def claim(self, instance: IDEInstance) -> IDEInstance:
        workspace_id = instance.workspace.workspace_id
        with self._lock:
            current = self._instances.get(workspace_id)
            if current is not None and current.instance_id != instance.instance_id:
                raise IDEError(
                    IDEErrorCategory.WORKSPACE_CONFLICT,
                    f"workspace {workspace_id} already owns an IDE instance",
                    recoverable=True,
                )
            self._instances[workspace_id] = instance
            return instance

    def update(self, instance: IDEInstance) -> IDEInstance:
        workspace_id = instance.workspace.workspace_id
        with self._lock:
            current = self._instances.get(workspace_id)
            if current is None or current.instance_id != instance.instance_id:
                raise IDEError(
                    IDEErrorCategory.WORKSPACE_CONFLICT,
                    f"IDE instance does not own workspace {workspace_id}",
                )
            self._instances[workspace_id] = instance
            return instance

    def release(self, workspace_id: str, instance_id: str) -> IDEInstance | None:
        with self._lock:
            current = self._instances.get(workspace_id)
            if current is None:
                return None
            if current.instance_id != instance_id:
                raise IDEError(
                    IDEErrorCategory.WORKSPACE_CONFLICT,
                    f"IDE instance does not own workspace {workspace_id}",
                )
            return self._instances.pop(workspace_id)

    def values(self) -> tuple[IDEInstance, ...]:
        with self._lock:
            return tuple(self._instances.values())
