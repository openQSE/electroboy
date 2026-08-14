"""Local browser service for ElectroBoy."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import html
import io
import json
import os
import pty
import re
import shutil
import signal
import shlex
import struct
import subprocess
import sys
import termios
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .frontend import frontend_asset_payload, read_service_text_asset
from .registry import (
    ModuleRegistry,
    WorkflowRegistry,
    build_module_registry,
    build_workflow_registry,
    registry_payload,
)
from ..artifacts import ArtifactManager
from ..document_export import (
    DocumentExportError,
    export_markdown_document,
)
from ..feature_artifacts import (
    artifact_paths_for_run,
    read_feature_record,
    resolve_artifact_path,
)
from ..models import (
    ActivityEvent,
    GATE_DESIGN,
    STAGE_COMPLETE,
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_DOCS_REVIEW,
    STAGE_IMPLEMENTATION,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    STAGE_TEST_PLAN,
    STAGE_VALIDATION,
    utc_now,
)
from ..state_store import StateError, StateStore
from ..structured_artifacts import (
    ARTIFACT_DEFAULT_MARKDOWN_PATHS,
    ARTIFACT_TITLES,
    artifact_jsonl_path,
    artifact_markdown_path,
    import_artifact,
    read_artifact_records,
    render_artifact,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SPLASH_IMAGE_ROUTE = "/assets/electroboy-splash-16x9.png"
CREATIVE_SPLASH_IMAGE_ROUTE = "/assets/electroboy-splash-creative-writing-16x9.png"
SPLASH_IMAGE_PACKAGE = "electroboy"
SPLASH_IMAGE_RESOURCE = "electroboy-splash-16x9.png"
CREATIVE_SPLASH_IMAGE_RESOURCE = "electroboy-splash-creative-writing-16x9.png"
TERMINAL_SUBMIT_DELAY_SECONDS = 0.08
MIN_TERMINAL_COLUMNS = 20
MAX_TERMINAL_COLUMNS = 1000
MIN_TERMINAL_ROWS = 5
MAX_TERMINAL_ROWS = 120
META_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "repositories.json"
WORK_ITEM_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "work-items.json"
CREATIVE_DEFAULT_FOLDERS = (
    "chapters",
    "scratchpad",
    "characters",
    "corkboard",
    "reviews",
    "research",
)
CREATIVE_SCRATCHPAD_PATH = "scratchpad/scratchpad.md"
CREATIVE_IGNORED_NAMES = frozenset({".git", ".electroboy", "__pycache__"})
CREATIVE_CORKBOARD_SUFFIX = ".corkboard.json"
CREATIVE_CORKBOARD_GROUP_DIRECTORY = Path("corkboard") / "groups"
CREATIVE_CORKBOARD_STATE_RELATIVE_PATH = (
    Path(".electroboy") / "creative" / "corkboards.json"
)
RECENT_PROJECTS_RELATIVE_PATH = Path(".electroboy") / "service" / "recent-projects.json"
RECENT_PROJECT_LIMIT = 12
SERVICE_SESSION_RECORDS_RELATIVE_PATH = (
    Path(".electroboy") / "service" / "sessions.json"
)
SERVICE_SESSION_TRANSCRIPTS_RELATIVE_DIR = (
    Path(".electroboy") / "service" / "session-transcripts"
)
SESSION_BACKEND_ENV = "ELECTROBOY_SESSION_BACKEND"
SESSION_BACKEND_PTY = "pty"
SESSION_BACKEND_TMUX = "tmux"
CREATIVE_CARD_PALETTE: tuple[dict[str, str], ...] = (
    {"id": "butter", "label": "Butter", "value": "#fff6cf"},
    {"id": "rose", "label": "Rose", "value": "#f9e7dd"},
    {"id": "sky", "label": "Sky", "value": "#e6f0ff"},
    {"id": "mint", "label": "Mint", "value": "#e8f7e6"},
    {"id": "lilac", "label": "Lilac", "value": "#f1e9ff"},
    {"id": "peach", "label": "Peach", "value": "#ffe8cc"},
    {"id": "slate", "label": "Slate", "value": "#e9edf5"},
)
CREATIVE_CARD_PALETTE_IDS = frozenset(entry["id"] for entry in CREATIVE_CARD_PALETTE)
CREATIVE_CARD_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")

_CONTROL_CHARS_TO_DROP = frozenset(
    chr(code)
    for code in [*range(0x00, 0x08), *range(0x0B, 0x0D), *range(0x0E, 0x20), 0x7F]
)

WORKFLOW_STAGES = [
    "project",
    "requirements",
    "design",
    "design-review",
    "implementation-plan",
    "code",
    "test-plan",
    "validate",
    "document",
]

APPROVAL_WORKFLOW_STAGES = frozenset(
    {
        "requirements-approve",
        "design-approve",
        "plan-approve",
        "code-approve",
        "test-plan-approve",
        "validation-approve",
    }
)

APPROVAL_STAGE_OWNERS = {
    "requirements-approve": "requirements",
    "design-approve": "design-review",
    "plan-approve": "implementation-plan",
    "code-approve": "code",
    "test-plan-approve": "test-plan",
    "validation-approve": "validate",
}

DURABLE_STAGE_OWNERS = {
    STAGE_DESIGN_ACCEPTANCE: "design-review",
    STAGE_PLAN: "implementation-plan",
    STAGE_IMPLEMENTATION: "code",
    STAGE_TEST_PLAN: "test-plan",
    STAGE_VALIDATION: "validate",
    STAGE_DOCS_REVIEW: "document",
    STAGE_COMPLETE: "document",
}

SESSION_ARTIFACT_LOCKS = {
    "requirements": frozenset({"docs/requirements.md", "docs/requirements.jsonl"}),
    "design": frozenset({"docs/detailed-design.md", "docs/detailed-design.jsonl"}),
    "design-review": frozenset(
        {
            "docs/detailed-design.md",
            "docs/detailed-design.jsonl",
            "design-review.jsonl",
        }
    ),
    "implementation-plan": frozenset(
        {"docs/implementation-plan.md", "docs/implementation-plan.jsonl"}
    ),
    "code": frozenset(
        {
            "docs/implementation-log.md",
            "docs/implementation-report.md",
        }
    ),
    "test-plan": frozenset({"docs/test-plan.md", "docs/test-plan.jsonl"}),
    "validate": frozenset(
        {
            "docs/test-review.md",
            "docs/validation-report.md",
            "validation-test-review.jsonl",
            "validation-review.jsonl",
        }
    ),
    "documentation": frozenset(),
}

GENERIC_STAGE_CONFIG: dict[str, dict[str, object]] = {
    "implementation-plan": {
        "command": "implementation-plan",
        "approval_command": "plan-approve",
        "artifact_path": "docs/implementation-plan.md",
        "artifact_title": "Implementation Plan",
        "interactive_default": True,
        "interactive_arg": False,
        "reason_arg": True,
        "approval_reason_arg": True,
        "next_stage": "code",
    },
    "code": {
        "command": "code",
        "approval_command": "code-approve",
        "artifact_path": "docs/implementation-report.md",
        "artifact_title": "Implementation Report",
        "interactive_default": False,
        "interactive_arg": True,
        "reason_arg": True,
        "approval_reason_arg": False,
        "next_stage": "test-plan",
    },
    "test-plan": {
        "command": "test-plan",
        "approval_command": "test-plan-approve",
        "artifact_path": "docs/test-plan.md",
        "artifact_title": "Test Plan",
        "interactive_default": True,
        "interactive_arg": False,
        "reason_arg": True,
        "approval_reason_arg": True,
        "next_stage": "validate",
    },
    "validate": {
        "command": "validate",
        "approval_command": "validation-approve",
        "artifact_path": "docs/validation-report.md",
        "artifact_title": "Validation Report",
        "interactive_default": False,
        "interactive_arg": True,
        "reason_arg": False,
        "approval_reason_arg": True,
        "next_stage": "document",
    },
}

WORKFLOW_STAGE_RESET_TARGETS = {
    "requirements": STAGE_REQUIREMENTS,
    "design": STAGE_DESIGN,
    "design-review": STAGE_DESIGN_REVIEW,
    "implementation-plan": STAGE_PLAN,
    "code": STAGE_IMPLEMENTATION,
    "test-plan": STAGE_TEST_PLAN,
    "validate": STAGE_VALIDATION,
}

ARTIFACT_EVENT_ROUTE_PATHS = {
    "/artifacts/requirements": "docs/requirements.md",
    "/artifacts/design": "docs/detailed-design.md",
    "/artifacts/design-review": "docs/design-review.md",
    "/artifacts/implementation-plan": "docs/implementation-plan.md",
    "/artifacts/implementation-report": "docs/implementation-report.md",
    "/artifacts/test-plan": "docs/test-plan.md",
    "/artifacts/validation-report": "docs/validation-report.md",
}

STRUCTURED_ARTIFACT_BY_MARKDOWN_PATH = {
    path: artifact
    for artifact, path in ARTIFACT_DEFAULT_MARKDOWN_PATHS.items()
}

ARTIFACT_EDITOR_LIST_FIELDS = {
    "acceptance_criteria",
    "commit_tasks",
    "consequences",
    "dependencies",
    "design_sections",
    "expected_results",
    "exit_criteria",
    "implementation_units",
    "interfaces",
    "out_of_scope",
    "paths",
    "personas",
    "plan_tasks",
    "preconditions",
    "requirements",
    "scope",
    "steps",
    "verification",
}

ARTIFACT_EDITOR_JSON_FIELDS = {"automation", "schema"}


INDEX_HTML_TEMPLATE = read_service_text_asset("index.html")

INDEX_HTML = (
    INDEX_HTML_TEMPLATE.replace("__SPLASH_IMAGE_ROUTE__", SPLASH_IMAGE_ROUTE)
    .replace("__CREATIVE_SPLASH_IMAGE_ROUTE__", CREATIVE_SPLASH_IMAGE_ROUTE)
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
    lock: threading.Lock = field(default_factory=threading.Lock)
    contexts: dict[str, BrowserContext] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.session_backend = _normalize_session_backend(self.session_backend)
        (self.root / SERVICE_SESSION_TRANSCRIPTS_RELATIVE_DIR).mkdir(
            parents=True,
            exist_ok=True,
        )
        if self.session_backend == SESSION_BACKEND_TMUX:
            self._restore_tmux_sessions()

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
        collection_name = name.strip()
        if not collection_name:
            raise StateError("feature collection name is required")
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            self._require_no_active_agent_locked(context)
        registry = _load_work_item_registry(project_root)
        collection = _upsert_feature_collection(registry, collection_name)
        registry["active_collection_id"] = collection["id"]
        _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "created collection",
            "label": collection["name"],
        }

    def switch_feature_collection(
        self,
        context_id: str,
        collection_id: str,
    ) -> dict[str, object]:
        collection_id = collection_id.strip()
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            self._require_no_active_agent_locked(context)
        registry = _load_work_item_registry(project_root)
        collection = _feature_collection_by_id(registry, collection_id)
        if collection is None:
            raise StateError("unknown feature collection")
        registry["active_collection_id"] = collection["id"]
        _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "switched collection",
            "label": collection["name"],
        }

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
        title = title.strip()
        if not title:
            raise AgentSessionError("feature title is required")
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        terminated_agent = self._terminate_workflow_sessions(context_id)
        output = _run_feature_start_context(
            project_root,
            title=title,
            feature_name=feature_name,
            amend=True,
            branch=branch,
            stash_subrepo_changes=stash_subrepo_changes,
        )
        registry = _load_work_item_registry(project_root)
        feature_record = _current_feature_record(project_root)
        if feature_record is not None:
            effective_collection_id = (
                collection_id if collection_id or parent_slug else "default"
            )
            collection = _ensure_collection_for_feature(
                registry,
                effective_collection_id,
                parent_slug=parent_slug,
            )
            _upsert_feature_record(
                registry,
                feature_record,
                collection_id=str(collection["id"]),
                parent_slug=parent_slug,
            )
            registry["active_collection_id"] = collection["id"]
            registry["active_feature_slug"] = feature_record.get("slug")
            registry["active_bug_slug"] = None
            _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = _active_workflow_stage(project_root)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "started feature",
            "label": _feature_record_label(feature_record) if feature_record else title,
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def switch_feature_work_item(
        self,
        context_id: str,
        slug: str,
    ) -> dict[str, object]:
        slug = slug.strip()
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        registry = _load_work_item_registry(project_root)
        feature = _feature_by_slug(registry, slug)
        if feature is None:
            raise AgentSessionError("unknown feature")
        terminated_agent = self._terminate_workflow_sessions(context_id)
        output = _run_feature_start_context(
            project_root,
            title=str(feature.get("input") or feature.get("title") or slug),
            feature_name=str(feature.get("name") or slug),
            amend=True,
            branch=bool(feature.get("branch")),
            branch_name=(
                str(feature.get("branch"))
                if isinstance(feature.get("branch"), str)
                and str(feature.get("branch")).strip()
                else None
            ),
        )
        feature_record = _current_feature_record(project_root)
        if feature_record is not None:
            _upsert_feature_record(
                registry,
                feature_record,
                collection_id=str(feature.get("collection_id") or ""),
                parent_slug=(
                    str(feature.get("parent_slug"))
                    if feature.get("parent_slug")
                    else None
                ),
            )
        registry["active_feature_slug"] = slug
        registry["active_bug_slug"] = None
        if feature.get("collection_id"):
            registry["active_collection_id"] = feature.get("collection_id")
        _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = _active_workflow_stage(project_root)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "switched feature",
            "label": _feature_record_label(feature),
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def start_bug_work_item(
        self,
        context_id: str,
        *,
        issue_reference: str,
        branch: bool = False,
        stash_subrepo_changes: bool = False,
    ) -> dict[str, object]:
        issue_reference = issue_reference.strip()
        if not issue_reference:
            raise AgentSessionError("bug issue reference is required")
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        terminated_agent = self._terminate_workflow_sessions(context_id)
        output = _run_bug_start_context(
            project_root,
            issue_reference=issue_reference,
            branch=branch,
            stash_subrepo_changes=stash_subrepo_changes,
        )
        registry = _load_work_item_registry(project_root)
        bug_record = _current_bug_record(project_root)
        if bug_record is not None:
            _upsert_bug_record(registry, bug_record)
            registry["active_bug_slug"] = bug_record.get("slug")
            registry["active_feature_slug"] = None
            _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "started bug resolution",
            "label": _bug_record_label(bug_record) if bug_record else issue_reference,
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def switch_bug_work_item(
        self,
        context_id: str,
        slug: str,
    ) -> dict[str, object]:
        slug = slug.strip()
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        registry = _load_work_item_registry(project_root)
        bug = _bug_by_slug(registry, slug)
        if bug is None:
            raise AgentSessionError("unknown bug")
        terminated_agent = self._terminate_workflow_sessions(context_id)
        _write_current_bug_record(project_root, bug)
        registry["active_bug_slug"] = slug
        registry["active_feature_slug"] = None
        _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "switched bug resolution",
            "label": _bug_record_label(bug),
            "terminated_agent": terminated_agent,
        }

    def select_workflow_stage(
        self,
        context_id: str,
        stage: str,
    ) -> dict[str, object]:
        stage = stage.strip()
        if stage in APPROVAL_WORKFLOW_STAGES:
            raise StateError(f"approval stage is not directly selectable: {stage}")
        if stage == "project" or stage not in WORKFLOW_STAGES:
            raise StateError(f"unknown workflow stage: {stage}")
        target_stage = WORKFLOW_STAGE_RESET_TARGETS.get(stage)
        if target_stage is None:
            raise StateError(f"stage cannot be set directly: {stage}")
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            previous_stage = context.workflow_stage
            sessions = (
                self._context_sessions_locked(context)
                if previous_stage != stage
                else []
            )
        terminated_agent = False
        if sessions:
            terminated_agent = self._terminate_sessions(sessions)
        reset_decision = None
        reset_output = ""
        if previous_stage != stage:
            reset_decision, reset_output = _force_reset_workflow_stage(
                project_root,
                stage,
                target_stage,
            )
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = stage
            self._clear_sessions_locked(context, sessions)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "selected",
            "previous_stage": previous_stage,
            "terminated_agent": terminated_agent,
            "reset_decision": reset_decision,
            "reset_output": reset_output,
        }

    def approve_requirements(
        self,
        context_id: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage not in {"requirements", "requirements-approve"}:
                raise AgentSessionError("requirements stage is not active")
            requirements_started = context.requirements_started
        self._terminate_requirements_session(context_id)
        _record_requirements_complete(project_root, skipped=skip_approval)
        from ..cli import _cmd_stage, _stage_args
        from ..gates import GateEngine

        stdout = io.StringIO()
        stderr = io.StringIO()
        store = StateStore(project_root)
        engine = GateEngine(project_root)
        previously_approved = _stage_has_approvals(
            project_root,
            STAGE_REQUIREMENTS,
            ["human-approval", "author-confirmation"],
        )
        if skip_approval:
            force_approval = True
            reason = (
                "Requirements approval was skipped from the GUI during an "
                "update after a previous requirements approval."
                if previously_approved
                else "WARNING: requirements approval was skipped from the GUI. "
                "The operator accepted the risk that requirements were not "
                "explicitly approved."
            )
        else:
            force_approval = _should_force_completed_requirements_approval(store)
            reason = (
                "Requirements authoring was completed from the GUI without "
                "agent confirmation; approval "
                "force-records the missing author confirmation."
                if force_approval
                else None
            )
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_REQUIREMENTS,
                    human=True,
                    author=True,
                    force=force_approval,
                    reason=reason,
                ),
            )
        output = "\n".join(
            part.strip() for part in [stderr.getvalue(), stdout.getvalue()] if part.strip()
        )
        if code != 0:
            raise AgentSessionError(output or "requirements approval failed")
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = "design"
            context.requirements_session = None
            context.requirements_started = requirements_started
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": "design",
            "output": output,
            "warning": (
                "WARNING: requirements approval was skipped; advancing to design "
                "with forced approval records."
                if skip_approval and not previously_approved
                else None
            ),
        }

    def open_project(self, context_id: str, path: str) -> dict[str, object]:
        if _is_meta_project_path(path):
            return self.open_meta_project(context_id, path)
        project_root = _existing_project_root(path)
        workflow_stage = _active_workflow_stage(project_root)
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
            context.workflow_stage = _visible_workflow_stage(manifest.active_stage)
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
        project_root = _existing_creative_project_root(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        _ensure_creative_workspace(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = project_root
            context.project_mode = "creative"
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
            context.workflow_stage = "project"
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "creative")
        return {
            **project_payload(self.root, context, project_root),
            "status": "opened",
        }

    def create_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _resolve_project_path(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        project_root.mkdir(parents=True, exist_ok=True)
        _ensure_creative_workspace(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = project_root
            context.project_mode = "creative"
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
            context.workflow_stage = "project"
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "creative")
        return {
            **project_payload(self.root, context, project_root),
            "status": "created",
        }

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
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "requirements" and not allow_stage_reopen:
                raise AgentSessionError("requirements stage is not active")
            if (
                context.requirements_session is not None
                and context.requirements_session.is_active()
            ):
                return context.requirements_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["requirements"]
            self._require_session_locks_available_locked(context, lock_names)
            session = AgentSession(
                command=_requirements_command(command_root),
                cwd=command_root,
                label="requirements agent",
                kind="requirements",
                interactive=True,
                lock_names=lock_names,
            )
            session = self._prepare_session_locked(context, session)
            context.requirements_session = session
            context.selected_session_id = session.session_id
            context.workflow_stage = "requirements"
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.requirements_session is session:
                    context.requirements_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.requirements_started = False
            raise
        with self.lock:
            context = self._context_locked(context_id)
            if context.requirements_session is session:
                context.requirements_started = True
        return session, True

    def restart_requirements_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.workflow_stage == "requirements"
                and not context.requirements_started
            ):
                raise AgentSessionError("start requirements first")
        self._terminate_requirements_session(context_id)
        _reopen_requirements_for_restart(project_root)
        return self.start_requirements_agent(context_id, allow_stage_reopen=True)

    def complete_requirements_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_requirements(context_id)

    def skip_requirements_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_requirements(context_id, skip_approval=True)

    def start_design_agent(
        self,
        context_id: str,
        *,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design" and not allow_stage_reopen:
                raise AgentSessionError("design stage is not active")
            if (
                context.design_session is not None
                and context.design_session.is_active()
            ):
                return context.design_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["design"]
            self._require_session_locks_available_locked(context, lock_names)
            session = AgentSession(
                command=_stage_command(command_root, "design"),
                cwd=command_root,
                label="design agent",
                kind="design",
                interactive=True,
                lock_names=lock_names,
            )
            session = self._prepare_session_locked(context, session)
            context.design_session = session
            context.selected_session_id = session.session_id
            context.workflow_stage = "design"
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.design_session is session:
                    context.design_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.design_started = False
            raise
        with self.lock:
            context = self._context_locked(context_id)
            if context.design_session is session:
                context.design_started = True
        return session, True

    def restart_design_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage == "design":
                raise AgentSessionError("design stage is already active")
        self._terminate_workflow_sessions(context_id)
        _reopen_design_for_restart(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.design_review_started = False
            context.design_review_interactive = False
        return self.start_design_agent(context_id, allow_stage_reopen=True)

    def complete_design_agent(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design":
                raise AgentSessionError("design stage is not active")
            design_started = context.design_started
        self._terminate_design_session(context_id)
        _record_design_complete(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = "design-review"
            context.design_session = None
            context.design_started = design_started
            context.design_review_session = None
            context.design_review_started = False
            context.design_review_interactive = False
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "completed",
            "next_stage": "design-review",
        }

    def start_design_review_agent(
        self,
        context_id: str,
        *,
        force: bool = False,
        allow_stage_reopen: bool = False,
        interactive: bool = False,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design-review" and not allow_stage_reopen:
                raise AgentSessionError("design review stage is not active")
            if (
                context.design_review_session is not None
                and context.design_review_session.is_active()
            ):
                return context.design_review_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["design-review"]
            self._require_session_locks_available_locked(context, lock_names)
            session = AgentSession(
                command=_stage_command(
                    command_root,
                    "design-review",
                    force=force,
                    interactive=interactive,
                ),
                cwd=command_root,
                label=(
                    "interactive design-review agent"
                    if interactive
                    else "design-review agent"
                ),
                kind="design-review",
                interactive=interactive,
                lock_names=lock_names,
                on_completed=(
                    None
                    if interactive
                    else lambda returncode: self._mark_design_review_completed(
                        context_id,
                        returncode,
                    )
                ),
            )
            session = self._prepare_session_locked(context, session)
            context.design_review_session = session
            context.selected_session_id = session.session_id
            context.design_review_interactive = interactive
            context.workflow_stage = "design-review"
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.design_review_session is session:
                    context.design_review_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.design_review_started = False
                    context.design_review_interactive = False
            raise
        with self.lock:
            context = self._context_locked(context_id)
            if context.design_review_session is session:
                context.design_review_started = True
        return session, True

    def restart_design_review_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            force = context.workflow_stage != "design-review"
            if context.workflow_stage == "design-review" and not context.design_review_started:
                raise AgentSessionError("start design review first")
        self._terminate_workflow_sessions(context_id)
        return self.start_design_review_agent(
            context_id,
            force=force,
            allow_stage_reopen=True,
        )

    def start_documentation_agent(
        self,
        context_id: str,
        *,
        interactive: bool = True,
        target: str | None = None,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            target_path = (target or "").strip()
            if target_path:
                target_path = _ensure_document_target(project_root, target_path)
            session_key = target_path or "__default__"
            existing_session = context.documentation_sessions.get(session_key)
            if existing_session is not None and existing_session.is_active():
                context.selected_session_id = existing_session.session_id
                return existing_session, False
            lock_names = frozenset({f"documentation:{session_key}"})
            self._require_session_locks_available_locked(context, lock_names)
            label_target = f" ({target_path})" if target_path else ""
            document_label = Path(target_path).name if target_path else "Documentation"
            session = AgentSession(
                command=_documentation_command(
                    command_root,
                    interactive=interactive,
                    target=target_path or None,
                ),
                cwd=command_root,
                label=(
                    f"interactive documentation agent{label_target}"
                    if interactive
                    else f"documentation agent{label_target}"
                ),
                kind="documentation",
                interactive=interactive,
                lock_names=lock_names,
                metadata={
                    "document_path": target_path,
                    "document_label": document_label,
                },
            )
            session = self._prepare_session_locked(context, session)
            context.documentation_sessions[session_key] = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.documentation_sessions.get(session_key) is session:
                    context.documentation_sessions.pop(session_key, None)
                    context.selected_session_id = None
            raise
        return session, True

    def initialize_creative_workspace(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        _ensure_creative_workspace(project_root)
        return self.creative_tree(context_id)

    def creative_tree(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        return _creative_tree_payload(project_root)

    def create_creative_folder(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _create_creative_folder(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def create_creative_document(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _create_creative_document(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def create_creative_corkboard(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _create_creative_corkboard(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def rename_creative_entry(
        self,
        context_id: str,
        relative_path: str,
        new_name: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        old_path, new_path = _rename_creative_entry(
            project_root,
            relative_path,
            new_name,
        )
        return {
            "status": "renamed",
            "old_path": old_path,
            "path": new_path,
        }

    def delete_creative_entry(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _delete_creative_entry(project_root, relative_path)
        return {
            "status": "deleted",
            "path": path,
        }

    def creative_scratchpad(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _ensure_creative_scratchpad(project_root)
        return {
            "path": path.relative_to(project_root).as_posix(),
            "markdown": path.read_text(encoding="utf-8"),
        }

    def save_creative_scratchpad(
        self,
        context_id: str,
        markdown: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _ensure_creative_scratchpad(project_root)
        path.write_text(markdown, encoding="utf-8")
        return {
            "status": "saved",
            "path": path.relative_to(project_root).as_posix(),
        }

    def save_creative_corkboard(
        self,
        context_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        board_type = str(payload.get("board_type") or "folder")
        if board_type == "folder" and "order" in payload:
            order = payload.get("order")
            if not isinstance(order, list):
                raise StateError("folder corkboard order must be a list")
            saved_order = _save_creative_folder_corkboard_order(
                project_root,
                folder_path=str(payload.get("folder") or ""),
                order=[str(item) for item in order],
            )
            return {
                "status": "saved",
                "order": saved_order,
            }
        if board_type == "folder":
            card = _save_creative_folder_corkboard_card(
                project_root,
                folder_path=str(payload.get("folder") or ""),
                card_path=str(payload.get("path") or ""),
                note=str(payload.get("note") or ""),
                color=payload.get("color"),
            )
            return {
                "status": "saved",
                "card": card,
            }
        if board_type == "freeform":
            if str(payload.get("action") or "") == "delete":
                card_id = _delete_creative_freeform_corkboard_card(
                    project_root,
                    corkboard_path=str(payload.get("corkboard") or ""),
                    card_id=str(payload.get("card_id") or ""),
                )
                return {
                    "status": "deleted",
                    "card_id": card_id,
                }
            card_payload = payload.get("card")
            if not isinstance(card_payload, dict):
                raise StateError("freeform corkboard card is required")
            card = _save_creative_freeform_corkboard_card(
                project_root,
                corkboard_path=str(payload.get("corkboard") or ""),
                card_payload=card_payload,
            )
            return {
                "status": "saved",
                "card": card,
            }
        raise StateError(f"unknown corkboard type: {board_type}")

    def start_creative_writing_agent(
        self,
        context_id: str,
        *,
        active_document: str | None = None,
        active_target: dict[str, object] | None = None,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.creative_session is not None
                and context.creative_session.is_active()
            ):
                context.selected_session_id = context.creative_session.session_id
                return context.creative_session, False
            document_path = ""
            if active_document:
                document_path = _document_target_path(project_root, active_document)[0]
            target = _creative_agent_target(
                project_root,
                active_target=active_target,
                active_document=document_path or None,
            )
            session = AgentSession(
                command=_creative_writing_command(project_root, target),
                cwd=project_root,
                label="creative writing agent",
                kind="creative-writing",
                interactive=True,
            )
            session = self._prepare_session_locked(context, session)
            context.creative_session = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.creative_session is session:
                    context.creative_session = None
                    context.selected_session_id = None
            raise
        return session, True

    def stop_design_review_agent(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design-review":
                raise AgentSessionError("design review stage is not active")
            session = context.design_review_session
            if session is None or not session.is_active():
                raise AgentSessionError("design review is not running")
        session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.design_review_session is session:
                context.design_review_session = None
                context.design_review_interactive = False
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "stopped",
        }

    def complete_design_review_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_design(context_id)

    def approve_design(
        self,
        context_id: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage not in {"design-review", "design-approve"}:
                raise AgentSessionError("design review stage is not active")
            session = context.design_review_session
            design_review_started = context.design_review_started
            needs_design_review_completion = context.workflow_stage == "design-review"
        if session is not None and session.is_active():
            session.terminate()
        from ..cli import _cmd_stage, _stage_args
        from ..gates import GateEngine

        stdout = io.StringIO()
        stderr = io.StringIO()
        store = StateStore(project_root)
        engine = GateEngine(project_root)
        manifest = store.load_current_manifest()
        if needs_design_review_completion and not manifest.has_gate(GATE_DESIGN):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = _cmd_stage(
                    store,
                    engine,
                    _stage_args(
                        STAGE_DESIGN_REVIEW,
                        force=True,
                        reason="Design review was completed from the GUI approval action.",
                    ),
                )
            if code != 0:
                output = "\n".join(
                    part.strip()
                    for part in [stderr.getvalue(), stdout.getvalue()]
                    if part.strip()
                )
                with self.lock:
                    context = self._context_locked(context_id)
                    if context.design_review_session is session:
                        context.design_review_session = None
                        if (
                            session is not None
                            and context.selected_session_id
                            == getattr(session, "session_id", None)
                        ):
                            context.selected_session_id = None
                        context.design_review_interactive = False
                raise AgentSessionError(output or "design review completion failed")
            store = StateStore(project_root)
            engine = GateEngine(project_root)
        previously_approved = _stage_has_approvals(
            project_root,
            STAGE_DESIGN_ACCEPTANCE,
            ["human-approval"],
        )
        if skip_approval:
            reason = (
                "Design approval was skipped from the GUI during an update "
                "after a previous design approval."
                if previously_approved
                else "WARNING: design approval was skipped from the GUI. "
                "The operator accepted the risk that design was not "
                "explicitly approved."
            )
        else:
            reason = None
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_DESIGN_ACCEPTANCE,
                    human=True,
                    force=skip_approval,
                    reason=reason,
                ),
            )
        output = "\n".join(
            part.strip()
            for part in [stderr.getvalue(), stdout.getvalue()]
            if part.strip()
        )
        if code != 0:
            raise AgentSessionError(output or "design approval failed")
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = "implementation-plan"
            context.design_review_session = None
            context.design_review_interactive = False
            context.design_review_started = design_review_started
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": "implementation-plan",
            "output": output,
            "warning": (
                "WARNING: design approval was skipped; advancing to "
                "implementation planning with a forced approval record."
                if skip_approval and not previously_approved
                else None
            ),
        }

    def start_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
        *,
        interactive: bool | None = None,
        force: bool = False,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        config = _generic_stage_config(stage)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None or command_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage and not allow_stage_reopen:
                raise AgentSessionError(f"{stage} stage is not active")
            existing = context.stage_sessions.get(stage)
            if existing is not None and existing.is_active():
                return existing, False
            lock_names = SESSION_ARTIFACT_LOCKS.get(stage, frozenset())
            self._require_session_locks_available_locked(context, lock_names)
            accepts_input = (
                bool(config["interactive_default"])
                if interactive is None
                else interactive
            )
            session = AgentSession(
                command=_generic_stage_command(
                    command_root,
                    stage,
                    force=force,
                    reason=(
                        f"{_stage_display_label(stage)} restarted from the GUI."
                        if force and bool(config.get("reason_arg"))
                        else None
                    ),
                    interactive=accepts_input,
                ),
                cwd=command_root,
                label=(
                    f"interactive {_stage_display_label(stage)} agent"
                    if accepts_input
                    else f"{_stage_display_label(stage)} agent"
                ),
                kind=stage,
                interactive=accepts_input,
                lock_names=lock_names,
                on_completed=lambda returncode: self._mark_generic_stage_completed(
                    context_id,
                    stage,
                    returncode,
                ),
            )
            session = self._prepare_session_locked(context, session)
            context.stage_sessions[stage] = session
            context.selected_session_id = session.session_id
            context.workflow_stage = stage
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.stage_sessions.get(stage) is session:
                    context.stage_sessions.pop(stage, None)
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.stage_started.discard(stage)
            raise
        with self.lock:
            context = self._context_locked(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_started.add(stage)
        return session, True

    def restart_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
        *,
        interactive: bool | None = None,
    ) -> tuple[AgentSession, bool]:
        _generic_stage_config(stage)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage == stage and stage not in context.stage_started:
                raise AgentSessionError(f"start {stage} first")
        self._terminate_workflow_sessions(context_id)
        return self.start_workflow_stage_agent(
            context_id,
            stage,
            interactive=interactive,
            force=True,
            allow_stage_reopen=True,
        )

    def stop_workflow_stage_agent(self, context_id: str, stage: str) -> dict[str, object]:
        _generic_stage_config(stage)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage:
                raise AgentSessionError(f"{stage} stage is not active")
            session = context.stage_sessions.get(stage)
            if session is None or not session.is_active():
                raise AgentSessionError(f"{stage} agent is not running")
        session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_sessions.pop(stage, None)
            if context.selected_session_id == session.session_id:
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "stopped",
        }

    def approve_workflow_stage(
        self,
        context_id: str,
        stage: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        config = _generic_stage_config(stage)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage:
                raise AgentSessionError(f"{stage} stage is not active")
            session = context.stage_sessions.get(stage)
        if session is not None and session.is_active():
            session.terminate()
        command = [str(config["approval_command"])]
        warning = None
        if skip_approval:
            command.append("--force")
            if bool(config.get("approval_reason_arg", config.get("reason_arg"))):
                command.extend(
                    [
                        "--reason",
                        (
                            f"WARNING: {_stage_display_label(stage)} approval was "
                            "skipped from the GUI. The operator accepted the risk "
                            "that the stage was not explicitly approved."
                        ),
                    ]
                )
            warning = (
                f"WARNING: {_stage_display_label(stage)} approval was skipped; "
                "advancing with forced approval records."
            )
        output = _run_electroboy_cli_command(project_root, command)
        with self.lock:
            context = self._context_locked(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_sessions.pop(stage, None)
            context.stage_started.add(stage)
            context.workflow_stage = _active_workflow_stage(project_root)
            if session is not None and context.selected_session_id == session.session_id:
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": context.workflow_stage,
            "output": output,
            "warning": warning,
        }

    def _mark_generic_stage_completed(
        self,
        context_id: str,
        stage: str,
        returncode: int,
    ) -> None:
        if returncode != 0:
            return
        with self.lock:
            try:
                context = self._context_locked(context_id)
            except StateError:
                return
            context.stage_started.add(stage)
            project_root = context.active_project_root
            if project_root is not None:
                context.workflow_stage = _active_workflow_stage(project_root)

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
        elif session.kind in GENERIC_STAGE_CONFIG:
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


def _force_reset_workflow_stage(
    project_root: Path,
    workflow_stage: str,
    target_stage: str,
) -> tuple[str, str]:
    from ..cli import _force_reset_to_stage

    stdout = io.StringIO()
    stderr = io.StringIO()
    store = StateStore(project_root)
    reason = f"Set workflow stage to {workflow_stage} from the GUI."
    with redirect_stdout(stdout), redirect_stderr(stderr):
        decision_id = _force_reset_to_stage(store, target_stage, reason)
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    return decision_id, output


@dataclass(frozen=True)
class ServiceConfig:
    root: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    session_backend: str = SESSION_BACKEND_PTY
    module_registry: ModuleRegistry | None = None
    workflow_registry: WorkflowRegistry | None = None


class AgentSessionError(RuntimeError):
    """Raised when an agent session cannot accept an operation."""


class AgentSession:
    """One browser-mediated child process attached through a pseudo-terminal."""

    def __init__(
        self,
        command: list[str],
        cwd: Path | str,
        columns: int = 120,
        rows: int = 32,
        label: str = "agent",
        kind: str = "agent",
        interactive: bool = True,
        lock_names: frozenset[str] | set[str] | None = None,
        on_completed: Callable[[int], None] | None = None,
        echo_input: bool = False,
        metadata: dict[str, object] | None = None,
        context_id: str | None = None,
        transcript_path: Path | str | None = None,
        backend: str = "pty",
        on_status_changed: Callable[["AgentSession"], None] | None = None,
        session_id: str | None = None,
    ) -> None:
        self.session_id = session_id or uuid4().hex
        self.command = command
        self.cwd = Path(cwd).resolve()
        self.columns = _clamp_terminal_columns(columns)
        self.rows = _clamp_terminal_rows(rows)
        self.label = label
        self.kind = kind
        self.interactive = interactive
        self.echo_input = echo_input
        self.lock_names = frozenset(lock_names or ())
        self.created_at = utc_now()
        self.on_completed = on_completed
        self.on_status_changed = on_status_changed
        self.metadata = dict(metadata or {})
        self.context_id = context_id
        self.transcript_path = (
            Path(transcript_path).expanduser().resolve() if transcript_path else None
        )
        self.backend = backend
        self.process: subprocess.Popen[bytes] | None = None
        self.status = "created"
        self.returncode: int | None = None
        self._master_fd: int | None = None
        self._events: list[dict[str, object]] = []
        self._next_event_id = 1
        self._terminal_pending = ""
        self._condition = threading.Condition()
        self._reader_thread: threading.Thread | None = None
        self._waiter_thread: threading.Thread | None = None

    def payload(self, selected: bool = False) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "kind": self.kind,
            "label": self.label,
            "status": "running" if self.is_active() else self.status,
            "returncode": self.returncode,
            "interactive": self.interactive,
            "locks": sorted(self.lock_names),
            "selected": selected,
            "created_at": self.created_at,
            "command": list(self.command),
            "metadata": dict(self.metadata),
            "context_id": self.context_id,
            "backend": self.backend,
            "transcript_path": (
                str(self.transcript_path) if self.transcript_path is not None else None
            ),
        }

    def persist_to(
        self,
        *,
        context_id: str,
        transcript_path: Path,
        on_status_changed: Callable[["AgentSession"], None] | None = None,
    ) -> None:
        self.context_id = context_id
        self.transcript_path = transcript_path.expanduser().resolve()
        if on_status_changed is not None:
            self.on_status_changed = on_status_changed

    def start(self) -> None:
        if self.process is not None:
            return
        master_fd, slave_fd = pty.openpty()
        env = _agent_process_env()
        env["ELECTROBOY_PROJECT_ROOT"] = str(self.cwd)
        env["AI_PIPELINE_PROJECT_ROOT"] = str(self.cwd)
        if not self.echo_input:
            _disable_terminal_echo(slave_fd)
        _set_terminal_size(slave_fd, self.columns, self.rows)
        popen_kwargs: dict[str, Any] = {
            "args": self.command,
            "cwd": self.cwd,
            "stdin": slave_fd,
            "stdout": slave_fd,
            "stderr": slave_fd,
            "env": env,
            "close_fds": True,
        }
        if sys.version_info >= (3, 11):
            popen_kwargs["process_group"] = 0
        else:
            popen_kwargs["start_new_session"] = True
        try:
            self.process = subprocess.Popen(**popen_kwargs)
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        os.close(slave_fd)
        self._master_fd = master_fd
        self.status = "running"
        self._notify_status_changed()
        self._append_event(
            {
                "type": "system",
                "text": f"started: {' '.join(self.command)}",
            }
        )
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="electroboy-agent-output",
            daemon=True,
        )
        self._waiter_thread = threading.Thread(
            target=self._wait_for_exit,
            name="electroboy-agent-wait",
            daemon=True,
        )
        self._reader_thread.start()
        self._waiter_thread.start()

    def send(self, message: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            for index, text in enumerate(_terminal_input_chunks_for_message(message)):
                if index > 0:
                    time.sleep(TERMINAL_SUBMIT_DELAY_SECONDS)
                os.write(self._master_fd, text.encode("utf-8"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def send_key(self, key: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            os.write(self._master_fd, _terminal_input_for_key(key).encode("utf-8"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def send_raw(self, data: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            os.write(self._master_fd, data.encode("utf-8", errors="ignore"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def interrupt(self) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        fd = self._master_fd
        if fd is not None:
            try:
                os.write(fd, b"\x1b")
            except OSError as error:
                raise AgentSessionError(
                    f"could not interrupt {self.label}: {error}"
                )

    def terminate(self, timeout: float = 2.0) -> None:
        process = self.process
        if process is None:
            self._close_master()
            return
        if process.poll() is not None:
            self._close_master()
            return
        _terminate_process_tree(process, timeout=timeout)
        self.returncode = process.returncode
        self.status = "terminated"
        self._notify_status_changed()
        self._close_master()

    def resize(self, columns: int, rows: int) -> None:
        self.columns = _clamp_terminal_columns(columns)
        self.rows = _clamp_terminal_rows(rows)
        fd = self._master_fd
        if fd is None:
            return
        _set_terminal_size(fd, self.columns, self.rows)
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGWINCH)
        except ProcessLookupError:
            return
        except OSError:
            return

    def events_after(self, event_id: int) -> list[dict[str, object]]:
        with self._condition:
            return [
                event.copy()
                for event in self._events
                if int(event.get("id", 0)) > event_id
            ]

    def events(self) -> list[dict[str, object]]:
        transcript_events = self._read_transcript_events()
        if transcript_events:
            return transcript_events
        with self._condition:
            return [event.copy() for event in self._events]

    def wait_for_events_after(
        self,
        event_id: int,
        timeout: float,
    ) -> list[dict[str, object]]:
        with self._condition:
            if (
                not any(int(event.get("id", 0)) > event_id for event in self._events)
                and self.is_active()
            ):
                self._condition.wait(timeout=timeout)
            return [
                event.copy()
                for event in self._events
                if int(event.get("id", 0)) > event_id
            ]

    def is_active(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    def _append_event(self, payload: dict[str, object]) -> None:
        with self._condition:
            payload["id"] = self._next_event_id
            self._next_event_id += 1
            self._events.append(payload)
            self._append_transcript_event(payload)
            self._condition.notify_all()

    def _read_output(self) -> None:
        fd = self._master_fd
        if fd is None:
            return
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError as error:
                if error.errno in {errno.EBADF, errno.EIO}:
                    break
                self._append_event(
                    {
                        "type": "error",
                        "text": f"agent output stream failed: {error}",
                    }
                )
                break
            if not chunk:
                break
            terminal_text = chunk.decode("utf-8", errors="replace")
            text, self._terminal_pending = _clean_terminal_output(
                terminal_text,
                self._terminal_pending,
            )
            if not text and not terminal_text:
                continue
            self._append_event(
                {
                    "type": "output",
                    "text": text,
                    "terminal": terminal_text,
                }
            )

    def _wait_for_exit(self) -> None:
        process = self.process
        if process is None:
            return
        returncode = process.wait()
        time.sleep(0.05)
        self.returncode = returncode
        self.status = "completed"
        self._notify_status_changed()
        if self.on_completed is not None:
            try:
                self.on_completed(returncode)
            except Exception as error:
                self._append_event(
                    {
                        "type": "error",
                        "text": f"completion hook failed: {error}",
                    }
                )
        self._append_event(
            {
                "type": "completed",
                "returncode": returncode,
            }
        )
        self._close_master()

    def _append_transcript_event(self, payload: dict[str, object]) -> None:
        path = self.transcript_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except OSError:
            return

    def _read_transcript_events(self) -> list[dict[str, object]]:
        path = self.transcript_path
        if path is None or not path.exists():
            return []
        events: list[dict[str, object]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
        except (OSError, json.JSONDecodeError):
            return []
        return events

    def _notify_status_changed(self) -> None:
        if self.on_status_changed is None:
            return
        try:
            self.on_status_changed(self)
        except Exception:
            return

    def _close_master(self) -> None:
        fd = self._master_fd
        if fd is None:
            return
        self._master_fd = None
        try:
            os.close(fd)
        except OSError:
            return


class TmuxAgentSession(AgentSession):
    """Agent session backed by a named tmux session."""

    def __init__(
        self,
        command: list[str],
        cwd: Path | str,
        columns: int = 120,
        rows: int = 32,
        label: str = "agent",
        kind: str = "agent",
        interactive: bool = True,
        lock_names: frozenset[str] | set[str] | None = None,
        on_completed: Callable[[int], None] | None = None,
        echo_input: bool = False,
        metadata: dict[str, object] | None = None,
        context_id: str | None = None,
        transcript_path: Path | str | None = None,
        on_status_changed: Callable[["AgentSession"], None] | None = None,
        session_id: str | None = None,
        tmux_name: str | None = None,
    ) -> None:
        super().__init__(
            command,
            cwd,
            columns=columns,
            rows=rows,
            label=label,
            kind=kind,
            interactive=interactive,
            lock_names=lock_names,
            on_completed=on_completed,
            echo_input=echo_input,
            metadata=metadata,
            context_id=context_id,
            transcript_path=transcript_path,
            backend=SESSION_BACKEND_TMUX,
            on_status_changed=on_status_changed,
            session_id=session_id,
        )
        self.tmux_name = tmux_name or _tmux_session_name(self.session_id)
        self._last_capture = ""

    @classmethod
    def from_agent_session(cls, session: AgentSession) -> "TmuxAgentSession":
        return cls(
            session.command,
            session.cwd,
            columns=session.columns,
            rows=session.rows,
            label=session.label,
            kind=session.kind,
            interactive=session.interactive,
            lock_names=session.lock_names,
            on_completed=session.on_completed,
            echo_input=session.echo_input,
            metadata=session.metadata,
            context_id=session.context_id,
            transcript_path=session.transcript_path,
            on_status_changed=session.on_status_changed,
            session_id=session.session_id,
        )

    def payload(self, selected: bool = False) -> dict[str, object]:
        payload = super().payload(selected=selected)
        payload["tmux_session"] = self.tmux_name
        return payload

    def start(self) -> None:
        if shutil.which("tmux") is None:
            raise AgentSessionError("tmux session backend requires tmux in PATH")
        if _tmux_has_session(self.tmux_name):
            raise AgentSessionError(f"tmux session already exists: {self.tmux_name}")
        command = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            self.tmux_name,
            "-c",
            str(self.cwd),
            _tmux_shell_command(self.command, self.cwd),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as error:
            stderr = error.stderr.decode("utf-8", errors="replace").strip()
            raise AgentSessionError(
                stderr or f"could not start tmux session {self.tmux_name}"
            ) from error
        self.status = "running"
        self._notify_status_changed()
        self._append_event(
            {
                "type": "system",
                "text": f"started tmux session: {self.tmux_name}",
            }
        )
        self.resize(self.columns, self.rows)
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="electroboy-tmux-output",
            daemon=True,
        )
        self._waiter_thread = threading.Thread(
            target=self._wait_for_exit,
            name="electroboy-tmux-wait",
            daemon=True,
        )
        self._reader_thread.start()
        self._waiter_thread.start()

    def attach_existing(self) -> None:
        if not _tmux_has_session(self.tmux_name):
            self.status = "completed"
            self.returncode = 0
            return
        self.status = "running"
        self._notify_status_changed()
        self._append_event(
            {
                "type": "system",
                "text": f"reattached tmux session: {self.tmux_name}",
            }
        )
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="electroboy-tmux-output",
            daemon=True,
        )
        self._waiter_thread = threading.Thread(
            target=self._wait_for_exit,
            name="electroboy-tmux-wait",
            daemon=True,
        )
        self._reader_thread.start()
        self._waiter_thread.start()

    def send(self, message: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        for index, text in enumerate(_terminal_input_chunks_for_message(message)):
            if index > 0:
                time.sleep(TERMINAL_SUBMIT_DELAY_SECONDS)
            self.send_raw(text)

    def send_key(self, key: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        tmux_key = _tmux_key_name(key)
        if tmux_key is None:
            self.send_raw(_terminal_input_for_key(key))
            return
        _tmux_run(["send-keys", "-t", self.tmux_name, tmux_key])

    def send_raw(self, data: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if not data:
            return
        buffer_name = f"electroboy-{self.session_id}"
        encoded = data.encode("utf-8", errors="ignore")
        _tmux_run(["load-buffer", "-b", buffer_name, "-"], input_bytes=encoded)
        _tmux_run(["paste-buffer", "-d", "-b", buffer_name, "-t", self.tmux_name])

    def interrupt(self) -> None:
        self.send_key("escape")

    def terminate(self, timeout: float = 2.0) -> None:
        if self.is_active():
            _tmux_run(["kill-session", "-t", self.tmux_name], check=False)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and self.is_active():
                time.sleep(0.05)
        self.returncode = 0
        self.status = "terminated"
        self._notify_status_changed()

    def resize(self, columns: int, rows: int) -> None:
        self.columns = _clamp_terminal_columns(columns)
        self.rows = _clamp_terminal_rows(rows)
        if self.is_active():
            _tmux_run(
                [
                    "resize-window",
                    "-t",
                    self.tmux_name,
                    "-x",
                    str(self.columns),
                    "-y",
                    str(self.rows),
                ],
                check=False,
            )

    def is_active(self) -> bool:
        return _tmux_has_session(self.tmux_name)

    def _read_output(self) -> None:
        while self.is_active():
            capture = _tmux_capture_pane(self.tmux_name)
            if capture and capture != self._last_capture:
                text = _tmux_capture_delta(self._last_capture, capture)
                self._last_capture = capture
                if text:
                    self._append_event(
                        {
                            "type": "output",
                            "text": text,
                            "terminal": text,
                        }
                    )
            time.sleep(1)

    def _wait_for_exit(self) -> None:
        while self.is_active():
            time.sleep(0.5)
        self.returncode = 0 if self.returncode is None else self.returncode
        completed = self.status == "running"
        if completed:
            self.status = "completed"
        self._notify_status_changed()
        if self.on_completed is not None and completed:
            try:
                self.on_completed(self.returncode or 0)
            except Exception as error:
                self._append_event(
                    {
                        "type": "error",
                        "text": f"completion hook failed: {error}",
                    }
                )
        self._append_event(
            {
                "type": "completed",
                "returncode": self.returncode,
            }
        )


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    timeout: float,
) -> None:
    root_pid = process.pid
    pids = [root_pid, *_descendant_process_ids(root_pid)]
    _signal_process_ids(root_pid, pids, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _signal_process_ids(root_pid, pids, signal.SIGKILL)
        process.wait(timeout=1)
        return

    survivors = [pid for pid in pids if pid != root_pid and _process_exists(pid)]
    if survivors:
        _signal_process_ids(root_pid, survivors, signal.SIGKILL)


def _signal_process_ids(root_pid: int, pids: list[int], sig: int) -> None:
    try:
        os.killpg(root_pid, sig)
    except ProcessLookupError:
        pass
    except OSError:
        pass
    for pid in reversed(pids):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except OSError:
            continue


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _descendant_process_ids(root_pid: int) -> list[int]:
    parent_map = _process_parent_map()
    if not parent_map:
        return []
    children_by_parent: dict[int, list[int]] = {}
    for pid, parent_pid in parent_map.items():
        children_by_parent.setdefault(parent_pid, []).append(pid)

    descendants: list[int] = []
    stack = list(children_by_parent.get(root_pid, []))
    while stack:
        pid = stack.pop()
        descendants.append(pid)
        stack.extend(children_by_parent.get(pid, []))
    return descendants


def _process_parent_map() -> dict[int, int]:
    proc = Path("/proc")
    if not proc.exists():
        return {}
    parent_map: dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            pid = int(entry.name)
            close_paren = stat.rfind(")")
            fields = stat[close_paren + 2 :].split()
            parent_map[pid] = int(fields[1])
        except (IndexError, OSError, ValueError):
            continue
    return parent_map


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
    module_registry = build_module_registry()
    workflow_registry = build_workflow_registry(module_registry)
    config = ServiceConfig(
        root=Path(root).expanduser().resolve(),
        host=host,
        port=port,
        session_backend=backend,
        module_registry=module_registry,
        workflow_registry=workflow_registry,
    )
    state = ServiceState(root=config.root, session_backend=config.session_backend)
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
    payload["frontend_bundles"] = [
        bundle["id"] for bundle in frontend_asset_payload()
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
        _visible_workflow_stage(context.workflow_stage)
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
            and _stage_has_approvals(
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
        "stage_runs": _generic_stage_run_payload(context, active_root),
        "documentation_running": documentation_running,
        "creative_writing_running": creative_running,
        "ad_hoc_running": ad_hoc_running,
        "project_shell_running": project_shell_running,
        "design_approved": bool(
            active_root
            and _stage_has_approvals(
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
        "work_items": _work_item_payload(active_root) if active_root else _empty_work_item_payload(),
        "recent_projects": _recent_project_entries(service_root),
    }


def _recent_projects_path(service_root: Path | str) -> Path:
    return Path(service_root).expanduser().resolve() / RECENT_PROJECTS_RELATIVE_PATH


def _load_recent_projects(service_root: Path | str) -> dict[str, object]:
    path = _recent_projects_path(service_root)
    if not path.exists():
        return {"schema_version": 1, "projects": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "projects": []}
    if not isinstance(data, dict):
        return {"schema_version": 1, "projects": []}
    if not isinstance(data.get("projects"), list):
        data["projects"] = []
    data["schema_version"] = 1
    return data


def _save_recent_projects(service_root: Path | str, data: dict[str, object]) -> None:
    path = _recent_projects_path(service_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _recent_project_entries(service_root: Path | str) -> list[dict[str, object]]:
    data = _load_recent_projects(service_root)
    entries: list[dict[str, object]] = []
    for entry in data.get("projects", []):
        if not isinstance(entry, dict):
            continue
        project_path = str(entry.get("path") or "").strip()
        if not project_path:
            continue
        kind = str(entry.get("kind") or "project").strip()
        if kind not in {"project", "meta", "creative"}:
            kind = "project"
        label = str(entry.get("label") or Path(project_path).name or project_path)
        entries.append(
            {
                "kind": kind,
                "label": label,
                "path": project_path,
                "opened_at": str(entry.get("opened_at") or ""),
            }
        )
    return entries[:RECENT_PROJECT_LIMIT]


def _remember_recent_project(
    service_root: Path | str,
    project_root: Path | str,
    kind: str,
) -> None:
    project_path = str(Path(project_root).expanduser().resolve())
    if kind not in {"project", "meta", "creative"}:
        kind = "project"
    data = _load_recent_projects(service_root)
    existing = [
        entry
        for entry in data.get("projects", [])
        if isinstance(entry, dict) and str(entry.get("path") or "") != project_path
    ]
    data["projects"] = [
        {
            "kind": kind,
            "label": Path(project_path).name or project_path,
            "path": project_path,
            "opened_at": utc_now(),
        },
        *existing,
    ][:RECENT_PROJECT_LIMIT]
    _save_recent_projects(service_root, data)


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


def _generic_stage_run_payload(
    context: BrowserContext,
    active_root: Path | None,
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for stage in GENERIC_STAGE_CONFIG:
        session = context.stage_sessions.get(stage)
        running = bool(active_root and session is not None and session.is_active())
        payload[stage] = {
            "started": bool(active_root and stage in context.stage_started),
            "running": running,
            "interactive": bool(running and session is not None and session.interactive),
        }
    return payload


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


def _empty_work_item_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "active_collection_id": None,
        "active_feature_slug": None,
        "active_bug_slug": None,
        "collections": [],
        "features": [],
        "bugs": [],
    }


def _work_item_payload(project_root: Path) -> dict[str, object]:
    registry = _load_work_item_registry(project_root)
    feature = _current_feature_record(project_root)
    bug = _current_bug_record(project_root)
    if feature is not None:
        existing = _feature_by_slug(registry, str(feature.get("slug") or ""))
        collection = _ensure_collection_for_feature(
            registry,
            (
                str(existing.get("collection_id"))
                if existing and existing.get("collection_id")
                else None
            ),
            parent_slug=(
                str(existing.get("parent_slug"))
                if existing and existing.get("parent_slug")
                else None
            ),
        )
        _upsert_feature_record(
            registry,
            feature,
            collection_id=str(collection["id"]),
            parent_slug=(
                str(existing.get("parent_slug"))
                if existing and existing.get("parent_slug")
                else None
            ),
        )
        registry["active_collection_id"] = collection["id"]
        registry["active_feature_slug"] = feature.get("slug")
    if bug is not None:
        _upsert_bug_record(registry, bug)
        registry["active_bug_slug"] = bug.get("slug")
    return {
        "schema_version": 1,
        "active_collection_id": registry.get("active_collection_id"),
        "active_feature_slug": registry.get("active_feature_slug"),
        "active_bug_slug": registry.get("active_bug_slug"),
        "collections": _registry_list(registry, "collections"),
        "features": _registry_list(registry, "features"),
        "bugs": _registry_list(registry, "bugs"),
    }


def _registry_list(
    registry: dict[str, object],
    key: str,
) -> list[dict[str, object]]:
    values = registry.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _load_work_item_registry(project_root: Path) -> dict[str, object]:
    path = project_root / WORK_ITEM_REGISTRY_RELATIVE_PATH
    if not path.exists():
        return {
            **_empty_work_item_payload(),
            "collections": [_default_feature_collection()],
            "active_collection_id": "default",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    registry = {
        **_empty_work_item_payload(),
        **data,
    }
    collections = _registry_list(registry, "collections")
    if not collections:
        collections = [_default_feature_collection()]
    elif _feature_collection_by_id(registry, "default") is None:
        collections.insert(0, _default_feature_collection())
    registry["collections"] = collections
    registry["features"] = _registry_list(registry, "features")
    registry["bugs"] = _registry_list(registry, "bugs")
    if not registry.get("active_collection_id"):
        registry["active_collection_id"] = collections[0].get("id")
    return registry


def _save_work_item_registry(project_root: Path, registry: dict[str, object]) -> None:
    path = project_root / WORK_ITEM_REGISTRY_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _default_feature_collection() -> dict[str, object]:
    return {
        "id": "default",
        "name": "Default",
        "feature_slugs": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def _upsert_feature_collection(
    registry: dict[str, object],
    name: str,
) -> dict[str, object]:
    collections = _registry_list(registry, "collections")
    collection_id = _slugify_work_item(name)
    existing = _feature_collection_by_id(registry, collection_id)
    if existing is not None:
        existing["name"] = name
        existing["updated_at"] = utc_now()
        return existing
    collection = {
        "id": collection_id,
        "name": name,
        "feature_slugs": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    collections.append(collection)
    registry["collections"] = collections
    return collection


def _feature_collection_by_id(
    registry: dict[str, object],
    collection_id: str,
) -> dict[str, object] | None:
    for collection in _registry_list(registry, "collections"):
        if collection.get("id") == collection_id:
            return collection
    return None


def _ensure_collection_for_feature(
    registry: dict[str, object],
    collection_id: str | None,
    *,
    parent_slug: str | None = None,
) -> dict[str, object]:
    if collection_id:
        collection = _feature_collection_by_id(registry, collection_id)
        if collection is not None:
            return collection
    if parent_slug:
        parent = _feature_by_slug(registry, parent_slug)
        if parent and parent.get("collection_id"):
            collection = _feature_collection_by_id(
                registry,
                str(parent.get("collection_id")),
            )
            if collection is not None:
                return collection
    active_id = registry.get("active_collection_id")
    if active_id:
        collection = _feature_collection_by_id(registry, str(active_id))
        if collection is not None:
            return collection
    collections = _registry_list(registry, "collections")
    if collections:
        return collections[0]
    collection = _default_feature_collection()
    registry["collections"] = [collection]
    registry["active_collection_id"] = collection["id"]
    return collection


def _feature_by_slug(
    registry: dict[str, object],
    slug: str,
) -> dict[str, object] | None:
    for feature in _registry_list(registry, "features"):
        if feature.get("slug") == slug:
            return feature
    return None


def _bug_by_slug(
    registry: dict[str, object],
    slug: str,
) -> dict[str, object] | None:
    for bug in _registry_list(registry, "bugs"):
        if bug.get("slug") == slug:
            return bug
    return None


def _upsert_feature_record(
    registry: dict[str, object],
    record: dict[str, object],
    *,
    collection_id: str,
    parent_slug: str | None,
) -> None:
    slug = str(record.get("slug") or "").strip()
    if not slug:
        return
    features = [
        feature
        for feature in _registry_list(registry, "features")
        if feature.get("slug") != slug
    ]
    feature = dict(record)
    feature["collection_id"] = collection_id
    feature["parent_slug"] = parent_slug
    feature["updated_at"] = utc_now()
    features.append(feature)
    registry["features"] = sorted(
        features,
        key=lambda item: str(item.get("name") or item.get("slug") or ""),
    )
    collection = _ensure_collection_for_feature(registry, collection_id)
    feature_slugs = [
        value
        for value in collection.get("feature_slugs", [])
        if isinstance(value, str) and value != slug
    ]
    feature_slugs.append(slug)
    collection["feature_slugs"] = feature_slugs
    collection["updated_at"] = utc_now()


def _upsert_bug_record(
    registry: dict[str, object],
    record: dict[str, object],
) -> None:
    slug = str(record.get("slug") or "").strip()
    if not slug:
        return
    bugs = [
        bug
        for bug in _registry_list(registry, "bugs")
        if bug.get("slug") != slug
    ]
    bug = dict(record)
    bug["updated_at"] = utc_now()
    bugs.append(bug)
    registry["bugs"] = sorted(
        bugs,
        key=lambda item: str(item.get("title") or item.get("slug") or ""),
    )


def _current_feature_record(project_root: Path) -> dict[str, object] | None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        return None
    return read_feature_record(project_root, run_id)


def _current_bug_record(project_root: Path) -> dict[str, object] | None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        return None
    path = store.run_dir(run_id) / "bug.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_current_bug_record(project_root: Path, record: dict[str, object]) -> None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        raise StateError("project has no active run")
    path = store.run_dir(run_id) / "bug.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _feature_record_label(record: dict[str, object] | None) -> str:
    if not record:
        return "feature"
    return str(
        record.get("name")
        or record.get("title")
        or record.get("slug")
        or "feature"
    )


def _bug_record_label(record: dict[str, object] | None) -> str:
    if not record:
        return "bug"
    return str(record.get("title") or record.get("slug") or "bug")


def _run_feature_start_context(
    project_root: Path,
    *,
    title: str,
    feature_name: str | None,
    amend: bool,
    branch: bool,
    stash_subrepo_changes: bool = False,
    branch_name: str | None = None,
) -> str:
    from ..cli import _cmd_feature_start

    args = SimpleNamespace(
        title_or_issue_url=title,
        feature_name=feature_name,
        amend=amend,
        branch=(branch_name or "") if branch else None,
        stash_subrepo_changes=stash_subrepo_changes,
    )
    return _run_orchestrator_command(project_root, _cmd_feature_start, args)


def _run_bug_start_context(
    project_root: Path,
    *,
    issue_reference: str,
    branch: bool,
    stash_subrepo_changes: bool = False,
) -> str:
    from ..cli import _cmd_bug_start

    args = SimpleNamespace(
        issue_reference=issue_reference,
        provider=None,
        branch="" if branch else None,
        stash_subrepo_changes=stash_subrepo_changes,
    )
    return _run_orchestrator_command(project_root, _cmd_bug_start, args)


def _run_orchestrator_command(
    project_root: Path,
    command: Callable[[StateStore, Any], int],
    args: Any,
) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = command(StateStore(project_root), args)
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    if code != 0:
        raise AgentSessionError(output or "work item command failed")
    return output


def _run_electroboy_cli_command(project_root: Path, args: list[str]) -> str:
    from ..cli import main

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(["--root", str(project_root), *args])
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    if code != 0:
        raise AgentSessionError(output or f"electroboy {' '.join(args)} failed")
    return output


def _work_item_error_payload(error: BaseException) -> dict[str, object]:
    message = str(error)
    payload: dict[str, object] = {"error": message}
    if "nested repository changes require stashing" in message:
        payload["stash_subrepo_changes_required"] = True
    return payload


def _generic_stage_config(stage: str) -> dict[str, object]:
    try:
        return GENERIC_STAGE_CONFIG[stage]
    except KeyError as error:
        raise AgentSessionError(f"unsupported workflow stage: {stage}") from error


def _stage_display_label(stage: str) -> str:
    return str(
        _generic_stage_config(stage).get("artifact_title")
        or stage.replace("-", " ")
    ).lower()


def _generic_stage_command(
    root: Path,
    stage: str,
    *,
    force: bool = False,
    reason: str | None = None,
    interactive: bool = False,
) -> list[str]:
    config = _generic_stage_config(stage)
    command_parts = [str(config["command"])]
    if force:
        command_parts.append("--force")
    if reason and bool(config.get("reason_arg")):
        command_parts.extend(["--reason", reason])
    if interactive and bool(config.get("interactive_arg")):
        command_parts.append("--interactive")
    return _electroboy_command(root, command_parts)


def _generic_agent_route(path: str) -> tuple[str, str] | None:
    prefix = "/api/agents/"
    if not path.startswith(prefix):
        return None
    suffix = path[len(prefix):]
    for stage in GENERIC_STAGE_CONFIG:
        stage_prefix = f"{stage}/"
        if suffix.startswith(stage_prefix):
            return stage, suffix[len(stage_prefix):]
    return None


def _slugify_work_item(value: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
            previous_dash = False
            continue
        if not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")
    return slug or "default"


def _visible_workflow_stage(stage: str) -> str:
    return DURABLE_STAGE_OWNERS.get(stage, APPROVAL_STAGE_OWNERS.get(stage, stage))


def _active_workflow_stage(project_root: Path | str) -> str:
    try:
        manifest = StateStore(project_root).load_current_manifest()
    except OSError as error:
        raise StateError(f"could not read ElectroBoy project: {error}") from error
    return _visible_workflow_stage(manifest.active_stage)


def _stage_has_approvals(
    project_root: Path | str,
    stage: str,
    approval_types: list[str],
) -> bool:
    try:
        approvals = StateStore(project_root).read_approvals()
    except (OSError, StateError):
        return False
    return all(
        any(
            approval.get("stage") == stage
            and approval.get("approval_type") == approval_type
            for approval in approvals
        )
        for approval_type in approval_types
    )


def workflow_payload(active_project_root: Path | str | None = None) -> dict[str, object]:
    return {
        "stages": [
            {
                "id": stage,
                "label": stage,
                "operations": _stage_operations(stage, active_project_root),
            }
            for stage in WORKFLOW_STAGES
        ]
    }


def browse_directories(path: Path | str, *, show_hidden: bool = False) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir() and _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: child.name.lower(),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
            }
            for child in children[:200]
        ],
    }


def browse_files(path: Path | str, *, show_hidden: bool = False) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir() or child.is_file()
                if _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: (not child.is_dir(), child.name.lower()),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
                "type": "directory" if child.is_dir() else "file",
            }
            for child in children[:300]
        ],
    }


def browse_markdown_files(
    path: Path | str,
    *,
    show_hidden: bool = False,
) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir()
                or (child.is_file() and child.suffix.lower() == ".md")
                if _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: (not child.is_dir(), child.name.lower()),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
                "type": "directory" if child.is_dir() else "file",
            }
            for child in children[:300]
        ],
    }


def _browser_entry_visible(path: Path, show_hidden: bool) -> bool:
    return show_hidden or not path.name.startswith(".")


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
                workflow_stage = _active_workflow_stage(candidate)
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
        _meta_repository_by_name,
        _meta_repositories,
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


def _existing_creative_project_root(path: str) -> Path:
    project_root = _resolve_project_path(path)
    if not project_root.exists():
        raise StateError(f"project directory does not exist: {project_root}")
    if not project_root.is_dir():
        raise StateError(f"project path is not a directory: {project_root}")
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


def _reopen_requirements_for_restart(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    from ..cli import _is_backward_stage_request, _record_stage_reopen

    if _is_backward_stage_request(manifest.active_stage, STAGE_REQUIREMENTS):
        _record_stage_reopen(
            store=store,
            manifest=manifest,
            target_stage=STAGE_REQUIREMENTS,
            reason="Requirements authoring restarted from the GUI.",
            actor="human-operator",
            action="gui-requirements-restarted",
            summary="Reopened requirements authoring from the GUI.",
        )
        return
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_REQUIREMENTS,
            action="gui-requirements-restarted",
            summary="Restarted requirements authoring from the GUI.",
        )
    )


def _reopen_design_for_restart(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    from ..cli import _is_backward_stage_request, _record_stage_reopen

    if _is_backward_stage_request(manifest.active_stage, STAGE_DESIGN):
        _record_stage_reopen(
            store=store,
            manifest=manifest,
            target_stage=STAGE_DESIGN,
            reason="Design authoring restarted from the GUI.",
            actor="human-operator",
            action="gui-design-restarted",
            summary="Reopened design authoring from the GUI.",
        )
        return
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_DESIGN,
            action="gui-design-restarted",
            summary="Restarted design authoring from the GUI.",
        )
    )


def _record_requirements_complete(project_root: Path, *, skipped: bool = False) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    action = (
        "gui-requirements-approval-skipped"
        if skipped
        else "gui-requirements-authoring-completed"
    )
    summary = (
        "Skipped explicit requirements approval from the GUI and advanced "
        "with a forced approval warning."
        if skipped
        else "Completed requirements authoring and approved the requirements baseline."
    )
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_REQUIREMENTS,
            action=action,
            summary=summary,
            inputs=[manifest.active_stage],
        )
    )


def _record_design_complete(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_DESIGN,
            action="gui-design-authoring-completed",
            summary="Completed design authoring and moved to design review.",
            inputs=[manifest.active_stage],
        )
    )


def _should_force_completed_requirements_approval(store: StateStore) -> bool:
    from ..cli import _has_successful_agent_event

    if _has_successful_agent_event(store, "design_author", STAGE_REQUIREMENTS):
        return False
    completion_actions = {
        "gui-requirements-authoring-completed",
        "gui-requirements-authoring-skipped",
        "gui-requirements-approval-skipped",
    }
    return any(
        event.get("actor") == "human-operator"
        and event.get("stage") == STAGE_REQUIREMENTS
        and event.get("action") in completion_actions
        for event in store.read_activity()
    )


def requirements_document_html(
    project_root: Path | str,
    *,
    embedded: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/requirements.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Requirements",
        "Requirements document does not exist yet.",
        embedded=embedded,
        zoom_percent=zoom_percent,
    )


def design_document_html(project_root: Path | str) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/detailed-design.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Design",
        "Design document does not exist yet.",
    )


def design_review_document_html(project_root: Path | str) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/design-review.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Design Review",
        "Design review document does not exist yet.",
    )


def stage_document_html(
    project_root: Path | str,
    stage: str,
) -> tuple[str, HTTPStatus]:
    config = _generic_stage_config(stage)
    title = str(config["artifact_title"])
    relative_path = _resolved_artifact_relative_path(
        project_root,
        str(config["artifact_path"]),
    )
    return markdown_document_html(
        project_root,
        relative_path,
        title,
        f"{title} document does not exist yet.",
    )


def document_target_html(
    project_root: Path | str,
    relative_path: str,
    *,
    title: str | None = None,
    embedded: bool = False,
    create_missing: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    normalized_path = (
        _ensure_document_target(project_root, relative_path)
        if create_missing
        else _document_target_path(project_root, relative_path)[0]
    )
    display_title = title or normalized_path
    return markdown_document_html(
        project_root,
        normalized_path,
        display_title,
        f"{normalized_path} document does not exist yet.",
        embedded=embedded,
        zoom_percent=zoom_percent,
    )


def artifact_editor_html(
    project_root: Path | str,
    artifact: str,
    requested_path: str = "",
    *,
    title: str | None = None,
    create_missing: bool = False,
    context_id: str = "",
    rich_editor: bool = False,
    editor_font_size: int | None = None,
) -> tuple[str, HTTPStatus]:
    """Return a live editor page for a Markdown or structured artifact."""

    project_root = Path(project_root).expanduser().resolve()
    edit_data = _artifact_edit_payload(
        project_root,
        artifact,
        requested_path,
        title=title,
        create_missing=create_missing,
        rich_editor=rich_editor,
        editor_font_size=editor_font_size,
    )
    edit_data["context_id"] = context_id
    page = _artifact_editor_page(edit_data)
    return page, HTTPStatus.OK


def markdown_document_html(
    project_root: Path | str,
    relative_path: str,
    title: str,
    missing_message: str,
    *,
    embedded: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    project_root = Path(project_root).expanduser().resolve()
    document_path = project_root / relative_path
    if document_path.exists():
        text = document_path.read_text(encoding="utf-8")
        body = _render_markdown(text)
        status = HTTPStatus.OK
    else:
        body = f"<p>{html.escape(missing_message)}</p>"
        status = HTTPStatus.NOT_FOUND
    main_max_width = "none" if embedded else "880px"
    main_margin = "0" if embedded else "0 auto"
    main_padding = "16px" if embedded else "40px 24px 64px"
    article_padding = "18px" if embedded else "28px"
    article_radius = "0" if embedded else "8px"
    article_border = "0" if embedded else "1px solid var(--doc-border)"
    zoom_percent = _clamp_document_zoom(zoom_percent)
    document_font_size = 16 * (zoom_percent / 100)
    mermaid_script = _mermaid_script(body)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --doc-bg: #10141f;
      --doc-surface: #10141f;
      --doc-text: #e7edf7;
      --doc-heading: #ffffff;
      --doc-link: #66d9e8;
      --doc-muted: #aab8cf;
      --doc-border: #2a3142;
      --doc-code-bg: #151b29;
      --doc-code-text: #e7edf7;
      --doc-table-head: #151b29;
      --doc-accent: #8bd8ca;
      --doc-font-size: {document_font_size:.2f}px;
    }}
    html {{
      background: var(--doc-bg);
    }}
    body {{
      margin: 0;
      background: var(--doc-bg);
      color: var(--doc-text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: var(--doc-font-size);
      line-height: 1.55;
    }}
    main {{
      max-width: {main_max_width};
      margin: {main_margin};
      padding: {main_padding};
    }}
    article {{
      background: var(--doc-surface);
      border: {article_border};
      border-radius: {article_radius};
      color: var(--doc-text);
      padding: {article_padding};
    }}
    article, article :where(p, li, td, dd, strong, em, summary, details, figcaption) {{
      color: var(--doc-text);
    }}
    h1, h2, h3, h4, h5, h6 {{
      color: var(--doc-heading);
      line-height: 1.2;
    }}
    a {{
      color: var(--doc-link);
    }}
    blockquote {{
      margin-left: 0;
      border-left: 4px solid var(--doc-accent);
      color: var(--doc-muted);
      padding-left: 14px;
    }}
    hr {{
      border: 0;
      border-top: 1px solid var(--doc-border);
    }}
    img {{
      max-width: 100%;
      height: auto;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border: 1px solid var(--doc-border);
      padding: 8px 10px;
    }}
    th {{
      background: var(--doc-table-head);
      color: var(--doc-heading);
    }}
    pre, code {{
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    }}
    code {{
      color: var(--doc-code-text);
      background: var(--doc-code-bg);
      border-radius: 4px;
      padding: 1px 4px;
    }}
    pre {{
      overflow: auto;
      padding: 12px;
      background: var(--doc-code-bg);
      color: var(--doc-code-text);
      border: 1px solid var(--doc-border);
      border-radius: 6px;
    }}
    pre code {{
      background: transparent;
      border-radius: 0;
      padding: 0;
    }}
    .mermaid {{
      display: flex;
      justify-content: center;
      overflow: auto;
      margin: 16px 0;
      padding: 14px;
      border: 1px solid var(--doc-border);
      border-radius: 6px;
      background: var(--doc-code-bg);
      cursor: zoom-in;
      transition: border-color 120ms ease, background 120ms ease;
    }}
    .mermaid:hover,
    .mermaid:focus-visible {{
      border-color: var(--doc-accent);
      outline: none;
    }}
    .mermaid svg {{
      max-width: 100%;
      height: auto;
    }}
  </style>
  {mermaid_script}
</head>
<body>
  <main>
    <article>
      {body}
    </article>
  </main>
</body>
</html>
"""
    return page, status


