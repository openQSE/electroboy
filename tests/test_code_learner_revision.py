from __future__ import annotations

from pathlib import Path

from electroboy.workflows.code_learner.domain import repository_revision
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.revision import (
    RevisionInvalidator,
    repository_source_snapshot,
)


def _reference(path: str) -> dict[str, object]:
    return {
        "path": path,
        "start_line": 1,
        "end_line": 1,
        "reason": "Revision fixture evidence.",
    }


def _seed(root: Path) -> KnowledgeStore:
    (root / "README.md").write_text("# Revision\n", encoding="utf-8")
    source = root / "src"
    source.mkdir()
    (source / "a.py").write_text("A = 1\n", encoding="utf-8")
    (source / "b.py").write_text("B = 1\n", encoding="utf-8")
    revision = repository_revision(root)
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-revision",
        "repository_revision": revision,
    }
    records = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "Revision",
            "scope_path": ".",
            "status": "validated",
            "entity_count": 3,
            "relationship_count": 2,
            "flow_count": 0,
            "diagnostic_count": 0,
            "attributes": {
                "module_catalog": {
                    "major_module_ids": ["module.a", "module.b"]
                }
            },
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": "Revision",
            "summary": "Revision fixture.",
            "source_refs": [_reference("README.md")],
            "confidence": "high",
        },
    ]
    for name in ("a", "b"):
        module_id = f"module.{name}"
        records.extend(
            [
                {
                    **common,
                    "record_type": "entity",
                    "id": module_id,
                    "kind": "module",
                    "name": name,
                    "summary": f"Module {name}.",
                    "parent_id": "repository.root",
                    "source_refs": [_reference(f"src/{name}.py")],
                    "confidence": "high",
                },
                {
                    **common,
                    "record_type": "relationship",
                    "id": f"relationship.contains-{name}",
                    "kind": "contains",
                    "from_id": "repository.root",
                    "to_id": module_id,
                    "summary": f"Repository contains {name}.",
                    "source_refs": [_reference(f"src/{name}.py")],
                    "confidence": "high",
                },
            ]
        )
    store = KnowledgeStore(root)
    store.save_knowledge(records)
    _save_course(store, "architecture", "repository.root", ["module.a", "module.b"])
    _save_course(store, "module", "module.a", ["module.a"])
    _save_course(store, "module", "module.b", ["module.b"])
    store.save_checkpoint(
        {
            "schema_version": 1,
            "analysis_run_id": "run-revision",
            "repository_revision": revision,
            "source_snapshot": repository_source_snapshot(root),
            "status": "validated",
            "passes": {},
        }
    )
    return store


def _save_course(
    store: KnowledgeStore,
    mode: str,
    scope_id: str,
    entity_ids: list[str],
) -> None:
    revision = repository_revision(store.root)
    document_id = (
        "course.architecture.repository.root"
        if mode == "architecture"
        else f"course.module.{scope_id}"
    )
    path = "README.md" if mode == "architecture" else f"src/{scope_id[-1]}.py"
    records = [
        {
            "schema_version": 1,
            "analysis_run_id": "run-revision",
            "repository_revision": revision,
            "record_type": "document",
            "id": document_id,
            "title": document_id,
            "course_mode": mode,
            "scope_id": scope_id,
            "status": "ready",
        },
        {
            "schema_version": 1,
            "analysis_run_id": "run-revision",
            "repository_revision": revision,
            "record_type": "section",
            "id": f"{document_id}.overview",
            "parent_id": document_id,
            "heading_level": 2,
            "order": 1,
            "title": "Overview",
            "body": "Revision fixture course.",
            "detail_level": mode,
            "previous_section_id": None,
            "next_section_id": None,
            "return_section_id": None,
            "deep_dive_ids": [],
            "knowledge_entity_ids": entity_ids,
            "relationship_ids": [],
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": entity_ids,
            "related_symbol_ids": [],
            "prerequisite_section_ids": [],
            "source_refs": [_reference(path)],
            "confidence": "high",
            "diagrams": [],
        },
    ]
    course_path = store.save_course(mode, scope_id, records)
    store.course_markdown_path(mode, scope_id).write_text(
        "# Course\n", encoding="utf-8"
    )
    store.record_course_status(
        mode,
        scope_id,
        "ready",
        path=course_path.relative_to(store.root).as_posix(),
    )


def test_revision_change_stales_only_affected_module_and_architecture(
    tmp_path: Path,
) -> None:
    store = _seed(tmp_path)
    previous = repository_revision(tmp_path)
    (tmp_path / "src" / "a.py").write_text("A = 200\n", encoding="utf-8")

    report = RevisionInvalidator(tmp_path).run()

    assert report.previous_revision == previous
    assert report.current_revision != previous
    assert report.changed_paths == ("src/a.py",)
    assert "module.a" in report.affected_record_ids
    assert "module.b" not in report.affected_record_ids
    assert any(path.endswith("architecture.jsonl") for path in report.stale_courses)
    assert any(path.endswith("module.a.jsonl") for path in report.stale_courses)
    assert any(path.endswith("module.b.jsonl") for path in report.promoted_courses)
    assert store.load_course(
        "module", "module.a", validate_sources=False
    )[0]["status"] == "stale"
    assert store.load_course("module", "module.b")[0][
        "repository_revision"
    ] == report.current_revision
    knowledge = {
        str(record["id"]): record
        for record in store.load_knowledge(validate_sources=False)
    }
    assert knowledge["module.a"]["attributes"]["stale"] is True
    assert knowledge["module.b"]["repository_revision"] == report.current_revision


def test_missing_prior_snapshot_falls_back_to_broad_invalidation(
    tmp_path: Path,
) -> None:
    store = _seed(tmp_path)
    checkpoint = store.load_checkpoint()
    checkpoint.pop("source_snapshot")
    store.save_checkpoint(checkpoint)
    (tmp_path / "src" / "a.py").write_text("A = 300\n", encoding="utf-8")

    report = RevisionInvalidator(tmp_path).run()

    assert {"module.a", "module.b"} <= set(report.affected_record_ids)
    assert len(report.stale_courses) == 3
