from __future__ import annotations

import json
from pathlib import Path

from electroboy.workflows.code_learner.navigation import CourseNavigator
from electroboy.workflows.code_learner.store import LearnerStore


def _write_course(root: Path) -> LearnerStore:
    store = LearnerStore(root)
    store.initialize_layout()
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
                    "body": f"**{title}** details",
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

    assert walkthrough["steps"][0]["explanation"] == "**Purpose** details"
    assert artifact["jsonl_path"].endswith("01.Overview.jsonl")
    assert "markdown_path" not in artifact
    assert not list(root.rglob("*.md"))
