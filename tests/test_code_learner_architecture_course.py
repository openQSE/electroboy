from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.course_builder import CourseBuilder
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "code_learner_extension"


class FakeRuntime:
    def __init__(self, results: list[AgentResult]) -> None:
        self.results = list(results)
        self.invocations: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocations.append(invocation)
        return self.results.pop(0)


def _copy_fixture(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURE, repository)
    records = [
        json.loads(line)
        for line in (repository / "knowledge-fixture.jsonl").read_text().splitlines()
    ]
    KnowledgeStore(repository).save_knowledge(records)
    return repository


def _course(
    *,
    covered: tuple[str, ...] = (
        "family.transport",
        "interface.transport",
        "implementation.memory",
        "implementation.tcp",
        "module.registry",
    ),
):
    common = {
        "schema_version": 1,
        "analysis_run_id": "course-fixture",
        "repository_revision": "fixture-v1",
    }
    return [
        {
            **common,
            "record_type": "document",
            "id": "course.architecture.repository.root",
            "title": "Transport Architecture",
            "course_mode": "architecture",
            "scope_id": "repository.root",
            "status": "validated",
        },
        {
            **common,
            "record_type": "section",
            "id": "course.architecture.components",
            "parent_id": "course.architecture.repository.root",
            "heading_level": 2,
            "order": 1,
            "title": "Components",
            "body": (
                "The registry selects a transport implementation.\n\n"
                "```mermaid\nflowchart LR\n  Registry --> Family\n```\n\n"
                "```mermaid\nclassDiagram\n  Transport <|-- MemoryTransport\n```"
            ),
            "detail_level": "architecture",
            "previous_section_id": None,
            "next_section_id": "course.architecture.sequence",
            "return_section_id": None,
            "deep_dive_ids": ["course.module.registry"],
            "knowledge_entity_ids": list(covered),
            "relationship_ids": [
                "relationship.repository-contains-family",
                "relationship.family-contains-memory",
                "relationship.family-contains-tcp",
                "relationship.memory-implements-transport",
                "relationship.tcp-implements-transport",
                "relationship.registry-registers-memory",
                "relationship.registry-registers-tcp",
                "relationship.registry-contains-create",
            ],
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": [
                item for item in covered if item.startswith("module.")
            ],
            "related_symbol_ids": ["symbol.create_transport"],
            "prerequisite_section_ids": [],
            "source_refs": [
                {
                    "path": "README.md",
                    "start_line": 1,
                    "end_line": 3,
                    "reason": "States repository purpose.",
                }
            ],
            "confidence": "high",
            "diagrams": [
                {
                    "id": "diagram.components",
                    "type": "flowchart",
                    "question": "How are components connected?",
                },
                {
                    "id": "diagram.contract",
                    "type": "classDiagram",
                    "question": "Which implementations share the contract?",
                },
            ],
        },
        {
            **common,
            "record_type": "section",
            "id": "course.architecture.sequence",
            "parent_id": "course.architecture.repository.root",
            "heading_level": 2,
            "order": 2,
            "title": "Runtime Selection",
            "body": (
                "A caller selects an implementation by name.\n\n"
                "```mermaid\nsequenceDiagram\n"
                "  Caller->>Registry: create_transport(name)\n"
                "  Registry-->>Caller: transport\n```"
            ),
            "detail_level": "architecture",
            "previous_section_id": "course.architecture.components",
            "next_section_id": None,
            "return_section_id": None,
            "deep_dive_ids": [],
            "knowledge_entity_ids": ["module.registry", "symbol.create_transport"],
            "relationship_ids": ["relationship.create-selects-family"],
            "runtime_flow_ids": ["flow.transport-selection"],
            "diagnostic_ids": [],
            "related_module_ids": ["module.registry"],
            "related_symbol_ids": ["symbol.create_transport"],
            "prerequisite_section_ids": ["course.architecture.components"],
            "source_refs": [
                {
                    "path": "src/transports/registry.py",
                    "start_line": 4,
                    "end_line": 11,
                    "reason": "Defines registration lookup and construction.",
                }
            ],
            "confidence": "verified",
            "diagrams": [
                {
                    "id": "diagram.sequence",
                    "type": "sequenceDiagram",
                    "question": "How is a transport selected?",
                }
            ],
        },
    ]


def _jsonl(records: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(record) for record in records)


def test_architecture_builder_selects_invokes_validates_persists_and_renders(
    tmp_path: Path,
) -> None:
    repository = _copy_fixture(tmp_path)
    runtime = FakeRuntime([AgentResult(ok=True, final_message=_jsonl(_course()))])

    result = CourseBuilder(
        repository,
        runtime_factory=lambda _role, _root: runtime,
        max_attempts=1,
    ).build_architecture()

    assert result.record_count == 3
    assert (repository / result.jsonl_path).is_file()
    markdown = (repository / result.markdown_path).read_text()
    assert "flowchart LR" in markdown
    assert "sequenceDiagram" in markdown
    assert "classDiagram" in markdown
    assert len(runtime.invocations) == 1
    invocation = runtime.invocations[0]
    assert "$code-learner-course" in invocation.prompt
    assert "Course mode: architecture" in invocation.prompt
    assert len(invocation.context_paths) == 1
    assert invocation.context_paths[0].endswith(
        "analysis/course-inputs/architecture-repository.root.jsonl"
    )
    selected = (repository / invocation.context_paths[0]).read_text()
    assert "implementation.memory" in selected
    assert "relationship.registry-registers-tcp" in selected
    assert "flow.transport-selection" in selected


def test_architecture_builder_rejects_course_that_omits_an_unchanged_module(
    tmp_path: Path,
) -> None:
    repository = _copy_fixture(tmp_path)
    store = KnowledgeStore(repository)
    manifest = store.get("knowledge.manifest")
    common = {
        "schema_version": 1,
        "analysis_run_id": "course-fixture",
        "repository_revision": "fixture-v1",
    }
    store.merge_knowledge(
        [
            {
                **common,
                "record_type": "entity",
                "id": "module.unchanged",
                "kind": "module",
                "name": "Unchanged subsystem",
                "summary": "A module not touched by the active branch.",
                "parent_id": "repository.root",
                "source_refs": [
                    {
                        "path": "README.md",
                        "start_line": 1,
                        "end_line": 3,
                        "reason": "Fixture evidence.",
                    }
                ],
                "confidence": "high",
            },
            {**manifest, "entity_count": int(manifest["entity_count"]) + 1},
        ]
    )
    runtime = FakeRuntime([AgentResult(ok=True, final_message=_jsonl(_course()))])

    with pytest.raises(CodeLearnerError, match="module.unchanged"):
        CourseBuilder(
            repository,
            runtime_factory=lambda _role, _root: runtime,
            max_attempts=1,
        ).build_architecture()


def test_architecture_builder_requires_both_mandatory_diagrams(
    tmp_path: Path,
) -> None:
    repository = _copy_fixture(tmp_path)
    records = _course()
    records[2]["diagrams"] = []
    records[2]["body"] = "Runtime selection without a sequence diagram."
    runtime = FakeRuntime([AgentResult(ok=True, final_message=_jsonl(records))])

    with pytest.raises(CodeLearnerError, match="sequence diagram"):
        CourseBuilder(
            repository,
            runtime_factory=lambda _role, _root: runtime,
            max_attempts=1,
        ).build_architecture()
