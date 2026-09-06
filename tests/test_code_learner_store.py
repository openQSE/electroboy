from __future__ import annotations

import json
from pathlib import Path

from electroboy.workflows.code_learner.store import LearnerStore


def test_store_creates_named_course_and_raw_knowledge(tmp_path: Path) -> None:
    root = tmp_path / "sample-repository"
    root.mkdir()
    store = LearnerStore(root)

    store.initialize_layout()

    assert store.course_root == (
        root / ".electroboy/code-learner/courses/sample-repository"
    )
    assert store.raw_knowledge_root.is_dir()
    assert not store.architecture_root.exists()


def test_store_reads_ai_written_arrays_without_rewriting(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    store = LearnerStore(root)
    store.initialize_layout()
    components = [
        {
            "eb_comp_id": "comp-901",
            "ai_component_name": "AI name",
            "ai_file_list": ["src/example.py", "not/a/verified/path"],
        }
    ]
    store.components_path.write_text(json.dumps(components), encoding="utf-8")

    assert store.components() == components


def test_store_projects_ai_course_index_to_lesson_paths(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    store = LearnerStore(root)
    store.initialize_layout()
    concept = store.architecture_root / "01.System"
    concept.mkdir(parents=True)
    store.course_index_path("architecture").write_text(
        json.dumps(
            {
                "course_type": "architecture",
                "course_title": "Architecture",
                "concepts": [
                    {
                        "directory_name": "01.System",
                        "concept_title": "System",
                        "lessons": [
                            {
                                "file_name": "01.Overview.jsonl",
                                "lesson_title": "Overview",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    lesson = concept / "01.Overview.jsonl"
    lesson.write_text(
        json.dumps(
            {
                "record_type": "document",
                "id": "lesson",
                "title": "Overview",
            }
        )
        + "\n"
        + json.dumps(
            {
                "record_type": "section",
                "id": "slide",
                "title": "Purpose",
                "body": "**Markdown** details",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    lessons = store.lessons("architecture")

    assert lessons[0]["path"] == lesson
    assert store.course_ready("architecture")
    assert store.read_lesson(lesson)[1]["body"] == "**Markdown** details"


def test_store_clear_removes_all_visible_course_state(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    store = LearnerStore(root)
    store.initialize_layout()
    store.save_status(status="initialized")
    store.append_progress({"message": "working"})

    result = store.clear()

    assert result["removed_file_count"] == 2
    assert not store.state_root.exists()
