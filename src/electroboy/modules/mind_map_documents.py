"""Project-backed editable mind-map documents."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from electroboy.state_store import StateError

MIND_MAP_SUFFIX = ".mindmap.json"
MIND_MAP_SCHEMA_VERSION = 1
MIND_MAP_TYPE = "electroboy.mind-map"
DEFAULT_MIND_MAP_DIRECTORY = Path(".electroboy") / "shared" / "mind-maps"
ROOT_NODE_FONT_SIZE = 24.0
NODE_FONT_SIZE_STEP = 3.0
MINIMUM_NODE_FONT_SIZE = 14.0
DEFAULT_NODE_WIDTH = 260.0
DEFAULT_NODE_MIN_HEIGHT = 58.0
NODE_COLORS = frozenset(
    {"default", "violet", "blue", "teal", "green", "amber", "rose"}
)


def _revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def resolve_mind_map_path(root: Path, value: str) -> Path:
    """Resolve an absolute or project-relative mind-map path."""

    raw = value.strip()
    if not raw:
        raise StateError("mind map path is required")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    if not candidate.name.endswith(MIND_MAP_SUFFIX):
        raise StateError(f"mind map path must end with {MIND_MAP_SUFFIX}")
    return candidate


def empty_mind_map(title: str = "Untitled mind map") -> dict[str, object]:
    return {
        "schema_version": MIND_MAP_SCHEMA_VERSION,
        "type": MIND_MAP_TYPE,
        "title": title.strip() or "Untitled mind map",
        "nodes": [],
        "relationships": [],
    }


def _finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateError(f"{field} must be a number")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise StateError(f"{field} must be finite")
    return number


def _normalize_link(value: object, *, node_id: str, index: int) -> dict[str, str]:
    if not isinstance(value, dict):
        raise StateError(f"node {node_id} link {index} must be an object")
    link_type = str(value.get("type") or "").strip().lower()
    if link_type == "web":
        link_type = "url"
    if link_type not in {"document", "file", "url"}:
        raise StateError(f"node {node_id} link {index} has an invalid type")
    target = str(value.get("target") or value.get("url") or "").strip()
    if not target:
        raise StateError(f"node {node_id} link {index} has no target")
    if link_type == "url" and urlparse(target).scheme.lower() not in {
        "http",
        "https",
    }:
        raise StateError(f"node {node_id} link {index} has an unsupported URL")
    label = str(value.get("label") or "").strip()
    return {"type": link_type, "target": target, "label": label}


def normalize_mind_map(value: object) -> dict[str, object]:
    """Validate and return the stable editable-map representation."""

    if not isinstance(value, dict):
        raise StateError("mind map document must be an object")
    version = value.get("schema_version", MIND_MAP_SCHEMA_VERSION)
    if version != MIND_MAP_SCHEMA_VERSION:
        raise StateError(f"unsupported mind map schema version: {version}")
    raw_nodes = value.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise StateError("mind map nodes must be a list")

    nodes: list[dict[str, object]] = []
    node_ids: set[str] = set()
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise StateError(f"mind map node {index} must be an object")
        node_id = str(raw_node.get("id") or "").strip()
        if not node_id:
            raise StateError(f"mind map node {index} has no id")
        if node_id in node_ids:
            raise StateError(f"duplicate mind map node id: {node_id}")
        node_ids.add(node_id)
        raw_links = raw_node.get("links", [])
        if not isinstance(raw_links, list):
            raise StateError(f"node {node_id} links must be a list")
        parent = str(raw_node.get("parent_id") or "").strip() or None
        order = raw_node.get("order", index)
        if isinstance(order, bool) or not isinstance(order, int):
            raise StateError(f"node {node_id} order must be an integer")
        color = str(raw_node.get("color") or "default").strip().lower()
        if color not in NODE_COLORS:
            raise StateError(f"node {node_id} has an invalid color")
        font_size_mode = str(raw_node.get("font_size_mode") or "auto").strip().lower()
        if font_size_mode not in {"auto", "custom"}:
            raise StateError(f"node {node_id} has an invalid font_size_mode")
        raw_font_size = raw_node.get("font_size") if font_size_mode == "custom" else None
        font_size = (
            _finite_number(raw_font_size, field=f"node {node_id} font_size")
            if raw_font_size is not None
            else None
        )
        if font_size is not None and font_size <= 0:
            raise StateError(f"node {node_id} font_size must be greater than zero")
        if font_size_mode == "custom" and font_size is None:
            raise StateError(f"node {node_id} custom font_size is required")
        width = _finite_number(
            raw_node.get("width", DEFAULT_NODE_WIDTH),
            field=f"node {node_id} width",
        )
        min_height = _finite_number(
            raw_node.get("min_height", DEFAULT_NODE_MIN_HEIGHT),
            field=f"node {node_id} min_height",
        )
        if width <= 0 or min_height <= 0:
            raise StateError(
                f"node {node_id} width and min_height must be greater than zero"
            )
        nodes.append(
            {
                "id": node_id,
                "text": str(raw_node.get("text") or ""),
                "parent_id": parent,
                "order": order,
                "x": _finite_number(
                    raw_node.get("x", 80.0), field=f"node {node_id} x"
                ),
                "y": _finite_number(
                    raw_node.get("y", 80.0), field=f"node {node_id} y"
                ),
                "color": color,
                "font_size": font_size,
                "font_size_mode": font_size_mode,
                "width": width,
                "min_height": min_height,
                "links": [
                    _normalize_link(link, node_id=node_id, index=link_index)
                    for link_index, link in enumerate(raw_links)
                ],
            }
        )

    parents = {str(node["id"]): node["parent_id"] for node in nodes}
    for node_id, parent_id in parents.items():
        if parent_id is not None and parent_id not in node_ids:
            raise StateError(f"node {node_id} has an unknown parent: {parent_id}")
        seen = {node_id}
        ancestor = parent_id
        while ancestor is not None:
            if ancestor in seen:
                raise StateError(f"mind map contains a parent cycle at node {node_id}")
            seen.add(ancestor)
            ancestor = parents.get(ancestor)

    nodes_by_id = {str(node["id"]): node for node in nodes}

    def fill_default_font_size(node_id: str) -> float:
        node = nodes_by_id[node_id]
        font_size = node["font_size"]
        if node["font_size_mode"] == "custom" and isinstance(
            font_size, (int, float)
        ):
            return float(font_size)
        parent_id = node["parent_id"]
        if parent_id is None:
            font_size = ROOT_NODE_FONT_SIZE
        else:
            font_size = max(
                MINIMUM_NODE_FONT_SIZE,
                fill_default_font_size(str(parent_id)) - NODE_FONT_SIZE_STEP,
            )
        node["font_size"] = font_size
        return font_size

    for node_id in node_ids:
        fill_default_font_size(node_id)

    raw_relationships = value.get("relationships", [])
    if not isinstance(raw_relationships, list):
        raise StateError("mind map relationships must be a list")
    relationships: list[dict[str, str]] = []
    for index, raw_relationship in enumerate(raw_relationships):
        if not isinstance(raw_relationship, dict):
            raise StateError(f"relationship {index} must be an object")
        source = str(raw_relationship.get("source") or "").strip()
        target = str(raw_relationship.get("target") or "").strip()
        if source not in node_ids or target not in node_ids:
            raise StateError(f"relationship {index} references an unknown node")
        relationships.append(
            {
                "source": source,
                "target": target,
                "label": str(raw_relationship.get("label") or "").strip(),
            }
        )

    return {
        "schema_version": MIND_MAP_SCHEMA_VERSION,
        "type": MIND_MAP_TYPE,
        "title": str(value.get("title") or "Untitled mind map").strip()
        or "Untitled mind map",
        "nodes": nodes,
        "relationships": relationships,
    }


def _encode(document: dict[str, object]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()


def load_mind_map(root: Path, value: str) -> dict[str, object]:
    path = resolve_mind_map_path(root, value)
    try:
        content = path.read_bytes()
        raw: Any = json.loads(content)
    except FileNotFoundError as error:
        raise StateError(f"mind map does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise StateError(f"invalid mind map JSON: {error}") from error
    return {
        "path": str(path),
        "revision": _revision(content),
        "document": normalize_mind_map(raw),
    }


def save_mind_map(
    root: Path,
    value: str,
    document: object,
    *,
    expected_revision: str | None = None,
    create: bool = False,
) -> dict[str, object]:
    path = resolve_mind_map_path(root, value)
    normalized = normalize_mind_map(document)
    if path.exists():
        existing = path.read_bytes()
        if create:
            raise StateError(f"mind map already exists: {path}")
        if expected_revision is None:
            raise StateError("expected_revision is required when saving a mind map")
        if _revision(existing) != expected_revision:
            raise StateError("mind map changed on disk; reload it before saving")
    elif not create:
        raise StateError(f"mind map does not exist: {path}")

    content = _encode(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = temporary.name
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)
    return {
        "path": str(path),
        "revision": _revision(content),
        "document": normalized,
    }


def list_mind_maps(root: Path) -> list[dict[str, str]]:
    maps: list[dict[str, str]] = []
    directory = root / DEFAULT_MIND_MAP_DIRECTORY
    if not directory.is_dir():
        return maps
    for path in sorted(directory.rglob(f"*{MIND_MAP_SUFFIX}")):
        if not path.is_file():
            continue
        try:
            payload = load_mind_map(root, str(path))
        except StateError:
            continue
        document = payload["document"]
        assert isinstance(document, dict)
        maps.append(
            {
                "path": str(path),
                "relative_path": path.relative_to(root).as_posix(),
                "title": str(document["title"]),
            }
        )
    return maps


def default_mind_map_path(title: str) -> Path:
    slug = "-".join(
        part for part in "".join(
            character.lower() if character.isalnum() else " " for character in title
        ).split()
    )
    return DEFAULT_MIND_MAP_DIRECTORY / f"{slug or 'untitled'}{MIND_MAP_SUFFIX}"
