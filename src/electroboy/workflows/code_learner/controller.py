"""Code Learner browser workflow controller."""

from __future__ import annotations

import hashlib
import re
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

from .background_courses import ModuleCourseScheduler, module_generation_status
from .course_generation import (
    CourseGenerationCancelled,
    CourseGenerationService,
    CourseWorkerService,
)
from .domain import CodeLearnerError, SourceAdapter
from .initialization import InitializationLease
from .navigation import CourseNavigator
from .store import LearnerStore
from .tutor_context import (
    TUTOR_CONTEXT_RELATIVE_PATH,
    TutorContextStore,
    require_repository_read_capability,
    tutor_bootstrap_prompt,
)

WORKFLOW_ID = "code-learner"
_RUNNING_STATUSES = frozenset({"queued", "running", "aborting"})
_INITIALIZATION_MODES = frozenset({"continue", "replace"})


@dataclass
class _InitializationJob:
    root: Path
    job_id: str = field(default_factory=lambda: uuid4().hex)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    started_monotonic: float = field(default_factory=time.monotonic)
    thread: threading.Thread | None = None
    lease: InitializationLease | None = None

    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


def _existing_project_root(path: str) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise StateError(f"project path does not exist: {root}")
    if not root.is_dir():
        raise StateError(f"project path is not a directory: {root}")
    return root


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
        tutor_bootstrap_prompt(root),
    ]
    require_repository_read_capability(command, root)
    return command


