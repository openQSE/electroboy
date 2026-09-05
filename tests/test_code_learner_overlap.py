from __future__ import annotations

from pathlib import Path

from electroboy.workflows.code_learner.overlap import ComponentOverlapService


def _candidate(
    candidate_id: str,
    *,
    file_id: str,
    keys: tuple[str, ...],
    name: str = "Component",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "component_candidate",
        "repository_revision": "revision-1",
        "candidate_id": candidate_id,
        "name": name,
        "kind": "service",
        "responsibility": "Fixture.",
        "file_ids": [file_id],
        "symbols": [
            {
                "file_id": file_id,
                "name": key,
                "kind": "function",
                "start_line": index + 1,
                "end_line": index + 1,
                "canonical_key": key,
            }
            for index, key in enumerate(keys)
        ],
        "supporting_source_refs": [],
    }


def test_overlap_groups_are_transitive_and_retain_direct_edges(tmp_path: Path) -> None:
    service = ComponentOverlapService(tmp_path)
    candidates = [
        _candidate("a", file_id="file:a.py", keys=("shared-ab",)),
        _candidate("b", file_id="file:b.py", keys=("shared-ab", "shared-bc")),
        _candidate("c", file_id="file:c.py", keys=("shared-bc",)),
    ]

    groups = service.build(candidates)

    assert len(groups) == 1
    assert groups[0]["candidate_ids"] == ["a", "b", "c"]
    assert groups[0]["shared_symbol_edges"] == [
        {"canonical_key": "shared-ab", "candidate_ids": ["a", "b"]},
        {"canonical_key": "shared-bc", "candidate_ids": ["b", "c"]},
    ]
    assert groups[0]["candidate_symbol_sets"] == [
        {
            "candidate_id": "a",
            "shared_canonical_keys": ["shared-ab"],
            "exclusive_canonical_keys": [],
        },
        {
            "candidate_id": "b",
            "shared_canonical_keys": ["shared-ab", "shared-bc"],
            "exclusive_canonical_keys": [],
        },
        {
            "candidate_id": "c",
            "shared_canonical_keys": ["shared-bc"],
            "exclusive_canonical_keys": [],
        },
    ]
    assert len(groups[0]["candidate_revision"]) == 64
    assert service.by_candidate("b") == groups
    assert service.by_symbol("shared-ab") == groups


def test_shared_files_names_kinds_and_descriptions_do_not_trigger_overlap(
    tmp_path: Path,
) -> None:
    service = ComponentOverlapService(tmp_path)
    candidates = [
        _candidate("a", file_id="file:shared.py", keys=("key-a",), name="Same"),
        _candidate("b", file_id="file:shared.py", keys=("key-b",), name="Same"),
    ]

    assert service.build(candidates) == []


def test_supporting_only_references_do_not_trigger_overlap(tmp_path: Path) -> None:
    service = ComponentOverlapService(tmp_path)
    left = _candidate("a", file_id="file:a.py", keys=("key-a",))
    right = _candidate("b", file_id="file:b.py", keys=("key-b",))
    left["supporting_source_refs"] = [
        {
            "file_id": "file:shared.py",
            "symbol": {"canonical_key": "shared"},
        }
    ]
    right["supporting_source_refs"] = list(left["supporting_source_refs"])

    assert service.build([left, right]) == []


def test_overlap_storage_and_order_are_deterministic(tmp_path: Path) -> None:
    service = ComponentOverlapService(tmp_path)
    candidates = [
        _candidate("b", file_id="file:b.py", keys=("shared",)),
        _candidate("a", file_id="file:a.py", keys=("shared",)),
    ]

    first = service.build(candidates)
    second = service.build(reversed(candidates))

    assert first == second
    assert service.load() == first
