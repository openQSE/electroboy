from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.domain import (
    CodeLearnerError,
    repository_revision,
)
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.orchestrator import (
    ANALYSIS_PASSES,
    AnalysisOrchestrator,
)


class FakeRuntime:
    def __init__(self, results: list[AgentResult]) -> None:
        self.results = list(results)
        self.invocations: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocations.append(invocation)
        return self.results.pop(0)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Orchestration fixture\n", encoding="utf-8")
    return tmp_path


def _record_lines(records: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(record) for record in records)


def _inventory(revision: str, run_id: str) -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": run_id,
        "repository_revision": revision,
    }
    reference = {
        "path": "README.md",
        "start_line": 1,
        "end_line": 1,
        "reason": "Defines the fixture.",
    }
    return [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "Fixture",
            "scope_path": ".",
            "status": "inventory",
            "entity_count": 1,
            "relationship_count": 0,
            "flow_count": 0,
            "diagnostic_count": 0,
            "attributes": {
                "inventory": {
                    "languages": [
                        {"name": "Markdown", "evidence_paths": ["README.md"]}
                    ],
                    "excluded_regions": [],
                    "build_systems": [],
                    "dependency_manifests": [],
                    "produced_artifact_ids": [],
                    "entry_point_ids": [],
                    "public_surface_ids": [],
                    "process_ids": [],
                    "test_surface_ids": [],
                    "external_system_ids": [],
                    "analysis_tools": [
                        {
                            "name": "repository-search",
                            "available": True,
                            "applies_to": ["Markdown"],
                            "limitation": "Text search does not provide semantic edges.",
                        }
                    ],
                }
            },
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": "Fixture",
            "summary": "Orchestration fixture.",
            "source_refs": [reference],
            "confidence": "verified",
        },
    ]


def _module_patch(revision: str, run_id: str) -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": run_id,
        "repository_revision": revision,
    }
    reference = {
        "path": "README.md",
        "start_line": 1,
        "end_line": 1,
        "reason": "Supports the fixture module.",
    }
    return [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "Fixture",
            "scope_path": ".",
            "status": "modules",
            "entity_count": 2,
            "relationship_count": 1,
            "flow_count": 0,
            "diagnostic_count": 0,
            "attributes": {
                "inventory": {
                    "languages": [
                        {"name": "Markdown", "evidence_paths": ["README.md"]}
                    ],
                    "excluded_regions": [],
                    "build_systems": [],
                    "dependency_manifests": [],
                    "produced_artifact_ids": [],
                    "entry_point_ids": [],
                    "public_surface_ids": [],
                    "process_ids": [],
                    "test_surface_ids": [],
                    "external_system_ids": [],
                    "analysis_tools": [],
                },
                "module_catalog": {
                    "major_module_ids": ["module.fixture"],
                    "extension_family_ids": [],
                    "shared_infrastructure_module_ids": [],
                    "coverage": {
                        "candidate_count": 1,
                        "module_count": 1,
                        "implementation_candidate_count": 0,
                        "implementation_module_count": 0,
                        "excluded_count": 0,
                        "evidence_paths_reviewed": ["README.md"],
                    },
                },
            },
        },
        {
            **common,
            "record_type": "entity",
            "id": "module.fixture",
            "kind": "module",
            "name": "Fixture Module",
            "summary": "Owns fixture behavior.",
            "parent_id": "repository.root",
            "source_refs": [reference],
            "confidence": "high",
            "attributes": {
                "boundary_evidence": ["documentation"],
                "interface_ids": [],
                "initial_dependency_ids": [],
                "extension_family_id": "",
            },
        },
        {
            **common,
            "record_type": "relationship",
            "id": "relationship.repository-contains-fixture",
            "kind": "contains",
            "from_id": "repository.root",
            "to_id": "module.fixture",
            "summary": "The repository contains the fixture module.",
            "source_refs": [reference],
            "confidence": "high",
        },
    ]


