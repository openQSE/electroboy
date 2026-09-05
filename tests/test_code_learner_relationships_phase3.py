from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.adapters.base import AgentResult
from electroboy.workflows.code_learner.component_manifest import (
    ComponentManifestService,
)
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.modules import ModuleSynthesisService
from electroboy.workflows.code_learner.overlap import ComponentOverlapService
from electroboy.workflows.code_learner.phase3_store import Phase3Store
from electroboy.workflows.code_learner.relationships import (
    ModuleRelationshipService,
    RelationshipScope,
)
from electroboy.workflows.code_learner.source_manifest import SourceManifestService


class FakeRuntime:
    def __init__(self, outputs: list[AgentResult]) -> None:
        self.outputs = outputs
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return self.outputs.pop(0)


def _setup(root: Path):
    for index in range(2):
        (root / f"file{index}.py").write_text(
            f"def function{index}():\n    return {index}\n", encoding="utf-8"
        )
    source = SourceManifestService(root)
    source_snapshot = source.generate()
    candidates = []
    for index in range(2):
        candidates.append(
            {
                "schema_version": 1,
                "record_type": "component_candidate",
                "repository_revision": source_snapshot.revision,
                "candidate_id": f"candidate-{index}",
                "name": f"Component {index}",
                "kind": "service",
                "responsibility": "Fixture component.",
                "file_ids": [f"file:file{index}.py"],
                "symbols": [
                    {
                        "file_id": f"file:file{index}.py",
                        "name": f"function{index}",
                        "kind": "function",
                        "start_line": 1,
                        "end_line": 2,
                        "canonical_key": f"symbol-{index}",
                        "validated_by": "fixture",
                    }
                ],
                "owned_source_refs": [],
                "supporting_source_refs": [],
                "confidence": "high",
                "limitations": [],
            }
        )
    store = Phase3Store(root)
    store.write_jsonl(store.components_root / "candidates.jsonl", candidates)
    ComponentOverlapService(root, store=store).build(candidates)
    component_snapshot = ComponentManifestService(root, store=store).build(
        analysis_run_id="run-1"
    )
    revision = str(component_snapshot.manifest["repository_revision"])
    component_ids = list(component_snapshot.manifest["component_ids"])
    module_records = []
    for index, component_id in enumerate(component_ids):
        module_records.append(
            {
                "schema_version": 1,
                "record_type": "module",
                "repository_revision": revision,
                "id": f"temporary-{index}",
                "name": f"Module {index}",
                "kind": "subsystem",
                "purpose": "Fixture module.",
                "responsibility": "Owns one fixture component.",
                "component_ids": [component_id],
                "primary_component_ids": [component_id],
                "entry_component_ids": [component_id],
                "primary_for_component_ids": [component_id],
                "grouping_rationale": "One component forms this fixture module.",
                "source_refs": [],
                "confidence": "high",
                "limitations": [],
            }
        )
    module_snapshot = ModuleSynthesisService(root, store=store).ingest(
        module_records, analysis_run_id="run-1"
    )
    return source_snapshot, component_snapshot, module_snapshot


def _relationship(
    source_snapshot,
    component_snapshot,
    module_snapshot,
    **extra,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "module_relationship",
        "repository_revision": source_snapshot.revision,
        "id": "temporary-edge",
        "from_module_id": module_snapshot.modules[0]["id"],
        "to_module_id": module_snapshot.modules[1]["id"],
        "kind": "calls",
        "summary": "The first module invokes the second module.",
        "direction": "directed",
        "condition": "feature flag enabled",
        "confidence": "high",
        "supporting_component_ids": [
            component_snapshot.components[0]["id"],
            component_snapshot.components[1]["id"],
        ],
        "source_refs": [
            {
                "file_id": "file:file0.py",
                "start_line": 1,
                "end_line": 2,
                "reason": "Fixture call evidence.",
            }
        ],
        "limitations": ["Dynamic replacement may alter the target."],
        **extra,
    }


