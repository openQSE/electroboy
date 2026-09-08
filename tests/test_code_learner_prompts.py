from __future__ import annotations

from pathlib import Path

from electroboy.workflows.code_learner.prompts import (
    architecture_course_prompt,
    component_discovery_prompt,
    function_course_prompt,
    module_course_prompt,
    module_discovery_prompt,
    shared_instructions,
)


def test_shared_prompt_passes_append_only_raw_knowledge_contract() -> None:
    prompt = shared_instructions(Path("/course/raw-ai-knowledge"), "uuid-123")

    assert "/course/raw-ai-knowledge" in prompt
    assert "uuid-123" in prompt
    assert "Never edit, rename, replace, or delete" in prompt
    assert "request-flow-uuid-123.md" in prompt
    assert "Progress reporting" not in prompt
    assert "vendored dependencies" in prompt


def test_discovery_prompts_request_detailed_course_building_knowledge() -> None:
    root = Path("/repo")
    course = Path("/repo/.electroboy/code-learner/courses/repo")
    raw = course / "raw-ai-knowledge"
    components = course / "components.json"
    modules = course / "modules.json"

    component_prompt = component_discovery_prompt(
        root, course, raw, components, "component-uuid"
    )
    module_prompt = module_discovery_prompt(
        components, modules, raw, "module-uuid"
    )

    assert "comp-001" in component_prompt
    assert "as much detailed, reusable repository" in component_prompt
    assert "knowledge as possible" in component_prompt
    assert "A file may appear" not in component_prompt
    assert "lesson" not in component_prompt.split("Progress reporting", 1)[1].split(
        "Assign each component", 1
    )[0]
    assert "mod-001" in module_prompt
    assert "later course authors should not need to repeat" in module_prompt
    assert "slide" not in module_prompt.split("Progress reporting", 1)[1].split(
        "Assign each module", 1
    )[0]


def test_course_prompts_use_raw_knowledge_and_markdown_body_fields() -> None:
    course = Path("/repo/.electroboy/code-learner/courses/repo")
    raw = course / "raw-ai-knowledge"
    components = course / "components.json"
    modules = course / "modules.json"
    architecture = architecture_course_prompt(
        components, modules, raw, course / "architecture", "architecture-uuid"
    )
    module = module_course_prompt(
        "mod-001", components, modules, raw, course / "modules/mod-001", "mod-uuid"
    )
    function = function_course_prompt(
        "run", components, modules, raw, course / "functions/run", "function-uuid"
    )

    assert str(raw) in architecture
    assert "Do not repeat a\nrepository-wide code dive" in architecture
    for prompt in (architecture, module, function):
        assert "instructional content" in prompt or "instructional detail" in prompt
        assert "Markdown" in prompt
        assert "`body` field" in prompt
        assert "Approximately every ten" in prompt
        assert '"source_refs": [' in prompt
        assert '"path": "repository-relative/source/file.ext"' in prompt
        assert '"start_line": 40' in prompt
        assert '"end_line": 95' in prompt
        assert '"symbol": "important_symbol"' in prompt
        assert '"reason": "Why this source range supports the slide"' in prompt
        assert (
            "always write every section as exactly that\nform of JSON object"
            in prompt
        )
        assert "Do not omit, rename, or alias `source_refs`" in prompt
        assert "actually render it with Mermaid 11" in prompt
        assert "Mermaid-generated error diagrams as failures" in prompt
        assert "render it again" in prompt
