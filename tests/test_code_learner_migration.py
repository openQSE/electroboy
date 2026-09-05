from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.workflows.code_learner.domain import (
    CodeLearnerError,
    CodeLearnerStore,
)
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.migration import LegacyCorpusMigrator


def _legacy_records(path: str = "src/app.py") -> list[dict[str, object]]:
    source_refs = [{"path": path, "start_line": 1, "end_line": 2}]
    return [
        {
            "record_type": "course_manifest",
            "schema_version": 1,
            "repository_name": "Legacy",
            "repository_purpose": "Exercise migration.",
            "primary_languages": ["python"],
            "architecture_step_ids": ["architecture.purpose"],
            "module_ids": ["module.app"],
            "function_index_count": 1,
            "confidence": 0.8,
        },
        {
            "record_type": "architecture_step",
            "id": "architecture.purpose",
            "title": "Purpose",
            "body": "The application transforms values.",
            "source_refs": source_refs,
            "related_module_ids": ["module.app"],
            "confidence": 0.8,
        },
        {
            "record_type": "module",
            "id": "module.app",
            "name": "Application",
            "purpose": "Transform values.",
            "source_refs": source_refs,
            "confidence": 0.8,
        },
        {
            "record_type": "function_index_entry",
            "symbol": "app.transform",
            "display_name": "transform",
            "module_id": "module.app",
            "purpose": "Transform one value.",
            "source_refs": source_refs,
            "confidence": 0.8,
        },
    ]


def _write_legacy_corpus(root: Path, *, path: str = "src/app.py") -> None:
    records = _legacy_records(path)
    text = "\n".join(json.dumps(record) for record in records)
    CodeLearnerStore(root).save_corpus_jsonl(text)


def test_legacy_corpus_is_actionable_until_imported(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text(
        "def transform(value):\n    return value\n",
        encoding="utf-8",
    )
    _write_legacy_corpus(tmp_path)
    migrator = LegacyCorpusMigrator(tmp_path)

    required = migrator.status()
    imported = migrator.migrate()

    assert required.status == "required"
    assert "Run Initialize" in required.message
    assert imported.status == "imported"
    assert imported.imported_record_count >= 3
    assert migrator.status().status == "not_required"
    assert "module.app" in KnowledgeStore(tmp_path).knowledge_ids()


def test_legacy_migration_failure_explains_recovery(tmp_path: Path) -> None:
    _write_legacy_corpus(tmp_path, path="src/missing.py")

    with pytest.raises(CodeLearnerError) as caught:
        LegacyCorpusMigrator(tmp_path).migrate()

    message = str(caught.value)
    assert "could not be migrated" in message
    assert "run Initialize again" in message
    assert "remove .electroboy/code-learner/course-corpus.jsonl" in message
