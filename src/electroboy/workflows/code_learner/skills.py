"""Discovery for Code Learner skills packaged with the workflow."""

from __future__ import annotations

import re
from pathlib import Path

from .domain import CodeLearnerError

SKILL_NAMES = frozenset({"codebase-analysis", "code-learner-course"})


def packaged_skill_path(name: str) -> Path:
    """Return the validated SKILL.md path for a bundled learner skill."""

    normalized = str(name or "").strip().lower()
    if normalized not in SKILL_NAMES:
        expected = ", ".join(sorted(SKILL_NAMES))
        raise CodeLearnerError(f"unknown Code Learner skill; expected {expected}")
    path = Path(__file__).with_name("skills") / normalized / "SKILL.md"
    if not path.is_file():
        raise CodeLearnerError(
            f"required Code Learner skill is not installed: {normalized}"
        )
    return path.resolve()


def skill_prompt_reference(name: str) -> str:
    """Build the explicit instruction used by runtime prompts."""

    return f"""Use the ${name} skill at {packaged_skill_path(name)}.

Progress updates:
- While actively working, emit one brief status update in the runtime
  commentary/status channel at least every five seconds and whenever your
  focus changes.
- Each update must be exactly one plain-text sentence describing the current
  conceptual task or finding.
- Never include source code, commands, command output, JSON, file contents,
  paths, line numbers, private reasoning, or implementation traces.
- Progress updates are separate from the final structured response and must
  not be included in its JSONL."""


def validate_packaged_skill(name: str) -> Path:
    """Fail fast when a bundled skill is malformed or incomplete."""

    path = packaged_skill_path(name)
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise CodeLearnerError(f"invalid {name} skill frontmatter")
    frontmatter = parts[1]
    expected_name = f"name: {name}"
    description = next(
        (
            line.partition(":")[2].strip()
            for line in frontmatter.splitlines()
            if line.startswith("description:")
        ),
        "",
    )
    if expected_name not in frontmatter or not description:
        raise CodeLearnerError(f"invalid {name} skill identity or description")
    if any(marker in text for marker in ("TODO", "PLACEHOLDER", "{{")):
        raise CodeLearnerError(f"unfinished {name} skill content")
    for relative in re.findall(r"\((references/[^)]+\.md)\)", text):
        reference = path.parent / relative
        if not reference.is_file():
            raise CodeLearnerError(
                f"{name} skill references a missing file: {relative}"
            )
    return path
