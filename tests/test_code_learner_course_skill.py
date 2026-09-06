from __future__ import annotations

from electroboy.workflows.code_learner.skills import (
    packaged_skill_path,
    validate_packaged_skill,
)


def test_course_skill_routes_by_mode_and_keeps_diagrams_capability_driven() -> None:
    skill = packaged_skill_path("code-learner-course")
    text = skill.read_text(encoding="utf-8")

    assert validate_packaged_skill("code-learner-course") == skill
    assert "architecture-course.md" in text
    assert "module-course.md" in text
    assert "function-course.md" in text
    assert "Do not emit `knowledge_request` records" in text
    assert all(path.is_file() for path in (skill.parent / "references").glob("*.md"))
    mermaid = (skill.parent / "references" / "mermaid-guidelines.md").read_text(
        encoding="utf-8"
    )
    module = (skill.parent / "references" / "module-course.md").read_text(
        encoding="utf-8"
    )
    assert "do not encode a closed per-mode allowlist" in mermaid
    assert "Every Mermaid syntax" in module
    request = (skill.parent / "references" / "knowledge-request.md").read_text(
        encoding="utf-8"
    )
    assert "Do not also emit document or section records" in request
