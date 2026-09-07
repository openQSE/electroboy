"""Provider-neutral values used by the IDE service boundary."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any


class IDERuntimeOrigin(str, Enum):
    """How an IDE runtime became available to ElectroBoy."""

    MANAGED = "managed"
    SYSTEM = "system"


class IDERuntimeMode(str, Enum):
    """Operator-selected runtime resolution behavior."""

    AUTO = "auto"
    MANAGED = "managed"
    SYSTEM = "system"
    DISABLED = "disabled"


class IDEInstanceStatus(str, Enum):
    """Lifecycle state of one workspace-owned IDE provider process."""

    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class IDEErrorCategory(str, Enum):
    """Stable error categories shared by providers and service clients."""

    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"
    RUNTIME_MISSING = "runtime_missing"
    RUNTIME_INCOMPATIBLE = "runtime_incompatible"
    INSTALLATION_FAILED = "installation_failed"
    START_FAILED = "start_failed"
    READINESS_TIMEOUT = "readiness_timeout"
    WORKSPACE_CONFLICT = "workspace_conflict"
    INSTANCE_LIMIT = "instance_limit"
    NOT_READY = "not_ready"
    NAVIGATION_FAILED = "navigation_failed"
    POLICY_UNAVAILABLE = "policy_unavailable"
    INTERNAL = "internal"


class IDEError(RuntimeError):
    """An IDE failure with a provider-neutral category and recovery hint."""

    def __init__(
        self,
        category: IDEErrorCategory,
        message: str,
        *,
        recoverable: bool = False,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.recoverable = recoverable

    def payload(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "message": str(self),
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True)
class IDERuntime:
    """A resolved executable distribution for one IDE provider."""

    provider: str
    version: str
    platform: str
    architecture: str
    executable: Path
    origin: IDERuntimeOrigin

    def payload(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "version": self.version,
            "platform": self.platform,
            "architecture": self.architecture,
            "executable": str(self.executable),
            "origin": self.origin.value,
        }


@dataclass(frozen=True)
class IDEEndpoint:
    """Private provider endpoint; public payloads never expose its credential."""

    transport: str
    address: str
    connection_token: str = field(repr=False, compare=False)

    def public_payload(self) -> dict[str, str]:
        return {
            "transport": self.transport,
            "address": self.address,
            "authentication": "managed",
        }


@dataclass(frozen=True)
class IDEWorkspace:
    """Workspace identity and the active repository assigned to an IDE."""

    workspace_id: str
    project_root: Path


@dataclass(frozen=True)
class IDEProfile:
    """Provider data locations isolated to one ElectroBoy workspace."""

    root: Path
    user_data: Path
    extensions: Path
    server_data: Path
    logs: Path


@dataclass(frozen=True)
class IDEInstance:
    """Provider process state owned by one ElectroBoy workspace."""

    instance_id: str
    provider: str
    workspace: IDEWorkspace
    runtime: IDERuntime
    profile: IDEProfile
    status: IDEInstanceStatus
    endpoint: IDEEndpoint | None = field(default=None, repr=False)
    process_id: int | None = None
    started_at: float | None = None
    ready_at: float | None = None
    stopped_at: float | None = None
    failure: str | None = None

    def with_status(self, status: IDEInstanceStatus, **changes: Any) -> IDEInstance:
        return replace(self, status=status, **changes)

    def public_payload(self) -> dict[str, object]:
        return {
            "instance_id": self.instance_id,
            "provider": self.provider,
            "workspace_id": self.workspace.workspace_id,
            "project_root": str(self.workspace.project_root),
            "runtime": self.runtime.payload(),
            "status": self.status.value,
            "endpoint": self.endpoint.public_payload() if self.endpoint else None,
            "process_id": self.process_id,
            "started_at": self.started_at,
            "ready_at": self.ready_at,
            "stopped_at": self.stopped_at,
            "failure": self.failure,
        }


@dataclass(frozen=True)
class IDELocation:
    """A provider-neutral repository location to reveal in the editor."""

    path: str
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    symbol: str | None = None

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("IDE location path is required")
        for name in ("line", "column", "end_line", "end_column"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"IDE location {name} must be positive")


@dataclass(frozen=True)
class IDEEditorContext:
    """Current editor state reported by the provider bridge."""

    workspace_id: str
    path: str | None = None
    language: str | None = None
    cursor_line: int | None = None
    cursor_column: int | None = None
    selection_start_line: int | None = None
    selection_start_column: int | None = None
    selection_end_line: int | None = None
    selection_end_column: int | None = None
    dirty: bool = False
    revision: int = 0

    def payload(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "path": self.path,
            "language": self.language,
            "cursor": _position(self.cursor_line, self.cursor_column),
            "selection": {
                "start": _position(
                    self.selection_start_line,
                    self.selection_start_column,
                ),
                "end": _position(self.selection_end_line, self.selection_end_column),
            },
            "dirty": self.dirty,
            "revision": self.revision,
        }


def _position(line: int | None, column: int | None) -> dict[str, int] | None:
    if line is None or column is None:
        return None
    return {"line": line, "column": column}
