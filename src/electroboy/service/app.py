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
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from ..models import utc_now
from ..state_store import StateError
from .context import BrowserContext, ContextStore
from .file_watch import file_signature as _file_signature
from .frontend import (
    SERVICE_STATIC_ROUTE_PREFIX,
    frontend_asset_payload,
    read_service_binary_asset,
    read_service_text_asset,
    render_service_index,
    service_asset_content_type,
)
from .http import (
    BinaryResponse,
    HtmlResponse,
    JsonResponse,
    ServiceResponse,
    StreamResponse,
    TextResponse,
)
from .progress_events import progress_issue_events
from .recent_projects import (
    recent_project_entries as _recent_project_entries,
)
from .registry import (
    ModuleRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
    build_module_registry,
    build_workflow_registry,
    installed_workflow_factories,
)
from .routes import RouteOperations, RouteRequest, build_route_dispatcher
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
from .services import build_service_services
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
SERVICE_SESSION_RECORDS_RELATIVE_PATH = (
    Path(".electroboy") / "service" / "sessions.json"
)
SERVICE_SESSION_TRANSCRIPTS_RELATIVE_DIR = (
    Path(".electroboy") / "service" / "session-transcripts"
)


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
        return _apply_service_asset_replacements(read_service_text_asset(name))
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
class ServiceState:
    root: Path
    session_backend: str = SESSION_BACKEND_PTY
    workflow_registry: WorkflowRegistry | None = None
    context_store: ContextStore = field(default_factory=ContextStore)
    workflow_controllers: dict[str, Any] = field(
        init=False,
        default_factory=dict,
    )

    @property
    def lock(self) -> threading.RLock:
        return self.context_store.lock

    @property
    def contexts(self) -> dict[str, BrowserContext]:
        return self.context_store.contexts

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
        controllers = registry.create_controllers(
            build_service_services(self, registry)
        )
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
                context = self.context_store.get_or_create(context_id)
                activation_root = str(entry.get("activation_root") or "").strip()
                active_root = str(entry.get("active_project_root") or "").strip()
                context.activation_root = Path(activation_root) if activation_root else None
                context.active_project_root = Path(active_root) if active_root else None
                context.project_mode = str(entry.get("project_mode") or "project")
                context.workflow_id = (
                    "creative-writing"
                    if context.project_mode == "creative"
                    else "software"
                )
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
        workflows = self.workflow_registry.values() if self.workflow_registry else ()
        workflow_ids = {workflow.id for workflow in workflows}
        workflow_id = (
            "software"
            if "software" in workflow_ids
            else (workflows[0].id if workflows else "")
        )
        context = self.context_store.create(workflow_id=workflow_id)
        return {
            **self.project_payload(context.context_id),
            "status": "created",
        }

    def project_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            active_project_root = context.active_project_root
            workflow_id = context.workflow_id
        payload = project_payload(self.root, context, active_project_root)
        controller = self.workflow_controllers.get(workflow_id)
        extension = getattr(controller, "project_payload_extension", None)
        if callable(extension):
            payload.update(extension(context_id))
        return payload

    def project_mode(self, context_id: str) -> str:
        with self.lock:
            context = self._context_locked(context_id)
            return context.project_mode

    def workflow_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            active_project_root = context.active_project_root
            workflow_id = context.workflow_id
        controller = self.workflow_controllers.get(workflow_id)
        payload_factory = getattr(controller, "workflow_payload", None)
        if callable(payload_factory):
            return payload_factory(context_id)
        workflow = (
            self.workflow_registry.get(workflow_id)
            if self.workflow_registry is not None and workflow_id
            else None
        )
        return workflow_payload(active_project_root, workflow)

    def workflow_context_state(
        self,
        context_id: str,
        workflow_id: str,
    ) -> dict[str, object]:
        """Return state isolated to one registered workflow."""

        if self.workflow_registry is None:
            raise StateError("workflow registry is not configured")
        self.workflow_registry.get(workflow_id)
        with self.lock:
            return self._context_locked(context_id).workflow(workflow_id)

    def module_context_state(
        self,
        context_id: str,
        module_id: str,
    ) -> dict[str, object]:
        """Return state under a module's declared namespace."""

        if self.workflow_registry is None:
            raise StateError("workflow registry is not configured")
        module = self.workflow_registry.modules.get(module_id)
        namespace = module.state_namespace or module.id
        with self.lock:
            return self._context_locked(context_id).module(namespace)

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
        with self.lock:
            workflow_id = self._context_locked(context_id).workflow_id
        controller = self.workflow_controller(workflow_id)
        select_stage = getattr(controller, "select_workflow_stage", None)
        if not callable(select_stage):
            raise StateError(
                f"workflow does not support stage selection: {workflow_id}"
            )
        return select_stage(context_id, stage)

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
        return self.workflow_controller("software").open_project(context_id, path)

    def create_project(self, context_id: str, path: str) -> dict[str, object]:
        return self.workflow_controller("software").create_project(context_id, path)

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
        return self.workflow_controller("software").open_meta_project(
            context_id,
            path,
        )

    def create_meta_project(self, context_id: str, path: str) -> dict[str, object]:
        return self.workflow_controller("software").create_meta_project(
            context_id,
            path,
        )

    def add_meta_repository(self, context_id: str, path: str) -> dict[str, object]:
        return self.workflow_controller("software").add_meta_repository(
            context_id,
            path,
        )

    def start_meta_repository(self, context_id: str, repository: str) -> dict[str, object]:
        return self.workflow_controller("software").start_meta_repository(
            context_id,
            repository,
        )

    def remove_meta_repository(self, context_id: str, repository: str) -> dict[str, object]:
        return self.workflow_controller("software").remove_meta_repository(
            context_id,
            repository,
        )

    def deactivate_project(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            sessions = self._context_process_sessions_locked(context)
        self._terminate_sessions(sessions)
        with self.lock:
            context = self._context_locked(context_id)
            context.reset_project(
                workflow_id=context.workflow_id,
                project_mode="none",
                activation_root=None,
                active_project_root=None,
            )
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

    def current_project_shell_session(
        self,
        context_id: str,
        session_id: str = "",
    ) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            if session_id:
                return context.project_shell_sessions.get(session_id)
            return context.project_shell_session

    def start_project_shell(self, context_id: str) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            session = AgentSession(
                command=_project_shell_command(),
                cwd=project_root,
                label="project shell",
                kind="project-shell",
                interactive=True,
                echo_input=True,
                controlling_terminal=True,
            )
            session = self._prepare_session_locked(context, session)
            context.project_shell_sessions[session.session_id] = session
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                context.project_shell_sessions.pop(session.session_id, None)
            raise
        return session, True

    def send_project_shell_input(
        self,
        context_id: str,
        data: str,
        session_id: str = "",
    ) -> None:
        session = self.current_project_shell_session(context_id, session_id)
        if session is None:
            raise AgentSessionError("project shell has not been started")
        session.send_raw(data)

    def resize_project_shell(
        self,
        context_id: str,
        columns: int,
        rows: int,
        session_id: str = "",
    ) -> None:
        session = self.current_project_shell_session(context_id, session_id)
        if session is None:
            raise AgentSessionError("project shell has not been started")
        session.resize(columns, rows)

    def stop_project_shell(
        self,
        context_id: str,
        session_id: str = "",
    ) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            session = (
                context.project_shell_sessions.get(session_id)
                if session_id
                else context.project_shell_session
            )
            if session is not None:
                context.project_shell_sessions.pop(session.session_id, None)
            project_root = context.active_project_root
        if session is None:
            raise AgentSessionError("project shell is not running")
        if session.is_active():
            session.terminate(timeout=0.5)
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
        return [
            *self._context_sessions_locked(context),
            *context.project_shell_sessions.values(),
        ]

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
            for shell_id, shell_session in list(
                context.project_shell_sessions.items()
            ):
                if shell_session is session:
                    context.project_shell_sessions.pop(shell_id, None)
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
        try:
            return self.context_store.require(context_id)
        except KeyError:
            raise StateError("unknown browser context; refresh the page")

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
            context.project_shell_sessions[session.session_id] = session
        else:
            workflow = (
                self.workflow_registry.get(context.workflow_id)
                if self.workflow_registry is not None and context.workflow_id
                else None
            )
            stage_ids = {
                stage.id for stage in workflow.stages
            } if workflow is not None else set()
            if session.kind in stage_ids:
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
        modules = module_registry.values()
        payload["modules"] = [module.id for module in modules]
    else:
        modules = ()
    if workflow_registry is not None:
        workflows = workflow_registry.values()
        payload["workflows"] = [workflow.id for workflow in workflows]
    else:
        workflows = ()
    payload["plugins"] = {
        "modules": [
            {
                "id": module.id,
                "provider": module.provider,
                "entry_point": module.entry_point,
            }
            for module in modules
        ],
        "workflows": [
            {
                "id": workflow.id,
                "provider": workflow.provider,
                "entry_point": workflow.entry_point,
            }
            for workflow in workflows
        ],
    }
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
    project_shell_running = bool(
        active_root
        and any(
            session.is_active()
            for session in context.project_shell_sessions.values()
        )
    )
    workflow_stage = context.workflow_stage or "project"
    return {
        "context_id": context.context_id,
        "workflow_id": context.workflow_id,
        "service_root": str(service_root),
        "activation_root": str(activation_root) if activation_root else None,
        "project_mode": context.project_mode,
        "active_project_root": str(active_root) if active_root else None,
        "active_repository_name": context.active_repository_name,
        "registered_repositories": context.registered_repositories,
        "workflow_stage": workflow_stage,
        "documentation_running": documentation_running,
        "creative_writing_running": creative_running,
        "ad_hoc_running": ad_hoc_running,
        "project_shell_running": project_shell_running,
        "activate_command": (
            f"source {activation_root / '.electroboy' / 'bin' / 'activate'}"
            if activation_root and context.project_mode != "creative"
            else None
        ),
        "selected_session_id": context.selected_session_id,
        "sessions": _session_payloads(context),
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


def workflow_payload(
    active_project_root: Path | str | None = None,
    workflow: WorkflowDefinition | None = None,
) -> dict[str, object]:
    if workflow is None:
        factories = installed_workflow_factories()
        factory = factories.get("software") or next(iter(factories.values()), None)
        workflow = factory() if factory is not None else None
    if workflow is None:
        return {"stages": []}
    operations_factory = workflow.stage_operations_factory
    return {
        "stages": [
            {
                "id": stage.id,
                "label": stage.label,
                "operations": (
                    operations_factory(stage.id, active_project_root)
                    if operations_factory is not None
                    else (
                        ["Open", "Create"]
                        if stage.id == "project" and not active_project_root
                        else (
                            ["Open", "Create", "Deactivate"]
                            if stage.id == "project"
                            else []
                        )
                    )
                ),
            }
            for stage in workflow.stages
        ]
    }


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
    route_services = build_service_services(
        state,
        config.workflow_registry or build_workflow_registry(
            config.module_registry or build_module_registry()
        ),
    )
    route_dispatcher = build_route_dispatcher(
        config.module_registry or build_module_registry(),
        config.workflow_registry,
    )
    route_operations = RouteOperations(
        service_index_factory=lambda: _apply_service_asset_replacements(
            render_service_index(
                INDEX_HTML_TEMPLATE,
                config.module_registry,
                config.workflow_registry,
            )
        ),
        health_payload_factory=lambda: health_payload(
            config.root,
            config.module_registry,
            config.workflow_registry,
        ),
        frontend_asset_payload_factory=lambda: frontend_asset_payload(
            config.module_registry,
            config.workflow_registry,
        ),
        file_browser_factory=file_browser_window_html,
    )

    class ElectroBoyRequestHandler(BaseHTTPRequestHandler):
        server_version = "ElectroBoyService/0.1"

        def read_json_body(self) -> dict[str, object]:
            return self._read_json_body()

        def stream_session_events(self, session: AgentSession) -> None:
            self._stream_session_events(session)

        def stream_artifact_events(self, artifact: str, path: Path) -> None:
            self._stream_artifact_events(artifact, path)

        def stream_progress_events(
            self,
            context_id: str,
            root: Path,
            snapshot: Callable[[Path], tuple[str, bool]],
        ) -> None:
            self._stream_progress_events(context_id, root, snapshot)

        def emit_response(self, response: ServiceResponse) -> None:
            if isinstance(response, JsonResponse):
                self._send_json(response.payload, status=response.status)
                return
            if isinstance(response, HtmlResponse):
                self._send_text(
                    response.body,
                    "text/html; charset=utf-8",
                    status=response.status,
                )
                return
            if isinstance(response, TextResponse):
                self._send_text(
                    response.body,
                    response.content_type,
                    status=response.status,
                )
                return
            if isinstance(response, BinaryResponse):
                if response.filename:
                    self._send_binary_download(
                        response.data,
                        response.filename,
                        response.content_type,
                        status=response.status,
                    )
                    return
                self._send_headers(
                    response.status,
                    response.content_type,
                    len(response.data),
                )
                self.wfile.write(response.data)
                return
            if isinstance(response, StreamResponse):
                response.stream()
                return
            raise TypeError(f"unsupported service response: {type(response)!r}")

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
                    services=route_services,
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
            if relative_path.endswith((".html", ".js", ".css")):
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
            emitted_issues: set[tuple[str, str]] = set()
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
                        for issue in progress_issue_events(text):
                            issue_key = (
                                str(issue["severity"]),
                                str(issue["summary"]),
                            )
                            if issue_key in emitted_issues:
                                continue
                            issue_payload = json.dumps(issue, sort_keys=True)
                            self.wfile.write(
                                f"id: {event_id}\n".encode("utf-8")
                            )
                            self.wfile.write(b"event: progress-issue\n")
                            self.wfile.write(
                                f"data: {issue_payload}\n\n".encode("utf-8")
                            )
                            self.wfile.flush()
                            event_id += 1
                            emitted_issues.add(issue_key)
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
