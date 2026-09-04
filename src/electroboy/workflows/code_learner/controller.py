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
from electroboy.service.sessions import AgentSession
from electroboy.service.services import ServiceServices
from electroboy.service.workflow_controller import BoundWorkflowController
from electroboy.state_store import StateError

from .domain import (
    WORKFLOW_ID,
    CodeLearnerError,
    CodeLearnerStore,
    SourceAdapter,
    Walkthrough,
    RepositoryAnalysis,
    build_learner_context,
    create_walkthrough,
    learner_prompt,
    learner_question_payload,
    resolve_symbol,
)
from .planner import generate_code_learner_course_corpus_jsonl

_INITIALIZATION_RUNNING_STATUSES = frozenset({"queued", "running"})


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
    resumed_from_checkpoint: bool = False
    started_monotonic: float = field(default_factory=time.monotonic)
    thread: threading.Thread | None = field(default=None, repr=False)
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
        phase = str(record.get("phase") or self.phase or "running").strip()
        message = str(record.get("message") or phase).strip()
        percent = _bounded_percent(record.get("percent"))
        self.update(
            status="running",
            phase=phase or "running",
            percent=percent,
            message=message or "Initializing AI course material.",
            progress=True,
        )
        with self.lock:
            event = {
                "phase": phase or "running",
                "percent": percent,
                "message": message or "Initializing AI course material.",
                "updated_at": self.updated_at,
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
                "resumed_from_checkpoint": self.resumed_from_checkpoint,
                "checkpoint_path": str(
                    CodeLearnerStore(self.root).initialization_checkpoint_path
                ),
                "progress_path": str(
                    CodeLearnerStore(self.root).initialization_progress_path
                ),
            }


def _bounded_percent(value: object) -> int:
    try:
        percent = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, percent))


def _estimated_remaining_seconds(elapsed: int, percent: int) -> int | None:
    if percent <= 0 or percent >= 100:
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
        "resumed_from_checkpoint": False,
        "checkpoint_path": str(CodeLearnerStore(root).initialization_checkpoint_path),
        "progress_path": str(CodeLearnerStore(root).initialization_progress_path),
    }


def _completed_initialization_snapshot(root: Path) -> dict[str, object]:
    return {
        "job_id": "",
        "status": "initialized",
        "phase": "complete",
        "percent": 100,
        "message": "AI course material is ready.",
        "started_at": "",
        "updated_at": utc_now(),
        "last_progress_at": "",
        "elapsed_seconds": 0,
        "estimated_remaining_seconds": None,
        "error": "",
        "progress_events": [],
        "resumed_from_checkpoint": False,
        "checkpoint_path": str(CodeLearnerStore(root).initialization_checkpoint_path),
        "progress_path": str(CodeLearnerStore(root).initialization_progress_path),
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
    context: dict[str, object] | None = None,
) -> str:
    lines = [
        "You are the ElectroBoy Code Learner tutor for this repository.",
        "",
        "Stay in teaching mode. Answer questions about the code the learner is",
        "currently viewing. Do not modify files, run implementation commands, or",
        "launch other agents unless the operator explicitly changes the task.",
        "",
        f"Repository root: {root}",
    ]
    if context:
        lines.extend(
            [
                "",
                "Initial learner context:",
                f"- Walkthrough: {context.get('walkthrough_id')}",
                f"- Mode: {context.get('learning_mode')}",
                f"- Target: {context.get('mode_target')}",
                f"- Step: {context.get('step_position')} {context.get('step_title')}",
                (
                    "- Source: "
                    f"{context.get('file_path')}:{context.get('start_line')}-"
                    f"{context.get('end_line')}"
                ),
            ]
        )
    return "\n".join(lines).strip()


