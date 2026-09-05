from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from code_learner_phase3_fixtures import build_catalog, build_course_records

from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.phase3_courses import (
    Phase3CourseNavigator,
    Phase3CourseService,
)
from electroboy.workflows.code_learner.phase3_tutor import (
    Phase3TutorContextStore,
)
from electroboy.workflows.code_learner.source_manifest import SourceManifestService
from electroboy.workflows.code_learner.tutor_context import (
    PHASE3_TUTOR_CONTEXT_RELATIVE_PATH,
    tutor_bootstrap_prompt,
)


def _navigation(root: Path):
    catalog = build_catalog(root)
    service = Phase3CourseService(root, store=catalog.store)
    module_scope = str(catalog.modules.modules[0]["id"])
    module_document = f"course:module:{module_scope}"
    service.save(
        "architecture",
        "architecture:current",
        build_course_records(
            catalog,
            "architecture",
            "architecture:current",
            deep_dive_ids=[module_document],
        ),
    )
    service.save(
        "module",
        module_scope,
        build_course_records(catalog, "module", module_scope),
    )
    navigator = Phase3CourseNavigator(root, service=service)
    return (
        catalog,
        service,
        navigator,
        navigator.open("architecture", "architecture:current"),
    )


def test_phase3_context_contains_canonical_pointers_without_course_payload(
    tmp_path: Path,
) -> None:
    catalog, _service, _navigator, navigation = _navigation(tmp_path)
    context_store = Phase3TutorContextStore(tmp_path, store=catalog.store)

    context = context_store.write_navigation(
        navigation, project_id="project-1", writer_id="session-1"
    )

    assert context["schema_version"] == 2
    assert context["context_version"] == 1
    assert context["selection"]["module_ids"]
    assert context["selection"]["component_ids"]
    assert context["selection"]["symbol_locators"][0]["canonical_key"] == "symbol-0"
    assert context["source"]["file_id"] == "file:file0.py"
    assert "component_manifest" in context["artifacts"]
    assert "module_manifest" in context["artifacts"]
    assert "body" not in json.dumps(context)
    assert context_store.load_state()["status"] == "ready"


def test_vertical_navigation_and_source_changes_update_context_atomically(
    tmp_path: Path,
) -> None:
    catalog, _service, navigator, navigation = _navigation(tmp_path)
    context_store = Phase3TutorContextStore(tmp_path, store=catalog.store)
    first = context_store.write_navigation(
        navigation, project_id="project-1", writer_id="session-1"
    )
    module_document = navigation["section"]["deep_dive_ids"][0]
    descended = navigator.deep_dive(module_document)
    second = context_store.write_navigation(
        descended, project_id="project-1", writer_id="session-1"
    )
    restored = navigator.back()
    third = context_store.write_navigation(
        restored, project_id="project-1", writer_id="session-1"
    )

    assert [
        first["context_version"],
        second["context_version"],
        third["context_version"],
    ] == [1, 2, 3]
    assert second["course"]["mode"] == "module"
    assert len(second["course"]["vertical_path"]) == 2
    assert third["course"]["mode"] == "architecture"
    assert third["source"]["path"] == "file0.py"


def test_rapid_context_writes_are_monotonic_and_do_not_mutate_canonical_state(
    tmp_path: Path,
) -> None:
    catalog, _service, _navigator, navigation = _navigation(tmp_path)
    context_store = Phase3TutorContextStore(tmp_path, store=catalog.store)
    before = catalog.component_service.manifest_path.read_bytes()

    def write(index: int) -> int:
        context = context_store.write_navigation(
            navigation,
            project_id="project-1",
            writer_id=f"session-{index}",
        )
        return int(context["context_version"])

    with ThreadPoolExecutor(max_workers=4) as executor:
        versions = list(executor.map(write, range(8)))

    assert sorted(versions) == list(range(1, 9))
    assert catalog.component_service.manifest_path.read_bytes() == before


def test_context_surfaces_missing_malformed_incompatible_and_stale_states(
    tmp_path: Path,
) -> None:
    catalog, _service, _navigator, navigation = _navigation(tmp_path)
    context_store = Phase3TutorContextStore(tmp_path, store=catalog.store)
    assert context_store.load_state()["status"] == "missing"

    context_store.path.parent.mkdir(parents=True, exist_ok=True)
    context_store.path.write_text("{bad", encoding="utf-8")
    assert context_store.load_state()["status"] == "malformed"
    context_store.path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    assert context_store.load_state()["status"] == "incompatible"

    context_store.path.unlink()
    context_store.write_navigation(
        navigation, project_id="project-1", writer_id="session-1"
    )
    (tmp_path / "file0.py").write_text(
        "def changed():\n    return 3\n", encoding="utf-8"
    )
    SourceManifestService(tmp_path).generate()
    assert context_store.load_state()["status"] == "stale"
    with pytest.raises(CodeLearnerError, match="is stale"):
        context_store.load()


def test_phase3_bootstrap_is_one_small_file_instruction_for_session_reuse(
    tmp_path: Path,
) -> None:
    prompt = tutor_bootstrap_prompt(tmp_path, generation="phase3")

    assert PHASE3_TUTOR_CONTEXT_RELATIVE_PATH in prompt
    assert "Before answering every learner question" in prompt
    assert "schema_version 2" in prompt
    assert "Read only the referenced current course section" in prompt
    assert "context_version" in prompt
    assert "manifest" not in prompt.lower()
