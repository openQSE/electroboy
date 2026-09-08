from __future__ import annotations

import json
from pathlib import Path

from electroboy.workflows.code_learner.store import LearnerStore
from electroboy.workflows.code_learner.tutor_context import (
    EDITOR_CONTEXT_RELATIVE_PATH,
    TUTOR_CONTEXT_RELATIVE_PATH,
    TutorContextStore,
    tutor_bootstrap_prompt,
)


def test_tutor_context_tracks_course_slide_and_code_selection(tmp_path: Path) -> None:
    store = LearnerStore(tmp_path)
    store.initialize_layout()
    navigation = {
        "course_id": "course:module:mod-001",
        "mode": "module",
        "scope_id": "mod-001",
        "current": {
            "id": "module-entry",
            "title": "Entry point",
            "concept_title": "Runtime",
            "lesson_title": "Overview",
            "lesson_path": "course/lesson.jsonl",
        },
        "navigation": {
            "code_view": {
                "path": "src/app.py",
                "selected_start_line": 8,
                "selected_end_line": 12,
            }
        },
    }

    context = TutorContextStore(tmp_path).write_navigation(
        navigation,
        project_id="project-1",
        writer_id="browser-1",
    )

    assert context["course"] == {
        "course_id": "course:module:mod-001",
        "mode": "module",
        "scope_id": "mod-001",
        "concept_title": "Runtime",
        "lesson_title": "Overview",
        "lesson_path": "course/lesson.jsonl",
        "section_id": "module-entry",
        "section_title": "Entry point",
    }
    assert context["source"]["selected_start_line"] == 8
    persisted = json.loads(store.tutor_context_path.read_text(encoding="utf-8"))
    assert persisted == context


def test_tutor_prompt_receives_context_path_once(tmp_path: Path) -> None:
    prompt = tutor_bootstrap_prompt(tmp_path)

    assert prompt.count(TUTOR_CONTEXT_RELATIVE_PATH) == 1
    assert prompt.count(EDITOR_CONTEXT_RELATIVE_PATH) == 1
    assert "Before answering every learner question" in prompt
    assert "current concept, lesson, and slide" in prompt