def _clamp_document_zoom(value: int) -> int:
    stepped = int(((value + 5) // 10) * 10)
    return max(70, min(180, stepped))


def _document_zoom_from_params(params: dict[str, list[str]]) -> int:
    raw = params.get("zoom", ["100"])[0]
    try:
        return _clamp_document_zoom(int(raw))
    except (TypeError, ValueError):
        return 100


def _clamp_artifact_editor_font_size(value: object) -> int:
    try:
        requested = int(value) if value is not None else 16
    except (TypeError, ValueError):
        requested = 16
    return max(11, min(28, requested))


def _artifact_editor_font_size_from_params(params: dict[str, list[str]]) -> int:
    raw_font_size = (params.get("font_size") or [""])[0]
    if raw_font_size:
        return _clamp_artifact_editor_font_size(raw_font_size)
    raw_zoom = (params.get("document_zoom") or params.get("zoom") or [""])[0]
    try:
        zoom = _clamp_document_zoom(int(raw_zoom))
    except (TypeError, ValueError):
        zoom = 100
    return _clamp_artifact_editor_font_size(round(16 * (zoom / 100)))


def _normalize_document_target_path(relative_path: str) -> str:
    raw = relative_path.strip().replace("\\", "/")
    if not raw:
        raise StateError("document path is required")
    path = Path(raw)
    if path.is_absolute():
        raise StateError("document path must be relative")
    if any(part in {"..", ""} for part in path.parts):
        raise StateError("document path cannot escape the project")
    if path.suffix.lower() != ".md":
        raise StateError("document path must be a markdown file")
    return path.as_posix()


def _ensure_document_target(project_root: Path | str, relative_path: str) -> str:
    normalized_path, document_path = _document_target_path(project_root, relative_path)
    if not document_path.exists():
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            _document_starter_markdown(normalized_path),
            encoding="utf-8",
        )
    if not document_path.is_file():
        raise StateError("document path must refer to a file")
    if not document_path.read_text(encoding="utf-8").strip():
        document_path.write_text(
            _document_starter_markdown(normalized_path),
            encoding="utf-8",
        )
    return normalized_path


def _document_starter_markdown(relative_path: str) -> str:
    title = _document_starter_title(relative_path)
    return f"# {title}\n\n## Overview\n\n## Notes\n"


def _document_starter_title(relative_path: str) -> str:
    stem = Path(relative_path).stem.strip()
    if not stem:
        return "Document"
    if stem.lower() == "readme":
        return "README"
    if stem.lower() == "api":
        return "API"
    return stem.replace("-", " ").replace("_", " ").title()


def _artifact_edit_payload(
    project_root: Path,
    artifact: str,
    requested_path: str,
    *,
    title: str | None = None,
    create_missing: bool = False,
    rich_editor: bool = False,
    editor_font_size: int | None = None,
) -> dict[str, object]:
    artifact = artifact.strip()
    editor_font_size = _clamp_artifact_editor_font_size(editor_font_size)
    structured_artifact, markdown_path = _structured_artifact_for_edit_request(
        project_root,
        artifact,
        requested_path,
    )
    if structured_artifact:
        records, jsonl_path = _ensure_structured_edit_records(
            project_root,
            structured_artifact,
            markdown_path,
        )
        return {
            "mode": "structured",
            "artifact": artifact,
            "artifact_name": structured_artifact,
            "path": requested_path,
            "title": title or ARTIFACT_TITLES[structured_artifact],
            "markdown_path": markdown_path,
            "jsonl_path": jsonl_path,
            "records": records,
            "list_fields": sorted(ARTIFACT_EDITOR_LIST_FIELDS),
            "json_fields": sorted(ARTIFACT_EDITOR_JSON_FIELDS),
            "editor_font_size": editor_font_size,
        }

    if artifact == "document":
        markdown_path = (
            _ensure_document_target(project_root, requested_path)
            if create_missing
            else _document_target_path(project_root, requested_path)[0]
        )
        document_path = _document_target_path(project_root, markdown_path)[1]
    else:
        document_path = _artifact_event_document_path(
            project_root,
            artifact,
            requested_path,
        )
        markdown_path = document_path.relative_to(project_root).as_posix()
    if not document_path.exists():
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            _document_starter_markdown(markdown_path),
            encoding="utf-8",
        )
    return {
        "mode": "markdown",
        "artifact": artifact,
        "path": requested_path,
        "title": title or markdown_path,
        "markdown_path": markdown_path,
        "markdown": document_path.read_text(encoding="utf-8"),
        "rich_editor": bool(rich_editor and artifact == "document"),
        "editor_font_size": editor_font_size,
    }


