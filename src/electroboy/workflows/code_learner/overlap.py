"""Deterministic exact-symbol overlap grouping for component candidates."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

from .phase3_contracts import validate_overlap_groups
from .phase3_store import Phase3Store


class ComponentOverlapService:
    """Create reconciliation scopes only from exact canonical symbol overlap."""

    def __init__(self, root: Path | str, *, store: Phase3Store | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.path = self.store.components_root / "overlap-groups.jsonl"

    def build(
        self,
        candidates: Iterable[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        records = [dict(candidate) for candidate in candidates]
        records_by_id = {
            str(record.get("candidate_id") or ""): record for record in records
        }
        candidate_ids = set(records_by_id)
        by_symbol: dict[str, set[str]] = defaultdict(set)
        for record in records:
            candidate_id = str(record.get("candidate_id") or "")
            for symbol in record.get("symbols", []):
                if not isinstance(symbol, Mapping):
                    continue
                canonical_key = str(symbol.get("canonical_key") or "")
                if canonical_key:
                    by_symbol[canonical_key].add(candidate_id)
        shared = {
            key: members for key, members in by_symbol.items() if len(members) > 1
        }
        parent = {candidate_id: candidate_id for candidate_id in candidate_ids}
        for members in shared.values():
            ordered = sorted(members)
            for member in ordered[1:]:
                _union(parent, ordered[0], member)
        partitions: dict[str, set[str]] = defaultdict(set)
        for candidate_id in candidate_ids:
            if any(candidate_id in members for members in shared.values()):
                partitions[_find(parent, candidate_id)].add(candidate_id)
        revision = next(
            (
                str(record.get("repository_revision") or "")
                for record in records
                if record.get("repository_revision")
            ),
            "",
        )
        groups: list[dict[str, object]] = []
        for members in sorted(
            partitions.values(), key=lambda value: tuple(sorted(value))
        ):
            edges = [
                {
                    "canonical_key": key,
                    "candidate_ids": sorted(symbol_members & members),
                }
                for key, symbol_members in sorted(shared.items())
                if len(symbol_members & members) > 1
            ]
            identity = "\0".join(
                sorted(members) + [edge["canonical_key"] for edge in edges]
            )
            shared_keys = {str(edge["canonical_key"]) for edge in edges}
            symbol_sets = []
            for candidate_id in sorted(members):
                keys = sorted(
                    str(symbol.get("canonical_key") or "")
                    for symbol in records_by_id[candidate_id].get("symbols", [])
                    if isinstance(symbol, Mapping) and symbol.get("canonical_key")
                )
                symbol_sets.append(
                    {
                        "candidate_id": candidate_id,
                        "shared_canonical_keys": [
                            key for key in keys if key in shared_keys
                        ],
                        "exclusive_canonical_keys": [
                            key for key in keys if key not in shared_keys
                        ],
                    }
                )
            candidate_revision = hashlib.sha256(
                "\0".join(
                    f"{item['candidate_id']}:{','.join(item['shared_canonical_keys'])}:"
                    f"{','.join(item['exclusive_canonical_keys'])}"
                    for item in symbol_sets
                ).encode()
            ).hexdigest()
            groups.append(
                {
                    "schema_version": 1,
                    "record_type": "overlap_group",
                    "id": (
                        f"overlap:{hashlib.sha256(identity.encode()).hexdigest()[:16]}"
                    ),
                    "repository_revision": revision,
                    "candidate_revision": candidate_revision,
                    "candidate_ids": sorted(members),
                    "shared_symbol_edges": edges,
                    "candidate_symbol_sets": symbol_sets,
                    "status": "pending",
                }
            )
        validated = validate_overlap_groups(groups, candidate_ids=candidate_ids)
        self.store.write_jsonl(self.path, validated)
        return validated

    def load(self) -> list[dict[str, object]]:
        return self.store.read_jsonl(self.path)

    def by_candidate(self, candidate_id: str) -> list[dict[str, object]]:
        return [
            record
            for record in self.load()
            if candidate_id in record.get("candidate_ids", [])
        ]

    def by_symbol(self, canonical_key: str) -> list[dict[str, object]]:
        return [
            record
            for record in self.load()
            if any(
                edge.get("canonical_key") == canonical_key
                for edge in record.get("shared_symbol_edges", [])
                if isinstance(edge, Mapping)
            )
        ]


def _find(parent: dict[str, str], item: str) -> str:
    while parent[item] != item:
        parent[item] = parent[parent[item]]
        item = parent[item]
    return item


def _union(parent: dict[str, str], left: str, right: str) -> None:
    left_root = _find(parent, left)
    right_root = _find(parent, right)
    if left_root != right_root:
        parent[max(left_root, right_root)] = min(left_root, right_root)
