from __future__ import annotations

from pathlib import Path

import pytest

from electroboy.workflows.code_learner.contracts import (
    ContractError,
    load_contract_schema,
    parse_jsonl,
    validate_course_records,
    validate_knowledge_records,
    validate_tutor_context,
)


def _source_reference() -> dict[str, object]:
    return {
        "path": "src/service.py",
        "start_line": 1,
        "end_line": 2,
        "reason": "Defines the service entry point.",
        "revision": "revision-1",
    }


def _knowledge_records() -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-1",
        "repository_revision": "revision-1",
    }
    return [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "Sample",
            "scope_path": ".",
            "status": "validated",
            "entity_count": 2,
            "relationship_count": 1,
            "flow_count": 1,
            "diagnostic_count": 0,
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": "Sample",
            "summary": "Sample repository.",
            "source_refs": [_source_reference()],
            "confidence": "verified",
        },
        {
            **common,
            "record_type": "entity",
            "id": "module.service",
            "kind": "module",
            "name": "Service",
            "summary": "Handles requests.",
            "parent_id": "repository.root",
            "source_refs": [_source_reference()],
            "confidence": "high",
        },
        {
            **common,
            "record_type": "relationship",
            "id": "relationship.repository-contains-service",
            "kind": "contains",
            "from_id": "repository.root",
            "to_id": "module.service",
            "summary": "The repository contains the service module.",
            "source_refs": [_source_reference()],
            "confidence": 0.95,
        },
        {
            **common,
            "record_type": "runtime_flow",
            "id": "flow.request",
            "name": "Request",
            "kind": "request",
            "participant_ids": ["repository.root", "module.service"],
            "steps": [
                {
                    "order": 1,
                    "from_id": "repository.root",
                    "to_id": "module.service",
                    "action": "Dispatch request",
                    "relationship_ids": ["relationship.repository-contains-service"],
                }
            ],
            "source_refs": [_source_reference()],
            "confidence": "high",
        },
    ]


def _course_records() -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-1",
        "repository_revision": "revision-1",
    }
    return [
        {
            **common,
            "record_type": "document",
            "id": "course.module.service",
            "title": "Service",
            "course_mode": "module",
            "scope_id": "module.service",
            "status": "generated",
        },
        {
            **common,
            "record_type": "section",
            "id": "course.module.service.flow",
            "parent_id": "course.module.service",
            "heading_level": 2,
            "order": 10,
            "title": "Request Flow",
            "body": "```mermaid\nsequenceDiagram\n  A->>B: Request\n```",
            "detail_level": "module",
            "knowledge_entity_ids": ["module.service"],
            "relationship_ids": ["relationship.repository-contains-service"],
            "runtime_flow_ids": ["flow.request"],
            "source_refs": [_source_reference()],
            "confidence": "high",
            "diagrams": [
                {
                    "id": "diagram.request",
                    "type": "sequence",
                    "question": "How does a request reach the service?",
                }
            ],
        },
    ]


def _tutor_context() -> dict[str, object]:
    return {
        "schema_version": 1,
        "context_version": 1,
        "project_id": "project-1",
        "repository_revision": "revision-1",
        "stale": False,
        "course": {
            "document_id": "course.module.service",
            "mode": "module",
            "scope_id": "module.service",
            "section_id": "course.module.service.flow",
            "horizontal_index": 0,
            "vertical_path": ["course.architecture", "course.module.service"],
        },
        "selection": {
            "module_id": "module.service",
            "symbol_id": None,
            "knowledge_entity_ids": ["module.service"],
            "relationship_ids": ["relationship.repository-contains-service"],
            "runtime_flow_ids": ["flow.request"],
        },
        "source": {"path": "src/service.py", "start_line": 1, "end_line": 2},
        "artifacts": {
            "course": ".electroboy/code-learner/courses/modules/service.jsonl",
            "knowledge_root": ".electroboy/code-learner/knowledge",
        },
        "updated_at": "2026-09-04T12:00:00Z",
        "writer_id": "session-1",
    }


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    source = tmp_path / "src"
    source.mkdir()
    (source / "service.py").write_text(
        "def handle(request):\n    return request\n",
        encoding="utf-8",
    )
    return tmp_path


def test_packaged_schemas_are_versioned_json_schema_documents() -> None:
    for name in ("knowledge", "course", "tutor-context"):
        schema = load_contract_schema(name)
        assert schema["$schema"].endswith("2020-12/schema")
        assert "code-learner" in str(schema["$id"])


def test_parse_jsonl_requires_object_records() -> None:
    assert parse_jsonl('{"id":"one"}\n', artifact="fixture") == [{"id": "one"}]
    with pytest.raises(ContractError, match="record must be an object"):
        parse_jsonl("[]\n", artifact="fixture")


def test_validates_knowledge_references_counts_and_source_ranges(
    repository: Path,
) -> None:
    records = validate_knowledge_records(_knowledge_records(), root=repository)
    assert len(records) == 5


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("entity", "kind", "unknown"), "must be one of"),
        (("relationship", "to_id", "module.missing"), "unknown entity ID"),
        (("manifest", "entity_count", 99), "expected 2, got 99"),
        (("entity", "id", "repository.root"), "duplicate record ID"),
    ],
)
def test_rejects_invalid_knowledge_records(
    repository: Path,
    mutation: tuple[str, str, object],
    message: str,
) -> None:
    records = _knowledge_records()
    target, field, value = mutation
    if target == "manifest":
        record = records[0]
    elif target == "entity" and field == "id":
        record = records[2]
    else:
        record = next(record for record in records if record["record_type"] == target)
    record[field] = value

    with pytest.raises(ContractError, match=message):
        validate_knowledge_records(records, root=repository)


def test_rejects_malformed_source_reference(repository: Path) -> None:
    records = _knowledge_records()
    records[1]["source_refs"][0]["path"] = "../outside.py"  # type: ignore[index]

    with pytest.raises(ContractError, match="must be repository-relative"):
        validate_knowledge_records(records, root=repository)


def test_validates_course_hierarchy_knowledge_links_and_diagrams(
    repository: Path,
) -> None:
    knowledge_ids = [record["id"] for record in _knowledge_records()]
    records = validate_course_records(
        _course_records(),
        knowledge_ids=knowledge_ids,
        root=repository,
    )
    assert records[1]["diagrams"][0]["type"] == "sequence"  # type: ignore[index]


def test_rejects_unknown_course_knowledge_link(repository: Path) -> None:
    records = _course_records()
    records[1]["knowledge_entity_ids"] = ["module.missing"]

    with pytest.raises(ContractError, match="unknown knowledge ID"):
        validate_course_records(
            records,
            knowledge_ids=[record["id"] for record in _knowledge_records()],
            root=repository,
        )


def test_validates_compact_tutor_context(repository: Path) -> None:
    assert (
        validate_tutor_context(_tutor_context(), root=repository)["context_version"]
        == 1
    )

    context = _tutor_context()
    context["artifacts"]["course"] = "../outside.jsonl"  # type: ignore[index]
    with pytest.raises(ContractError, match="must be repository-relative"):
        validate_tutor_context(context, root=repository)