def _runtime_for_two_passes(repository: Path) -> tuple[FakeRuntime, str]:
    revision = repository_revision(repository)
    run_id = "run-1"
    runtime = FakeRuntime(
        [
            AgentResult(
                ok=True, final_message=_record_lines(_inventory(revision, run_id))
            ),
            AgentResult(
                ok=True, final_message=_record_lines(_module_patch(revision, run_id))
            ),
        ]
    )
    return runtime, run_id


def test_runs_fresh_scoped_passes_and_persists_each_result(repository: Path) -> None:
    runtime, run_id = _runtime_for_two_passes(repository)
    progress: list[dict[str, object]] = []
    orchestrator = AnalysisOrchestrator(
        repository,
        runtime_factory=lambda _role, _root: runtime,
        passes=ANALYSIS_PASSES[:2],
    )
    checkpoint = orchestrator.store.load_checkpoint()
    assert checkpoint is None
    original_checkpoint = orchestrator._checkpoint()
    original_checkpoint["analysis_run_id"] = run_id
    orchestrator.store.save_checkpoint(original_checkpoint)

    records = orchestrator.run(progress.append)

    assert len(runtime.invocations) == 2
    assert all("$codebase-analysis" in item.prompt for item in runtime.invocations)
    assert all(run_id in item.prompt for item in runtime.invocations)
    assert runtime.invocations[0].provider_session_id is None
    assert {record["id"] for record in records} >= {
        "repository.root",
        "module.fixture",
        "relationship.repository-contains-fixture",
    }
    assert progress[-1]["phase"] == "knowledge_validated"
    checkpoint = KnowledgeStore(repository).load_checkpoint()
    assert checkpoint is not None
    assert checkpoint["status"] == "validated"


def test_retries_without_duplicating_stable_records(repository: Path) -> None:
    revision = repository_revision(repository)
    run_id = "run-retry"
    runtime = FakeRuntime(
        [
            AgentResult(ok=False, final_message="", error="temporary failure"),
            AgentResult(
                ok=True, final_message=_record_lines(_inventory(revision, run_id))
            ),
        ]
    )
    orchestrator = AnalysisOrchestrator(
        repository,
        runtime_factory=lambda _role, _root: runtime,
        passes=ANALYSIS_PASSES[:1],
        max_attempts=2,
    )
    checkpoint = orchestrator._checkpoint()
    checkpoint["analysis_run_id"] = run_id
    orchestrator.store.save_checkpoint(checkpoint)

    records = orchestrator.run()

    assert len(runtime.invocations) == 2
    assert len({record["id"] for record in records}) == len(records)


def test_later_failure_preserves_completed_pass_and_resumes(repository: Path) -> None:
    revision = repository_revision(repository)
    run_id = "run-resume"
    failing = FakeRuntime(
        [
            AgentResult(
                ok=True, final_message=_record_lines(_inventory(revision, run_id))
            ),
            AgentResult(ok=False, final_message="", error="module pass failed"),
        ]
    )
    orchestrator = AnalysisOrchestrator(
        repository,
        runtime_factory=lambda _role, _root: failing,
        passes=ANALYSIS_PASSES[:2],
        max_attempts=1,
    )
    checkpoint = orchestrator._checkpoint()
    checkpoint["analysis_run_id"] = run_id
    orchestrator.store.save_checkpoint(checkpoint)

    with pytest.raises(CodeLearnerError, match="module pass failed"):
        orchestrator.run()

    assert KnowledgeStore(repository).get("repository.root")
    resumed = FakeRuntime(
        [
            AgentResult(
                ok=True, final_message=_record_lines(_module_patch(revision, run_id))
            )
        ]
    )
    result = AnalysisOrchestrator(
        repository,
        runtime_factory=lambda _role, _root: resumed,
        passes=ANALYSIS_PASSES[:2],
        max_attempts=1,
    ).run()

    assert len(resumed.invocations) == 1
    assert any(record["id"] == "module.fixture" for record in result)
