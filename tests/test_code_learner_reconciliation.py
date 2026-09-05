from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.adapters.base import AgentResult
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.phase3_prompts import (
    component_reconciliation_prompt,
)
from electroboy.workflows.code_learner.phase3_store import Phase3Store
from electroboy.workflows.code_learner.reconciliation import (
    ComponentReconciliationService,
)


class FakeRuntime:
    def __init__(self, outputs: list[AgentResult]) -> None:
        self.outputs = outputs
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return self.outputs.pop(0)


def _candidate(candidate_id: str, keys: tuple[str, ...]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "component_candidate",
        "repository_revision": "revision-1",
        "candidate_id": candidate_id,
        "name": f"Name {candidate_id}",
        "kind": "service",
        "responsibility": f"Responsibility {candidate_id}",
        "file_ids": [f"file:{candidate_id}.py"],
        "symbols": [
            {
                "file_id": f"file:{candidate_id}.py",
                "name": key,
                "kind": "function",
                "start_line": 1,
                "end_line": 2,
                "canonical_key": key,
                "validated_by": "universal-ctags",
            }
            for key in keys
        ],
        "owned_source_refs": [],
        "supporting_source_refs": [],
        "aliases": [],
        "limitations": [],
    }


def _setup(root: Path) -> tuple[ComponentReconciliationService, dict[str, object]]:
    store = Phase3Store(root)
    candidates = [
        _candidate("a", ("shared-ab", "only-a")),
        _candidate("b", ("shared-ab", "shared-bc")),
        _candidate("c", ("shared-bc", "only-c")),
    ]
    group = {
        "schema_version": 1,
        "record_type": "overlap_group",
        "id": "overlap:one",
        "repository_revision": "revision-1",
        "candidate_revision": "candidate-revision",
        "candidate_ids": ["a", "b", "c"],
        "shared_symbol_edges": [
            {"canonical_key": "shared-ab", "candidate_ids": ["a", "b"]},
            {"canonical_key": "shared-bc", "candidate_ids": ["b", "c"]},
        ],
    }
    store.write_jsonl(store.components_root / "candidates.jsonl", candidates)
    store.write_jsonl(store.components_root / "overlap-groups.jsonl", [group])
    return ComponentReconciliationService(root, store=store), group


def _record(decision: str, partitions: list[list[str]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "component_reconciliation",
        "repository_revision": "revision-1",
        "analysis_run_id": "run-1",
        "overlap_group_id": "overlap:one",
        "decision": decision,
        "partitions": [
            {"candidate_ids": members, "reason": "Source-backed decision."}
            for members in partitions
        ],
        "reason": "Compared exact shared and exclusive symbols.",
        "limitations": [],
    }


def test_same_reconciliation_merges_membership_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    service, _ = _setup(tmp_path)

    result = service.ingest(
        "overlap:one",
        "\n" + json.dumps(_record("same", [["a", "b", "c"]])) + "\n",
        attempt_id="same-1",
    )

    partition = result.resolved_partitions[0]
    assert partition["origin_candidate_ids"] == ["a", "b", "c"]
    assert partition["aliases"] == ["Name b", "Name c"]
    assert partition["reconciliation_ids"] == ["reconciliation:overlap-one"]
    assert len(partition["symbols"]) == 4
    assert service.pending_group_ids() == []


def test_distinct_and_mixed_partitions_preserve_intentional_overlap(
    tmp_path: Path,
) -> None:
    service, _ = _setup(tmp_path)

    result = service.ingest(
        "overlap:one",
        json.dumps(_record("distinct", [["a", "b"], ["c"]])),
        attempt_id="mixed-1",
    )

    assert [item["origin_candidate_ids"] for item in result.resolved_partitions] == [
        ["a", "b"],
        ["c"],
    ]
    assert result.resolved_partitions[0]["intentional_shared_symbol_keys"] == [
        "shared-ab",
        "shared-bc",
    ]
    assert result.resolved_partitions[1]["intentional_shared_symbol_keys"] == [
        "shared-bc"
    ]
    assert "relationship" not in json.dumps(result.record)


@pytest.mark.parametrize(
    "record",
    [
        _record("distinct", [["a"], ["b"]]),
        _record("same", [["a", "b"], ["c"]]),
        {
            **_record("distinct", [["a"], ["b"], ["c"]]),
            "relationships": [],
        },
        {
            **_record("distinct", [["a"], ["b"], ["c"]]),
            "partitions": [
                {"candidate_ids": ["a"], "file_ids": ["file:external.py"]},
                {"candidate_ids": ["b"]},
                {"candidate_ids": ["c"]},
            ],
        },
    ],
)
def test_malformed_or_out_of_scope_reconciliation_is_rejected(
    tmp_path: Path, record: dict[str, object]
) -> None:
    service, _ = _setup(tmp_path)

    with pytest.raises(CodeLearnerError):
        service.ingest("overlap:one", json.dumps(record), attempt_id="bad-1")

    assert service.load() == []


def test_runtime_retries_only_failed_group_and_restart_skips_completed(
    tmp_path: Path,
) -> None:
    service, _ = _setup(tmp_path)
    runtime = FakeRuntime(
        [
            AgentResult(False, "", error="temporary failure"),
            AgentResult(True, json.dumps(_record("distinct", [["a"], ["b"], ["c"]]))),
        ]
    )
    service.runtime_factory = lambda role, root: runtime

    records = service.reconcile_pending(analysis_run_id="run-1")

    assert len(records) == 1
    assert len(runtime.invocations) == 2
    assert "previous response" in runtime.invocations[1].prompt
    restarted = ComponentReconciliationService(
        tmp_path, runtime_factory=lambda role, root: FakeRuntime([])
    )
    assert restarted.pending_group_ids() == []


def test_reconciliation_prompt_is_complete_and_forbids_scope_drift(
    tmp_path: Path,
) -> None:
    service, group = _setup(tmp_path)
    _, candidates = service._scope("overlap:one")

    prompt = component_reconciliation_prompt(
        tmp_path,
        analysis_run_id="run-1",
        group=group,
        candidates=candidates,
        source_manifest_path="source/manifest.json",
        files_path="source/files.jsonl",
        schema_path="phase3.schema.json",
    )

    assert "shared-ab" in prompt
    assert "only-a" in prompt
    assert "Responsibility a" in prompt
    assert "supporting_source_refs" in prompt
    assert "every input candidate exactly once" in prompt
    assert "relationships, hierarchy" in prompt
