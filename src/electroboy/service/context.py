"""Browser context storage with workflow and module state isolation."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar, cast
from uuid import uuid4

from .sessions import AgentSession


T = TypeVar("T")


@dataclass
class BrowserContext:
    """State for one browser tab or GUI client session."""

    context_id: str
    workflow_id: str = ""
    activation_root: Path | None = None
    project_mode: str = "none"
    active_project_root: Path | None = None
    active_repository_name: str | None = None
    registered_repositories: list[dict[str, object]] = field(default_factory=list)
    selected_session_id: str | None = None
    workflow_state: dict[str, dict[str, object]] = field(default_factory=dict)
    module_state: dict[str, dict[str, object]] = field(default_factory=dict)

    def workflow(self, namespace: str | None = None) -> dict[str, object]:
        """Return mutable state isolated to one workflow namespace."""

        return self.workflow_state.setdefault(namespace or self.workflow_id, {})

    def module(self, namespace: str) -> dict[str, object]:
        """Return mutable state isolated to one module namespace."""

        return self.module_state.setdefault(namespace, {})

    def reset_project(
        self,
        *,
        workflow_id: str,
        project_mode: str,
        activation_root: Path | None,
        active_project_root: Path | None,
        active_repository_name: str | None = None,
        registered_repositories: list[dict[str, object]] | None = None,
        workflow_stage: str | None = None,
    ) -> None:
        """Activate a project and clear state owned by the previous project."""

        self.workflow_id = workflow_id
        self.activation_root = activation_root
        self.project_mode = project_mode
        self.active_project_root = active_project_root
        self.active_repository_name = active_repository_name
        self.registered_repositories = list(registered_repositories or [])
        self.selected_session_id = None
        self.workflow_state.clear()
        self.module_state.clear()
        self.workflow_stage = workflow_stage

    def _value(
        self,
        state: dict[str, object],
        key: str,
        default_factory: Callable[[], T],
    ) -> T:
        if key not in state:
            state[key] = default_factory()
        return cast(T, state[key])

    @property
    def workflow_stage(self) -> str | None:
        return cast(str | None, self.workflow().get("stage"))

    @workflow_stage.setter
    def workflow_stage(self, value: str | None) -> None:
        self.workflow()["stage"] = value

    @property
    def requirements_session(self) -> AgentSession | None:
        return cast(
            AgentSession | None,
            self.workflow("software").get("requirements_session"),
        )

    @requirements_session.setter
    def requirements_session(self, value: AgentSession | None) -> None:
        self.workflow("software")["requirements_session"] = value

    @property
    def design_session(self) -> AgentSession | None:
        return cast(
            AgentSession | None,
            self.workflow("software").get("design_session"),
        )

    @design_session.setter
    def design_session(self, value: AgentSession | None) -> None:
        self.workflow("software")["design_session"] = value

    @property
    def design_review_session(self) -> AgentSession | None:
        return cast(
            AgentSession | None,
            self.workflow("software").get("design_review_session"),
        )

    @design_review_session.setter
    def design_review_session(self, value: AgentSession | None) -> None:
        self.workflow("software")["design_review_session"] = value

    @property
    def documentation_sessions(self) -> dict[str, AgentSession]:
        return self._value(
            self.module("markdown_documents"),
            "sessions",
            dict,
        )

    @documentation_sessions.setter
    def documentation_sessions(self, value: dict[str, AgentSession]) -> None:
        self.module("markdown_documents")["sessions"] = value

    @property
    def creative_sessions(self) -> dict[str, AgentSession]:
        state = self.workflow("creative-writing")
        sessions = self._value(state, "sessions", dict)
        legacy = state.pop("session", None)
        if legacy is not None:
            session_id = str(getattr(legacy, "session_id", "__general__"))
            sessions.setdefault(session_id, legacy)
        return sessions

    @creative_sessions.setter
    def creative_sessions(self, value: dict[str, AgentSession]) -> None:
        self.workflow("creative-writing")["sessions"] = value

    @property
    def creative_session(self) -> AgentSession | None:
        for session in self.creative_sessions.values():
            metadata = getattr(session, "metadata", {}) or {}
            if str(metadata.get("creative_scope") or "general") != "document":
                return session
        return None

    @creative_session.setter
    def creative_session(self, value: AgentSession | None) -> None:
        sessions = self.creative_sessions
        for session_id, session in list(sessions.items()):
            metadata = getattr(session, "metadata", {}) or {}
            if str(metadata.get("creative_scope") or "general") != "document":
                sessions.pop(session_id, None)
        if value is not None:
            session_id = str(getattr(value, "session_id", "__general__"))
            sessions[session_id] = value

    @property
    def ad_hoc_session(self) -> AgentSession | None:
        return cast(
            AgentSession | None,
            self.module("agent_sessions").get("ad_hoc_session"),
        )

    @ad_hoc_session.setter
    def ad_hoc_session(self, value: AgentSession | None) -> None:
        self.module("agent_sessions")["ad_hoc_session"] = value

    @property
    def project_shell_session(self) -> AgentSession | None:
        sessions = self.project_shell_sessions
        return next(reversed(sessions.values()), None)

    @project_shell_session.setter
    def project_shell_session(self, value: AgentSession | None) -> None:
        sessions = self.project_shell_sessions
        sessions.clear()
        if value is not None:
            session_id = str(getattr(value, "session_id", "__legacy__"))
            sessions[session_id] = value

    @property
    def project_shell_sessions(self) -> dict[str, AgentSession]:
        return self._value(self.module("project_shell"), "sessions", dict)

    @project_shell_sessions.setter
    def project_shell_sessions(self, value: dict[str, AgentSession]) -> None:
        self.module("project_shell")["sessions"] = value

    @property
    def stage_sessions(self) -> dict[str, AgentSession]:
        return self._value(self.workflow("software"), "stage_sessions", dict)

    @stage_sessions.setter
    def stage_sessions(self, value: dict[str, AgentSession]) -> None:
        self.workflow("software")["stage_sessions"] = value

    @property
    def requirements_started(self) -> bool:
        return bool(self.workflow("software").get("requirements_started", False))

    @requirements_started.setter
    def requirements_started(self, value: bool) -> None:
        self.workflow("software")["requirements_started"] = bool(value)

    @property
    def design_started(self) -> bool:
        return bool(self.workflow("software").get("design_started", False))

    @design_started.setter
    def design_started(self, value: bool) -> None:
        self.workflow("software")["design_started"] = bool(value)

    @property
    def design_review_started(self) -> bool:
        return bool(self.workflow("software").get("design_review_started", False))

    @design_review_started.setter
    def design_review_started(self, value: bool) -> None:
        self.workflow("software")["design_review_started"] = bool(value)

    @property
    def design_review_interactive(self) -> bool:
        return bool(
            self.workflow("software").get("design_review_interactive", False)
        )

    @design_review_interactive.setter
    def design_review_interactive(self, value: bool) -> None:
        self.workflow("software")["design_review_interactive"] = bool(value)

    @property
    def stage_started(self) -> set[str]:
        return self._value(self.workflow("software"), "stage_started", set)

    @stage_started.setter
    def stage_started(self, value: set[str]) -> None:
        self.workflow("software")["stage_started"] = value


@dataclass
class ContextStore:
    """Thread-safe owner of browser contexts."""

    lock: threading.RLock = field(default_factory=threading.RLock)
    contexts: dict[str, BrowserContext] = field(default_factory=dict)

    def create(
        self,
        context_id: str | None = None,
        workflow_id: str = "",
    ) -> BrowserContext:
        context = BrowserContext(
            context_id=context_id or uuid4().hex,
            workflow_id=workflow_id,
        )
        with self.lock:
            self.contexts[context.context_id] = context
        return context

    def get(self, context_id: str) -> BrowserContext | None:
        with self.lock:
            return self.contexts.get(context_id)

    def require(self, context_id: str) -> BrowserContext:
        context = self.contexts.get(context_id)
        if context is None:
            raise KeyError(context_id)
        return context

    def get_or_create(
        self,
        context_id: str,
        workflow_id: str = "",
    ) -> BrowserContext:
        with self.lock:
            return self.contexts.setdefault(
                context_id,
                BrowserContext(context_id=context_id, workflow_id=workflow_id),
            )
