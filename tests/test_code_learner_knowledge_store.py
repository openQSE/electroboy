from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest import mock

import pytest

from electroboy.workflows.code_learner.contracts import ContractError, parse_jsonl
from electroboy.workflows.code_learner.domain import (
    CodeLearnerError,
    repository_revision,
)
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore

FIXTURE = Path(__file__).parent / "fixtures" / "code_learner_extension"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    shutil.copytree(FIXTURE, root)
    return root


def _knowledge(repository: Path) -> list[dict[str, object]]:
    return parse_jsonl(
        (repository / "knowledge-fixture.jsonl").read_text(encoding="utf-8"),
        artifact="fixture",
    )


def _course(mode: str, scope_id: str) -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "course-run",
        "repository_revision": "fixture-v1",
    }
    document_id = f"course.{mode}.{scope_id}"
    return [
        {
            **common,
            "record_type": "document",
            "id": document_id,
            "title": "Fixture Course",
            "course_mode": mode,
            "scope_id": scope_id,
            "status": "generated",
        },
        {
            **common,
            "record_type": "section",
            "id": f"{document_id}.purpose",
            "parent_id": document_id,
            "heading_level": 2,
            "order": 0,
            "title": "Purpose",
            "body": "Evidence-grounded purpose.",
            "detail_level": mode,
            "knowledge_entity_ids": [scope_id],
            "relationship_ids": [],
            "runtime_flow_ids": [],
            "related_module_ids": [],
            "related_symbol_ids": [],
            "prerequisite_section_ids": [],
            "source_refs": [
                {
                    "path": "README.md",
                    "start_line": 1,
                    "end_line": 3,
                    "reason": "States repository purpose.",
                }
            ],
            "confidence": "verified",
        },
    ]


def test_persists_knowledge_in_independent_atomic_streams(repository: Path) -> None:
    store = KnowledgeStore(repository)

    saved = store.save_knowledge(_knowledge(repository))

    assert store.load_knowledge() == saved
    assert store.knowledge_path("entity").is_file()
    assert store.knowledge_path("relationship").is_file()
    assert store.knowledge_path("runtime_flow").is_file()
    assert not list(store.knowledge_root.glob("*.tmp"))


def test_rejected_knowledge_does_not_replace_valid_streams(repository: Path) -> None:
    store = KnowledgeStore(repository)
    original = store.save_knowledge(_knowledge(repository))
    invalid = _knowledge(repository)
    invalid[1]["source_refs"][0]["path"] = "../escape.py"  # type: ignore[index]

    with pytest.raises(ContractError):
        store.save_knowledge(invalid)

    assert store.load_knowledge() == original


def test_merges_by_stable_id_and_refreshes_manifest_counts(repository: Path) -> None:
    store = KnowledgeStore(repository)
    store.save_knowledge(_knowledge(repository))
    changed = next(
        record
        for record in store.load_knowledge()
        if record["id"] == "implementation.memory"
    )
    changed["summary"] = "Updated memory behavior."

    merged = store.merge_knowledge([changed])

    by_id = {record["id"]: record for record in merged}
    assert by_id["implementation.memory"]["summary"] == "Updated memory behavior."
    assert by_id["knowledge.manifest"]["entity_count"] == 7


def test_rejects_incompatible_stable_id_replacement(repository: Path) -> None:
    store = KnowledgeStore(repository)
    store.save_knowledge(_knowledge(repository))
    changed = dict(store.get("implementation.memory"))
    changed["kind"] = "module"

    with pytest.raises(CodeLearnerError, match="incompatible"):
        store.merge_knowledge([changed])


def test_deprecates_records_without_changing_their_identity(repository: Path) -> None:
    store = KnowledgeStore(repository)
    store.save_knowledge(_knowledge(repository))

    deprecated = store.deprecate(
        "implementation.memory",
        reason="Implementation was removed.",
        analysis_run_id="run-2",
        revision="fixture-v2",
    )

    assert deprecated["status"] == "deprecated"
    assert deprecated["deprecation_reason"] == "Implementation was removed."
    assert store.get("implementation.memory")["kind"] == "implementation"


def test_queries_by_kind_module_source_and_relationship_neighborhood(
    repository: Path,
) -> None:
    store = KnowledgeStore(repository)
    store.save_knowledge(_knowledge(repository))

    assert {record["id"] for record in store.query(kind="implementation")} == {
        "implementation.memory",
        "implementation.tcp",
    }
    assert store.query(source_path="src/transports/tcp.py")
    module_records = {
        record["id"] for record in store.query(module_id="module.registry")
    }
    assert "symbol.create_transport" in module_records
    neighborhood = {
        record["id"] for record in store.neighborhood("module.registry", hops=2)
    }
    assert "implementation.memory" in neighborhood
    assert "family.transport" in neighborhood


