from __future__ import annotations

import copy
import json

import pytest

from electroboy.workflows.code_learner.analysis_passes import (
    ANALYSIS_PASSES,
    validate_pass_output,
)
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.orchestrator import analysis_pass_prompt
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore


def _module_knowledge() -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-modules",
        "repository_revision": "revision",
    }
    source = {
        "path": "src/transports/registry.py",
        "start_line": 1,
        "end_line": 8,
        "reason": "Registers transport implementations.",
    }
    catalog = {
        "major_module_ids": [
            "module.transport-core",
            "module.transport-memory",
            "module.transport-tcp",
        ],
        "extension_family_ids": ["family.transport"],
        "shared_infrastructure_module_ids": ["module.transport-core"],
        "coverage": {
            "candidate_count": 3,
            "module_count": 3,
            "implementation_candidate_count": 3,
            "implementation_module_count": 2,
            "excluded_count": 1,
            "evidence_paths_reviewed": [
                "src/transports/base.py",
                "src/transports/registry.py",
                "src/transports/memory.py",
                "src/transports/tcp.py",
            ],
        },
    }
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "transport-fixture",
            "scope_path": ".",
            "status": "modules",
            "entity_count": 6,
            "relationship_count": 0,
            "flow_count": 0,
            "diagnostic_count": 0,
            "attributes": {"inventory": {}, "module_catalog": catalog},
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": "transport-fixture",
            "summary": "Fixture repository.",
            "source_refs": [source],
            "confidence": "verified",
        },
        {
            **common,
            "record_type": "entity",
            "id": "interface.transport",
            "kind": "interface",
            "name": "Transport",
            "summary": "Transport extension contract.",
            "source_refs": [source],
            "confidence": "high",
        },
        {
            **common,
            "record_type": "entity",
            "id": "family.transport",
            "kind": "extension-family",
            "name": "Transport implementations",
            "summary": "Runtime-selected transports.",
            "parent_id": "repository.root",
            "source_refs": [source],
            "confidence": "high",
            "attributes": {
                "contract_ids": ["interface.transport"],
                "registration_ids": ["interface.transport"],
                "implementation_module_ids": [
                    "module.transport-memory",
                    "module.transport-tcp",
                ],
                "excluded_implementations": [
                    {
                        "name": "GeneratedTransport",
                        "reason": "Generated test double, not production behavior.",
                        "evidence_paths": ["generated/transport.py"],
                    }
                ],
            },
        },
    ]
    for module_id, family_id in (
        ("module.transport-core", ""),
        ("module.transport-memory", "family.transport"),
        ("module.transport-tcp", "family.transport"),
    ):
        records.append(
            {
                **common,
                "record_type": "entity",
                "id": module_id,
                "kind": "module",
                "name": module_id,
                "summary": f"Architectural module {module_id}.",
                "parent_id": "repository.root",
                "source_refs": [source],
                "confidence": "high",
                "attributes": {
                    "boundary_evidence": ["runtime registration", "interface"],
                    "interface_ids": ["interface.transport"],
                    "initial_dependency_ids": (
                        [] if module_id == "module.transport-core" else ["module.transport-core"]
                    ),
                    "extension_family_id": family_id,
                },
            }
        )
    return records


def test_module_contract_covers_every_extension_implementation() -> None:
    validate_pass_output(ANALYSIS_PASSES[1], _module_knowledge())


@pytest.mark.parametrize("family_name", ["plugin", "driver", "backend", "codec"])
def test_module_contract_is_independent_of_extension_family_naming(
    family_name: str,
) -> None:
    serialized = json.dumps(_module_knowledge()).replace("transport", family_name)

    validate_pass_output(ANALYSIS_PASSES[1], json.loads(serialized))


def test_module_contract_rejects_unlisted_implementation_module() -> None:
    records = _module_knowledge()
    family = next(record for record in records if record["id"] == "family.transport")
    family["attributes"]["implementation_module_ids"].remove(  # type: ignore[index]
        "module.transport-tcp"
    )

    # A family member cannot disappear from the family catalog silently.
    with pytest.raises(CodeLearnerError, match="must name family.transport"):
        validate_pass_output(ANALYSIS_PASSES[1], records)


def test_module_contract_requires_reason_for_excluded_implementation() -> None:
    records = copy.deepcopy(_module_knowledge())
    family = next(record for record in records if record["id"] == "family.transport")
    del family["attributes"]["excluded_implementations"][0]["reason"]  # type: ignore[index]

    with pytest.raises(CodeLearnerError, match="requires name, reason"):
        validate_pass_output(ANALYSIS_PASSES[1], records)


def test_module_prompt_uses_generic_discovery_and_repository_wide_scope(
    tmp_path,
) -> None:
    prompt = analysis_pass_prompt(
        tmp_path,
        ANALYSIS_PASSES[1],
        run_id="run-modules",
        revision="revision",
        store=KnowledgeStore(tmp_path),
    )

    assert "closed vocabulary" in prompt
    assert "runtime selection/dispatch patterns" in prompt
    assert "active branch" in prompt
    assert "implementation_module_ids" in prompt
