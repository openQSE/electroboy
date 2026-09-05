from __future__ import annotations

import json
from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.domain import repository_revision
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.knowledge_validation import (
    EnrichmentController,
    KnowledgeValidator,
)

RELATIONSHIP_CATEGORIES = {
    name: "not-applicable"
    for name in (
        "interfaces",
        "construction",
        "lifecycle",
        "cleanup",
        "state",
        "persistence",
        "events",
        "messages",
        "external_interactions",
        "concurrency",
        "asynchronous_behavior",
        "configuration",
        "errors",
        "tests",
        "deployment",
    )
}


class FakeRuntime:
    def __init__(self, results: list[AgentResult]) -> None:
        self.results = list(results)
        self.invocations: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocations.append(invocation)
        return self.results.pop(0)


def _source() -> dict[str, object]:
    return {
        "path": "README.md",
        "start_line": 1,
        "end_line": 1,
        "reason": "Defines the fixture.",
    }


def _module(run_id: str, revision: str, *, complete: bool) -> dict[str, object]:
    attributes: dict[str, object] = {
        "boundary_evidence": ["documentation"],
        "interface_ids": [],
        "initial_dependency_ids": [],
        "extension_family_id": "",
    }
    if complete:
        attributes["relationship_analysis"] = {
            "incoming_relationship_ids": [],
            "outgoing_relationship_ids": [],
            "diagnostic_ids": [],
            "categories": RELATIONSHIP_CATEGORIES,
        }
    return {
        "schema_version": 1,
        "analysis_run_id": run_id,
        "repository_revision": revision,
        "record_type": "entity",
        "id": "module.app",
        "kind": "module",
        "name": "Application",
        "summary": "Runs the fixture application.",
        "parent_id": "repository.root",
        "source_refs": [_source()],
        "confidence": "high",
        "attributes": attributes,
    }


def _knowledge(root: Path, *, complete: bool) -> list[dict[str, object]]:
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    revision = repository_revision(root)
    run_id = "run-validation"
    common = {
        "schema_version": 1,
        "analysis_run_id": run_id,
        "repository_revision": revision,
    }
    return [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "fixture",
            "scope_path": ".",
            "status": "validation",
            "entity_count": 3,
            "relationship_count": 0,
            "flow_count": 1,
            "diagnostic_count": 0,
            "attributes": {
                "inventory": {"entry_point_ids": ["entry.main"]},
                "module_catalog": {
                    "major_module_ids": ["module.app"],
                    "extension_family_ids": [],
                },
                "flow_catalog": {
                    "flow_ids": ["flow.main"],
                    "major_entry_point_ids": ["entry.main"],
                    "covered_entry_point_ids": ["entry.main"],
                    "uncovered_entry_points": [],
                },
            },
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": "fixture",
            "summary": "Validation fixture.",
            "source_refs": [_source()],
            "confidence": "verified",
        },
        _module(run_id, revision, complete=complete),
        {
            **common,
            "record_type": "entity",
            "id": "entry.main",
            "kind": "entry-point",
            "name": "main",
            "summary": "Starts the application.",
            "parent_id": "module.app",
            "source_refs": [_source()],
            "confidence": "high",
        },
        {
            **common,
            "record_type": "runtime_flow",
            "id": "flow.main",
            "name": "Startup",
            "kind": "startup",
            "participant_ids": ["entry.main", "module.app"],
            "steps": [
                {
                    "order": 1,
                    "from_id": "entry.main",
                    "to_id": "module.app",
                    "action": "Start application",
                    "relationship_ids": [],
                }
            ],
            "source_refs": [_source()],
            "confidence": "high",
        },
    ]


