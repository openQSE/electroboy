from __future__ import annotations

from pathlib import Path

from code_learner_phase3_fixtures import build_catalog, build_course_records

from electroboy.service.app import ServiceState
from electroboy.service.registry import build_module_registry, build_workflow_registry
from electroboy.workflows.code_learner.phase3_courses import Phase3CourseService
from electroboy.workflows.code_learner.phase3_pipeline import (
    Phase3InitializationPipeline,
)
from electroboy.workflows.code_learner.plugin import workflow as code_learner_workflow


def test_phase3_service_lists_modules_resolves_functions_and_opens_course(
    tmp_path: Path,
) -> None:
    controller, context_id, root = _controller(tmp_path)
    catalog = _activate_fixture(root)

    status = controller.initialization_status(context_id)
    modules = controller.modules(context_id)
    functions = controller.symbols(context_id, "function0")
    opened = controller.create_walkthrough(context_id, learning_mode="architecture")
    artifact = controller.course_artifact(
        context_id, "architecture", "architecture:current"
    )

    assert status["status"] == "initialized"
    assert status["initialization"]["completion_status"] == "complete"
    assert status["code_learner"]["learner_generation"] == "phase3"
    assert status["code_learner"]["phase3_initialized"] is True
    assert status["code_learner"]["phase3"]["manifests"]["source"]["count"] == 2
    assert status["code_learner"]["phase3"]["manifests"]["components"]["count"] == 2
    assert status["code_learner"]["phase3"]["manifests"]["modules"]["count"] == 2
    assert {item["id"] for item in modules["modules"]} == {
        item["id"] for item in catalog.modules.modules
    }
    assert functions["resolution"]["status"] == "exact"
    assert functions["resolution"]["symbol"]["file_path"] == "file0.py"
    assert opened["walkthrough"]["id"] == ("course:architecture:architecture:current")
    assert opened["source"]["path"] == "file0.py"
    assert opened["course_navigation"]["generation"] == "phase3"
    assert artifact["markdown_path"].endswith("phase3/courses/architecture.md")


def test_phase3_warning_completion_is_active_and_visible(tmp_path: Path) -> None:
    controller, context_id, root = _controller(tmp_path)
    catalog, pipeline = _ready_fixture(root)
    pipeline._warning("module_knowledge", "optional module details are incomplete")
    pipeline._activate(catalog.source.revision)

    status = controller.initialization_status(context_id)

    assert status["status"] == "initialized"
    assert status["initialization"]["completion_status"] == ("complete_with_warnings")
    assert status["initialization"]["warning_count"] == 1
    assert status["code_learner"]["phase3_initialized"] is True


def test_phase3_failed_result_disables_course_payload_and_reports_recovery(
    tmp_path: Path,
) -> None:
    controller, context_id, root = _controller(tmp_path)
    catalog = build_catalog(root)
    pipeline = Phase3InitializationPipeline(root, eager_function_budget=0)
    pipeline._active_stage = "architecture_knowledge"
    pipeline._fail(catalog.source.revision, RuntimeError("missing architecture"))

    status = controller.initialization_status(context_id)

    assert status["status"] == "failed"
    assert status["initialization"]["completion_status"] == "failed"
    assert status["initialization"]["failed_scope"] == "architecture_knowledge"
    assert "missing architecture" in status["initialization"]["recovery_action"]
    assert status["code_learner"]["phase3_initialized"] is False
    assert status["code_learner"]["analysis"] is None


def test_phase3_clear_cache_removes_backend_and_visible_course_state(
    tmp_path: Path,
) -> None:
    controller, context_id, root = _controller(tmp_path)
    _activate_fixture(root)
    controller.create_walkthrough(context_id, learning_mode="architecture")

    cleared = controller.clear_course_cache(context_id)

    assert cleared["status"] == "cache_cleared"
    assert cleared["initialization"]["status"] == "idle"
    assert cleared["code_learner"]["current_walkthrough"] is None
    assert cleared["code_learner"]["walkthroughs"] == []
    assert cleared["code_learner"]["source"] is None
    assert (root / ".electroboy/code-learner/phase3").exists() is False


def _controller(tmp_path: Path):
    root = tmp_path / "repository"
    root.mkdir()
    state = ServiceState(
        tmp_path / "service",
        workflow_registry=build_workflow_registry(
            build_module_registry(), (code_learner_workflow(),)
        ),
    )
    context_id = str(state.create_context(workflow_id="code-learner")["context_id"])
    controller = state.workflow_controller("code-learner")
    controller.open_project(context_id, str(root))
    return controller, context_id, root


def _activate_fixture(root: Path):
    catalog, pipeline = _ready_fixture(root)
    pipeline._activate(catalog.source.revision)
    return catalog


def _ready_fixture(root: Path):
    catalog = build_catalog(root)
    pipeline = Phase3InitializationPipeline(root, eager_function_budget=0)
    pipeline.store.write_jsonl(
        pipeline.architecture.path,
        [{"id": "knowledge:architecture"}],
    )
    for module in catalog.modules.modules:
        module_id = str(module["id"])
        pipeline.store.write_jsonl(
            pipeline.module_knowledge._path(module_id),
            [{"id": f"knowledge:{module_id}"}],
        )
    courses = Phase3CourseService(root, store=pipeline.store)
    courses.save(
        "architecture",
        "architecture:current",
        build_course_records(catalog, "architecture", "architecture:current"),
    )
    for index, module in enumerate(catalog.modules.modules):
        module_id = str(module["id"])
        courses.save(
            "module",
            module_id,
            build_course_records(catalog, "module", module_id, source_index=index),
        )
    return catalog, pipeline
