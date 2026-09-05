from __future__ import annotations

import json
from pathlib import Path

import pytest
from code_learner_phase3_fixtures import build_catalog

from electroboy.adapters.base import AgentResult
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.function_knowledge import (
    FunctionKnowledgeService,
)


class FakeRuntime:
    def __init__(self, outputs: list[AgentResult]) -> None:
        self.outputs = outputs
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return self.outputs.pop(0)


def _artifact(catalog, index: int = 0) -> dict[str, object]:
    symbol = dict(catalog.components.components[index]["symbols"][0])
    other = dict(catalog.components.components[1 - index]["symbols"][0])
    component_id = str(catalog.components.components[index]["id"])
    module_ids = [
        str(module["id"])
        for module in catalog.modules.modules
        if component_id in module["component_ids"]
    ]
    return {
        "schema_version": 1,
        "record_type": "function_knowledge",
        "repository_revision": catalog.source.revision,
        "id": f"function-knowledge:{symbol['canonical_key']}",
        "title": f"Function {symbol['name']}",
        "body": "Structured Function knowledge.",
        "symbol": symbol,
        "component_ids": [component_id],
        "module_ids": module_ids,
        "purpose": "Implements one fixture operation.",
        "contract": {
            "inputs": [],
            "outputs": ["integer"],
            "preconditions": [],
            "postconditions": [],
        },
        "local_flow": ["Directly returns a fixture value."],
        "callers": [],
        "callees": [other],
        "state": [],
        "errors": [],
        "concurrency": [],
        "tests": ["Covered by Phase 3 fixture tests."],
        "limitations": ["A dynamic replacement is not statically visible."],
        "call_edges": [
            {
                "from_symbol_key": symbol["canonical_key"],
                "to_symbol_key": other["canonical_key"],
                "confidence": "direct",
                "summary": "Direct fixture call.",
            },
            {
                "from_symbol_key": symbol["canonical_key"],
                "to_symbol_key": other["canonical_key"],
                "confidence": "dynamic",
                "summary": "Dynamic replacement may intercept the call.",
            },
        ],
        "diagrams": [
            {
                "id": "diagram:call",
                "type": "flowchart",
                "node_ids": [symbol["canonical_key"], other["canonical_key"]],
                "relationship_ids": [],
                "mermaid": (
                    f'flowchart LR\n A["{symbol["canonical_key"]}"] --> '
                    f'B["{other["canonical_key"]}"]'
                ),
            }
        ],
    }


def test_function_resolution_preserves_exact_partial_ambiguous_and_missing(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = FunctionKnowledgeService(tmp_path, store=catalog.store)

    assert service.resolve("symbol-0").status == "exact"
    assert service.resolve("function0").status == "exact"
    assert service.resolve("tion0").status == "partial"
    assert service.resolve("function").status == "ambiguous"
    assert service.resolve("absent").status == "missing"


def test_qualified_resolution_and_ambiguity_require_user_disambiguation(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    records = catalog.store.read_jsonl(catalog.component_service.components_path)
    records[0]["symbols"][0]["scope"] = "Fixture"
    catalog.store.write_jsonl(catalog.component_service.components_path, records)
    service = FunctionKnowledgeService(tmp_path, store=catalog.store)

    assert service.resolve("Fixture.function0").status == "qualified"
    with pytest.raises(CodeLearnerError, match="ambiguous; choose"):
        service.generate("function", analysis_run_id="run-1")


def test_function_artifact_validates_flow_call_confidence_diagram_and_links(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = FunctionKnowledgeService(tmp_path, store=catalog.store)
    artifact = _artifact(catalog)

    accepted = service.ingest("symbol-0", artifact)

    assert accepted["call_edges"][0]["confidence"] == "direct"
    assert accepted["call_edges"][1]["confidence"] == "dynamic"
    assert accepted["cache_key"] == service._cache_key(
        catalog.source.revision, "symbol-0"
    )
    assert service.load("symbol-0")["id"] == artifact["id"]
    link = catalog.store.read_jsonl(service.links_path)[0]
    assert link["architecture_target_id"] == "architecture:current"
    assert link["module_ids"] == artifact["module_ids"]
    assert service._path("new-revision", "symbol-0") != service._path(
        catalog.source.revision, "symbol-0"
    )


def test_important_selection_requires_canonical_keys_and_obeys_budget(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = FunctionKnowledgeService(tmp_path, store=catalog.store, eager_budget=1)
    payload = {
        "selections": [
            {"canonical_key": "symbol-0", "importance": 50, "reason": "Entry."},
            {"canonical_key": "symbol-1", "importance": 90, "reason": "Core."},
        ]
    }

    selected = service.select_important(json.dumps(payload))

    assert selected == [
        {"canonical_key": "symbol-1", "importance": 90, "reason": "Core."}
    ]
    with pytest.raises(CodeLearnerError, match="not an exact canonical"):
        service.select_important(
            json.dumps(
                {
                    "selections": [
                        {
                            "canonical_key": "function0",
                            "importance": 100,
                            "reason": "Not canonical.",
                        }
                    ]
                }
            )
        )


def test_uncached_on_demand_generation_does_not_touch_initialization(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    artifact = _artifact(catalog)
    runtime = FakeRuntime([AgentResult(True, json.dumps(artifact))])
    service = FunctionKnowledgeService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: runtime,
    )
    catalog.store.write_json(
        catalog.store.checkpoint_path, {"status": "complete", "sentinel": 1}
    )

    accepted = service.generate("function0", analysis_run_id="on-demand")

    assert accepted["symbol"]["canonical_key"] == "symbol-0"
    assert len(runtime.invocations) == 1
    assert "Do not analyze an alternate symbol" in runtime.invocations[0].prompt
    assert catalog.store.read_json(catalog.store.checkpoint_path) == {
        "status": "complete",
        "sentinel": 1,
    }


def test_eager_selection_generates_only_ranked_budgeted_function(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    selection = {
        "selections": [
            {
                "canonical_key": "symbol-0",
                "importance": 100,
                "reason": "Entry surface and vertical flow.",
            }
        ]
    }
    selection_runtime = FakeRuntime([AgentResult(True, json.dumps(selection))])
    generation_runtime = FakeRuntime(
        [AgentResult(True, json.dumps(_artifact(catalog)))]
    )
    service = FunctionKnowledgeService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: generation_runtime,
        eager_budget=1,
    )

    generated = service.eager_generate(
        analysis_run_id="run-1", selection_runtime=selection_runtime
    )

    assert [item["symbol"]["canonical_key"] for item in generated] == ["symbol-0"]
    assert "vertical flows" in selection_runtime.invocations[0].prompt
    assert len(generation_runtime.invocations) == 1


@pytest.mark.parametrize("failure", ["target", "context", "confidence"])
def test_function_validation_rejects_drift_and_bad_call_evidence(
    tmp_path: Path, failure: str
) -> None:
    catalog = build_catalog(tmp_path)
    artifact = _artifact(catalog)
    if failure == "target":
        artifact["symbol"] = catalog.components.components[1]["symbols"][0]
    elif failure == "context":
        artifact["component_ids"] = []
    else:
        artifact["call_edges"][0]["confidence"] = "certain"

    with pytest.raises(CodeLearnerError):
        FunctionKnowledgeService(tmp_path, store=catalog.store).ingest(
            "symbol-0", artifact
        )
