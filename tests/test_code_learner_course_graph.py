from __future__ import annotations

from pathlib import Path

from electroboy.workflows.code_learner.course_graph import (
    CourseGraph,
    CourseNavigator,
)
from electroboy.workflows.code_learner.course_projection import (
    phase2_analysis_payload,
    project_navigation,
)
from electroboy.workflows.code_learner.domain import repository_revision
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore


def _source(line: int = 1) -> dict[str, object]:
    return {
        "path": "src/app.py",
        "start_line": line,
        "end_line": line,
        "reason": "Navigation source evidence.",
    }


def _seed(root: Path) -> KnowledgeStore:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text(
        "def start():\n    return run()\ndef run():\n    return 1\n", encoding="utf-8"
    )
    revision = repository_revision(root)
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-graph",
        "repository_revision": revision,
    }
    store = KnowledgeStore(root)
    store.save_knowledge(
        [
            {
                **common,
                "record_type": "knowledge_manifest",
                "id": "knowledge.manifest",
                "repository_name": "graph",
                "scope_path": ".",
                "status": "validated",
                "entity_count": 2,
                "relationship_count": 0,
                "flow_count": 0,
                "diagnostic_count": 0,
            },
            {
                **common,
                "record_type": "entity",
                "id": "module.app",
                "kind": "module",
                "name": "App",
                "summary": "Application module.",
                "source_refs": [_source()],
                "confidence": "high",
            },
            {
                **common,
                "record_type": "entity",
                "id": "symbol.run",
                "kind": "symbol",
                "name": "run",
                "summary": "Runs the application.",
                "parent_id": "module.app",
                "source_refs": [_source(3)],
                "confidence": "high",
            },
        ]
    )
    architecture = _course(
        common,
        "architecture",
        "repository.root",
        "course.architecture.repository.root",
        deep_dive_ids=("course.module.module.app", "course.function.symbol.run"),
    )
    module = _course(
        common,
        "module",
        "module.app",
        "course.module.module.app",
        deep_dive_ids=("course.function.symbol.run",),
    )
    store.save_course("architecture", "repository.root", architecture)
    store.save_course("module", "module.app", module)
    store.record_course_status(
        "architecture", "repository.root", "ready", path="courses/architecture.jsonl"
    )
    store.record_course_status(
        "module", "module.app", "ready", path="courses/modules/module.app.jsonl"
    )
    store.record_course_status("function", "symbol.run", "generating")
    return store


def _course(
    common: dict[str, object],
    mode: str,
    scope_id: str,
    document_id: str,
    *,
    deep_dive_ids: tuple[str, ...],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "document",
            "id": document_id,
            "title": f"{mode.title()} Course",
            "course_mode": mode,
            "scope_id": scope_id,
            "status": "ready",
        }
    ]
    for index, title in enumerate(("Overview", "Flow"), start=1):
        section_id = f"{document_id}.section-{index}"
        records.append(
            {
                **common,
                "record_type": "section",
                "id": section_id,
                "parent_id": document_id,
                "heading_level": 2,
                "order": index,
                "title": title,
                "body": f"{title} material.",
                "detail_level": mode,
                "previous_section_id": (
                    f"{document_id}.section-{index - 1}" if index > 1 else None
                ),
                "next_section_id": (
                    f"{document_id}.section-{index + 1}" if index < 2 else None
                ),
                "return_section_id": None,
                "deep_dive_ids": list(deep_dive_ids) if index == 2 else [],
                "knowledge_entity_ids": ["module.app"],
                "relationship_ids": [],
                "runtime_flow_ids": [],
                "diagnostic_ids": [],
                "related_module_ids": ["module.app"],
                "related_symbol_ids": ["symbol.run"],
                "prerequisite_section_ids": [],
                "source_refs": [_source(index)],
                "confidence": "high",
                "diagrams": [],
            }
        )
    return records


def test_graph_projects_layers_horizontal_order_and_target_states(
    tmp_path: Path,
) -> None:
    store = _seed(tmp_path)
    graph = CourseGraph.from_store(store)

    first = graph.first_section("course.architecture.repository.root")
    assert first.next_id == "course.architecture.repository.root.section-2"
    assert graph.node(first.next_id).previous_id == first.id
    assert graph.target_state("course.module.module.app") == "ready"
    assert graph.target_state("course.function.symbol.run") == "generating"
    assert graph.target_state("course.module.missing") == "missing"

    store.record_course_status("module", "module.app", "stale")
    store.record_course_status("function", "symbol.run", "failed")
    refreshed = CourseGraph.from_store(store)
    assert refreshed.target_state("course.module.module.app") == "stale"
    assert refreshed.target_state("course.function.symbol.run") == "failed"


def test_navigation_preserves_horizontal_position_and_code_view_on_return(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)
    navigator = CourseNavigator(tmp_path)
    opened = navigator.open("course.architecture.repository.root")
    assert opened["current"]["id"].endswith("section-1")
    navigator.update_code_view(
        {
            "path": "src/app.py",
            "selected_start_line": 1,
            "selected_end_line": 1,
            "visible_start_line": 1,
            "visible_end_line": 4,
        }
    )

    moved = navigator.move("next")
    assert moved["current"]["id"].endswith("section-2")
    assert moved["navigation"]["code_view"]["visible_end_line"] == 4
    dived = navigator.deep_dive("course.module.module.app")
    assert dived["current"]["course_id"] == "course.module.module.app"
    assert len(dived["breadcrumbs"]) == 2

    returned = navigator.back()
    assert returned["current"]["id"].endswith("section-2")
    assert returned["navigation"]["code_view"]["visible_end_line"] == 4

    reloaded = CourseNavigator(tmp_path).state()
    assert reloaded["current"]["id"] == returned["current"]["id"]


def test_deep_dive_reports_generating_target_without_losing_location(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)
    navigator = CourseNavigator(tmp_path)
    navigator.open("course.architecture.repository.root")
    navigator.move("next")

    result = navigator.deep_dive("course.function.symbol.run")

    assert result["current"]["id"].endswith("section-2")
    assert result["navigation"]["target"] == {
        "id": "course.function.symbol.run",
        "status": "generating",
    }


def test_phase2_projection_supplies_menu_slide_source_and_artifact_models(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)
    navigation = CourseNavigator(tmp_path).open(
        "course.architecture.repository.root",
        "course.architecture.repository.root.section-2",
    )

    analysis = phase2_analysis_payload(tmp_path)
    payload = project_navigation(tmp_path, navigation)

    assert analysis["modules"] == [
        {
            "id": "module.app",
            "path": "module.app",
            "name": "App",
            "summary": "Application module.",
            "file_count": 1,
            "source_refs": [_source()],
        }
    ]
    assert analysis["symbols"][0]["id"] == "symbol.run"
    assert payload["walkthrough"]["current_step_id"].endswith("section-2")
    assert payload["walkthrough"]["steps"][1]["deep_dive_ids"] == [
        "course.module.module.app",
        "course.function.symbol.run",
    ]
    assert payload["source"]["path"] == "src/app.py"
    assert payload["source"]["active_start_line"] == 2
    assert payload["course_artifact"] == {
        "mode": "architecture",
        "scope_id": "repository.root",
        "jsonl_path": ".electroboy/code-learner/courses/architecture.jsonl",
        "markdown_path": ".electroboy/code-learner/courses/architecture.md",
        "title": "Architecture Course",
    }
