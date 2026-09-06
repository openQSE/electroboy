from __future__ import annotations

import threading
import time
from pathlib import Path

from code_learner_phase3_fixtures import build_catalog

from electroboy.workflows.code_learner.background_courses import (
    ModuleCourseScheduler,
    module_generation_status,
)
from electroboy.workflows.code_learner.phase3_courses import Phase3CourseService


class RecordingScheduler(ModuleCourseScheduler):
    def __init__(self, *args, fail_module: str = "", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fail_module = fail_module
        self.calls: list[str] = []
        self.running = 0
        self.maximum_running = 0
        self.recording_lock = threading.Lock()

    def _generate_target(self, module_id, *, knowledge, courses) -> None:
        with self.recording_lock:
            self.calls.append(module_id)
            self.running += 1
            self.maximum_running = max(self.maximum_running, self.running)
        try:
            self.courses.record_status(
                "module", module_id, "generating_knowledge"
            )
            time.sleep(0.04)
            if module_id == self.fail_module:
                self.courses.record_status(
                    "module", module_id, "failed", error="fixture failure"
                )
            else:
                self.courses.record_status("module", module_id, "building_course")
                self.courses.record_status("module", module_id, "ready")
        finally:
            with self.recording_lock:
                self.running -= 1


def test_scheduler_bounds_parallelism_and_suppresses_duplicate_jobs(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    scheduler = RecordingScheduler(tmp_path, worker_count=2)

    scheduler.start()
    scheduler.start()
    first_module = str(catalog.modules.modules[0]["id"])
    scheduler.prioritize(first_module)

    assert scheduler.wait(timeout=2)
    assert sorted(scheduler.calls) == sorted(
        str(module["id"]) for module in catalog.modules.modules
    )
    assert scheduler.maximum_running <= 2
    assert module_generation_status(tmp_path)["status"] == "complete"
    scheduler.stop()


def test_scheduler_recovers_unfinished_targets_without_rebuilding_ready_ones(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    module_ids = [str(module["id"]) for module in catalog.modules.modules]
    courses = Phase3CourseService(tmp_path)
    courses.record_status("module", module_ids[0], "ready")
    courses.record_status("module", module_ids[1], "generating_knowledge")
    scheduler = RecordingScheduler(tmp_path, worker_count=1)

    scheduler.start()

    assert scheduler.wait(timeout=2)
    assert scheduler.calls == [module_ids[1]]
    scheduler.stop()


def test_scheduler_preserves_failure_isolation_and_aggregate_warning(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    failed = str(catalog.modules.modules[0]["id"])
    scheduler = RecordingScheduler(tmp_path, worker_count=2, fail_module=failed)

    scheduler.start()

    assert scheduler.wait(timeout=2)
    status = module_generation_status(tmp_path)
    assert status["status"] == "complete_with_warnings"
    assert status["failed"] == 1
    assert status["ready"] == len(catalog.modules.modules) - 1
    scheduler.stop()


def test_module_target_runs_knowledge_before_course(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path)
    module_id = str(catalog.modules.modules[0]["id"])
    scheduler = ModuleCourseScheduler(tmp_path, worker_count=1)
    events: list[tuple[str, str]] = []

    class Knowledge:
        def generate(self, target, *, analysis_run_id):
            events.append(("knowledge", scheduler._target_status(target)))
            return {"id": f"knowledge:{target}"}

    class Courses:
        def build(self, mode, target, *, analysis_run_id):
            events.append(("course", scheduler._target_status(target)))
            scheduler.courses.record_status("module", target, "ready")
            return {"document_id": f"course:module:{target}"}

    scheduler._generate_target(module_id, knowledge=Knowledge(), courses=Courses())

    assert events == [
        ("knowledge", "generating_knowledge"),
        ("course", "building_course"),
    ]
    assert scheduler._target_status(module_id) == "ready"
