"""Local browser service for ElectroBoy."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from ..artifacts import ArtifactManager
from ..models import (
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_REQUIREMENTS,
    utc_now,
)
from ..state_store import StateError, StateStore
from .frontend import (
    SERVICE_STATIC_ROUTE_PREFIX,
    frontend_asset_payload,
    read_service_binary_asset,
    read_service_text_asset,
    render_service_index,
    service_asset_content_type,
)
from .file_watch import file_signature as _file_signature
from .recent_projects import (
    recent_project_entries as _recent_project_entries,
)
from .recent_projects import (
    remember_recent_project as _remember_recent_project,
)
from .registry import (
    ModuleRegistry,
    WorkflowRegistry,
    build_module_registry,
    build_workflow_registry,
    installed_workflow_factories,
)
from .routes import RouteRequest, build_route_dispatcher
from .sessions import (
    SESSION_BACKEND_PTY,
    SESSION_BACKEND_TMUX,
    AgentSession,
    AgentSessionError,
    TmuxAgentSession,
    _agent_process_env,
    _normalize_session_backend,
    _session_backend_from_env,
    _subprocess_output_text,
    _tmux_has_session,
)
from .workflow_config import (
    configured_workflows,
    workflow_config_payload,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SPLASH_IMAGE_ROUTE = "/assets/electroboy-splash-16x9.png"
CREATIVE_SPLASH_IMAGE_ROUTE = "/assets/electroboy-splash-creative-writing-16x9.png"
SPLASH_IMAGE_PACKAGE = "electroboy"
SPLASH_IMAGE_RESOURCE = "electroboy-splash-16x9.png"
CREATIVE_SPLASH_IMAGE_RESOURCE = "electroboy-splash-creative-writing-16x9.png"
META_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "repositories.json"
SERVICE_SESSION_RECORDS_RELATIVE_PATH = (
    Path(".electroboy") / "service" / "sessions.json"
)
SERVICE_SESSION_TRANSCRIPTS_RELATIVE_DIR = (
    Path(".electroboy") / "service" / "session-transcripts"
)


def _software_domain() -> Any:
    """Load the optional software workflow only when its behavior is needed."""

    return import_module("electroboy.workflows.software.domain")


INDEX_HTML_TEMPLATE = read_service_text_asset("index.html")


def _render_service_text_asset(name: str) -> str:
    return _apply_service_asset_replacements(read_service_text_asset(name))


def _apply_service_asset_replacements(text: str) -> str:
    return (
        text.replace("__SPLASH_IMAGE_ROUTE__", SPLASH_IMAGE_ROUTE)
        .replace("__CREATIVE_SPLASH_IMAGE_ROUTE__", CREATIVE_SPLASH_IMAGE_ROUTE)
    )


def _optional_service_text_asset(name: str) -> str:
    try:
        return read_service_text_asset(name)
    except FileNotFoundError:
        return ""


INDEX_PAGE_HTML = _apply_service_asset_replacements(
    render_service_index(INDEX_HTML_TEMPLATE)
)
INDEX_HTML = "\n".join(
    [
        INDEX_PAGE_HTML,
        read_service_text_asset("css/shell.css"),
        read_service_text_asset("js/core/registry.js"),
        _optional_service_text_asset("js/modules/agent-sessions.js"),
        _optional_service_text_asset("js/modules/documents.js"),
        _optional_service_text_asset("js/modules/binder.js"),
        _optional_service_text_asset("js/modules/corkboard.js"),
        _optional_service_text_asset("js/modules/file-browser.js"),
        _optional_service_text_asset("js/modules/progress.js"),
        _optional_service_text_asset("js/modules/project-shell.js"),
        _optional_service_text_asset("js/workflows/software.js"),
        _optional_service_text_asset("js/workflows/creative-writing.js"),
        _render_service_text_asset("js/core/runtime.js"),
    ]
)

PANE_WINDOW_HTML = read_service_text_asset("pane-window.html")


def pane_window_html(kind: str) -> str:
    return PANE_WINDOW_HTML.replace("__PANE_KIND__", json.dumps(kind))


FILE_BROWSER_WINDOW_HTML = read_service_text_asset("file-browser.html")


def file_browser_window_html(initial_path: str, mode: str = "project") -> str:
    select_mode = (
        mode
        if mode in {"link", "document", "document-new", "project-new"}
        else "project"
    )
    return (
        FILE_BROWSER_WINDOW_HTML.replace(
            "__INITIAL_PATH__",
            json.dumps(initial_path),
        )
        .replace("__SELECT_MODE__", json.dumps(select_mode))
    )


@dataclass
class BrowserContext:
    context_id: str
    activation_root: Path | None = None
    project_mode: str = "none"
    active_project_root: Path | None = None
    active_repository_name: str | None = None
    registered_repositories: list[dict[str, object]] = field(default_factory=list)
    requirements_session: AgentSession | None = None
    design_session: AgentSession | None = None
    design_review_session: AgentSession | None = None
    documentation_sessions: dict[str, AgentSession] = field(default_factory=dict)
    creative_session: AgentSession | None = None
    ad_hoc_session: AgentSession | None = None
    project_shell_session: AgentSession | None = None
    stage_sessions: dict[str, AgentSession] = field(default_factory=dict)
    selected_session_id: str | None = None
    workflow_stage: str | None = None
    requirements_started: bool = False
    design_started: bool = False
    design_review_started: bool = False
    design_review_interactive: bool = False
    stage_started: set[str] = field(default_factory=set)


@dataclass
class ServiceState:
    root: Path
    session_backend: str = SESSION_BACKEND_PTY
    workflow_registry: WorkflowRegistry | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    contexts: dict[str, BrowserContext] = field(default_factory=dict)
    workflow_controllers: dict[str, Any] = field(
        init=False,
        default_factory=dict,
    )

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.session_backend = _normalize_session_backend(self.session_backend)
        if self.workflow_registry is None:
            module_registry = build_module_registry()
            self.workflow_registry = build_workflow_registry(module_registry)
        self.bind_workflow_registry(self.workflow_registry)
        (self.root / SERVICE_SESSION_TRANSCRIPTS_RELATIVE_DIR).mkdir(
            parents=True,
            exist_ok=True,
        )
        if self.session_backend == SESSION_BACKEND_TMUX:
            self._restore_tmux_sessions()

    def workflow_controller(self, workflow_id: str) -> Any:
        """Return executable behavior for an enabled workflow."""
        try:
            return self.workflow_controllers[workflow_id]
        except KeyError as error:
            raise StateError(
                f"workflow has no executable controller: {workflow_id}"
            ) from error

    def bind_workflow_registry(self, registry: WorkflowRegistry) -> None:
        """Replace workflow definitions and their bound controllers together."""
        controllers = registry.create_controllers(self)
        with self.lock:
            self.workflow_registry = registry
            self.workflow_controllers = controllers

    def _prepare_session_locked(
        self,
        context: BrowserContext,
        session: AgentSession,
    ) -> AgentSession:
        if self.session_backend == SESSION_BACKEND_TMUX and not isinstance(
            session,
            TmuxAgentSession,
        ):
            session = TmuxAgentSession.from_agent_session(session)
        session.persist_to(
            context_id=context.context_id,
            transcript_path=_service_session_transcript_path(
                self.root,
                session.session_id,
            ),
            on_status_changed=self._record_session_status,
        )
        _upsert_service_session_record(
            self.root,
            _service_session_record(self.root, context, session),
        )
        return session

    def _record_session_status(self, session: AgentSession) -> None:
        with self.lock:
            context = self.contexts.get(str(session.context_id or ""))
            if context is None:
                return
            _upsert_service_session_record(
                self.root,
                _service_session_record(self.root, context, session),
            )

    def _restore_tmux_sessions(self) -> None:
        if shutil.which("tmux") is None:
            return
        records = _load_service_session_records(self.root)
        restored_sessions: list[TmuxAgentSession] = []
        with self.lock:
            for entry in records.get("sessions", []):
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("backend") or "") != SESSION_BACKEND_TMUX:
                    continue
                session_id = str(entry.get("session_id") or "").strip()
                tmux_name = str(entry.get("tmux_session") or "").strip()
                if not session_id or not tmux_name or not _tmux_has_session(tmux_name):
                    continue
                context_id = str(entry.get("context_id") or "").strip() or uuid4().hex
                context = self.contexts.setdefault(
                    context_id,
                    BrowserContext(context_id=context_id),
                )
                activation_root = str(entry.get("activation_root") or "").strip()
                active_root = str(entry.get("active_project_root") or "").strip()
                context.activation_root = Path(activation_root) if activation_root else None
                context.active_project_root = Path(active_root) if active_root else None
                context.project_mode = str(entry.get("project_mode") or "project")
                context.active_repository_name = (
                    str(entry.get("active_repository_name"))
                    if entry.get("active_repository_name")
                    else None
                )
                command = [
                    str(item)
                    for item in entry.get("command", [])
                    if isinstance(item, str)
                ]
                if not command:
                    continue
                cwd = str(entry.get("cwd") or active_root or self.root)
                session = TmuxAgentSession(
                    command=command,
                    cwd=Path(cwd),
                    session_id=session_id,
                    label=str(entry.get("label") or "agent"),
                    kind=str(entry.get("kind") or "agent"),
                    interactive=bool(entry.get("interactive", True)),
                    metadata=(
                        entry.get("metadata")
                        if isinstance(entry.get("metadata"), dict)
                        else None
                    ),
                    tmux_name=tmux_name,
                )
                session.persist_to(
                    context_id=context.context_id,
                    transcript_path=_service_session_transcript_path(
                        self.root,
                        session.session_id,
                    ),
                )
                self._attach_session_locked(context, session)
                if session.kind != "project-shell":
                    context.selected_session_id = session.session_id
                restored_sessions.append(session)
        for session in restored_sessions:
            session.on_status_changed = self._record_session_status
            session.attach_existing()

    def create_context(self) -> dict[str, object]:
        context = BrowserContext(context_id=uuid4().hex)
        with self.lock:
            self.contexts[context.context_id] = context
        return {
            **project_payload(self.root, context),
            "status": "created",
        }

    def project_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            active_project_root = context.active_project_root
        return project_payload(self.root, context, active_project_root)

    def project_mode(self, context_id: str) -> str:
        with self.lock:
            context = self._context_locked(context_id)
            return context.project_mode

    def workflow_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            active_project_root = context.active_project_root
        return workflow_payload(active_project_root)

    def project_status_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            command_root = self._command_root_locked(context)
        if command_root is None:
            raise StateError("activate a project first")
        output, ok = _status_snapshot(command_root)
        return {
            "ok": ok,
            "output": output,
        }

    def create_feature_collection(
        self,
        context_id: str,
        name: str,
    ) -> dict[str, object]:
        return self.workflow_controller("software").create_feature_collection(
            context_id,
            name,
        )

    def switch_feature_collection(
        self,
        context_id: str,
        collection_id: str,
    ) -> dict[str, object]:
        return self.workflow_controller("software").switch_feature_collection(
            context_id,
            collection_id,
        )

    def start_feature_work_item(
        self,
        context_id: str,
        *,
        title: str,
        feature_name: str | None = None,
        collection_id: str | None = None,
        parent_slug: str | None = None,
        branch: bool = False,
        stash_subrepo_changes: bool = False,
    ) -> dict[str, object]:
        return self.workflow_controller("software").start_feature_work_item(
            context_id,
            title=title,
            feature_name=feature_name,
            collection_id=collection_id,
            parent_slug=parent_slug,
            branch=branch,
            stash_subrepo_changes=stash_subrepo_changes,
        )

    def switch_feature_work_item(
        self,
        context_id: str,
        slug: str,
    ) -> dict[str, object]:
        return self.workflow_controller("software").switch_feature_work_item(
            context_id,
            slug,
        )

    def start_bug_work_item(
        self,
        context_id: str,
        *,
        issue_reference: str,
        branch: bool = False,
        stash_subrepo_changes: bool = False,
    ) -> dict[str, object]:
        return self.workflow_controller("software").start_bug_work_item(
            context_id,
            issue_reference=issue_reference,
            branch=branch,
            stash_subrepo_changes=stash_subrepo_changes,
        )

    def switch_bug_work_item(
        self,
        context_id: str,
        slug: str,
    ) -> dict[str, object]:
        return self.workflow_controller("software").switch_bug_work_item(
            context_id,
            slug,
        )

    def select_workflow_stage(
        self,
        context_id: str,
        stage: str,
    ) -> dict[str, object]:
        return self.workflow_controller("software").select_workflow_stage(
            context_id,
            stage,
        )

    def approve_requirements(
        self,
        context_id: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        return self.workflow_controller("software").approve_requirements(
            context_id,
            skip_approval=skip_approval,
        )

    def open_project(self, context_id: str, path: str) -> dict[str, object]:
        if _is_meta_project_path(path):
            return self.open_meta_project(context_id, path)
        project_root = _existing_project_root(path)
        workflow_stage = _software_domain()._active_workflow_stage(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            context.activation_root = project_root
            context.project_mode = "project"
            context.active_project_root = project_root
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = workflow_stage
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "project")
        return {
            **project_payload(self.root, context, project_root),
            "status": "opened",
        }

    def create_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _resolve_project_path(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        manifest = initialize_project(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = project_root
            context.project_mode = "project"
            context.active_project_root = project_root
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = _software_domain()._visible_workflow_stage(manifest.active_stage)
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "project")
        return {
            **project_payload(self.root, context, project_root),
            "status": "created",
            "run_id": manifest.run_id,
        }

    def open_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        return self.workflow_controller("creative-writing").open_creative_project(
            context_id,
            path,
        )

    def create_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        return self.workflow_controller("creative-writing").create_creative_project(
            context_id,
            path,
        )

    def open_meta_project(self, context_id: str, path: str) -> dict[str, object]:
        meta_context = _existing_meta_context(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            context.activation_root = meta_context["meta_root"]
            context.project_mode = "meta"
            context.active_project_root = meta_context["active_project_root"]
            context.active_repository_name = meta_context["active_repository_name"]
            context.registered_repositories = meta_context["registered_repositories"]
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = meta_context["workflow_stage"]
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
            project_root = context.active_project_root
        _remember_recent_project(self.root, meta_context["meta_root"], "meta")
        return {
            **project_payload(self.root, context, project_root),
            "status": "opened",
        }

    def create_meta_project(self, context_id: str, path: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        meta_root, registry = initialize_meta_project(path)
        repositories = _meta_repository_payloads(registry)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = meta_root
            context.project_mode = "meta"
            context.active_project_root = None
            context.active_repository_name = None
            context.registered_repositories = repositories
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, meta_root, "meta")
        return {
            **project_payload(self.root, context, None),
            "status": "created",
        }

    def add_meta_repository(self, context_id: str, path: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _add_meta_repository(meta_root, path)
        with self.lock:
            context = self._context_locked(context_id)
            context.registered_repositories = meta_context["registered_repositories"]
            context.active_repository_name = meta_context["active_repository_name"]
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "registered",
        }

    def start_meta_repository(self, context_id: str, repository: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _start_meta_repository(meta_root, repository)
        with self.lock:
            context = self._context_locked(context_id)
            context.active_project_root = meta_context["active_project_root"]
            context.active_repository_name = meta_context["active_repository_name"]
            context.registered_repositories = meta_context["registered_repositories"]
            context.workflow_stage = meta_context["workflow_stage"]
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "started",
        }

    def remove_meta_repository(self, context_id: str, repository: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _remove_meta_repository(meta_root, repository)
        with self.lock:
            context = self._context_locked(context_id)
            context.active_project_root = meta_context["active_project_root"]
            context.active_repository_name = meta_context["active_repository_name"]
            context.registered_repositories = meta_context["registered_repositories"]
            context.workflow_stage = meta_context["workflow_stage"]
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "removed",
        }

    def deactivate_project(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            sessions = self._context_process_sessions_locked(context)
        self._terminate_sessions(sessions)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = None
            context.project_mode = "none"
            context.active_project_root = None
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        return {
            **project_payload(self.root, context, None),
            "status": "deactivated",
        }

    def start_requirements_agent(
        self,
        context_id: str,
        *,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").start_requirements_agent(
            context_id,
            allow_stage_reopen=allow_stage_reopen,
        )

    def restart_requirements_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").restart_requirements_agent(
            context_id
        )

    def complete_requirements_agent(self, context_id: str) -> dict[str, object]:
        return self.workflow_controller("software").complete_requirements_agent(
            context_id
        )

    def skip_requirements_agent(self, context_id: str) -> dict[str, object]:
        return self.workflow_controller("software").skip_requirements_agent(context_id)

    def start_design_agent(
        self,
        context_id: str,
        *,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").start_design_agent(
            context_id,
            allow_stage_reopen=allow_stage_reopen,
        )

    def restart_design_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").restart_design_agent(context_id)

    def complete_design_agent(self, context_id: str) -> dict[str, object]:
        return self.workflow_controller("software").complete_design_agent(context_id)

    def start_design_review_agent(
        self,
        context_id: str,
        *,
        force: bool = False,
        allow_stage_reopen: bool = False,
        interactive: bool = False,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").start_design_review_agent(
            context_id,
            force=force,
            allow_stage_reopen=allow_stage_reopen,
            interactive=interactive,
        )

    def restart_design_review_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").restart_design_review_agent(
            context_id
        )

    def start_documentation_agent(
        self,
        context_id: str,
        *,
        interactive: bool = True,
        target: str | None = None,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").start_documentation_agent(
            context_id,
            interactive=interactive,
            target=target,
        )

    def initialize_creative_workspace(self, context_id: str) -> dict[str, object]:
        return self.workflow_controller(
            "creative-writing"
        ).initialize_creative_workspace(context_id)

    def creative_tree(self, context_id: str) -> dict[str, object]:
        return self.workflow_controller("creative-writing").creative_tree(context_id)

    def create_creative_folder(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        return self.workflow_controller("creative-writing").create_creative_folder(
            context_id,
            relative_path,
        )

    def create_creative_document(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        return self.workflow_controller("creative-writing").create_creative_document(
            context_id,
            relative_path,
        )

    def create_creative_corkboard(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        return self.workflow_controller("creative-writing").create_creative_corkboard(
            context_id,
            relative_path,
        )

    def rename_creative_entry(
        self,
        context_id: str,
        relative_path: str,
        new_name: str,
    ) -> dict[str, object]:
        return self.workflow_controller("creative-writing").rename_creative_entry(
            context_id,
            relative_path,
            new_name,
        )

    def delete_creative_entry(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        return self.workflow_controller("creative-writing").delete_creative_entry(
            context_id,
            relative_path,
        )

    def creative_scratchpad(self, context_id: str) -> dict[str, object]:
        return self.workflow_controller("creative-writing").creative_scratchpad(
            context_id
        )

    def save_creative_scratchpad(
        self,
        context_id: str,
        markdown: str,
    ) -> dict[str, object]:
        return self.workflow_controller("creative-writing").save_creative_scratchpad(
            context_id,
            markdown,
        )

    def save_creative_corkboard(
        self,
        context_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self.workflow_controller("creative-writing").save_creative_corkboard(
            context_id,
            payload,
        )

    def start_creative_writing_agent(
        self,
        context_id: str,
        *,
        active_document: str | None = None,
        active_target: dict[str, object] | None = None,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("creative-writing").start_creative_writing_agent(
            context_id,
            active_document=active_document,
            active_target=active_target,
        )

    def stop_design_review_agent(self, context_id: str) -> dict[str, object]:
        return self.workflow_controller("software").stop_design_review_agent(context_id)

    def complete_design_review_agent(self, context_id: str) -> dict[str, object]:
        return self.workflow_controller("software").complete_design_review_agent(
            context_id
        )

    def approve_design(
        self,
        context_id: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        return self.workflow_controller("software").approve_design(
            context_id,
            skip_approval=skip_approval,
        )

    def start_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
        *,
        interactive: bool | None = None,
        force: bool = False,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").start_workflow_stage_agent(
            context_id,
            stage,
            interactive=interactive,
            force=force,
            allow_stage_reopen=allow_stage_reopen,
        )

    def restart_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
        *,
        interactive: bool | None = None,
    ) -> tuple[AgentSession, bool]:
        return self.workflow_controller("software").restart_workflow_stage_agent(
            context_id,
            stage,
            interactive=interactive,
        )

    def stop_workflow_stage_agent(self, context_id: str, stage: str) -> dict[str, object]:
        return self.workflow_controller("software").stop_workflow_stage_agent(
            context_id,
            stage,
        )

    def approve_workflow_stage(
        self,
        context_id: str,
        stage: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        return self.workflow_controller("software").approve_workflow_stage(
            context_id,
            stage,
            skip_approval=skip_approval,
        )

    def _mark_generic_stage_completed(
        self,
        context_id: str,
        stage: str,
        returncode: int,
    ) -> None:
        return self.workflow_controller("software")._mark_generic_stage_completed(
            context_id,
            stage,
            returncode,
        )

    def requirements_document_root(self, context_id: str) -> Path:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            if (
                context.workflow_stage == "requirements"
                and not context.requirements_started
            ):
                raise AgentSessionError("start requirements first")
            return project_root

    def active_project_root(self, context_id: str) -> Path:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            return project_root

    def command_root(self, context_id: str) -> Path:
        with self.lock:
            context = self._context_locked(context_id)
            command_root = self._command_root_locked(context)
            if command_root is None:
                raise StateError("activate a project first")
            return command_root

    def current_requirements_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.requirements_session

    def current_design_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.design_session

    def current_design_review_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.design_review_session

    def current_documentation_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            selected_session_id = context.selected_session_id
            if selected_session_id:
                for session in context.documentation_sessions.values():
                    if session.session_id == selected_session_id:
                        return session
            for session in reversed(list(context.documentation_sessions.values())):
                if session.is_active():
                    return session
            if context.documentation_sessions:
                return list(context.documentation_sessions.values())[-1]
            return None

    def start_ad_hoc_agent(self, context_id: str) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            command_root = self._command_root_locked(context)
            if command_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.ad_hoc_session is not None
                and context.ad_hoc_session.is_active()
            ):
                context.selected_session_id = context.ad_hoc_session.session_id
                return context.ad_hoc_session, False
            session = AgentSession(
                command=_ad_hoc_agent_command(command_root),
                cwd=command_root,
                label="ad-hoc agent",
                kind="ad-hoc",
                interactive=True,
            )
            session = self._prepare_session_locked(context, session)
            context.ad_hoc_session = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.ad_hoc_session is session:
                    context.ad_hoc_session = None
                    context.selected_session_id = None
            raise
        return session, True

    def current_project_shell_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.project_shell_session

    def start_project_shell(self, context_id: str) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.project_shell_session is not None
                and context.project_shell_session.is_active()
            ):
                return context.project_shell_session, False
            session = AgentSession(
                command=_project_shell_command(),
                cwd=project_root,
                label="project shell",
                kind="project-shell",
                interactive=True,
                echo_input=True,
            )
            session = self._prepare_session_locked(context, session)
            context.project_shell_session = session
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.project_shell_session is session:
                    context.project_shell_session = None
            raise
        return session, True

    def send_project_shell_input(self, context_id: str, data: str) -> None:
        session = self.current_project_shell_session(context_id)
        if session is None:
            raise AgentSessionError("project shell has not been started")
        session.send_raw(data)

    def resize_project_shell(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        session = self.current_project_shell_session(context_id)
        if session is None:
            raise AgentSessionError("project shell has not been started")
        session.resize(columns, rows)

    def stop_project_shell(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.project_shell_session
        if session is None or not session.is_active():
            raise AgentSessionError("project shell is not running")
        session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.project_shell_session is session:
                context.project_shell_session = None
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "stopped project shell",
        }

    def session_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            selected_session = self._selected_session_locked(context)
            return {
                "context_id": context.context_id,
                "selected_session_id": (
                    selected_session.session_id if selected_session is not None else None
                ),
                "sessions": _session_payloads(context),
            }

    def session_registry_payload(self) -> dict[str, object]:
        records = _load_service_session_records(self.root)
        by_id: dict[str, dict[str, object]] = {}
        for entry in records.get("sessions", []):
            if not isinstance(entry, dict):
                continue
            session_id = str(entry.get("session_id") or "").strip()
            if not session_id:
                continue
            record = dict(entry)
            record["attachable"] = False
            by_id[session_id] = record
        with self.lock:
            for context in self.contexts.values():
                for session in self._context_process_sessions_locked(context):
                    record = _service_session_record(
                        self.root,
                        context,
                        session,
                    )
                    record["attachable"] = True
                    by_id[session.session_id] = record
        sessions = sorted(
            by_id.values(),
            key=lambda record: (
                str(record.get("status") or "") == "running",
                str(record.get("updated_at") or ""),
            ),
            reverse=True,
        )
        return {
            "schema_version": 1,
            "sessions": sessions,
        }

    def select_session(self, context_id: str, session_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            session = self._session_by_id_locked(context, session_id)
            context.selected_session_id = session.session_id
            return {
                "context_id": context.context_id,
                "selected_session_id": session.session_id,
                "sessions": _session_payloads(context),
            }

    def attach_session(self, context_id: str, session_id: str) -> dict[str, object]:
        with self.lock:
            target_context = self._context_locked(context_id)
            source_context, session = self._session_by_id_any_context_locked(session_id)
            target_context.activation_root = source_context.activation_root
            target_context.project_mode = source_context.project_mode
            target_context.active_project_root = source_context.active_project_root
            target_context.active_repository_name = source_context.active_repository_name
            target_context.registered_repositories = list(
                source_context.registered_repositories
            )
            target_context.workflow_stage = source_context.workflow_stage
            target_context.requirements_started = source_context.requirements_started
            target_context.design_started = source_context.design_started
            target_context.design_review_started = source_context.design_review_started
            target_context.design_review_interactive = (
                source_context.design_review_interactive
            )
            target_context.stage_started = set(source_context.stage_started)
            self._attach_session_locked(target_context, session)
            if session.kind != "project-shell":
                target_context.selected_session_id = session.session_id
            project_root = target_context.active_project_root
        return {
            **project_payload(self.root, target_context, project_root),
            "status": "attached",
            "attached_session_id": session.session_id,
        }

    def selected_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return self._selected_session_locked(context)

    def session_by_id(self, context_id: str, session_id: str) -> AgentSession:
        with self.lock:
            context = self._context_locked(context_id)
            return self._session_by_id_locked(context, session_id)

    def send_selected_session_message(self, context_id: str, message: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send(message)

    def send_session_message(
        self,
        context_id: str,
        session_id: str,
        message: str,
    ) -> None:
        session = self.session_by_id(context_id, session_id)
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send(message)

    def send_selected_session_key(self, context_id: str, key: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send_key(key)

    def send_selected_session_raw(self, context_id: str, data: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send_raw(data)

    def interrupt_selected_session(self, context_id: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        session.interrupt()

    def resize_selected_session(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        session.resize(columns, rows)

    def resize_session(
        self,
        context_id: str,
        session_id: str,
        columns: int,
        rows: int,
    ) -> None:
        session = self.session_by_id(context_id, session_id)
        session.resize(columns, rows)

    def has_running_progress_agent(self, context_id: str) -> bool:
        with self.lock:
            context = self._context_locked(context_id)
            design_review_session = context.design_review_session
            generic_running = any(
                session.is_active() and not session.interactive
                for session in context.stage_sessions.values()
            )
            return bool(
                (
                    design_review_session is not None
                    and design_review_session.is_active()
                    and not context.design_review_interactive
                )
                or generic_running
            )

    def resize_requirements_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.requirements_session
        if session is None:
            raise AgentSessionError("requirements agent has not been started")
        session.resize(columns, rows)

    def resize_design_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_session
        if session is None:
            raise AgentSessionError("design agent has not been started")
        session.resize(columns, rows)

    def resize_design_review_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_review_session
        if session is None:
            raise AgentSessionError("design review agent has not been started")
        session.resize(columns, rows)

    def interrupt_requirements_agent(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.requirements_session
        if session is None:
            raise AgentSessionError("requirements agent has not been started")
        session.interrupt()

    def interrupt_design_agent(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_session
        if session is None:
            raise AgentSessionError("design agent has not been started")
        session.interrupt()

    def interrupt_design_review_agent(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_review_session
        if session is None:
            raise AgentSessionError("design review agent has not been started")
        session.interrupt()

    def _terminate_requirements_session(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.requirements_session
        if session is not None and session.is_active():
            session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.requirements_session is session:
                context.requirements_session = None
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None

    def _terminate_design_session(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_session
        if session is not None and session.is_active():
            session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.design_session is session:
                context.design_session = None
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None

    def _terminate_all_context_sessions(self, context_id: str) -> bool:
        with self.lock:
            context = self._context_locked(context_id)
            sessions = self._context_sessions_locked(context)
        terminated = self._terminate_sessions(sessions)
        with self.lock:
            context = self._context_locked(context_id)
            self._clear_sessions_locked(context, sessions)
        return terminated

    def _terminate_workflow_sessions(self, context_id: str) -> bool:
        with self.lock:
            context = self._context_locked(context_id)
            sessions = [
                session
                for session in [
                    context.requirements_session,
                    context.design_session,
                    context.design_review_session,
                    *context.stage_sessions.values(),
                    context.ad_hoc_session,
                ]
                if session is not None
            ]
        terminated = self._terminate_sessions(sessions)
        with self.lock:
            context = self._context_locked(context_id)
            self._clear_sessions_locked(context, sessions)
        return terminated

    def terminate_all_sessions(self) -> bool:
        with self.lock:
            sessions = self._all_sessions_locked()
        terminated = self._terminate_sessions(sessions)
        with self.lock:
            for context in self.contexts.values():
                self._clear_sessions_locked(context, sessions)
        return terminated

    def _mark_design_review_completed(
        self,
        context_id: str,
        returncode: int,
    ) -> None:
        if returncode != 0:
            return
        with self.lock:
            try:
                context = self._context_locked(context_id)
            except StateError:
                return
            if context.workflow_stage == "design-review":
                context.design_review_started = True

    def _context_sessions_locked(
        self,
        context: BrowserContext,
    ) -> list[AgentSession]:
        return [
            session
            for session in [
                context.requirements_session,
                context.design_session,
                context.design_review_session,
                *context.stage_sessions.values(),
                *context.documentation_sessions.values(),
                context.creative_session,
                context.ad_hoc_session,
            ]
            if session is not None
        ]

    def _context_process_sessions_locked(
        self,
        context: BrowserContext,
    ) -> list[AgentSession]:
        sessions = self._context_sessions_locked(context)
        if context.project_shell_session is not None:
            sessions.append(context.project_shell_session)
        return sessions

    def _all_sessions_locked(self) -> list[AgentSession]:
        sessions: list[AgentSession] = []
        seen: set[int] = set()
        for context in self.contexts.values():
            for session in self._context_process_sessions_locked(context):
                identifier = id(session)
                if identifier in seen:
                    continue
                seen.add(identifier)
                sessions.append(session)
        return sessions

    def _clear_sessions_locked(
        self,
        context: BrowserContext,
        sessions: list[AgentSession],
    ) -> None:
        for session in sessions:
            if context.requirements_session is session:
                context.requirements_session = None
            if context.design_session is session:
                context.design_session = None
            if context.design_review_session is session:
                context.design_review_session = None
                context.design_review_interactive = False
            for stage, stage_session in list(context.stage_sessions.items()):
                if stage_session is session:
                    context.stage_sessions.pop(stage, None)
            for key, documentation_session in list(context.documentation_sessions.items()):
                if documentation_session is session:
                    context.documentation_sessions.pop(key, None)
            if context.creative_session is session:
                context.creative_session = None
            if context.ad_hoc_session is session:
                context.ad_hoc_session = None
            if context.project_shell_session is session:
                context.project_shell_session = None
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None

    def _terminate_sessions(self, sessions: list[AgentSession]) -> bool:
        terminated = False
        for session in sessions:
            if session.is_active():
                session.terminate()
                terminated = True
        return terminated

    def _context_locked(self, context_id: str) -> BrowserContext:
        context_id = context_id.strip()
        if not context_id:
            raise StateError("missing browser context; refresh the page")
        context = self.contexts.get(context_id)
        if context is None:
            raise StateError("unknown browser context; refresh the page")
        return context

    def _session_by_id_locked(
        self,
        context: BrowserContext,
        session_id: str,
    ) -> AgentSession:
        session_id = session_id.strip()
        for session in self._context_sessions_locked(context):
            if session.session_id == session_id:
                return session
        raise AgentSessionError("unknown agent session")

    def _session_by_id_any_context_locked(
        self,
        session_id: str,
    ) -> tuple[BrowserContext, AgentSession]:
        session_id = session_id.strip()
        for context in self.contexts.values():
            for session in self._context_process_sessions_locked(context):
                if session.session_id == session_id:
                    return context, session
        raise AgentSessionError("unknown service session")

    def _attach_session_locked(
        self,
        context: BrowserContext,
        session: AgentSession,
    ) -> None:
        if session.kind == "requirements":
            context.requirements_session = session
        elif session.kind == "design":
            context.design_session = session
        elif session.kind == "design-review":
            context.design_review_session = session
        elif session.kind == "documentation":
            session_key = str(session.metadata.get("document_path") or "__default__")
            context.documentation_sessions[session_key] = session
        elif session.kind == "creative-writing":
            context.creative_session = session
        elif session.kind == "ad-hoc":
            context.ad_hoc_session = session
        elif session.kind == "project-shell":
            context.project_shell_session = session
        elif session.kind in _software_domain().GENERIC_STAGE_CONFIG:
            context.stage_sessions[session.kind] = session
        else:
            context.ad_hoc_session = session

    def _selected_session_locked(
        self,
        context: BrowserContext,
    ) -> AgentSession | None:
        selected_session_id = context.selected_session_id
        sessions = self._context_sessions_locked(context)
        if selected_session_id:
            for session in sessions:
                if session.session_id == selected_session_id:
                    return session
        for session in sessions:
            if session.is_active():
                context.selected_session_id = session.session_id
                return session
        if sessions:
            context.selected_session_id = sessions[-1].session_id
            return sessions[-1]
        context.selected_session_id = None
        return None

    def _command_root_locked(self, context: BrowserContext) -> Path | None:
        return context.activation_root or context.active_project_root

    def _require_no_active_agent_locked(self, context: BrowserContext) -> None:
        active_labels = [
            getattr(session, "label", "agent")
            for session in self._context_process_sessions_locked(context)
            if session.is_active()
        ]
        if active_labels:
            raise AgentSessionError(
                "cannot change projects while this context's "
                f"{active_labels[0]} is running"
            )

    def _require_session_locks_available_locked(
        self,
        context: BrowserContext,
        lock_names: frozenset[str],
    ) -> None:
        if not lock_names:
            return
        for session in self._context_sessions_locked(context):
            if not session.is_active():
                continue
            overlap = sorted(frozenset(getattr(session, "lock_names", ())).intersection(lock_names))
            if overlap:
                raise AgentSessionError(
                    f"{session.label} is already using {', '.join(overlap)}"
                )

    def _require_requirements_started_locked(self, context: BrowserContext) -> None:
        if not context.requirements_started:
            raise AgentSessionError("start requirements first")


@dataclass
class ServiceConfig:
    root: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    session_backend: str = SESSION_BACKEND_PTY
    module_registry: ModuleRegistry | None = None
    workflow_registry: WorkflowRegistry | None = None


class ElectroBoyHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        bind_and_activate: bool = True,
        service_state: ServiceState | None = None,
    ) -> None:
        self.service_state = service_state
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

    def server_close(self) -> None:
        if (
            self.service_state is not None
            and self.service_state.session_backend != SESSION_BACKEND_TMUX
        ):
            self.service_state.terminate_all_sessions()
        super().server_close()


def create_server(
    root: Path | str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    session_backend: str | None = None,
) -> ElectroBoyHTTPServer:
    backend = (
        _session_backend_from_env()
        if session_backend is None
        else _normalize_session_backend(session_backend)
    )
    resolved_root = Path(root).expanduser().resolve()
    module_registry = build_module_registry()
    workflow_registry = build_workflow_registry(
        module_registry,
        configured_workflows(resolved_root, installed_workflow_factories()),
    )
    config = ServiceConfig(
        root=resolved_root,
        host=host,
        port=port,
        session_backend=backend,
        module_registry=module_registry,
        workflow_registry=workflow_registry,
    )
    state = ServiceState(
        root=config.root,
        session_backend=config.session_backend,
        workflow_registry=workflow_registry,
    )
    return ElectroBoyHTTPServer(
        (config.host, config.port),
        _handler_for(config, state),
        service_state=state,
    )


def run_service(
    root: Path | str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    session_backend: str | None = None,
) -> int:
    server = create_server(
        root,
        host=host,
        port=port,
        session_backend=session_backend,
    )
    stop_signal: int | None = None
    previous_signal_handlers: dict[int, Any] = {}

    def handle_stop_signal(signum: int, _frame: Any) -> None:
        nonlocal stop_signal
        stop_signal = signum
        raise KeyboardInterrupt

    if threading.current_thread() is threading.main_thread():
        for stop in [signal.SIGTERM, getattr(signal, "SIGHUP", None)]:
            if stop is None:
                continue
            previous_signal_handlers[stop] = signal.getsignal(stop)
            signal.signal(stop, handle_stop_signal)

    address, actual_port = server.server_address[:2]
    display_host = host if address in {"", "0.0.0.0"} else address
    print(
        f"ElectroBoy service listening on http://{display_host}:{actual_port}",
        flush=True,
    )
    print(f"root: {Path(root).expanduser().resolve()}", flush=True)
    print(f"session backend: {server.service_state.session_backend}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nElectroBoy service stopped.")
        if stop_signal is not None:
            return 128 + stop_signal
        return 130
    finally:
        for signum, previous_handler in previous_signal_handlers.items():
            signal.signal(signum, previous_handler)
        server.server_close()
    return 0


def health_payload(
    root: Path | str,
    module_registry: ModuleRegistry | None = None,
    workflow_registry: WorkflowRegistry | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "connected",
        "service": "electroboy",
        "root": str(Path(root).expanduser().resolve()),
    }
    if module_registry is not None:
        payload["modules"] = [module.id for module in module_registry.values()]
    if workflow_registry is not None:
        payload["workflows"] = [
            workflow.id for workflow in workflow_registry.values()
        ]
    payload["workflow_config"] = workflow_config_payload(root)
    payload["frontend_bundles"] = [
        bundle["id"]
        for bundle in frontend_asset_payload(module_registry, workflow_registry)
    ]
    return payload


def splash_image_bytes(resource: str = SPLASH_IMAGE_RESOURCE) -> bytes:
    return (
        resources.files(SPLASH_IMAGE_PACKAGE)
        .joinpath("assets", resource)
        .read_bytes()
    )


def project_payload(
    service_root: Path | str,
    context: BrowserContext,
    active_project_root: Path | str | None = None,
) -> dict[str, object]:
    service_root = Path(service_root).expanduser().resolve()
    active_root = (
        Path(active_project_root).expanduser().resolve()
        if active_project_root
        else None
    )
    activation_root = (
        Path(context.activation_root).expanduser().resolve()
        if context.activation_root
        else active_root
    )
    requirements_session = context.requirements_session
    requirements_running = bool(
        active_root
        and requirements_session is not None
        and requirements_session.is_active()
    )
    design_session = context.design_session
    design_running = bool(
        active_root
        and design_session is not None
        and design_session.is_active()
    )
    design_review_session = context.design_review_session
    design_review_running = bool(
        active_root
        and design_review_session is not None
        and design_review_session.is_active()
    )
    documentation_running = bool(
        active_root
        and any(session.is_active() for session in context.documentation_sessions.values())
    )
    creative_session = context.creative_session
    creative_running = bool(
        active_root
        and creative_session is not None
        and creative_session.is_active()
    )
    ad_hoc_session = context.ad_hoc_session
    ad_hoc_running = bool(
        activation_root
        and ad_hoc_session is not None
        and ad_hoc_session.is_active()
    )
    project_shell_session = context.project_shell_session
    project_shell_running = bool(
        active_root
        and project_shell_session is not None
        and project_shell_session.is_active()
    )
    workflow_stage = (
        _software_domain()._visible_workflow_stage(context.workflow_stage)
        if active_root and context.workflow_stage
        else ("requirements" if active_root else "project")
    )
    return {
        "context_id": context.context_id,
        "service_root": str(service_root),
        "activation_root": str(activation_root) if activation_root else None,
        "project_mode": context.project_mode,
        "active_project_root": str(active_root) if active_root else None,
        "active_repository_name": context.active_repository_name,
        "registered_repositories": context.registered_repositories,
        "workflow_stage": workflow_stage,
        "requirements_started": bool(active_root and context.requirements_started),
        "requirements_running": requirements_running,
        "requirements_approved": bool(
            active_root
            and _software_domain()._stage_has_approvals(
                active_root,
                STAGE_REQUIREMENTS,
                ["human-approval", "author-confirmation"],
            )
        ),
        "design_started": bool(active_root and context.design_started),
        "design_running": design_running,
        "design_review_started": bool(active_root and context.design_review_started),
        "design_review_running": design_review_running,
        "design_review_interactive": bool(
            active_root and design_review_running and context.design_review_interactive
        ),
        "stage_runs": (
            _software_domain()._generic_stage_run_payload(context, active_root)
            if active_root
            else {}
        ),
        "documentation_running": documentation_running,
        "creative_writing_running": creative_running,
        "ad_hoc_running": ad_hoc_running,
        "project_shell_running": project_shell_running,
        "design_approved": bool(
            active_root
            and _software_domain()._stage_has_approvals(
                active_root,
                STAGE_DESIGN_ACCEPTANCE,
                ["human-approval"],
            )
        ),
        "activate_command": (
            f"source {activation_root / '.electroboy' / 'bin' / 'activate'}"
            if activation_root and context.project_mode != "creative"
            else None
        ),
        "selected_session_id": context.selected_session_id,
        "sessions": _session_payloads(context),
        "work_items": (
            _software_domain()._work_item_payload(active_root)
            if active_root
            else {
                "schema_version": 1,
                "active_collection_id": None,
                "active_feature_slug": None,
                "active_bug_slug": None,
                "collections": [],
                "features": [],
                "bugs": [],
            }
        ),
        "recent_projects": _recent_project_entries(service_root),
    }


def _service_session_records_path(service_root: Path | str) -> Path:
    return (
        Path(service_root).expanduser().resolve()
        / SERVICE_SESSION_RECORDS_RELATIVE_PATH
    )


def _service_session_transcript_path(
    service_root: Path | str,
    session_id: str,
) -> Path:
    safe_session_id = _download_name_part(session_id)
    return (
        Path(service_root).expanduser().resolve()
        / SERVICE_SESSION_TRANSCRIPTS_RELATIVE_DIR
        / f"{safe_session_id}.jsonl"
    )


def _load_service_session_records(service_root: Path | str) -> dict[str, object]:
    path = _service_session_records_path(service_root)
    if not path.exists():
        return {"schema_version": 1, "sessions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "sessions": []}
    if not isinstance(data, dict):
        return {"schema_version": 1, "sessions": []}
    if not isinstance(data.get("sessions"), list):
        data["sessions"] = []
    data["schema_version"] = 1
    return data


def _save_service_session_records(
    service_root: Path | str,
    data: dict[str, object],
) -> None:
    path = _service_session_records_path(service_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _upsert_service_session_record(
    service_root: Path | str,
    record: dict[str, object],
) -> None:
    session_id = str(record.get("session_id") or "").strip()
    if not session_id:
        return
    data = _load_service_session_records(service_root)
    sessions = [
        entry
        for entry in data.get("sessions", [])
        if isinstance(entry, dict) and str(entry.get("session_id") or "") != session_id
    ]
    data["sessions"] = [record, *sessions][:200]
    _save_service_session_records(service_root, data)


def _service_session_record(
    service_root: Path | str,
    context: BrowserContext,
    session: AgentSession,
) -> dict[str, object]:
    payload = session.payload(selected=False)
    active_root = context.active_project_root
    activation_root = context.activation_root or active_root
    record = {
        **payload,
        "context_id": context.context_id,
        "active_project_root": str(active_root) if active_root else None,
        "activation_root": str(activation_root) if activation_root else None,
        "project_mode": context.project_mode,
        "active_repository_name": context.active_repository_name,
        "cwd": str(session.cwd),
        "updated_at": utc_now(),
        "transcript_path": (
            str(session.transcript_path)
            if session.transcript_path is not None
            else str(_service_session_transcript_path(service_root, session.session_id))
        ),
    }
    tmux_name = getattr(session, "tmux_name", None)
    if tmux_name:
        record["tmux_session"] = str(tmux_name)
    return record


def _session_payloads(context: BrowserContext) -> list[dict[str, object]]:
    selected_session_id = context.selected_session_id
    payloads: list[dict[str, object]] = []
    for session in [
        context.requirements_session,
        context.design_session,
        context.design_review_session,
        *context.stage_sessions.values(),
        *context.documentation_sessions.values(),
        context.creative_session,
        context.ad_hoc_session,
    ]:
        if session is None:
            continue
        session_id = str(getattr(session, "session_id", f"legacy-{id(session)}"))
        if hasattr(session, "payload"):
            payloads.append(
                session.payload(selected=session_id == selected_session_id)  # type: ignore[attr-defined]
            )
            continue
        payloads.append(
            {
                "session_id": session_id,
                "kind": getattr(session, "kind", "agent"),
                "label": getattr(session, "label", "agent"),
                "status": "running" if session.is_active() else "completed",
                "returncode": getattr(session, "returncode", None),
                "interactive": bool(getattr(session, "interactive", True)),
                "locks": sorted(getattr(session, "lock_names", [])),
                "selected": session_id == selected_session_id,
                "created_at": getattr(session, "created_at", ""),
                "command": list(getattr(session, "command", [])),
                "metadata": dict(getattr(session, "metadata", {}) or {}),
            }
        )
    return payloads


def workflow_payload(active_project_root: Path | str | None = None) -> dict[str, object]:
    return {
        "stages": [
            {
                "id": stage,
                "label": stage,
                "operations": _stage_operations(stage, active_project_root),
            }
            for stage in _software_domain().WORKFLOW_STAGES
        ]
    }


def initialize_project(project_root: Path | str):
    from ..cli import (
        _init_git_repository,
        _write_project_bin,
        _write_project_config,
        _write_project_gitignore,
        _write_project_runtime,
    )

    project_root = Path(project_root).expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    _init_git_repository(project_root)
    ArtifactManager(project_root).init_templates()
    _write_project_config(project_root)
    _write_project_gitignore(project_root)
    _write_project_runtime(project_root)
    _write_project_bin(project_root)

    store = StateStore(project_root)
    return store.init_run()


def initialize_meta_project(path: Path | str) -> tuple[Path, dict[str, object]]:
    from ..cli import (
        _meta_registry_file,
        _read_meta_registry,
        _write_meta_environment,
        _write_meta_registry,
    )

    meta_root = _resolve_project_path(str(path))
    meta_root.mkdir(parents=True, exist_ok=True)
    _write_meta_environment(meta_root)
    registry_exists = _meta_registry_file(meta_root).exists()
    registry = _read_meta_registry(meta_root)
    if not registry_exists:
        _write_meta_registry(meta_root, registry)
    return meta_root, registry


def _resolve_project_path(path: str) -> Path:
    path = path.strip()
    if not path:
        raise StateError("project path is required")
    return Path(path).expanduser().resolve()


def _is_meta_project_path(path: str | Path) -> bool:
    try:
        project_root = Path(path).expanduser().resolve()
    except OSError:
        return False
    return (project_root / META_REGISTRY_RELATIVE_PATH).exists()


def _existing_meta_context(path: str | Path) -> dict[str, object]:
    meta_root = _resolve_project_path(str(path))
    if not meta_root.exists():
        raise StateError(f"meta-project directory does not exist: {meta_root}")
    if not meta_root.is_dir():
        raise StateError(f"meta-project path is not a directory: {meta_root}")
    if not _is_meta_project_path(meta_root):
        raise StateError(
            "no ElectroBoy meta-project exists at this path; create it first"
        )
    return _meta_context(meta_root)


def _meta_context(meta_root: Path) -> dict[str, object]:
    from ..cli import _meta_repository_by_name, _read_meta_registry

    registry = _read_meta_registry(meta_root)
    repositories = _meta_repository_payloads(registry)
    active_name = str(registry.get("active") or "")
    active_project_root: Path | None = None
    workflow_stage: str | None = None
    if active_name:
        record = _meta_repository_by_name(registry, active_name)
        if record is not None:
            candidate = Path(str(record.get("path", ""))).expanduser().resolve()
            if (
                candidate.exists()
                and candidate.is_dir()
                and StateStore(candidate).current_run_id()
            ):
                active_project_root = candidate
                workflow_stage = _software_domain()._active_workflow_stage(candidate)
    return {
        "meta_root": meta_root,
        "active_project_root": active_project_root,
        "active_repository_name": active_name or None,
        "registered_repositories": repositories,
        "workflow_stage": workflow_stage,
    }


def _meta_repository_payloads(registry: dict[str, object]) -> list[dict[str, object]]:
    from ..cli import _meta_repositories

    return [
        {
            "name": str(repo.get("name") or ""),
            "path": str(repo.get("path") or ""),
        }
        for repo in _meta_repositories(registry)
    ]


def _add_meta_repository(meta_root: Path, path: str) -> dict[str, object]:
    from ..cli import (
        _read_meta_registry,
        _register_meta_repository,
        _resolve_existing_repo_path,
    )

    registry = _read_meta_registry(meta_root)
    repo_path = _resolve_existing_repo_path(meta_root, path)
    _register_meta_repository(meta_root, repo_path, registry)
    return _meta_context(meta_root)


def _start_meta_repository(meta_root: Path, repository: str) -> dict[str, object]:
    from ..cli import (
        _ensure_target_pipeline_project,
        _read_meta_registry,
        _register_meta_repository,
        _resolve_meta_repository,
        _write_meta_registry,
    )

    repository = repository.strip()
    if not repository:
        raise StateError("repository is required")
    registry = _read_meta_registry(meta_root)
    repo_path, record = _resolve_meta_repository(meta_root, registry, repository)
    registry, record = _register_meta_repository(meta_root, repo_path, registry)
    registry["active"] = record["name"]
    _write_meta_registry(meta_root, registry)
    _ensure_target_pipeline_project(repo_path)
    return _meta_context(meta_root)


def _remove_meta_repository(meta_root: Path, repository: str) -> dict[str, object]:
    from ..cli import (
        _candidate_repo_path,
        _meta_repositories,
        _meta_repository_by_name,
        _read_meta_registry,
        _write_meta_registry,
    )

    repository = repository.strip()
    if not repository:
        raise StateError("repository is required")
    registry = _read_meta_registry(meta_root)
    record = _meta_repository_by_name(registry, repository)
    if record is None:
        candidate_path = _candidate_repo_path(meta_root, repository)
        for repo in _meta_repositories(registry):
            repo_path = Path(str(repo.get("path", ""))).expanduser().resolve()
            if repo_path == candidate_path:
                record = repo
                break
    if record is None:
        raise StateError(f"repository is not registered: {repository}")
    name = str(record.get("name") or "")
    path = Path(str(record.get("path", ""))).expanduser().resolve()
    remaining = [
        repo
        for repo in _meta_repositories(registry)
        if str(repo.get("name") or "") != name
        and Path(str(repo.get("path", ""))).expanduser().resolve() != path
    ]
    registry["repositories"] = remaining
    if registry.get("active") == name:
        registry["active"] = None
    _write_meta_registry(meta_root, registry)
    return _meta_context(meta_root)


def _existing_project_root(path: str) -> Path:
    project_root = _resolve_project_path(path)
    if not project_root.exists():
        raise StateError(f"project directory does not exist: {project_root}")
    if not project_root.is_dir():
        raise StateError(f"project path is not a directory: {project_root}")
    try:
        current_run_id = StateStore(project_root).current_run_id()
    except OSError as error:
        raise StateError(f"could not read ElectroBoy project: {error}") from error
    if not current_run_id:
        raise StateError(
            "no ElectroBoy project exists at this path; create it first"
        )
    return project_root


def _stage_operations(
    stage: str,
    active_project_root: Path | str | None,
) -> list[str]:
    if stage == "project":
        operations = ["Open", "Create"]
        if active_project_root:
            operations.append("Deactivate")
        return operations
    if stage == "requirements" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open requirements",
        ]
    if stage == "design" and active_project_root:
        return ["Set stage", "Start", "Complete", "Open design"]
    if stage == "design-review" and active_project_root:
        return [
            "Set stage",
            "Run automatic review",
            "Run interactive review",
            "Stop review",
            "Approve",
            "Skip approval",
        ]
    if stage == "implementation-plan" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open implementation plan",
        ]
    if stage == "code" and active_project_root:
        return [
            "Set stage",
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Open implementation report",
        ]
    if stage == "test-plan" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open test plan",
        ]
    if stage == "validate" and active_project_root:
        return [
            "Set stage",
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Open validation report",
        ]
    return []


def _status_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["status"])


def _ad_hoc_agent_command(root: Path) -> list[str]:
    return [
        "codex",
        "--cd",
        str(root),
        "--sandbox",
        "workspace-write",
        _ad_hoc_agent_prompt(),
    ]


def _ad_hoc_agent_prompt() -> str:
    return "Here is the code base. Follow what the operator says."


def _project_shell_command() -> list[str]:
    candidates = [
        os.environ.get("SHELL", "").strip(),
        "/bin/bash",
        "/bin/sh",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return [candidate]
    return ["/bin/sh"]


def _electroboy_command(root: Path, args: list[str]) -> list[str]:
    activate_script = root / ".electroboy" / "bin" / "activate"
    command_parts = [
        sys.executable,
        "-m",
        "electroboy",
        "--root",
        str(root),
        *args,
    ]
    command_text = " ".join(shlex.quote(part) for part in command_parts)
    if activate_script.exists():
        module_path = shlex.quote(str(_service_module_search_path()))
        return [
            "/bin/sh",
            "-c",
            f". {shlex.quote(str(activate_script))} >/dev/null && "
            f"PYTHONPATH={module_path}${{PYTHONPATH:+:$PYTHONPATH}} "
            f"{command_text}",
        ]
    return command_parts


def _service_module_search_path() -> Path:
    return Path(__file__).resolve().parents[2]


def _status_snapshot(root: Path | str, timeout: float = 5.0) -> tuple[str, bool]:
    project_root = Path(root).expanduser().resolve()
    try:
        completed = subprocess.run(
            _status_command(project_root),
            cwd=project_root,
            env=_agent_process_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = _subprocess_output_text(error.stdout)
        if output and not output.endswith("\n"):
            output += "\n"
        return f"{output}status command timed out\n", False
    output = completed.stdout or ""
    if completed.returncode != 0:
        if output and not output.endswith("\n"):
            output += "\n"
        output += f"status command exited with code {completed.returncode}\n"
        return output, False
    return output or "status: none\n", True


def _download_name_part(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    text = text.strip(".-")
    return text or "export"


def _handler_for(
    config: ServiceConfig,
    state: ServiceState,
) -> type[BaseHTTPRequestHandler]:
    route_dispatcher = build_route_dispatcher(
        config.module_registry or build_module_registry(),
        config.workflow_registry,
    )
    route_operations: dict[str, Callable[..., Any]] = {
        "service_index": lambda: _apply_service_asset_replacements(
            render_service_index(
                INDEX_HTML_TEMPLATE,
                config.module_registry,
                config.workflow_registry,
            )
        ),
        "health_payload": lambda: health_payload(
            config.root,
            config.module_registry,
            config.workflow_registry,
        ),
        "frontend_asset_payload": lambda: frontend_asset_payload(
            config.module_registry,
            config.workflow_registry,
        ),
        "file_browser_window_html": file_browser_window_html,
    }

    class ElectroBoyRequestHandler(BaseHTTPRequestHandler):
        server_version = "ElectroBoyService/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if self._dispatch_registered_route("GET", path, parsed.query):
                return
            if path == SPLASH_IMAGE_ROUTE:
                self._send_splash_image(SPLASH_IMAGE_RESOURCE)
                return
            if path == CREATIVE_SPLASH_IMAGE_ROUTE:
                self._send_splash_image(CREATIVE_SPLASH_IMAGE_RESOURCE)
                return
            if path.startswith(SERVICE_STATIC_ROUTE_PREFIX):
                self._send_service_asset(path)
                return
            if path.startswith("/pane/"):
                self._send_pane_window(path)
                return
            self._send_json(
                {"error": "not found"},
                status=HTTPStatus.NOT_FOUND,
            )

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if self._dispatch_registered_route("POST", path, parsed.query):
                return
            generic_route = _software_domain()._generic_agent_route(path)
            if generic_route is not None:
                stage, action = generic_route
                self._handle_generic_stage_agent(parsed.query, stage, action)
                return
            self._send_json(
                {"error": "not found"},
                status=HTTPStatus.NOT_FOUND,
            )

        def do_HEAD(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                self._send_headers(
                    HTTPStatus.OK,
                    "text/html; charset=utf-8",
                    len(INDEX_PAGE_HTML.encode("utf-8")),
                )
                return
            if path == SPLASH_IMAGE_ROUTE:
                self._send_splash_image(
                    SPLASH_IMAGE_RESOURCE,
                    headers_only=True,
                )
                return
            if path == CREATIVE_SPLASH_IMAGE_ROUTE:
                self._send_splash_image(
                    CREATIVE_SPLASH_IMAGE_RESOURCE,
                    headers_only=True,
                )
                return
            if path.startswith(SERVICE_STATIC_ROUTE_PREFIX):
                self._send_service_asset(path, headers_only=True)
                return
            if path == "/api/health":
                data = json.dumps(
                    health_payload(
                        config.root,
                        config.module_registry,
                        config.workflow_registry,
                    )
                ).encode("utf-8")
                self._send_headers(
                    HTTPStatus.OK,
                    "application/json; charset=utf-8",
                    len(data),
                )
                return
            self._send_headers(
                HTTPStatus.NOT_FOUND,
                "application/json; charset=utf-8",
                len(b'{"error": "not found"}'),
            )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _dispatch_registered_route(
            self,
            method: str,
            path: str,
            query: str,
        ) -> bool:
            return route_dispatcher.dispatch(
                RouteRequest(
                    method=method,
                    path=path,
                    query=query,
                    state=state,
                    config=config,
                    transport=self,
                    operations=route_operations,
                )
            )

        def _send_splash_image(
            self,
            resource: str = SPLASH_IMAGE_RESOURCE,
            *,
            headers_only: bool = False,
        ) -> None:
            try:
                data = splash_image_bytes(resource)
            except FileNotFoundError:
                self._send_json(
                    {"error": "splash image not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_headers(HTTPStatus.OK, "image/png", len(data))
            if not headers_only:
                self.wfile.write(data)

        def _send_service_asset(
            self,
            path: str,
            *,
            headers_only: bool = False,
        ) -> None:
            relative_path = path.removeprefix(SERVICE_STATIC_ROUTE_PREFIX)
            try:
                data = read_service_binary_asset(
                    relative_path,
                    config.module_registry,
                    config.workflow_registry,
                )
            except FileNotFoundError:
                self._send_json(
                    {"error": "service asset not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            if relative_path in {"index.html", "js/core/runtime.js"}:
                text = data.decode("utf-8")
                data = _apply_service_asset_replacements(text).encode("utf-8")
            self._send_headers(
                HTTPStatus.OK,
                service_asset_content_type(relative_path),
                len(data),
            )
            if not headers_only:
                self.wfile.write(data)

        def _send_pane_window(self, path: str) -> None:
            kind = path.rsplit("/", 1)[-1].strip()
            if kind not in {
                "agent",
                "artifact",
                "progress",
                "scratch",
                "status",
                "input",
                "shell",
            }:
                self._send_json(
                    {"error": "unknown pane"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_text(
                pane_window_html(kind),
                "text/html; charset=utf-8",
            )

        def _handle_generic_stage_agent(
            self,
            query: str,
            stage: str,
            action: str,
        ) -> None:
            if action == "start":
                self._start_generic_stage_agent(query, stage, interactive=None)
                return
            if action == "start-interactive":
                self._start_generic_stage_agent(query, stage, interactive=True)
                return
            if action == "restart":
                self._restart_generic_stage_agent(query, stage)
                return
            if action == "stop":
                self._stop_generic_stage_agent(query, stage)
                return
            if action == "approve":
                self._approve_generic_stage(query, stage, skip_approval=False)
                return
            if action == "skip-approval":
                self._approve_generic_stage(query, stage, skip_approval=True)
                return
            self._send_json(
                {"error": "not found"},
                status=HTTPStatus.NOT_FOUND,
            )

        def _start_generic_stage_agent(
            self,
            query: str,
            stage: str,
            *,
            interactive: bool | None,
        ) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_workflow_stage_agent(
                    context_id,
                    stage,
                    interactive=interactive,
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start {stage}: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                }
            )

        def _restart_generic_stage_agent(self, query: str, stage: str) -> None:
            try:
                context_id = self._context_id(query)
                session, _started = state.restart_workflow_stage_agent(
                    context_id,
                    stage,
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not restart {stage}: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "restarted",
                    "command": session.command,
                }
            )

        def _stop_generic_stage_agent(self, query: str, stage: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.stop_workflow_stage_agent(context_id, stage))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _approve_generic_stage(
            self,
            query: str,
            stage: str,
            *,
            skip_approval: bool,
        ) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(
                    state.approve_workflow_stage(
                        context_id,
                        stage,
                        skip_approval=skip_approval,
                    )
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _stream_session_events(self, session: AgentSession) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_event_id = self._last_event_id()
            try:
                while True:
                    events = session.wait_for_events_after(last_event_id, timeout=15)
                    if not events and session.is_active():
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                    for event in events:
                        event_id = int(event["id"])
                        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                        self.wfile.write(b"event: agent-event\n")
                        self.wfile.write(
                            f"data: {json.dumps(event, sort_keys=True)}\n\n".encode(
                                "utf-8"
                            )
                        )
                        self.wfile.flush()
                        last_event_id = event_id
                    if not session.is_active():
                        break
            except (BrokenPipeError, ConnectionError, OSError):
                return

        def _stream_artifact_events(self, artifact: str, document_path: Path) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_signature: dict[str, object] | None = None
            event_id = 1
            try:
                while True:
                    signature = _file_signature(document_path)
                    if signature != last_signature:
                        payload = {
                            "artifact": artifact,
                            "path": str(document_path),
                            "signature": signature,
                        }
                        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                        self.wfile.write(b"event: artifact-event\n")
                        self.wfile.write(
                            f"data: {json.dumps(payload, sort_keys=True)}\n\n".encode(
                                "utf-8"
                            )
                        )
                        self.wfile.flush()
                        event_id += 1
                        last_signature = signature
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    time.sleep(0.75)
            except (BrokenPipeError, ConnectionError, OSError):
                return

        def _stream_progress_events(
            self,
            context_id: str,
            project_root: Path,
            snapshot_operation: Callable[[Path], tuple[str, bool]],
        ) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_snapshot = ""
            event_id = 1
            try:
                while True:
                    text, ok = snapshot_operation(project_root)
                    running = state.has_running_progress_agent(context_id)
                    payload = {
                        "type": "snapshot" if ok else "error",
                        "text": text,
                        "running": running,
                    }
                    snapshot = json.dumps(payload, sort_keys=True)
                    if snapshot != last_snapshot:
                        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                        self.wfile.write(b"event: progress-event\n")
                        self.wfile.write(f"data: {snapshot}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        event_id += 1
                        last_snapshot = snapshot
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    if not running:
                        break
                    time.sleep(1)
            except (BrokenPipeError, ConnectionError, OSError, StateError):
                return

        def _context_id(self, query: str) -> str:
            params = parse_qs(query)
            return str((params.get("context_id") or [""])[0])

        def _read_json_body(self) -> dict[str, object]:
            try:
                content_length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if content_length <= 0:
                return {}
            body = self.rfile.read(content_length).decode("utf-8")
            if not body.strip():
                return {}
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as error:
                raise ValueError("request body is not valid JSON") from error
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _last_event_id(self) -> int:
            header = self.headers.get("Last-Event-ID", "")
            try:
                return int(header)
            except ValueError:
                return 0

        def _send_download(
            self,
            text: str,
            filename: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            data = text.encode("utf-8")
            safe_name = _download_name_part(filename)
            if not safe_name.endswith(".md"):
                safe_name = f"{safe_name}.md"
            self._send_binary_download(
                data,
                safe_name,
                "text/markdown; charset=utf-8",
                status=status,
            )

        def _send_binary_download(
            self,
            data: bytes,
            filename: str,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            safe_name = _download_name_part(filename)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{safe_name}"',
            )
            self.end_headers()
            self.wfile.write(data)

        def _send_text(
            self,
            text: str,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            data = text.encode("utf-8")
            self._send_headers(status, content_type, len(data))
            self.wfile.write(data)

        def _send_json(
            self,
            payload: dict[str, object],
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            data = json.dumps(payload, sort_keys=True).encode("utf-8")
            self._send_headers(
                status,
                "application/json; charset=utf-8",
                len(data),
            )
            self.wfile.write(data)

        def _send_headers(
            self,
            status: HTTPStatus,
            content_type: str,
            content_length: int,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

    return ElectroBoyRequestHandler
