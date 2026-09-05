from __future__ import annotations

import json
import shutil
from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.course_builder import CourseBuilder
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "code_learner_extension"
TOPICS = (
    "purpose",
    "interfaces",
    "dependencies",
    "internals",
    "state",
    "flows",
    "tests",
    "changes",
    "risks",
)


class FakeRuntime:
    def __init__(self, results: list[AgentResult]) -> None:
        self.results = list(results)
        self.invocations: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocations.append(invocation)
        return self.results.pop(0)


class RuntimeSequence:
    def __init__(self, runtimes: list[FakeRuntime]) -> None:
        self.runtimes = list(runtimes)

    def __call__(self, _role: str, _root: Path) -> FakeRuntime:
        return self.runtimes.pop(0)


def _copy_fixture(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURE, repository)
    records = [
        json.loads(line)
        for line in (repository / "knowledge-fixture.jsonl").read_text().splitlines()
    ]
    KnowledgeStore(repository).save_knowledge(records)
    return repository


def _module_course(
    scope_id: str,
    *,
    entities: list[str],
    relationships: list[str],
) -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "course-fixture",
        "repository_revision": "fixture-v1",
    }
    document_id = f"course.module.{scope_id}"
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "document",
            "id": document_id,
            "title": f"Module: {scope_id}",
            "course_mode": "module",
            "scope_id": scope_id,
            "coverage_topics": list(TOPICS),
            "status": "validated",
        }
    ]
    for index, topic in enumerate(TOPICS):
        section_id = f"{document_id}.{topic}"
        previous = f"{document_id}.{TOPICS[index - 1]}" if index else None
        following = (
            f"{document_id}.{TOPICS[index + 1]}"
            if index + 1 < len(TOPICS)
            else None
        )
        body = f"Evidence-grounded {topic} behavior for `{scope_id}`."
        diagrams: list[dict[str, object]] = []
        if index == 0 and len(relationships) >= 2:
            body += (
                "\n\n```mermaid\nstateDiagram-v2\n"
                "  [*] --> Selected\n  Selected --> Ready\n```\n\n"
                "```mermaid\nsequenceDiagram\n"
                "  Caller->>Module: invoke\n  Module-->>Caller: result\n```"
            )
            diagrams = [
                {
                    "id": f"diagram.{scope_id}.state",
                    "type": "stateDiagram-v2",
                    "question": "What states matter?",
                },
                {
                    "id": f"diagram.{scope_id}.sequence",
                    "type": "sequenceDiagram",
                    "question": "How is the module invoked?",
                },
            ]
        records.append(
            {
                **common,
                "record_type": "section",
                "id": section_id,
                "parent_id": document_id,
                "heading_level": 2,
                "order": index,
                "title": topic.title(),
                "topic": topic,
                "body": body,
                "detail_level": "module",
                "previous_section_id": previous,
                "next_section_id": following,
                "return_section_id": None,
                "deep_dive_ids": (
                    ["course.function.symbol.create_transport"]
                    if topic == "internals"
                    else []
                ),
                "knowledge_entity_ids": entities if index == 0 else [scope_id],
                "relationship_ids": relationships if index == 0 else [],
                "runtime_flow_ids": (
                    ["flow.transport-selection"]
                    if scope_id == "module.registry" and topic == "flows"
                    else []
                ),
                "diagnostic_ids": [],
                "related_module_ids": [
                    item for item in entities if item.startswith("module.")
                ],
                "related_symbol_ids": (
                    ["symbol.create_transport"]
                    if scope_id == "module.registry"
                    else []
                ),
                "prerequisite_section_ids": [previous] if previous else [],
                "source_refs": [
                    {
                        "path": (
                            "src/transports/registry.py"
                            if scope_id == "module.registry"
                            else "README.md"
                        ),
                        "start_line": 1,
                        "end_line": 1,
                        "reason": f"Supports the {topic} lesson.",
                    }
                ],
                "confidence": "high",
                "diagrams": diagrams,
            }
        )
    return records


def _jsonl(records: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(record) for record in records)


