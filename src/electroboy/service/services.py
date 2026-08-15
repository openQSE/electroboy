"""Stable service interfaces exposed to workflow and module plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol

from .context import BrowserContext, ContextStore
from .registry import WorkflowRegistry
from .sessions import AgentSession


class ServiceLock(Protocol):
    """Context-manager surface required for synchronized service state."""

    def __enter__(self) -> object: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class ContextServices(Protocol):
    """Browser context and active-project operations available to plugins."""

    @property
    def lock(self) -> ServiceLock: ...

    def require(self, context_id: str) -> BrowserContext: ...

    def require_no_active_agent(self, context: BrowserContext) -> None: ...

    def command_root(self, context: BrowserContext) -> Path | None: ...

    def active_project_root(self, context_id: str) -> Path: ...

    def project_payload(self, context_id: str) -> dict[str, object]: ...


class SessionServices(Protocol):
    """Agent-session lifecycle operations available to plugins."""

    def prepare(
        self,
        context: BrowserContext,
        session: AgentSession,
    ) -> AgentSession: ...

    def for_context(self, context: BrowserContext) -> list[AgentSession]: ...

    def require_locks_available(
        self,
        context: BrowserContext,
        requested_locks: frozenset[str],
    ) -> None: ...

    def terminate(self, sessions: list[AgentSession]) -> bool: ...

    def clear(
        self,
        context: BrowserContext,
        sessions: list[AgentSession],
    ) -> None: ...

    def terminate_workflow(self, context_id: str) -> bool: ...

    def terminate_kind(self, context_id: str, kind: str) -> None: ...


class ProjectFileServices(Protocol):
    """Filesystem roots exposed to plugins without the service runtime."""

    @property
    def service_root(self) -> Path: ...


class WorkflowServices(Protocol):
    """Registered workflow metadata exposed to plugins."""

    @property
    def registry(self) -> WorkflowRegistry: ...


@dataclass(frozen=True)
class ServiceServices:
    """The complete, typed dependency surface passed to plugins."""

    contexts: ContextServices
    sessions: SessionServices
    files: ProjectFileServices
    workflows: WorkflowServices


class ServiceRuntimeBackend(Protocol):
    """Internal runtime surface used only by core service adapters."""

    root: Path
    context_store: ContextStore

    def _context_locked(self, context_id: str) -> BrowserContext: ...

    def _require_no_active_agent_locked(self, context: BrowserContext) -> None: ...

    def _command_root_locked(self, context: BrowserContext) -> Path | None: ...

    def active_project_root(self, context_id: str) -> Path: ...

    def project_payload(self, context_id: str) -> dict[str, object]: ...

    def _prepare_session_locked(
        self,
        context: BrowserContext,
        session: AgentSession,
    ) -> AgentSession: ...

    def _context_sessions_locked(
        self,
        context: BrowserContext,
    ) -> list[AgentSession]: ...

    def _require_session_locks_available_locked(
        self,
        context: BrowserContext,
        requested_locks: frozenset[str],
    ) -> None: ...

    def _terminate_sessions(self, sessions: list[AgentSession]) -> bool: ...

    def _clear_sessions_locked(
        self,
        context: BrowserContext,
        sessions: list[AgentSession],
    ) -> None: ...

    def _terminate_workflow_sessions(self, context_id: str) -> bool: ...

    def _terminate_requirements_session(self, context_id: str) -> None: ...

    def _terminate_design_session(self, context_id: str) -> None: ...


@dataclass(frozen=True)
class RuntimeContextServices:
    runtime: ServiceRuntimeBackend

    @property
    def lock(self) -> ServiceLock:
        return self.runtime.context_store.lock

    def require(self, context_id: str) -> BrowserContext:
        return self.runtime._context_locked(context_id)

    def require_no_active_agent(self, context: BrowserContext) -> None:
        self.runtime._require_no_active_agent_locked(context)

    def command_root(self, context: BrowserContext) -> Path | None:
        return self.runtime._command_root_locked(context)

    def active_project_root(self, context_id: str) -> Path:
        return self.runtime.active_project_root(context_id)

    def project_payload(self, context_id: str) -> dict[str, object]:
        return self.runtime.project_payload(context_id)


@dataclass(frozen=True)
class RuntimeSessionServices:
    runtime: ServiceRuntimeBackend

    def prepare(
        self,
        context: BrowserContext,
        session: AgentSession,
    ) -> AgentSession:
        return self.runtime._prepare_session_locked(context, session)

    def for_context(self, context: BrowserContext) -> list[AgentSession]:
        return self.runtime._context_sessions_locked(context)

    def require_locks_available(
        self,
        context: BrowserContext,
        requested_locks: frozenset[str],
    ) -> None:
        self.runtime._require_session_locks_available_locked(
            context,
            requested_locks,
        )

    def terminate(self, sessions: list[AgentSession]) -> bool:
        return self.runtime._terminate_sessions(sessions)

    def clear(
        self,
        context: BrowserContext,
        sessions: list[AgentSession],
    ) -> None:
        self.runtime._clear_sessions_locked(context, sessions)

    def terminate_workflow(self, context_id: str) -> bool:
        return self.runtime._terminate_workflow_sessions(context_id)

    def terminate_kind(self, context_id: str, kind: str) -> None:
        if kind == "requirements":
            self.runtime._terminate_requirements_session(context_id)
            return
        if kind == "design":
            self.runtime._terminate_design_session(context_id)
            return
        raise ValueError(f"unsupported workflow session kind: {kind}")


@dataclass(frozen=True)
class RuntimeProjectFileServices:
    runtime: ServiceRuntimeBackend

    @property
    def service_root(self) -> Path:
        return self.runtime.root


@dataclass(frozen=True)
class RuntimeWorkflowServices:
    _registry: WorkflowRegistry

    @property
    def registry(self) -> WorkflowRegistry:
        return self._registry


def build_service_services(
    runtime: ServiceRuntimeBackend,
    workflow_registry: WorkflowRegistry,
) -> ServiceServices:
    """Bind the core runtime to the public plugin service interfaces."""

    return ServiceServices(
        contexts=RuntimeContextServices(runtime),
        sessions=RuntimeSessionServices(runtime),
        files=RuntimeProjectFileServices(runtime),
        workflows=RuntimeWorkflowServices(workflow_registry),
    )