def _structured_artifact_for_edit_request(
    project_root: Path,
    artifact: str,
    requested_path: str,
) -> tuple[str | None, str]:
    if artifact == "requirements":
        structured_artifact = "requirements"
        return structured_artifact, artifact_markdown_path(project_root, structured_artifact)
    if artifact == "route":
        default_path = ARTIFACT_EVENT_ROUTE_PATHS.get(requested_path, "")
        structured_artifact = STRUCTURED_ARTIFACT_BY_MARKDOWN_PATH.get(default_path)
        if structured_artifact:
            return (
                structured_artifact,
                _resolved_artifact_relative_path(project_root, default_path),
            )
        return None, default_path
    if artifact == "document" and requested_path:
        try:
            markdown_path = _document_target_path(project_root, requested_path)[0]
        except StateError:
            return None, ""
        for structured_artifact in ARTIFACT_DEFAULT_MARKDOWN_PATHS:
            if markdown_path == artifact_markdown_path(project_root, structured_artifact):
                return structured_artifact, markdown_path
    return None, ""


def _ensure_structured_edit_records(
    project_root: Path,
    artifact: str,
    markdown_path: str,
) -> tuple[list[dict[str, object]], str]:
    jsonl_path = artifact_jsonl_path(project_root, artifact, markdown_path)
    jsonl_file = _safe_project_document_path(project_root, jsonl_path)
    if jsonl_file.exists():
        return read_artifact_records(project_root, jsonl_path), jsonl_path

    markdown_file = _safe_project_document_path(project_root, markdown_path)
    if markdown_file.exists():
        import_artifact(
            project_root,
            artifact,
            markdown_path=markdown_path,
            jsonl_path=jsonl_path,
        )
        return read_artifact_records(project_root, jsonl_path), jsonl_path

    records = [
        {
            "schema_version": 1,
            "artifact_type": artifact,
            "record_type": "document",
            "id": _artifact_document_record_id(artifact),
            "order": 0,
            "title": ARTIFACT_TITLES[artifact],
            "body": "",
            "status": "draft",
        }
    ]
    _write_artifact_records(project_root, jsonl_path, records, artifact)
    render_artifact(
        project_root,
        artifact,
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
    )
    return records, jsonl_path


def _artifact_document_record_id(artifact: str) -> str:
    return {
        "requirements": "REQ-DOC",
        "design": "DES-DOC",
        "implementation-plan": "PLAN-DOC",
        "test-plan": "TEST-DOC",
    }.get(artifact, "DOC")


def _safe_project_document_path(project_root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise StateError("document path must be relative")
    resolved = (project_root / path).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as error:
        raise StateError("document path cannot escape the project") from error
    return resolved


def _write_artifact_records(
    project_root: Path,
    jsonl_path: str,
    records: list[dict[str, object]],
    artifact: str,
) -> None:
    if not records:
        raise StateError("artifact must contain at least one record")
    normalized_records: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise StateError(f"record {index + 1} must be an object")
        normalized = dict(record)
        normalized.setdefault("schema_version", 1)
        normalized.setdefault("artifact_type", artifact)
        normalized.setdefault("record_type", "section")
        normalized_records.append(normalized)
    output_path = _safe_project_document_path(project_root, jsonl_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in normalized_records)
        + "\n",
        encoding="utf-8",
    )


def save_artifact_edit(
    project_root: Path | str,
    artifact: str,
    requested_path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    project_root = Path(project_root).expanduser().resolve()
    artifact = artifact.strip()
    mode = str(payload.get("mode") or "")
    structured_artifact, markdown_path = _structured_artifact_for_edit_request(
        project_root,
        artifact,
        requested_path,
    )
    if structured_artifact:
        records = payload.get("records")
        if not isinstance(records, list):
            raise StateError("records must be a list")
        jsonl_path = artifact_jsonl_path(project_root, structured_artifact, markdown_path)
        _write_artifact_records(
            project_root,
            jsonl_path,
            records,
            structured_artifact,
        )
        result = render_artifact(
            project_root,
            structured_artifact,
            jsonl_path=jsonl_path,
            markdown_path=markdown_path,
        )
        return {
            "status": "saved",
            "mode": "structured",
            "artifact": structured_artifact,
            "markdown_path": result.markdown_path,
            "jsonl_path": result.jsonl_path,
            "record_count": result.record_count,
        }

    if mode != "markdown":
        raise StateError("artifact is not backed by a structured JSONL document")
    markdown = str(payload.get("markdown") or "")
    document_path = _artifact_event_document_path(
        project_root,
        artifact,
        requested_path,
    )
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text(markdown, encoding="utf-8")
    return {
        "status": "saved",
        "mode": "markdown",
        "markdown_path": document_path.relative_to(project_root).as_posix(),
    }


def _artifact_editor_page(edit_data: dict[str, object]) -> str:
    data_json = json.dumps(edit_data).replace("</", "<\\/")
    title = html.escape(str(edit_data.get("title") or "Artifact Editor"))
    editor_font_size = _clamp_artifact_editor_font_size(
        edit_data.get("editor_font_size")
    )
    rich_editor_script = (
        _rich_markdown_editor_script() if edit_data.get("rich_editor") else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} Editor</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #10141f;
      --panel: #151b29;
      --panel-soft: #1d2638;
      --text: #e7edf7;
      --muted: #aab8cf;
      --border: #2a3142;
      --accent: #66d9e8;
      --accent-strong: #1f6f8b;
      --dirty: #ffd43b;
      --ok: #8ce99a;
      --error: #ff8787;
      --editor-font-size: {editor_font_size}px;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      font-size: 14px;
    }}

    * {{
      box-sizing: border-box;
    }}

    html,
    body {{
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
    }}

    body {{
      overflow: auto;
    }}

    body.markdown-mode {{
      overflow: hidden;
    }}

    main {{
      display: grid;
      gap: 14px;
      max-width: 1040px;
      margin: 0 auto;
      padding: 16px;
    }}

    body.markdown-mode main {{
      display: block;
      width: 100%;
      height: 100%;
      max-width: none;
      margin: 0;
      padding: 0;
    }}

    .editor-header,
    .record-editor,
    .markdown-editor {{
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
    }}

    .editor-header {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 12px;
    }}

    .editor-title {{
      min-width: 0;
    }}

    h1 {{
      margin: 0;
      font-size: 17px;
      line-height: 1.25;
    }}

    .editor-meta {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }}

    .editor-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}

    button,
    .editor-actions select {{
      min-height: 34px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: var(--panel-soft);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-weight: 650;
      padding: 0 12px;
    }}

    .editor-actions select {{
      min-width: 130px;
      cursor: pointer;
      font-weight: 500;
    }}

    button.primary {{
      border-color: var(--accent-strong);
      background: var(--accent-strong);
      color: #ffffff;
    }}

    button:disabled {{
      cursor: not-allowed;
      opacity: 0.55;
    }}

    .status {{
      color: var(--muted);
      min-height: 20px;
      font-size: 13px;
    }}

    .status.dirty {{
      color: var(--dirty);
    }}

    .status.saved {{
      color: var(--ok);
    }}

    .status.error {{
      color: var(--error);
    }}

    body.markdown-mode .editor-header {{
      position: sticky;
      top: 0;
      z-index: 3;
      border-width: 0 0 1px;
      border-radius: 0;
    }}

    body.markdown-mode .status {{
      position: fixed;
      right: 10px;
      bottom: 10px;
      z-index: 2;
      min-height: 0;
      border-radius: 999px;
      background: rgba(15, 20, 32, 0.9);
      color: var(--muted);
      padding: 4px 10px;
      box-shadow: 0 8px 22px rgba(0, 0, 0, 0.22);
      pointer-events: none;
    }}

    body.markdown-mode .status:empty {{
      display: none;
    }}

    body.markdown-mode .status.error {{
      color: var(--error);
    }}

    .records {{
      display: grid;
      gap: 10px;
    }}

    body.markdown-mode .records {{
      display: block;
      height: 100%;
    }}

    details.record-editor > summary {{
      cursor: pointer;
      padding: 12px;
      color: var(--text);
      font-weight: 650;
    }}

    .record-summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
    }}

    .record-summary-text {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .record-summary-kind {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 500;
    }}

    .record-body {{
      display: grid;
      gap: 12px;
      border-top: 1px solid var(--border);
      padding: 12px;
    }}

    .record-actions {{
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }}

    .field-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }}

    label {{
      display: grid;
      gap: 5px;
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }}

    input,
    select,
    textarea {{
      width: 100%;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #0f1420;
      color: var(--text);
      font: inherit;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      line-height: 1.45;
      padding: 8px;
      text-transform: none;
    }}

    textarea {{
      min-height: 92px;
      resize: vertical;
    }}

    textarea.body-field {{
      min-height: 180px;
      font-size: var(--editor-font-size);
    }}

    .generated-fields {{
      border: 1px dashed #364156;
      border-radius: 7px;
      background: #101725;
      color: var(--muted);
    }}

    .generated-fields > summary {{
      cursor: pointer;
      padding: 8px 10px;
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }}

    .generated-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 8px;
      padding: 0 10px 10px;
    }}

    .generated-field {{
      display: grid;
      gap: 3px;
      min-width: 0;
      font-size: 12px;
    }}

    .generated-field code {{
      overflow: hidden;
      border-radius: 4px;
      background: #0f1420;
      color: var(--text);
      padding: 4px 6px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .markdown-editor {{
      display: grid;
      gap: 10px;
      padding: 12px;
    }}

    body.markdown-mode .markdown-editor {{
      display: block;
      height: 100%;
      border: 0;
      border-radius: 0;
      background: transparent;
      padding: 0;
    }}

    .markdown-editor textarea {{
      min-height: 62vh;
    }}

    body.markdown-mode .markdown-editor textarea {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 100%;
      border: 0;
      border-radius: 0;
      font-size: var(--editor-font-size);
      resize: none;
      padding: 14px 16px 36px;
    }}

    body.rich-markdown-mode .markdown-editor {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 100%;
    }}

    .rich-toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      border-bottom: 1px solid var(--border);
      background: #121827;
      padding: 8px;
    }}

    .rich-toolbar select,
    .rich-toolbar button {{
      min-height: 30px;
      border: 1px solid #354058;
      border-radius: 5px;
      background: #171f31;
      color: var(--text);
      font-size: 12px;
      padding: 0 9px;
    }}

    .rich-toolbar button {{
      min-width: 32px;
    }}

    .rich-toolbar button.active {{
      border-color: var(--accent);
      color: #ffffff;
      background: #1f3b4b;
    }}

    .rich-editor-surface {{
      min-height: 0;
      overflow: auto;
      background: #0f1420;
    }}

    .rich-editor-surface .tiptap {{
      min-height: 100%;
      font-size: var(--editor-font-size);
      outline: none;
      padding: 16px 18px 40px;
    }}

    .rich-editor-surface .tiptap > :first-child {{
      margin-top: 0;
    }}

    .rich-editor-surface .tiptap table {{
      border-collapse: collapse;
      width: 100%;
    }}

    .rich-editor-surface .tiptap th,
    .rich-editor-surface .tiptap td {{
      border: 1px solid var(--border);
      padding: 6px 8px;
      vertical-align: top;
    }}

    .rich-editor-surface .tiptap th {{
      background: #151b29;
    }}

    body.rich-markdown-mode .markdown-editor textarea.rich-source-fallback[hidden] {{
      display: none;
    }}

    .markdown-editor.rich-fallback {{
      grid-template-rows: auto minmax(0, 1fr);
    }}
  </style>