def test_saves_courses_independently_by_mode_and_scope(repository: Path) -> None:
    store = KnowledgeStore(repository)
    store.save_knowledge(_knowledge(repository))

    module_path = store.save_course(
        "module",
        "module.registry",
        _course("module", "module.registry"),
    )
    function_path = store.save_course(
        "function",
        "symbol.create_transport",
        _course("function", "symbol.create_transport"),
    )

    assert module_path != function_path
    assert store.load_course("module", "module.registry")[0]["scope_id"] == (
        "module.registry"
    )
    assert (
        store.load_course("function", "symbol.create_transport")[0]["scope_id"]
        == "symbol.create_transport"
    )


def test_clear_course_cache_preserves_knowledge_and_invalidates_context(
    repository: Path,
) -> None:
    store = KnowledgeStore(repository)
    store.save_knowledge(_knowledge(repository))
    store.save_course(
        "module",
        "module.registry",
        _course("module", "module.registry"),
    )
    store.course_markdown_path("module", "module.registry").write_text(
        "# Cached course\n",
        encoding="utf-8",
    )
    store.navigation_path.write_text("{}\n", encoding="utf-8")
    store.tutor_context_path.write_text("{}\n", encoding="utf-8")
    store.save_checkpoint(
        {
            "pipeline_status": "activated",
            "courses": {"module:module.registry": {"status": "completed"}},
        }
    )
    knowledge_ids = store.knowledge_ids()

    result = store.clear_course_cache()

    assert result["removed_file_count"] >= 2
    assert result["removed_bytes"] > 0
    assert not store.courses_root.exists()
    assert not store.navigation_path.exists()
    assert not store.tutor_context_path.exists()
    assert store.knowledge_ids() == knowledge_ids
    checkpoint = store.load_checkpoint()
    assert checkpoint["pipeline_status"] == "course_cache_cleared"
    assert "courses" not in checkpoint


def test_rejects_unsafe_or_mismatched_course_scope(repository: Path) -> None:
    store = KnowledgeStore(repository)
    store.save_knowledge(_knowledge(repository))

    with pytest.raises(CodeLearnerError, match="scope does not match"):
        store.save_course(
            "module", "module.other", _course("module", "module.registry")
        )


def test_persists_progress_and_checkpoint(repository: Path) -> None:
    store = KnowledgeStore(repository)
    store.append_progress({"phase": "inventory", "percent": 10})
    store.save_checkpoint({"analysis_run_id": "run-1", "completed": ["inventory"]})

    assert (
        json.loads(store.progress_path.read_text().splitlines()[0])["phase"]
        == "inventory"
    )
    assert store.load_checkpoint() == {
        "analysis_run_id": "run-1",
        "completed": ["inventory"],
    }


def test_staging_interruption_preserves_existing_knowledge(repository: Path) -> None:
    store = KnowledgeStore(repository)
    original = store.save_knowledge(_knowledge(repository))

    with (
        mock.patch(
            "electroboy.workflows.code_learner.knowledge_store._stage_jsonl",
            side_effect=OSError("interrupted"),
        ),
        pytest.raises(OSError, match="interrupted"),
    ):
        store.save_knowledge(_knowledge(repository))

    assert store.load_knowledge() == original


def test_reports_revision_and_source_reference_staleness(repository: Path) -> None:
    store = KnowledgeStore(repository)
    records = _knowledge(repository)
    revision = repository_revision(repository)
    for record in records:
        record["repository_revision"] = revision
    store.save_knowledge(records)

    assert store.freshness() == {
        "fresh": True,
        "revision": revision,
        "stale_ids": [],
    }

    (repository / "README.md").write_text("# Changed\n", encoding="utf-8")
    stale = store.freshness()
    assert not stale["fresh"]
    assert stale["stale_ids"]


def test_imports_useful_v1_modules_and_symbols(repository: Path) -> None:
    store = KnowledgeStore(repository)
    source_refs = [
        {
            "path": "src/transports/registry.py",
            "start_line": 1,
            "end_line": 11,
            "reason": "Legacy registry evidence.",
        }
    ]
    records = [
        {
            "record_type": "course_manifest",
            "repository_name": "Legacy",
            "repository_purpose": "Legacy learner corpus.",
            "confidence": 0.8,
        },
        {
            "record_type": "module",
            "id": "module.registry",
            "name": "Registry",
            "purpose": "Select transports.",
            "source_refs": source_refs,
            "confidence": 0.8,
        },
        {
            "record_type": "function_index_entry",
            "symbol": "transports.registry.create_transport",
            "display_name": "create_transport",
            "module_id": "module.registry",
            "purpose": "Construct a transport.",
            "source_refs": source_refs,
            "confidence": 0.8,
        },
    ]

    imported = store.import_v1_corpus(
        records,
        analysis_run_id="migration-1",
        revision="legacy-revision",
    )

    ids = {record["id"] for record in imported}
    assert "module.registry" in ids
    assert "symbol.transports.registry.create_transport" in ids
    assert "diagnostic.v1-import" in ids
