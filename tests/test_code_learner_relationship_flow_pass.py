from __future__ import annotations

import json
from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.analysis_passes import (
    ANALYSIS_PASSES,
    AnalysisScope,
    analysis_scopes,
    validate_pass_output,
)
from electroboy.workflows.code_learner.domain import repository_revision
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.orchestrator import (
    AnalysisOrchestrator,
    analysis_pass_prompt,
)

RELATIONSHIP_CATEGORIES = {
    "interfaces": "not-applicable",
    "construction": "not-applicable",
    "lifecycle": "not-applicable",
    "cleanup": "not-applicable",
    "state": "not-applicable",
    "persistence": "not-applicable",
    "events": "not-applicable",
    "messages": "not-applicable",
    "external_interactions": "not-applicable",
    "concurrency": "not-applicable",
    "asynchronous_behavior": "not-applicable",
    "configuration": "not-applicable",
    "errors": "not-applicable",
    "tests": "not-applicable",
    "deployment": "not-applicable",
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
        "reason": "Defines the test module.",
    }


def _module_record(
    module_id: str, run_id: str, revision: str, *, analyzed: bool = False
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "boundary_evidence": ["documentation"],
        "interface_ids": [],
        "initial_dependency_ids": [],
        "extension_family_id": "",
    }
    if analyzed:
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
        "id": module_id,
        "kind": "module",
        "name": module_id,
        "summary": f"Module {module_id}.",
        "parent_id": "repository.root",
        "source_refs": [_source()],
        "confidence": "high",
        "attributes": attributes,
    }


def _seed_modules(root: Path, *, count: int = 5) -> tuple[str, str, list[str]]:
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    revision = repository_revision(root)
    run_id = "run-relationships"
    module_ids = [f"module.{index}" for index in range(count)]
    common = {
        "schema_version": 1,
        "analysis_run_id": run_id,
        "repository_revision": revision,
    }
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "fixture",
            "scope_path": ".",
            "status": "modules",
            "entity_count": count + 1,
            "relationship_count": 0,
            "flow_count": 0,
            "diagnostic_count": 0,
            "attributes": {
                "module_catalog": {
                    "major_module_ids": module_ids,
                    "extension_family_ids": [],
                    "shared_infrastructure_module_ids": [],
                    "coverage": {
                        "candidate_count": count,
                        "module_count": count,
                        "implementation_candidate_count": 0,
                        "implementation_module_count": 0,
                        "excluded_count": 0,
                        "evidence_paths_reviewed": ["README.md"],
                    },
                }
            },
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": "fixture",
            "summary": "Relationship fixture.",
            "source_refs": [_source()],
            "confidence": "verified",
        },
    ]
    records.extend(_module_record(item, run_id, revision) for item in module_ids)
    KnowledgeStore(root).save_knowledge(records)
    return run_id, revision, module_ids


def test_relationship_scopes_batch_major_modules(tmp_path: Path) -> None:
    _run_id, _revision, module_ids = _seed_modules(tmp_path, count=9)

    scopes = analysis_scopes(
        ANALYSIS_PASSES[2], KnowledgeStore(tmp_path).load_knowledge(), batch_size=4
    )

    assert [scope.entity_ids for scope in scopes] == [
        tuple(module_ids[:4]),
        tuple(module_ids[4:8]),
        tuple(module_ids[8:]),
    ]


def test_relationship_jobs_are_invoked_and_checkpointed_independently(
    tmp_path: Path,
) -> None:
    run_id, revision, module_ids = _seed_modules(tmp_path)
    batches = (module_ids[:4], module_ids[4:])
    runtime = FakeRuntime(
        [
            AgentResult(
                ok=True,
                final_message="\n".join(
                    json.dumps(_module_record(item, run_id, revision, analyzed=True))
                    for item in batch
                ),
            )
            for batch in batches
        ]
    )

    AnalysisOrchestrator(
        tmp_path,
        runtime_factory=lambda _role, _root: runtime,
        passes=(ANALYSIS_PASSES[2],),
        max_attempts=1,
    ).run()

    assert len(runtime.invocations) == 2
    assert module_ids[0] in runtime.invocations[0].prompt
    assert module_ids[-1] in runtime.invocations[1].prompt
    checkpoint = KnowledgeStore(tmp_path).load_checkpoint()
    jobs = checkpoint["passes"]["relationships"]["jobs"]  # type: ignore[index]
    assert {value["status"] for value in jobs.values()} == {"completed"}


def test_relationship_prompt_requires_reconciliation_and_dynamic_diagnostics(
    tmp_path: Path,
) -> None:
    prompt = analysis_pass_prompt(
        tmp_path,
        ANALYSIS_PASSES[2],
        run_id="run",
        revision="revision",
        store=KnowledgeStore(tmp_path),
        scope=AnalysisScope("modules-1", ("module.a", "module.b")),
    )

    assert "Reconcile an apparent contradiction" in prompt
    assert "function pointers" in " ".join(prompt.split())
    assert "module.a, module.b" in prompt


def test_flow_contract_supports_cycles_events_processes_and_error_paths() -> None:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-flow",
        "repository_revision": "revision",
    }
    source = _source()
    entities = [
        ("entry.command", "entry-point"),
        ("module.publisher", "module"),
        ("module.consumer", "module"),
        ("process.worker", "process"),
        ("external.queue", "external-system"),
    ]
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "flow-fixture",
            "scope_path": ".",
            "status": "flows",
            "entity_count": len(entities),
            "relationship_count": 0,
            "flow_count": 1,
            "diagnostic_count": 0,
            "attributes": {
                "flow_catalog": {
                    "flow_ids": ["flow.command"],
                    "major_entry_point_ids": ["entry.command"],
                    "covered_entry_point_ids": ["entry.command"],
                    "uncovered_entry_points": [],
                }
            },
        }
    ]
    records.extend(
        {
            **common,
            "record_type": "entity",
            "id": record_id,
            "kind": kind,
            "name": record_id,
            "summary": f"Flow participant {record_id}.",
            "source_refs": [source],
            "confidence": "high",
        }
        for record_id, kind in entities
    )
    records.append(
        {
            **common,
            "record_type": "runtime_flow",
            "id": "flow.command",
            "name": "Asynchronous command processing",
            "kind": "event-driven-cross-process",
            "participant_ids": [item[0] for item in entities],
            "steps": [
                {
                    "order": 1,
                    "from_id": "entry.command",
                    "to_id": "module.publisher",
                    "action": "Accept command",
                    "relationship_ids": [],
                },
                {
                    "order": 2,
                    "from_id": "module.publisher",
                    "to_id": "external.queue",
                    "action": "Publish event",
                    "relationship_ids": [],
                },
                {
                    "order": 3,
                    "from_id": "process.worker",
                    "to_id": "module.consumer",
                    "action": "Consume event",
                    "relationship_ids": [],
                },
                {
                    "order": 4,
                    "from_id": "module.consumer",
                    "to_id": "module.publisher",
                    "action": "Publish completion event",
                    "relationship_ids": [],
                },
            ],
            "source_refs": [source],
            "confidence": "medium",
            "attributes": {
                "normal_path_summary": "A command crosses a queue and worker process.",
                "alternate_flows": ["A duplicate command is ignored."],
                "error_flows": ["Queue publication failure is returned."],
                "concurrency_notes": "The worker consumes asynchronously.",
                "unresolved_dispatch": ["Runtime subscriber selection is dynamic."],
            },
        }
    )

    validate_pass_output(ANALYSIS_PASSES[3], records)
