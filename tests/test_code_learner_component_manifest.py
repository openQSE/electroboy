from __future__ import annotations

import json
from pathlib import Path

from electroboy.workflows.code_learner.component_manifest import (
    ComponentManifestService,
)
from electroboy.workflows.code_learner.overlap import ComponentOverlapService
from electroboy.workflows.code_learner.phase3_store import Phase3Store
from electroboy.workflows.code_learner.reconciliation import (
    ComponentReconciliationService,
)
from electroboy.workflows.code_learner.source_manifest import SourceManifestService


def _source(root: Path, names: tuple[str, ...] = ("app.py", "helper.py")):
    for index, name in enumerate(names):
        (root / name).write_text(
            f"def function_{index}():\n    return {index}\n", encoding="utf-8"
        )
    source = SourceManifestService(root)
    return source, source.generate()


def _candidate(
    revision: str,
    candidate_id: str,
    file_name: str,
    *,
    key: str,
    supporting: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "component_candidate",
        "repository_revision": revision,
        "candidate_id": candidate_id,
        "name": f"Name {candidate_id}",
        "kind": "service",
        "responsibility": f"Responsibility {candidate_id}",
        "file_ids": [f"file:{file_name}"],
        "symbols": [
            {
                "file_id": f"file:{file_name}",
                "name": "function_0",
                "kind": "function",
                "start_line": 1,
                "end_line": 2,
                "canonical_key": key,
                "validated_by": "fixture",
            }
        ],
        "owned_source_refs": [],
        "supporting_source_refs": [
            {
                "file_id": f"file:{name}",
                "start_line": 1,
                "end_line": 2,
                "reason": "Supports this component.",
            }
            for name in supporting
        ],
        "confidence": "high",
        "limitations": [],
    }


def _write_candidates(
    root: Path, records: list[dict[str, object]]
) -> ComponentManifestService:
    store = Phase3Store(root)
    store.write_jsonl(store.components_root / "candidates.jsonl", records)
    ComponentOverlapService(root, store=store).build(records)
    return ComponentManifestService(root, store=store)


def test_manifest_passes_nonoverlap_and_persists_warning_coverage(
    tmp_path: Path,
) -> None:
    _, source = _source(tmp_path)
    service = _write_candidates(
        tmp_path,
        [_candidate(source.revision, "app", "app.py", key="app-key")],
    )

    first = service.build(analysis_run_id="run-1")
    second = service.build(analysis_run_id="run-1")

    assert first.manifest["status"] == "complete_with_warnings"
    assert first.coverage["unresolved_file_ids"] == ["file:helper.py"]
    assert first.components[0]["id"].startswith("component:")
    assert "app" not in first.components[0]["id"]
    assert second.components[0]["id"] == first.components[0]["id"]
    assert service.query_components(candidate_id="app") == list(second.components)
    assert service.query_components(file_id="file:app.py") == list(second.components)
    assert service.query_components(canonical_key="app-key") == list(second.components)
    assert service.query_components(name="Name app") == list(second.components)
    assert service.query_dispositions("unresolved")[0]["file_id"] == "file:helper.py"


def test_unresolved_overlap_is_quarantined_without_blocking_other_components(
    tmp_path: Path,
) -> None:
    _, source = _source(tmp_path, ("a.py", "b.py", "ok.py"))
    service = _write_candidates(
        tmp_path,
        [
            _candidate(source.revision, "a", "a.py", key="shared"),
            _candidate(source.revision, "b", "b.py", key="shared"),
            _candidate(source.revision, "ok", "ok.py", key="ok"),
        ],
    )

    snapshot = service.build(analysis_run_id="run-1")

    assert [item["origin_candidate_ids"] for item in snapshot.components] == [["ok"]]
    assert snapshot.manifest["unresolved_overlap_group_ids"]
    assert set(snapshot.coverage["unresolved_file_ids"]) == {
        "file:a.py",
        "file:b.py",
    }


