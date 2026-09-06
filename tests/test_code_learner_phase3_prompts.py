from __future__ import annotations

from pathlib import Path

from electroboy.workflows.code_learner.component_contract import (
    COMPONENT_CANDIDATE_REQUIRED_FIELDS,
    COMPONENT_CONFIDENCE_VALUES,
)
from electroboy.workflows.code_learner.phase3_contract_catalog import (
    AGENT_RECORD_REQUIRED_FIELDS,
)
from electroboy.workflows.code_learner.phase3_prompts import (
    architecture_knowledge_prompt,
    component_discovery_prompt,
    component_reconciliation_prompt,
    function_knowledge_prompt,
    module_knowledge_prompt,
    module_relationship_prompt,
    module_synthesis_prompt,
)


def test_component_discovery_prompt_is_bounded_file_backed_and_read_only(
    tmp_path: Path,
) -> None:
    prompt = component_discovery_prompt(
        tmp_path,
        analysis_run_id="run-1",
        repository_revision="revision-1",
        source_manifest_path="source/manifest.json",
        files_path="source/files.jsonl",
        ctags_path="source/universal-ctags.raw.jsonl",
        schema_path="schemas/phase3.schema.json",
        prior_artifact_paths=("components/attempt-1.jsonl",),
    )

    assert "Use the $codebase-analysis skill" in prompt
    assert "source/files.jsonl" in prompt
    assert "source/universal-ctags.raw.jsonl" in prompt
    assert "components/attempt-1.jsonl" in prompt
    assert "component_candidate" in prompt
    assert "source-oriented symbol locators" in prompt
    assert "Do not emit" in prompt
    assert "modules" in prompt and "relationships" in prompt
    assert "Do not modify" in prompt
    assert "Do not build, compile, link, test, or execute" in prompt
    assert "at least every five seconds" in prompt
    assert "exactly one plain-text sentence" in prompt
    assert "Never include source code, commands, command output" in prompt
    assert "Use `reason`, never `role`" in prompt
    assert "Do not use a numeric score" in prompt
    for field in COMPONENT_CANDIDATE_REQUIRED_FIELDS:
        assert field in prompt
    for confidence in COMPONENT_CONFIDENCE_VALUES:
        assert f"`{confidence}`" in prompt


def test_component_discovery_skill_describes_phase3_boundaries() -> None:
    skill_root = (
        Path(__file__).parents[1]
        / "src/electroboy/workflows/code_learner/skills/codebase-analysis"
    )
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    schema_reference = (skill_root / "references/knowledge-schema.md").read_text(
        encoding="utf-8"
    )

    assert "Component discovery must not" in skill
    assert "same` or `distinct" in skill
    assert "do not write output or checkpoints directly" in skill
    for field in COMPONENT_CANDIDATE_REQUIRED_FIELDS:
        assert f"`{field}`" in schema_reference


def test_every_ai_prompt_includes_its_complete_record_contract(
    tmp_path: Path,
) -> None:
    common = {
        "analysis_run_id": "run-1",
        "repository_revision": "revision-1",
    }
    prompts = {
        "component_reconciliation": component_reconciliation_prompt(
            tmp_path,
            analysis_run_id="run-1",
            group={
                "repository_revision": "revision-1",
                "id": "overlap:1",
            },
            candidates=[],
            source_paths=[],
        ),
        "module": module_synthesis_prompt(
            tmp_path,
            **common,
            source_manifest_path="source/manifest.json",
            component_manifest_path="components/manifest.json",
            components_path="components/components.jsonl",
            schema_path="schemas/phase3.schema.json",
        ),
        "module_relationship": module_relationship_prompt(
            tmp_path,
            **common,
            source_manifest_path="source/manifest.json",
            component_manifest_path="components/manifest.json",
            components_path="components/components.jsonl",
            module_manifest_path="modules/manifest.json",
            modules_path="modules/modules.jsonl",
            relationship_kinds=["calls"],
            schema_path="schemas/phase3.schema.json",
        ),
        "architecture_knowledge": architecture_knowledge_prompt(
            tmp_path,
            **common,
            source_manifest_path="source/manifest.json",
            component_manifest_path="components/manifest.json",
            module_manifest_path="modules/manifest.json",
            relationships_path="modules/relationships.jsonl",
            schema_path="schemas/phase3.schema.json",
        ),
        "module_knowledge": module_knowledge_prompt(
            tmp_path,
            **common,
            module_id="module:1",
            source_manifest_path="source/manifest.json",
            component_manifest_path="components/manifest.json",
            module_manifest_path="modules/manifest.json",
            relationships_path="modules/relationships.jsonl",
            schema_path="schemas/phase3.schema.json",
        ),
        "function_knowledge": function_knowledge_prompt(
            tmp_path,
            **common,
            symbol={"canonical_key": "symbol:1"},
            component_ids=["component:1"],
            module_ids=["module:1"],
            source_manifest_path="source/manifest.json",
            component_manifest_path="components/manifest.json",
            module_manifest_path="modules/manifest.json",
            architecture_knowledge_path="knowledge/architecture.jsonl",
            module_knowledge_path="knowledge/modules",
            schema_path="schemas/phase3.schema.json",
        ),
    }

    for record_type, fields in AGENT_RECORD_REQUIRED_FIELDS.items():
        for field in fields:
            assert f"`{field}`" in prompts[record_type]
