from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from code_learner_phase3_fixtures import build_catalog

from electroboy.adapters.base import AgentResult
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.module_knowledge import (
    ModuleKnowledgeService,
)


class FakeRuntime:
    def __init__(self, outputs: list[AgentResult]) -> None:
        self.outputs = outputs
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return self.outputs.pop(0)


def _artifact(catalog, index: int = 0) -> dict[str, object]:
    module = catalog.modules.modules[index]
    module_id = str(module["id"])
    members = list(module["component_ids"])
    relationships = [
        item
        for item in catalog.relationships
        if module_id in {item["from_module_id"], item["to_module_id"]}
    ]
    relationship_ids = [str(item["id"]) for item in relationships]
    neighbor_ids = sorted(
        {
            str(endpoint)
            for item in relationships
            for endpoint in (item["from_module_id"], item["to_module_id"])
            if endpoint != module_id
        }
    )
    symbols = [
        dict(component["symbols"][0])
        for component in catalog.components.components
        if component["id"] in members
    ]
    diagrams = []
    if relationships:
        neighbor = neighbor_ids[0]
        edge = relationship_ids[0]
        diagrams = [
            {
                "id": f"diagram:{index}:flow",
                "type": "flowchart",
                "node_ids": [module_id, neighbor],
                "relationship_ids": [edge],
                "mermaid": (
                    f'flowchart LR\n A["{module_id}"] -->|{edge}| B["{neighbor}"]'
                ),
            },
            {
                "id": f"diagram:{index}:sequence",
                "type": "sequence",
                "node_ids": [module_id, neighbor],
                "relationship_ids": [edge],
                "mermaid": (
                    f"sequenceDiagram\n participant A as {module_id}\n"
                    f" participant B as {neighbor}\n A->>B: {edge}"
                ),
            },
        ]
    return {
        "schema_version": 1,
        "record_type": "module_knowledge",
        "repository_revision": catalog.source.revision,
        "id": f"module-knowledge:{module_id}",
        "module_id": module_id,
        "title": str(module["name"]),
        "body": "Structured module knowledge.",
        "module_ids": [module_id],
        "component_ids": members,
        "horizontal": {
            "purpose": module["purpose"],
            "interfaces": [],
            "relationship_ids": relationship_ids,
            "configuration": [],
            "state": [],
            "tests": [],
            "risks": ["Dynamic dispatch is not represented in this fixture."],
            "peer_navigation": neighbor_ids,
        },
        "vertical": {
            "components": [
                {"component_id": component_id, "summary": "Member component."}
                for component_id in members
            ],
            "initialization": [],
            "normal_flow": ["Calls the neighboring module when configured."],
            "alternate_flow": [],
            "errors": [],
            "data": [],
            "concurrency": [],
            "important_functions": symbols,
        },
        "diagrams": diagrams,
        "peer_links": [
            {"target_type": "module", "target_id": neighbor_id}
            for neighbor_id in neighbor_ids
        ],
        "deep_links": [
            {
                "target_type": "function",
                "target_id": symbol["canonical_key"],
            }
            for symbol in symbols
        ],
        "intentional_component_overlap": [],
        "limitations": ["Fixture knowledge is intentionally small."],
    }


