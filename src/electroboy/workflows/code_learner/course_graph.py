"""Layered course graph projection and durable navigation state."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from electroboy.models import utc_now

from .contracts import parse_jsonl, validate_course_records
from .domain import CodeLearnerError
from .knowledge_store import KnowledgeStore


@dataclass(frozen=True)
class CourseNode:
    """One navigable course section."""

    id: str
    course_id: str
    title: str
    mode: str
    scope_id: str
    parent_id: str
    previous_id: str
    next_id: str
    return_id: str
    deep_dive_ids: tuple[str, ...]
    source_ref: Mapping[str, object] | None
    order: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "course_id": self.course_id,
            "title": self.title,
            "mode": self.mode,
            "scope_id": self.scope_id,
            "parent_id": self.parent_id,
            "previous_id": self.previous_id,
            "next_id": self.next_id,
            "return_id": self.return_id,
            "deep_dive_ids": list(self.deep_dive_ids),
            "source_ref": dict(self.source_ref) if self.source_ref else None,
            "order": self.order,
        }


class CourseGraph:
    """Read-only projection of independently persisted course artifacts."""

    def __init__(
        self,
        nodes: Mapping[str, CourseNode],
        documents: Mapping[str, dict[str, object]],
        target_states: Mapping[str, str],
    ) -> None:
        self.nodes = dict(nodes)
        self.documents = {key: dict(value) for key, value in documents.items()}
        self.target_states = dict(target_states)

    @classmethod
    def from_store(cls, store: KnowledgeStore) -> CourseGraph:
        nodes: dict[str, CourseNode] = {}
        documents: dict[str, dict[str, object]] = {}
        states: dict[str, str] = {}
        index = store.load_course_index().get("courses", {})
        if isinstance(index, dict):
            for item in index.values():
                if not isinstance(item, dict):
                    continue
                key = _target_key(
                    str(item.get("mode") or ""), str(item.get("scope_id") or "")
                )
                states[key] = str(item.get("status") or "missing")
        if not store.courses_root.is_dir():
            return cls(nodes, documents, states)
        for path in sorted(store.courses_root.rglob("*.jsonl")):
            records = validate_course_records(
                parse_jsonl(
                    path.read_text(encoding="utf-8"),
                    artifact=path.relative_to(store.root).as_posix(),
                ),
                knowledge_ids=store.knowledge_ids(),
                root=store.root,
            )
            document = next(
                record
                for record in records
                if record.get("record_type") == "document"
            )
            document_id = str(document["id"])
            mode = str(document["course_mode"])
            scope_id = str(document["scope_id"])
            documents[document_id] = document
            states.setdefault(document_id, str(document.get("status") or "ready"))
            sections = sorted(
                (
                    record
                    for record in records
                    if record.get("record_type") == "section"
                ),
                key=lambda record: (int(record.get("order") or 0), str(record["id"])),
            )
            for index_in_course, section in enumerate(sections):
                section_id = str(section["id"])
                previous_id = str(section.get("previous_section_id") or "")
                next_id = str(section.get("next_section_id") or "")
                if not previous_id and index_in_course:
                    previous_id = str(sections[index_in_course - 1]["id"])
                if not next_id and index_in_course + 1 < len(sections):
                    next_id = str(sections[index_in_course + 1]["id"])
                source_refs = section.get("source_refs", [])
                source_ref = (
                    source_refs[0]
                    if isinstance(source_refs, list)
                    and source_refs
                    and isinstance(source_refs[0], dict)
                    else None
                )
                nodes[section_id] = CourseNode(
                    id=section_id,
                    course_id=document_id,
                    title=str(section.get("title") or section_id),
                    mode=mode,
                    scope_id=scope_id,
                    parent_id=str(section.get("parent_id") or document_id),
                    previous_id=previous_id,
                    next_id=next_id,
                    return_id=str(section.get("return_section_id") or ""),
                    deep_dive_ids=tuple(
                        str(item) for item in section.get("deep_dive_ids", [])
                    ),
                    source_ref=source_ref,
                    order=int(section.get("order") or 0),
                )
        return cls(nodes, documents, states)

    def first_section(self, course_id: str) -> CourseNode:
        candidates = [
            node for node in self.nodes.values() if node.course_id == course_id
        ]
        if not candidates:
            raise CodeLearnerError(f"course has no sections: {course_id}")
        return min(candidates, key=lambda node: (node.order, node.id))

    def node(self, section_id: str) -> CourseNode:
        try:
            return self.nodes[section_id]
        except KeyError as error:
            raise CodeLearnerError(f"unknown course section: {section_id}") from error

    def target_state(self, target_id: str) -> str:
        if target_id in self.documents:
            return self.target_states.get(target_id, "ready")
        if target_id in self.nodes:
            return self.target_states.get(self.nodes[target_id].course_id, "ready")
        return self.target_states.get(target_id, "missing")

    def to_dict(self) -> dict[str, object]:
        return {
            "documents": list(self.documents.values()),
            "nodes": [
                node.to_dict()
                for node in sorted(
                    self.nodes.values(),
                    key=lambda item: (item.mode, item.scope_id, item.order),
                )
            ],
            "target_states": dict(self.target_states),
        }


class CourseNavigator:
    """Persist graph location and vertical return history atomically."""

    def __init__(self, root: Path | str) -> None:
        self.store = KnowledgeStore(root)

    def state(self) -> dict[str, object]:
        state = self._load()
        return self._payload(state)

    def open(self, course_id: str, section_id: str = "") -> dict[str, object]:
        graph = CourseGraph.from_store(self.store)
        if graph.target_state(course_id) != "ready":
            raise CodeLearnerError(
                f"course target {course_id} is {graph.target_state(course_id)}"
            )
        node = graph.node(section_id) if section_id else graph.first_section(course_id)
        if node.course_id != course_id:
            raise CodeLearnerError("section does not belong to requested course")
        state = self._load()
        state.update(
            {
                "current_course_id": course_id,
                "current_section_id": node.id,
                "history": [],
            }
        )
        self._sync_source(state, node)
        self._save(state)
        return self._payload(state, graph)

    def move(self, direction: str) -> dict[str, object]:
        graph = CourseGraph.from_store(self.store)
        state = self._load()
        current = graph.node(str(state.get("current_section_id") or ""))
        target_id = current.previous_id if direction == "previous" else current.next_id
        if direction not in {"previous", "next"}:
            raise CodeLearnerError("navigation direction must be previous or next")
        if not target_id:
            return self._payload(state, graph)
        target = graph.node(target_id)
        if target.course_id != current.course_id:
            raise CodeLearnerError("horizontal navigation cannot cross course layers")
        state["current_section_id"] = target.id
        self._sync_source(state, target)
        self._save(state)
        return self._payload(state, graph)

    def deep_dive(self, target_course_id: str) -> dict[str, object]:
        graph = CourseGraph.from_store(self.store)
        state = self._load()
        current = graph.node(str(state.get("current_section_id") or ""))
        if target_course_id not in current.deep_dive_ids:
            raise CodeLearnerError("deep-dive target is not linked from this section")
        target_state = graph.target_state(target_course_id)
        if target_state != "ready":
            state["target"] = {
                "id": target_course_id,
                "status": target_state,
            }
            self._save(state)
            return self._payload(state, graph)
        target = graph.first_section(target_course_id)
        history = state.setdefault("history", [])
        if not isinstance(history, list):
            raise CodeLearnerError("navigation history must be an array")
        history.append(
            {
                "course_id": current.course_id,
                "section_id": current.id,
                "code_view": state.get("code_view", {}),
            }
        )
        state.update(
            {
                "current_course_id": target.course_id,
                "current_section_id": target.id,
                "target": {},
            }
        )
        self._sync_source(state, target)
        self._save(state)
        return self._payload(state, graph)

    def back(self) -> dict[str, object]:
        graph = CourseGraph.from_store(self.store)
        state = self._load()
        history = state.get("history", [])
        if not isinstance(history, list) or not history:
            return self._payload(state, graph)
        previous = history.pop()
        state.update(
            {
                "current_course_id": previous["course_id"],
                "current_section_id": previous["section_id"],
                "code_view": previous.get("code_view", {}),
                "target": {},
            }
        )
        self._save(state)
        return self._payload(state, graph)

    def update_code_view(self, code_view: Mapping[str, object]) -> dict[str, object]:
        state = self._load()
        state["code_view"] = dict(code_view)
        self._save(state)
        return self._payload(state)

    def _load(self) -> dict[str, object]:
        if not self.store.navigation_path.is_file():
            return {
                "schema_version": 1,
                "version": 0,
                "current_course_id": "",
                "current_section_id": "",
                "history": [],
                "code_view": {},
                "target": {},
            }
        try:
            state = json.loads(self.store.navigation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(
                f"could not load course navigation: {error}"
            ) from error
        if not isinstance(state, dict):
            raise CodeLearnerError("course navigation must be an object")
        return state

    def _save(self, state: dict[str, object]) -> None:
        state["schema_version"] = 1
        state["version"] = int(state.get("version") or 0) + 1
        state["updated_at"] = utc_now()
        path = self.store.navigation_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _sync_source(self, state: dict[str, object], node: CourseNode) -> None:
        if not node.source_ref:
            state["code_view"] = {}
            return
        current = state.get("code_view")
        current = current if isinstance(current, dict) else {}
        path = str(node.source_ref.get("path") or "")
        same_path = current.get("path") == path
        state["code_view"] = {
            "path": path,
            "selected_start_line": node.source_ref.get("start_line"),
            "selected_end_line": node.source_ref.get("end_line"),
            "visible_start_line": (
                current.get("visible_start_line") if same_path else None
            ),
            "visible_end_line": current.get("visible_end_line") if same_path else None,
        }

    def _payload(
        self,
        state: dict[str, object],
        graph: CourseGraph | None = None,
    ) -> dict[str, object]:
        graph = graph or CourseGraph.from_store(self.store)
        section_id = str(state.get("current_section_id") or "")
        node = graph.nodes.get(section_id)
        history = state.get("history", [])
        breadcrumbs = [
            {
                "course_id": item.get("course_id"),
                "section_id": item.get("section_id"),
            }
            for item in history
            if isinstance(item, dict)
        ]
        if node:
            breadcrumbs.append(
                {"course_id": node.course_id, "section_id": node.id}
            )
        return {
            "status": "ready" if node else "empty",
            "navigation": state,
            "current": node.to_dict() if node else None,
            "breadcrumbs": breadcrumbs,
            "graph": graph.to_dict(),
        }


def _target_key(mode: str, scope_id: str) -> str:
    if mode == "architecture":
        return "course.architecture.repository.root"
    return f"course.{mode}.{scope_id}"
