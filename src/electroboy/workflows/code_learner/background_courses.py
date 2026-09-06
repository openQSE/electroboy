"""Bounded background generation of AI-written Module courses."""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from electroboy.models import utc_now

from .course_generation import CourseWorkerService, RuntimeFactory
from .domain import CodeLearnerError
from .store import LearnerStore

ProgressCallback = Callable[[dict[str, object]], None]
ACTIVE_STATES = frozenset({"pending", "generating"})


class ModuleCourseScheduler:
    """Generate independent Module courses with a bounded worker pool."""

    def __init__(
        self,
        root: Path | str,
        *,
        runtime_factory: RuntimeFactory | None = None,
        worker_count: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = LearnerStore(self.root)
        self.runtime_factory = runtime_factory
        requested = worker_count or int(
            os.environ.get("ELECTROBOY_CODE_LEARNER_WORKERS", "3")
        )
        self.worker_count = max(1, min(8, requested))
        self.progress_callback = progress_callback
        self._queue: queue.PriorityQueue[tuple[int, int, str]] = queue.PriorityQueue()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._queued: set[str] = set()
        self._active: set[str] = set()
        self._sequence = 0
        self._started = False

    def start(self) -> dict[str, object]:
        module_ids = self._module_ids()
        if not module_ids:
            return module_generation_status(self.root)
        with self._lock:
            first_start = not self._started
            self._started = True
            if not self._threads:
                for index in range(min(self.worker_count, len(module_ids))):
                    thread = threading.Thread(
                        target=self._worker,
                        name=f"code-learner-module-{index}",
                        daemon=True,
                    )
                    self._threads.append(thread)
                    thread.start()
            for module_id in module_ids:
                if self.store.course_ready("module", module_id):
                    self._set_status(module_id, "ready")
                elif self._target_status(module_id) != "failed":
                    self._enqueue(module_id, 100)
        if first_start:
            self._emit("Background Module course generation started.")
        return module_generation_status(self.root)

    def prioritize(self, module_id: str) -> dict[str, object]:
        if module_id not in self._module_ids():
            raise CodeLearnerError(f"unknown Module target: {module_id}")
        if not self.store.course_ready("module", module_id):
            self._enqueue(module_id, 0)
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
            if status["status"] in {"complete", "complete_with_warnings", "idle"}:
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def _enqueue(self, module_id: str, priority: int) -> None:
        with self._lock:
            if module_id in self._queued or module_id in self._active:
                return
            self._sequence += 1
            self._queued.add(module_id)
            self._set_status(module_id, "pending")
            self._queue.put((priority, self._sequence, module_id))

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                _priority, _sequence, module_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                self._queued.discard(module_id)
                self._active.add(module_id)
            try:
                self._generate(module_id)
            finally:
                with self._lock:
                    self._active.discard(module_id)
                self._queue.task_done()

    def _generate(self, module_id: str) -> None:
        self._set_status(module_id, "generating")
        self._emit(f"Generating Module course {module_id}.", module_id)
        try:
            CourseWorkerService(
                self.root,
                runtime_factory=self.runtime_factory,
                cancel_event=self._stop,
                progress_callback=self.progress_callback,
            ).generate_module(module_id)
        except Exception as error:
            self._set_status(module_id, "failed", str(error))
            self._emit(
                f"Module course {module_id} failed: {error}",
                module_id,
                activity_kind="warning",
            )
            return
        self._set_status(module_id, "ready")
        self._emit(f"Module course {module_id} is ready.", module_id)

    def _module_ids(self) -> list[str]:
        return [
            str(module.get("eb_module_id") or "")
            for module in self.store.modules()
            if module.get("eb_module_id")
        ]

    def _target_status(self, module_id: str) -> str:
        targets = self.store.read_object(self.store.module_status_path).get(
            "targets"
        )
        if not isinstance(targets, dict):
            return "pending"
        target = targets.get(module_id)
        if not isinstance(target, dict):
            return "pending"
        return str(target.get("status") or "pending")

    def _set_status(self, module_id: str, status: str, error: str = "") -> None:
        with self._lock:
            payload = self.store.read_object(self.store.module_status_path)
            targets = payload.get("targets")
            targets = dict(targets) if isinstance(targets, dict) else {}
            targets[module_id] = {
                "status": status,
                "error": error,
                "updated_at": utc_now(),
            }
            self.store.write_state(
                self.store.module_status_path,
                {"targets": targets},
            )

    def _emit(
        self,
        message: str,
        module_id: str = "",
        *,
        activity_kind: str = "background",
    ) -> None:
        event = {
            "activity_kind": activity_kind,
            "phase": "module_courses",
            "percent": 100,
            "message": message,
            "scope_ids": [module_id] if module_id else [],
        }
        self.store.append_progress(event)
        if self.progress_callback is not None:
            self.progress_callback(event)


def module_generation_status(root: Path | str) -> dict[str, object]:
    store = LearnerStore(root)
    persisted = store.read_object(store.module_status_path)
    saved_targets = persisted.get("targets")
    saved_targets = saved_targets if isinstance(saved_targets, dict) else {}
    targets: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for module in store.modules():
        module_id = str(module.get("eb_module_id") or "")
        if not module_id:
            continue
        saved = saved_targets.get(module_id)
        saved = saved if isinstance(saved, dict) else {}
        status = (
            "ready"
            if store.course_ready("module", module_id)
            else str(saved.get("status") or "pending")
        )
        counts[status] = counts.get(status, 0) + 1
        targets.append(
            {
                "module_id": module_id,
                "status": status,
                "error": str(saved.get("error") or ""),
            }
        )
    if not targets:
        aggregate = "idle"
    elif counts.get("ready", 0) == len(targets):
        aggregate = "complete"
    elif any(counts.get(state, 0) for state in ACTIVE_STATES):
        aggregate = "running"
    else:
        aggregate = "complete_with_warnings"
    return {
        "status": aggregate,
        "total": len(targets),
        "pending": counts.get("pending", 0),
        "generating": counts.get("generating", 0),
        "ready": counts.get("ready", 0),
        "failed": counts.get("failed", 0),
        "targets": targets,
    }