def test_module_knowledge_validates_horizontal_vertical_and_multiple_diagrams(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = ModuleKnowledgeService(tmp_path, store=catalog.store)
    artifact = _artifact(catalog)

    accepted = service.ingest(str(artifact["module_id"]), artifact)

    assert accepted["horizontal"]["relationship_ids"] == [
        catalog.relationships[0]["id"]
    ]
    assert accepted["vertical"]["important_functions"][0]["canonical_key"] == "symbol-0"
    assert len(accepted["diagrams"]) == 2
    assert service.load(str(artifact["module_id"]))["id"] == artifact["id"]


def test_module_without_relationships_or_diagrams_is_valid(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path, relationship=False)
    artifact = _artifact(catalog)

    accepted = ModuleKnowledgeService(tmp_path, store=catalog.store).ingest(
        str(artifact["module_id"]), artifact
    )

    assert accepted["horizontal"]["relationship_ids"] == []
    assert accepted["diagrams"] == []


def test_module_normalizes_legacy_component_ids(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path)
    artifact = _artifact(catalog)
    for component in artifact["vertical"]["components"]:
        component["id"] = component.pop("component_id")

    accepted = ModuleKnowledgeService(tmp_path, store=catalog.store).ingest(
        str(artifact["module_id"]), artifact
    )

    assert all(
        item["component_id"] in accepted["component_ids"]
        for item in accepted["vertical"]["components"]
    )


@pytest.mark.parametrize("failure", ["member", "neighbor", "diagram", "navigation"])
def test_module_knowledge_rejects_stale_or_conflated_references(
    tmp_path: Path, failure: str
) -> None:
    catalog = build_catalog(tmp_path)
    artifact = _artifact(catalog)
    if failure == "member":
        artifact["component_ids"] = []
    elif failure == "neighbor":
        artifact["horizontal"]["relationship_ids"] = []
    elif failure == "diagram":
        artifact["diagrams"][0]["node_ids"] = ["module:stale"]
    else:
        artifact["deep_links"] = copy.deepcopy(artifact["peer_links"])

    with pytest.raises(CodeLearnerError):
        ModuleKnowledgeService(tmp_path, store=catalog.store).ingest(
            str(artifact["module_id"]), artifact
        )


def test_module_generation_retries_only_uncached_module(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path)
    first = _artifact(catalog, 0)
    second = _artifact(catalog, 1)
    service = ModuleKnowledgeService(tmp_path, store=catalog.store)
    service.ingest(str(first["module_id"]), first)
    runtime = FakeRuntime(
        [
            AgentResult(False, "partial", error="module analysis timed out"),
            AgentResult(True, json.dumps(second)),
        ]
    )
    service.runtime_factory = lambda role, root: runtime

    generated = service.generate_all(analysis_run_id="run-1")

    assert len(generated) == 2
    assert len(runtime.invocations) == 2
    assert str(second["module_id"]) in runtime.invocations[0].prompt
    assert (
        str(first["module_id"])
        not in runtime.invocations[0]
        .prompt.split("Module scope ID: ", 1)[1]
        .splitlines()[0]
    )


def test_module_generation_retries_malformed_json(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path)
    artifact = _artifact(catalog)
    runtime = FakeRuntime(
        [
            AgentResult(True, '{"record_type":"module_knowledge"'),
            AgentResult(True, json.dumps(artifact)),
        ]
    )
    service = ModuleKnowledgeService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: runtime,
    )

    accepted = service.generate(str(artifact["module_id"]), analysis_run_id="run-1")

    assert accepted["module_id"] == artifact["module_id"]
    assert len(runtime.invocations) == 2


def test_module_generation_does_not_retry_semantic_failure(tmp_path: Path) -> None:
    catalog = build_catalog(tmp_path)
    invalid = _artifact(catalog)
    invalid["component_ids"] = []
    runtime = FakeRuntime(
        [
            AgentResult(True, json.dumps(invalid)),
            AgentResult(True, json.dumps(_artifact(catalog))),
        ]
    )
    service = ModuleKnowledgeService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: runtime,
    )

    with pytest.raises(CodeLearnerError, match="cover every member component"):
        service.generate(str(invalid["module_id"]), analysis_run_id="run-1")

    assert len(runtime.invocations) == 1


def test_many_and_repeated_components_preserve_vertical_membership(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path, relationship=False)
    revision = catalog.source.revision
    component_ids = [str(item["id"]) for item in catalog.components.components]
    records = [
        {
            "schema_version": 1,
            "record_type": "module",
            "repository_revision": revision,
            "id": "many",
            "name": "Many components",
            "kind": "subsystem",
            "purpose": "Groups both components.",
            "responsibility": "Coordinates both components.",
            "component_ids": component_ids,
            "primary_component_ids": [component_ids[0]],
            "entry_component_ids": [component_ids[0]],
            "primary_for_component_ids": component_ids,
            "grouping_rationale": "Both components form one flow.",
            "repeated_component_rationales": {
                component_ids[1]: "Also shown in the supporting view."
            },
            "source_refs": [],
            "confidence": "high",
            "limitations": [],
        },
        {
            "schema_version": 1,
            "record_type": "module",
            "repository_revision": revision,
            "id": "supporting",
            "name": "Supporting view",
            "kind": "view",
            "purpose": "Shows a second architectural view.",
            "responsibility": "Explains supporting behavior.",
            "component_ids": [component_ids[1]],
            "primary_component_ids": [component_ids[1]],
            "entry_component_ids": [],
            "primary_for_component_ids": [],
            "grouping_rationale": "The component has two useful views.",
            "repeated_component_rationales": {
                component_ids[1]: "Also belongs to the main flow."
            },
            "source_refs": [],
            "confidence": "high",
            "limitations": [],
        },
    ]
    catalog.modules = catalog.module_service.ingest(records, analysis_run_id="run-1")
    artifact = _artifact(catalog, 0)

    accepted = ModuleKnowledgeService(tmp_path, store=catalog.store).ingest(
        str(artifact["module_id"]), artifact
    )

    assert set(accepted["component_ids"]) == set(component_ids)
    assert len(accepted["vertical"]["components"]) == 2
