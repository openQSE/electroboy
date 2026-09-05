from __future__ import annotations

from pathlib import Path

import pytest

from electroboy.workflows.code_learner.analysis_adapters import (
    RepositorySearchAdapter,
    SymbolAdapterRegistry,
    SymbolEvidenceCollector,
)
from electroboy.workflows.code_learner.analysis_passes import (
    ANALYSIS_PASSES,
    validate_pass_output,
)
from electroboy.workflows.code_learner.domain import CodeLearnerError


def test_repository_search_fallback_indexes_mixed_languages_and_overloads(
    tmp_path: Path,
) -> None:
    (tmp_path / "service.py").write_text(
        "def serve(request):\n    return request\n", encoding="utf-8"
    )
    (tmp_path / "client.ts").write_text(
        "export function connect(url: string) { return url; }\n", encoding="utf-8"
    )
    (tmp_path / "codec.cpp").write_text(
        "int parse(int value) { return value; }\n"
        "int parse(double value) { return int(value); }\n"
        "void invoke(void (*callback)(int)) { callback(1); }\n",
        encoding="utf-8",
    )

    facts = RepositorySearchAdapter().analyze(
        tmp_path, ["service.py", "client.ts", "codec.cpp"]
    )

    assert {fact.name for fact in facts} >= {"serve", "connect", "parse", "invoke"}
    assert len([fact for fact in facts if fact.name == "parse"]) == 2
    assert {fact.language for fact in facts} >= {"python", "typescript", "cpp"}
    assert all(fact.limitations for fact in facts)


def test_evidence_collector_honors_exclusions_and_reports_optional_tools(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.c").write_text(
        "int main(void) { return 0; }\n", encoding="utf-8"
    )
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "bindings.c").write_text(
        "int generated_call(void) { return 0; }\n", encoding="utf-8"
    )
    collector = SymbolEvidenceCollector(
        tmp_path, excluded_regions=("generated",), file_limit=10
    )

    evidence = collector.collect()

    assert evidence["indexed_paths"] == ["src/main.c"]
    capabilities = evidence["capabilities"]
    assert capabilities[0]["name"] == "repository-search"
    assert capabilities[0]["available"] is True
    assert all(capability["name"] != "vim" for capability in capabilities)


def _symbol_records() -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-symbols",
        "repository_revision": "revision",
    }
    source = {
        "path": "src/callbacks.c",
        "start_line": 1,
        "end_line": 2,
        "reason": "Defines callback symbols.",
    }
    symbol_ids = ["symbol.dispatch", "symbol.handle"]
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "symbols",
            "scope_path": ".",
            "status": "symbols",
            "entity_count": 3,
            "relationship_count": 0,
            "flow_count": 0,
            "diagnostic_count": 0,
            "attributes": {
                "symbol_catalog": {
                    "symbol_ids": symbol_ids,
                    "adapter_capabilities": [
                        {
                            "name": "repository-search",
                            "available": True,
                            "limitation": "Indirect calls require source inspection.",
                        }
                    ],
                    "indexed_paths": ["src/callbacks.c"],
                    "skipped_paths": ["generated/bindings.c"],
                }
            },
        },
        {
            **common,
            "record_type": "entity",
            "id": "module.callbacks",
            "kind": "module",
            "name": "Callbacks",
            "summary": "Owns callback dispatch.",
            "source_refs": [source],
            "confidence": "high",
        },
    ]
    for symbol_id, name, callers, callees, limitations in (
        (
            "symbol.dispatch",
            "dispatch",
            [],
            ["symbol.handle"],
            ["Function-pointer target is selected at runtime."],
        ),
        ("symbol.handle", "handle", ["symbol.dispatch"], [], []),
    ):
        records.append(
            {
                **common,
                "record_type": "entity",
                "id": symbol_id,
                "kind": "symbol",
                "name": name,
                "summary": f"Symbol {name}.",
                "parent_id": "module.callbacks",
                "source_refs": [source],
                "confidence": "medium",
                "attributes": {
                    "qualified_name": f"callbacks.{name}",
                    "symbol_kind": "function",
                    "language": "c",
                    "owning_module_id": "module.callbacks",
                    "implementation_refs": [source],
                    "visibility": "public",
                    "signature": f"void {name}(void)",
                    "caller_ids": callers,
                    "callee_ids": callees,
                    "input_types": [],
                    "output_types": ["void"],
                    "side_effects": [],
                    "state_access_ids": [],
                    "test_ids": [],
                    "analysis_limitations": limitations,
                    "call_edge_confidence": {
                        related: "unresolved" if limitations else "inferred"
                        for related in [*callers, *callees]
                    },
                },
            }
        )
    return records


def test_symbol_contract_normalizes_ownership_calls_and_limitations() -> None:
    validate_pass_output(ANALYSIS_PASSES[4], _symbol_records())


def test_symbol_contract_rejects_unknown_callee() -> None:
    records = _symbol_records()
    dispatch = next(record for record in records if record["id"] == "symbol.dispatch")
    dispatch["attributes"]["callee_ids"] = ["symbol.missing"]  # type: ignore[index]

    with pytest.raises(CodeLearnerError, match="unknown IDs"):
        validate_pass_output(ANALYSIS_PASSES[4], records)


def test_registry_always_exposes_fallback_without_editor_dependency() -> None:
    capabilities = SymbolAdapterRegistry().capabilities()

    assert capabilities[0].name == "repository-search"
    assert capabilities[0].available
    assert "all text source languages" in capabilities[0].applies_to
    assert "vim" not in {item.name.lower() for item in capabilities}
