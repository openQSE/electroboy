from __future__ import annotations

import json

import pytest

from electroboy.workflows.code_learner.phase3_contracts import (
    Phase3ContractError,
    SymbolLocator,
    load_phase3_schema,
    parse_phase3_jsonl,
    validate_component_candidates,
    validate_coverage_report,
    validate_file_dispositions,
    validate_knowledge_artifacts,
    validate_knowledge_requests,
    validate_manifest,
    validate_module_relationships,
    validate_modules,
    validate_reconciliations,
    validate_source_files,
    validate_terminal_result,
)

REVISION = "revision-1"


def _file() -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "source_file",
        "repository_revision": REVISION,
        "id": "file:src/app.py",
        "path": "src/app.py",
        "content_hash": "sha256:abc",
        "size": 20,
        "language": "python",
        "source_status": "tracked",
    }


def _candidate() -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "component_candidate",
        "repository_revision": REVISION,
        "candidate_id": "candidate-app",
        "name": "Application",
        "kind": "service",
        "responsibility": "Runs the application.",
        "file_ids": ["file:src/app.py"],
        "symbols": [
            {
                "file_id": "file:src/app.py",
                "name": "main",
                "kind": "function",
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "owned_source_refs": [],
        "supporting_source_refs": [],
        "confidence": "high",
    }


def test_phase3_schema_and_single_record_jsonl_are_loadable() -> None:
    assert load_phase3_schema()["title"].endswith("Phase 3 Record")
    record = _candidate()
    assert parse_phase3_jsonl(json.dumps(record), artifact="candidate") == [record]


def test_source_and_candidate_contracts_validate_grounding() -> None:
    files = validate_source_files([_file()], repository_revision=REVISION)
    candidates = validate_component_candidates(
        [_candidate()],
        repository_revision=REVISION,
        files={str(files[0]["id"]): files[0]},
    )

    assert candidates[0]["candidate_id"] == "candidate-app"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("file_ids", ["file:missing.py"], "unknown source file ID"),
        ("repository_revision", "stale", "revision does not match"),
    ],
)
def test_candidate_contract_rejects_unknown_or_stale_references(
    field: str,
    value: object,
    message: str,
) -> None:
    candidate = _candidate()
    candidate[field] = value

    with pytest.raises(Phase3ContractError, match=message):
        validate_component_candidates(
            [candidate], repository_revision=REVISION, files={_file()["id"]: _file()}
        )


def test_candidate_contract_rejects_invalid_symbol_range() -> None:
    candidate = _candidate()
    candidate["symbols"][0]["end_line"] = 0

    with pytest.raises(Phase3ContractError, match="positive integer"):
        validate_component_candidates(
            [candidate], repository_revision=REVISION, files={_file()["id"]: _file()}
        )


def test_reconciliation_requires_complete_distinct_partition() -> None:
    group = {"candidate_ids": ["a", "b"]}
    reconciliation = {
        "schema_version": 1,
        "record_type": "component_reconciliation",
        "overlap_group_id": "overlap:1",
        "decision": "distinct",
        "partitions": [{"candidate_ids": ["a", "b"]}],
    }

    with pytest.raises(Phase3ContractError, match="singletons"):
        validate_reconciliations([reconciliation], groups={"overlap:1": group})


def test_module_contract_rejects_hierarchy_cycle() -> None:
    common = {
        "schema_version": 1,
        "record_type": "module",
        "repository_revision": REVISION,
        "kind": "package",
        "purpose": "Fixture.",
        "component_ids": ["component:1"],
    }
    modules = [
        {**common, "id": "module:a", "name": "A", "parent_module_id": "module:b"},
        {**common, "id": "module:b", "name": "B", "parent_module_id": "module:a"},
    ]

    with pytest.raises(Phase3ContractError, match="cycle"):
        validate_modules(
            modules,
            repository_revision=REVISION,
            component_ids={"component:1"},
        )


