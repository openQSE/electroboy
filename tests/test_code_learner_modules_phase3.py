from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.adapters.base import AgentResult
from electroboy.workflows.code_learner.component_manifest import (
    ComponentManifestService,
    ComponentManifestSnapshot,
)
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.modules import ModuleSynthesisService
from electroboy.workflows.code_learner.overlap import ComponentOverlapService
from electroboy.workflows.code_learner.phase3_store import Phase3Store
from electroboy.workflows.code_learner.source_manifest import SourceManifestService


class FakeRuntime:
    def __init__(self, outputs: list[AgentResult]) -> None:
        self.outputs = outputs
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return self.outputs.pop(0)


def _components(root: Path, count: int = 2) -> ComponentManifestSnapshot:
    for index in range(count):
        (root / f"file{index}.py").write_text(
            f"def function{index}():\n    return {index}\n", encoding="utf-8"
        )
    source = SourceManifestService(root)
    source_snapshot = source.generate()
    candidates = []
    for index in range(count):
        candidates.append(
            {
                "schema_version": 1,
                "record_type": "component_candidate",
                "repository_revision": source_snapshot.revision,
                "candidate_id": f"candidate-{index}",
                "name": f"Component {index}",
                "kind": "service",
                "responsibility": f"Owns function {index}.",
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
    return ComponentManifestService(root, store=store).build(analysis_run_id="run-1")


def _module(
    module_id: str,
    component_ids: list[str],
    revision: str,
    **extra,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "module",
        "repository_revision": revision,
        "id": module_id,
        "name": f"Module {module_id}",
        "kind": "subsystem",
        "purpose": "Groups related behavior.",
        "responsibility": "Coordinates its member components.",
        "component_ids": component_ids,
        "primary_component_ids": component_ids[:1],
        "entry_component_ids": component_ids[:1],
        "primary_for_component_ids": component_ids,
        "grouping_rationale": "The components implement one responsibility.",
        "source_refs": [],
        "confidence": "high",
        "limitations": [],
        **extra,
    }


def test_module_manifest_freezes_complete_grouping_with_opaque_ids(
    tmp_path: Path,
) -> None:
    components = _components(tmp_path)
    ids = list(components.manifest["component_ids"])
    service = ModuleSynthesisService(tmp_path)

    snapshot = service.ingest(
        [_module("temporary-parent", ids, components.manifest["repository_revision"])],
        analysis_run_id="run-1",
    )

    module = snapshot.modules[0]
    assert module["id"].startswith("module:")
    assert "temporary-parent" not in module["id"]
    assert module["origin_module_id"] == "temporary-parent"
    assert snapshot.manifest["frozen"] is True
    assert snapshot.manifest["primary_module_by_component"] == {
        ids[0]: module["id"],
        ids[1]: module["id"],
    }
    assert service.by_component(ids[0])[0]["id"] == module["id"]


def test_intentionally_ungrouped_component_is_explicit(tmp_path: Path) -> None:
    components = _components(tmp_path, count=1)
    component_id = str(components.manifest["component_ids"][0])
    module = _module(
        "ungrouped",
        [component_id],
        str(components.manifest["repository_revision"]),
        kind="intentionally_ungrouped",
        grouping_rationale="No stable architectural grouping is supported.",
    )

    snapshot = ModuleSynthesisService(tmp_path).ingest(
        [module], analysis_run_id="run-1"
    )

    assert snapshot.modules[0]["kind"] == "intentionally_ungrouped"


def test_repeated_membership_requires_explicit_rationale(tmp_path: Path) -> None:
    components = _components(tmp_path, count=1)
    revision = str(components.manifest["repository_revision"])
    component_id = str(components.manifest["component_ids"][0])
    modules = [
        _module("a", [component_id], revision),
        _module(
            "b",
            [component_id],
            revision,
            primary_for_component_ids=[],
        ),
    ]
    service = ModuleSynthesisService(tmp_path)

    with pytest.raises(CodeLearnerError, match="rationales is incomplete"):
        service.ingest(modules, analysis_run_id="run-1")

    for module in modules:
        module["repeated_component_rationales"] = {
            component_id: "This module provides a distinct architectural view."
        }
    assert len(service.ingest(modules, analysis_run_id="run-1").modules) == 2


@pytest.mark.parametrize("failure", ["cycle", "unknown", "source"])
def test_module_validation_rejects_cycles_unknown_components_and_foreign_source(
    tmp_path: Path, failure: str
) -> None:
    components = _components(tmp_path, count=2)
    revision = str(components.manifest["repository_revision"])
    ids = list(components.manifest["component_ids"])
    modules = [
        _module("a", [ids[0]], revision, parent_module_id="b"),
        _module("b", [ids[1]], revision),
    ]
    if failure == "cycle":
        modules[1]["parent_module_id"] = "a"
    elif failure == "unknown":
        modules[0]["component_ids"] = ["component:missing"]
    else:
        modules[0]["source_refs"] = [
            {
                "file_id": "file:file1.py",
                "start_line": 1,
                "end_line": 2,
                "reason": "Not owned by module a.",
            }
        ]

    with pytest.raises(CodeLearnerError):
        ModuleSynthesisService(tmp_path).ingest(modules, analysis_run_id="run-1")


def test_targeted_missing_component_request_retries_only_affected_scope(
    tmp_path: Path,
) -> None:
    components = _components(tmp_path, count=1)
    revision = str(components.manifest["repository_revision"])
    existing_id = str(components.manifest["component_ids"][0])
    new_id = "component:targeted-new"
    request = {
        "schema_version": 1,
        "record_type": "knowledge_request",
        "repository_revision": revision,
        "id": "request:missing-component",
        "request_type": "missing_component",
        "status": "open",
        "reason": "A source-backed component is absent.",
        "source_refs": [
            {
                "file_id": "file:file0.py",
                "start_line": 1,
                "end_line": 2,
                "reason": "Defines the missing behavior.",
            }
        ],
    }
    second_modules = [
        _module("existing", [existing_id], revision),
        _module("targeted", [new_id], revision),
    ]
    runtime = FakeRuntime(
        [
            AgentResult(True, json.dumps(request)),
            AgentResult(True, "\n".join(json.dumps(item) for item in second_modules)),
        ]
    )
    service = ModuleSynthesisService(
        tmp_path,
        runtime_factory=lambda role, root: runtime,
        max_attempts=2,
    )

    def targeted(requests) -> ComponentManifestSnapshot:
        assert requests[0]["request_type"] == "missing_component"
        current = service.components.load()
        new_component = {
            **current.components[0],
            "id": new_id,
            "name": "Targeted component",
            "origin_candidate_ids": ["targeted-candidate"],
        }
        records = [*current.components, new_component]
        manifest = {
            **current.manifest,
            "component_ids": [existing_id, new_id],
            "component_count": 2,
        }
        service.store.write_jsonl(service.components.components_path, records)
        service.store.write_json(service.components.manifest_path, manifest)
        return ComponentManifestSnapshot(
            manifest, tuple(records), current.dispositions, current.coverage
        )

    snapshot = service.synthesize(analysis_run_id="run-1", targeted_discovery=targeted)

    assert len(snapshot.modules) == 2
    assert new_id in runtime.invocations[1].prompt
    assert "Affected component scope" in runtime.invocations[1].prompt
    assert service.store.read_jsonl(service.requests_path)[0]["id"] == request["id"]
