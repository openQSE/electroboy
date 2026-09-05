from __future__ import annotations

from pathlib import Path

import pytest

from electroboy.workflows.code_learner.analysis_passes import (
    ANALYSIS_PASSES,
    validate_pass_output,
)
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.orchestrator import analysis_pass_prompt


def _inventory() -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-inventory",
        "repository_revision": "revision",
    }
    source = {
        "path": "packages/api/main.py",
        "start_line": 1,
        "end_line": 1,
        "reason": "Python service entry point.",
    }
    entities = [
        ("repository.root", "repository"),
        ("build.api", "build-target"),
        ("entry.api", "entry-point"),
        ("test.api", "test-surface"),
    ]
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "mixed-monorepo",
            "scope_path": ".",
            "status": "inventory",
            "entity_count": len(entities),
            "relationship_count": 0,
            "flow_count": 0,
            "diagnostic_count": 1,
            "attributes": {
                "inventory": {
                    "languages": [
                        {"name": "Python", "evidence_paths": ["packages/api/main.py"]},
                        {"name": "TypeScript", "evidence_paths": ["packages/web/index.ts"]},
                    ],
                    "excluded_regions": [
                        {
                            "path": "vendor/",
                            "category": "vendored",
                            "reason": "Third-party source is outside learning scope.",
                        },
                        {
                            "path": "dist/",
                            "category": "generated",
                            "reason": "Rebuilt from tracked package sources.",
                        },
                    ],
                    "build_systems": ["Python packaging", "npm"],
                    "dependency_manifests": ["pyproject.toml", "package.json"],
                    "produced_artifact_ids": ["build.api"],
                    "entry_point_ids": ["entry.api"],
                    "public_surface_ids": ["entry.api"],
                    "process_ids": [],
                    "test_surface_ids": ["test.api"],
                    "external_system_ids": [],
                    "analysis_tools": [
                        {
                            "name": "repository-search",
                            "available": True,
                            "applies_to": ["Python", "TypeScript"],
                            "limitation": "Text search does not resolve dynamic dispatch.",
                        },
                        {
                            "name": "language-server",
                            "available": False,
                            "applies_to": [],
                            "limitation": "No server was detected; fallback remains available.",
                        },
                    ],
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
            "summary": f"Inventory entity for {record_id}.",
            "source_refs": [source],
            "confidence": "high",
        }
        for record_id, kind in entities
    )
    records.append(
        {
            **common,
            "record_type": "diagnostic",
            "id": "diagnostic.missing-docs",
            "severity": "warning",
            "message": "No architecture documentation was found.",
        }
    )
    return records


def test_inventory_contract_accepts_mixed_monorepo_and_explicit_exclusions() -> None:
    validate_pass_output(ANALYSIS_PASSES[0], _inventory())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("languages", None, "languages"),
        ("excluded_regions", [{"path": "dist/", "category": "generated"}], "reason"),
        ("entry_point_ids", ["entry.missing"], "unknown entity IDs"),
        (
            "analysis_tools",
            [{"name": "ctags", "available": True, "applies_to": []}],
            "limitation",
        ),
    ],
)
def test_inventory_contract_rejects_incomplete_categories(
    field: str, value: object, message: str
) -> None:
    records = _inventory()
    manifest = records[0]
    manifest["attributes"]["inventory"][field] = value  # type: ignore[index]

    with pytest.raises(CodeLearnerError, match=message):
        validate_pass_output(ANALYSIS_PASSES[0], records)


def test_inventory_prompt_defines_language_independent_scope(tmp_path: Path) -> None:
    prompt = analysis_pass_prompt(
        tmp_path,
        ANALYSIS_PASSES[0],
        run_id="run-inventory",
        revision="revision",
        store=KnowledgeStore(tmp_path),
    )

    assert "attributes.inventory" in prompt
    assert "Monorepo packages remain" in prompt
    assert "Missing documentation is not fatal" in prompt
    assert "available language-analysis tools" in prompt
    assert "excluded_regions" in prompt
