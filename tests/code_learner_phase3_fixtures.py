from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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


def build_catalog(root: Path, *, relationship: bool = True):
    for index in range(2):
        (root / f"file{index}.py").write_text(
            f"def function{index}():\n    return {index}\n", encoding="utf-8"
        )
    source_service = SourceManifestService(root)
    source = source_service.generate()
    candidates = []
    for index in range(2):
        candidates.append(
            {
                "schema_version": 1,
                "record_type": "component_candidate",
                "repository_revision": source.revision,
                "candidate_id": f"candidate-{index}",
                "name": f"Component {index}",
                "kind": "service",
                "responsibility": f"Owns function {index}.",
                "file_ids": [f"file:file{index}.py"],
                "symbols": [
                    {
                        "file_id": f"file:file{index}.py",
                        "name": f"function{index}",
                        "kind": "function",
                        "language": "python",
                        "scope": "",
                        "signature": f"function{index}()",
                        "start_line": 1,
                        "end_line": 2,
                        "canonical_key": f"symbol-{index}",
                        "validated_by": "fixture",
                    }
                ],
                "owned_source_refs": [],
                "supporting_source_refs": [],
                "confidence": "high",
                "limitations": [],
            }
        )
    store = Phase3Store(root)
    store.write_jsonl(store.components_root / "candidates.jsonl", candidates)
    ComponentOverlapService(root, store=store).build(candidates)
    component_service = ComponentManifestService(root, store=store)
    components = component_service.build(analysis_run_id="run-1")
    module_records = []
    for index, component in enumerate(components.components):
        component_id = str(component["id"])
        module_records.append(
            {
                "schema_version": 1,
                "record_type": "module",
                "repository_revision": source.revision,
                "id": f"temporary-{index}",
                "name": f"Module {index}",
                "kind": "subsystem",
                "purpose": f"Coordinates component {index}.",
                "responsibility": "Fixture module responsibility.",
                "component_ids": [component_id],
                "primary_component_ids": [component_id],
                "entry_component_ids": [component_id],
                "primary_for_component_ids": [component_id],
                "grouping_rationale": "One source-backed fixture component.",
                "source_refs": [],
                "confidence": "high",
                "limitations": [],
            }
        )
    module_service = ModuleSynthesisService(root, store=store)
    modules = module_service.ingest(module_records, analysis_run_id="run-1")
    relationship_service = ModuleRelationshipService(root, store=store)
    relationships = []
    if relationship:
        edge = {
            "schema_version": 1,
            "record_type": "module_relationship",
            "repository_revision": source.revision,
            "id": "temporary-edge",
            "from_module_id": modules.modules[0]["id"],
            "to_module_id": modules.modules[1]["id"],
            "kind": "calls",
            "summary": "Module zero calls module one.",
            "direction": "directed",
            "condition": "",
            "confidence": "verified",
            "supporting_component_ids": [
                components.components[0]["id"],
                components.components[1]["id"],
            ],
            "source_refs": [
                {
                    "file_id": "file:file0.py",
                    "start_line": 1,
                    "end_line": 2,
                    "reason": "Fixture relationship evidence.",
                }
            ],
            "limitations": [],
        }
        relationships = relationship_service.ingest_scope(
            RelationshipScope("fixture", str(modules.modules[0]["id"])),
            json.dumps(edge),
        )
        relationship_service.rebuild()
    return SimpleNamespace(
        store=store,
        source=source,
        source_service=source_service,
        components=components,
        component_service=component_service,
        modules=modules,
        module_service=module_service,
        relationships=relationships,
        relationship_service=relationship_service,
    )


def build_course_records(
    catalog,
    mode: str,
    scope_id: str,
    *,
    deep_dive_ids: list[str] | None = None,
    source_index: int = 0,
) -> list[dict[str, object]]:
    document_id = f"course:{mode}:{scope_id}"
    module = catalog.modules.modules[source_index]
    component = catalog.components.components[source_index]
    symbol = component["symbols"][0]
    return [
        {
            "schema_version": 1,
            "record_type": "document",
            "id": document_id,
            "analysis_run_id": "run-1",
            "repository_revision": catalog.source.revision,
            "title": f"{mode.title()} Course",
            "course_mode": mode,
            "scope_id": scope_id,
            "status": "ready",
        },
        {
            "schema_version": 1,
            "record_type": "section",
            "id": f"{document_id}:section:1",
            "analysis_run_id": "run-1",
            "repository_revision": catalog.source.revision,
            "parent_id": document_id,
            "heading_level": 2,
            "order": 1,
            "title": "Current lesson",
            "body": "A compact fixture lesson.",
            "detail_level": mode,
            "confidence": "high",
            "previous_section_id": None,
            "next_section_id": None,
            "return_section_id": None,
            "deep_dive_ids": list(deep_dive_ids or []),
            "deep_dive_targets": [
                {"target_type": "component", "target_id": component["id"]}
            ],
            "prerequisite_section_ids": [],
            "knowledge_entity_ids": [component["id"], module["id"]],
            "relationship_ids": [
                item["id"]
                for item in catalog.relationships
                if module["id"] in {item["from_module_id"], item["to_module_id"]}
            ],
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": [module["id"]],
            "related_symbol_ids": [symbol["canonical_key"]],
            "source_refs": [
                {
                    "path": f"file{source_index}.py",
                    "start_line": 1,
                    "end_line": 2,
                    "symbol": symbol["name"],
                    "reason": "Tutor context source.",
                    "revision": catalog.source.revision,
                }
            ],
            "diagrams": [],
        },
    ]
