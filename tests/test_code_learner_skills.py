from __future__ import annotations

from pathlib import Path

import pytest

from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.skills import (
    packaged_skill_path,
    skill_prompt_reference,
    validate_packaged_skill,
)


def test_analysis_skill_is_discoverable_and_explicitly_referenceable() -> None:
    name = "codebase-analysis"
    path = packaged_skill_path(name)

    assert path.name == "SKILL.md"
    assert path.parent.name == name
    assert path.is_file()
    reference = skill_prompt_reference(name)
    assert reference.startswith(f"Use the ${name} skill at {path}.")
    assert "at least every five seconds" in reference
    assert "exactly one plain-text sentence" in reference
    assert "Never include source code, commands, command output" in reference
    assert validate_packaged_skill(name) == path


def test_unknown_skill_fails_before_runtime_invocation() -> None:
    with pytest.raises(CodeLearnerError, match="unknown Code Learner skill"):
        packaged_skill_path("unknown")


def test_analysis_skill_routes_to_focused_references() -> None:
    skill = packaged_skill_path("codebase-analysis")
    text = skill.read_text(encoding="utf-8")

    assert "not course prose" in text.lower()
    assert "repository-discovery.md" in text
    assert "knowledge-schema.md" in text
    assert "relationship-types.md" in text
    assert "language-tooling.md" in text
    assert "completeness-rules.md" in text
    for reference in _linked_references(skill):
        assert reference.is_file()


def _linked_references(skill: Path) -> list[Path]:
    references = skill.parent / "references"
    return sorted(references.glob("*.md"))
