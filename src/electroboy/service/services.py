"""Stable service interfaces exposed to workflow and module plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol, TypeVar

from .context import BrowserContext, ContextStore
from .registry import WorkflowRegistry
from .sessions import AgentSession

ControllerT = TypeVar("ControllerT")


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

    def create(self) -> dict[str, object]: ...

    def project_mode(self, context_id: str) -> str: ...

    def project_status_payload(self, context_id: str) -> dict[str, object]: ...

    def workflow_payload(self, context_id: str) -> dict[str, object]: ...

    def deactivate_project(self, context_id: str) -> dict[str, object]: ...

    def requirements_document_root(self, context_id: str) -> Path: ...

    def command_root_for(self, context_id: str) -> Path: ...


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

    def payload(self, context_id: str) -> dict[str, object]: ...

    def registry_payload(self) -> dict[str, object]: ...

    def selected(self, context_id: str) -> AgentSession | None: ...

    def by_id(self, context_id: str, session_id: str) -> AgentSession: ...

    def current(self, context_id: str, kind: str) -> AgentSession | None: ...

    def attach(self, context_id: str, session_id: str) -> dict[str, object]: ...

    def send_message(
        self,
        context_id: str,
        session_id: str,
        message: str,
    ) -> None: ...

    def send_selected_message(self, context_id: str, message: str) -> None: ...

    def send_selected_key(self, context_id: str, key: str) -> None: ...

    def send_selected_raw(self, context_id: str, data: str) -> None: ...

    def interrupt_selected(self, context_id: str) -> None: ...

    def interrupt_kind(self, context_id: str, kind: str) -> None: ...

    def resize_selected(self, context_id: str, columns: int, rows: int) -> None: ...

    def resize(
        self,
        context_id: str,
        session_id: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def resize_kind(
        self,
        context_id: str,
        kind: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def start_project_shell(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]: ...

    def send_project_shell_input(self, context_id: str, data: str) -> None: ...

    def resize_project_shell(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def stop_project_shell(self, context_id: str) -> dict[str, object]: ...

    def start_ad_hoc(self, context_id: str) -> tuple[AgentSession, bool]: ...


class ProjectFileServices(Protocol):
    """Filesystem roots exposed to plugins without the service runtime."""

    @property
    def service_root(self) -> Path: ...


class WorkflowServices(Protocol):
    """Registered workflow metadata exposed to plugins."""

    @property
    def registry(self) -> WorkflowRegistry: ...

    def controller(
        self,
        workflow_id: str,
        expected_type: type[ControllerT],
    ) -> ControllerT: ...

    def select_stage(
        self,
        context_id: str,
        stage: str,
    ) -> dict[str, object]: ...

    def bind_registry(self, registry: WorkflowRegistry) -> None: ...


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

    def create_context(self) -> dict[str, object]: ...

    def project_mode(self, context_id: str) -> str: ...

    def project_status_payload(self, context_id: str) -> dict[str, object]: ...

    def workflow_payload(self, context_id: str) -> dict[str, object]: ...

    def deactivate_project(self, context_id: str) -> dict[str, object]: ...

    def requirements_document_root(self, context_id: str) -> Path: ...

    def command_root(self, context_id: str) -> Path: ...

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

    def session_payload(self, context_id: str) -> dict[str, object]: ...

    def session_registry_payload(self) -> dict[str, object]: ...

    def selected_session(self, context_id: str) -> AgentSession | None: ...

    def session_by_id(self, context_id: str, session_id: str) -> AgentSession: ...

    def attach_session(
        self,
        context_id: str,
        session_id: str,
    ) -> dict[str, object]: ...

    def send_session_message(
        self,
        context_id: str,
        session_id: str,
        message: str,
    ) -> None: ...

    def send_selected_session_message(
        self,
        context_id: str,
        message: str,
    ) -> None: ...

    def send_selected_session_key(self, context_id: str, key: str) -> None: ...

    def send_selected_session_raw(self, context_id: str, data: str) -> None: ...

    def interrupt_selected_session(self, context_id: str) -> None: ...

    def resize_selected_session(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def resize_session(
        self,
        context_id: str,
        session_id: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def current_requirements_session(
        self,
        context_id: str,
    ) -> AgentSession | None: ...

    def current_design_session(self, context_id: str) -> AgentSession | None: ...

    def current_design_review_session(
        self,
        context_id: str,
    ) -> AgentSession | None: ...

    def current_documentation_session(
        self,
        context_id: str,
    ) -> AgentSession | None: ...

    def current_project_shell_session(
        self,
        context_id: str,
    ) -> AgentSession | None: ...

    def interrupt_requirements_agent(self, context_id: str) -> None: ...

    def interrupt_design_agent(self, context_id: str) -> None: ...

    def interrupt_design_review_agent(self, context_id: str) -> None: ...

    def resize_requirements_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def resize_design_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def resize_design_review_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def start_project_shell(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]: ...

    def send_project_shell_input(self, context_id: str, data: str) -> None: ...

    def resize_project_shell(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None: ...

    def stop_project_shell(self, context_id: str) -> dict[str, object]: ...

    def start_ad_hoc_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]: ...

    def workflow_controller(self, workflow_id: str) -> object: ...

    def select_workflow_stage(
        self,
        context_id: str,
        stage: str,
    ) -> dict[str, object]: ...

    def bind_workflow_registry(self, registry: WorkflowRegistry) -> None: ...


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

    def create(self) -> dict[str, object]:
        return self.runtime.create_context()

    def project_mode(self, context_id: str) -> str:
        return self.runtime.project_mode(context_id)

    def project_status_payload(self, context_id: str) -> dict[str, object]:
        return self.runtime.project_status_payload(context_id)

    def workflow_payload(self, context_id: str) -> dict[str, object]:
        return self.runtime.workflow_payload(context_id)

    def deactivate_project(self, context_id: str) -> dict[str, object]:
        return self.runtime.deactivate_project(context_id)

    def requirements_document_root(self, context_id: str) -> Path:
        return self.runtime.requirements_document_root(context_id)

    def command_root_for(self, context_id: str) -> Path:
        return self.runtime.command_root(context_id)


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

    def payload(self, context_id: str) -> dict[str, object]:
        return self.runtime.session_payload(context_id)

    def registry_payload(self) -> dict[str, object]:
        return self.runtime.session_registry_payload()

    def selected(self, context_id: str) -> AgentSession | None:
        return self.runtime.selected_session(context_id)

    def by_id(self, context_id: str, session_id: str) -> AgentSession:
        return self.runtime.session_by_id(context_id, session_id)

    def current(self, context_id: str, kind: str) -> AgentSession | None:
        methods = {
            "requirements": self.runtime.current_requirements_session,
            "design": self.runtime.current_design_session,
            "design-review": self.runtime.current_design_review_session,
            "documentation": self.runtime.current_documentation_session,
            "project-shell": self.runtime.current_project_shell_session,
        }
        try:
            method = methods[kind]
        except KeyError as error:
            raise ValueError(f"unsupported session kind: {kind}") from error
        return method(context_id)

    def attach(self, context_id: str, session_id: str) -> dict[str, object]:
        return self.runtime.attach_session(context_id, session_id)

    def send_message(
        self,
        context_id: str,
        session_id: str,
        message: str,
    ) -> None:
        self.runtime.send_session_message(context_id, session_id, message)

    def send_selected_message(self, context_id: str, message: str) -> None:
        self.runtime.send_selected_session_message(context_id, message)

    def send_selected_key(self, context_id: str, key: str) -> None:
        self.runtime.send_selected_session_key(context_id, key)

    def send_selected_raw(self, context_id: str, data: str) -> None:
        self.runtime.send_selected_session_raw(context_id, data)

    def interrupt_selected(self, context_id: str) -> None:
        self.runtime.interrupt_selected_session(context_id)

    def interrupt_kind(self, context_id: str, kind: str) -> None:
        methods = {
            "requirements": self.runtime.interrupt_requirements_agent,
            "design": self.runtime.interrupt_design_agent,
            "design-review": self.runtime.interrupt_design_review_agent,
        }
        try:
            method = methods[kind]
        except KeyError as error:
            raise ValueError(
                f"unsupported interrupt session kind: {kind}"
            ) from error
        method(context_id)

    def resize_selected(self, context_id: str, columns: int, rows: int) -> None:
        self.runtime.resize_selected_session(context_id, columns, rows)

    def resize(
        self,
        context_id: str,
        session_id: str,
        columns: int,
        rows: int,
    ) -> None:
        self.runtime.resize_session(context_id, session_id, columns, rows)

    def resize_kind(
        self,
        context_id: str,
        kind: str,
        columns: int,
        rows: int,
    ) -> None:
        methods = {
            "requirements": self.runtime.resize_requirements_agent,
            "design": self.runtime.resize_design_agent,
            "design-review": self.runtime.resize_design_review_agent,
        }
        try:
            method = methods[kind]
        except KeyError as error:
            raise ValueError(
                f"unsupported resize session kind: {kind}"
            ) from error
        method(context_id, columns, rows)

    def start_project_shell(self, context_id: str) -> tuple[AgentSession, bool]:
        return self.runtime.start_project_shell(context_id)

    def send_project_shell_input(self, context_id: str, data: str) -> None:
        self.runtime.send_project_shell_input(context_id, data)

    def resize_project_shell(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        self.runtime.resize_project_shell(context_id, columns, rows)

    def stop_project_shell(self, context_id: str) -> dict[str, object]:
        return self.runtime.stop_project_shell(context_id)

    def start_ad_hoc(self, context_id: str) -> tuple[AgentSession, bool]:
        return self.runtime.start_ad_hoc_agent(context_id)


@dataclass(frozen=True)
class RuntimeProjectFileServices:
    runtime: ServiceRuntimeBackend

    @property
    def service_root(self) -> Path:
        return self.runtime.root


@dataclass
class RuntimeWorkflowServices:
    runtime: ServiceRuntimeBackend
    _registry: WorkflowRegistry

    @property
    def registry(self) -> WorkflowRegistry:
        return self._registry

    def controller(
        self,
        workflow_id: str,
        expected_type: type[ControllerT],
    ) -> ControllerT:
        controller = self.runtime.workflow_controller(workflow_id)
        if not isinstance(controller, expected_type):
            raise TypeError(
                f"workflow controller has unexpected type: {workflow_id}"
            )
        return controller

    def select_stage(
        self,
        context_id: str,
        stage: str,
    ) -> dict[str, object]:
        return self.runtime.select_workflow_stage(context_id, stage)

    def bind_registry(self, registry: WorkflowRegistry) -> None:
        self.runtime.bind_workflow_registry(registry)
        self._registry = registry


def build_service_services(
    runtime: ServiceRuntimeBackend,
    workflow_registry: WorkflowRegistry,
) -> ServiceServices:
    """Bind the core runtime to the public plugin service interfaces."""

    return ServiceServices(
        contexts=RuntimeContextServices(runtime),
        sessions=RuntimeSessionServices(runtime),
        files=RuntimeProjectFileServices(runtime),
        workflows=RuntimeWorkflowServices(runtime, workflow_registry),
    )
