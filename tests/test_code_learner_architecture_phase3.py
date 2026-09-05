from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from code_learner_phase3_fixtures import build_catalog

from electroboy.adapters.base import AgentResult
from electroboy.workflows.code_learner.architecture_knowledge import (
    ArchitectureKnowledgeService,
)
from electroboy.workflows.code_learner.domain import CodeLearnerError


class FakeRuntime:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return AgentResult(True, json.dumps(self.output))


def _architecture(catalog) -> dict[str, object]:
    modules = [str(item["id"]) for item in catalog.modules.modules]
    components = [str(item["id"]) for item in catalog.components.components]
    relationship = str(catalog.relationships[0]["id"])
    symbol = dict(catalog.components.components[0]["symbols"][0])
    return {
        "schema_version": 1,
        "record_type": "architecture_knowledge",
        "repository_revision": catalog.source.revision,
        "id": "architecture:current",
        "title": "Repository Architecture",
        "body": "A structured architecture summary.",
        "module_ids": modules,
        "component_ids": components,
        "horizontal": {
            "repository_purpose": "A two-module fixture.",
            "external_boundaries": [],
            "entry_surfaces": ["function0"],
            "modules": [
                {"module_id": module_id, "summary": f"Covers {module_id}."}
                for module_id in modules
            ],
            "relationships": [relationship],
            "state": [],
            "build": {"summary": "Python source fixture."},
            "tests": {"summary": "Validated by unit tests."},
            "constraints": [],
        },
        "vertical_slices": [
            {
                "id": "slice:request",
                "title": "Request flow",
                "ordered_steps": [
                    {
                        "order": 1,
                        "module_id": modules[0],
                        "component_ids": [components[0]],
                        "summary": "The request enters.",
                        "symbol_locators": [symbol],
                        "source_refs": [
                            {
                                "file_id": "file:file0.py",
                                "start_line": 1,
                                "end_line": 2,
                                "reason": "Entry function.",
                            }
                        ],
                    },
                    {
                        "order": 2,
                        "module_id": modules[1],
                        "component_ids": [components[1]],
                        "summary": "The target responds.",
                        "symbol_locators": [],
                        "source_refs": [],
                    },
                ],
                "alternate_flows": ["No alternate in fixture."],
                "error_flows": ["Errors return to the caller."],
                "dynamic_behavior": ["Target may be replaced."],
                "unresolved": ["Runtime replacement is not statically proven."],
            }
        ],
        "diagrams": [
            {
                "id": "diagram:components",
                "type": "component",
                "title": "Components",
                "node_ids": modules,
                "relationship_ids": [relationship],
                "mermaid": (
                    f'flowchart LR\n A["{modules[0]}"] -->|{relationship}| '
                    f'B["{modules[1]}"]'
                ),
            },
            {
                "id": "diagram:sequence",
                "type": "sequence",
                "title": "Request sequence",
                "node_ids": modules,
                "relationship_ids": [relationship],
                "mermaid": (
                    "sequenceDiagram\n"
                    f" participant A as {modules[0]}\n"
                    f" participant B as {modules[1]}\n"
                    f" A->>B: {relationship}"
                ),
            },
        ],
        "deep_links": [
            {"target_type": "module", "target_id": modules[0]},
            {"target_type": "function", "target_id": symbol["canonical_key"]},
        ],
        "limitations": ["The dynamic target is inferred."],
    }


def test_architecture_validates_repository_breadth_vertical_flow_and_diagrams(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    artifact = _architecture(catalog)
    service = ArchitectureKnowledgeService(tmp_path, store=catalog.store)

    accepted = service.ingest(artifact)

    assert set(accepted["module_ids"]) == {
        item["id"] for item in catalog.modules.modules
    }
    assert accepted["vertical_slices"][0]["dynamic_behavior"]
    assert accepted["vertical_slices"][0]["unresolved"]
    assert (
        accepted["vertical_slices"][0]["ordered_steps"][0]["symbol_locators"][0][
            "canonical_key"
        ]
        == "symbol-0"
    )
    assert service.load()["id"] == "architecture:current"


@pytest.mark.parametrize("failure", ["breadth", "sequence", "stale-node", "fields"])
def test_architecture_rejects_incomplete_or_stale_knowledge(
    tmp_path: Path, failure: str
) -> None:
    catalog = build_catalog(tmp_path)
    artifact = _architecture(catalog)
    if failure == "breadth":
        artifact["module_ids"] = artifact["module_ids"][:1]
    elif failure == "sequence":
        artifact["diagrams"] = artifact["diagrams"][:1]
    elif failure == "stale-node":
        artifact["diagrams"][0]["node_ids"] = ["module:stale"]
    else:
        del artifact["horizontal"]["constraints"]

    with pytest.raises(CodeLearnerError):
        ArchitectureKnowledgeService(tmp_path, store=catalog.store).ingest(artifact)


def test_architecture_generation_prompt_uses_frozen_manifests_and_retries(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    artifact = _architecture(catalog)
    runtime = FakeRuntime(copy.deepcopy(artifact))
    service = ArchitectureKnowledgeService(
        tmp_path,
        store=catalog.store,
        runtime_factory=lambda role, root: runtime,
    )

    assert service.generate(analysis_run_id="run-1")["id"] == "architecture:current"
    prompt = runtime.invocations[0].prompt
    assert "Frozen component manifest" in prompt
    assert "Frozen module manifest" in prompt
    assert "Do not narrow scope" in prompt
    assert "sequence diagram" in prompt