def code_learner_agent_command(
    root: Path,
    context: dict[str, object] | None = None,
) -> list[str]:
    return [
        "codex",
        "--cd",
        str(root),
        "--sandbox",
        "read-only",
        _code_learner_agent_prompt(root, context),
    ]


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
        if CodeLearnerStore(root).corpus_analysis() is not None:
            return self._initialization_payload(context_id, root)
        with self._initialization_lock:
            job = self._initialization_jobs.get(str(root))
            if job is None or not job.is_running():
                store = CodeLearnerStore(root)
                job = _InitializationJob(
                    root=root,
                    resumed_from_checkpoint=store.initialization_checkpoint_path.is_file(),
                )
                thread = threading.Thread(
                    target=self._run_initialization_job,
                    args=(root, job),
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
        self._save_initialized_corpus(root, corpus_jsonl)
        state = self._state_payload(root)
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "initialized",
            "initialization": _completed_initialization_snapshot(root),
            "code_learner": state,
        }

    def _save_initialized_corpus(self, root: Path, corpus_jsonl: str) -> None:
        store = CodeLearnerStore(root)
        store.save_corpus_jsonl(corpus_jsonl)
        architecture = create_walkthrough(root, learning_mode="architecture")
        store.save_walkthrough(architecture)

    def _run_initialization_job(
        self,
        root: Path,
        job: _InitializationJob,
    ) -> None:
        store = CodeLearnerStore(root)
        progress_path = store.initialization_progress_relative_path.as_posix()
        checkpoint_path = store.initialization_checkpoint_relative_path.as_posix()
        job.record_progress(
            {
                "phase": "setup",
                "percent": 1,
                "message": (
                    "Resuming AI course initialization from cached findings."
                    if job.resumed_from_checkpoint
                    else "Starting AI course initialization with durable checkpointing."
                ),
            }
        )
        try:
            corpus_jsonl = generate_code_learner_course_corpus_jsonl(
                root,
                progress_path=progress_path,
                checkpoint_path=checkpoint_path,
                progress_callback=lambda record: self._record_initialization_progress(
                    job,
                    record,
                ),
            )
            job.update(
                phase="formalizing",
                percent=98,
                message="Formalizing AI course material.",
            )
            self._save_initialized_corpus(root, corpus_jsonl)
            job.update(
                status="initialized",
                phase="complete",
                percent=100,
                message="AI course material is ready.",
            )
        except Exception as error:
            message = str(error)
            job.update(
                status="failed",
                phase="failed",
                message=message,
                error=message,
            )

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
        initialized = "analysis" in state
        if job is not None and job.is_running():
            status = "initializing"
            initialization = job.snapshot()
        elif job is not None and str(job.snapshot().get("status")) == "failed":
            status = "failed"
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
            initialization = _idle_initialization_snapshot(root)
        return {
            **self.services.contexts.project_payload(context_id),
            "status": status,
            "initialization": initialization,
            "code_learner": state,
        }

    def analysis(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
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

    def modules(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        analysis = CodeLearnerStore(root).corpus_analysis() or _empty_analysis(root)
        return {
            "status": "listed",
            "modules": list(analysis.to_dict()["modules"]),
            "truncated": analysis.truncated,
        }

    def symbols(self, context_id: str, query: str = "") -> dict[str, object]:
        root = self._active_project_root(context_id)
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
        walkthrough = create_walkthrough(
            root,
            learning_mode=learning_mode,
            target=target,
            intended_audience=intended_audience,
        )
        saved = CodeLearnerStore(root).save_walkthrough(walkthrough)
        return self._walkthrough_payload(root, saved)

    def set_current_step(
        self,
        context_id: str,
        walkthrough_id: str,
        step_id: str,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        walkthrough = CodeLearnerStore(root).set_current_step(
            walkthrough_id,
            step_id,
        )
        return self._walkthrough_payload(root, walkthrough)

    def learner_context(
        self,
        context_id: str,
        walkthrough_id: str = "",
        **context_options: object,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        walkthrough = CodeLearnerStore(root).get(walkthrough_id)
        return {
            "status": "prepared",
            "context": build_learner_context(
                root,
                walkthrough,
                **context_options,
            ),
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
        walkthrough = store.get(walkthrough_id)
        payload = learner_question_payload(
            root,
            walkthrough,
            question,
            **context_options,
        )
        context = payload.get("context")
        if not isinstance(context, dict):
            raise CodeLearnerError("question context was not prepared")
        updated = store.record_question(walkthrough.id, question, context)
        return {
            **payload,
            "walkthrough": updated.to_dict(),
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
        walkthrough = store.get(walkthrough_id)
        learner_context = build_learner_context(root, walkthrough, **context_options)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            for session in context.code_learner_sessions.values():
                if session.is_active():
                    context.selected_session_id = session.session_id
                    return session, False
            session = AgentSession(
                command=code_learner_agent_command(root, learner_context),
                cwd=root,
                label="code learner tutor",
                kind=self.workflow_id,
                interactive=True,
                metadata={
                    "walkthrough_id": walkthrough.id,
                    "learning_mode": walkthrough.learning_mode,
                    "mode_target": walkthrough.mode_target,
                },
            )
            session = self.services.sessions.prepare(context, session)
            context.code_learner_sessions[session.session_id] = session
            context.selected_session_id = session.session_id
            self.services.sessions.record(context, session)
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
        root = self._active_project_root(context_id)
        walkthrough = CodeLearnerStore(root).get(walkthrough_id)
        return learner_prompt(
            question,
            build_learner_context(root, walkthrough, **context_options),
        )

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