def test_file_dispositions_require_complete_unique_coverage() -> None:
    with pytest.raises(Phase3ContractError, match="missing dispositions"):
        validate_file_dispositions(
            [], file_ids={"file:src/app.py"}, component_ids=set()
        )


@pytest.mark.parametrize(
    ("manifest_type", "extra"),
    [
        ("source_manifest", {"file_ids": ["file:src/app.py"], "raw_tag_count": 1}),
        (
            "component_manifest",
            {
                "component_ids": ["component:1"],
                "unresolved_overlap_group_ids": [],
                "coverage_path": "components/coverage.json",
            },
        ),
        ("module_manifest", {"module_ids": ["module:1"], "frozen": True}),
    ],
)
def test_manifest_contracts_cover_each_phase3_catalog(
    manifest_type: str,
    extra: dict[str, object],
) -> None:
    record = {
        "schema_version": 1,
        "record_type": manifest_type,
        "repository_revision": REVISION,
        "id": f"{manifest_type}:current",
        "status": "complete",
        **extra,
    }

    assert validate_manifest(
        record, manifest_type=manifest_type, repository_revision=REVISION
    )["id"]


def test_coverage_contract_requires_counts_to_partition_scope() -> None:
    coverage = {
        "schema_version": 1,
        "record_type": "file_coverage",
        "repository_revision": REVISION,
        "in_scope_count": 1,
        "owned_count": 1,
        "supporting_count": 0,
        "repository_infrastructure_count": 0,
        "excluded_count": 0,
        "unresolved_count": 0,
        "unresolved_file_ids": [],
    }

    assert validate_coverage_report(coverage, repository_revision=REVISION)


def test_relationship_knowledge_and_request_contracts_validate_ids() -> None:
    relationship = {
        "schema_version": 1,
        "record_type": "module_relationship",
        "repository_revision": REVISION,
        "id": "relationship:1",
        "from_module_id": "module:1",
        "to_module_id": "module:2",
        "kind": "calls",
        "summary": "One module calls another.",
        "supporting_component_ids": ["component:1"],
    }
    knowledge = {
        "schema_version": 1,
        "record_type": "architecture_knowledge",
        "repository_revision": REVISION,
        "id": "architecture:overview",
        "title": "Overview",
        "body": "Architecture body.",
        "component_ids": ["component:1"],
        "module_ids": ["module:1"],
        "diagrams": [{"type": "component", "mermaid": "flowchart LR\nA-->B"}],
    }
    request = {
        "schema_version": 1,
        "record_type": "knowledge_request",
        "repository_revision": REVISION,
        "id": "request:1",
        "request_type": "missing_component",
        "status": "open",
        "reason": "A source-backed component may be absent.",
    }

    assert validate_module_relationships(
        [relationship],
        repository_revision=REVISION,
        module_ids={"module:1", "module:2"},
        component_ids={"component:1"},
    )
    assert validate_knowledge_artifacts(
        [knowledge],
        repository_revision=REVISION,
        component_ids={"component:1"},
        module_ids={"module:1"},
    )
    assert validate_knowledge_requests([request], repository_revision=REVISION)


@pytest.mark.parametrize(
    "result",
    [
        {"status": "complete", "course_active": True, "warning_count": 0},
        {
            "status": "complete_with_warnings",
            "course_active": True,
            "warning_count": 2,
        },
        {
            "status": "failed",
            "course_active": False,
            "warning_count": 0,
            "failed_scope": "source",
            "recovery_action": "Retry initialization.",
        },
    ],
)
def test_terminal_results_accept_only_consistent_states(
    result: dict[str, object],
) -> None:
    assert validate_terminal_result({"schema_version": 1, **result})["status"]


def test_symbol_locator_key_uses_source_identity() -> None:
    locator = SymbolLocator.from_mapping(_candidate()["symbols"][0])

    assert locator.canonical_key(REVISION, "src/app.py").endswith(
        "\x1ffunction\x1f\x1fmain\x1f1"
    )