def _architecture_course(revision: str) -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-validation",
        "repository_revision": revision,
    }
    return [
        {
            **common,
            "record_type": "document",
            "id": "course.architecture",
            "title": "Architecture",
            "course_mode": "architecture",
            "scope_id": "repository.root",
            "status": "ready",
        },
        {
            **common,
            "record_type": "section",
            "id": "course.architecture.overview",
            "parent_id": "course.architecture",
            "heading_level": 2,
            "order": 1,
            "title": "Overview",
            "body": "The application starts from its main entry point.",
            "detail_level": "architecture",
            "knowledge_entity_ids": ["module.app"],
            "relationship_ids": [],
            "runtime_flow_ids": ["flow.main"],
            "related_module_ids": ["module.app"],
            "related_symbol_ids": [],
            "prerequisite_section_ids": [],
            "source_refs": [_source()],
            "confidence": "high",
        },
    ]


def test_complete_knowledge_passes_cross_record_validation(tmp_path: Path) -> None:
    report = KnowledgeValidator(tmp_path).audit(_knowledge(tmp_path, complete=True))

    assert report.complete
    assert report.gaps == ()


def test_actionable_gap_becomes_stable_structured_request(tmp_path: Path) -> None:
    records = _knowledge(tmp_path, complete=False)
    report = KnowledgeValidator(tmp_path).audit(records)

    assert not report.complete
    assert report.gaps[0].code == "module-completeness"
    first = report.request_records()[0]
    second = KnowledgeValidator(tmp_path).audit(records).request_records()[0]
    assert first["id"] == second["id"]
    assert first["scope_id"] == "module.app"
    assert first["attributes"]["blocks_course"] is True


def test_enrichment_merges_targeted_revision_resolves_request_and_stales_course(
    tmp_path: Path,
) -> None:
    records = _knowledge(tmp_path, complete=False)
    store = KnowledgeStore(tmp_path)
    store.save_knowledge(records)
    revision = repository_revision(tmp_path)
    store.save_course(
        "architecture", "repository.root", _architecture_course(revision)
    )
    runtime = FakeRuntime(
        [
            AgentResult(
                ok=True,
                final_message=json.dumps(
                    _module("run-validation", revision, complete=True)
                ),
            )
        ]
    )

    report = EnrichmentController(
        tmp_path,
        runtime_factory=lambda _role, _root: runtime,
        max_attempts=1,
    ).run()

    assert report.complete
    requests = store.query(kind="")
    request = next(
        item for item in requests if item["record_type"] == "knowledge_request"
    )
    assert request["status"] == "resolved"
    assert len(runtime.invocations) == 1
    assert "module.app" in runtime.invocations[0].prompt
    assert store.load_course("architecture", "repository.root")[0]["status"] == "stale"


def test_unresolved_enrichment_stops_at_attempt_limit(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    store.save_knowledge(_knowledge(tmp_path, complete=False))
    runtime = FakeRuntime(
        [
            AgentResult(ok=False, final_message="", error="temporary failure"),
            AgentResult(ok=False, final_message="", error="still unresolved"),
        ]
    )

    report = EnrichmentController(
        tmp_path,
        runtime_factory=lambda _role, _root: runtime,
        max_attempts=2,
    ).run()

    assert not report.complete
    request = next(
        item
        for item in store.load_knowledge()
        if item["record_type"] == "knowledge_request"
    )
    assert request["status"] == "blocked"
    assert request["attributes"]["attempts"] == 2
    assert len(runtime.invocations) == 2


def test_conflicting_enrichment_is_rejected_and_bounded(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    store.save_knowledge(_knowledge(tmp_path, complete=False))
    module = store.get("module.app")
    conflict = {**module, "kind": "interface"}
    runtime = FakeRuntime([AgentResult(ok=True, final_message=json.dumps(conflict))])

    EnrichmentController(
        tmp_path,
        runtime_factory=lambda _role, _root: runtime,
        max_attempts=1,
    ).run()

    assert store.get("module.app")["kind"] == "module"
    request = next(
        item
        for item in store.load_knowledge()
        if item["record_type"] == "knowledge_request"
    )
    assert request["status"] == "blocked"
