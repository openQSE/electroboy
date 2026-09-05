from __future__ import annotations

from pathlib import Path

from electroboy.workflows.code_learner.phase3_prompts import (
    component_discovery_prompt,
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


def test_component_discovery_skill_describes_phase3_boundaries() -> None:
    skill = (
        Path(__file__).parents[1]
        / "src/electroboy/workflows/code_learner/skills/codebase-analysis/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "Component discovery must not" in skill
    assert "same` or `distinct" in skill
    assert "do not write output or checkpoints directly" in skill