def test_relationship_scope_validates_conditional_dynamic_edge_and_persists(
    tmp_path: Path,
) -> None:
    source, components, modules = _setup(tmp_path)
    service = ModuleRelationshipService(tmp_path)
    scope = RelationshipScope("scope-a", str(modules.modules[0]["id"]))

    accepted = service.ingest_scope(
        scope, json.dumps(_relationship(source, components, modules))
    )

    assert accepted[0]["id"].startswith("relationship:")
    assert accepted[0]["condition"] == "feature flag enabled"
    assert accepted[0]["limitations"]
    assert service.rebuild() == accepted


def test_exact_duplicates_collapse_and_contradictions_use_focused_resolver(
    tmp_path: Path,
) -> None:
    source, components, modules = _setup(tmp_path)
    service = ModuleRelationshipService(tmp_path)
    scope = RelationshipScope("scope-a", str(modules.modules[0]["id"]))
    original = _relationship(source, components, modules)
    duplicate_text = "\n".join(json.dumps(original) for _ in range(2))

    assert len(service.ingest_scope(scope, duplicate_text)) == 1

    conflict = {**original, "summary": "A contradictory explanation."}
    prompts = []

    def resolve(left, right, prompt):
        prompts.append(prompt)
        return original

    accepted = service.ingest_scope(
        scope,
        "\n".join(json.dumps(item) for item in (original, conflict)),
        conflict_resolver=resolve,
    )
    assert len(accepted) == 1
    assert "same frozen endpoints" in prompts[0]
    assert "create or reconcile components" in prompts[0]


def test_unknown_endpoint_becomes_targeted_request_not_canonical_edge(
    tmp_path: Path,
) -> None:
    source, components, modules = _setup(tmp_path)
    service = ModuleRelationshipService(tmp_path)
    scope = RelationshipScope("scope-a", str(modules.modules[0]["id"]))
    unknown = _relationship(
        source,
        components,
        modules,
        to_module_id="module:missing",
        supporting_component_ids=[components.components[0]["id"]],
    )

    assert service.ingest_scope(scope, json.dumps(unknown)) == []
    requests = service.store.read_jsonl(service.requests_path)
    assert requests[0]["request_type"] == "missing_endpoint"
    assert requests[0]["unknown_endpoint_ids"] == ["module:missing"]


def test_self_relationship_requires_explicit_reason(tmp_path: Path) -> None:
    source, components, modules = _setup(tmp_path)
    service = ModuleRelationshipService(tmp_path)
    module_id = str(modules.modules[0]["id"])
    scope = RelationshipScope("scope-a", module_id)
    self_edge = _relationship(
        source,
        components,
        modules,
        to_module_id=module_id,
        supporting_component_ids=[components.components[0]["id"]],
    )

    with pytest.raises(CodeLearnerError, match="self relationship"):
        service.ingest_scope(scope, json.dumps(self_edge))

    self_edge["self_relationship_reason"] = "The module schedules itself."
    assert service.ingest_scope(scope, json.dumps(self_edge))


def test_failed_scope_retries_without_rebuilding_completed_scope(
    tmp_path: Path,
) -> None:
    _setup(tmp_path)
    bootstrap = ModuleRelationshipService(tmp_path)
    first, second = bootstrap.scopes()
    bootstrap.ingest_scope(first, "")
    runtime = FakeRuntime(
        [
            AgentResult(False, "", error="temporary failure"),
            AgentResult(True, ""),
        ]
    )
    service = ModuleRelationshipService(
        tmp_path,
        runtime_factory=lambda role, root: runtime,
        max_attempts=2,
    )

    assert service.generate(analysis_run_id="run-1") == []
    assert len(runtime.invocations) == 2
    assert second.module_id in runtime.invocations[0].prompt
    assert (
        first.module_id
        not in runtime.invocations[0]
        .prompt.split("Relationship scope module ID: ", 1)[1]
        .splitlines()[0]
    )
