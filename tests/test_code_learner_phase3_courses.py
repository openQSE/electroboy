from __future__ import annotations

import json
from pathlib import Path

import pytest
from code_learner_phase3_fixtures import build_catalog

from electroboy.adapters.base import AgentResult
from electroboy.workflows.code_learner.contracts import load_contract_schema
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.phase3_courses import (
    Phase3CourseNavigator,
    Phase3CourseService,
)


class FakeRuntime:
    def __init__(self, output: list[dict[str, object]]) -> None:
        self.output = output
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return AgentResult(True, "\n".join(json.dumps(item) for item in self.output))


class SequenceRuntime:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return AgentResult(True, self.outputs.pop(0))


def _records(catalog, mode: str, scope_id: str) -> list[dict[str, object]]:
    document_id = f"course:{mode}:{scope_id}"
    module_ids = [str(item["id"]) for item in catalog.modules.modules]
    symbol_ids = [
        str(item["symbols"][0]["canonical_key"])
        for item in catalog.components.components
    ]
    relationship_ids = [str(item["id"]) for item in catalog.relationships]
    target = (
        f"course:module:{module_ids[0]}"
        if mode == "architecture"
        else f"course:function:{symbol_ids[0]}"
    )
    component_id = str(catalog.components.components[0]["id"])
    return [
        {
            "schema_version": 1,
            "record_type": "document",
            "id": document_id,
            "analysis_run_id": "run-1",
            "repository_revision": catalog.source.revision,
            "title": f"{mode.title()} Course",
            "course_mode": mode,
            "scope_id": scope_id,
            "status": "ready",
            "coverage_topics": ["purpose", "flow"],
        },
        {
            "schema_version": 1,
            "record_type": "section",
            "id": f"{document_id}:section:1",
            "analysis_run_id": "run-1",
            "repository_revision": catalog.source.revision,
            "parent_id": document_id,
            "heading_level": 2,
            "order": 1,
            "title": "System purpose",
            "body": "Purpose and evidence.\n\n```mermaid\nflowchart LR\nA --> B\n```",
            "topic": "purpose",
            "detail_level": mode,
            "confidence": "high",
            "previous_section_id": None,
            "next_section_id": f"{document_id}:section:2",
            "return_section_id": None,
            "deep_dive_ids": [target],
            "deep_dive_targets": [
                {"target_type": "component", "target_id": component_id}
            ],
            "prerequisite_section_ids": [],
            "knowledge_entity_ids": [module_ids[0]],
            "relationship_ids": relationship_ids,
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": [module_ids[0]],
            "related_symbol_ids": [symbol_ids[0]],
            "source_refs": [
                {
                    "path": "file0.py",
                    "start_line": 1,
                    "end_line": 2,
                    "symbol": "function0",
                    "reason": "Primary source evidence.",
                    "revision": catalog.source.revision,
                }
            ],
            "diagrams": [
                {
                    "id": "diagram:course",
                    "type": "flowchart",
                    "question": "How does control move?",
                }
            ],
        },
        {
            "schema_version": 1,
            "record_type": "section",
            "id": f"{document_id}:section:2",
            "analysis_run_id": "run-1",
            "repository_revision": catalog.source.revision,
            "parent_id": document_id,
            "heading_level": 2,
            "order": 2,
            "title": "Implementation flow",
            "body": "The implementation flow uses the second source file.",
            "topic": "flow",
            "detail_level": mode,
            "confidence": "verified",
            "previous_section_id": f"{document_id}:section:1",
            "next_section_id": None,
            "return_section_id": f"{document_id}:section:1",
            "deep_dive_ids": [],
            "deep_dive_targets": [],
            "prerequisite_section_ids": [f"{document_id}:section:1"],
            "knowledge_entity_ids": [module_ids[-1]],
            "relationship_ids": relationship_ids,
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": [module_ids[-1]],
            "related_symbol_ids": [symbol_ids[-1]],
            "source_refs": [
                {
                    "path": "file1.py",
                    "start_line": 1,
                    "end_line": 2,
                    "symbol": "function1",
                    "reason": "Secondary source evidence.",
                    "revision": catalog.source.revision,
                }
            ],
            "diagrams": [],
        },
    ]


