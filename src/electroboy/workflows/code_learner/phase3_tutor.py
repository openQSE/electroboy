"""Compact file-backed tutor context for Phase 3 course navigation."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from electroboy.models import utc_now

from .domain import CodeLearnerError
from .knowledge import Phase3KnowledgeContext
from .phase3_courses import Phase3CourseService
from .phase3_store import Phase3Store
from .source_manifest import SourceManifestService

PHASE3_TUTOR_CONTEXT_SCHEMA_VERSION = 2
CONTEXT_STATES = frozenset({"ready", "missing", "stale", "malformed", "incompatible"})


class Phase3TutorContextStore:
    """Atomically track the learner's current canonical Phase 3 location."""

    def __init__(self, root: Path | str, *, store: Phase3Store | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.path = self.store.tutor_context_path
        self.lock_path = self.path.with_suffix(".lock")

    def write_navigation(
        self,
        navigation: Mapping[str, object],
        *,
        project_id: str,
        writer_id: str,
    ) -> dict[str, object]:
        context = Phase3KnowledgeContext(self.root, store=self.store)
        current = _mapping(navigation.get("current"), "navigation.current")
        section = _mapping(navigation.get("section"), "navigation.section")
        history = navigation.get("history", [])
        if not isinstance(history, list):
            raise CodeLearnerError("navigation history must be an array")
        mode = _required(current.get("mode"), "course mode")
        scope_id = _required(current.get("scope_id"), "course scope")
        document_id = _required(current.get("document_id"), "course document")
        section_id = _required(current.get("section_id"), "course section")
        records = Phase3CourseService(self.root, store=self.store).load(mode, scope_id)
        sections = sorted(
            (item for item in records if item.get("record_type") == "section"),
            key=lambda item: (int(item.get("order") or 0), str(item.get("id") or "")),
        )
        if not any(item.get("id") == section_id for item in sections):
            raise CodeLearnerError("current Phase 3 course section is not persisted")
        module_ids = set(section.get("related_module_ids", []))
        if mode == "module":
            module_ids.add(scope_id)
        component_ids = {
            str(item)
            for item in section.get("knowledge_entity_ids", [])
            if item in context.components
        }
        for target in section.get("deep_dive_targets", []):
            if isinstance(target, Mapping) and target.get("target_type") == "component":
                component_ids.add(str(target.get("target_id") or ""))
        symbol_ids = set(section.get("related_symbol_ids", []))
        if mode == "function":
            symbol_ids.add(scope_id)
        source = self._source(navigation.get("code_view"), context)
        course_path = Phase3CourseService(self.root, store=self.store).course_path(
            mode, scope_id
        )
        payload = {
            "schema_version": PHASE3_TUTOR_CONTEXT_SCHEMA_VERSION,
            "project_id": _required(project_id, "project ID"),
            "repository_revision": context.revision,
            "context_status": "ready",
            "stale": False,
            "course": {
                "document_id": document_id,
                "mode": mode,
                "scope_id": scope_id,
                "section_id": section_id,
                "horizontal_index": next(
                    index
                    for index, item in enumerate(sections)
                    if item.get("id") == section_id
                ),
                "vertical_path": [
                    str(item.get("current", {}).get("document_id") or "")
                    for item in history
                    if isinstance(item, Mapping)
                    and isinstance(item.get("current"), Mapping)
                ]
                + [document_id],
            },
            "selection": {
                "module_ids": sorted(module_ids),
                "component_ids": sorted(component_ids),
                "symbol_locators": [
                    dict(context.symbols[item])
                    for item in sorted(symbol_ids)
                    if item in context.symbols
                ],
                "relationship_ids": list(section.get("relationship_ids", [])),
            },
            "source": source,
            "navigation": {
                "can_go_back": bool(history),
                "target": dict(navigation.get("target", {})),
            },
            "artifacts": {
                "course": course_path.relative_to(self.root).as_posix(),
                "source_manifest": context.source_service.manifest_path.relative_to(
                    self.root
                ).as_posix(),
                "component_manifest": (
                    context.component_service.manifest_path.relative_to(
                        self.root
                    ).as_posix()
                ),
                "module_manifest": context.module_service.manifest_path.relative_to(
                    self.root
                ).as_posix(),
                "relationships": (
                    context.relationship_service.relationships_path.relative_to(
                        self.root
                    ).as_posix()
                ),
                "knowledge_root": self.store.knowledge_root.relative_to(
                    self.root
                ).as_posix(),
            },
            "writer_id": _required(writer_id, "writer ID"),
        }
        return self._write(payload)

    def load(self, *, required: bool = True) -> dict[str, object] | None:
        result = self.load_state()
        if result["status"] == "ready":
            return dict(result["context"])
        if required:
            raise CodeLearnerError(
                f"Phase 3 tutor context is {result['status']}: {result['message']}"
            )
        return None

    def load_state(self) -> dict[str, object]:
        if not self.path.is_file():
            return _state("missing", "context file does not exist")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return _state("malformed", str(error))
        if not isinstance(value, Mapping):
            return _state("malformed", "context root is not an object")
        try:
            self._validate(value)
        except CodeLearnerError as error:
            return _state("incompatible", str(error), context=value)
        try:
            source = SourceManifestService(self.root).load()
            if source is None:
                raise CodeLearnerError("source manifest is missing")
            revision = source.revision
        except CodeLearnerError as error:
            return _state("incompatible", str(error), context=value)
        if value.get("stale") is True or value.get("repository_revision") != revision:
            return _state(
                "stale", "repository or course context changed", context=value
            )
        return _state("ready", "context is current", context=value)

    def _write(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._lock():
            current = self.load_state()
            previous = current.get("context")
            previous = previous if isinstance(previous, Mapping) else {}
            context = {
                **dict(payload),
                "context_version": int(previous.get("context_version") or 0) + 1,
                "updated_at": utc_now(),
            }
            self._validate(context)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps(context, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return context

    def _validate(self, value: Mapping[str, object]) -> None:
        if value.get("schema_version") != PHASE3_TUTOR_CONTEXT_SCHEMA_VERSION:
            raise CodeLearnerError("schema_version must be 2")
        if int(value.get("context_version") or 0) < 1:
            raise CodeLearnerError("context_version must be positive")
        for field in ("project_id", "repository_revision", "writer_id", "updated_at"):
            _required(value.get(field), field)
        if value.get("context_status") not in {"ready", "stale"}:
            raise CodeLearnerError("context_status is unsupported")
        for field in ("course", "selection", "navigation", "artifacts"):
            _mapping(value.get(field), field)
        course = value["course"]
        for field in ("document_id", "mode", "scope_id", "section_id"):
            _required(course.get(field), f"course.{field}")
        selection = value["selection"]
        for field in (
            "module_ids",
            "component_ids",
            "symbol_locators",
            "relationship_ids",
        ):
            if not isinstance(selection.get(field), list):
                raise CodeLearnerError(f"selection.{field} must be an array")
        source = value.get("source")
        if source is not None:
            source = _mapping(source, "source")
            path = Path(str(source.get("path") or ""))
            if path.is_absolute() or ".." in path.parts:
                raise CodeLearnerError("source path must be repository-relative")
            start = int(source.get("start_line") or 0)
            end = int(source.get("end_line") or 0)
            if start < 1 or end < start:
                raise CodeLearnerError("source line range is invalid")
        for field, path in value["artifacts"].items():
            if not isinstance(path, str) or not path:
                raise CodeLearnerError(f"artifacts.{field} is invalid")
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts:
                raise CodeLearnerError(f"artifacts.{field} escapes repository")

    def _source(
        self, value: object, context: Phase3KnowledgeContext
    ) -> dict[str, object] | None:
        if not isinstance(value, Mapping) or not value.get("path"):
            return None
        path = str(value["path"])
        file = next(
            (item for item in context.files.values() if item.get("path") == path),
            None,
        )
        if file is None:
            raise CodeLearnerError("selected source is outside the source manifest")
        start = int(value.get("start_line") or value.get("selected_start_line") or 1)
        end = int(value.get("end_line") or value.get("selected_end_line") or start)
        return {
            "file_id": file["id"],
            "path": path,
            "start_line": start,
            "end_line": end,
        }

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CodeLearnerError(f"{field} must be an object")
    return value


def _required(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CodeLearnerError(f"{field} is required")
    return normalized


def _state(
    status: str,
    message: str,
    *,
    context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {"status": status, "message": message, "context": dict(context or {})}
