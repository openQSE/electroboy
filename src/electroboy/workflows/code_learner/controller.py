"""Code Learner browser workflow controller."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from electroboy.models import utc_now
from electroboy.service.recent_projects import remember_recent_project
from electroboy.service.services import ServiceServices
from electroboy.service.sessions import AgentSession
from electroboy.service.workflow_controller import BoundWorkflowController
from electroboy.state_store import StateError

from .course_artifacts import render_saved_course
from .course_builder import CourseBuilder
from .course_graph import CourseGraph, CourseNavigator
from .course_projection import (
    phase2_analysis_payload,
    phase3_analysis_payload,
    project_navigation,
    project_phase3_navigation,
)
from .domain import (
    WORKFLOW_ID,
    CodeLearnerError,
    CodeLearnerStore,
    RepositoryAnalysis,
    SourceAdapter,
    Walkthrough,
    create_walkthrough,
    resolve_symbol,
)
from .function_knowledge import FunctionKnowledgeService
from .generation import LearnerGenerationStore, clear_phase3_cache
from .initialization import (
    InitializationLease,
    initialization_ready,
)
from .knowledge_store import KnowledgeStore
from .migration import LegacyCorpusMigrator
from .phase3_courses import Phase3CourseNavigator, Phase3CourseService
from .phase3_pipeline import Phase3InitializationPipeline, phase3_initialization_ready
from .phase3_store import Phase3Store
from .phase3_tutor import Phase3TutorContextStore
from .source_manifest import SourceManifestService
from .tutor_context import (
    TutorContextStore,
    require_repository_read_capability,
    tutor_bootstrap_prompt,
)

_INITIALIZATION_RUNNING_STATUSES = frozenset({"queued", "running"})
_AI_PROGRESS_MAX_PERCENT = 95
_VALIDATION_PERCENT = 97
_FORMALIZATION_PERCENT = 99


@dataclass
class _InitializationJob:
    """In-memory status for one Code Learner course initialization."""

    root: Path
    job_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "queued"
    phase: str = "queued"
    percent: int = 0
    message: str = "Queued AI course initialization."
    started_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    last_progress_at: str = ""
    error: str = ""
    progress_events: list[dict[str, object]] = field(default_factory=list)
    active_scope: list[str] = field(default_factory=list)
    record_counts: dict[str, int] = field(default_factory=dict)
    completed_analysis_jobs: int = 0
    remaining_analysis_jobs: int = 0
    completed_analysis_scopes: list[str] = field(default_factory=list)
    remaining_analysis_scopes: list[str] = field(default_factory=list)
    completed_module_courses: list[str] = field(default_factory=list)
    remaining_module_courses: list[str] = field(default_factory=list)
    resumed_from_checkpoint: bool = False
    completion_status: str = ""
    warning_count: int = 0
    failed_scope: str = ""
    recovery_action: str = ""
    started_monotonic: float = field(default_factory=time.monotonic)
    thread: threading.Thread | None = field(default=None, repr=False)
    lease: InitializationLease | None = field(default=None, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def is_running(self) -> bool:
        with self.lock:
            return self.status in _INITIALIZATION_RUNNING_STATUSES

    def update(
        self,
        *,
        status: str | None = None,
        phase: str | None = None,
        percent: int | None = None,
        message: str | None = None,
        error: str | None = None,
        progress: bool = False,
    ) -> None:
        with self.lock:
            if status is not None:
                self.status = status
            if phase is not None:
                self.phase = phase
            if percent is not None:
                self.percent = max(self.percent, _bounded_percent(percent))
            if message is not None:
                self.message = message
            if error is not None:
                self.error = error
            self.updated_at = utc_now()
            if progress:
                self.last_progress_at = self.updated_at

    def record_progress(self, record: dict[str, object]) -> None:
        if record.get("activity") is True:
            self._record_activity(record)
            return
        phase = str(record.get("phase") or self.phase or "running").strip()
        message = str(record.get("message") or phase).strip()
        reported_percent = _bounded_percent(record.get("percent"))
        host_owned = record.get("host_owned") is True
        percent = min(reported_percent, 99 if host_owned else _AI_PROGRESS_MAX_PERCENT)
        if reported_percent >= 100 and not host_owned:
            phase = "final_delivery"
            message = "Receiving final course corpus from AI."
        self._record_running_progress(phase, percent, message, details=record)

    def _record_activity(self, record: dict[str, object]) -> None:
        message = str(record.get("message") or "").strip()
        if not message:
            return
        with self.lock:
            scope_ids = record.get("scope_ids")
            self.updated_at = utc_now()
            self.last_progress_at = self.updated_at
            event = {
                "phase": str(record.get("phase") or self.phase or "running"),
                "percent": min(
                    _bounded_percent(record.get("percent")),
                    _AI_PROGRESS_MAX_PERCENT,
                ),
                "message": message,
                "updated_at": self.updated_at,
                "scope_ids": [
                    str(item)
                    for item in (scope_ids if isinstance(scope_ids, list) else [])
                ],
                "activity": True,
                "activity_kind": str(record.get("activity_kind") or "runtime"),
                "heartbeat": False,
            }
            if self.progress_events and all(
                self.progress_events[-1].get(key) == event.get(key)
                for key in ("message", "scope_ids", "activity_kind")
            ):
                return
            self.progress_events.append(event)
            self.progress_events = self.progress_events[-250:]

    def record_system_progress(
        self,
        *,
        phase: str,
        percent: int,
        message: str,
    ) -> None:
        self._record_running_progress(
            phase,
            min(_bounded_percent(percent), 99),
            message,
        )

    def _record_running_progress(
        self,
        phase: str,
        percent: int,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        self.update(
            status="running",
            phase=phase or "running",
            percent=percent,
            message=message or "Initializing AI course material.",
            progress=True,
        )
        with self.lock:
            details = details or {}
            if "scope_ids" in details:
                self.active_scope = [str(item) for item in details.get("scope_ids", [])]
            counts = details.get("counts", details.get("record_counts"))
            if isinstance(counts, dict):
                self.record_counts = {
                    str(key): int(value) for key, value in counts.items()
                }
            if "completed_analysis_jobs" in details:
                self.completed_analysis_jobs = int(
                    details.get("completed_analysis_jobs") or 0
                )
            if "remaining_analysis_jobs" in details:
                self.remaining_analysis_jobs = int(
                    details.get("remaining_analysis_jobs") or 0
                )
            if "completed_analysis_scopes" in details:
                self.completed_analysis_scopes = [
                    str(item) for item in details.get("completed_analysis_scopes", [])
                ]
            if "remaining_analysis_scopes" in details:
                self.remaining_analysis_scopes = [
                    str(item) for item in details.get("remaining_analysis_scopes", [])
                ]
            if "completed_module_courses" in details:
                self.completed_module_courses = [
                    str(item) for item in details.get("completed_module_courses", [])
                ]
            if "remaining_module_courses" in details:
                self.remaining_module_courses = [
                    str(item) for item in details.get("remaining_module_courses", [])
                ]
            if details.get("heartbeat"):
                return
            event = {
                "phase": phase or "running",
                "percent": percent,
                "message": message or "Initializing AI course material.",
                "updated_at": self.updated_at,
                "scope_ids": list(self.active_scope),
                "record_counts": dict(self.record_counts),
                "completed_analysis_jobs": self.completed_analysis_jobs,
                "remaining_analysis_jobs": self.remaining_analysis_jobs,
                "completed_analysis_scopes": list(self.completed_analysis_scopes),
                "remaining_analysis_scopes": list(self.remaining_analysis_scopes),
                "completed_module_courses": list(self.completed_module_courses),
                "remaining_module_courses": list(self.remaining_module_courses),
                "heartbeat": bool(details.get("heartbeat")),
            }
            if self.progress_events and self.progress_events[-1] == event:
                return
            self.progress_events.append(event)
            self.progress_events = self.progress_events[-250:]

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            elapsed = max(0, int(time.monotonic() - self.started_monotonic))
            percent = _bounded_percent(self.percent)
            remaining = _estimated_remaining_seconds(elapsed, percent)
            return {
                "job_id": self.job_id,
                "status": self.status,
                "phase": self.phase,
                "percent": percent,
                "message": self.message,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
                "last_progress_at": self.last_progress_at,
                "elapsed_seconds": elapsed,
                "estimated_remaining_seconds": remaining,
                "error": self.error,
                "progress_events": [dict(event) for event in self.progress_events],
                "active_scope": list(self.active_scope),
                "record_counts": dict(self.record_counts),
                "completed_analysis_jobs": self.completed_analysis_jobs,
                "remaining_analysis_jobs": self.remaining_analysis_jobs,
                "completed_analysis_scopes": list(self.completed_analysis_scopes),
                "remaining_analysis_scopes": list(self.remaining_analysis_scopes),
                "completed_module_courses": list(self.completed_module_courses),
                "remaining_module_courses": list(self.remaining_module_courses),
                "resumed_from_checkpoint": self.resumed_from_checkpoint,
                "completion_status": self.completion_status,
                "warning_count": self.warning_count,
                "failed_scope": self.failed_scope,
                "recovery_action": self.recovery_action,
                "checkpoint_path": str(Phase3Store(self.root).checkpoint_path),
                "progress_path": str(Phase3Store(self.root).progress_path),
            }


def _bounded_percent(value: object) -> int:
    try:
        percent = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, percent))


def _estimated_remaining_seconds(elapsed: int, percent: int) -> int | None:
    if percent <= 0 or percent >= _AI_PROGRESS_MAX_PERCENT:
        return None
    return max(0, int(elapsed * ((100 - percent) / percent)))


def _idle_initialization_snapshot(root: Path) -> dict[str, object]:
    return {
        "job_id": "",
        "status": "idle",
        "phase": "idle",
        "percent": 0,
        "message": "Initialize Code Learner to generate AI course material.",
        "started_at": "",
        "updated_at": "",
        "last_progress_at": "",
        "elapsed_seconds": 0,
        "estimated_remaining_seconds": None,
        "error": "",
        "progress_events": [],
        "active_scope": [],
        "record_counts": {},
        "completed_analysis_jobs": 0,
        "remaining_analysis_jobs": 0,
        "completed_analysis_scopes": [],
        "remaining_analysis_scopes": [],
        "completed_module_courses": [],
        "remaining_module_courses": [],
        "resumed_from_checkpoint": False,
        "completion_status": "",
        "warning_count": 0,
        "failed_scope": "",
        "recovery_action": "",
        "checkpoint_path": str(Phase3Store(root).checkpoint_path),
        "progress_path": str(Phase3Store(root).progress_path),
    }


def _completed_initialization_snapshot(root: Path) -> dict[str, object]:
    terminal = Phase3Store(root).load_terminal_result() or {}
    completion_status = str(terminal.get("status") or "complete")
    warning_count = int(terminal.get("warning_count") or 0)
    return {
        "job_id": "",
        "status": "initialized",
        "phase": "complete",
        "percent": 100,
        "message": (
            "AI course material is ready with warnings."
            if completion_status == "complete_with_warnings"
            else "AI course material is ready."
        ),
        "started_at": "",
        "updated_at": utc_now(),
        "last_progress_at": "",
        "elapsed_seconds": 0,
        "estimated_remaining_seconds": None,
        "error": "",
        "progress_events": [],
        "active_scope": [],
        "record_counts": {},
        "completed_analysis_jobs": 0,
        "remaining_analysis_jobs": 0,
        "completed_analysis_scopes": [],
        "remaining_analysis_scopes": [],
        "completed_module_courses": [],
        "remaining_module_courses": [],
        "resumed_from_checkpoint": False,
        "completion_status": completion_status,
        "warning_count": warning_count,
        "failed_scope": str(terminal.get("failed_scope") or ""),
        "recovery_action": str(terminal.get("recovery_action") or ""),
        "checkpoint_path": str(Phase3Store(root).checkpoint_path),
        "progress_path": str(Phase3Store(root).progress_path),
    }


def _existing_project_root(path: str) -> Path:
    project_root = Path(path).expanduser().resolve()
    if not project_root.exists():
        raise StateError(f"project path does not exist: {project_root}")
    if not project_root.is_dir():
        raise StateError(f"project path is not a directory: {project_root}")
    return project_root


def _walkthrough_summary(walkthrough: Walkthrough) -> dict[str, object]:
    return {
        "id": walkthrough.id,
        "title": walkthrough.title,
        "learning_mode": walkthrough.learning_mode,
        "mode_target": walkthrough.mode_target,
        "current_step_id": walkthrough.current_step_id,
        "generated_at": walkthrough.generated_at,
        "source_revision": walkthrough.source_revision,
        "review_status": walkthrough.review_status,
        "step_count": len(walkthrough.steps),
        "qa_count": len(walkthrough.qa_history),
    }


def _walkthrough_source_payload(
    root: Path,
    walkthrough: Walkthrough | None,
) -> dict[str, object] | None:
    if walkthrough is None:
        return None
    step = walkthrough.current_step()
    if step is None:
        return None
    reference = step.primary_reference
    return SourceAdapter(root).source_payload(
        reference.file_path,
        start_line=reference.start_line,
        end_line=reference.end_line,
    )


def _empty_analysis(root: Path) -> RepositoryAnalysis:
    return RepositoryAnalysis(
        source_root=str(root),
        source_files=(),
        language_counts={},
        modules=(),
        symbols=(),
        truncated=False,
    )


def _code_learner_agent_prompt(
    root: Path,
    _context: dict[str, object] | None = None,
) -> str:
    selected = LearnerGenerationStore(root).load()
    generation = selected.generation if selected is not None else "phase2"
    return tutor_bootstrap_prompt(root, generation=generation)


def code_learner_agent_command(
    root: Path,
    _context: dict[str, object] | None = None,
) -> list[str]:
    command = [
        "codex",
        "--cd",
        str(root),
        "--sandbox",
        "read-only",
        _code_learner_agent_prompt(root),
    ]
    require_repository_read_capability(command, root)
    return command


class CodeLearnerWorkflowController(BoundWorkflowController):
    """Own Code Learner source walkthroughs and tutor sessions."""

    workflow_id = WORKFLOW_ID

    def __init__(self, services: ServiceServices) -> None:
        super().__init__(services)
        self._initialization_lock = threading.RLock()
        self._initialization_jobs: dict[str, _InitializationJob] = {}

    def _reserve_project_workspace(
        self,
        context_id: str,
        project_root: Path,
    ) -> tuple[str, bool]:
        with self.services.contexts.lock:
            current = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(current)
        workspace, resumed = self.services.workspaces.reserve_project(
            context_id,
            workflow_id=self.workflow_id,
            project_kind="code-learner",
            project_identity=str(project_root),
            name=project_root.name,
        )
        return workspace.context_id, resumed

    def open_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _existing_project_root(path)
        context_id, resumed = self._reserve_project_workspace(
            context_id,
            project_root,
        )
        if resumed:
            return {
                **self.services.contexts.project_payload(context_id),
                "status": "resumed",
            }
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="code-learner",
                activation_root=project_root,
                active_project_root=project_root,
                workflow_stage="project",
            )
            self.services.workspaces.persist(context_id)
        remember_recent_project(
            self.services.files.state_root,
            project_root,
            "code-learner",
        )
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "opened",
        }

    def project_payload_extension(self, context_id: str) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            root = context.active_project_root
        if root is None:
            return {
                "code_learner": {
                    "state_path": "",
                    "walkthroughs": [],
                    "current_walkthrough_id": "",
                    "current_walkthrough": None,
                    "source": None,
                }
            }
        return {"code_learner": self._state_payload(root)}

    def initialize(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if phase3_initialization_ready(root):
            return self._initialization_payload(context_id, root)
        with self._initialization_lock:
            job = self._initialization_jobs.get(str(root))
            if job is None or not job.is_running():
                job = _InitializationJob(
                    root=root,
                    resumed_from_checkpoint=(
                        Phase3Store(root).checkpoint_path.is_file()
                    ),
                )
                source = SourceManifestService(root).load()
                job.lease = InitializationLease.acquire(
                    root,
                    job.job_id,
                    repository_revision=source.revision if source else "",
                )
                thread = threading.Thread(
                    target=self._run_initialization_job,
                    args=(context_id, root, job),
                    name=f"code-learner-init-{job.job_id[:8]}",
                    daemon=True,
                )
                job.thread = thread
                self._initialization_jobs[str(root)] = job
                thread.start()
        return self._initialization_payload(context_id, root)

    def initialization_status(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        return self._initialization_payload(context_id, root)

    def clear_course_cache(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if any(
                session.is_active()
                for session in context.code_learner_sessions.values()
            ):
                raise CodeLearnerError(
                    "stop the Code Learner tutor before clearing the course cache"
                )
        with self._initialization_lock:
            job = self._initialization_jobs.get(str(root))
            if job is not None and job.is_running():
                raise CodeLearnerError(
                    "wait for Code Learner initialization before clearing the cache"
                )
            lease = InitializationLease.acquire(
                root,
                f"clear-course-cache-{uuid4().hex}",
            )
            try:
                phase3_cleared = clear_phase3_cache(root)
                phase2_cleared = KnowledgeStore(root).clear_course_cache()
                legacy_cleared = CodeLearnerStore(root).clear_course_cache()
                cleared = {
                    "removed_file_count": (
                        phase3_cleared["removed_file_count"]
                        + phase2_cleared["removed_file_count"]
                        + legacy_cleared["removed_file_count"]
                    ),
                    "removed_bytes": (
                        phase3_cleared["removed_bytes"]
                        + phase2_cleared["removed_bytes"]
                        + legacy_cleared["removed_bytes"]
                    ),
                }
            finally:
                lease.release()
            self._initialization_jobs.pop(str(root), None)
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "cache_cleared",
            "cache": cleared,
            "initialization": _idle_initialization_snapshot(root),
            "code_learner": self._state_payload(root),
        }

    def wait_for_initialization(
        self,
        context_id: str,
        timeout: float | None = None,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        job = self._initialization_job(root)
        if job is not None and job.thread is not None:
            job.thread.join(timeout=timeout)
        return self._initialization_payload(context_id, root)

    def initialize_from_jsonl(
        self,
        context_id: str,
        corpus_jsonl: str,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        return self._initialize_from_corpus_jsonl(context_id, root, corpus_jsonl)

    def _initialize_from_corpus_jsonl(
        self,
        context_id: str,
        root: Path,
        corpus_jsonl: str,
    ) -> dict[str, object]:
        LearnerGenerationStore(root).select(
            "phase2",
            "legacy-jsonl-import",
        )
        self._save_initialized_corpus(root, corpus_jsonl)
        state = self._state_payload(root)
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "initialized",
            "initialization": _completed_initialization_snapshot(root),
            "code_learner": state,
        }

    def _save_initialized_corpus(
        self,
        root: Path,
        corpus_jsonl: str,
        *,
        job: _InitializationJob | None = None,
    ) -> None:
        store = CodeLearnerStore(root)
        if job is not None:
            job.record_system_progress(
                phase="validation",
                percent=_VALIDATION_PERCENT,
                message="Validating and saving AI course corpus.",
            )
        store.save_corpus_jsonl(corpus_jsonl)
        if job is not None:
            job.record_system_progress(
                phase="formalizing",
                percent=_FORMALIZATION_PERCENT,
                message="Building the initial architecture lesson.",
            )
        architecture = create_walkthrough(root, learning_mode="architecture")
        store.save_walkthrough(architecture)

    def _run_initialization_job(
        self,
        context_id: str,
        root: Path,
        job: _InitializationJob,
    ) -> None:
        job.record_system_progress(
            phase="setup",
            percent=1,
            message=(
                "Resuming AI course initialization from cached findings."
                if job.resumed_from_checkpoint
                else "Starting AI course initialization with durable checkpointing."
            ),
        )
        try:
            result = Phase3InitializationPipeline(root).run(
                lambda record: self._record_initialization_progress(job, record),
                acquire_lease=False,
            )
            navigation = Phase3CourseNavigator(root).open(
                "architecture", "architecture:current"
            )
            Phase3TutorContextStore(root).write_navigation(
                navigation,
                project_id=context_id,
                writer_id=f"electroboy:{context_id}",
            )
            terminal = Phase3Store(root).load_terminal_result() or {}
            job.completion_status = str(terminal.get("status") or result.status)
            job.warning_count = int(terminal.get("warning_count") or 0)
            job.failed_scope = str(terminal.get("failed_scope") or "")
            job.recovery_action = str(terminal.get("recovery_action") or "")
            job.update(
                status="initialized",
                phase="complete",
                percent=100,
                message=(
                    "AI course material is ready with warnings."
                    if job.completion_status == "complete_with_warnings"
                    else "AI course material is ready."
                ),
            )
        except Exception as error:
            message = str(error)
            terminal = Phase3Store(root).load_terminal_result() or {}
            job.completion_status = str(terminal.get("status") or "failed")
            job.warning_count = int(terminal.get("warning_count") or 0)
            job.failed_scope = str(
                terminal.get("failed_scope") or job.phase or "initialization"
            )
            job.recovery_action = str(
                terminal.get("recovery_action")
                or "Resume initialization after correcting the reported failure."
            )
            job.update(
                status="failed",
                phase="failed",
                message=message,
                error=message,
            )
        finally:
            if job.lease is not None:
                job.lease.release()
                job.lease = None

    def _record_initialization_progress(
        self,
        job: _InitializationJob,
        record: dict[str, object],
    ) -> None:
        job.record_progress(record)

    def _initialization_job(self, root: Path) -> _InitializationJob | None:
        with self._initialization_lock:
            return self._initialization_jobs.get(str(root))

    def _initialization_payload(
        self,
        context_id: str,
        root: Path,
    ) -> dict[str, object]:
        job = self._initialization_job(root)
        state = self._state_payload(root)
        initialized = phase3_initialization_ready(root)
        if job is not None and job.is_running():
            status = "initializing"
            initialization = job.snapshot()
        elif job is not None and str(job.snapshot().get("status")) == "failed":
            status = "failed"
            initialization = job.snapshot()
        elif job is not None and str(job.snapshot().get("status")) == "initialized":
            status = "initialized"
            initialization = job.snapshot()
        elif initialized:
            status = "initialized"
            initialization = (
                job.snapshot()
                if job is not None
                else _completed_initialization_snapshot(root)
            )
        else:
            status = "uninitialized"
            terminal = Phase3Store(root).load_terminal_result()
            if terminal and terminal.get("status") == "failed":
                status = "failed"
                initialization = {
                    **_idle_initialization_snapshot(root),
                    "status": "failed",
                    "phase": str(terminal.get("failed_scope") or "failed"),
                    "message": str(terminal.get("recovery_action") or "failed"),
                    "error": str(terminal.get("recovery_action") or "failed"),
                    "completion_status": "failed",
                    "warning_count": int(terminal.get("warning_count") or 0),
                    "failed_scope": str(terminal.get("failed_scope") or ""),
                    "recovery_action": str(terminal.get("recovery_action") or ""),
                }
            else:
                initialization = _idle_initialization_snapshot(root)
        return {
            **self.services.contexts.project_payload(context_id),
            "status": status,
            "initialization": initialization,
            "code_learner": state,
        }

    def analysis(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            return {
                "status": "analyzed"
                if phase3_initialization_ready(root)
                else "uninitialized",
                "analysis": phase3_analysis_payload(root),
            }
        if KnowledgeStore(root).load_knowledge(validate_sources=False):
            return {
                "status": "analyzed",
                "analysis": phase2_analysis_payload(root),
            }
        analysis = CodeLearnerStore(root).corpus_analysis()
        return {
            "status": "analyzed" if analysis is not None else "uninitialized",
            "analysis": (analysis or _empty_analysis(root)).to_dict(),
        }

    def source_file(
        self,
        context_id: str,
        path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        padding: int = 80,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        return {
            "status": "loaded",
            "source": SourceAdapter(root).source_payload(
                path,
                start_line=start_line,
                end_line=end_line,
                padding=padding,
            ),
        }

    def course_artifact(
        self, context_id: str, mode: str, scope_id: str
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            service = Phase3CourseService(root)
            records = service.load(mode, scope_id)
            if not records:
                raise CodeLearnerError("Phase 3 course artifact is missing")
            return {
                "status": "rendered",
                "artifact": "course",
                "jsonl_path": service.course_path(mode, scope_id)
                .relative_to(root)
                .as_posix(),
                "markdown_path": service.markdown_path(mode, scope_id)
                .relative_to(root)
                .as_posix(),
                "record_count": len(records),
            }
        result = render_saved_course(root, mode, scope_id)
        return {
            "status": "rendered",
            "artifact": result.artifact,
            "jsonl_path": result.jsonl_path,
            "markdown_path": result.markdown_path,
            "record_count": result.record_count,
        }

    def course_graph(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            return {
                "status": "loaded",
                "graph": {
                    "generation": "phase3",
                    "targets": Phase3CourseService(root).index().get("targets", {}),
                },
            }
        return {
            "status": "loaded",
            "graph": CourseGraph.from_store(KnowledgeStore(root)).to_dict(),
        }

    def resolve_function_course(self, context_id: str, query: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            service = FunctionKnowledgeService(root)
            resolution = service.resolve(query)
            payload = resolution.to_dict()
            symbol = resolution.symbol
            if symbol:
                key = str(symbol.get("canonical_key") or "")
                payload["course_status"] = Phase3CourseService(root).target_status(
                    f"course:function:{key}"
                )
            else:
                payload["course_status"] = "missing"
            payload["candidates"] = [
                _phase3_symbol_payload(root, item) for item in resolution.candidates
            ]
            payload["symbol"] = (
                _phase3_symbol_payload(root, symbol) if symbol is not None else None
            )
            return payload
        resolution = CourseBuilder(root).resolve_function(query)
        payload = resolution.to_dict()
        symbol = resolution.symbol
        if symbol:
            symbol_id = str(symbol.get("id") or "")
            index = KnowledgeStore(root).load_course_index().get("courses", {})
            course = (
                index.get(f"function:{symbol_id}", {})
                if isinstance(index, dict)
                else {}
            )
            payload["course_status"] = (
                course.get("status", "missing")
                if isinstance(course, dict)
                else "missing"
            )
        else:
            payload["course_status"] = "missing"
        return payload

    def build_function_course(
        self, context_id: str, query: str, audience: str = ""
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            if not phase3_initialization_ready(root):
                raise CodeLearnerError(
                    "initialize Phase 3 before generating a function"
                )
            knowledge = FunctionKnowledgeService(root)
            resolution = knowledge.resolve(query)
            if resolution.symbol is None or resolution.status == "ambiguous":
                raise CodeLearnerError(f"function target is {resolution.status}")
            canonical_key = str(resolution.symbol["canonical_key"])
            checkpoint = (
                Phase3Store(root).read_json(Phase3Store(root).checkpoint_path) or {}
            )
            run_id = str(checkpoint.get("analysis_run_id") or uuid4().hex)
            knowledge.generate(canonical_key, analysis_run_id=run_id)
            courses = Phase3CourseService(root)
            document_id = f"course:function:{canonical_key}"
            if courses.target_status(document_id) != "ready":
                courses.build(
                    "function",
                    canonical_key,
                    analysis_run_id=run_id,
                    audience=audience or "software engineer",
                )
            records = courses.load("function", canonical_key)
            return {
                "status": "ready",
                "course": {
                    "mode": "function",
                    "scope_id": canonical_key,
                    "jsonl_path": courses.course_path("function", canonical_key)
                    .relative_to(root)
                    .as_posix(),
                    "markdown_path": courses.markdown_path("function", canonical_key)
                    .relative_to(root)
                    .as_posix(),
                    "record_count": len(records),
                },
            }
        result = CourseBuilder(root).build_function(query, audience=audience)
        return {
            "status": "ready",
            "course": {
                "mode": result.mode,
                "scope_id": result.scope_id,
                "jsonl_path": result.jsonl_path,
                "markdown_path": result.markdown_path,
                "record_count": result.record_count,
            },
        }

    def navigate_course(
        self,
        context_id: str,
        action: str,
        *,
        course_id: str = "",
        section_id: str = "",
        target_id: str = "",
        code_view: dict[str, object] | None = None,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            navigator = Phase3CourseNavigator(root)
            if action == "open":
                mode, scope_id = _phase3_course_identity(course_id)
                result = navigator.open(mode, scope_id, section_id)
            elif action in {"previous", "next"}:
                result = navigator.move(action)
            elif action == "deep-dive":
                result = navigator.deep_dive(target_id)
            elif action == "back":
                result = navigator.back()
            elif action == "code-view":
                result = navigator.update_code_view(code_view or {})
            elif action == "state":
                result = navigator.state()
            else:
                raise CodeLearnerError(f"unknown course navigation action: {action}")
            if result.get("current"):
                result["tutor_context"] = Phase3TutorContextStore(
                    root
                ).write_navigation(
                    result,
                    project_id=context_id,
                    writer_id=f"electroboy:{context_id}",
                )
                return project_phase3_navigation(root, result)
            return result
        navigator = CourseNavigator(root)
        if action == "open":
            result = navigator.open(course_id, section_id)
        elif action in {"previous", "next"}:
            result = navigator.move(action)
        elif action == "deep-dive":
            result = navigator.deep_dive(target_id)
        elif action == "back":
            result = navigator.back()
        elif action == "code-view":
            result = navigator.update_code_view(code_view or {})
        elif action == "state":
            result = navigator.state()
        else:
            raise CodeLearnerError(f"unknown course navigation action: {action}")
        if result.get("current"):
            result["tutor_context"] = TutorContextStore(root).write_navigation(
                result,
                project_id=context_id,
                writer_id=f"electroboy:{context_id}",
            )
            return project_navigation(root, result)
        return result

    def modules(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            analysis = phase3_analysis_payload(root)
            return {
                "status": "listed",
                "modules": analysis["modules"],
                "truncated": False,
            }
        if KnowledgeStore(root).load_knowledge(validate_sources=False):
            analysis = phase2_analysis_payload(root)
            return {
                "status": "listed",
                "modules": analysis["modules"],
                "truncated": False,
            }
        analysis = CodeLearnerStore(root).corpus_analysis() or _empty_analysis(root)
        return {
            "status": "listed",
            "modules": list(analysis.to_dict()["modules"]),
            "truncated": analysis.truncated,
        }

    def symbols(self, context_id: str, query: str = "") -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            analysis = phase3_analysis_payload(root)
            symbols = list(analysis["symbols"])
            requested = query.strip().lower()
            if requested:
                symbols = [
                    symbol
                    for symbol in symbols
                    if requested in str(symbol.get("qualified_name") or "").lower()
                    or requested in str(symbol.get("name") or "").lower()
                ]
            return {
                "status": "listed",
                "symbols": symbols[:80],
                "truncated": len(symbols) > 80,
                "resolution": (
                    self.resolve_function_course(context_id, query)
                    if requested
                    else None
                ),
            }
        if KnowledgeStore(root).load_knowledge(validate_sources=False):
            analysis = phase2_analysis_payload(root)
            symbols = list(analysis["symbols"])
            requested = query.strip().lower()
            if requested:
                symbols = [
                    symbol
                    for symbol in symbols
                    if requested in str(symbol.get("qualified_name") or "").lower()
                    or requested in str(symbol.get("name") or "").lower()
                ]
            return {
                "status": "listed",
                "symbols": symbols[:80],
                "truncated": len(symbols) > 80,
                "resolution": (
                    CourseBuilder(root).resolve_function(query).to_dict()
                    if requested
                    else None
                ),
            }
        analysis = CodeLearnerStore(root).corpus_analysis() or _empty_analysis(root)
        symbols = list(analysis.symbols)
        requested = query.strip().lower()
        if requested:
            symbols = [
                symbol
                for symbol in symbols
                if requested in symbol.qualified_name.lower()
                or requested in symbol.name.lower()
            ]
        return {
            "status": "listed",
            "symbols": [symbol.to_dict() for symbol in symbols[:80]],
            "truncated": len(symbols) > 80 or analysis.truncated,
            "resolution": resolve_symbol(analysis, query).to_dict()
            if query.strip()
            else None,
        }

    def create_walkthrough(
        self,
        context_id: str,
        *,
        learning_mode: str,
        target: str = "",
        intended_audience: str = "",
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if _phase3_selected(root):
            if not phase3_initialization_ready(root):
                raise CodeLearnerError("initialize Phase 3 before opening a course")
            mode = str(learning_mode or "").strip().lower()
            scope_id = target
            if mode == "architecture":
                scope_id = "architecture:current"
            elif mode == "module":
                if not scope_id:
                    raise CodeLearnerError("Module target is required")
            elif mode == "function":
                result = self.build_function_course(
                    context_id, target, intended_audience
                )
                scope_id = str(result["course"]["scope_id"])
            else:
                raise CodeLearnerError(f"unknown course mode: {learning_mode}")
            return self.navigate_course(
                context_id,
                "open",
                course_id=f"course:{mode}:{scope_id}",
            )
        store = KnowledgeStore(root)
        if store.load_knowledge(validate_sources=False):
            mode = str(learning_mode or "").strip().lower()
            if mode == "architecture":
                course_id = "course.architecture.repository.root"
            elif mode == "module":
                if not target:
                    raise CodeLearnerError("Module target is required")
                course_id = f"course.module.{target}"
            elif mode == "function":
                result = CourseBuilder(root).build_function(
                    target,
                    audience=intended_audience,
                )
                course_id = f"course.function.{result.scope_id}"
            else:
                raise CodeLearnerError(f"unknown course mode: {learning_mode}")
            return self.navigate_course(
                context_id,
                "open",
                course_id=course_id,
            )
        walkthrough = create_walkthrough(
            root,
            learning_mode=learning_mode,
            target=target,
            intended_audience=intended_audience,
        )
        saved = CodeLearnerStore(root).save_walkthrough(walkthrough)
        TutorContextStore(root).write_walkthrough(
            saved,
            project_id=context_id,
            writer_id=f"electroboy:{context_id}",
        )
        return self._walkthrough_payload(root, saved)

    def set_current_step(
        self,
        context_id: str,
        walkthrough_id: str,
        step_id: str,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if walkthrough_id.startswith("course:"):
            return self.navigate_course(
                context_id,
                "open",
                course_id=walkthrough_id,
                section_id=step_id,
            )
        if walkthrough_id.startswith("course."):
            return self.navigate_course(
                context_id,
                "open",
                course_id=walkthrough_id,
                section_id=step_id,
            )
        walkthrough = CodeLearnerStore(root).set_current_step(
            walkthrough_id,
            step_id,
        )
        TutorContextStore(root).write_walkthrough(
            walkthrough,
            project_id=context_id,
            writer_id=f"electroboy:{context_id}",
        )
        return self._walkthrough_payload(root, walkthrough)

    def learner_context(
        self,
        context_id: str,
        walkthrough_id: str = "",
        **context_options: object,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if walkthrough_id.startswith("course:"):
            navigation = Phase3CourseNavigator(root).update_code_view(
                _phase3_code_view_from_options(root, context_options)
            )
            context = Phase3TutorContextStore(root).write_navigation(
                navigation,
                project_id=context_id,
                writer_id=f"electroboy:{context_id}",
            )
            return {"status": "prepared", "context": context}
        if walkthrough_id.startswith("course."):
            navigation = CourseNavigator(root).update_code_view(
                _code_view_from_options(root, context_options)
            )
            context = TutorContextStore(root).write_navigation(
                navigation,
                project_id=context_id,
                writer_id=f"electroboy:{context_id}",
            )
            return {"status": "prepared", "context": context}
        walkthrough = CodeLearnerStore(root).get(walkthrough_id)
        context = TutorContextStore(root).write_walkthrough(
            walkthrough,
            project_id=context_id,
            writer_id=f"electroboy:{context_id}",
            context_options=context_options,
        )
        return {
            "status": "prepared",
            "context": context,
        }

    def prepare_question(
        self,
        context_id: str,
        question: str,
        walkthrough_id: str = "",
        **context_options: object,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        store = CodeLearnerStore(root)
        question = str(question or "").strip()
        if not question:
            raise CodeLearnerError("learner question is required")
        if walkthrough_id.startswith("course:"):
            context = self.learner_context(
                context_id,
                walkthrough_id,
                **context_options,
            )["context"]
            return {
                **project_phase3_navigation(root, Phase3CourseNavigator(root).state()),
                "status": "prepared",
                "question": question,
                "prompt": question,
                "context_version": context["context_version"],
                "context_path": (".electroboy/code-learner/phase3/tutor-context.json"),
            }
        if walkthrough_id.startswith("course."):
            context = self.learner_context(
                context_id,
                walkthrough_id,
                **context_options,
            )["context"]
            return {
                **project_navigation(root, CourseNavigator(root).state()),
                "status": "prepared",
                "question": question,
                "prompt": question,
                "context_version": context["context_version"],
                "context_path": ".electroboy/code-learner/tutor-context.json",
            }
        walkthrough = store.get(walkthrough_id)
        context = TutorContextStore(root).write_walkthrough(
            walkthrough,
            project_id=context_id,
            writer_id=f"electroboy:{context_id}",
            context_options=context_options,
        )
        return {
            "status": "prepared",
            "question": question,
            "prompt": question,
            "context_version": context["context_version"],
            "context_path": ".electroboy/code-learner/tutor-context.json",
            "walkthrough": walkthrough.to_dict(),
            "walkthroughs": self._walkthrough_summaries(root),
        }

    def start_agent(
        self,
        context_id: str,
        walkthrough_id: str = "",
        **context_options: object,
    ) -> tuple[AgentSession, bool]:
        root = self._active_project_root(context_id)
        store = CodeLearnerStore(root)
        tutor_context = TutorContextStore(root)
        phase3 = walkthrough_id.startswith("course:")
        if phase3:
            navigation = Phase3CourseNavigator(root).update_code_view(
                _phase3_code_view_from_options(root, context_options)
            )
            compact_context = Phase3TutorContextStore(root).write_navigation(
                navigation,
                project_id=context_id,
                writer_id=f"electroboy:{context_id}",
            )
            course = compact_context["course"]
            learning_mode = str(course["mode"])
            mode_target = str(course["scope_id"])
        elif walkthrough_id.startswith("course."):
            navigation = CourseNavigator(root).update_code_view(
                _code_view_from_options(root, context_options)
            )
            compact_context = tutor_context.write_navigation(
                navigation,
                project_id=context_id,
                writer_id=f"electroboy:{context_id}",
            )
            course = compact_context["course"]
            learning_mode = str(course["mode"])
            mode_target = str(course["scope_id"])
        else:
            walkthrough = store.get(walkthrough_id)
            tutor_context.write_walkthrough(
                walkthrough,
                project_id=context_id,
                writer_id=f"electroboy:{context_id}",
                context_options=context_options,
            )
            learning_mode = walkthrough.learning_mode
            mode_target = walkthrough.mode_target
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            for session in context.code_learner_sessions.values():
                if session.is_active():
                    context.selected_session_id = session.session_id
                    return session, False
            session = AgentSession(
                command=code_learner_agent_command(root),
                cwd=root,
                label="code learner tutor",
                kind=self.workflow_id,
                interactive=True,
                metadata={
                    "walkthrough_id": walkthrough_id,
                    "learning_mode": learning_mode,
                    "mode_target": mode_target,
                    "tutor_context_path": (
                        ".electroboy/code-learner/phase3/tutor-context.json"
                        if phase3
                        else ".electroboy/code-learner/tutor-context.json"
                    ),
                },
            )
            session = self.services.sessions.prepare(context, session)
            context.code_learner_sessions[session.session_id] = session
            context.selected_session_id = session.session_id
            self.services.sessions.record(context, session)
        if phase3:
            Phase3TutorContextStore(root).write_navigation(
                Phase3CourseNavigator(root).state(),
                project_id=context_id,
                writer_id=session.session_id,
            )
        elif walkthrough_id.startswith("course."):
            tutor_context.write_navigation(
                CourseNavigator(root).state(),
                project_id=context_id,
                writer_id=session.session_id,
            )
        else:
            tutor_context.write_walkthrough(
                walkthrough,
                project_id=context_id,
                writer_id=session.session_id,
                context_options=context_options,
            )
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                try:
                    context = self.services.contexts.require(context_id)
                except StateError:
                    raise
                self.services.sessions.clear(context, [session])
            raise
        return session, True

    def prompt_for_question(
        self,
        context_id: str,
        question: str,
        walkthrough_id: str = "",
        **context_options: object,
    ) -> str:
        self.prepare_question(
            context_id,
            question,
            walkthrough_id,
            **context_options,
        )
        return str(question or "").strip() + "\n"

    def _walkthrough_payload(
        self,
        root: Path,
        walkthrough: Walkthrough,
    ) -> dict[str, object]:
        return {
            "status": "ready",
            "walkthrough": walkthrough.to_dict(),
            "walkthroughs": self._walkthrough_summaries(root),
            "source": _walkthrough_source_payload(root, walkthrough),
        }

    def _state_payload(self, root: Path) -> dict[str, object]:
        store = CodeLearnerStore(root)
        walkthroughs = store.walkthroughs()
        current = store.current()
        payload: dict[str, object] = {
            "state_path": str(store.path),
            "walkthroughs": [
                _walkthrough_summary(walkthrough) for walkthrough in walkthroughs
            ],
            "current_walkthrough_id": current.id if current else "",
            "current_walkthrough": current.to_dict() if current else None,
        }
        phase3_store = Phase3Store(root)
        if _phase3_state_present(root):
            terminal = phase3_store.load_terminal_result()
            ready = phase3_initialization_ready(root)
            payload.update(
                {
                    "learner_generation": "phase3",
                    "phase3_initialized": ready,
                    "phase2_initialized": False,
                    "completion_status": (
                        str(terminal.get("status") or "") if terminal else ""
                    ),
                    "warning_count": (
                        int(terminal.get("warning_count") or 0) if terminal else 0
                    ),
                    "failed_scope": (
                        str(terminal.get("failed_scope") or "") if terminal else ""
                    ),
                    "recovery_action": (
                        str(terminal.get("recovery_action") or "") if terminal else ""
                    ),
                    "walkthroughs": [],
                    "current_walkthrough_id": "",
                    "current_walkthrough": None,
                    "source": None,
                    "analysis": phase3_analysis_payload(root) if ready else None,
                    "phase3": _phase3_manifest_status(root),
                }
            )
            if ready and Phase3CourseService(root).navigation_path.is_file():
                navigation = Phase3CourseNavigator(root).state()
                payload.update(project_phase3_navigation(root, navigation))
            return payload
        phase2_store = KnowledgeStore(root)
        if phase2_store.load_knowledge(validate_sources=False):
            payload.update(
                {
                    "walkthroughs": [],
                    "current_walkthrough_id": "",
                    "current_walkthrough": None,
                    "source": None,
                }
            )
            payload["analysis"] = phase2_analysis_payload(root)
            payload["phase2_initialized"] = initialization_ready(root)
            payload["course_graph"] = CourseGraph.from_store(phase2_store).to_dict()
            navigation = CourseNavigator(root).state()
            if navigation.get("current"):
                payload.update(project_navigation(root, navigation))
            return payload
        migration = LegacyCorpusMigrator(root).status()
        payload["phase2_initialized"] = False
        payload["migration"] = migration.to_dict()
        analysis = store.corpus_analysis()
        if analysis is not None:
            payload["analysis"] = analysis.to_dict()
        corpus = store.course_corpus_payload()
        if corpus is not None:
            payload["corpus"] = corpus
        try:
            payload["source"] = _walkthrough_source_payload(root, current)
        except CodeLearnerError as error:
            payload["source_error"] = str(error)
        return payload

    def _walkthrough_summaries(self, root: Path) -> list[dict[str, object]]:
        return [
            _walkthrough_summary(walkthrough)
            for walkthrough in CodeLearnerStore(root).walkthroughs()
        ]

    def _active_project_root(self, context_id: str) -> Path:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.workflow_id != self.workflow_id:
                raise StateError("activate the Code Learner workflow first")
            root = context.active_project_root
        if root is None:
            raise StateError("open a source repository first")
        return Path(root).expanduser().resolve()


def _code_view_from_options(
    root: Path,
    options: dict[str, object],
) -> dict[str, object]:
    navigation = CourseNavigator(root).state().get("navigation")
    navigation = navigation if isinstance(navigation, dict) else {}
    current = navigation.get("code_view")
    current = current if isinstance(current, dict) else {}
    return {
        "path": options.get("selected_file_path") or current.get("path") or "",
        "selected_start_line": options.get("selected_start_line"),
        "selected_end_line": options.get("selected_end_line"),
        "visible_start_line": options.get("visible_start_line")
        or current.get("visible_start_line"),
        "visible_end_line": options.get("visible_end_line")
        or current.get("visible_end_line"),
    }


def _phase3_code_view_from_options(
    root: Path,
    options: dict[str, object],
) -> dict[str, object]:
    navigation = Phase3CourseNavigator(root).state()
    current = navigation.get("code_view")
    current = current if isinstance(current, dict) else {}
    return {
        "path": options.get("selected_file_path") or current.get("path") or "",
        "selected_start_line": options.get("selected_start_line"),
        "selected_end_line": options.get("selected_end_line"),
        "start_line": options.get("selected_start_line")
        or current.get("start_line")
        or 1,
        "end_line": options.get("selected_end_line")
        or current.get("end_line")
        or options.get("selected_start_line")
        or current.get("start_line")
        or 1,
        "visible_start_line": options.get("visible_start_line")
        or current.get("visible_start_line"),
        "visible_end_line": options.get("visible_end_line")
        or current.get("visible_end_line"),
    }


def _phase3_selected(root: Path) -> bool:
    selected = LearnerGenerationStore(root).load()
    return selected is not None and selected.generation == "phase3"


def _phase3_state_present(root: Path) -> bool:
    store = Phase3Store(root)
    return _phase3_selected(root) or any(
        path.exists()
        for path in (
            store.checkpoint_path,
            store.result_path,
            store.state_root / "source" / "manifest.json",
        )
    )


def _phase3_course_identity(course_id: str) -> tuple[str, str]:
    for mode in ("architecture", "module", "function"):
        prefix = f"course:{mode}:"
        if course_id.startswith(prefix):
            scope_id = course_id[len(prefix) :]
            if scope_id:
                return mode, scope_id
    raise CodeLearnerError(f"invalid Phase 3 course ID: {course_id}")


def _phase3_symbol_payload(root: Path, symbol: dict[str, object]) -> dict[str, object]:
    source = SourceManifestService(root).load()
    file = source.by_id().get(str(symbol.get("file_id") or ""), {}) if source else {}
    scope = str(symbol.get("scope") or "")
    name = str(symbol.get("name") or "")
    return {
        **symbol,
        "id": symbol.get("canonical_key"),
        "qualified_name": f"{scope}.{name}" if scope else name,
        "file_path": file.get("path") or "",
    }


def _phase3_manifest_status(root: Path) -> dict[str, object]:
    store = Phase3Store(root)
    checkpoint = store.read_json(store.checkpoint_path) or {}
    terminal = store.load_terminal_result() or {}
    manifests = {
        "source": store.read_json(store.state_root / "source" / "manifest.json"),
        "components": store.read_json(store.components_root / "manifest.json"),
        "modules": store.read_json(store.modules_root / "manifest.json"),
    }
    count_fields = {
        "source": "file_count",
        "components": "component_count",
        "modules": "module_count",
    }
    return {
        "generation": "phase3",
        "checkpoint_status": str(checkpoint.get("status") or ""),
        "analysis_run_id": str(checkpoint.get("analysis_run_id") or ""),
        "repository_revision": str(
            terminal.get("repository_revision")
            or checkpoint.get("repository_revision")
            or ""
        ),
        "stages": dict(checkpoint.get("stages") or {}),
        "manifests": {
            name: (
                {
                    "id": value.get("id"),
                    "status": value.get("status"),
                    "repository_revision": value.get("repository_revision"),
                    "count": value.get(count_fields[name]),
                }
                if value
                else None
            )
            for name, value in manifests.items()
        },
        "terminal": terminal or None,
    }


def context_options_from_payload(payload: dict[str, Any]) -> dict[str, object]:
    return {
        "selected_file_path": str(payload.get("selected_file_path") or ""),
        "selected_start_line": _optional_int(payload.get("selected_start_line")),
        "selected_end_line": _optional_int(payload.get("selected_end_line")),
        "visible_start_line": _optional_int(payload.get("visible_start_line")),
        "visible_end_line": _optional_int(payload.get("visible_end_line")),
    }


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise CodeLearnerError(f"expected an integer line number, got: {value}")