def test_module_builder_uses_direct_neighborhood_and_multiple_diagram_types(
    tmp_path: Path,
) -> None:
    repository = _copy_fixture(tmp_path)
    relationships = [
        "relationship.registry-registers-memory",
        "relationship.registry-registers-tcp",
        "relationship.registry-contains-create",
        "relationship.create-selects-family",
    ]
    entities = [
        "module.registry",
        "family.transport",
        "implementation.memory",
        "implementation.tcp",
    ]
    runtime = FakeRuntime(
        [
            AgentResult(
                ok=True,
                final_message=_jsonl(
                    _module_course(
                        "module.registry",
                        entities=entities,
                        relationships=relationships,
                    )
                ),
            )
        ]
    )

    result = CourseBuilder(
        repository,
        runtime_factory=lambda _role, _root: runtime,
        max_attempts=1,
    ).build_module("module.registry")

    assert result.scope_id == "module.registry"
    markdown = (repository / result.markdown_path).read_text()
    assert "stateDiagram-v2" in markdown
    assert "sequenceDiagram" in markdown
    invocation = runtime.invocations[0]
    assert "Course mode: module" in invocation.prompt
    selected = (repository / invocation.context_paths[0]).read_text()
    assert "relationship.registry-registers-memory" in selected
    assert "implementation.tcp" in selected
    index = KnowledgeStore(repository).load_course_index()["courses"]
    assert index["module:module.registry"]["status"] == "ready"


def test_module_batch_isolates_failure_and_supports_single_module_retry(
    tmp_path: Path,
) -> None:
    repository = _copy_fixture(tmp_path)
    store = KnowledgeStore(repository)
    manifest = store.get("knowledge.manifest")
    store.merge_knowledge(
        [
            {
                "schema_version": 1,
                "analysis_run_id": "course-fixture",
                "repository_revision": "fixture-v1",
                "record_type": "entity",
                "id": "module.other",
                "kind": "module",
                "name": "Other",
                "summary": "Independent unchanged module.",
                "parent_id": "repository.root",
                "source_refs": [
                    {
                        "path": "README.md",
                        "start_line": 1,
                        "end_line": 1,
                        "reason": "Fixture evidence.",
                    }
                ],
                "confidence": "high",
            },
            {
                **manifest,
                "attributes": {
                    "module_catalog": {
                        "major_module_ids": ["module.registry", "module.other"]
                    }
                },
            },
        ]
    )
    registry_scope = CourseBuilder(repository).selector.module("module.registry")
    registry_entities = [
        str(record["id"])
        for record in registry_scope.records
        if record.get("record_type") == "entity"
        and record.get("kind")
        in {"module", "extension-family", "implementation", "interface"}
    ]
    registry_relationships = [
        str(record["id"])
        for record in registry_scope.records
        if record.get("record_type") == "relationship"
    ]
    success = FakeRuntime(
        [
            AgentResult(
                ok=True,
                final_message=_jsonl(
                    _module_course(
                        "module.registry",
                        entities=registry_entities,
                        relationships=registry_relationships,
                    )
                ),
            )
        ]
    )
    failure = FakeRuntime(
        [AgentResult(ok=False, final_message="", error="module generation failed")]
    )

    batch = CourseBuilder(
        repository,
        runtime_factory=RuntimeSequence([success, failure]),
        max_attempts=1,
    ).build_all_modules()

    assert [item.scope_id for item in batch.completed] == ["module.registry"]
    assert "module.other" in batch.failed
    index = store.load_course_index()["courses"]
    assert index["module:module.registry"]["status"] == "ready"
    assert index["module:module.other"]["status"] == "failed"

    retry_runtime = FakeRuntime(
        [
            AgentResult(
                ok=True,
                final_message=_jsonl(
                    _module_course(
                        "module.other",
                        entities=["module.other"],
                        relationships=[],
                    )
                ),
            )
        ]
    )
    retried = CourseBuilder(
        repository,
        runtime_factory=lambda _role, _root: retry_runtime,
        max_attempts=1,
    ).build_module("module.other")

    assert retried.scope_id == "module.other"
    assert store.load_course_index()["courses"]["module:module.other"][
        "status"
    ] == "ready"
