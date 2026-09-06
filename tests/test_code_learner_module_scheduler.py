from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.background_courses import (
    ModuleCourseScheduler,
    module_generation_status,
)
from electroboy.workflows.code_learner.store import LearnerStore


class ModuleRuntime:
    def __init__(self, root: Path, tracker: dict[str, object]) -> None:
        self.root = root
        self.tracker = tracker

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        match = re.search(
            r"Module course for this module ID:\n([^\n]+)",
            invocation.prompt,
        )
        module_id = match.group(1).strip()
        with self.tracker["lock"]:
            self.tracker["active"] += 1
            self.tracker["peak"] = max(self.tracker["peak"], self.tracker["active"])
            self.tracker["prompts"].append(invocation.prompt)
        time.sleep(0.03)
        if module_id == "mod-002":
            result = AgentResult(False, "failed", error="worker failed")
        else:
            _write_course(LearnerStore(self.root), module_id)
            result = AgentResult(True, "complete")
        with self.tracker["lock"]:
            self.tracker["active"] -= 1
        return result


def _write_course(store: LearnerStore, module_id: str) -> None:
    root = store.course_directory("module", module_id)
    lesson_dir = root / "01.Structure"
    lesson_dir.mkdir(parents=True, exist_ok=True)
    store.course_index_path("module", module_id).write_text(
        json.dumps(
            {
                "course_type": "module",
                "course_title": module_id,
                "concepts": [
                    {
                        "directory_name": "01.Structure",
                        "concept_title": "Structure",
                        "lessons": [
                            {
                                "file_name": "01.Overview.jsonl",
                                "lesson_title": "Overview",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (lesson_dir / "01.Overview.jsonl").write_text(
        json.dumps({"record_type": "document", "title": "Overview"})
        + "\n"
        + json.dumps(
            {
                "record_type": "section",
                "id": f"{module_id}-overview",
                "title": "Overview",
                "body": "Module details.",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_scheduler_runs_bounded_workers_and_isolates_failures(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    store = LearnerStore(root)
    store.initialize_layout()
    store.components_path.write_text("[]", encoding="utf-8")
    store.modules_path.write_text(
        json.dumps(
            [
                {
                    "eb_module_id": f"mod-00{index}",
                    "ai_module_name": f"Module {index}",
                    "ai_comp_list": [],
                }
                for index in range(1, 4)
            ]
        ),
        encoding="utf-8",
    )
    tracker = {
        "active": 0,
        "peak": 0,
        "prompts": [],
        "lock": threading.Lock(),
    }
    scheduler = ModuleCourseScheduler(
        root,
        worker_count=2,
        runtime_factory=lambda _role, _root: ModuleRuntime(root, tracker),
    )

    initial = scheduler.start()
    assert initial["status"] == "running"
    assert scheduler.wait(timeout=2)

    status = module_generation_status(root)
    assert status["ready"] == 2
    assert status["failed"] == 1
    assert status["status"] == "complete_with_warnings"
    assert tracker["peak"] == 2
    assert len(tracker["prompts"]) == 3
    assert all(str(store.raw_knowledge_root) in prompt for prompt in tracker["prompts"])
    assert store.course_ready("module", "mod-001")
    assert store.course_ready("module", "mod-003")
    scheduler.stop()
