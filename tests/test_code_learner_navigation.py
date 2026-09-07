from __future__ import annotations

import json
from pathlib import Path

from electroboy.workflows.code_learner.navigation import CourseNavigator
from electroboy.workflows.code_learner.store import LearnerStore


def _write_course(root: Path) -> LearnerStore:
    store = LearnerStore(root)
    store.initialize_layout()
    store.components_path.write_text(
        json.dumps(
            [
                {
                    "eb_comp_id": "comp-001",
                    "ai_component_name": "Request Parser",
                    "ai_file_list": ["src/parser.py"],
                }
            ]
        ),
        encoding="utf-8",
    )
    store.modules_path.write_text(
        json.dumps(
            [
                {
                    "eb_module_id": "mod-001",
                    "ai_module_name": "Runtime",
                    "ai_comp_list": ["comp-001"],
                }
            ]
        ),
        encoding="utf-8",
    )
    for concept_name, lesson_name, slide_names in (
        ("01.Context", "01.Overview.jsonl", ("Purpose", "Parts")),
        ("02.Flow", "01.Overview.jsonl", ("Request flow",)),
    ):
        concept = store.architecture_root / concept_name
        concept.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "record_type": "document",
                "id": f"{concept_name}-lesson",
                "title": "Overview",
            },
            *[
                {
                    "record_type": "section",
                    "id": f"{concept_name}-{index}",
                    "order": index * 10,
                    "title": title,
                    "body": (
                        f"**{title}** details for mod-001 and comp-001\n\n"
                        "| Item | Owner |\n| --- | --- |\n| Parse | comp-001 |"
                    ),
                }
                for index, title in enumerate(slide_names, 1)
            ],
        ]
        (concept / lesson_name).write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )
    store.course_index_path("architecture").write_text(
        json.dumps(
            {
                "course_type": "architecture",
                "course_title": "Repository Architecture",
                "concepts": [
                    {
                        "directory_name": "01.Context",
                        "concept_title": "Context",
                        "lessons": [
                            {
                                "file_name": "01.Overview.jsonl",
                                "lesson_title": "Overview",
                            }
                        ],
                    },
                    {
                        "directory_name": "02.Flow",
                        "concept_title": "Flow",
                        "lessons": [
                            {
                                "file_name": "01.Overview.jsonl",
                                "lesson_title": "Overview",
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return store


def test_navigation_traverses_sections_and_lesson_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _write_course(root)
    navigator = CourseNavigator(root)

    first = navigator.open("architecture")
    second = navigator.move("next")
    third = navigator.move("next")

    assert first["current"]["title"] == "Purpose"
    assert second["current"]["title"] == "Parts"
    assert third["current"]["title"] == "Request flow"
    assert third["navigation"]["can_go_next"] is False


def test_navigation_projects_markdown_sections_without_companion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _write_course(root)
    navigator = CourseNavigator(root)

    view = navigator.open("architecture")
    walkthrough = navigator.walkthrough(view)
    artifact = navigator.artifact(view)

    step = walkthrough["steps"][0]
    assert step["explanation"].startswith("**Purpose** details for Runtime")
    assert "Request Parser" in step["explanation"]
    assert "<table>" in step["explanation_html"]
    assert "<strong>Purpose</strong>" in step["explanation_html"]
    assert "mod-001" not in step["explanation_html"]
    assert "comp-001" not in step["explanation_html"]
    assert step["primary_reference"] == {}
    assert step["secondary_references"] == []
    assert artifact["jsonl_path"].endswith("01.Overview.jsonl")
    assert "markdown_path" not in artifact
    assert not list(root.rglob("*.md"))


def test_navigation_projects_all_ai_source_references_without_validation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    store = _write_course(root)
    lesson = store.architecture_root / "01.Context" / "01.Overview.jsonl"
    records = store.read_lesson(lesson)
    records[1]["source_refs"] = [
        {
            "path": "src/parser.py",
            "start_line": 4,
            "end_line": 12,
            "symbol": "parse",
            "reason": "comp-001 entry point",
        },
        {
            "path": "tests/test_parser.py",
            "start_line": 20,
            "end_line": 20,
            "symbol": "test_parse",
            "reason": "Observed behavior",
        },
    ]
    lesson.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    step = CourseNavigator(root).walkthrough(
        CourseNavigator(root).open("architecture")
    )["steps"][0]

    assert step["primary_reference"] == {
        "file_path": "src/parser.py",
        "start_line": 4,
        "end_line": 12,
        "symbol": "parse",
        "label": "Request Parser entry point",
        "kind": "source",
    }
    assert step["secondary_references"][0]["file_path"] == "tests/test_parser.py"
