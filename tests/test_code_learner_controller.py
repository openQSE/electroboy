from __future__ import annotations

import json
import time
from pathlib import Path

from electroboy.service.app import ServiceState
from electroboy.service.registry import build_module_registry, build_workflow_registry
from electroboy.workflows.code_learner import controller as controller_module
from electroboy.workflows.code_learner.course_generation import (
    CourseGenerationCancelled,
)
from electroboy.workflows.code_learner.plugin import workflow
from electroboy.workflows.code_learner.store import LearnerStore


def _controller(tmp_path: Path):
    root = tmp_path / "sample-repository"
    root.mkdir()
    (root / "core.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    state = ServiceState(
        tmp_path / "service",
        workflow_registry=build_workflow_registry(
            build_module_registry(),
            (workflow(),),
        ),
    )
    context_id = str(state.create_context(workflow_id="code-learner")["context_id"])
    controller = state.workflow_controller("code-learner")
    opened = controller.open_project(context_id, str(root))
    context_id = str(opened["context_id"])
    return controller, context_id, root


def _write_course(store: LearnerStore, mode: str, scope_id: str = "") -> None:
    root = store.course_directory(mode, scope_id)
    concept = root / "01.System"
    concept.mkdir(parents=True, exist_ok=True)
    store.course_index_path(mode, scope_id).write_text(
        json.dumps(
            {
                "course_type": mode,
                "course_title": f"{mode.title()} Course",
                "concepts": [
                    {
                        "directory_name": "01.System",
                        "concept_title": "System",
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
    records = [
        {
            "record_type": "document",
            "id": f"{mode}-overview",
            "title": "Overview",
        },
        {
            "record_type": "section",
            "id": f"{mode}-purpose",
            "parent_id": f"{mode}-overview",
            "order": 10,
            "title": "Purpose",
            "body": "## Purpose\n\n```mermaid\nflowchart LR\nA --> B\n```",
            "source_refs": [
                {"path": "core.py", "start_line": 1, "end_line": 2}
            ],
        },
    ]
    (concept / "01.Overview.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def _seed_discovery(store: LearnerStore) -> None:
    store.initialize_layout()
    store.components_path.write_text(
        json.dumps(
            [
                {
                    "eb_comp_id": "comp-001",
                    "ai_component_name": "Core",
                    "ai_file_list": ["core.py"],
                }
            ]
        ),
        encoding="utf-8",
    )
    store.modules_path.write_text(
        json.dumps(
            [
                {
                    "eb_module_id": "mod-001",
                    "ai_module_name": "Core module",
                    "ai_comp_list": ["comp-001"],
                }
            ]
        ),
        encoding="utf-8",
    )


def test_controller_projects_direct_architecture_and_clears_cache(
    tmp_path: Path,
) -> None:
    controller, context_id, root = _controller(tmp_path)
    store = LearnerStore(root)
    _seed_discovery(store)
    _write_course(store, "architecture")
    store.save_status(status="initialized", completion_status="complete")

    modules = controller.modules(context_id)
    opened = controller.create_walkthrough(
        context_id,
        learning_mode="architecture",
    )
    question = controller.prepare_question(
        context_id,
        "How does this flow work?",
        str(opened["walkthrough"]["id"]),
        selected_file_path="core.py",
        selected_start_line=1,
        selected_end_line=2,
    )

    assert modules["modules"][0]["path"] == "mod-001"
    assert opened["walkthrough"]["steps"][0]["explanation"].startswith("##")
    assert opened["course_artifact"]["path"].endswith("01.Overview.jsonl")
    assert "markdown_path" not in opened["course_artifact"]
    assert question["prompt"] == "How does this flow work?"
    context = store.read_object(store.tutor_context_path)
    assert context["source"]["path"] == "core.py"
    assert context["source"]["selected_start_line"] == 1

    cleared = controller.clear_course_cache(context_id)
    assert cleared["status"] == "cache_cleared"
    assert cleared["code_learner"]["initialized"] is False
    assert cleared["code_learner"]["current_walkthrough"] is None
    assert not store.course_root.exists()


def test_function_text_is_not_resolved_before_independent_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller, context_id, root = _controller(tmp_path)
    store = LearnerStore(root)
    _seed_discovery(store)
    _write_course(store, "architecture")
    generated: list[tuple[str, str]] = []

    class Worker:
        def __init__(self, worker_root: Path) -> None:
            assert Path(worker_root) == root

        def generate_function(self, symbol: str, scope_id: str) -> Path:
            generated.append((symbol, scope_id))
            _write_course(store, "function", scope_id)
            return store.course_index_path("function", scope_id)

    monkeypatch.setattr(controller_module, "CourseWorkerService", Worker)

    resolution = controller.resolve_function_course(context_id, "Widget::run(int)")
    built = controller.build_function_course(context_id, "Widget::run(int)")
    opened = controller.create_walkthrough(
        context_id,
        learning_mode="function",
        target="Widget::run(int)",
    )

    assert resolution["status"] == "resolved"
    assert resolution["symbol"]["name"] == "Widget::run(int)"
    assert generated == [("Widget::run(int)", built["course"]["scope_id"])]
    assert opened["walkthrough"]["learning_mode"] == "function"


def test_initialization_job_activates_architecture_without_content_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller, context_id, root = _controller(tmp_path)

    class Initialization:
        def __init__(self, init_root: Path, *, cancel_event) -> None:
            self.root = Path(init_root)
            self.cancel_event = cancel_event

        def run(self) -> None:
            store = LearnerStore(self.root)
            _seed_discovery(store)
            store.modules_path.write_text("[]", encoding="utf-8")
            _write_course(store, "architecture")
            store.save_status(
                status="initialized",
                phase="complete",
                percent=100,
                completion_status="complete",
            )

    monkeypatch.setattr(controller_module, "CourseGenerationService", Initialization)

    controller.initialize(context_id, mode="continue")
    completed = controller.wait_for_initialization(context_id, timeout=2)

    assert completed["status"] == "initialized"
    assert completed["code_learner"]["initialized"] is True
    assert completed["initialization"]["choice_required"] is False


def test_abort_stops_active_initialization_and_preserves_continue_choice(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller, context_id, _root = _controller(tmp_path)

    class BlockingInitialization:
        def __init__(self, _root: Path, *, cancel_event) -> None:
            self.cancel_event = cancel_event

        def run(self) -> None:
            while not self.cancel_event.wait(0.01):
                pass
            raise CourseGenerationCancelled("aborted")

    monkeypatch.setattr(
        controller_module,
        "CourseGenerationService",
        BlockingInitialization,
    )

    started = controller.initialize(context_id)
    assert started["status"] == "initializing"
    controller.abort_initialization(context_id)
    deadline = time.monotonic() + 2
    stopped = controller.initialization_status(context_id)
    while stopped["initialization"]["status"] != "aborted":
        assert time.monotonic() < deadline
        time.sleep(0.01)
        stopped = controller.initialization_status(context_id)

    assert stopped["status"] == "uninitialized"
    assert stopped["initialization"]["choice_required"] is True
