from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from electroboy.workflows.code_learner.course_graph import CourseNavigator
from electroboy.workflows.code_learner.domain import (
    CodeLearnerError,
    repository_revision,
)
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.tutor_context import (
    TUTOR_CONTEXT_RELATIVE_PATH,
    TutorContextStore,
    require_repository_read_capability,
    tutor_bootstrap_prompt,
)


def _source(line: int = 1) -> dict[str, object]:
    return {
        "path": "src/app.py",
        "start_line": line,
        "end_line": line,
        "reason": "Tutor context evidence.",
    }


def _seed(root: Path) -> tuple[KnowledgeStore, dict[str, object]]:
    source = root / "src"
    source.mkdir()
    (source / "app.py").write_text(
        "def start():\n    return run()\ndef run():\n    return 1\n",
        encoding="utf-8",
    )
    revision = repository_revision(root)
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-tutor",
        "repository_revision": revision,
    }
    store = KnowledgeStore(root)
    store.save_knowledge(
        [
            {
                **common,
                "record_type": "knowledge_manifest",
                "id": "knowledge.manifest",
                "repository_name": "tutor",
                "scope_path": ".",
                "status": "validated",
                "entity_count": 2,
                "relationship_count": 1,
                "flow_count": 1,
                "diagnostic_count": 0,
            },
            {
                **common,
                "record_type": "entity",
                "id": "module.app",
                "kind": "module",
                "name": "App",
                "summary": "Application module.",
                "source_refs": [_source()],
                "confidence": "high",
            },
            {
                **common,
                "record_type": "entity",
                "id": "symbol.run",
                "kind": "symbol",
                "name": "run",
                "summary": "Runs the application.",
                "parent_id": "module.app",
                "source_refs": [_source(3)],
                "confidence": "high",
            },
            {
                **common,
                "record_type": "relationship",
                "id": "relationship.app-calls-run",
                "kind": "calls",
                "from_id": "module.app",
                "to_id": "symbol.run",
                "summary": "The app invokes run.",
                "source_refs": [_source()],
                "confidence": "high",
            },
            {
                **common,
                "record_type": "runtime_flow",
                "id": "flow.start",
                "name": "Start flow",
                "kind": "request",
                "participant_ids": ["module.app", "symbol.run"],
                "steps": [
                    {
                        "order": 1,
                        "from_id": "module.app",
                        "to_id": "symbol.run",
                        "action": "Invoke run.",
                        "relationship_ids": ["relationship.app-calls-run"],
                    }
                ],
                "source_refs": [_source()],
                "confidence": "high",
            },
        ]
    )
    document_id = "course.module.module.app"
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "document",
            "id": document_id,
            "title": "App Module",
            "course_mode": "module",
            "scope_id": "module.app",
            "status": "ready",
        },
        {
            **common,
            "record_type": "section",
            "id": f"{document_id}.flow",
            "parent_id": document_id,
            "heading_level": 2,
            "order": 1,
            "title": "Runtime flow",
            "body": "The app delegates to run.",
            "detail_level": "module",
            "previous_section_id": None,
            "next_section_id": None,
            "return_section_id": None,
            "deep_dive_ids": [],
            "knowledge_entity_ids": ["module.app", "symbol.run"],
            "relationship_ids": ["relationship.app-calls-run"],
            "runtime_flow_ids": ["flow.start"],
            "diagnostic_ids": [],
            "related_module_ids": ["module.app"],
            "related_symbol_ids": ["symbol.run"],
            "prerequisite_section_ids": [],
            "source_refs": [_source()],
            "confidence": "high",
            "diagrams": [],
        },
    ]
    store.save_course("module", "module.app", records)
    store.record_course_status("module", "module.app", "ready")
    navigation = CourseNavigator(root).open(document_id)
    return store, navigation


def test_writes_compact_navigation_context_and_increments_version(
    tmp_path: Path,
) -> None:
    _store, navigation = _seed(tmp_path)
    context_store = TutorContextStore(tmp_path)

    first = context_store.write_navigation(
        navigation,
        project_id="project-1",
        writer_id="browser-1",
    )
    navigation = CourseNavigator(tmp_path).update_code_view(
        {
            "path": "src/app.py",
            "selected_start_line": 3,
            "selected_end_line": 4,
            "visible_start_line": 1,
            "visible_end_line": 4,
        }
    )
    second = context_store.write_navigation(
        navigation,
        project_id="project-1",
        writer_id="browser-1",
    )

    assert first["context_version"] == 1
    assert second["context_version"] == 2
    assert second["course"]["document_id"] == "course.module.module.app"
    assert second["selection"]["runtime_flow_ids"] == ["flow.start"]
    assert second["source"] == {
        "path": "src/app.py",
        "start_line": 3,
        "end_line": 4,
    }
    assert second["artifacts"]["knowledge_root"].startswith(".electroboy/")
    assert "body" not in json.dumps(second)


def test_concurrent_navigation_updates_receive_unique_monotonic_versions(
    tmp_path: Path,
) -> None:
    _store, navigation = _seed(tmp_path)
    context_store = TutorContextStore(tmp_path)

    def write(index: int) -> int:
        result = context_store.write_navigation(
            navigation,
            project_id="project-1",
            writer_id=f"browser-{index}",
        )
        return int(result["context_version"])

    with ThreadPoolExecutor(max_workers=6) as executor:
        versions = list(executor.map(write, range(12)))

    assert sorted(versions) == list(range(1, 13))
    assert TutorContextStore(tmp_path).load()["context_version"] == 12


def test_marks_context_stale_when_repository_revision_changes(tmp_path: Path) -> None:
    _store, navigation = _seed(tmp_path)
    context_store = TutorContextStore(tmp_path)
    context_store.write_navigation(
        navigation,
        project_id="project-1",
        writer_id="browser-1",
    )

    (tmp_path / "src" / "app.py").write_text(
        "def changed():\n    return 2\n", encoding="utf-8"
    )
    stale = context_store.write_navigation(
        navigation,
        project_id="project-1",
        writer_id="browser-1",
    )

    assert stale["stale"] is True


def test_rejects_malformed_existing_context_and_escaping_source(tmp_path: Path) -> None:
    _store, navigation = _seed(tmp_path)
    context_store = TutorContextStore(tmp_path)
    context_store.path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CodeLearnerError, match="unreadable"):
        context_store.write_navigation(
            navigation,
            project_id="project-1",
            writer_id="browser-1",
        )

    context_store.path.unlink()
    navigation["navigation"]["code_view"] = {
        "path": "../outside.py",
        "selected_start_line": 1,
        "selected_end_line": 1,
    }
    with pytest.raises(Exception, match="repository-relative"):
        context_store.write_navigation(
            navigation,
            project_id="project-1",
            writer_id="browser-1",
        )


def test_bootstrap_requires_fresh_file_reads_and_bounded_evidence(
    tmp_path: Path,
) -> None:
    prompt = tutor_bootstrap_prompt(tmp_path)
    command = [
        "codex",
        "--cd",
        str(tmp_path),
        "--sandbox",
        "read-only",
        prompt,
    ]

    require_repository_read_capability(command, tmp_path)

    assert TUTOR_CONTEXT_RELATIVE_PATH in prompt
    assert "Before answering every learner question" in prompt
    assert "missing, unreadable, incompatible, or stale" in prompt
    assert "Read only the referenced current course section" in prompt
    assert "context_version" in prompt
    assert "<code-learner-enrichment-request>" in prompt
    with pytest.raises(CodeLearnerError, match="repository reads"):
        require_repository_read_capability(["other-runtime"], tmp_path)