</head>
<body>
  <main>
    <header class="editor-header">
      <div class="editor-title">
        <h1>{title}</h1>
        <div id="editorMeta" class="editor-meta"></div>
      </div>
      <div class="editor-actions">
        <select id="recordType" aria-label="Record type to add">
          <option value="section">Section</option>
          <option value="requirement">Requirement</option>
          <option value="decision">Decision</option>
          <option value="interface">Interface</option>
          <option value="unit">Implementation unit</option>
          <option value="suite">Test suite</option>
          <option value="test">Test case</option>
        </select>
        <button id="addRecord" type="button">Add record</button>
        <button id="saveArtifact" class="primary" type="button" disabled>Save</button>
      </div>
    </header>
    <div id="status" class="status"></div>
    <section id="records" class="records"></section>
  </main>
  <script>
    const EDIT_DATA = {data_json};
    const LIST_FIELDS = new Set(EDIT_DATA.list_fields || []);
    const JSON_FIELDS = new Set(EDIT_DATA.json_fields || []);
    const RICH_EDITOR_ENABLED = Boolean(EDIT_DATA.rich_editor);
    const MIN_EDITOR_FONT_SIZE = 11;
    const MAX_EDITOR_FONT_SIZE = 28;
    const CORE_FIELDS = new Set([
      "schema_version",
      "artifact_type",
      "record_type",
      "id",
      "unit_id",
      "title",
      "order",
      "status",
      "phase",
      "sequence",
      "body",
    ]);
    const recordsRoot = document.getElementById("records");
    const recordType = document.getElementById("recordType");
    const addRecord = document.getElementById("addRecord");
    const saveArtifact = document.getElementById("saveArtifact");
    const statusLine = document.getElementById("status");
    const editorMeta = document.getElementById("editorMeta");
    let records = Array.isArray(EDIT_DATA.records)
      ? EDIT_DATA.records.map((record) => ({{ ...record }}))
      : [];
    let saveInFlight = false;
    let dirty = false;
    let markdownTextarea = null;
    let richMarkdownEditor = null;
    let richToolbar = null;
    let richEditorLoading = false;
    let editorFontSize = clampEditorFontSize(EDIT_DATA.editor_font_size || 16);

    const GENERATED_FIELDS = new Set([
      "schema_version",
      "artifact_type",
      "id",
      "unit_id",
      "order",
      "heading_level",
      "parent_id",
      "updated_at",
    ]);

    const COMMON_FIELDS = ["record_type", "title", "status", "body"];
    const RECORD_FIELDS = {{
      document: ["title", "summary", "scope", "out_of_scope", "personas", "status", "body"],
      section: ["title", "status", "body", "requirements", "tags", "links"],
      requirement: [
        "title",
        "statement",
        "body",
        "rationale",
        "priority",
        "acceptance_criteria",
        "verification",
        "dependencies",
        "status",
      ],
      decision: [
        "title",
        "context",
        "decision",
        "body",
        "consequences",
        "requirements",
        "status",
      ],
      interface: [
        "title",
        "kind",
        "producer",
        "consumer",
        "body",
        "schema",
        "requirements",
        "status",
      ],
      unit: [
        "title",
        "phase",
        "sequence",
        "body",
        "scope",
        "commit_tasks",
        "paths",
        "requirements",
        "design_sections",
        "dependencies",
        "exit_criteria",
        "status",
      ],
      suite: ["title", "body", "scope", "requirements", "status"],
      test: [
        "title",
        "level",
        "suite",
        "body",
        "requirements",
        "design_sections",
        "implementation_units",
        "preconditions",
        "steps",
        "expected_results",
        "automation",
        "status",
      ],
    }};

    function contextUrl(path) {{
      const contextId = EDIT_DATA.context_id || "";
      if (!contextId) {{
        return path;
      }}
      const separator = path.includes("?") ? "&" : "?";
      return `${{path}}${{separator}}context_id=${{encodeURIComponent(contextId)}}`;
    }}

    function setStatus(message, error = false) {{
      statusLine.textContent = message || "";
      statusLine.classList.toggle("error", Boolean(error));
      statusLine.classList.toggle("dirty", !error && dirty);
      statusLine.classList.toggle("saved", !error && !dirty && Boolean(message));
    }}

    function setDirty(nextDirty = true) {{
      dirty = Boolean(nextDirty);
      saveArtifact.disabled = saveInFlight || !dirty;
      if (dirty) {{
        setStatus("unsaved changes");
      }}
    }}

    function markDirty() {{
      setDirty(true);
    }}

    function clampEditorFontSize(value) {{
      const requested = Number(value);
      if (!Number.isFinite(requested)) {{
        return 16;
      }}
      return Math.max(
        MIN_EDITOR_FONT_SIZE,
        Math.min(MAX_EDITOR_FONT_SIZE, Math.round(requested)),
      );
    }}

    function applyEditorFontSize(value = editorFontSize) {{
      editorFontSize = clampEditorFontSize(value);
      document.documentElement.style.setProperty(
        "--editor-font-size",
        `${{editorFontSize}}px`,
      );
    }}

    function displayId(record) {{
      return record.id || record.unit_id || "";
    }}

    function recordSummary(record, index) {{
      const id = displayId(record);
      const title = record.title || "Untitled";
      const type = record.record_type || "section";
      return `${{id ? `${{id}}. ` : ""}}${{title}} · ${{type}} #${{index + 1}}`;
    }}

    function stringValue(value) {{
      if (value === undefined || value === null) {{
        return "";
      }}
      return String(value);
    }}

    function arrayValue(value) {{
      if (Array.isArray(value)) {{
        return value.join("\\n");
      }}
      return stringValue(value);
    }}

    function jsonValue(value) {{
      if (value === undefined || value === null || value === "") {{
        return "";
      }}
      if (typeof value === "string") {{
        return value;
      }}
      return JSON.stringify(value, null, 2);
    }}

    function recordKind(record) {{
      return String(record.record_type || "section");
    }}

    function generatedFieldEntries(record) {{
      return Object.entries(record)
        .filter(([field]) => GENERATED_FIELDS.has(field))
        .filter(([, value]) => value !== undefined && value !== null && value !== "");
    }}

    function editableFieldsForRecord(record) {{
      const fields = new Set(RECORD_FIELDS[recordKind(record)] || COMMON_FIELDS);
      fields.add("record_type");
      for (const field of Object.keys(record)) {{
        if (!GENERATED_FIELDS.has(field)) {{
          fields.add(field);
        }}
      }}
      return Array.from(fields);
    }}

    function fieldInputOptions(field) {{
      if (field === "record_type") {{
        return {{
          kind: "select",
          values: ["document", "section", "requirement", "decision", "interface", "unit", "suite", "test"],
        }};
      }}
      if (field === "status") {{
        return {{
          kind: "select",
          values: ["draft", "approved", "changed", "deprecated", "deferred"],
        }};
      }}
      if (field === "priority") {{
        return {{ kind: "select", values: ["", "must", "should", "could", "deferred"] }};
      }}
      if (["order", "phase", "sequence"].includes(field)) {{
        return {{ numeric: true }};
      }}
      if (field === "body" || LIST_FIELDS.has(field) || JSON_FIELDS.has(field)) {{
        return {{
          kind: "textarea",
          list: LIST_FIELDS.has(field),
          json: JSON_FIELDS.has(field),
        }};
      }}
      return {{}};
    }}

    function fieldLabel(field) {{
      if (field === "record_type") {{
        return "Type";
      }}
      return field.replace(/_/g, " ");
    }}

    function appendInput(container, record, field, label, options = {{}}) {{
      const wrapper = document.createElement("label");
      wrapper.textContent = label;
      let input;
      if (options.kind === "select") {{
        input = document.createElement("select");
        for (const optionValue of options.values || []) {{
          const option = document.createElement("option");
          option.value = optionValue;
          option.textContent = optionValue || "none";
          input.append(option);
        }}
        input.value = stringValue(record[field]);
      }} else if (options.kind === "textarea") {{
        input = document.createElement("textarea");
        input.value = options.list
          ? arrayValue(record[field])
          : options.json
          ? jsonValue(record[field])
          : stringValue(record[field]);
      }} else {{
        input = document.createElement("input");
        input.type = options.numeric ? "number" : "text";
        input.value = stringValue(record[field]);
      }}
      input.dataset.field = field;
      if (options.list) {{
        input.dataset.list = "1";
      }}
      if (options.json) {{
        input.dataset.json = "1";
      }}
      if (options.numeric) {{
        input.dataset.numeric = "1";
      }}
      if (field === "body") {{
        input.classList.add("body-field");
        input.placeholder = "Markdown text, tables, code fences, and Mermaid diagrams";
      }}
      input.addEventListener("input", markDirty);
      input.addEventListener("change", markDirty);
      wrapper.append(input);
      container.append(wrapper);
      return input;
    }}

    function renderStructuredEditor() {{
      document.body.classList.remove("markdown-mode", "rich-markdown-mode");
      if (richMarkdownEditor) {{
        richMarkdownEditor.destroy();
        richMarkdownEditor = null;
      }}
      markdownTextarea = null;
      richToolbar = null;
      editorMeta.textContent = `${{EDIT_DATA.markdown_path}} · source ${{EDIT_DATA.jsonl_path}}`;
      addRecord.hidden = false;
      recordType.hidden = false;
      recordsRoot.replaceChildren();
      for (const [index, record] of records.entries()) {{
        const details = document.createElement("details");
        details.className = "record-editor";
        details.open = index === 0 || dirty;
        details.dataset.index = String(index);

        const summary = document.createElement("summary");
        const summaryInner = document.createElement("span");
        summaryInner.className = "record-summary";
        const summaryText = document.createElement("span");
        summaryText.className = "record-summary-text";
        summaryText.textContent = recordSummary(record, index);
        const summaryKind = document.createElement("span");
        summaryKind.className = "record-summary-kind";
        summaryKind.textContent = recordKind(record);
        summaryInner.append(summaryText, summaryKind);
        summary.append(summaryInner);
        details.append(summary);

        const body = document.createElement("div");
        body.className = "record-body";
        const grid = document.createElement("div");
        grid.className = "field-grid";
        for (const field of editableFieldsForRecord(record)) {{
          if (field === "body") {{
            continue;
          }}
          appendInput(grid, record, field, fieldLabel(field), fieldInputOptions(field));
        }}
        body.append(grid);
        if (editableFieldsForRecord(record).includes("body")) {{
          appendInput(body, record, "body", "Markdown body", fieldInputOptions("body"));
        }}

        const generatedEntries = generatedFieldEntries(record);
        if (generatedEntries.length > 0) {{
          const generated = document.createElement("details");
          generated.className = "generated-fields";
          const generatedSummary = document.createElement("summary");
          generatedSummary.textContent = "Generated fields";
          generated.append(generatedSummary);
          const generatedGrid = document.createElement("div");
          generatedGrid.className = "generated-grid";
          for (const [field, value] of generatedEntries) {{
            const wrapper = document.createElement("div");
            wrapper.className = "generated-field";
            const name = document.createElement("span");
            name.textContent = field.replace(/_/g, " ");
            const code = document.createElement("code");
            code.textContent = Array.isArray(value) || typeof value === "object"
              ? JSON.stringify(value)
              : String(value);
            wrapper.append(name, code);
            generatedGrid.append(wrapper);
          }}
          generated.append(generatedGrid);
          body.append(generated);
        }}

        const actions = document.createElement("div");
        actions.className = "record-actions";
        const duplicate = document.createElement("button");
        duplicate.type = "button";
        duplicate.textContent = "Duplicate";
        duplicate.addEventListener("click", () => duplicateRecord(index));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Delete";
        remove.disabled = records.length <= 1;
        remove.addEventListener("click", () => deleteRecord(index));
        actions.append(duplicate, remove);
        body.append(actions);

        details.append(body);
        recordsRoot.append(details);
      }}
    }}

    function markdownValue() {{
      if (
        richMarkdownEditor &&
        typeof richMarkdownEditor.getMarkdown === "function"
      ) {{
        return richMarkdownEditor.getMarkdown();
      }}
      return markdownTextarea ? markdownTextarea.value : "";
    }}

    function setMarkdownValue(value) {{
      const nextValue = String(value || "");
      if (markdownTextarea) {{
        markdownTextarea.value = nextValue;
      }}
      if (
        richMarkdownEditor &&
        richMarkdownEditor.commands &&
        typeof richMarkdownEditor.commands.setContent === "function"
      ) {{
        richMarkdownEditor.commands.setContent(nextValue, {{ contentType: "markdown" }});
      }}
    }}

    function appendMarkdownSnippet(snippet) {{
      const prefix = markdownValue().replace(/\\s*$/, "");
      const nextValue = `${{prefix}}${{prefix ? "\\n\\n" : ""}}${{snippet}}\\n`;
      setMarkdownValue(nextValue);
      markDirty();
    }}

    {rich_editor_script}

    function renderMarkdownEditor() {{
      document.body.classList.add("markdown-mode");
      document.body.classList.toggle("rich-markdown-mode", RICH_EDITOR_ENABLED);
      if (richMarkdownEditor) {{
        richMarkdownEditor.destroy();
        richMarkdownEditor = null;
      }}
      editorMeta.textContent = EDIT_DATA.markdown_path || "";
      addRecord.hidden = true;
      recordType.hidden = true;
      recordsRoot.replaceChildren();
      const wrapper = document.createElement("section");
      wrapper.className = "markdown-editor";
      if (RICH_EDITOR_ENABLED) {{
        wrapper.classList.add("rich-markdown-editor", "rich-fallback");
      }}
      const textarea = document.createElement("textarea");
      textarea.id = "markdownSource";
      textarea.className = RICH_EDITOR_ENABLED ? "rich-source-fallback" : "";
      textarea.setAttribute("aria-label", EDIT_DATA.markdown_path || "Markdown");
      textarea.spellcheck = true;
      textarea.value = EDIT_DATA.markdown || "";
      textarea.addEventListener("input", markDirty);
      textarea.addEventListener("change", markDirty);
      markdownTextarea = textarea;
      if (RICH_EDITOR_ENABLED) {{
        wrapper.append(createRichToolbar());
        const surface = document.createElement("div");
        surface.className = "rich-editor-surface";
        surface.setAttribute("aria-label", EDIT_DATA.markdown_path || "Markdown");
        wrapper.append(surface, textarea);
        recordsRoot.append(wrapper);
        initializeRichMarkdownEditor(wrapper, surface);
      }} else {{
        wrapper.append(textarea);
        recordsRoot.append(wrapper);
      }}
    }}

    function splitLines(value) {{
      return String(value || "")
        .split(/\\r?\\n/)
        .map((line) => line.trim())
        .filter(Boolean);
    }}

    function parseInputValue(input) {{
      if (input.dataset.list === "1") {{
        return splitLines(input.value);
      }}
      if (input.dataset.json === "1") {{
        const raw = input.value.trim();
        if (!raw) {{
          return {{}};
        }}
        return JSON.parse(raw);
      }}
      if (input.dataset.numeric === "1") {{
        if (!input.value.trim()) {{
          return undefined;
        }}
        return Number(input.value);
      }}
      return input.value;
    }}

    function collectStructuredRecords() {{
      const collected = [];
      for (const details of recordsRoot.querySelectorAll(".record-editor")) {{
        const original = records[Number(details.dataset.index || "0")] || {{}};
        const record = {{ ...original }};
        record.schema_version = original.schema_version || 1;
        record.artifact_type = original.artifact_type || EDIT_DATA.artifact_name;
        for (const input of details.querySelectorAll("[data-field]")) {{
          const field = input.dataset.field;
          const value = parseInputValue(input);
          if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {{
            continue;
          }}
          if (JSON_FIELDS.has(field) && Object.keys(value).length === 0) {{
            continue;
          }}
          record[field] = value;
        }}
        collected.push(record);
      }}
      return collected;
    }}

    function collectMarkdownDocument() {{
      return markdownValue();
    }}

    function nextGeneratedId(type) {{
      const existing = new Set(records.map((record) => displayId(record)).filter(Boolean));
      const prefixByType = {{
        document: "DOC",
        section: `${{String(EDIT_DATA.artifact_name || "doc").toUpperCase().replace(/[^A-Z0-9]+/g, "")}}SEC`,
        requirement: "REQ",
        decision: "DEC",
        interface: "IFACE",
        unit: "PH1-C",
        suite: "TS",
        test: "TEST",
      }};
      const prefix = prefixByType[type] || "REC";
      for (let index = 1; index < 10000; index += 1) {{
        const candidate = type === "unit"
          ? `${{prefix}}${{index}}`
          : `${{prefix}}-${{String(index).padStart(3, "0")}}`;
        if (!existing.has(candidate)) {{
          return candidate;
        }}
      }}
      return `${{prefix}}-${{Date.now()}}`;
    }}

    function nextOrder() {{
      const nextOrder = records.reduce((maximum, record) => {{
        const order = Number(record.order || 0);
        return Number.isFinite(order) ? Math.max(maximum, order) : maximum;
      }}, 0) + 10;
      return nextOrder;
    }}

    function newRecord(type) {{
      const record = {{
        schema_version: 1,
        artifact_type: EDIT_DATA.artifact_name,
        record_type: type,
        title: `New ${{type.replace(/-/g, " ")}}`,
        order: nextOrder(),
        body: "",
        status: "draft",
      }};
      if (type === "unit") {{
        record.unit_id = nextGeneratedId(type);
        record.phase = 1;
        record.sequence = 1;
      }} else {{
        record.id = nextGeneratedId(type);
      }}
      return record;
    }}

    function addSectionRecord() {{
      records.push(newRecord(recordType.value || "section"));
      renderStructuredEditor();
      const last = recordsRoot.querySelector(".record-editor:last-child");
      if (last) {{
        last.open = true;
        last.scrollIntoView({{ block: "nearest" }});
      }}
      markDirty();
    }}

    function duplicateRecord(index) {{
      const original = records[index];
      if (!original) {{
        return;
      }}
      const copy = {{ ...original, order: nextOrder(), title: `${{original.title || "Record"}} copy` }};
      if (copy.unit_id) {{
        copy.unit_id = nextGeneratedId("unit");
      }} else if (copy.id) {{
        copy.id = nextGeneratedId(recordKind(copy));
      }}
      records.splice(index + 1, 0, copy);
      renderStructuredEditor();
      markDirty();
    }}

    function deleteRecord(index) {{
      if (records.length <= 1) {{
        return;
      }}
      const record = records[index];
      const name = record ? recordSummary(record, index) : "this record";
      if (!window.confirm(`Delete ${{name}}?`)) {{
        return;
      }}
      records.splice(index, 1);
      renderStructuredEditor();
      markDirty();
    }}

    async function save(options = {{}}) {{
      if (saveInFlight) {{
        return false;
      }}
      if (!dirty && !options.force) {{
        return true;
      }}
      saveInFlight = true;
      saveArtifact.disabled = true;
      setStatus("saving...");
      try {{
        const payload = EDIT_DATA.mode === "structured"
          ? {{
              mode: "structured",
              artifact: EDIT_DATA.artifact,
              path: EDIT_DATA.path || "",
              records: collectStructuredRecords(),
            }}
          : {{
              mode: "markdown",
              artifact: EDIT_DATA.artifact,
              path: EDIT_DATA.path || "",
              markdown: collectMarkdownDocument(),
            }};
        const response = await fetch(contextUrl("/api/artifacts/edit"), {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        const result = await response.json().catch(() => ({{ error: "save failed" }}));
        if (!response.ok) {{
          throw new Error(result.error || "save failed");
        }}
        if (EDIT_DATA.mode === "structured") {{
          records = collectStructuredRecords();
        }}
        setDirty(false);
        setStatus(`saved ${{result.markdown_path || EDIT_DATA.markdown_path}}`);
        if (window.parent) {{
          window.parent.postMessage(
            {{
              type: "electroboy-artifact-saved",
              path: result.markdown_path || EDIT_DATA.markdown_path,
            }},
            window.location.origin,
          );
        }}
        return true;
      }} catch (error) {{
        setStatus(error.message || String(error), true);
        return false;
      }} finally {{
        saveInFlight = false;
        saveArtifact.disabled = !dirty;
      }}
    }}

    addRecord.addEventListener("click", addSectionRecord);
    saveArtifact.addEventListener("click", () => {{
      save({{ force: true }});
    }});
    window.addEventListener("message", async (event) => {{
      if (event.origin !== window.location.origin) {{
        return;
      }}
      const data = event.data || {{}};
      if (data.type === "electroboy-editor-font-size") {{
        applyEditorFontSize(data.font_size);
        return;
      }}
      if (data.type !== "electroboy-save-request") {{
        return;
      }}
      const ok = await save({{ force: true }});
      if (window.parent) {{
        window.parent.postMessage(
          {{
            type: "electroboy-artifact-save-complete",
            token: data.token || "",
            ok,
          }},
          window.location.origin,
        );
      }}
    }});
    window.addEventListener("beforeunload", (event) => {{
      if (!dirty) {{
        return;
      }}
      event.preventDefault();
      event.returnValue = "";
    }});
    applyEditorFontSize();
    if (EDIT_DATA.mode === "structured") {{
      renderStructuredEditor();
    }} else {{
      renderMarkdownEditor();
    }}
  </script>
</body>
</html>
"""


def _rich_markdown_editor_script() -> str:
    return """
    function richButton(command, label, title) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.command = command;
      button.title = title;
      button.setAttribute("aria-label", title);
      button.textContent = label;
      button.addEventListener("click", () => executeRichCommand(command));
      return button;
    }

    function createRichToolbar() {
      const toolbar = document.createElement("div");
      toolbar.className = "rich-toolbar";

      const heading = document.createElement("select");
      heading.dataset.heading = "1";
      heading.title = "Block style";
      heading.setAttribute("aria-label", "Block style");
      for (const [value, label] of [
        ["paragraph", "Paragraph"],
        ["1", "Heading 1"],
        ["2", "Heading 2"],
        ["3", "Heading 3"],
      ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        heading.append(option);
      }
      heading.addEventListener("change", () => {
        if (!richMarkdownEditor) {
          return;
        }
        if (heading.value === "paragraph") {
          richMarkdownEditor.chain().focus().setParagraph().run();
        } else {
          richMarkdownEditor
            .chain()
            .focus()
            .toggleHeading({ level: Number(heading.value) })
            .run();
        }
      });

      toolbar.append(
        heading,
        richButton("bold", "B", "Bold"),
        richButton("italic", "I", "Italic"),
        richButton("code", "`", "Inline code"),
        richButton("bulletList", "Bullet", "Bullet list"),
        richButton("orderedList", "1.", "Numbered list"),
        richButton("blockquote", "Quote", "Quote"),
        richButton("codeBlock", "Code", "Code block"),
        richButton("link", "Link", "Link"),
        richButton("table", "Table", "Insert table"),
        richButton("mermaid", "Mermaid", "Insert Mermaid block"),
      );
      richToolbar = toolbar;
      return toolbar;
    }

    function executeRichCommand(command) {
      if (!richMarkdownEditor) {
        return;
      }
      const chain = richMarkdownEditor.chain().focus();
      if (command === "bold") {
        chain.toggleBold().run();
      } else if (command === "italic") {
        chain.toggleItalic().run();
      } else if (command === "code") {
        chain.toggleCode().run();
      } else if (command === "bulletList") {
        chain.toggleBulletList().run();
      } else if (command === "orderedList") {
        chain.toggleOrderedList().run();
      } else if (command === "blockquote") {
        chain.toggleBlockquote().run();
      } else if (command === "codeBlock") {
        chain.toggleCodeBlock().run();
      } else if (command === "link") {
        const previous = richMarkdownEditor.getAttributes("link").href || "";
        const href = window.prompt("Link URL", previous);
        if (href === null) {
          return;
        }
        if (!href.trim()) {
          chain.unsetLink().run();
        } else {
          chain.setLink({ href: href.trim() }).run();
        }
      } else if (command === "table") {
        chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
      } else if (command === "mermaid") {
        appendMarkdownSnippet(
          "```mermaid\\ngraph TD\\n  A[Start] --> B[Next]\\n```",
        );
      }
      updateRichToolbarState();
    }

    function updateRichToolbarState() {
      if (!richToolbar || !richMarkdownEditor) {
        return;
      }
      const heading = richToolbar.querySelector("[data-heading]");
      if (heading) {
        if (richMarkdownEditor.isActive("heading", { level: 1 })) {
          heading.value = "1";
        } else if (richMarkdownEditor.isActive("heading", { level: 2 })) {
          heading.value = "2";
        } else if (richMarkdownEditor.isActive("heading", { level: 3 })) {
          heading.value = "3";
        } else {
          heading.value = "paragraph";
        }
      }
      for (const button of richToolbar.querySelectorAll("[data-command]")) {
        const command = button.dataset.command || "";
        const activeByCommand = {
          bold: "bold",
          italic: "italic",
          code: "code",
          bulletList: "bulletList",
          orderedList: "orderedList",
          blockquote: "blockquote",
          codeBlock: "codeBlock",
          link: "link",
        };
        button.classList.toggle(
          "active",
          Boolean(activeByCommand[command]) &&
            richMarkdownEditor.isActive(activeByCommand[command]),
        );
      }
    }

    async function initializeRichMarkdownEditor(wrapper, surface) {
      if (!RICH_EDITOR_ENABLED || richEditorLoading) {
        return;
      }
      richEditorLoading = true;
      surface.setAttribute("aria-busy", "true");
      setStatus("loading rich editor...");
      try {
        const [
          coreModule,
          starterKitModule,
          markdownModule,
          linkModule,
          tableModule,
          tableRowModule,
          tableHeaderModule,
          tableCellModule,
        ] = await Promise.all([
          import("https://esm.sh/@tiptap/core"),
          import("https://esm.sh/@tiptap/starter-kit"),
          import("https://esm.sh/@tiptap/markdown"),
          import("https://esm.sh/@tiptap/extension-link"),
          import("https://esm.sh/@tiptap/extension-table"),
          import("https://esm.sh/@tiptap/extension-table-row"),
          import("https://esm.sh/@tiptap/extension-table-header"),
          import("https://esm.sh/@tiptap/extension-table-cell"),
        ]);
        const Editor = coreModule.Editor;
        const StarterKit = starterKitModule.default || starterKitModule.StarterKit;
        const Markdown = markdownModule.Markdown || markdownModule.default;
        const Link = linkModule.default || linkModule.Link;
        const Table = tableModule.default || tableModule.Table;
        const TableRow = tableRowModule.default || tableRowModule.TableRow;
        const TableHeader = tableHeaderModule.default || tableHeaderModule.TableHeader;
        const TableCell = tableCellModule.default || tableCellModule.TableCell;
        if (!Editor || !StarterKit || !Markdown) {
          throw new Error("Tiptap Markdown modules are unavailable");
        }
        richMarkdownEditor = new Editor({
          element: surface,
          extensions: [
            StarterKit,
            Markdown,
            Link ? Link.configure({ openOnClick: false }) : null,
            Table ? Table.configure({ resizable: true }) : null,
            TableRow,
            TableHeader,
            TableCell,
          ].filter(Boolean),
          content: markdownTextarea ? markdownTextarea.value : "",
          contentType: "markdown",
          editorProps: {
            attributes: {
              spellcheck: "true",
            },
          },
          onUpdate: () => {
            if (markdownTextarea) {
              markdownTextarea.value = markdownValue();
            }
            markDirty();
          },
          onSelectionUpdate: updateRichToolbarState,
          onFocus: updateRichToolbarState,
        });
        surface.removeAttribute("aria-busy");
        if (markdownTextarea) {
          markdownTextarea.hidden = true;
        }
        wrapper.classList.remove("rich-fallback");
        setStatus("");
        updateRichToolbarState();
      } catch (error) {
        wrapper.classList.add("rich-fallback");
        surface.remove();
        if (markdownTextarea) {
          markdownTextarea.hidden = false;
        }
        setStatus(`rich editor unavailable: ${error.message || error}`, true);
      } finally {
        richEditorLoading = false;
      }
    }
"""


def _document_target_path(project_root: Path | str, relative_path: str) -> tuple[str, Path]:
    project_root = Path(project_root).expanduser().resolve()
    normalized_path = _normalize_document_target_path(relative_path)
    document_path = (project_root / normalized_path).resolve()
    try:
        document_path.relative_to(project_root)
    except ValueError as error:
        raise StateError("document path cannot escape the project") from error
    return normalized_path, document_path


def _normalize_creative_relative_path(relative_path: str) -> str:
    raw = relative_path.strip().replace("\\", "/")
    if not raw:
        raise StateError("path is required")
    path = Path(raw)
    if path.is_absolute():
        raise StateError("path must be relative")
    if any(part in {"", ".."} for part in path.parts):
        raise StateError("path cannot escape the project")
    return path.as_posix()


def _creative_path(project_root: Path | str, relative_path: str) -> tuple[str, Path]:
    project_root = Path(project_root).expanduser().resolve()
    normalized_path = _normalize_creative_relative_path(relative_path)
    resolved = (project_root / normalized_path).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as error:
        raise StateError("path cannot escape the project") from error
    return normalized_path, resolved


def _ensure_creative_workspace(project_root: Path | str) -> None:
    project_root = Path(project_root).expanduser().resolve()
    for folder in CREATIVE_DEFAULT_FOLDERS:
        (project_root / folder).mkdir(parents=True, exist_ok=True)
    _ensure_creative_scratchpad(project_root)
    chapters = project_root / "chapters"
    if not any(chapters.glob("*.md")):
        _create_creative_document(project_root, "chapters/chapter-01.md")
    for path in [
        "characters/characters.md",
        "reviews/review-notes.md",
    ]:
        _create_creative_document(project_root, path)
    _create_creative_corkboard(
        project_root,
        f"corkboard/ideas{CREATIVE_CORKBOARD_SUFFIX}",
    )


def _ensure_creative_scratchpad(project_root: Path | str) -> Path:
    _relative, path = _document_target_path(project_root, CREATIVE_SCRATCHPAD_PATH)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Scratchpad\n\n", encoding="utf-8")
    return path


def _create_creative_folder(project_root: Path | str, relative_path: str) -> str:
    normalized_path, folder_path = _creative_path(project_root, relative_path)
    if folder_path.exists() and not folder_path.is_dir():
        raise StateError("folder path already exists as a file")
    folder_path.mkdir(parents=True, exist_ok=True)
    return normalized_path


def _create_creative_document(project_root: Path | str, relative_path: str) -> str:
    normalized_path, document_path = _document_target_path(project_root, relative_path)
    if document_path.exists() and not document_path.is_file():
        raise StateError("document path already exists as a folder")
    if not document_path.exists() or not document_path.read_text(encoding="utf-8").strip():
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            _document_starter_markdown(normalized_path),
            encoding="utf-8",
        )
    return normalized_path


def _empty_creative_corkboard_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "electroboy.creative.corkboard",
        "cards": [],
    }


def _create_creative_corkboard(project_root: Path | str, relative_path: str) -> str:
    normalized_path, corkboard_path = _creative_path(project_root, relative_path)
    if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard path must end with {CREATIVE_CORKBOARD_SUFFIX}")
    if corkboard_path.exists() and not corkboard_path.is_file():
        raise StateError("corkboard path already exists as a folder")
    if not corkboard_path.exists() or not corkboard_path.read_text(encoding="utf-8").strip():
        corkboard_path.parent.mkdir(parents=True, exist_ok=True)
        corkboard_path.write_text(
            json.dumps(_empty_creative_corkboard_document(), indent=2) + "\n",
            encoding="utf-8",
        )
    return normalized_path


def _normalize_creative_entry_name(name: str) -> str:
    normalized_name = name.strip()
    if not normalized_name:
        raise StateError("name is required")
    if normalized_name in {".", ".."}:
        raise StateError("name cannot be . or ..")
    if "/" in normalized_name or "\\" in normalized_name:
        raise StateError("name cannot contain path separators")
    return normalized_name


def _rename_creative_entry(
    project_root: Path | str,
    relative_path: str,
    new_name: str,
) -> tuple[str, str]:
    old_relative_path, source = _creative_path(project_root, relative_path)
    project_root = Path(project_root).expanduser().resolve()
    if not source.exists():
        raise StateError(f"path does not exist: {old_relative_path}")
    normalized_name = _normalize_creative_entry_name(new_name)
    destination = (source.parent / normalized_name).resolve()
    try:
        destination.relative_to(project_root)
    except ValueError as error:
        raise StateError("path cannot escape the project") from error
    if destination.exists():
        raise StateError(f"path already exists: {normalized_name}")
    source.rename(destination)
    new_relative_path = destination.relative_to(project_root).as_posix()
    _remap_creative_corkboard_paths(project_root, old_relative_path, new_relative_path)
    return old_relative_path, new_relative_path


def _delete_creative_entry(project_root: Path | str, relative_path: str) -> str:
    normalized_path, path = _creative_path(project_root, relative_path)
    if not path.exists():
        raise StateError(f"path does not exist: {normalized_path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    _remove_creative_corkboard_paths(project_root, normalized_path)
    return normalized_path


def _creative_tree_payload(project_root: Path | str) -> dict[str, object]:
    project_root = Path(project_root).expanduser().resolve()
    return {
        "root": str(project_root),
        "entries": _creative_tree_entries(project_root, project_root),
    }


def _creative_tree_entries(
    project_root: Path,
    directory: Path,
    *,
    depth: int = 0,
) -> list[dict[str, object]]:
    if depth > 8:
        return []
    entries: list[dict[str, object]] = []
    try:
        children = sorted(
            directory.iterdir(),
            key=lambda path: (not path.is_dir(), path.name.lower()),
        )
    except OSError:
        return []
    for child in children:
        if child.name in CREATIVE_IGNORED_NAMES or child.name.startswith("."):
            continue
        relative_path = child.relative_to(project_root).as_posix()
        if child.is_dir():
            entries.append(
                {
                    "name": child.name,
                    "path": relative_path,
                    "type": "directory",
                    "children": _creative_tree_entries(
                        project_root,
                        child,
                        depth=depth + 1,
                    ),
                }
            )
            continue
        entries.append(
            {
                "name": child.name,
                "path": relative_path,
                "type": "file",
                "markdown": child.suffix.lower() == ".md",
                "corkboard": child.name.endswith(CREATIVE_CORKBOARD_SUFFIX),
            }
        )
    return entries


def creative_corkboard_html(
    project_root: Path | str,
    board_path: str,
    *,
    title: str | None = None,
    context_id: str = "",
) -> tuple[str, HTTPStatus]:
    """Return an interactive corkboard for a folder or corkboard file."""

    payload = _creative_corkboard_payload(
        project_root,
        board_path,
        title=title,
        context_id=context_id,
    )
    data_json = json.dumps(payload).replace("</", "<\\/")
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(str(payload["title"]))}</title>
  <style>
    :root {{
      color-scheme: dark;
      --cork: #a86d38;
      --cork-dark: #5f4128;
      --ink: #263247;
      --muted: #6b7280;
      --pin: #d1495b;
      --insert: #66d9e8;
      --shadow: rgba(15, 20, 32, 0.32);
    }}

    * {{
      box-sizing: border-box;
    }}

    html,
    body {{
      width: 100%;
      min-height: 100%;
      margin: 0;
      background-color: var(--cork);
      background:
        radial-gradient(ellipse at 18% 24%, rgba(89, 50, 22, 0.48) 0 2px, transparent 3px),
        radial-gradient(ellipse at 73% 38%, rgba(68, 39, 18, 0.38) 0 2px, transparent 4px),
        radial-gradient(ellipse at 41% 72%, rgba(219, 157, 88, 0.34) 0 2px, transparent 3px),
        radial-gradient(ellipse at 84% 82%, rgba(92, 52, 22, 0.32) 0 1px, transparent 3px),
        radial-gradient(ellipse at 31% 48%, rgba(236, 183, 112, 0.20) 0 1px, transparent 3px),
        repeating-linear-gradient(27deg, rgba(61, 36, 18, 0.10) 0 1px, transparent 1px 9px),
        repeating-linear-gradient(112deg, rgba(236, 183, 112, 0.08) 0 1px, transparent 1px 11px),
        var(--cork);
      background-size:
        46px 38px,
        53px 47px,
        61px 52px,
        37px 41px,
        29px 31px,
        31px 31px,
        43px 43px,
        auto;
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: auto;
    }}

    .board-shell {{
      min-width: 100%;
      min-height: 100vh;
      border: 14px solid var(--cork-dark);
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
    }}

    body.freeform-canvas {{
      height: 100vh;
      overflow: hidden;
    }}

    body.freeform-canvas .board-shell {{
      height: 100vh;
      overflow: hidden;
    }}

    .board-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 62px;
      border-bottom: 1px solid rgba(52, 34, 22, 0.34);
      background: rgba(52, 34, 22, 0.18);
      padding: 10px 18px;
    }}

    .board-eyebrow {{
      color: rgba(255, 248, 228, 0.84);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    h1 {{
      margin: 2px 0 0;
      color: #fff9e8;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 22px;
      font-weight: 700;
      line-height: 1.15;
    }}

    .toolbar-button {{
      min-height: 32px;
      border: 1px solid rgba(255, 249, 232, 0.42);
      border-radius: 999px;
      background: rgba(255, 249, 232, 0.18);
      color: #fff9e8;
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      padding: 0 14px;
    }}

    .toolbar-button[hidden] {{
      display: none;
    }}

    .canvas-viewport {{
      min-width: 100%;
      min-height: calc(100vh - 90px);
    }}

    .board {{
      min-width: 100%;
      min-height: calc(100vh - 90px);
      overflow: visible;
    }}

    body.freeform-canvas .canvas-viewport {{
      position: relative;
      width: 100%;
      height: calc(100vh - 90px);
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      cursor: grab;
      touch-action: none;
    }}

    .board.folder {{
      position: relative;
      display: grid;
      grid-template-columns: repeat(auto-fill, var(--card-width, 218px));
      align-content: start;
      justify-content: start;
      gap: var(--card-gap, 24px);
      padding: 26px;
    }}

    .board.freeform {{
      position: absolute;
      inset: 0;
      min-width: 100%;
      min-height: 100%;
      transform-origin: 0 0;
      will-change: transform;
    }}

    body.canvas-panning,
    body.canvas-panning .canvas-viewport {{
      cursor: grabbing;
      user-select: none;
    }}

    .empty-board {{
      width: 240px;
      min-height: 140px;
      border-radius: 4px;
      background: #fff6cf;
      color: #596176;
      box-shadow: 0 18px 36px var(--shadow);
      padding: 22px;
      transform: rotate(-2deg);
    }}

    .board.freeform .empty-board {{
      position: absolute;
      top: 42px;
      left: 42px;
    }}

    .index-card {{
      min-height: var(--card-min-height, 158px);
      border: 1px solid rgba(38, 50, 71, 0.14);
      border-radius: 5px;
      background:
        linear-gradient(var(--paper), var(--paper)),
        repeating-linear-gradient(
          to bottom,
          transparent 0,
          transparent 25px,
          rgba(63, 77, 103, 0.16) 26px
        );
      box-shadow:
        0 18px 34px var(--shadow),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
      transform: rotate(var(--rotation));
      transform-origin: 50% 22px;
      touch-action: none;
    }}

    .index-card.selected {{
      outline: 3px solid var(--insert);
      outline-offset: 5px;
      box-shadow:
        0 0 0 1px rgba(255, 249, 232, 0.86),
        0 24px 46px rgba(15, 20, 32, 0.34),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
      z-index: 10;
    }}

    .index-card.group {{
      box-shadow:
        10px 10px 0 rgba(255, 249, 232, 0.38),
        18px 18px 30px rgba(15, 20, 32, 0.28),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
    }}

    .index-card.group.selected {{
      box-shadow:
        8px 8px 0 rgba(255, 249, 232, 0.38),
        0 0 0 1px rgba(255, 249, 232, 0.86),
        0 24px 46px rgba(15, 20, 32, 0.34),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
    }}

    .board.folder .index-card {{
      position: relative;
      width: auto;
    }}

    .board.folder .index-card.dragging {{
      opacity: 0.42;
    }}

    .insertion-marker {{
      position: absolute;
      width: 5px;
      min-height: 64px;
      border-radius: 999px;
      background: var(--insert);
      box-shadow:
        0 0 0 3px rgba(15, 20, 32, 0.22),
        0 0 20px rgba(102, 217, 232, 0.62);
      pointer-events: none;
      transform: translateX(-50%);
      transition:
        left 90ms ease,
        top 90ms ease,
        height 90ms ease;
      z-index: 1001;
    }}

    .insertion-marker[hidden] {{
      display: none;
    }}

    .board.freeform .index-card {{
      position: absolute;
      width: var(--card-width, 218px);
    }}

    .index-card.dragging {{
      cursor: grabbing;
      box-shadow:
        0 28px 54px rgba(15, 20, 32, 0.44),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
      z-index: 1000;
    }}

    .index-card::before {{
      content: "";
      position: absolute;
      top: -8px;
      left: 50%;
      width: 16px;
      height: 16px;
      border-radius: 999px;
      background:
        radial-gradient(circle at 35% 32%, rgba(255, 255, 255, 0.75), transparent 0 22%),
        var(--pin);
      box-shadow: 0 4px 8px rgba(48, 28, 22, 0.35);
      transform: translateX(-50%);
    }}

    .index-card::after {{
      content: "";
      position: absolute;
      top: 8px;
      left: 16px;
      right: 16px;
      height: 16px;
      border-radius: 2px;
      background: rgba(255, 255, 255, 0.26);
      mix-blend-mode: multiply;
      transform: rotate(-1deg);
      pointer-events: none;
    }}

    .card-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: start;
      padding: 18px 14px 8px;
      cursor: grab;
    }}

    .card-title {{
      min-width: 0;
      overflow: hidden;
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
      font-size: 17px;
      font-weight: 700;
      line-height: 1.15;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .card-title-input {{
      width: 100%;
      border: 0;
      background: transparent;
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
      font-size: 17px;
      font-weight: 700;
      line-height: 1.15;
      outline: none;
      padding: 0;
    }}

    .card-type {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .card-open {{
      min-height: 24px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.55);
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      font-size: 11px;
      font-weight: 800;
      padding: 0 10px;
    }}

    .card-group-action {{
      display: grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.46);
      color: var(--ink);
      cursor: pointer;
      padding: 0;
    }}

    .card-group-action:hover {{
      background: rgba(255, 255, 255, 0.72);
    }}

    .card-group-action.active {{
      border-color: rgba(42, 87, 148, 0.38);
      background: rgba(216, 230, 255, 0.74);
    }}

    .card-stack-icon {{
      position: relative;
      width: 14px;
      height: 12px;
      border: 1.5px solid currentcolor;
      border-radius: 2px;
    }}

    .card-stack-icon::before,
    .card-stack-icon::after {{
      position: absolute;
      width: 14px;
      height: 12px;
      border: 1.5px solid currentcolor;
      border-radius: 2px;
      content: "";
    }}

    .card-stack-icon::before {{
      top: 3px;
      left: -4px;
      opacity: 0.74;
    }}

    .card-stack-icon::after {{
      top: 6px;
      left: -8px;
      opacity: 0.48;
    }}

    .card-tools {{
      position: relative;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .card-color {{
      display: grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.46);
      color: var(--ink);
      cursor: pointer;
      padding: 0;
    }}

    .card-color:hover {{
      background: rgba(255, 255, 255, 0.72);
    }}

    .card-color-icon {{
      width: 14px;
      height: 14px;
      border: 2px solid currentcolor;
      border-radius: 999px 999px 999px 2px;
      background: var(--selected-paper, #fff6cf);
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.62) inset;
      transform: rotate(-45deg);
    }}

    .card-palette {{
      position: absolute;
      top: calc(100% + 6px);
      right: 0;
      z-index: 1200;
      display: none;
      grid-template-columns: repeat(4, 24px);
      gap: 6px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 8px;
      background: rgba(255, 249, 232, 0.96);
      box-shadow: 0 16px 32px rgba(15, 20, 32, 0.28);
      padding: 8px;
    }}

    .card-palette.open {{
      display: grid;
    }}

    .card-swatch {{
      width: 24px;
      height: 24px;
      border: 1px solid rgba(38, 50, 71, 0.2);
      border-radius: 999px;
      background: var(--swatch);
      cursor: pointer;
      padding: 0;
    }}

    .card-swatch.selected {{
      box-shadow:
        0 0 0 2px rgba(255, 249, 232, 0.9),
        0 0 0 4px rgba(38, 50, 71, 0.72);
    }}

    .card-delete {{
      display: grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.42);
      color: #6f3f45;
      cursor: pointer;
      padding: 0;
    }}

    .card-delete:hover:not(:disabled) {{
      border-color: rgba(140, 48, 58, 0.48);
      background: rgba(255, 238, 234, 0.78);
      color: #9b2634;
    }}

    .card-delete:disabled {{
      cursor: default;
      opacity: 0.45;
    }}

    .card-delete-icon {{
      position: relative;
      width: 11px;
      height: 11px;
      border: 1.5px solid currentcolor;
      border-top: 0;
      border-radius: 0 0 2px 2px;
    }}

    .card-delete-icon::before {{
      position: absolute;
      top: -4px;
      left: -2px;
      width: 13px;
      height: 1.5px;
      background: currentcolor;
      content: "";
    }}

    .card-delete-icon::after {{
      position: absolute;
      top: -7px;
      left: 2px;
      width: 5px;
      height: 3px;
      border: 1.5px solid currentcolor;
      border-bottom: 0;
      border-radius: 2px 2px 0 0;
      content: "";
    }}

    .card-note {{
      display: block;
      width: calc(100% - 24px);
      min-height: var(--card-note-min-height, 82px);
      margin: 0 12px 12px;
      border: 0;
      background:
        repeating-linear-gradient(
          to bottom,
          transparent 0,
          transparent 25px,
          rgba(63, 77, 103, 0.18) 26px
        );
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      line-height: 26px;
      outline: none;
      resize: none;
    }}

    .card-size-control {{
      position: fixed;
      right: 12px;
      bottom: 12px;
      z-index: 1100;
      display: grid;
      gap: 6px;
      width: 220px;
      border: 1px solid rgba(255, 249, 232, 0.34);
      border-radius: 8px;
      background: rgba(15, 20, 32, 0.86);
      color: #d8e3f4;
      box-shadow: 0 10px 24px rgba(15, 20, 32, 0.26);
      padding: 8px 10px;
    }}

    .card-size-label {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }}

    .card-size-control input {{
      width: 100%;
      accent-color: var(--insert);
    }}

  </style>
</head>
<body>
  <main class="board-shell">
    <header class="board-toolbar">
      <div>
        <div id="boardEyebrow" class="board-eyebrow"></div>
        <h1>{html.escape(str(payload["title"]))}</h1>
      </div>
      <button id="addCard" class="toolbar-button" type="button" hidden>Add card</button>
    </header>
    <section id="canvasViewport" class="canvas-viewport">
      <section id="board" class="board" aria-label="{html.escape(str(payload["title"]))}"></section>
    </section>
  </main>
  <label class="card-size-control">
    <span class="card-size-label">
      <span>Card size</span>
      <output id="cardSizeValue">100%</output>
    </span>
    <input
      id="cardSizeSlider"
      type="range"
      min="70"
      max="300"
      step="5"
      value="100"
      aria-label="Resize corkboard cards"
    >
  </label>
  <script>
    const CORKBOARD_DATA = {data_json};
    const canvasViewport = document.getElementById("canvasViewport");
    const board = document.getElementById("board");
    const boardEyebrow = document.getElementById("boardEyebrow");
    const addCard = document.getElementById("addCard");
    const cardSizeSlider = document.getElementById("cardSizeSlider");
    const cardSizeValue = document.getElementById("cardSizeValue");
    const boardType = CORKBOARD_DATA.board_type || "folder";
    const cards = Array.isArray(CORKBOARD_DATA.cards) ? CORKBOARD_DATA.cards : [];
    const CARD_PALETTE = Array.isArray(CORKBOARD_DATA.palette)
      ? CORKBOARD_DATA.palette
      : [];
    const saveTimers = new Map();
    const cardSaveRequests = new Map();
    const CARD_SCALE_STORAGE_PREFIX = "electroboy.creative.corkboard.cardScale.";
    const CANVAS_PAN_STORAGE_PREFIX = "electroboy.creative.corkboard.canvasPan.";
    const MIN_CARD_SCALE = 70;
    const MAX_CARD_SCALE = 300;
    let dragState = null;
    let canvasPanState = null;
    let draggedPath = "";
    let folderInsertionMarker = null;
    let folderDropTarget = "";
    let folderDropPlacement = "before";
    let cardScale = storedCardScale();
    let canvasPan = storedCanvasPan();
    let selectedCardKey = "";

    document.body.classList.toggle("freeform-canvas", boardType === "freeform");

    function contextUrl(path) {{
      const contextId = CORKBOARD_DATA.context_id || "";
      if (!contextId) {{
        return path;
      }}
      const separator = path.includes("?") ? "&" : "?";
      return `${{path}}${{separator}}context_id=${{encodeURIComponent(contextId)}}`;
    }}

    function boardStoragePath() {{
      if (CORKBOARD_DATA.corkboard && CORKBOARD_DATA.corkboard.path) {{
        return CORKBOARD_DATA.corkboard.path;
      }}
      if (CORKBOARD_DATA.folder && CORKBOARD_DATA.folder.path) {{
        return CORKBOARD_DATA.folder.path;
      }}
      return "default";
    }}

    function cardScaleStorageKey() {{
      return `${{CARD_SCALE_STORAGE_PREFIX}}${{boardType}}:${{boardStoragePath()}}`;
    }}

    function canvasPanStorageKey() {{
      return `${{CANVAS_PAN_STORAGE_PREFIX}}${{boardStoragePath()}}`;
    }}

    function storedCanvasPan() {{
      if (boardType !== "freeform") {{
        return {{ x: 0, y: 0 }};
      }}
      try {{
        const stored = JSON.parse(window.localStorage.getItem(canvasPanStorageKey()));
        const x = Number(stored && stored.x);
        const y = Number(stored && stored.y);
        if (Number.isFinite(x) && Number.isFinite(y)) {{
          return {{ x, y }};
        }}
      }} catch (error) {{
        return {{ x: 0, y: 0 }};
      }}
      return {{ x: 0, y: 0 }};
    }}

    function saveCanvasPan() {{
      try {{
        window.localStorage.setItem(canvasPanStorageKey(), JSON.stringify(canvasPan));
      }} catch (error) {{
        return;
      }}
    }}

    function applyCanvasPan() {{
      if (boardType !== "freeform") {{
        board.style.transform = "";
        return;
      }}
      board.style.transform = `translate(${{canvasPan.x}}px, ${{canvasPan.y}}px)`;
    }}

    function clampCardScale(value) {{
      const scale = Number(value);
      if (!Number.isFinite(scale)) {{
        return 100;
      }}
      return Math.max(MIN_CARD_SCALE, Math.min(MAX_CARD_SCALE, Math.round(scale)));
    }}

    function storedCardScale() {{
      try {{
        const stored = Number(window.localStorage.getItem(cardScaleStorageKey()));
        if (Number.isFinite(stored)) {{
          return clampCardScale(stored);
        }}
      }} catch (error) {{
        return 100;
      }}
      return 100;
    }}

    function saveCardScale() {{
      try {{
        window.localStorage.setItem(cardScaleStorageKey(), String(cardScale));
      }} catch (error) {{
        return;
      }}
    }}

    function scaledCardValue(value) {{
      return Math.round(value * cardScale / 100);
    }}

    function applyCardScale() {{
      const root = document.documentElement;
      root.style.setProperty("--card-width", `${{scaledCardValue(218)}}px`);
      root.style.setProperty("--card-min-height", `${{scaledCardValue(158)}}px`);
      root.style.setProperty("--card-note-min-height", `${{scaledCardValue(82)}}px`);
      root.style.setProperty("--card-gap", `${{Math.max(14, scaledCardValue(24))}}px`);
      cardSizeSlider.value = String(cardScale);
      cardSizeValue.value = `${{cardScale}}%`;
      cardSizeValue.textContent = `${{cardScale}}%`;
      sizeBoard();
    }}

    function updateCardScale(value) {{
      cardScale = clampCardScale(value);
      saveCardScale();
      applyCardScale();
    }}

    function cardKey(card) {{
      return String(card.id || card.path || "");
    }}

    function cardKind(card) {{
      return card && card.card_type === "group" ? "group" : "card";
    }}

    function cardCssType(card) {{
      if (boardType === "freeform") {{
        return cardKind(card);
      }}
      return card.type || "file";
    }}

    function selectCard(card, cardElement) {{
      selectedCardKey = cardKey(card);
      for (const element of board.querySelectorAll(".index-card.selected")) {{
        element.classList.remove("selected");
        element.setAttribute("aria-selected", "false");
      }}
      cardElement.classList.add("selected");
      cardElement.setAttribute("aria-selected", "true");
    }}

    function paletteEntryFor(color) {{
      const raw = String(color || "").trim();
      const lower = raw.toLowerCase();
      return CARD_PALETTE.find((entry) =>
        entry.id === raw || String(entry.value || "").toLowerCase() === lower,
      );
    }}

    function cardColorName(card) {{
      const entry = paletteEntryFor(card.color);
      if (entry) {{
        return entry.id;
      }}
      const raw = String(card.color || "").trim();
      return /^#[0-9a-f]{{6}}$/i.test(raw) ? raw.toLowerCase() : "butter";
    }}

    function cardColor(card) {{
      const entry = paletteEntryFor(card.color);
      if (entry) {{
        return entry.value;
      }}
      const raw = String(card.color || "").trim();
      return /^#[0-9a-f]{{6}}$/i.test(raw) ? raw.toLowerCase() : "#fff6cf";
    }}

    function closePalettes(except = null) {{
      for (const palette of board.querySelectorAll(".card-palette.open")) {{
        if (palette !== except) {{
          palette.classList.remove("open");
        }}
      }}
    }}

    function buildColorButton(card, cardElement) {{
      const wrapper = document.createElement("div");
      wrapper.className = "card-color-wrap";
      const button = document.createElement("button");
      button.className = "card-color";
      button.type = "button";
      button.title = "Change card color";
      button.setAttribute("aria-label", "Change card color");
      const icon = document.createElement("span");
      icon.className = "card-color-icon";
      icon.setAttribute("aria-hidden", "true");
      button.append(icon);
      const palette = document.createElement("div");
      palette.className = "card-palette";
      palette.addEventListener("click", (event) => event.stopPropagation());
      for (const entry of CARD_PALETTE) {{
        const swatch = document.createElement("button");
        swatch.className = "card-swatch";
        swatch.type = "button";
        swatch.title = entry.label || entry.id;
        swatch.setAttribute("aria-label", `Set card color to ${{entry.label || entry.id}}`);
        swatch.style.setProperty("--swatch", entry.value || "#fff6cf");
        swatch.classList.toggle("selected", cardColorName(card) === entry.id);
        swatch.addEventListener("click", (event) => {{
          event.stopPropagation();
          card.color = entry.id;
          cardElement.style.setProperty("--paper", cardColor(card));
          icon.style.setProperty("--selected-paper", cardColor(card));
          for (const item of palette.querySelectorAll(".card-swatch.selected")) {{
            item.classList.remove("selected");
          }}
          swatch.classList.add("selected");
          palette.classList.remove("open");
          queueSave(card);
        }});
        palette.append(swatch);
      }}
      button.addEventListener("click", (event) => {{
        event.stopPropagation();
        const isOpen = palette.classList.contains("open");
        closePalettes(palette);
        palette.classList.toggle("open", !isOpen);
      }});
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
      wrapper.addEventListener("pointerdown", (event) => event.stopPropagation());
      icon.style.setProperty("--selected-paper", cardColor(card));
      wrapper.append(button, palette);
      return wrapper;
    }}

    function applyCardPosition(cardElement, card) {{
      cardElement.style.left = `${{Number(card.x) || 0}}px`;
      cardElement.style.top = `${{Number(card.y) || 0}}px`;
      cardElement.style.setProperty("--rotation", `${{Number(card.rotation) || 0}}deg`);
      cardElement.style.setProperty("--paper", cardColor(card));
    }}

    function sizeBoard() {{
      applyCanvasPan();
    }}

    function startCanvasPan(event) {{
      if (boardType !== "freeform" || event.button !== 1) {{
        return;
      }}
      event.preventDefault();
      canvasPanState = {{
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originalX: canvasPan.x,
        originalY: canvasPan.y,
      }};
      canvasViewport.setPointerCapture(event.pointerId);
      document.body.classList.add("canvas-panning");
    }}

    function updateCanvasPan(event) {{
      if (!canvasPanState || event.pointerId !== canvasPanState.pointerId) {{
        return;
      }}
      canvasPan = {{
        x: canvasPanState.originalX + event.clientX - canvasPanState.startX,
        y: canvasPanState.originalY + event.clientY - canvasPanState.startY,
      }};
      applyCanvasPan();
    }}

    function finishCanvasPan(event) {{
      if (!canvasPanState || event.pointerId !== canvasPanState.pointerId) {{
        return;
      }}
      const pointerId = canvasPanState.pointerId;
      canvasPanState = null;
      document.body.classList.remove("canvas-panning");
      saveCanvasPan();
      try {{
        canvasViewport.releasePointerCapture(pointerId);
      }} catch (error) {{
        // Pointer capture may already be released by the browser.
      }}
    }}

    function queueSave(card) {{
      const key = cardKey(card);
      window.clearTimeout(saveTimers.get(key));
      saveTimers.set(
        key,
        window.setTimeout(() => {{
          saveTimers.delete(key);
          persistCard(card);
        }}, 350),
      );
    }}

    function persistCard(card) {{
      const key = cardKey(card);
      const request = saveCard(card);
      cardSaveRequests.set(key, request);
      request.finally(() => {{
        if (cardSaveRequests.get(key) === request) {{
          cardSaveRequests.delete(key);
        }}
      }});
      return request;
    }}

    async function saveCard(card) {{
      if (!CORKBOARD_DATA.context_id) {{
        return null;
      }}
      let payload = null;
      if (boardType === "folder") {{
        payload = {{
          board_type: "folder",
          folder: CORKBOARD_DATA.folder.path,
          path: card.path,
          note: card.note || "",
          color: cardColorName(card),
        }};
      }} else {{
        payload = {{
          board_type: "freeform",
          corkboard: CORKBOARD_DATA.corkboard.path,
          card: {{
            id: card.id,
            title: card.title || "",
            note: card.note || "",
            x: Number(card.x) || 0,
            y: Number(card.y) || 0,
            rotation: Number(card.rotation) || 0,
            color: cardColorName(card),
            card_type: cardKind(card),
            board_path: card.board_path || "",
          }},
        }};
      }}
      const response = await fetch(contextUrl("/api/creative/corkboard"), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload),
      }}).catch(() => null);
      if (!response || !response.ok) {{
        return null;
      }}
      return response.json().catch(() => null);
    }}

    async function deleteFreeformCard(card, button) {{
      if (boardType !== "freeform") {{
        return;
      }}
      const title = card.title || "Untitled card";
      if (!window.confirm(`Delete "${{title}}"?`)) {{
        return;
      }}
      const key = cardKey(card);
      window.clearTimeout(saveTimers.get(key));
      saveTimers.delete(key);
      button.disabled = true;
      await cardSaveRequests.get(key);
      if (CORKBOARD_DATA.context_id) {{
        const response = await fetch(contextUrl("/api/creative/corkboard"), {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            board_type: "freeform",
            action: "delete",
            corkboard: CORKBOARD_DATA.corkboard.path,
            card_id: card.id,
          }}),
        }}).catch(() => null);
        if (!response || !response.ok) {{
          const payload = response
            ? await response.json().catch(() => ({{}}))
            : {{}};
          button.disabled = false;
          window.alert(payload.error || "Unable to delete card.");
          return;
        }}
      }}
      const index = cards.findIndex((candidate) => cardKey(candidate) === key);
      if (index >= 0) {{
        cards.splice(index, 1);
      }}
      if (selectedCardKey === key) {{
        selectedCardKey = "";
      }}
      renderCards();
    }}

    async function saveOrder() {{
      if (!CORKBOARD_DATA.context_id || boardType !== "folder") {{
        return;
      }}
      await fetch(contextUrl("/api/creative/corkboard"), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          board_type: "folder",
          folder: CORKBOARD_DATA.folder.path,
          order: cards.map((card) => card.path),
        }}),
      }}).catch(() => null);
    }}

    function openCard(card) {{
      const targetWindow =
        window.parent && window.parent !== window ? window.parent : window.opener;
      if (!targetWindow) {{
        return;
      }}
      targetWindow.postMessage(
        {{
          type: "electroboy-creative-open",
          path: card.path,
          entry_type: card.corkboard ? "corkboard" : card.type,
        }},
        window.location.origin,
      );
    }}

    function openGroupCard(card) {{
      const targetWindow =
        window.parent && window.parent !== window ? window.parent : window.opener;
      if (!targetWindow || cardKind(card) !== "group" || !card.board_path) {{
        return;
      }}
      targetWindow.postMessage(
        {{
          type: "electroboy-creative-open",
          path: card.board_path,
          entry_type: "corkboard",
        }},
        window.location.origin,
      );
    }}

    async function convertCardToGroup(card, cardElement, button) {{
      if (boardType !== "freeform") {{
        return;
      }}
      if (cardKind(card) === "group") {{
        openGroupCard(card);
        return;
      }}
      const title = card.title || "Untitled card";
      if (!window.confirm(`Convert "${{title}}" to a card group?`)) {{
        return;
      }}
      const key = cardKey(card);
      window.clearTimeout(saveTimers.get(key));
      saveTimers.delete(key);
      button.disabled = true;
      await cardSaveRequests.get(key);
      card.card_type = "group";
      const saved = await persistCard(card);
      if (saved && saved.card) {{
        Object.assign(card, saved.card);
      }}
      button.disabled = false;
      renderCards();
      if (card.board_path) {{
        openGroupCard(card);
      }}
    }}

    function buildGroupButton(card, cardElement) {{
      const button = document.createElement("button");
      const isGroup = cardKind(card) === "group";
      button.className = `card-group-action ${{isGroup ? "active" : ""}}`;
      button.type = "button";
      button.title = isGroup ? "Open card group" : "Convert to card group";
      button.setAttribute(
        "aria-label",
        isGroup ? "Open card group" : "Convert to card group",
      );
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
      button.addEventListener("click", () => convertCardToGroup(card, cardElement, button));
      const icon = document.createElement("span");
      icon.className = "card-stack-icon";
      icon.setAttribute("aria-hidden", "true");
      button.append(icon);
      return button;
    }}

    function startDrag(event) {{
      if (event.button !== 0 || event.target.closest("textarea, button")) {{
        return;
      }}
      const cardElement = event.currentTarget;
      const card = cards.find((candidate) => cardKey(candidate) === cardElement.dataset.key);
      if (!card) {{
        return;
      }}
      dragState = {{
        card,
        cardElement,
        startX: event.clientX,
        startY: event.clientY,
        originalX: Number(card.x) || 0,
        originalY: Number(card.y) || 0,
      }};
      cardElement.classList.add("dragging");
      cardElement.setPointerCapture(event.pointerId);
    }}

    function updateDrag(event) {{
      if (!dragState) {{
        return;
      }}
      dragState.card.x = Math.max(
        -1000000,
        Math.min(1000000, dragState.originalX + event.clientX - dragState.startX),
      );
      dragState.card.y = Math.max(
        -1000000,
        Math.min(1000000, dragState.originalY + event.clientY - dragState.startY),
      );
      applyCardPosition(dragState.cardElement, dragState.card);
      sizeBoard();
    }}

    function finishDrag(event) {{
      if (!dragState) {{
        return;
      }}
      dragState.cardElement.classList.remove("dragging");
      try {{
        dragState.cardElement.releasePointerCapture(event.pointerId);
      }} catch (error) {{
        // Pointer capture may already be released if the window lost focus.
      }}
      queueSave(dragState.card);
      dragState = null;
    }}

    function startFolderDrag(event, card, cardElement) {{
      draggedPath = card.path || "";
      cardElement.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", draggedPath);
    }}

    function finishFolderDrag(cardElement) {{
      draggedPath = "";
      clearFolderInsertionMarker();
      cardElement.classList.remove("dragging");
    }}

    function ensureFolderInsertionMarker() {{
      if (folderInsertionMarker && folderInsertionMarker.parentElement === board) {{
        return folderInsertionMarker;
      }}
      folderInsertionMarker = document.createElement("div");
      folderInsertionMarker.className = "insertion-marker";
      folderInsertionMarker.hidden = true;
      board.prepend(folderInsertionMarker);
      return folderInsertionMarker;
    }}

    function clearFolderInsertionMarker() {{
      folderDropTarget = "";
      folderDropPlacement = "before";
      if (folderInsertionMarker) {{
        folderInsertionMarker.hidden = true;
      }}
    }}

    function folderInsertionPlacement(event, cardElement) {{
      const rect = cardElement.getBoundingClientRect();
      return event.clientX < rect.left + rect.width / 2 ? "before" : "after";
    }}

    function showFolderInsertionMarker(event, card, cardElement) {{
      if (!draggedPath || draggedPath === card.path) {{
        clearFolderInsertionMarker();
        return;
      }}
      const placement = folderInsertionPlacement(event, cardElement);
      const marker = ensureFolderInsertionMarker();
      const cardRect = cardElement.getBoundingClientRect();
      const boardRect = board.getBoundingClientRect();
      const x = placement === "before"
        ? cardRect.left - boardRect.left
        : cardRect.right - boardRect.left;
      marker.style.left = `${{Math.max(0, x)}}px`;
      marker.style.top = `${{Math.max(0, cardRect.top - boardRect.top)}}px`;
      marker.style.height = `${{Math.max(64, cardRect.height)}}px`;
      marker.hidden = false;
      folderDropTarget = card.path || "";
      folderDropPlacement = placement;
    }}

    function dropFolderCard(event, targetCard, cardElement) {{
      event.preventDefault();
      const sourcePath = draggedPath || event.dataTransfer.getData("text/plain");
      if (!sourcePath || sourcePath === targetCard.path) {{
        clearFolderInsertionMarker();
        return;
      }}
      const sourceIndex = cards.findIndex((card) => card.path === sourcePath);
      const targetPath = folderDropTarget || targetCard.path;
      const placement = folderDropTarget
        ? folderDropPlacement
        : folderInsertionPlacement(event, cardElement);
      if (sourceIndex < 0 || !targetPath) {{
        clearFolderInsertionMarker();
        return;
      }}
      const [moved] = cards.splice(sourceIndex, 1);
      const targetIndex = cards.findIndex((card) => card.path === targetPath);
      if (targetIndex < 0) {{
        cards.splice(sourceIndex, 0, moved);
        clearFolderInsertionMarker();
        return;
      }}
      const insertIndex = placement === "after" ? targetIndex + 1 : targetIndex;
      cards.splice(insertIndex, 0, moved);
      clearFolderInsertionMarker();
      renderCards();
      saveOrder();
    }}

    function makeFreeformCard() {{
      const index = cards.length;
      const card = {{
        id: `card-${{Date.now().toString(36)}}-${{Math.random().toString(36).slice(2, 8)}}`,
        title: "Untitled card",
        note: "",
        x: -canvasPan.x + 36 + (index % 4) * scaledCardValue(236),
        y: -canvasPan.y + 36 + Math.floor(index / 4) * scaledCardValue(206),
        rotation: (index % 5) - 2,
        color: CARD_PALETTE.length
          ? CARD_PALETTE[index % CARD_PALETTE.length].id
          : "#fff6cf",
        card_type: "card",
      }};
      cards.push(card);
      selectedCardKey = card.id;
      renderCards();
      persistCard(card);
    }}

    function renderCards() {{
      board.replaceChildren();
      folderInsertionMarker = null;
      clearFolderInsertionMarker();
      board.className = `board ${{boardType}}`;
      boardEyebrow.textContent = boardType === "freeform"
        ? "Freeform corkboard"
        : "Folder board";
      addCard.hidden = boardType !== "freeform";
      if (cards.length === 0) {{
        const empty = document.createElement("section");
        empty.className = "empty-board";
        empty.textContent = boardType === "freeform"
          ? "No cards yet. Add one to start arranging ideas."
          : "No folders or files yet.";
        board.append(empty);
        return;
      }}
      for (const card of cards) {{
        const cardElement = document.createElement("article");
        cardElement.className = `index-card ${{cardCssType(card)}}`;
        cardElement.dataset.key = cardKey(card);
        cardElement.tabIndex = 0;
        cardElement.classList.toggle("selected", selectedCardKey === cardElement.dataset.key);
        cardElement.setAttribute(
          "aria-selected",
          selectedCardKey === cardElement.dataset.key ? "true" : "false",
        );
        cardElement.style.setProperty("--rotation", `${{Number(card.rotation) || 0}}deg`);
        cardElement.style.setProperty("--paper", cardColor(card));
        cardElement.addEventListener(
          "pointerdown",
          () => selectCard(card, cardElement),
          {{ capture: true }},
        );
        cardElement.addEventListener("focusin", () => selectCard(card, cardElement));
        if (boardType === "freeform") {{
          applyCardPosition(cardElement, card);
          cardElement.addEventListener("pointerdown", startDrag);
          cardElement.addEventListener("pointermove", updateDrag);
          cardElement.addEventListener("pointerup", finishDrag);
          cardElement.addEventListener("pointercancel", finishDrag);
        }} else {{
          ensureFolderInsertionMarker();
          cardElement.draggable = true;
          cardElement.addEventListener("dragstart", (event) =>
            startFolderDrag(event, card, cardElement),
          );
          cardElement.addEventListener("dragend", () => finishFolderDrag(cardElement));
          cardElement.addEventListener("dragover", (event) => {{
            event.preventDefault();
            showFolderInsertionMarker(event, card, cardElement);
          }});
          cardElement.addEventListener("drop", (event) =>
            dropFolderCard(event, card, cardElement),
          );
        }}

        const head = document.createElement("div");
        head.className = "card-head";
        const titleBox = document.createElement("div");
        let title = null;
        if (boardType === "freeform") {{
          title = document.createElement("input");
          title.className = "card-title-input";
          title.type = "text";
          title.value = card.title || "Untitled card";
          title.addEventListener("input", () => {{
            card.title = title.value;
            queueSave(card);
          }});
        }} else {{
          title = document.createElement("div");
          title.className = "card-title";
          title.textContent = card.name || card.path;
        }}
        if (boardType === "folder") {{
          const type = document.createElement("div");
          type.className = "card-type";
          type.textContent = card.type === "directory"
            ? "Folder"
            : card.corkboard ? "Board" : "File";
          titleBox.append(title, type);
          const tools = document.createElement("div");
          tools.className = "card-tools";
          tools.append(buildColorButton(card, cardElement));
          const open = document.createElement("button");
          open.className = "card-open";
          open.type = "button";
          open.textContent = "Open";
          open.addEventListener("click", () => openCard(card));
          tools.append(open);
          head.append(titleBox, tools);
        }} else {{
          titleBox.append(title);
          const tools = document.createElement("div");
          tools.className = "card-tools";
          tools.append(buildColorButton(card, cardElement));
          tools.append(buildGroupButton(card, cardElement));
          const remove = document.createElement("button");
          remove.className = "card-delete";
          remove.type = "button";
          remove.title = "Delete card";
          remove.setAttribute("aria-label", `Delete ${{card.title || "card"}}`);
          remove.addEventListener("pointerdown", (event) => event.stopPropagation());
          remove.addEventListener("click", () => deleteFreeformCard(card, remove));
          const icon = document.createElement("span");
          icon.className = "card-delete-icon";
          icon.setAttribute("aria-hidden", "true");
          remove.append(icon);
          tools.append(remove);
          head.append(titleBox, tools);
        }}

        const note = document.createElement("textarea");
        note.className = "card-note";
        note.spellcheck = true;
        note.value = card.note || "";
        note.addEventListener("input", () => {{
          card.note = note.value;
          queueSave(card);
        }});

        cardElement.append(head, note);
        board.append(cardElement);
      }}
      sizeBoard();
    }}

    addCard.addEventListener("click", makeFreeformCard);
    document.addEventListener("click", () => closePalettes());
    cardSizeSlider.addEventListener("input", () => updateCardScale(cardSizeSlider.value));
    canvasViewport.addEventListener("pointerdown", startCanvasPan);
    canvasViewport.addEventListener("pointermove", updateCanvasPan);
    canvasViewport.addEventListener("pointerup", finishCanvasPan);
    canvasViewport.addEventListener("pointercancel", finishCanvasPan);
    canvasViewport.addEventListener("auxclick", (event) => {{
      if (event.button === 1) {{
        event.preventDefault();
      }}
    }});
    window.addEventListener("resize", sizeBoard);
    applyCardScale();
    renderCards();
  </script>
</body>
</html>
"""
    return page, HTTPStatus.OK


def _creative_corkboard_payload(
    project_root: Path | str,
    board_path: str,
    *,
    title: str | None = None,
    context_id: str = "",
) -> dict[str, object]:
    project_root = Path(project_root).expanduser().resolve()
    normalized_path, path = _creative_path(project_root, board_path)
    if path.exists() and path.is_dir():
        return _creative_folder_corkboard_payload(
            project_root,
            normalized_path,
            path,
            title=title,
            context_id=context_id,
        )
    if (
        path.exists()
        and path.is_file()
        and normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX)
    ):
        return _creative_freeform_corkboard_payload(
            project_root,
            normalized_path,
            path,
            title=title,
            context_id=context_id,
        )
    if normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard does not exist: {normalized_path}")
    raise StateError(f"folder does not exist: {normalized_path}")


def _creative_folder_corkboard_payload(
    project_root: Path,
    normalized_folder: str,
    folder: Path,
    *,
    title: str | None = None,
    context_id: str = "",
) -> dict[str, object]:
    state = _load_creative_corkboard_state(project_root)
    folder_state = _creative_corkboard_folder_state(state, normalized_folder)
    card_states = _creative_corkboard_folder_cards(folder_state)
    cards = []
    for index, child in enumerate(_creative_corkboard_children(project_root, folder)):
        relative_path = child.relative_to(project_root).as_posix()
        card_state = card_states.get(relative_path, {})
        cards.append(
            _creative_folder_corkboard_card(
                child,
                relative_path,
                index,
                card_state if isinstance(card_state, dict) else {},
            )
        )
    order = folder_state.get("order")
    if isinstance(order, list):
        order_index = {str(path): index for index, path in enumerate(order)}
        natural_index = {str(card["path"]): index for index, card in enumerate(cards)}
        cards.sort(
            key=lambda card: (
                order_index.get(
                    str(card["path"]),
                    len(order) + natural_index[str(card["path"])],
                ),
                natural_index[str(card["path"])],
            )
        )
    return {
        "schema_version": 1,
        "board_type": "folder",
        "context_id": context_id,
        "palette": _creative_card_palette_payload(),
        "title": title or f"Folder board: {folder.name}",
        "folder": {
            "name": folder.name,
            "path": normalized_folder,
        },
        "cards": cards,
    }


def _creative_freeform_corkboard_payload(
    project_root: Path,
    normalized_path: str,
    corkboard_path: Path,
    *,
    title: str | None = None,
    context_id: str = "",
) -> dict[str, object]:
    data = _load_creative_corkboard_document(corkboard_path)
    return {
        "schema_version": 1,
        "board_type": "freeform",
        "context_id": context_id,
        "palette": _creative_card_palette_payload(),
        "title": title or corkboard_path.name.removesuffix(CREATIVE_CORKBOARD_SUFFIX),
        "corkboard": {
            "name": corkboard_path.name,
            "path": normalized_path,
        },
        "cards": _freeform_corkboard_cards(data),
    }


def _creative_corkboard_children(project_root: Path, folder: Path) -> list[Path]:
    try:
        children = sorted(
            folder.iterdir(),
            key=lambda path: (not path.is_dir(), path.name.lower()),
        )
    except OSError:
        return []
    return [
        child
        for child in children
        if child.name not in CREATIVE_IGNORED_NAMES and not child.name.startswith(".")
    ]


def _creative_card_palette_payload() -> list[dict[str, str]]:
    return [dict(entry) for entry in CREATIVE_CARD_PALETTE]


def _creative_card_palette_default(index: int) -> str:
    return CREATIVE_CARD_PALETTE[index % len(CREATIVE_CARD_PALETTE)]["id"]


def _normalize_creative_card_color(value: object, default: str) -> str:
    raw = str(value or "").strip()
    if raw in CREATIVE_CARD_PALETTE_IDS:
        return raw
    if CREATIVE_CARD_COLOR_RE.fullmatch(raw):
        return raw.lower()
    return default


def _creative_freeform_card_type(value: object) -> str:
    return "group" if str(value or "").strip() == "group" else "card"


def _normalize_creative_corkboard_reference(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    try:
        relative_path = Path(raw)
    except ValueError:
        return ""
    if (
        relative_path.is_absolute()
        or any(part in {"", ".."} for part in relative_path.parts)
        or not relative_path.as_posix().endswith(CREATIVE_CORKBOARD_SUFFIX)
    ):
        return ""
    return relative_path.as_posix()


def _creative_card_group_default_path(parent_corkboard_path: str, card_id: str) -> str:
    parent_stem = parent_corkboard_path.removesuffix(CREATIVE_CORKBOARD_SUFFIX)
    parent_slug = _slugify_work_item(parent_stem.replace("/", "-"))
    card_slug = _slugify_work_item(card_id)
    return (
        CREATIVE_CORKBOARD_GROUP_DIRECTORY
        / parent_slug
        / f"{card_slug}{CREATIVE_CORKBOARD_SUFFIX}"
    ).as_posix()


def _ensure_creative_card_group_corkboard(
    project_root: Path | str,
    *,
    parent_corkboard_path: str,
    card_id: str,
    board_path: object,
) -> str:
    normalized_board_path = _normalize_creative_corkboard_reference(board_path)
    if not normalized_board_path:
        normalized_board_path = _creative_card_group_default_path(
            parent_corkboard_path,
            card_id,
        )
    _create_creative_corkboard(project_root, normalized_board_path)
    return normalized_board_path


def _creative_folder_corkboard_card(
    path: Path,
    relative_path: str,
    index: int,
    state: dict[str, object],
) -> dict[str, object]:
    style = _creative_corkboard_card_style(relative_path, index)
    color = _normalize_creative_card_color(state.get("color"), str(style["color"]))
    return {
        "name": path.name,
        "path": relative_path,
        "type": "directory" if path.is_dir() else "file",
        "corkboard": path.name.endswith(CREATIVE_CORKBOARD_SUFFIX),
        "note": str(state.get("note") or ""),
        "rotation": style["rotation"],
        "color": color,
    }


def _creative_corkboard_card_style(
    relative_path: str,
    index: int,
) -> dict[str, object]:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()
    rotation = (int(digest[4:6], 16) % 9) - 4
    return {
        "rotation": rotation,
        "color": _creative_card_palette_default(
            int(digest[6:8], 16) % len(CREATIVE_CARD_PALETTE)
        ),
    }


def _bounded_float(
    value: object,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _creative_corkboard_state_path(project_root: Path | str) -> Path:
    return Path(project_root).expanduser().resolve() / CREATIVE_CORKBOARD_STATE_RELATIVE_PATH


def _load_creative_corkboard_state(project_root: Path | str) -> dict[str, object]:
    path = _creative_corkboard_state_path(project_root)
    if not path.exists():
        return {"schema_version": 1, "folders": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "folders": {}}
    if not isinstance(data, dict):
        return {"schema_version": 1, "folders": {}}
    folders = data.get("folders")
    if not isinstance(folders, dict):
        data["folders"] = {}
    data["schema_version"] = 1
    return data


def _save_creative_corkboard_state(
    project_root: Path | str,
    state: dict[str, object],
) -> None:
    path = _creative_corkboard_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _creative_corkboard_folder_state(
    state: dict[str, object],
    folder_path: str,
) -> dict[str, object]:
    folders = state.setdefault("folders", {})
    if not isinstance(folders, dict):
        state["folders"] = {}
        folders = state["folders"]
    folder_state = folders.setdefault(folder_path, {})
    if not isinstance(folder_state, dict):
        folder_state = {}
        folders[folder_path] = folder_state
    cards = _creative_corkboard_folder_cards(folder_state)
    order = folder_state.setdefault("order", [])
    if not isinstance(order, list):
        folder_state["order"] = []
    return folder_state


def _creative_corkboard_folder_cards(
    folder_state: dict[str, object],
) -> dict[str, object]:
    cards = folder_state.setdefault("cards", {})
    if not isinstance(cards, dict):
        folder_state["cards"] = {}
        cards = folder_state["cards"]
    return cards


def _save_creative_folder_corkboard_card(
    project_root: Path | str,
    *,
    folder_path: str,
    card_path: str,
    note: str,
    color: object = None,
) -> dict[str, object]:
    normalized_folder, folder = _creative_path(project_root, folder_path)
    normalized_card, card = _creative_path(project_root, card_path)
    if not folder.exists() or not folder.is_dir():
        raise StateError(f"folder does not exist: {normalized_folder}")
    if not card.exists():
        raise StateError(f"card path does not exist: {normalized_card}")
    if card.parent.resolve() != folder.resolve():
        raise StateError("card does not belong to the corkboard folder")
    state = _load_creative_corkboard_state(project_root)
    folder_state = _creative_corkboard_folder_state(state, normalized_folder)
    card_states = _creative_corkboard_folder_cards(folder_state)
    previous = card_states.get(normalized_card, {})
    style = _creative_corkboard_card_style(normalized_card, len(card_states))
    previous_color = (
        previous.get("color")
        if isinstance(previous, dict)
        else None
    )
    default_color = _normalize_creative_card_color(previous_color, str(style["color"]))
    card_states[normalized_card] = {
        **(previous if isinstance(previous, dict) else {}),
        "note": note[:5000],
        "color": _normalize_creative_card_color(color, default_color),
    }
    _save_creative_corkboard_state(project_root, state)
    return {
        "path": normalized_card,
        **card_states[normalized_card],
    }


def _save_creative_folder_corkboard_order(
    project_root: Path | str,
    *,
    folder_path: str,
    order: list[str],
) -> list[str]:
    normalized_folder, folder = _creative_path(project_root, folder_path)
    if not folder.exists() or not folder.is_dir():
        raise StateError(f"folder does not exist: {normalized_folder}")
    project_root_path = Path(project_root).expanduser().resolve()
    valid_children = {
        child.relative_to(project_root_path).as_posix()
        for child in _creative_corkboard_children(project_root_path, folder)
    }
    saved_order: list[str] = []
    seen: set[str] = set()
    for item in order:
        normalized_item, item_path = _creative_path(project_root, item)
        if (
            normalized_item in valid_children
            and normalized_item not in seen
            and item_path.parent.resolve() == folder.resolve()
        ):
            saved_order.append(normalized_item)
            seen.add(normalized_item)
    for item in sorted(valid_children):
        if item not in seen:
            saved_order.append(item)
    state = _load_creative_corkboard_state(project_root)
    folder_state = _creative_corkboard_folder_state(state, normalized_folder)
    folder_state["order"] = saved_order
    _save_creative_corkboard_state(project_root, state)
    return saved_order


def _load_creative_corkboard_document(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_creative_corkboard_document()
    if not isinstance(data, dict):
        return _empty_creative_corkboard_document()
    if data.get("type") != "electroboy.creative.corkboard":
        data["type"] = "electroboy.creative.corkboard"
    data["schema_version"] = 1
    if not isinstance(data.get("cards"), list):
        data["cards"] = []
    return data


def _freeform_corkboard_cards(data: dict[str, object]) -> list[dict[str, object]]:
    cards = data.get("cards")
    if not isinstance(cards, list):
        return []
    normalized_cards: list[dict[str, object]] = []
    for index, raw_card in enumerate(cards):
        if not isinstance(raw_card, dict):
            continue
        card_id = str(raw_card.get("id") or f"card-{index + 1}")
        style = _creative_corkboard_card_style(card_id, index)
        color = _normalize_creative_card_color(
            raw_card.get("color"),
            str(style["color"]),
        )
        card_type = _creative_freeform_card_type(raw_card.get("card_type"))
        card = {
            "id": card_id[:100],
            "title": str(raw_card.get("title") or "Untitled card")[:200],
            "note": str(raw_card.get("note") or "")[:5000],
            "x": _bounded_float(
                raw_card.get("x"),
                36 + index * 24,
                -1_000_000,
                1_000_000,
            ),
            "y": _bounded_float(
                raw_card.get("y"),
                36 + index * 18,
                -1_000_000,
                1_000_000,
            ),
            "rotation": _bounded_float(
                raw_card.get("rotation"),
                float(style["rotation"]),
                -8,
                8,
            ),
            "color": color,
            "card_type": card_type,
        }
        if card_type == "group":
            board_path = _normalize_creative_corkboard_reference(
                raw_card.get("board_path")
            )
            if board_path:
                card["board_path"] = board_path
        normalized_cards.append(card)
    return normalized_cards


def _save_creative_freeform_corkboard_card(
    project_root: Path | str,
    *,
    corkboard_path: str,
    card_payload: dict[str, object],
) -> dict[str, object]:
    normalized_path, path = _creative_path(project_root, corkboard_path)
    if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard path must end with {CREATIVE_CORKBOARD_SUFFIX}")
    if not path.exists():
        _create_creative_corkboard(project_root, normalized_path)
    if not path.is_file():
        raise StateError(f"corkboard is not a file: {normalized_path}")
    data = _load_creative_corkboard_document(path)
    cards = _freeform_corkboard_cards(data)
    card_id = str(card_payload.get("id") or uuid4().hex)[:100]
    style = _creative_corkboard_card_style(card_id, len(cards))
    existing_card: dict[str, object] = {}
    existing_color: object = None
    for existing in cards:
        if existing.get("id") == card_id:
            existing_card = existing
            existing_color = existing.get("color")
            break
    default_color = _normalize_creative_card_color(existing_color, str(style["color"]))
    card_type = _creative_freeform_card_type(
        card_payload.get("card_type") or existing_card.get("card_type")
    )
    card = {
        "id": card_id,
        "title": str(card_payload.get("title") or "Untitled card")[:200],
        "note": str(card_payload.get("note") or "")[:5000],
        "x": _bounded_float(
            card_payload.get("x"),
            36,
            -1_000_000,
            1_000_000,
        ),
        "y": _bounded_float(
            card_payload.get("y"),
            36,
            -1_000_000,
            1_000_000,
        ),
        "rotation": _bounded_float(
            card_payload.get("rotation"),
            float(style["rotation"]),
            -8,
            8,
        ),
        "color": _normalize_creative_card_color(
            card_payload.get("color"),
            default_color,
        ),
        "card_type": card_type,
    }
    if card_type == "group":
        card["board_path"] = _ensure_creative_card_group_corkboard(
            project_root,
            parent_corkboard_path=normalized_path,
            card_id=card_id,
            board_path=(
                card_payload.get("board_path")
                or existing_card.get("board_path")
            ),
        )
    replaced = False
    for index, existing in enumerate(cards):
        if existing.get("id") == card_id:
            cards[index] = card
            replaced = True
            break
    if not replaced:
        cards.append(card)
    data["cards"] = cards
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return card


def _delete_creative_freeform_corkboard_card(
    project_root: Path | str,
    *,
    corkboard_path: str,
    card_id: str,
) -> str:
    normalized_path, path = _creative_path(project_root, corkboard_path)
    if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard path must end with {CREATIVE_CORKBOARD_SUFFIX}")
    if not path.is_file():
        raise StateError(f"corkboard does not exist: {normalized_path}")
    normalized_card_id = card_id.strip()[:100]
    if not normalized_card_id:
        raise StateError("freeform corkboard card id is required")
    data = _load_creative_corkboard_document(path)
    cards = _freeform_corkboard_cards(data)
    remaining_cards = [
        card for card in cards if card.get("id") != normalized_card_id
    ]
    if len(remaining_cards) == len(cards):
        raise StateError(f"card does not exist: {normalized_card_id}")
    data["cards"] = remaining_cards
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized_card_id


def _remap_creative_path_reference(path: str, old_path: str, new_path: str) -> str:
    if path == old_path:
        return new_path
    if path.startswith(f"{old_path}/"):
        return f"{new_path}/{path[len(old_path) + 1:]}"
    return path


def _remap_creative_corkboard_paths(
    project_root: Path | str,
    old_path: str,
    new_path: str,
) -> None:
    state_path = _creative_corkboard_state_path(project_root)
    if not state_path.exists():
        return
    state = _load_creative_corkboard_state(project_root)
    folders = state.get("folders")
    if not isinstance(folders, dict):
        return
    remapped_folders: dict[str, object] = {}
    for folder_key, folder_state in folders.items():
        if not isinstance(folder_key, str) or not isinstance(folder_state, dict):
            continue
        next_folder_key = _remap_creative_path_reference(folder_key, old_path, new_path)
        cards = folder_state.get("cards")
        if isinstance(cards, dict):
            folder_state["cards"] = {
                _remap_creative_path_reference(
                    str(card_path),
                    old_path,
                    new_path,
                ): card_state
                for card_path, card_state in cards.items()
            }
        order = folder_state.get("order")
        if isinstance(order, list):
            folder_state["order"] = [
                _remap_creative_path_reference(str(card_path), old_path, new_path)
                for card_path in order
            ]
        remapped_folders[next_folder_key] = folder_state
    state["folders"] = remapped_folders
    _save_creative_corkboard_state(project_root, state)


def _remove_creative_corkboard_paths(project_root: Path | str, removed_path: str) -> None:
    state_path = _creative_corkboard_state_path(project_root)
    if not state_path.exists():
        return
    state = _load_creative_corkboard_state(project_root)
    folders = state.get("folders")
    if not isinstance(folders, dict):
        return
    kept_folders: dict[str, object] = {}
    for folder_key, folder_state in folders.items():
        if not isinstance(folder_key, str) or _creative_path_is_inside(folder_key, removed_path):
            continue
        if isinstance(folder_state, dict):
            cards = folder_state.get("cards")
            if isinstance(cards, dict):
                folder_state["cards"] = {
                    str(card_path): card_state
                    for card_path, card_state in cards.items()
                    if not _creative_path_is_inside(str(card_path), removed_path)
                }
            order = folder_state.get("order")
            if isinstance(order, list):
                folder_state["order"] = [
                    str(card_path)
                    for card_path in order
                    if not _creative_path_is_inside(str(card_path), removed_path)
                ]
        kept_folders[folder_key] = folder_state
    state["folders"] = kept_folders
    _save_creative_corkboard_state(project_root, state)


def _creative_path_is_inside(path: str, container: str) -> bool:
    return path == container or path.startswith(f"{container}/")


def _resolved_artifact_relative_path(
    project_root: Path | str,
    default_relative_path: str,
) -> str:
    project_root = Path(project_root).expanduser().resolve()
    relative_path = default_relative_path
    run_id = StateStore(project_root).current_run_id()
    if run_id:
        relative_path = resolve_artifact_path(
            artifact_paths_for_run(project_root, run_id),
            default_relative_path,
        )
    return _document_target_path(project_root, relative_path)[0]


def _resolved_artifact_document_path(
    project_root: Path | str,
    default_relative_path: str,
) -> Path:
    project_root = Path(project_root).expanduser().resolve()
    relative_path = _resolved_artifact_relative_path(
        project_root,
        default_relative_path,
    )
    return _document_target_path(project_root, relative_path)[1]


def _artifact_event_document_path(
    project_root: Path | str,
    artifact: str,
    requested_path: str,
) -> Path:
    project_root = Path(project_root).expanduser().resolve()
    if artifact == "requirements":
        return _resolved_artifact_document_path(project_root, "docs/requirements.md")
    if artifact == "document":
        return _document_target_path(project_root, requested_path)[1]
    if artifact == "route":
        relative_path = ARTIFACT_EVENT_ROUTE_PATHS.get(requested_path)
        if relative_path is None:
            raise StateError(f"unknown artifact route: {requested_path}")
        return _resolved_artifact_document_path(project_root, relative_path)
    raise StateError(f"unknown artifact: {artifact}")


def _file_signature(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"exists": False, "mtime_ns": 0, "size": 0}
    return {
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _render_markdown(text: str) -> str:
    try:
        import markdown as markdown_library
    except ImportError:
        return _render_basic_markdown(text)
    rendered = str(
        markdown_library.markdown(
            _enable_markdown_in_details(text),
            extensions=["extra", "sane_lists", "md_in_html"],
        )
    )
    return _promote_mermaid_blocks(rendered)


_DETAILS_TAG_RE = re.compile(r"<details(?P<attrs>[^>]*)>", re.IGNORECASE)


def _enable_markdown_in_details(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attrs = match.group("attrs") or ""
        if re.search(r"\smarkdown\s*=", attrs, re.IGNORECASE):
            return match.group(0)
        return f'<details{attrs} markdown="1">'

    return _DETAILS_TAG_RE.sub(replace, text)


def _render_basic_markdown(text: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    code_lines: list[str] = []
    code_language = ""

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{html.escape(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            items = "".join(f"<li>{html.escape(item)}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items.clear()

    def flush_code() -> None:
        nonlocal code_language
        escaped = html.escape("\n".join(code_lines))
        language = code_language.strip().lower()
        if language == "mermaid":
            blocks.append(f'<div class="mermaid">{escaped}</div>')
        else:
            class_attr = (
                f' class="language-{html.escape(language)}"'
                if language
                else ""
            )
            blocks.append(f"<pre><code{class_attr}>{escaped}</code></pre>")
        code_lines.clear()
        code_language = ""

    for raw_line in text.splitlines():
        if code_language:
            if raw_line.strip() == "```":
                flush_code()
            else:
                code_lines.append(raw_line)
            continue
        line = raw_line.strip()
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            code_language = line[3:].strip() or "plain"
            continue
        if not line:
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading is not None:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            title = html.escape(heading.group(2).strip())
            blocks.append(f"<h{level}>{title}</h{level}>")
            continue
        if line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:].strip())
            continue
        flush_list()
        paragraph.append(line)
    if code_language:
        flush_code()
    flush_paragraph()
    flush_list()
    return "\n".join(blocks) if blocks else "<p></p>"


_MERMAID_BLOCK_RE = re.compile(
    r'<pre><code class="(?:language-)?mermaid">(?P<body>.*?)</code></pre>',
    re.DOTALL,
)


def _promote_mermaid_blocks(rendered: str) -> str:
    return _MERMAID_BLOCK_RE.sub(
        lambda match: f'<div class="mermaid">{match.group("body")}</div>',
        rendered,
    )


def _mermaid_script(rendered: str) -> str:
    if 'class="mermaid"' not in rendered:
        return ""
    return """
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>
    window.addEventListener("DOMContentLoaded", () => {
      const popupFeatures =
        "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";

      function prepareMermaidPopouts() {
        for (const diagram of document.querySelectorAll(".mermaid")) {
          if (diagram.dataset.electroboyPopout === "1") {
            continue;
          }
          diagram.dataset.electroboyPopout = "1";
          diagram.tabIndex = 0;
          diagram.setAttribute("role", "button");
          diagram.setAttribute(
            "aria-label",
            "Open Mermaid diagram in a separate window",
          );
          diagram.title = "Open diagram";
          diagram.addEventListener("click", () => openMermaidPopup(diagram));
          diagram.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") {
              return;
            }
            event.preventDefault();
            openMermaidPopup(diagram);
          });
        }
      }

      function openMermaidPopup(diagram) {
        let popupUrl = "";
        try {
          popupUrl = URL.createObjectURL(new Blob(
            [mermaidPopupHtml(diagramMarkup(diagram))],
            { type: "text/html" },
          ));
        } catch (error) {
          console.warn("Could not prepare Mermaid popup", error);
          return;
        }
        const popup = window.open(
          popupUrl,
          "electroboy-mermaid-diagram",
          popupFeatures,
        );
        if (!popup) {
          URL.revokeObjectURL(popupUrl);
          return;
        }
        window.setTimeout(() => URL.revokeObjectURL(popupUrl), 30000);
      }

      function diagramMarkup(diagram) {
        const clone = diagram.cloneNode(true);
        clone.classList.add("popup-mermaid-diagram");
        clone.removeAttribute("tabindex");
        clone.removeAttribute("role");
        clone.removeAttribute("title");
        return clone.outerHTML;
      }

      function mermaidPopupHtml(diagramHtml) {
        return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mermaid diagram</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #10141f;
      --panel: #151b29;
      --text: #e7edf7;
      --muted: #aab8cf;
      --border: #2a3142;
      --button: #1d2638;
      --accent: #66d9e8;
    }
    * {
      box-sizing: border-box;
    }
    html,
    body {
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: hidden;
    }
    .diagram-window {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      height: 100vh;
    }
    .diagram-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 42px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      padding: 0 12px;
    }
    .diagram-title {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
    }
    .diagram-controls {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .diagram-controls button {
      min-width: 34px;
      height: 30px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: var(--button);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 750;
    }
    .diagram-controls button:hover:not(:disabled) {
      border-color: var(--accent);
      background: #22314a;
    }
    .diagram-controls button:disabled {
      cursor: default;
      opacity: 0.45;
    }
    .zoom-level {
      min-width: 48px;
      text-align: center;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }
    .diagram-viewport {
      min-height: 0;
      height: 100%;
      width: 100%;
      overflow: auto;
      background: var(--bg);
      cursor: grab;
      user-select: none;
    }
    .diagram-viewport.dragging {
      cursor: grabbing;
    }
    .diagram-viewport.dragging * {
      user-select: none;
    }
    .diagram-content {
      display: inline-block;
      min-height: 100%;
      min-width: 100%;
      padding: 24px;
    }
    .diagram-content .mermaid {
      display: inline-block;
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
      cursor: default;
    }
    .diagram-content svg {
      display: block;
      max-width: none !important;
      max-height: none !important;
      height: auto;
      overflow: visible;
    }
  </style>
</head>
<body>
  <main class="diagram-window">
    <header class="diagram-toolbar">
      <span id="diagramTitle" class="diagram-title">Mermaid diagram</span>
      <div class="diagram-controls">
        <button id="zoomOut" type="button" title="Zoom out" aria-label="Zoom out">-</button>
        <span id="zoomLevel" class="zoom-level">100%</span>
        <button id="zoomReset" type="button" title="Reset zoom" aria-label="Reset zoom">100%</button>
        <button id="zoomIn" type="button" title="Zoom in" aria-label="Zoom in">+</button>
      </div>
    </header>
    <section class="diagram-viewport">
      <div id="diagramContent" class="diagram-content">${diagramHtml}</div>
    </section>
  </main>
  <script>
    (() => {
      const minimumZoom = 0.4;
      const maximumZoom = 4;
      const zoomStep = 0.25;
      let zoom = 1;
      let naturalWidth = 0;
      let naturalHeight = 0;
      let baseWidth = 0;
      let baseHeight = 0;
      let panState = null;
      const content = document.getElementById("diagramContent");
      const viewport = document.querySelector(".diagram-viewport");
      const toolbar = document.querySelector(".diagram-toolbar");
      const zoomLevel = document.getElementById("zoomLevel");
      const zoomOut = document.getElementById("zoomOut");
      const zoomReset = document.getElementById("zoomReset");
      const zoomIn = document.getElementById("zoomIn");

      function contentBox(svg) {
        try {
          const box = svg.getBBox();
          if (
            Number.isFinite(box.x) &&
            Number.isFinite(box.y) &&
            Number.isFinite(box.width) &&
            Number.isFinite(box.height) &&
            box.width > 0 &&
            box.height > 0
          ) {
            return box;
          }
        } catch (error) {
          return null;
        }
        return null;
      }

      function readSvgDimensions(svg) {
        const box = contentBox(svg);
        if (box) {
          svg.setAttribute(
            "viewBox",
            [box.x, box.y, box.width, box.height].join(" "),
          );
          svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
          return { width: box.width, height: box.height };
        }
        const viewBox = (svg.getAttribute("viewBox") || "")
          .trim()
          .split(/\\s+/)
          .map(Number);
        const width = viewBox.length === 4 && Number.isFinite(viewBox[2])
          ? viewBox[2]
          : Number.parseFloat(svg.getAttribute("width")) || svg.clientWidth || 800;
        const height = viewBox.length === 4 && Number.isFinite(viewBox[3])
          ? viewBox[3]
          : Number.parseFloat(svg.getAttribute("height")) || svg.clientHeight || 600;
        return { width, height };
      }

      function updateBaseSize() {
        if (!naturalWidth || !naturalHeight) {
          return;
        }
        const viewportRect = viewport.getBoundingClientRect();
        const toolbarRect = toolbar.getBoundingClientRect();
        const viewportWidth = viewportRect.width || window.innerWidth || 980;
        const viewportHeight =
          viewportRect.height ||
          Math.max(220, (window.innerHeight || 720) - toolbarRect.height);
        const availableWidth = Math.max(320, viewportWidth - 48);
        const availableHeight = Math.max(220, viewportHeight - 48);
        const fitScale = Math.min(
          availableWidth / naturalWidth,
          availableHeight / naturalHeight,
        );
        const scale = Math.max(0.1, fitScale);
        baseWidth = naturalWidth * scale;
        baseHeight = naturalHeight * scale;
      }

      function applyZoom() {
        const svg = content.querySelector("svg");
        if (svg) {
          svg.style.width = (baseWidth * zoom) + "px";
          svg.style.height = (baseHeight * zoom) + "px";
        } else {
          content.style.fontSize = (16 * zoom) + "px";
        }
        zoomLevel.textContent = Math.round(zoom * 100) + "%";
        zoomOut.disabled = zoom <= minimumZoom;
        zoomIn.disabled = zoom >= maximumZoom;
      }

      function changeZoom(delta) {
        zoom = Math.max(minimumZoom, Math.min(maximumZoom, zoom + delta));
        applyZoom();
      }

      function startPan(event) {
        if (event.button !== 0 || event.target.closest("a")) {
          return;
        }
        event.preventDefault();
        panState = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          scrollLeft: viewport.scrollLeft,
          scrollTop: viewport.scrollTop,
        };
        viewport.classList.add("dragging");
        viewport.setPointerCapture(event.pointerId);
      }

      function updatePan(event) {
        if (!panState || event.pointerId !== panState.pointerId) {
          return;
        }
        event.preventDefault();
        viewport.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX);
        viewport.scrollTop = panState.scrollTop - (event.clientY - panState.startY);
      }

      function finishPan(event) {
        if (!panState || event.pointerId !== panState.pointerId) {
          return;
        }
        panState = null;
        viewport.classList.remove("dragging");
        try {
          viewport.releasePointerCapture(event.pointerId);
        } catch (error) {
          return;
        }
      }

      function initializeDiagramPopup(title) {
        const svg = content.querySelector("svg");
        if (svg) {
          const dimensions = readSvgDimensions(svg);
          naturalWidth = dimensions.width;
          naturalHeight = dimensions.height;
          updateBaseSize();
        }
        applyZoom();
      }

      function fitAfterLayout() {
        initializeDiagramPopup("Mermaid diagram");
      }

      zoomOut.addEventListener("click", () => changeZoom(-zoomStep));
      zoomReset.addEventListener("click", () => {
        zoom = 1;
        applyZoom();
      });
      zoomIn.addEventListener("click", () => changeZoom(zoomStep));
      viewport.addEventListener("pointerdown", startPan);
      viewport.addEventListener("pointermove", updatePan);
      viewport.addEventListener("pointerup", finishPan);
      viewport.addEventListener("pointercancel", finishPan);
      window.addEventListener("resize", () => {
        updateBaseSize();
        applyZoom();
      });
      window.requestAnimationFrame(() => {
        fitAfterLayout();
        window.requestAnimationFrame(fitAfterLayout);
      });
      window.setTimeout(fitAfterLayout, 100);
    })();
  <\\/script>
</body>
</html>`;
      }

      async function renderMermaidBlocks() {
        if (!window.mermaid) {
          prepareMermaidPopouts();
          return;
        }
        window.mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: {
            background: "#10141f",
            mainBkg: "#151b29",
            primaryColor: "#151b29",
            primaryTextColor: "#e7edf7",
            primaryBorderColor: "#364156",
            lineColor: "#66d9e8",
            secondaryColor: "#1d2638",
            secondaryTextColor: "#e7edf7",
            tertiaryColor: "#10141f",
            tertiaryTextColor: "#e7edf7",
            textColor: "#e7edf7",
            nodeBorder: "#364156",
            clusterBkg: "#10141f",
            clusterBorder: "#2a3142",
            edgeLabelBackground: "#10141f",
            fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          },
        });
        try {
          await window.mermaid.run({ querySelector: ".mermaid" });
        } catch (error) {
          console.warn("Mermaid render failed", error);
        }
        prepareMermaidPopouts();
      }

      renderMermaidBlocks();
    });
  </script>
"""


def _requirements_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["requirements"])


def _stage_command(
    root: Path,
    command: str,
    *,
    force: bool = False,
    reason: str | None = None,
    interactive: bool = False,
) -> list[str]:
    command_parts = ["electroboy", command]
    if force:
        command_parts.append("--force")
    if reason:
        command_parts.extend(["--reason", reason])
    if interactive:
        command_parts.append("--interactive")
    return _electroboy_command(root, command_parts[1:])


def _progress_once_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["progress", "--once"])


def _status_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["status"])


def _documentation_command(
    root: Path,
    *,
    interactive: bool = True,
    target: str | None = None,
) -> list[str]:
    args = ["document", "--sidecar"]
    if interactive:
        args.append("--interactive")
    if target:
        args.extend(["--target", target])
    return _electroboy_command(root, args)


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


def _creative_agent_target(
    root: Path,
    *,
    active_target: dict[str, object] | None = None,
    active_document: str | None = None,
) -> dict[str, str] | None:
    if isinstance(active_target, dict):
        target_type = str(active_target.get("type") or "").strip()
        target_path = str(active_target.get("path") or "").strip()
        if target_type == "document" and target_path:
            normalized_path, _path = _document_target_path(root, target_path)
            return {"type": "document", "path": normalized_path}
        if target_type == "freeform-corkboard" and target_path:
            normalized_path, path = _creative_path(root, target_path)
            if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
                raise StateError("freeform corkboard path must end in .corkboard.json")
            if not path.is_file():
                raise StateError("freeform corkboard path is not a file")
            return {"type": "freeform-corkboard", "path": normalized_path}
        if target_type == "folder-corkboard" and target_path:
            normalized_path, path = _creative_path(root, target_path)
            if not path.is_dir():
                raise StateError("folder corkboard path is not a directory")
            return {"type": "folder-corkboard", "path": normalized_path}
    if active_document:
        if active_document.endswith(CREATIVE_CORKBOARD_SUFFIX):
            normalized_path, _path = _creative_path(root, active_document)
            return {"type": "freeform-corkboard", "path": normalized_path}
        normalized_path, _path = _document_target_path(root, active_document)
        return {"type": "document", "path": normalized_path}
    return None


def _creative_writing_command(
    root: Path,
    active_target: dict[str, str] | None = None,
) -> list[str]:
    return [
        "codex",
        "--cd",
        str(root),
        "--sandbox",
        "workspace-write",
        _creative_writing_prompt(active_target),
    ]


def _creative_writing_prompt(active_target: dict[str, str] | None = None) -> str:
    target_lines = _creative_writing_target_prompt_lines(active_target)
    return "\n".join(
        [
            "Act as a creative writing collaborator inside this project.",
            "",
            "The writer may move fluidly among chapters, character notes,",
            "corkboard ideas, reviews, research, and scratchpad notes.",
            "Markdown files are the source of truth for prose and notes.",
            "Use docs/corkboard-api.md for corkboard operations.",
            "Do not edit corkboard JSON directly unless the writer asks.",
            "Do not rewrite or reorganize files until the writer asks.",
            "When asked to write or revise without naming a different file,",
            "work in the active target.",
            "Use scratchpad/scratchpad.md as optional context for rough notes.",
            "Keep responses concise unless the writer asks for a draft.",
            *target_lines,
        ]
    )


def _creative_writing_target_prompt_lines(
    active_target: dict[str, str] | None,
) -> list[str]:
    if not active_target:
        return []
    target_type = active_target.get("type", "")
    target_path = active_target.get("path", "")
    if target_type == "document":
        return [
            "",
            f"Current active target: document {target_path}.",
            "Treat it as the document displayed in the middle pane.",
        ]
    if target_type == "freeform-corkboard":
        return [
            "",
            f"Current active target: freeform corkboard {target_path}.",
            "This board contains arbitrary cards with x/y positions.",
            "Use `electroboy corkboard` commands from docs/corkboard-api.md",
            "for card additions, edits, moves, styling, and deletes.",
        ]
    if target_type == "folder-corkboard":
        return [
            "",
            f"Current active target: folder corkboard {target_path}.",
            "This board is backed by that folder's files and subfolders.",
            "Use `electroboy corkboard folder` commands for notes and order.",
            "Create, delete, or rename files only when the writer asks.",
        ]
    return []


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


def _progress_snapshot(root: Path | str, timeout: float = 5.0) -> tuple[str, bool]:
    project_root = Path(root).expanduser().resolve()
    try:
        completed = subprocess.run(
            _progress_once_command(project_root),
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
        return f"{output}progress command timed out\n", False
    output = completed.stdout or ""
    if completed.returncode != 0:
        if output and not output.endswith("\n"):
            output += "\n"
        output += f"progress command exited with code {completed.returncode}\n"
        return output, False
    return output or "progress: none\n", True


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


def _subprocess_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _terminal_input_for_message(message: str) -> str:
    return "".join(_terminal_input_chunks_for_message(message))


def _terminal_input_for_key(key: str) -> str:
    if re.fullmatch(r"[0-9]", key):
        return key
    keys = {
        "enter": "\r",
        "escape": "\x1b",
        "tab": "\t",
        "backspace": "\x7f",
        "delete": "\x1b[3~",
        "up": "\x1b[A",
        "down": "\x1b[B",
        "right": "\x1b[C",
        "left": "\x1b[D",
    }
    try:
        return keys[key]
    except KeyError:
        choices = ", ".join(sorted(keys))
        raise AgentSessionError(
            f"unknown terminal key {key!r}; choose one of: {choices}, 0-9"
        )


def _terminal_input_chunks_for_message(message: str) -> list[str]:
    text = message.replace("\r\n", "\n").replace("\r", "\n")
    text = text.rstrip("\n")
    if "\n" in text:
        return [f"\x1b[200~{text}\x1b[201~", "\r"]
    return [text, "\r"]


def _normalize_session_backend(value: str | None) -> str:
    backend = str(value or SESSION_BACKEND_PTY).strip().lower()
    if backend in {"", SESSION_BACKEND_PTY}:
        return SESSION_BACKEND_PTY
    if backend == SESSION_BACKEND_TMUX:
        return SESSION_BACKEND_TMUX
    raise StateError(f"unknown session backend: {value}")


def _session_backend_from_env() -> str:
    return _normalize_session_backend(os.environ.get(SESSION_BACKEND_ENV))


def _tmux_session_name(session_id: str) -> str:
    safe_session_id = _download_name_part(session_id)
    return f"electroboy-{safe_session_id[:32]}"


def _tmux_run(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    command = ["tmux", *args]
    result = subprocess.run(
        command,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise AgentSessionError(stderr or f"tmux command failed: {shlex.join(command)}")
    return result


def _tmux_has_session(tmux_name: str) -> bool:
    if shutil.which("tmux") is None:
        return False
    result = subprocess.run(
        ["tmux", "has-session", "-t", tmux_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _tmux_shell_command(command: list[str], cwd: Path | str) -> str:
    root = Path(cwd).expanduser().resolve()
    env = _agent_process_env()
    env["ELECTROBOY_PROJECT_ROOT"] = str(root)
    env["AI_PIPELINE_PROJECT_ROOT"] = str(root)
    env_args = [f"{key}={value}" for key, value in sorted(env.items())]
    return "exec " + shlex.join(["env", *env_args, *command])


def _tmux_key_name(key: str) -> str | None:
    normalized = key.strip().lower()
    mapping = {
        "enter": "Enter",
        "escape": "Escape",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "backspace": "BSpace",
        "delete": "DC",
    }
    if normalized in mapping:
        return mapping[normalized]
    if re.fullmatch(r"[0-9]", normalized):
        return None
    return None


def _tmux_capture_pane(tmux_name: str) -> str:
    result = _tmux_run(
        ["capture-pane", "-p", "-e", "-J", "-t", tmux_name, "-S", "-2000"],
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace")


def _tmux_capture_delta(previous: str, current: str) -> str:
    if not previous:
        return current
    if current.startswith(previous):
        return current[len(previous) :]
    previous_lines = previous.splitlines()
    current_lines = current.splitlines()
    for count in range(min(len(previous_lines), len(current_lines)), 0, -1):
        if previous_lines[-count:] == current_lines[:count]:
            suffix = "\n".join(current_lines[count:])
            return suffix + ("\n" if suffix and current.endswith("\n") else "")
    return current


def _disable_terminal_echo(slave_fd: int) -> None:
    try:
        attributes = termios.tcgetattr(slave_fd)
        attributes[3] &= ~(
            termios.ECHO
            | termios.ECHOE
            | termios.ECHOK
            | termios.ECHONL
        )
        termios.tcsetattr(slave_fd, termios.TCSANOW, attributes)
    except termios.error:
        return


def _clamp_terminal_columns(columns: int) -> int:
    return max(MIN_TERMINAL_COLUMNS, min(columns, MAX_TERMINAL_COLUMNS))


def _clamp_terminal_rows(rows: int) -> int:
    return max(MIN_TERMINAL_ROWS, min(rows, MAX_TERMINAL_ROWS))


def _set_terminal_size(fd: int, columns: int, rows: int) -> None:
    columns = _clamp_terminal_columns(columns)
    rows = _clamp_terminal_rows(rows)
    packed_size = struct.pack("HHHH", rows, columns, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed_size)
    except OSError:
        return


def _agent_process_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["ELECTROBOY_DISABLE_SESSION_RESUME"] = "1"
    env.pop("NO_COLOR", None)
    env.pop("CLICOLOR", None)
    env.pop("FORCE_COLOR", None)
    module_path = str(_module_search_path())
    existing_pythonpath = env.get("PYTHONPATH", "")
    entries = [module_path]
    entries.extend(
        entry
        for entry in existing_pythonpath.split(os.pathsep)
        if entry and entry != module_path
    )
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def _module_search_path() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_terminal_output(
    text: str,
    pending: str = "",
) -> tuple[str, str]:
    combined = f"{pending}{text}"
    output: list[str] = []
    index = 0
    while index < len(combined):
        char = combined[index]
        if char == "\x1b":
            consumed, incomplete = _terminal_escape_length(combined, index)
            if incomplete:
                return _normalize_terminal_text("".join(output)), combined[index:]
            index += consumed
            continue
        if char == "\r":
            if index + 1 < len(combined) and combined[index + 1] == "\n":
                output.append("\n")
                index += 2
            else:
                output.append("\n")
                index += 1
            continue
        if char == "\b":
            if output and output[-1] != "\n":
                output.pop()
            index += 1
            continue
        if char in _CONTROL_CHARS_TO_DROP:
            index += 1
            continue
        output.append(char)
        index += 1
    return _normalize_terminal_text("".join(output)), ""


def _terminal_escape_length(text: str, index: int) -> tuple[int, bool]:
    if index + 1 >= len(text):
        return len(text) - index, True
    introducer = text[index + 1]
    if introducer == "[":
        return _consume_until_final_byte(text, index, 2)
    if introducer == "]":
        return _consume_string_control(text, index)
    if introducer in {"P", "^", "_", "X"}:
        return _consume_string_control(text, index)
    if introducer in {"(", ")", "*", "+", "-", ".", "/"}:
        if index + 2 >= len(text):
            return len(text) - index, True
        return 3, False
    if "@" <= introducer <= "_":
        return 2, False
    return 1, False


def _consume_until_final_byte(
    text: str,
    index: int,
    offset: int,
) -> tuple[int, bool]:
    cursor = index + offset
    while cursor < len(text):
        if "@" <= text[cursor] <= "~":
            return cursor - index + 1, False
        cursor += 1
    return len(text) - index, True


def _consume_string_control(text: str, index: int) -> tuple[int, bool]:
    cursor = index + 2
    while cursor < len(text):
        char = text[cursor]
        if char == "\x07":
            return cursor - index + 1, False
        if char == "\x1b":
            if cursor + 1 < len(text) and text[cursor + 1] == "\\":
                return cursor - index + 2, False
            return cursor - index, False
        cursor += 1
    return len(text) - index, True


def _normalize_terminal_text(text: str) -> str:
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def _markdown_code_block(text: str, language: str = "") -> str:
    body = text.rstrip("\n")
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}{language}\n{body}\n{fence}"


def _session_export_filename(session: AgentSession) -> str:
    kind = _download_name_part(session.kind or "agent")
    timestamp = _download_name_part(utc_now())
    return f"agent-session-{kind}-{timestamp}.md"


def _progress_export_filename() -> str:
    return f"progress-log-{_download_name_part(utc_now())}.md"


def _download_name_part(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    text = text.strip(".-")
    return text or "export"


def _session_events_markdown(session: AgentSession) -> str:
    events = session.events()
    payload = session.payload()
    lines = [
        "# Agent Session Export",
        "",
        "## Metadata",
        "",
        f"- Session id: `{session.session_id}`",
        f"- Kind: `{session.kind}`",
        f"- Label: {session.label}",
        f"- Status: `{payload.get('status', session.status)}`",
        f"- Created: {session.created_at}",
        f"- Exported: {utc_now()}",
        f"- Working directory: `{session.cwd}`",
        f"- Interactive: `{str(session.interactive).lower()}`",
        f"- Return code: `{session.returncode}`",
        "",
        "### Command",
        "",
        _markdown_code_block(shlex.join(session.command), "console"),
        "",
        "## Transcript",
        "",
    ]
    if not events:
        lines.extend(["No events were recorded.", ""])
        return "\n".join(lines).rstrip() + "\n"

    pending_output: list[str] = []
    pending_start: int | None = None
    pending_end: int | None = None

    def flush_output() -> None:
        nonlocal pending_output, pending_start, pending_end
        if not pending_output:
            return
        title = (
            f"### Output Events {pending_start}-{pending_end}"
            if pending_start != pending_end
            else f"### Output Event {pending_start}"
        )
        lines.extend([title, "", _markdown_code_block("".join(pending_output), "text"), ""])
        pending_output = []
        pending_start = None
        pending_end = None

    for event in events:
        event_id = int(event.get("id", 0) or 0)
        event_type = str(event.get("type") or "event")
        if event_type == "output":
            if pending_start is None:
                pending_start = event_id
            pending_end = event_id
            pending_output.append(str(event.get("text") or ""))
            continue
        flush_output()
        if event_type == "completed":
            lines.extend(
                [
                    f"### Event {event_id}: completed",
                    "",
                    f"- Return code: `{event.get('returncode')}`",
                    "",
                ]
            )
            continue
        text = str(event.get("text") or "")
        lines.extend(
            [
                f"### Event {event_id}: {event_type}",
                "",
                _markdown_code_block(text, "text") if text else "_No event text._",
                "",
            ]
        )
    flush_output()
    return "\n".join(lines).rstrip() + "\n"


def _progress_snapshot_markdown(project_root: Path, text: str, ok: bool) -> str:
    return "\n".join(
        [
            "# Progress Log Export",
            "",
            "## Metadata",
            "",
            f"- Project root: `{project_root}`",
            f"- Exported: {utc_now()}",
            f"- Snapshot status: `{'ok' if ok else 'error'}`",
            "",
            "## Progress",
            "",
            _markdown_code_block(text, "text"),
            "",
        ]
    )


def _handler_for(
    config: ServiceConfig,
    state: ServiceState,
) -> type[BaseHTTPRequestHandler]:
    class ElectroBoyRequestHandler(BaseHTTPRequestHandler):
        server_version = "ElectroBoyService/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in {"/", "/index.html"}:
                self._send_text(INDEX_HTML, "text/html; charset=utf-8")
                return
            if path == SPLASH_IMAGE_ROUTE:
                self._send_splash_image(SPLASH_IMAGE_RESOURCE)
                return
            if path == CREATIVE_SPLASH_IMAGE_ROUTE:
                self._send_splash_image(CREATIVE_SPLASH_IMAGE_RESOURCE)
                return
            if path == "/file-browser":
                self._send_file_browser_window(parsed.query)
                return
            if path.startswith("/pane/"):
                self._send_pane_window(path)
                return
            if path == "/api/health":
                self._send_json(
                    health_payload(
                        config.root,
                        config.module_registry,
                        config.workflow_registry,
                    )
                )
                return
            if path == "/api/registry":
                module_registry = config.module_registry or build_module_registry()
                workflow_registry = (
                    config.workflow_registry
                    or build_workflow_registry(module_registry)
                )
                self._send_json(
                    {
                        **registry_payload(
                            module_registry,
                            workflow_registry,
                        ),
                        "frontend_bundles": frontend_asset_payload(),
                    }
                )
                return
            if path == "/api/project":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.project_payload(context_id),
                )
                return
            if path == "/api/project/status":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.project_status_payload(context_id),
                )
                return
            if path == "/api/workflow":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.workflow_payload(context_id),
                )
                return
            if path == "/api/sessions":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.session_payload(context_id),
                )
                return
            if path == "/api/session-registry":
                self._send_json(state.session_registry_payload())
                return
            if path == "/api/sessions/export":
                self._send_session_export(parsed.query)
                return
            if path == "/api/progress/export":
                self._send_progress_export(parsed.query)
                return
            if path == "/api/documents/export":
                self._send_document_export(parsed.query)
                return
            if path == "/api/creative/tree":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.creative_tree(context_id),
                )
                return
            if path == "/api/creative/scratch":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.creative_scratchpad(context_id),
                )
                return
            if path == "/artifacts/edit":
                self._send_artifact_editor(parsed.query)
                return
            if path == "/api/files/browse":
                self._browse_files(parsed.query)
                return
            if path == "/artifacts/requirements":
                self._send_requirements_document(parsed.query)
                return
            if path == "/artifacts/design":
                self._send_design_document(parsed.query)
                return
            if path == "/artifacts/design-review":
                self._send_design_review_document(parsed.query)
                return
            if path == "/artifacts/implementation-plan":
                self._send_stage_document(parsed.query, "implementation-plan")
                return
            if path == "/artifacts/test-plan":
                self._send_stage_document(parsed.query, "test-plan")
                return
            if path == "/artifacts/implementation-report":
                self._send_stage_document(parsed.query, "code")
                return
            if path == "/artifacts/validation-report":
                self._send_stage_document(parsed.query, "validate")
                return
            if path == "/artifacts/document":
                self._send_document_target(parsed.query)
                return
            if path == "/artifacts/creative-corkboard":
                self._send_creative_corkboard(parsed.query)
                return
            if path == "/api/progress/events":
                self._send_progress_events(parsed.query)
                return
            if path == "/api/artifacts/events":
                self._send_artifact_events(parsed.query)
                return
            if path == "/api/sessions/events":
                self._send_selected_session_events(parsed.query)
                return
            if path == "/api/shell/events":
                self._send_project_shell_events(parsed.query)
                return
            if path == "/api/agents/requirements/events":
                self._send_agent_events(parsed.query)
                return
            if path == "/api/agents/design/events":
                self._send_design_agent_events(parsed.query)
                return
            if path == "/api/agents/design-review/events":
                self._send_design_review_agent_events(parsed.query)
                return
            self._send_json(
                {"error": "not found"},
                status=HTTPStatus.NOT_FOUND,
            )

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/contexts":
                self._send_json(state.create_context())
                return
            if path == "/api/project/open":
                self._open_project(parsed.query)
                return
            if path == "/api/project/new":
                self._create_project(parsed.query)
                return
            if path == "/api/meta/init":
                self._create_meta_project(parsed.query)
                return
            if path == "/api/meta/add":
                self._add_meta_repository(parsed.query)
                return
            if path == "/api/meta/start":
                self._start_meta_repository(parsed.query)
                return
            if path == "/api/meta/remove":
                self._remove_meta_repository(parsed.query)
                return
            if path == "/api/work-items/collections":
                self._create_feature_collection(parsed.query)
                return
            if path == "/api/work-items/collections/switch":
                self._switch_feature_collection(parsed.query)
                return
            if path == "/api/work-items/features":
                self._start_feature_work_item(parsed.query)
                return
            if path == "/api/work-items/features/switch":
                self._switch_feature_work_item(parsed.query)
                return
            if path == "/api/work-items/bugs":
                self._start_bug_work_item(parsed.query)
                return
            if path == "/api/work-items/bugs/switch":
                self._switch_bug_work_item(parsed.query)
                return
            if path == "/api/project/deactivate":
                self._deactivate_project(parsed.query)
                return
            if path == "/api/workflow/stage":
                self._select_workflow_stage(parsed.query)
                return
            if path == "/api/artifacts/edit":
                self._save_artifact_editor(parsed.query)
                return
            if path == "/api/creative/project/open":
                self._open_creative_project(parsed.query)
                return
            if path == "/api/creative/project/new":
                self._create_creative_project(parsed.query)
                return
            if path == "/api/creative/init":
                self._initialize_creative_workspace(parsed.query)
                return
            if path == "/api/creative/folders":
                self._create_creative_folder(parsed.query)
                return
            if path == "/api/creative/documents":
                self._create_creative_document(parsed.query)
                return
            if path == "/api/creative/corkboards":
                self._create_creative_corkboard(parsed.query)
                return
            if path == "/api/creative/rename":
                self._rename_creative_entry(parsed.query)
                return
            if path == "/api/creative/delete":
                self._delete_creative_entry(parsed.query)
                return
            if path == "/api/creative/scratch":
                self._save_creative_scratchpad(parsed.query)
                return
            if path == "/api/creative/corkboard":
                self._save_creative_corkboard(parsed.query)
                return
            if path == "/api/creative/agent/start":
                self._start_creative_writing_agent(parsed.query)
                return
            if path == "/api/agents/ad-hoc/start":
                self._start_ad_hoc_agent(parsed.query)
                return
            if path == "/api/sessions/select":
                self._select_session(parsed.query)
                return
            if path == "/api/sessions/attach":
                self._attach_session(parsed.query)
                return
            if path == "/api/sessions/message":
                self._send_selected_session_message(parsed.query)
                return
            if path == "/api/sessions/key":
                self._send_selected_session_key(parsed.query)
                return
            if path == "/api/sessions/raw":
                self._send_selected_session_raw(parsed.query)
                return
            if path == "/api/sessions/interrupt":
                self._interrupt_selected_session(parsed.query)
                return
            if path == "/api/sessions/resize":
                self._resize_selected_session(parsed.query)
                return
            if path == "/api/shell/start":
                self._start_project_shell(parsed.query)
                return
            if path == "/api/shell/input":
                self._send_project_shell_input(parsed.query)
                return
            if path == "/api/shell/resize":
                self._resize_project_shell(parsed.query)
                return
            if path == "/api/shell/stop":
                self._stop_project_shell(parsed.query)
                return
            if path == "/api/agents/requirements/start":
                self._start_requirements_agent(parsed.query)
                return
            if path == "/api/agents/requirements/restart":
                self._restart_requirements_agent(parsed.query)
                return
            if path == "/api/agents/requirements/complete":
                self._complete_requirements_agent(parsed.query)
                return
            if path == "/api/agents/requirements/skip":
                self._skip_requirements_approval(parsed.query)
                return
            if path == "/api/agents/requirements/skip-approval":
                self._skip_requirements_approval(parsed.query)
                return
            if path == "/api/agents/requirements/approve":
                self._approve_requirements(parsed.query)
                return
            if path == "/api/agents/requirements/message":
                self._send_requirements_message(parsed.query)
                return
            if path == "/api/agents/requirements/interrupt":
                self._interrupt_requirements_agent(parsed.query)
                return
            if path == "/api/agents/requirements/resize":
                self._resize_requirements_agent(parsed.query)
                return
            if path == "/api/agents/design/start":
                self._start_design_agent(parsed.query)
                return
            if path == "/api/agents/design/restart":
                self._restart_design_agent(parsed.query)
                return
            if path == "/api/agents/design/complete":
                self._complete_design_agent(parsed.query)
                return
            if path == "/api/agents/design/message":
                self._send_design_message(parsed.query)
                return
            if path == "/api/agents/design/interrupt":
                self._interrupt_design_agent(parsed.query)
                return
            if path == "/api/agents/design/resize":
                self._resize_design_agent(parsed.query)
                return
            if path == "/api/agents/design-review/start":
                self._start_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/start-interactive":
                self._start_interactive_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/stop":
                self._stop_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/complete":
                self._complete_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/approve":
                self._approve_design(parsed.query)
                return
            if path == "/api/agents/design-review/skip-approval":
                self._skip_design_approval(parsed.query)
                return
            if path == "/api/agents/design-review/restart":
                self._restart_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/interrupt":
                self._interrupt_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/resize":
                self._resize_design_review_agent(parsed.query)
                return
            generic_route = _generic_agent_route(path)
            if generic_route is not None:
                stage, action = generic_route
                self._handle_generic_stage_agent(parsed.query, stage, action)
                return
            if path == "/api/agents/documentation/start":
                self._start_documentation_agent(parsed.query)
                return
            if path == "/api/agents/design-approve/approve":
                self._approve_design(parsed.query)
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
                    len(INDEX_HTML.encode("utf-8")),
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

        def _browse_files(self, query: str) -> None:
            params = parse_qs(query)
            path = (params.get("path") or [str(state.root)])[0]
            mode = (params.get("mode") or ["directory"])[0]
            show_hidden = (params.get("hidden") or ["0"])[0] == "1"
            try:
                if mode == "file":
                    payload = browse_files(path, show_hidden=show_hidden)
                elif mode == "markdown":
                    payload = browse_markdown_files(path, show_hidden=show_hidden)
                else:
                    payload = browse_directories(path, show_hidden=show_hidden)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json(payload)

        def _open_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.open_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _create_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _open_creative_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.open_creative_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _create_creative_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_creative_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _create_meta_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_meta_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _add_meta_repository(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.add_meta_repository(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _start_meta_repository(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                repository = payload.get("repository") or payload.get("path") or ""
                self._send_json(
                    state.start_meta_repository(
                        context_id,
                        str(repository),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _remove_meta_repository(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                repository = payload.get("repository") or payload.get("path") or ""
                self._send_json(
                    state.remove_meta_repository(
                        context_id,
                        str(repository),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _create_feature_collection(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_feature_collection(
                        context_id,
                        str(payload.get("name") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _switch_feature_collection(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.switch_feature_collection(
                        context_id,
                        str(payload.get("collection_id") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _start_feature_work_item(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.start_feature_work_item(
                        context_id,
                        title=str(payload.get("title") or ""),
                        feature_name=str(payload.get("name") or "") or None,
                        collection_id=str(payload.get("collection_id") or "") or None,
                        parent_slug=str(payload.get("parent_slug") or "") or None,
                        branch=bool(payload.get("branch")),
                        stash_subrepo_changes=bool(
                            payload.get("stash_subrepo_changes")
                        ),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    _work_item_error_payload(error),
                    status=HTTPStatus.CONFLICT,
                )

        def _switch_feature_work_item(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.switch_feature_work_item(
                        context_id,
                        str(payload.get("slug") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _start_bug_work_item(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.start_bug_work_item(
                        context_id,
                        issue_reference=str(payload.get("issue_reference") or ""),
                        branch=bool(payload.get("branch")),
                        stash_subrepo_changes=bool(
                            payload.get("stash_subrepo_changes")
                        ),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    _work_item_error_payload(error),
                    status=HTTPStatus.CONFLICT,
                )

        def _switch_bug_work_item(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.switch_bug_work_item(
                        context_id,
                        str(payload.get("slug") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _deactivate_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.deactivate_project(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _select_workflow_stage(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.select_workflow_stage(
                        context_id,
                        str(payload.get("stage") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _select_session(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.select_session(
                        context_id,
                        str(payload.get("session_id") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _attach_session(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.attach_session(
                        context_id,
                        str(payload.get("session_id") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _send_selected_session_events(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                params = parse_qs(query)
                session_id = str((params.get("session_id") or [""])[0])
                session = (
                    state.session_by_id(context_id, session_id)
                    if session_id
                    else state.selected_session(context_id)
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": "no agent session is selected"},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_session_events(session)

        def _send_session_export(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                params = parse_qs(query)
                session_id = str((params.get("session_id") or [""])[0])
                session = (
                    state.session_by_id(context_id, session_id)
                    if session_id
                    else state.selected_session(context_id)
                )
            except (AgentSessionError, StateError) as error:
                self._send_text(
                    str(error),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_text(
                    "no agent session is selected",
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_download(
                _session_events_markdown(session),
                _session_export_filename(session),
            )

        def _send_selected_session_message(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                message = str(payload.get("message") or "")
                if not message.strip():
                    self._send_json(
                        {"error": "message is empty"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                session_id = str(payload.get("session_id") or "")
                if session_id:
                    state.send_session_message(context_id, session_id, message)
                else:
                    state.send_selected_session_message(context_id, message)
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "sent"})

        def _send_selected_session_key(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                key = str(payload.get("key") or "")
                if not key:
                    self._send_json(
                        {"error": "key is required"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                state.send_selected_session_key(context_id, key)
            except AgentSessionError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except (StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json({"status": "sent"})

        def _send_selected_session_raw(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                data = str(payload.get("data") or "")
                if not data:
                    self._send_json(
                        {"error": "data is required"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                state.send_selected_session_raw(context_id, data)
            except AgentSessionError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except (StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json({"status": "sent"})

        def _interrupt_selected_session(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                state.interrupt_selected_session(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "interrupted"})

        def _resize_selected_session(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                columns = int(payload.get("columns") or 120)
                rows = int(payload.get("rows") or 32)
                session_id = str(payload.get("session_id") or "").strip()
                if session_id:
                    state.resize_session(context_id, session_id, columns, rows)
                else:
                    state.resize_selected_session(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _start_project_shell(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_project_shell(context_id)
                self._send_json(
                    {
                        **state.project_payload(context_id),
                        "status": "started" if started else "already running",
                        "shell_session": session.payload(selected=False),
                    }
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _send_project_shell_events(self, query: str) -> None:
            self._send_session_events(
                query,
                state.current_project_shell_session,
                "project shell has not been started",
            )

        def _send_project_shell_input(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                state.send_project_shell_input(
                    context_id,
                    str(payload.get("data") or ""),
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "sent"})

        def _resize_project_shell(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                columns = int(payload.get("columns") or 120)
                rows = int(payload.get("rows") or 32)
                state.resize_project_shell(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _stop_project_shell(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.stop_project_shell(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _send_requirements_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.requirements_document_root(context_id)
                params = parse_qs(query)
                embedded = str((params.get("embed") or [""])[0]) == "1"
                zoom_percent = _document_zoom_from_params(params)
                page, status = requirements_document_html(
                    project_root,
                    embedded=embedded,
                    zoom_percent=zoom_percent,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

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

        def _send_file_browser_window(self, query: str) -> None:
            params = parse_qs(query)
            initial_path = (params.get("path") or [str(state.root)])[0]
            mode = (params.get("mode") or ["project"])[0]
            self._send_text(
                file_browser_window_html(initial_path, mode),
                "text/html; charset=utf-8",
            )

        def _send_design_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                page, status = design_document_html(project_root)
            except (OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_design_review_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                page, status = design_review_document_html(project_root)
            except (OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_stage_document(self, query: str, stage: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                page, status = stage_document_html(project_root, stage)
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_document_target(self, query: str) -> None:
            try:
                params = parse_qs(query)
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                path = params.get("path", [""])[0]
                title = params.get("title", [""])[0].strip() or None
                embedded = params.get("embed", ["0"])[0] == "1"
                create_missing = params.get("create", ["0"])[0] == "1"
                zoom_percent = _document_zoom_from_params(params)
                page, status = document_target_html(
                    project_root,
                    path,
                    title=title,
                    embedded=embedded,
                    create_missing=create_missing,
                    zoom_percent=zoom_percent,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_creative_corkboard(self, query: str) -> None:
            try:
                params = parse_qs(query)
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                folder_path = str((params.get("path") or [""])[0])
                title = str((params.get("title") or [""])[0]).strip() or None
                page, status = creative_corkboard_html(
                    project_root,
                    folder_path,
                    title=title,
                    context_id=context_id,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_artifact_editor(self, query: str) -> None:
            try:
                params = parse_qs(query)
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                artifact = str((params.get("artifact") or [""])[0]).strip()
                requested_path = str((params.get("path") or [""])[0])
                title = str((params.get("title") or [""])[0]).strip() or None
                create_missing = str((params.get("create") or [""])[0]) == "1"
                rich_editor = (
                    state.project_mode(context_id) == "creative"
                    and artifact == "document"
                )
                editor_font_size = _artifact_editor_font_size_from_params(params)
                page, status = artifact_editor_html(
                    project_root,
                    artifact,
                    requested_path,
                    title=title,
                    create_missing=create_missing,
                    context_id=context_id,
                    rich_editor=rich_editor,
                    editor_font_size=editor_font_size,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _save_artifact_editor(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                payload = self._read_json_body()
                artifact = str(payload.get("artifact") or "")
                requested_path = str(payload.get("path") or "")
                self._send_json(
                    save_artifact_edit(
                        project_root,
                        artifact,
                        requested_path,
                        payload,
                    )
                )
            except (AgentSessionError, OSError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _save_creative_corkboard(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.save_creative_corkboard(context_id, payload)
                )
            except (AgentSessionError, OSError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
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

        def _start_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_requirements_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start requirements agent: {error}"},
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

        def _restart_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, _started = state.restart_requirements_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not restart requirements agent: {error}"},
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

        def _complete_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.complete_requirements_agent(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _approve_requirements(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.approve_requirements(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _skip_requirements_approval(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(
                    state.approve_requirements(context_id, skip_approval=True)
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _send_requirements_message(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session = state.current_requirements_session(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": "requirements agent has not been started"},
                    status=HTTPStatus.CONFLICT,
                )
                return
            try:
                payload = self._read_json_body()
            except ValueError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            message = str(payload.get("message") or "")
            if not message.strip():
                self._send_json(
                    {"error": "message is empty"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                session.send(message)
            except AgentSessionError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "sent"})

        def _interrupt_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                state.interrupt_requirements_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "interrupted"})

        def _send_agent_events(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session = state.current_requirements_session(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": "requirements agent has not been started"},
                    status=HTTPStatus.CONFLICT,
                )
                return
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

        def _resize_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                columns = int(payload.get("columns") or 120)
                rows = int(payload.get("rows") or 32)
                state.resize_requirements_agent(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _start_design_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_design_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start design agent: {error}"},
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

        def _restart_design_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, _started = state.restart_design_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not restart design agent: {error}"},
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

        def _complete_design_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.complete_design_agent(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _start_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_design_review_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start design review: {error}"},
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

        def _start_interactive_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_design_review_agent(
                    context_id,
                    interactive=True,
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start interactive design review: {error}"},
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

        def _start_documentation_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                session, started = state.start_documentation_agent(
                    context_id,
                    interactive=True,
                    target=str(payload.get("target") or ""),
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except ValueError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start documentation agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                    "session_id": session.session_id,
                }
            )

        def _initialize_creative_workspace(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.initialize_creative_workspace(context_id))
            except (AgentSessionError, StateError, OSError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _create_creative_folder(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_creative_folder(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _create_creative_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_creative_document(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _create_creative_corkboard(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_creative_corkboard(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _rename_creative_entry(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.rename_creative_entry(
                        context_id,
                        str(payload.get("path") or ""),
                        str(payload.get("new_name") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _delete_creative_entry(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.delete_creative_entry(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _save_creative_scratchpad(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.save_creative_scratchpad(
                        context_id,
                        str(payload.get("markdown") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _start_creative_writing_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                active_target = payload.get("active_target")
                session, started = state.start_creative_writing_agent(
                    context_id,
                    active_document=str(payload.get("active_document") or ""),
                    active_target=(
                        active_target if isinstance(active_target, dict) else None
                    ),
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start creative writing agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                    "session_id": session.session_id,
                }
            )

        def _start_ad_hoc_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_ad_hoc_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start ad-hoc agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                    "session_id": session.session_id,
                }
            )

        def _restart_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, _started = state.restart_design_review_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not restart design review: {error}"},
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

        def _stop_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.stop_design_review_agent(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _complete_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.complete_design_review_agent(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _approve_design(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.approve_design(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _skip_design_approval(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.approve_design(context_id, skip_approval=True))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _send_design_message(self, query: str) -> None:
            self._send_agent_message(
                query,
                state.current_design_session,
                "design agent has not been started",
            )

        def _interrupt_design_agent(self, query: str) -> None:
            self._send_interrupt(query, state.interrupt_design_agent)

        def _interrupt_design_review_agent(self, query: str) -> None:
            self._send_interrupt(query, state.interrupt_design_review_agent)

        def _send_design_agent_events(self, query: str) -> None:
            self._send_session_events(
                query,
                state.current_design_session,
                "design agent has not been started",
            )

        def _send_design_review_agent_events(self, query: str) -> None:
            self._send_session_events(
                query,
                state.current_design_review_session,
                "design review has not been started",
            )

        def _send_progress_events(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                command_root = state.command_root(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_progress_events(context_id, command_root)

        def _send_progress_export(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                command_root = state.command_root(context_id)
                text, ok = _progress_snapshot(command_root)
            except StateError as error:
                self._send_text(
                    str(error),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_download(
                _progress_snapshot_markdown(command_root, text, ok),
                _progress_export_filename(),
            )

        def _send_document_export(self, query: str) -> None:
            params = parse_qs(query)
            artifact = str((params.get("artifact") or [""])[0]).strip()
            requested_path = str((params.get("path") or [""])[0])
            export_format = str((params.get("format") or ["markdown"])[0])
            try:
                context_id = self._context_id(query)
                project_root = Path(state.active_project_root(context_id)).resolve()
                if artifact == "document" and requested_path:
                    _ensure_document_target(project_root, requested_path)
                document_path = _artifact_event_document_path(
                    project_root,
                    artifact,
                    requested_path,
                )
                relative_path = document_path.relative_to(project_root).as_posix()
                exported = export_markdown_document(
                    document_path,
                    relative_path,
                    export_format,
                )
            except (
                AgentSessionError,
                DocumentExportError,
                OSError,
                StateError,
                ValueError,
            ) as error:
                self._send_text(
                    str(error),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_binary_download(
                exported.data,
                exported.filename,
                exported.content_type,
            )

        def _send_artifact_events(self, query: str) -> None:
            params = parse_qs(query)
            artifact = str((params.get("artifact") or [""])[0]).strip()
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                document_path = _artifact_event_document_path(
                    project_root,
                    artifact,
                    str((params.get("path") or [""])[0]),
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_artifact_events(artifact, document_path)

        def _resize_design_agent(self, query: str) -> None:
            self._send_resize(query, state.resize_design_agent)

        def _resize_design_review_agent(self, query: str) -> None:
            self._send_resize(query, state.resize_design_review_agent)

        def _send_interrupt(
            self,
            query: str,
            interrupt: Callable[[str], None],
        ) -> None:
            try:
                context_id = self._context_id(query)
                interrupt(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "interrupted"})

        def _send_agent_message(
            self,
            query: str,
            session_for_context: Callable[[str], AgentSession | None],
            missing_message: str,
        ) -> None:
            try:
                context_id = self._context_id(query)
                session = session_for_context(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": missing_message},
                    status=HTTPStatus.CONFLICT,
                )
                return
            try:
                payload = self._read_json_body()
            except ValueError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            message = str(payload.get("message") or "")
            if not message.strip():
                self._send_json(
                    {"error": "message is empty"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                session.send(message)
            except AgentSessionError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "sent"})

        def _send_session_events(
            self,
            query: str,
            session_for_context: Callable[[str], AgentSession | None],
            missing_message: str,
        ) -> None:
            try:
                context_id = self._context_id(query)
                session = session_for_context(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": missing_message},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_session_events(session)

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

        def _stream_progress_events(self, context_id: str, project_root: Path) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_snapshot = ""
            event_id = 1
            try:
                while True:
                    text, ok = _progress_snapshot(project_root)
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

        def _send_resize(
            self,
            query: str,
            resize: Callable[[str, int, int], None],
        ) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                columns = int(payload.get("columns") or 120)
                rows = int(payload.get("rows") or 32)
                resize(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _send_context_json(
            self,
            query: str,
            build_payload: Callable[[str], dict[str, object]],
        ) -> None:
            try:
                payload = build_payload(self._context_id(query))
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json(payload)

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