class CodeLearnerWorkflowController(BoundWorkflowController):
    """Coordinate trusted AI course files with browser workflow state."""

    workflow_id = WORKFLOW_ID

    def __init__(self, services: ServiceServices) -> None:
        super().__init__(services)
        self._lock = threading.RLock()
        self._jobs: dict[str, _InitializationJob] = {}
        self._module_schedulers: dict[str, ModuleCourseScheduler] = {}

    def close(self) -> None:
        with self._lock:
            jobs = tuple(self._jobs.values())
            schedulers = tuple(self._module_schedulers.values())
        for job in jobs:
            job.cancel_event.set()
        for scheduler in schedulers:
            scheduler.stop()

    def open_project(self, context_id: str, path: str) -> dict[str, object]:
        root = _existing_project_root(path)
        workspace_id, resumed = self._reserve_project_workspace(context_id, root)
        if resumed:
            return {
                **self.services.contexts.project_payload(workspace_id),
                "status": "resumed",
            }
        with self.services.contexts.lock:
            context = self.services.contexts.require(workspace_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="code-learner",
                activation_root=root,
                active_project_root=root,
                workflow_stage="project",
            )
            self.services.workspaces.persist(workspace_id)
        remember_recent_project(self.services.files.state_root, root, self.workflow_id)
        return {
            **self.services.contexts.project_payload(workspace_id),
            "status": "opened",
        }

    def project_payload_extension(self, context_id: str) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            root = context.active_project_root
        if root is None:
            return {"code_learner": _empty_state()}
        return {"code_learner": self._state_payload(Path(root))}

    def initialize(
        self,
        context_id: str,
        *,
        mode: str = "continue",
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        requested_mode = str(mode or "continue").strip().lower()
        if requested_mode not in _INITIALIZATION_MODES:
            raise CodeLearnerError(f"invalid initialization mode: {requested_mode}")
        store = LearnerStore(root)
        if requested_mode == "continue" and store.course_ready("architecture"):
            self._start_module_scheduler(root)
            return self._initialization_payload(context_id, root)
        self._require_cache_clearable(context_id)
        with self._lock:
            active = self._jobs.get(str(root))
            if active is not None and active.running():
                if requested_mode == "replace":
                    raise CodeLearnerError(
                        "stop the current initialization before replacing it"
                    )
                return self._initialization_payload(context_id, root)
            scheduler = self._module_schedulers.pop(str(root), None)
            if scheduler is not None:
                scheduler.stop()
            job = _InitializationJob(root)
            job.lease = InitializationLease.acquire(root, job.job_id)
            try:
                if requested_mode == "replace":
                    store.clear()
                store.initialize_layout()
                store.save_status(
                    status="queued",
                    phase="setup",
                    percent=1,
                    completion_status="",
                    message="Queued Code Learner initialization.",
                    error="",
                    started_at=utc_now(),
                )
            except Exception:
                job.lease.release()
                raise
            job.thread = threading.Thread(
                target=self._run_initialization,
                args=(root, job),
                name=f"code-learner-init-{job.job_id[:8]}",
                daemon=True,
            )
            self._jobs[str(root)] = job
            job.thread.start()
        return self._initialization_payload(context_id, root)

    def initialization_status(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        if LearnerStore(root).course_ready("architecture"):
            self._start_module_scheduler(root)
        return self._initialization_payload(context_id, root)

    def abort_initialization(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        with self._lock:
            job = self._jobs.get(str(root))
        if job is not None and job.running():
            job.cancel_event.set()
            LearnerStore(root).save_status(
                status="aborting",
                phase="aborting",
                message="Stopping initialization...",
            )
        return self._initialization_payload(context_id, root)

    def wait_for_initialization(
        self,
        context_id: str,
        timeout: float | None = None,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        with self._lock:
            job = self._jobs.get(str(root))
        if job is not None and job.thread is not None:
            job.thread.join(timeout=timeout)
        return self._initialization_payload(context_id, root)

    def clear_course_cache(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        self._require_cache_clearable(context_id)
        with self._lock:
            job = self._jobs.get(str(root))
            if job is not None and job.running():
                raise CodeLearnerError(
                    "stop Code Learner initialization before clearing the cache"
                )
            scheduler = self._module_schedulers.pop(str(root), None)
            if scheduler is not None:
                scheduler.stop()
            lease = InitializationLease.acquire(root, f"clear-{uuid4().hex}")
            try:
                cleared = LearnerStore(root).clear()
            finally:
                lease.release()
            self._jobs.pop(str(root), None)
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "cache_cleared",
            "cache": cleared,
            "initialization": self._initialization_snapshot(root),
            "code_learner": self._state_payload(root),
        }

    def analysis(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        state = self._state_payload(root)
        return {
            "status": "analyzed" if state["initialized"] else "uninitialized",
            "analysis": state["analysis"],
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
        self,
        context_id: str,
        mode: str,
        scope_id: str,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        view = CourseNavigator(root).open(mode, _scope_for_mode(mode, scope_id))
        return {"status": "loaded", **CourseNavigator(root).artifact(view)}

    def course_graph(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        store = LearnerStore(root)
        return {
            "status": "loaded",
            "graph": {
                "architecture": store.course_index("architecture"),
                "modules": store.modules(),
                "background_modules": module_generation_status(root),
            },
        }

    def resolve_function_course(
        self,
        context_id: str,
        query: str,
    ) -> dict[str, object]:
        root = self._active_project_root(context_id)
        symbol = str(query or "").strip()
        if not symbol:
            raise CodeLearnerError("Function symbol is required")
        scope_id = _function_course_id(symbol)
        return {
            "status": "resolved",
            "symbol": {
                "id": scope_id,
                "canonical_key": scope_id,
                "name": symbol,
                "qualified_name": symbol,
            },
            "candidates": [],
            "course_status": (
                "ready"
                if LearnerStore(root).course_ready("function", scope_id)
                else "missing"
            ),
        }

    def build_function_course(
        self,
        context_id: str,
        query: str,
        audience: str = "",
    ) -> dict[str, object]:
        del audience
        root = self._active_project_root(context_id)
        if not LearnerStore(root).course_ready("architecture"):
            raise CodeLearnerError("initialize Code Learner first")
        symbol = str(query or "").strip()
        if not symbol:
            raise CodeLearnerError("Function symbol is required")
        scope_id = _function_course_id(symbol)
        store = LearnerStore(root)
        if not store.course_ready("function", scope_id):
            CourseWorkerService(root).generate_function(symbol, scope_id)
        return {
            "status": "ready",
            "course": {
                "mode": "function",
                "scope_id": scope_id,
                "jsonl_path": store.relative(
                    store.course_index_path("function", scope_id)
                ),
            },
        }

    def modules(self, context_id: str) -> dict[str, object]:
        root = self._active_project_root(context_id)
        return {
            "status": "listed",
            "modules": self._module_payloads(root),
            "truncated": False,
        }

    def symbols(self, context_id: str, query: str = "") -> dict[str, object]:
        resolution = self.resolve_function_course(context_id, query) if query else None
        return {
            "status": "listed",
            "symbols": [],
            "truncated": False,
            "resolution": resolution,
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
        store = LearnerStore(root)
        if not store.course_ready("architecture"):
            raise CodeLearnerError("initialize Code Learner first")
        mode = str(learning_mode or "").strip().lower()
        scope_id = str(target or "").strip()
        if mode == "architecture":
            scope_id = ""
        elif mode == "module":
            if not scope_id:
                raise CodeLearnerError("Module target is required")
            if not store.course_ready("module", scope_id):
                background = self._start_module_scheduler(root)
                scheduler = self._module_schedulers[str(root)]
                background = scheduler.prioritize(scope_id)
                target_state = next(
                    (
                        item
                        for item in background["targets"]
                        if item["module_id"] == scope_id
                    ),
                    {"module_id": scope_id, "status": "pending"},
                )
                return {
                    "status": str(target_state["status"]),
                    "course_target": target_state,
                    "background_modules": background,
                }
        elif mode == "function":
            result = self.build_function_course(
                context_id,
                scope_id,
                intended_audience,
            )
            scope_id = str(result["course"]["scope_id"])
        else:
            raise CodeLearnerError(f"unknown course mode: {learning_mode}")
        return self._navigation_payload(
            context_id,
            root,
            CourseNavigator(root).open(mode, scope_id),
        )

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
        del target_id
        root = self._active_project_root(context_id)
        navigator = CourseNavigator(root)
        if action == "open":
            mode, scope_id = _course_identity(course_id)
            view = navigator.open(mode, scope_id, section_id)
        elif action in {"previous", "next"}:
            view = navigator.move(action)
        elif action == "code-view":
            view = navigator.update_code_view(code_view or {})
        elif action in {"state", "back", "deep-dive"}:
            view = navigator.state()
        else:
            raise CodeLearnerError(f"unknown course navigation action: {action}")
        if not view:
            return {}
        return self._navigation_payload(context_id, root, view)

    def set_current_step(
        self,
        context_id: str,
        walkthrough_id: str,
        step_id: str,
    ) -> dict[str, object]:
        del walkthrough_id
        root = self._active_project_root(context_id)
        view = CourseNavigator(root).select(step_id)
        return self._navigation_payload(context_id, root, view)

    def learner_context(
        self,
        context_id: str,
        walkthrough_id: str = "",
        **context_options: object,
    ) -> dict[str, object]:
        del walkthrough_id
        root = self._active_project_root(context_id)
        navigator = CourseNavigator(root)
        view = navigator.update_code_view(_code_view(root, context_options))
        context = TutorContextStore(root).write_navigation(
            view,
            project_id=context_id,
            writer_id=f"electroboy:{context_id}",
        )
        return {"status": "prepared", "context": context}

    def prepare_question(
        self,
        context_id: str,
        question: str,
        walkthrough_id: str = "",
        **context_options: object,
    ) -> dict[str, object]:
        text = str(question or "").strip()
        if not text:
            raise CodeLearnerError("learner question is required")
        context = self.learner_context(
            context_id,
            walkthrough_id,
            **context_options,
        )["context"]
        return {
            "status": "prepared",
            "question": text,
            "prompt": text,
            "context_version": context["context_version"],
            "context_path": TUTOR_CONTEXT_RELATIVE_PATH,
        }

    def start_agent(
        self,
        context_id: str,
        walkthrough_id: str = "",
        **context_options: object,
    ) -> tuple[AgentSession, bool]:
        root = self._active_project_root(context_id)
        navigation = CourseNavigator(root).state()
        if not navigation:
            raise CodeLearnerError("open a course before starting the tutor")
        if context_options:
            navigation = CourseNavigator(root).update_code_view(
                _code_view(root, context_options)
            )
        course = navigation.get("current")
        course = course if isinstance(course, dict) else {}
        with self.services.contexts.lock:
            browser = self.services.contexts.require(context_id)
            for session in browser.code_learner_sessions.values():
                if session.is_active():
                    browser.selected_session_id = session.session_id
                    return session, False
            session = AgentSession(
                command=code_learner_agent_command(root),
                cwd=root,
                label="code learner tutor",
                kind=self.workflow_id,
                interactive=True,
                metadata={
                    "walkthrough_id": walkthrough_id,
                    "learning_mode": navigation.get("mode"),
                    "mode_target": navigation.get("scope_id"),
                    "tutor_context_path": TUTOR_CONTEXT_RELATIVE_PATH,
                },
            )
            session = self.services.sessions.prepare(browser, session)
            browser.code_learner_sessions[session.session_id] = session
            browser.selected_session_id = session.session_id
            self.services.sessions.record(browser, session)
        TutorContextStore(root).write_navigation(
            navigation,
            project_id=context_id,
            writer_id=session.session_id,
        )
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                browser = self.services.contexts.require(context_id)
                self.services.sessions.clear(browser, [session])
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

    def _reserve_project_workspace(
        self,
        context_id: str,
        root: Path,
    ) -> tuple[str, bool]:
        with self.services.contexts.lock:
            current = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(current)
        workspace, resumed = self.services.workspaces.reserve_project(
            context_id,
            workflow_id=self.workflow_id,
            project_kind="code-learner",
            project_identity=str(root),
            name=root.name,
        )
        return workspace.context_id, resumed

    def _run_initialization(self, root: Path, job: _InitializationJob) -> None:
        store = LearnerStore(root)
        try:
            CourseGenerationService(root, cancel_event=job.cancel_event).run()
            self._start_module_scheduler(root)
        except CourseGenerationCancelled:
            store.save_status(
                status="aborted",
                phase="aborted",
                message="Initialization stopped. Run Initialize to resume.",
                error="",
            )
        except Exception as error:
            message = str(error)
            store.append_progress(
                {
                    "activity_kind": "error",
                    "phase": "initialization",
                    "percent": int(store.load_status().get("percent") or 0),
                    "message": message,
                }
            )
            store.save_status(
                status="failed",
                completion_status="failed",
                message=message,
                error=message,
            )
        finally:
            if job.lease is not None:
                job.lease.release()
                job.lease = None

    def _initialization_payload(
        self,
        context_id: str,
        root: Path,
    ) -> dict[str, object]:
        snapshot = self._initialization_snapshot(root)
        status = str(snapshot["status"])
        outer = (
            "initializing"
            if status in _RUNNING_STATUSES
            else "initialized"
            if status == "initialized"
            else "failed"
            if status == "failed"
            else "uninitialized"
        )
        return {
            **self.services.contexts.project_payload(context_id),
            "status": outer,
            "initialization": snapshot,
            "code_learner": self._state_payload(root),
        }

    def _initialization_snapshot(self, root: Path) -> dict[str, object]:
        store = LearnerStore(root)
        status = store.load_status()
        with self._lock:
            job = self._jobs.get(str(root))
        if store.course_ready("architecture"):
            status.update(
                {
                    "status": "initialized",
                    "phase": "complete",
                    "percent": 100,
                    "completion_status": "complete",
                    "message": "Architecture course is ready.",
                    "error": "",
                }
            )
        elif not status:
            status = {
                "status": "idle",
                "phase": "idle",
                "percent": 0,
                "message": "Initialize Code Learner to generate a course.",
                "error": "",
                "completion_status": "",
            }
        elapsed = (
            max(0, int(time.monotonic() - job.started_monotonic))
            if job is not None
            else 0
        )
        status.update(
            {
                "job_id": job.job_id if job is not None else "",
                "elapsed_seconds": elapsed,
                "estimated_remaining_seconds": None,
                "progress_events": store.progress(),
                "abort_requested": bool(job and job.cancel_event.is_set()),
                "choice_required": self._choice_required(store, status),
                "background_modules": module_generation_status(root),
                "progress_path": str(store.progress_path),
            }
        )
        return status

    def _state_payload(self, root: Path) -> dict[str, object]:
        store = LearnerStore(root)
        initialized = store.course_ready("architecture")
        navigation = CourseNavigator(root).state() if initialized else {}
        payload = {
            **_empty_state(),
            "state_path": store.relative(store.status_path),
            "initialized": initialized,
            "completion_status": "complete" if initialized else "",
            "analysis": {
                "source_root": str(root),
                "source_files": [],
                "language_counts": {},
                "modules": self._module_payloads(root) if initialized else [],
                "symbols": [],
                "truncated": False,
            },
            "background_modules": module_generation_status(root),
        }
        if navigation:
            payload.update(self._navigation_projection(root, navigation))
        return payload

    def _module_payloads(self, root: Path) -> list[dict[str, object]]:
        status = module_generation_status(root)
        target_by_id = {
            str(target.get("module_id")): target
            for target in status["targets"]
            if isinstance(target, dict)
        }
        result = []
        for module in LearnerStore(root).modules():
            module_id = str(module.get("eb_module_id") or "")
            components = module.get("ai_comp_list")
            result.append(
                {
                    "id": module_id,
                    "path": module_id,
                    "name": str(module.get("ai_module_name") or module_id),
                    "summary": "",
                    "file_count": 0,
                    "component_count": (
                        len(components) if isinstance(components, list) else 0
                    ),
                    "course_status": str(
                        target_by_id.get(module_id, {}).get("status") or "pending"
                    ),
                }
            )
        return result

    def _navigation_payload(
        self,
        context_id: str,
        root: Path,
        navigation: dict[str, object],
    ) -> dict[str, object]:
        context = TutorContextStore(root).write_navigation(
            navigation,
            project_id=context_id,
            writer_id=f"electroboy:{context_id}",
        )
        payload = self._navigation_projection(root, navigation)
        payload["tutor_context"] = context
        return {"status": "ready", **payload}

    def _navigation_projection(
        self,
        root: Path,
        navigation: dict[str, object],
    ) -> dict[str, object]:
        navigator = CourseNavigator(root)
        walkthrough = navigator.walkthrough(navigation)
        walkthrough["source_root"] = str(root)
        walkthrough["intended_audience"] = ""
        source = _source_for_walkthrough(root, walkthrough, navigation)
        return {
            "walkthrough": walkthrough,
            "current_walkthrough": walkthrough,
            "walkthroughs": [_walkthrough_summary(walkthrough)],
            "source": source,
            "course_navigation": navigation,
            "course_artifact": navigator.artifact(navigation),
        }

    def _start_module_scheduler(self, root: Path) -> dict[str, object]:
        if not LearnerStore(root).course_ready("architecture"):
            return module_generation_status(root)
        key = str(root)
        with self._lock:
            scheduler = self._module_schedulers.get(key)
            if scheduler is None:
                scheduler = ModuleCourseScheduler(root)
                self._module_schedulers[key] = scheduler
        return scheduler.start()

    def _require_cache_clearable(self, context_id: str) -> None:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if any(
                session.is_active()
                for session in context.code_learner_sessions.values()
            ):
                raise CodeLearnerError(
                    "stop the Code Learner tutor before clearing the course cache"
                )

    @staticmethod
    def _choice_required(
        store: LearnerStore,
        status: dict[str, object],
    ) -> bool:
        if str(status.get("status") or "") in _RUNNING_STATUSES | {"initialized"}:
            return False
        if str(status.get("status") or "") in {"failed", "aborted"}:
            return True
        return store.course_root.is_dir() and any(
            path.is_file() for path in store.course_root.rglob("*")
        )

    def _active_project_root(self, context_id: str) -> Path:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.workflow_id != self.workflow_id:
                raise StateError("activate the Code Learner workflow first")
            root = context.active_project_root
        if root is None:
            raise StateError("open a source repository first")
        return Path(root).expanduser().resolve()


def _empty_state() -> dict[str, object]:
    return {
        "state_path": "",
        "initialized": False,
        "completion_status": "",
        "analysis": None,
        "background_modules": None,
        "walkthroughs": [],
        "current_walkthrough_id": "",
        "current_walkthrough": None,
        "source": None,
        "course_artifact": None,
        "course_navigation": None,
    }


def _course_identity(course_id: str) -> tuple[str, str]:
    for mode in ("architecture", "module", "function"):
        prefix = f"course:{mode}:"
        if course_id.startswith(prefix):
            scope_id = course_id[len(prefix) :]
            return mode, _scope_for_mode(mode, scope_id)
    raise CodeLearnerError(f"invalid course ID: {course_id}")


def _scope_for_mode(mode: str, scope_id: str) -> str:
    if mode == "architecture" and scope_id in {"", "current"}:
        return ""
    return scope_id


def _function_course_id(symbol: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", symbol).strip("-").lower() or "symbol"
    digest = hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:10]
    return f"fn-{slug[:48]}-{digest}"


def _walkthrough_summary(walkthrough: dict[str, object]) -> dict[str, object]:
    steps = walkthrough.get("steps")
    return {
        "id": walkthrough.get("id"),
        "title": walkthrough.get("title"),
        "learning_mode": walkthrough.get("learning_mode"),
        "mode_target": walkthrough.get("mode_target"),
        "current_step_id": walkthrough.get("current_step_id"),
        "review_status": walkthrough.get("review_status"),
        "step_count": len(steps) if isinstance(steps, list) else 0,
        "qa_count": 0,
    }


def _source_for_walkthrough(
    root: Path,
    walkthrough: dict[str, object],
    navigation: dict[str, object],
) -> dict[str, object] | None:
    steps = walkthrough.get("steps")
    steps = steps if isinstance(steps, list) else []
    current_id = str(walkthrough.get("current_step_id") or "")
    step = next(
        (
            item
            for item in steps
            if isinstance(item, dict) and item.get("id") == current_id
        ),
        {},
    )
    reference = step.get("primary_reference")
    reference = reference if isinstance(reference, dict) else {}
    nav = navigation.get("navigation")
    nav = nav if isinstance(nav, dict) else {}
    code_view = nav.get("code_view")
    code_view = code_view if isinstance(code_view, dict) else {}
    path = str(code_view.get("path") or reference.get("file_path") or "")
    if not path:
        return None
    start = _safe_int(
        code_view.get("selected_start_line") or reference.get("start_line"), 1
    )
    end = _safe_int(
        code_view.get("selected_end_line") or reference.get("end_line"), start
    )
    try:
        return SourceAdapter(root).source_payload(
            path,
            start_line=start,
            end_line=end,
            padding=80,
        )
    except (OSError, StateError, CodeLearnerError, ValueError):
        return None


def _code_view(root: Path, options: dict[str, object]) -> dict[str, object]:
    state = CourseNavigator(root).state()
    navigation = state.get("navigation")
    navigation = navigation if isinstance(navigation, dict) else {}
    current = navigation.get("code_view")
    current = current if isinstance(current, dict) else {}
    return {
        "path": options.get("selected_file_path") or current.get("path") or "",
        "selected_start_line": options.get("selected_start_line"),
        "selected_end_line": options.get("selected_end_line"),
        "visible_start_line": (
            options.get("visible_start_line") or current.get("visible_start_line")
        ),
        "visible_end_line": (
            options.get("visible_end_line") or current.get("visible_end_line")
        ),
    }


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


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
    except (TypeError, ValueError) as error:
        raise CodeLearnerError(
            f"expected an integer line number, got: {value}"
        ) from error
