from __future__ import annotations

from pathlib import Path

from electroboy.structured_artifacts import (
    markdown_to_artifact_records,
    render_artifact_markdown,
)
from electroboy.workflows.code_learner.course_artifacts import render_saved_course
from electroboy.workflows.code_learner.domain import repository_revision
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore


def _source() -> dict[str, object]:
    return {
        "path": "README.md",
        "start_line": 1,
        "end_line": 1,
        "reason": "Defines the fixture.",
    }


def _course(revision: str) -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-course",
        "repository_revision": revision,
    }
    return [
        {
            **common,
            "record_type": "document",
            "id": "course.architecture",
            "title": "Architecture Course",
            "course_mode": "architecture",
            "scope_id": "repository.root",
            "status": "ready",
        },
        {
            **common,
            "record_type": "section",
            "id": "course.architecture.components",
            "parent_id": "course.architecture",
            "heading_level": 2,
            "order": 1,
            "title": "Components",
            "body": (
                "| Component | Role |\n| --- | --- |\n| App | Coordinates |\n\n"
                "```mermaid\nflowchart LR\n  Entry --> App\n```"
            ),
            "detail_level": "architecture",
            "previous_section_id": None,
            "next_section_id": "course.architecture.sequence",
            "deep_dive_ids": ["course.module.app"],
            "knowledge_entity_ids": ["module.app"],
            "relationship_ids": [],
            "runtime_flow_ids": [],
            "related_module_ids": ["module.app"],
            "related_symbol_ids": [],
            "prerequisite_section_ids": [],
            "source_refs": [_source()],
            "confidence": "high",
            "diagrams": [
                {
                    "id": "diagram.components",
                    "type": "flowchart",
                    "question": "How do components connect?",
                }
            ],
        },
        {
            **common,
            "record_type": "section",
            "id": "course.architecture.sequence",
            "parent_id": "course.architecture.components",
            "heading_level": 3,
            "order": 2,
            "title": "Runtime Sequence",
            "body": "```mermaid\nsequenceDiagram\n  Entry->>App: start\n```",
            "detail_level": "architecture",
            "previous_section_id": "course.architecture.components",
            "next_section_id": None,
            "return_section_id": "course.architecture.components",
            "knowledge_entity_ids": ["module.app"],
            "relationship_ids": [],
            "runtime_flow_ids": ["flow.main"],
            "related_module_ids": ["module.app"],
            "related_symbol_ids": [],
            "prerequisite_section_ids": ["course.architecture.components"],
            "source_refs": [_source()],
            "confidence": "verified",
            "diagrams": [
                {
                    "id": "diagram.sequence",
                    "type": "sequenceDiagram",
                    "question": "How does startup proceed?",
                }
            ],
        },
    ]


def _knowledge(root: Path) -> KnowledgeStore:
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    revision = repository_revision(root)
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-course",
        "repository_revision": revision,
    }
    store = KnowledgeStore(root)
    store.save_knowledge(
        [
            {
                **common,
                "record_type": "knowledge_manifest",
                "id": "knowledge.manifest",
                "repository_name": "fixture",
                "scope_path": ".",
                "status": "validated",
                "entity_count": 1,
                "relationship_count": 0,
                "flow_count": 1,
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
                "record_type": "runtime_flow",
                "id": "flow.main",
                "name": "Startup",
                "kind": "startup",
                "participant_ids": ["module.app"],
                "steps": [
                    {
                        "order": 1,
                        "from_id": "module.app",
                        "to_id": "module.app",
                        "action": "Start",
                        "relationship_ids": [],
                    }
                ],
                "source_refs": [_source()],
                "confidence": "high",
            },
        ]
    )
    return store


def test_generic_course_renderer_preserves_hierarchy_markdown_and_mermaid() -> None:
    markdown = render_artifact_markdown("course", _course("revision"))

    assert "## course.architecture.components. Components" in markdown
    assert "### course.architecture.sequence. Runtime Sequence" in markdown
    assert "| Component | Role |" in markdown
    assert "```mermaid\nflowchart LR\n  Entry --> App\n```" in markdown
    assert "```mermaid\nsequenceDiagram\n  Entry->>App: start\n```" in markdown
    assert '**Diagrams:**\n```json\n[' in markdown


def test_course_markdown_import_preserves_ids_fields_and_fences() -> None:
    markdown = render_artifact_markdown("course", _course("revision"))
    records = markdown_to_artifact_records("course", markdown)

    document = records[0]
    components = records[1]
    assert document["id"] == "course.architecture"
    assert document["course_mode"] == "architecture"
    assert components["id"] == "course.architecture.components"
    assert components["knowledge_entity_ids"] == ["module.app"]
    assert components["diagrams"][0]["type"] == "flowchart"
    assert "```mermaid\nflowchart LR" in components["body"]


def test_saved_course_uses_safe_shared_artifact_paths(tmp_path: Path) -> None:
    store = _knowledge(tmp_path)
    revision = repository_revision(tmp_path)
    store.save_course("architecture", "repository.root", _course(revision))

    result = render_saved_course(tmp_path, "architecture", "repository.root")

    assert result.artifact == "course"
    assert result.jsonl_path.endswith("courses/architecture.jsonl")
    assert result.markdown_path.endswith("courses/architecture.md")
    assert (tmp_path / result.markdown_path).is_file()
    assert "sequenceDiagram" in (tmp_path / result.markdown_path).read_text()