def test_manifest_applies_reconciled_partitions_without_name_based_identity(
    tmp_path: Path,
) -> None:
    _, source = _source(tmp_path)
    left = _candidate(source.revision, "left", "app.py", key="shared")
    right = _candidate(source.revision, "right", "app.py", key="shared")
    helper = _candidate(source.revision, "helper", "helper.py", key="helper")
    service = _write_candidates(tmp_path, [left, right, helper])
    group_id = str(service.overlaps.load()[0]["id"])
    reconciliation = {
        "schema_version": 1,
        "record_type": "component_reconciliation",
        "repository_revision": source.revision,
        "analysis_run_id": "run-1",
        "overlap_group_id": group_id,
        "decision": "same",
        "partitions": [
            {
                "candidate_ids": ["left", "right"],
                "name": "Merged name",
                "aliases": ["Historical name"],
                "reason": "Both candidates own the same exact symbol.",
            }
        ],
        "reason": "The source defines one construct.",
        "limitations": [],
    }
    ComponentReconciliationService(tmp_path, store=service.store).ingest(
        group_id,
        json.dumps(reconciliation),
        attempt_id="same-1",
    )

    snapshot = service.build(analysis_run_id="run-1")

    assert len(snapshot.components) == 2
    merged = service.query_components(alias="Historical name")[0]
    assert merged["name"] == "Merged name"
    assert merged["origin_candidate_ids"] == ["left", "right"]
    assert merged["reconciliation_ids"]


def test_clean_manifest_accounts_for_owned_and_supporting_files(tmp_path: Path) -> None:
    _, source = _source(tmp_path)
    service = _write_candidates(
        tmp_path,
        [
            _candidate(
                source.revision,
                "app",
                "app.py",
                key="app-key",
                supporting=("helper.py",),
            )
        ],
    )

    snapshot = service.build(analysis_run_id="run-1")

    assert snapshot.manifest["status"] == "complete"
    assert snapshot.coverage["owned_count"] == 1
    assert snapshot.coverage["supporting_count"] == 1
    assert snapshot.coverage["unresolved_count"] == 0


def test_missing_file_investigation_runs_once_and_uses_context_bundle(
    tmp_path: Path,
) -> None:
    _, source = _source(tmp_path)
    service = _write_candidates(
        tmp_path,
        [_candidate(source.revision, "app", "app.py", key="app-key")],
    )
    prompts: list[str] = []

    def investigate(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "schema_version": 1,
                "record_type": "file_disposition",
                "repository_revision": source.revision,
                "file_id": "file:helper.py",
                "disposition": "repository_infrastructure",
                "component_ids": [],
                "reason": "Repository maintenance helper.",
            }
        )

    first = service.build(analysis_run_id="run-1", investigator=investigate)
    second = service.build(analysis_run_id="run-1", investigator=investigate)

    assert first.manifest["status"] == "complete"
    assert second.manifest["status"] == "complete"
    assert len(prompts) == 1
    assert "Read the complete investigation context first" in prompts[0]
    context = service.store.read_json(service.context_path)
    assert context["attempted"] is True
    assert "raw_ctags" in context["artifact_paths"]
    assert "reconciliations" in context["artifact_paths"]


def test_missing_file_pass_rejects_catch_all_and_keeps_course_usable(
    tmp_path: Path,
) -> None:
    _, source = _source(tmp_path)
    service = _write_candidates(
        tmp_path,
        [_candidate(source.revision, "app", "app.py", key="app-key")],
    )
    catch_all = _candidate(source.revision, "misc", "helper.py", key="helper-key")
    catch_all["name"] = "Miscellaneous unclassified files"

    snapshot = service.build(
        analysis_run_id="run-1",
        investigator=lambda prompt: json.dumps(catch_all),
    )

    assert snapshot.manifest["status"] == "complete_with_warnings"
    assert snapshot.coverage["unresolved_file_ids"] == ["file:helper.py"]
    assert not service.query_components(candidate_id="misc")
    warnings = service.store.active_diagnostics("warning")
    assert any(item["code"] == "catch-all-component-rejected" for item in warnings)