def test_phase3_course_uses_shared_renderer_and_preserves_structured_source(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = Phase3CourseService(tmp_path, store=catalog.store)
    scope = "architecture:current"

    path, rendered = service.save(
        "architecture", scope, _records(catalog, "architecture", scope)
    )

    assert path.is_file()
    assert Path(tmp_path, rendered.markdown_path).is_file()
    markdown = Path(tmp_path, rendered.markdown_path).read_text(encoding="utf-8")
    assert "# Architecture Course" in markdown
    assert ". System purpose" in markdown
    assert "```mermaid" in markdown
    assert service.target_status("course:architecture:architecture:current") == "ready"


def test_phase3_course_preserves_ai_authored_knowledge_links(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path)
    service = Phase3CourseService(tmp_path, store=catalog.store)
    scope = "architecture:current"
    records = _records(catalog, "architecture", scope)
    records[1]["runtime_flow_ids"] = ["flow:ai-authored"]
    records[1]["knowledge_entity_ids"] = ["entity:ai-authored"]

    service.save("architecture", scope, records)

    loaded = service.load("architecture", scope)
    assert loaded[1]["runtime_flow_ids"] == ["flow:ai-authored"]
    assert loaded[1]["knowledge_entity_ids"] == ["entity:ai-authored"]


def test_course_schema_defines_deep_dive_target_shape() -> None:
    schema = load_contract_schema("course")

    target = schema["$defs"]["deepDiveTarget"]
    assert target["required"] == ["target_type", "target_id"]
    assert schema["properties"]["deep_dive_targets"]["items"] == {
        "$ref": "#/$defs/deepDiveTarget"
    }


def test_course_navigation_moves_horizontally_and_restores_vertical_position(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = Phase3CourseService(tmp_path, store=catalog.store)
    architecture_scope = "architecture:current"
    module_scope = str(catalog.modules.modules[0]["id"])
    service.save(
        "architecture",
        architecture_scope,
        _records(catalog, "architecture", architecture_scope),
    )
    service.save("module", module_scope, _records(catalog, "module", module_scope))
    navigator = Phase3CourseNavigator(tmp_path, service=service)

    opened = navigator.open("architecture", architecture_scope)
    first_section = opened["current"]["section_id"]
    assert opened["code_view"]["path"] == "file0.py"
    moved = navigator.move("next")
    assert moved["code_view"]["path"] == "file1.py"
    navigator.move("previous")
    target = f"course:module:{module_scope}"
    descended = navigator.deep_dive(target)
    assert descended["current"]["mode"] == "module"
    restored = navigator.back()
    assert restored["current"]["section_id"] == first_section
    assert restored["code_view"]["path"] == "file0.py"
    reloaded = Phase3CourseNavigator(tmp_path, service=service).state()
    assert reloaded["current"] == restored["current"]


def test_navigation_reports_missing_and_all_explicit_target_states(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = Phase3CourseService(tmp_path, store=catalog.store)
    scope = "architecture:current"
    records = _records(catalog, "architecture", scope)
    symbol_id = str(catalog.components.components[0]["symbols"][0]["canonical_key"])
    missing_target = f"course:function:{symbol_id}"
    records[1]["deep_dive_ids"] = [missing_target]
    service.save("architecture", scope, records)
    navigator = Phase3CourseNavigator(tmp_path, service=service)
    navigator.open("architecture", scope)

    assert navigator.deep_dive(missing_target)["target"]["status"] == "missing"
    for status in ("generating", "stale", "failed", "unresolved"):
        service.record_status("function", symbol_id, status)
        assert service.target_status(missing_target) == status


def test_course_preserves_unknown_links_but_rejects_cross_level_navigation(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = Phase3CourseService(tmp_path, store=catalog.store)
    scope = "architecture:current"
    records = _records(catalog, "architecture", scope)
    records[1]["deep_dive_ids"] = ["course:module:missing"]
    records[1]["deep_dive_targets"] = [
        {"target_type": "function", "target_id": "course:function:missing"}
    ]
    records[1]["related_module_ids"] = ["module:ai-authored"]
    records[1]["related_symbol_ids"] = ["function:file.py#ai_authored"]

    service.save("architecture", scope, records)
    loaded = service.load("architecture", scope)
    assert loaded[1]["deep_dive_ids"] == ["course:module:missing"]
    assert loaded[1]["deep_dive_targets"] == [
        {"target_type": "function", "target_id": "course:function:missing"}
    ]
    assert loaded[1]["related_module_ids"] == ["module:ai-authored"]
    assert loaded[1]["related_symbol_ids"] == ["function:file.py#ai_authored"]

    records = _records(catalog, "architecture", scope)
    records[1]["detail_level"] = "module"
    with pytest.raises(CodeLearnerError, match="detail level"):
        service.save("architecture", scope, records)


def test_course_build_prompt_uses_phase3_manifests_without_restarting_discovery(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    catalog.store.write_jsonl(
        catalog.store.knowledge_root / "architecture.jsonl",
        [{"id": "architecture:current"}],
    )
    records = _records(catalog, "architecture", "architecture:current")
    runtime = FakeRuntime(records)
    service = Phase3CourseService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: runtime,
    )

    result = service.build(
        "architecture", "architecture:current", analysis_run_id="run-1"
    )

    assert result["record_count"] == 3
    prompt = runtime.invocations[0].prompt
    assert "Component manifest" in prompt
    assert "Module manifest" in prompt
    assert "Scoped layered knowledge" in prompt
    assert "Do not restart discovery" in prompt
    assert "do not return `knowledge_request`" in prompt


def test_course_contract_failure_is_not_retried(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    catalog.store.write_jsonl(
        catalog.store.knowledge_root / "architecture.jsonl",
        [{"id": "architecture:current"}],
    )
    records = _records(catalog, "architecture", "architecture:current")
    invalid = json.dumps(
        {
            "schema_version": 1,
            "record_type": "knowledge_request",
            "id": "request:course",
            "analysis_run_id": "run-1",
            "repository_revision": catalog.source.revision,
        }
    )
    valid = "\n".join(json.dumps(item) for item in records)
    runtime = SequenceRuntime([invalid, valid])
    service = Phase3CourseService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: runtime,
    )

    with pytest.raises(CodeLearnerError, match="Architecture course failed"):
        service.build("architecture", "architecture:current", analysis_run_id="run-1")

    assert len(runtime.invocations) == 1
    assert service.target_status("course:architecture:architecture:current") == "failed"


def test_malformed_course_output_is_retried(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path)
    catalog.store.write_jsonl(
        catalog.store.knowledge_root / "architecture.jsonl",
        [{"id": "architecture:current"}],
    )
    records = _records(catalog, "architecture", "architecture:current")
    valid = "\n".join(json.dumps(item) for item in records)
    runtime = SequenceRuntime(['{"record_type":"document"', valid])
    service = Phase3CourseService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: runtime,
    )

    result = service.build(
        "architecture", "architecture:current", analysis_run_id="run-1"
    )

    assert result["record_count"] == len(records)
    assert len(runtime.invocations) == 2
    assert "Previous course output error" in runtime.invocations[1].prompt
    assert service.target_status(result["document_id"]) == "ready"


def test_course_contract_failures_end_in_failed_status(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path)
    catalog.store.write_jsonl(
        catalog.store.knowledge_root / "architecture.jsonl",
        [{"id": "architecture:current"}],
    )
    invalid = json.dumps({"record_type": "knowledge_request"})
    runtime = SequenceRuntime([invalid, invalid])
    service = Phase3CourseService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: runtime,
    )

    with pytest.raises(CodeLearnerError, match="Architecture course failed"):
        service.build("architecture", "architecture:current", analysis_run_id="run-1")

    assert len(runtime.invocations) == 1
    document_id = "course:architecture:architecture:current"
    assert service.target_status(document_id) == "failed"
