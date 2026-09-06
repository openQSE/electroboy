"""Concurrent, durable Module knowledge and course generation."""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .agent_sessions import AgentSessionRegistry, ReusableAgentRuntime
from .domain import CodeLearnerError
from .module_knowledge import ModuleKnowledgeService
from .modules import ModuleSynthesisService
from .phase3_courses import Phase3CourseService
from .phase3_store import Phase3Store

ProgressCallback = Callable[[dict[str, object]], None]
RuntimeFactory = Callable[[str, Path], AgentRuntime]
ACTIVE_TARGET_STATES = frozenset(
    {"queued", "generating_knowledge", "building_course"}
)


class ModuleCourseScheduler:
    """Run independent Module targets through a bounded priority queue."""

    def __init__(
        self,
        root: Path | str,
        *,
        runtime_factory: RuntimeFactory | None = None,
        worker_count: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = Phase3Store(self.root)
        self.courses = Phase3CourseService(self.root, store=self.store)
        self.sessions = AgentSessionRegistry(self.root, store=self.store)
        self.runtime_factory = runtime_factory or _runtime_factory
        requested = worker_count or int(
            os.environ.get("ELECTROBOY_CODE_LEARNER_WORKERS", "3")
        )
        self.worker_count = max(1, min(8, requested))
        self.progress_callback = progress_callback
        self._queue: queue.PriorityQueue[tuple[int, int, str]] = queue.PriorityQueue()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._queued_versions: dict[str, int] = {}
        self._queued_priorities: dict[str, int] = {}
        self._active: set[str] = set()
        self._sequence = 0

    def start(self) -> dict[str, object]:
        modules = self._module_ids()
        if not modules:
            return module_generation_status(self.root)
        revision = self._revision()
        self.sessions.prepare(revision)
        with self._lock:
            self.worker_count = min(self.worker_count, len(modules))
            if not self._threads:
                for index in range(self.worker_count):
                    thread = threading.Thread(
                        target=self._worker,
                        args=(index,),
                        name=f"code-learner-module-{index}",
                        daemon=True,
                    )
                    self._threads.append(thread)
                    thread.start()
            for module_id in modules:
                status = self._target_status(module_id)
                if status == "ready" or status == "failed":
                    continue
                self._enqueue(module_id, priority=100, reset_status=True)
        self._emit("Background Module generation started.")
        return module_generation_status(self.root)

    def prioritize(self, module_id: str) -> dict[str, object]:
        if module_id not in set(self._module_ids()):
            raise CodeLearnerError(f"unknown Module target: {module_id}")
        status = self._target_status(module_id)
        if status == "ready" or module_id in self._active:
            return module_generation_status(self.root)
        self._enqueue(module_id, priority=0, reset_status=True)
        self._emit(f"Prioritized Module course {module_id}.", module_id=module_id)
        return module_generation_status(self.root)

    def stop(self) -> None:
        self._stop.set()
        current = threading.current_thread()
        for thread in self._threads:
            if thread is not current:
                thread.join(timeout=5)

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            status = module_generation_status(self.root)
            if status["status"] in {"complete", "complete_with_warnings"}:
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def _enqueue(self, module_id: str, *, priority: int, reset_status: bool) -> None:
        with self._lock:
            if module_id in self._active:
                return
            existing_priority = self._queued_priorities.get(module_id)
            if existing_priority is not None and priority >= existing_priority:
                return
            self._sequence += 1
            sequence = self._sequence
            self._queued_versions[module_id] = sequence
            self._queued_priorities[module_id] = priority
            if reset_status:
                self.courses.record_status("module", module_id, "queued")
            self._queue.put((priority, sequence, module_id))

    def _worker(self, index: int) -> None:
        runtime_factory = self._worker_runtime_factory(index)
        knowledge = ModuleKnowledgeService(
            self.root,
            store=self.store,
            runtime_factory=runtime_factory,
        )
        courses = Phase3CourseService(
            self.root,
            store=self.store,
            runtime_factory=runtime_factory,
        )
        while not self._stop.is_set():
            try:
                _priority, sequence, module_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                if self._queued_versions.get(module_id) != sequence:
                    self._queue.task_done()
                    continue
                self._queued_versions.pop(module_id, None)
                self._queued_priorities.pop(module_id, None)
                self._active.add(module_id)
            try:
                self._generate_target(module_id, knowledge=knowledge, courses=courses)
            finally:
                with self._lock:
                    self._active.discard(module_id)
                self._queue.task_done()
                self._refresh_terminal_status()

    def _generate_target(
        self,
        module_id: str,
        *,
        knowledge: ModuleKnowledgeService,
        courses: Phase3CourseService,
    ) -> None:
        try:
            self.courses.record_status("module", module_id, "generating_knowledge")
            self._emit(
                f"Generating knowledge for Module {module_id}.",
                module_id=module_id,
            )
            knowledge.generate(module_id, analysis_run_id=self._analysis_run_id())
            self.courses.record_status("module", module_id, "building_course")
            self._emit(
                f"Building course for Module {module_id}.",
                module_id=module_id,
            )
            courses.build(
                "module",
                module_id,
                analysis_run_id=self._analysis_run_id(),
            )
            self._emit(f"Module course {module_id} is ready.", module_id=module_id)
        except Exception as error:
            message = str(error)
            self.courses.record_status(
                "module", module_id, "failed", error=message
            )
            self.store.save_diagnostic(
                {
                    "schema_version": 1,
                    "record_type": "diagnostic",
                    "id": f"diagnostic:background-module:{_safe(module_id)}",
                    "severity": "warning",
                    "code": "background-module-failed",
                    "message": f"Module {module_id}: {message}",
                    "active": True,
                    "recorded_at": utc_now(),
                }
            )
            self._emit(
                f"Module course {module_id} failed: {message}",
                module_id=module_id,
                activity_kind="warning",
            )

    def _worker_runtime_factory(self, index: int) -> RuntimeFactory:
        slot = f"worker:{index}"

        def factory(role: str, root: Path) -> AgentRuntime:
            return _CancellableRuntime(
                ReusableAgentRuntime(
                    self.runtime_factory(role, root),
                    self.sessions,
                    slot=slot,
                    fork_from_slot="primary",
                ),
                self._stop,
            )

        return factory

    def _target_status(self, module_id: str) -> str:
        return self.courses.target_status(f"course:module:{module_id}")

    def _module_ids(self) -> list[str]:
        snapshot = ModuleSynthesisService(self.root, store=self.store).load()
        return (
            sorted(str(module["id"]) for module in snapshot.modules)
            if snapshot is not None
            else []
        )

    def _revision(self) -> str:
        snapshot = ModuleSynthesisService(self.root, store=self.store).load()
        if snapshot is None:
            return ""
        return str(snapshot.manifest.get("repository_revision") or "")

    def _analysis_run_id(self) -> str:
        checkpoint = self.store.read_json(self.store.checkpoint_path) or {}
        return str(checkpoint.get("analysis_run_id") or "background")

    def _refresh_terminal_status(self) -> None:
        terminal = self.store.load_terminal_result()
        if terminal is None or terminal.get("course_active") is not True:
            return
        warnings = self.store.active_diagnostics("warning")
        terminal.update(
            {
                "status": "complete_with_warnings" if warnings else "complete",
                "warning_count": len(warnings),
                "diagnostic_ids": [str(item["id"]) for item in warnings],
                "completed_at": utc_now(),
            }
        )
        self.store.save_terminal_result(terminal)

    def _emit(
        self,
        message: str,
        *,
        module_id: str = "",
        activity_kind: str = "background",
    ) -> None:
        status = module_generation_status(self.root)
        payload = {
            "record_type": "progress",
            "phase": "module_courses",
            "stage": "module_courses",
            "percent": 100,
            "message": message,
            "activity_kind": activity_kind,
            "scope_ids": [module_id] if module_id else [],
            "background_modules": status,
            "updated_at": utc_now(),
        }
        self.store.append_progress(payload)
        if self.progress_callback is not None:
            self.progress_callback(payload)


def module_generation_status(root: Path | str) -> dict[str, object]:
    repository = Path(root).expanduser().resolve()
    store = Phase3Store(repository)
    snapshot = ModuleSynthesisService(repository, store=store).load()
    module_ids = (
        sorted(str(module["id"]) for module in snapshot.modules)
        if snapshot is not None
        else []
    )
    courses = Phase3CourseService(repository, store=store)
    targets = []
    counts: dict[str, int] = {}
    for module_id in module_ids:
        document_id = f"course:module:{module_id}"
        item = courses.index().get("targets", {}).get(document_id, {})
        status = courses.target_status(document_id)
        counts[status] = counts.get(status, 0) + 1
        targets.append(
            {
                "module_id": module_id,
                "document_id": document_id,
                "status": status,
                "error": str(item.get("error") or "") if isinstance(item, dict) else "",
            }
        )
    if not targets:
        aggregate = "idle"
    elif counts.get("ready", 0) == len(targets):
        aggregate = "complete"
    elif counts.get("failed", 0) and not any(
        counts.get(state, 0) for state in ACTIVE_TARGET_STATES
    ):
        aggregate = "complete_with_warnings"
    else:
        aggregate = "running"
    return {
        "status": aggregate,
        "total": len(targets),
        "ready": counts.get("ready", 0),
        "failed": counts.get("failed", 0),
        "active": sum(counts.get(state, 0) for state in ACTIVE_TARGET_STATES),
        "counts": counts,
        "targets": targets,
    }


def _safe(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value)


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)


class _CancellableRuntime(AgentRuntime):
    def __init__(self, runtime: AgentRuntime, cancel_event: threading.Event) -> None:
        self.runtime = runtime
        self.cancel_event = cancel_event

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        return self.runtime.invoke(
            replace(
                invocation,
                cancel_event=invocation.cancel_event or self.cancel_event,
            )
        )
