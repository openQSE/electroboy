"""Public provider contract for workflow-backed mind maps."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from electroboy.state_store import StateError

MIND_MAP_GROUPS = ("sources", "observations", "provider_events", "facts")
MIND_MAP_KINDS = {"source", "observation", "provider_event", "fact"}
MIND_MAP_DEFAULT_LEVELS = ("source", "observation", "fact")


class MindMapProvider(Protocol):
    """Translate workflow-owned records into generic source traceability maps."""

    provider_id: str

    def load_mind_map(
        self,
        context_id: str,
        *,
        filters: dict[str, str],
        connection_id: str = "",
    ) -> dict[str, object]: ...


@runtime_checkable
class MindMapWorkflowController(Protocol):
    """Structural controller capability consumed by the Mind Map module."""

    def get_mind_map_provider(self) -> MindMapProvider: ...


def _node_kind(group: str) -> str:
    if group == "sources":
        return "source"
    if group == "provider_events":
        return "provider_event"
    return group.removesuffix("s")


def _normalize_confidence(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError) as error:
        raise StateError("mind map confidence must be numeric") from error
    if not 0 <= confidence <= 1:
        raise StateError("mind map confidence is out of range")
    return confidence


def _normalize_node(
    entry: object,
    *,
    group: str,
    index: int,
) -> dict[str, object]:
    if not isinstance(entry, dict):
        raise StateError(f"mind map {group} node {index + 1} must be an object")
    node_id = str(entry.get("id") or "").strip()
    if not node_id:
        raise StateError(f"mind map {group} node {index + 1} id is required")
    kind = str(entry.get("kind") or _node_kind(group)).strip().lower()
    if kind not in MIND_MAP_KINDS:
        raise StateError(f"mind map node {node_id} has unknown kind: {kind}")
    title = str(entry.get("title") or entry.get("label") or node_id).strip()
    if not title:
        raise StateError(f"mind map node {node_id} title is required")
    member_labels = entry.get("member_labels") or []
    if not isinstance(member_labels, list):
        raise StateError("mind map node member_labels must be a list")
    return {
        **entry,
        "id": node_id,
        "kind": kind,
        "title": title,
        "status": str(entry.get("status") or "").strip(),
        "confidence": _normalize_confidence(entry.get("confidence")),
        "member_labels": [str(value) for value in member_labels if str(value)],
    }


def _normalize_edge(
    entry: object,
    *,
    index: int,
    node_ids: set[str],
) -> dict[str, object]:
    if not isinstance(entry, dict):
        raise StateError(f"mind map edge {index + 1} must be an object")
    source_id = str(entry.get("from") or entry.get("source") or "").strip()
    target_id = str(entry.get("to") or entry.get("target") or "").strip()
    if not source_id or not target_id:
        raise StateError(f"mind map edge {index + 1} needs from and to ids")
    if source_id not in node_ids:
        raise StateError(f"mind map edge references unknown node: {source_id}")
    if target_id not in node_ids:
        raise StateError(f"mind map edge references unknown node: {target_id}")
    tree_source_id = str(entry.get("tree_from") or source_id).strip()
    tree_target_id = str(entry.get("tree_to") or target_id).strip()
    if tree_source_id not in node_ids or tree_target_id not in node_ids:
        raise StateError("mind map primary projection references an unknown node")
    return {
        **entry,
        "id": str(entry.get("id") or f"edge-{index + 1}"),
        "from": source_id,
        "to": target_id,
        "relationship": str(entry.get("relationship") or "linked").strip(),
        "family": str(entry.get("family") or "other").strip().lower(),
        "primary": bool(entry.get("primary", False)),
        "directed": bool(entry.get("directed", True)),
        "state": str(entry.get("state") or "active").strip().lower(),
        "confidence": _normalize_confidence(entry.get("confidence")),
        "tree_from": tree_source_id,
        "tree_to": tree_target_id,
    }


def normalize_mind_map_snapshot(
    payload: dict[str, object],
    *,
    provider_id: str,
) -> dict[str, object]:
    """Validate provider data for a source-first provenance graph."""

    title = str(payload.get("title") or "").strip()
    if not title:
        raise StateError("mind map title is required")
    levels_value = payload.get("levels") or list(MIND_MAP_DEFAULT_LEVELS)
    if not isinstance(levels_value, list):
        raise StateError("mind map levels must be a list")
    levels = [str(value).strip() for value in levels_value if str(value).strip()]
    if not levels:
        levels = list(MIND_MAP_DEFAULT_LEVELS)
    unknown_levels = set(levels) - MIND_MAP_KINDS
    if unknown_levels:
        unknown = ", ".join(sorted(unknown_levels))
        raise StateError(f"mind map levels contain unknown kinds: {unknown}")

    normalized: dict[str, object] = {
        **payload,
        "provider": provider_id,
        "title": title,
        "subtitle": str(payload.get("subtitle") or "").strip(),
        "levels": levels,
    }
    node_ids: set[str] = set()
    for group in MIND_MAP_GROUPS:
        value = payload.get(group) or []
        if not isinstance(value, list):
            raise StateError(f"mind map {group} must be a list")
        nodes = [
            _normalize_node(entry, group=group, index=index)
            for index, entry in enumerate(value)
        ]
        duplicate_ids = node_ids.intersection({str(node["id"]) for node in nodes})
        if duplicate_ids:
            duplicate = ", ".join(sorted(duplicate_ids))
            raise StateError(f"mind map contains duplicate node ids: {duplicate}")
        node_ids.update(str(node["id"]) for node in nodes)
        normalized[group] = nodes

    edges_value = payload.get("edges") or []
    if not isinstance(edges_value, list):
        raise StateError("mind map edges must be a list")
    normalized_edges = [
        _normalize_edge(entry, index=index, node_ids=node_ids)
        for index, entry in enumerate(edges_value)
    ]
    edge_ids = [str(edge["id"]) for edge in normalized_edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise StateError("mind map contains duplicate edge ids")
    normalized["edges"] = normalized_edges
    styles_value = payload.get("relationship_styles") or {}
    if not isinstance(styles_value, dict):
        raise StateError("mind map relationship_styles must be an object")
    normalized["relationship_styles"] = {
        str(family).strip().lower(): {
            "label": str(
                (style if isinstance(style, dict) else {}).get("label") or family
            ).strip(),
            "color": str(
                (style if isinstance(style, dict) else {}).get("color") or "#4DA3FF"
            ).strip(),
        }
        for family, style in styles_value.items()
        if str(family).strip()
    }
    capabilities = payload.get("capabilities") or []
    if not isinstance(capabilities, list):
        raise StateError("mind map capabilities must be a list")
    normalized["capabilities"] = [str(value) for value in capabilities if str(value)]
    return normalized
