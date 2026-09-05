from __future__ import annotations

import hashlib
from pathlib import Path

from code_learner_phase3_fixtures import build_catalog, build_course_records

from electroboy.workflows.code_learner.generation import (
    LearnerGenerationStore,
    clear_phase3_cache,
)
from electroboy.workflows.code_learner.phase3_courses import Phase3CourseService
from electroboy.workflows.code_learner.phase3_pipeline import (
    Phase3InitializationPipeline,
    phase3_initialization_ready,
)
from electroboy.workflows.code_learner.phase3_revision import (
    Phase3RevisionInvalidator,
)


def test_revision_change_invalidates_only_dependent_phase3_scopes(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    service = Phase3CourseService(tmp_path, store=catalog.store)
    component_ids = [str(item["id"]) for item in catalog.components.components]
    module_ids = [str(item["id"]) for item in catalog.modules.modules]
    _seed_knowledge_and_courses(catalog, service)
    catalog.store.write_json(catalog.store.checkpoint_path, {"status": "complete"})
    catalog.store.write_json(
        catalog.store.result_path,
        {
            "schema_version": 1,
            "repository_revision": catalog.source.revision,
            "status": "complete",
            "course_active": True,
            "warning_count": 0,
        },
    )
    old_unaffected_course = service.course_path("module", module_ids[1])

    (tmp_path / "file0.py").write_text(
        "def replacement():\n    return 10\n", encoding="utf-8"
    )
    current = catalog.source_service.generate()
    report = Phase3RevisionInvalidator(tmp_path, store=catalog.store).run(
        catalog.source, current
    )

    assert report.changed_file_ids == ("file:file0.py",)
    assert report.affected_component_ids == (component_ids[0],)
    assert report.affected_module_ids == (module_ids[0],)
    assert report.preserved_component_ids == (component_ids[1],)
    assert report.preserved_module_ids == (module_ids[1],)
    assert catalog.store.read_json(catalog.component_service.manifest_path) is None
    assert catalog.store.read_json(catalog.module_service.manifest_path) is None
    assert catalog.store.result_path.exists() is False
    assert catalog.store.checkpoint_path.exists() is False
    assert service.course_path("module", module_ids[0]).exists() is False
    assert old_unaffected_course.is_file()
    preserved = catalog.store.read_jsonl(old_unaffected_course)
    assert preserved[0]["repository_revision"] == current.revision
    index = service.index()["targets"]
    assert index[f"course:module:{module_ids[0]}"]["status"] == "stale"
    assert index[f"course:module:{module_ids[1]}"]["status"] == "ready"


def test_revision_change_invalidates_raw_and_targeted_ctags_evidence(
    tmp_path: Path,
) -> None:
    catalog = build_catalog(tmp_path)
    source_root = catalog.store.state_root / "source"
    targeted = source_root / "targeted"
    targeted.mkdir(parents=True)
    changed_digest = hashlib.sha256(b"file0.py").hexdigest()[:16]
    changed_target = targeted / f"{changed_digest}.jsonl"
    changed_target.write_text("{}\n", encoding="utf-8")
    retained_target = targeted / "unrelated.jsonl"
    retained_target.write_text("{}\n", encoding="utf-8")
    (source_root / "universal-ctags.raw.jsonl").write_text("{}\n", encoding="utf-8")
    (source_root / "universal-ctags-invocation.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (tmp_path / "file0.py").write_text("def changed():\n    pass\n", encoding="utf-8")
    current = catalog.source_service.generate()

    Phase3RevisionInvalidator(tmp_path, store=catalog.store).run(
        catalog.source, current
    )

    assert (source_root / "universal-ctags.raw.jsonl").exists() is False
    assert (source_root / "universal-ctags-invocation.json").exists() is False
    assert changed_target.exists() is False
    assert retained_target.is_file()


def test_phase3_activation_explicitly_replaces_legacy_phase2_generation(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / ".electroboy" / "code-learner" / "knowledge"
    legacy.mkdir(parents=True)
    (legacy / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    pipeline, catalog = _ready_pipeline(tmp_path)

    result = pipeline._activate(catalog.source.revision)

    selected = LearnerGenerationStore(tmp_path).load()
    assert result["status"] == "complete"
    assert selected is not None
    assert selected.generation == "phase3"
    assert selected.repository_revision == catalog.source.revision
    assert phase3_initialization_ready(tmp_path)
    assert (legacy / "manifest.jsonl").is_file()


def test_clear_phase3_cache_removes_all_phase3_and_generation_state(
    tmp_path: Path,
) -> None:
    pipeline, catalog = _ready_pipeline(tmp_path)
    pipeline._activate(catalog.source.revision)
    catalog.store.write_json(catalog.store.tutor_context_path, {"context": True})
    catalog.store.write_json(catalog.store.checkpoint_path, {"status": "complete"})

    result = clear_phase3_cache(tmp_path)

    assert result["removed_file_count"] > 0
    assert catalog.store.state_root.exists() is False
    assert LearnerGenerationStore(tmp_path).load() is None
    assert phase3_initialization_ready(tmp_path) is False


def _seed_knowledge_and_courses(catalog, service: Phase3CourseService) -> None:
    catalog.store.write_jsonl(
        catalog.store.knowledge_root / "architecture.jsonl",
        [{"id": "knowledge:architecture"}],
    )
    for index, module in enumerate(catalog.modules.modules):
        module_id = str(module["id"])
        catalog.store.write_jsonl(
            catalog.store.knowledge_root
            / "modules"
            / f"{module_id.replace(':', '-')}.jsonl",
            [{"id": f"knowledge:{module_id}"}],
        )
        service.save(
            "module",
            module_id,
            build_course_records(catalog, "module", module_id, source_index=index),
        )
    service.save(
        "architecture",
        "architecture:current",
        build_course_records(catalog, "architecture", "architecture:current"),
    )


def _ready_pipeline(tmp_path: Path):
    catalog = build_catalog(tmp_path)
    pipeline = Phase3InitializationPipeline(tmp_path, eager_function_budget=0)
    service = Phase3CourseService(tmp_path, store=catalog.store)
    _seed_knowledge_and_courses(catalog, service)
    return pipeline, catalog
