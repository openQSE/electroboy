from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from time import perf_counter

import pytest

from electroboy.workflows.code_learner.component_manifest import (
    ComponentManifestService,
)
from electroboy.workflows.code_learner.modules import ModuleSynthesisService
from electroboy.workflows.code_learner.overlap import ComponentOverlapService
from electroboy.workflows.code_learner.phase3_store import Phase3Store
from electroboy.workflows.code_learner.relationships import (
    ModuleRelationshipService,
    RelationshipScope,
)
from electroboy.workflows.code_learner.source_manifest import SourceManifestService

FIXTURES = Path(__file__).parent / "fixtures" / "code_learner_phase3"


@pytest.mark.parametrize(
    "fixture",
    [
        "c-symbol-overlap",
        "c-shared-file",
        "object-oriented",
        "dynamic-language",
        "mixed-language",
    ],
)
def test_phase3_fixtures_initialize_without_build_and_dispose_every_file(
    tmp_path: Path, fixture: str
) -> None:
    root = tmp_path / fixture
    shutil.copytree(FIXTURES / fixture, root)
    before = _source_hashes(root)

    started = perf_counter()
    source_service = SourceManifestService(root)
    source = source_service.generate()
    manifest_seconds = perf_counter() - started
    store = Phase3Store(root)
    candidates = [_candidate(source.revision, record) for record in source.files]
    store.write_jsonl(store.components_root / "candidates.jsonl", candidates)
    ComponentOverlapService(root, store=store).build(candidates)

    started = perf_counter()
    component_service = ComponentManifestService(root, store=store)
    components = component_service.build(analysis_run_id="acceptance")
    component_seconds = perf_counter() - started
    assert components.coverage["unresolved_count"] == 0
    assert {item["file_id"] for item in components.dispositions} == {
        item["id"] for item in source.files
    }

    assert (store.modules_root / "relationships.jsonl").exists() is False
    module_records = [
        _module(source.revision, index, component)
        for index, component in enumerate(components.components)
    ]
    started = perf_counter()
    modules = ModuleSynthesisService(root, store=store).ingest(
        module_records, analysis_run_id="acceptance"
    )
    module_seconds = perf_counter() - started
    assert len(modules.modules) == len(components.components)

    relationship_service = ModuleRelationshipService(root, store=store)
    if len(modules.modules) > 1:
        first, second = modules.modules[:2]
        relationship_service.ingest_scope(
            RelationshipScope("acceptance", str(first["id"])),
            _relationship_json(source.revision, first, second, components),
        )
    started = perf_counter()
    relationships = relationship_service.rebuild()
    relationship_seconds = perf_counter() - started
    assert all(
        item["from_module_id"] in modules.manifest["module_ids"]
        and item["to_module_id"] in modules.manifest["module_ids"]
        and item["source_refs"]
        for item in relationships
    )

    assert _source_hashes(root) == before
    assert all(
        value < 2.0
        for value in (
            manifest_seconds,
            component_seconds,
            module_seconds,
            relationship_seconds,
        )
    )


def test_exact_symbol_overlap_reconciles_but_shared_file_only_does_not(
    tmp_path: Path,
) -> None:
    shared = _overlap_candidate("a", "shared", "decode")
    overlapping = _overlap_candidate("b", "shared", "receive")
    distinct = _overlap_candidate("b", "audit", "receive")

    overlap_service = ComponentOverlapService(tmp_path)

    assert len(overlap_service.build([shared, overlapping])) == 1
    assert overlap_service.build([shared, distinct]) == []


def test_language_concept_fixtures_cover_oop_dynamic_and_mixed_boundaries(
    tmp_path: Path,
) -> None:
    for fixture in ("object-oriented", "dynamic-language", "mixed-language"):
        root = tmp_path / fixture
        shutil.copytree(FIXTURES / fixture, root)
        snapshot = SourceManifestService(root).generate()
        languages = {str(item["language"]) for item in snapshot.files}
        if fixture == "object-oriented":
            text = (root / "models.py").read_text(encoding="utf-8")
            lines = {line.strip() for line in text.splitlines()}
            assert "class Record:" in lines
            assert "class UserRecord(Record):" in lines
            assert "def serialize(self) -> str:" in lines
        elif fixture == "dynamic-language":
            text = (root / "plugins.py").read_text(encoding="utf-8")
            assert "getattr(target, method_name)" in text
            assert "PLUGINS.get(name)" in text
        else:
            assert {"c", "python", "javascript"} <= languages


def _candidate(revision: str, file: dict[str, object]) -> dict[str, object]:
    file_id = str(file["id"])
    return {
        "schema_version": 1,
        "record_type": "component_candidate",
        "repository_revision": revision,
        "candidate_id": f"candidate:{file_id}",
        "name": f"Component for {file['path']}",
        "kind": "source-unit",
        "responsibility": f"Owns the code in {file['path']}.",
        "file_ids": [file_id],
        "symbols": [],
        "owned_source_refs": [
            {
                "file_id": file_id,
                "start_line": 1,
                "end_line": 1,
                "reason": "Primary implementation file.",
            }
        ],
        "supporting_source_refs": [],
        "confidence": "high",
        "limitations": [],
    }


def _module(
    revision: str, index: int, component: dict[str, object]
) -> dict[str, object]:
    component_id = str(component["id"])
    return {
        "schema_version": 1,
        "record_type": "module",
        "repository_revision": revision,
        "id": f"fixture-module-{index}",
        "name": f"Fixture Module {index}",
        "kind": "subsystem",
        "purpose": "Teach one source-backed fixture boundary.",
        "responsibility": "Own the selected component.",
        "component_ids": [component_id],
        "primary_component_ids": [component_id],
        "entry_component_ids": [component_id],
        "primary_for_component_ids": [component_id],
        "grouping_rationale": "The fixture has one component per source unit.",
        "source_refs": [],
        "confidence": "high",
        "limitations": [],
    }


def _relationship_json(
    revision: str,
    first: dict[str, object],
    second: dict[str, object],
    components,
) -> str:
    import json

    component_ids = [
        str(components.components[0]["id"]),
        str(components.components[1]["id"]),
    ]
    file_id = str(components.components[0]["file_ids"][0])
    return json.dumps(
        {
            "schema_version": 1,
            "record_type": "module_relationship",
            "repository_revision": revision,
            "id": "fixture-relationship",
            "from_module_id": first["id"],
            "to_module_id": second["id"],
            "kind": "depends-on",
            "summary": "Fixture cross-boundary dependency.",
            "direction": "directed",
            "condition": "",
            "confidence": "medium",
            "supporting_component_ids": component_ids,
            "source_refs": [
                {
                    "file_id": file_id,
                    "start_line": 1,
                    "end_line": 1,
                    "reason": "Fixture relationship evidence.",
                }
            ],
            "limitations": ["Fixture relationship is intentionally synthetic."],
        }
    )


def _overlap_candidate(
    candidate_id: str, canonical_key: str, symbol_name: str
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "file_ids": ["file:dispatch.c"],
        "symbols": [
            {
                "file_id": "file:dispatch.c",
                "name": symbol_name,
                "canonical_key": canonical_key,
            }
        ],
    }


def _source_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and ".electroboy" not in path.parts
    }
