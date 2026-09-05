"""Compact file-backed context for the Code Learner tutor."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from electroboy.models import utc_now

from .contracts import ContractError, validate_tutor_context
from .domain import (
    CodeLearnerError,
    CodeLearnerStore,
    Walkthrough,
    build_learner_context,
    repository_revision,
)
from .knowledge_store import KnowledgeStore

TUTOR_CONTEXT_RELATIVE_PATH = ".electroboy/code-learner/tutor-context.json"
PHASE3_TUTOR_CONTEXT_RELATIVE_PATH = (
    ".electroboy/code-learner/phase3/tutor-context.json"
)
TUTOR_CONTEXT_SCHEMA_VERSION = 1


class TutorContextStore:
    """Validate and atomically version the tutor's current course pointer."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = KnowledgeStore(self.root)
        self.path = self.store.tutor_context_path
        self.lock_path = self.path.with_suffix(".lock")

    def load(self, *, required: bool = True) -> dict[str, object] | None:
        """Load a valid context or fail instead of returning guessed state."""

        if not self.path.is_file():
            if required:
                raise CodeLearnerError(
                    f"tutor context is missing: {TUTOR_CONTEXT_RELATIVE_PATH}"
                )
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(f"tutor context is unreadable: {error}") from error
        if not isinstance(value, dict):
            raise CodeLearnerError("tutor context must be a JSON object")
        try:
            return validate_tutor_context(value, root=self.root)
        except ContractError as error:
            raise CodeLearnerError(f"tutor context is incompatible: {error}") from error

    def write_navigation(
        self,
        navigation: Mapping[str, object],
        *,
        project_id: str,
        writer_id: str,
    ) -> dict[str, object]:
        """Project durable layered-course navigation into the tutor context."""

        current = _mapping(navigation.get("current"), "navigation.current")
        state = _mapping(navigation.get("navigation"), "navigation.navigation")
        mode = str(current.get("mode") or "")
        scope_id = str(current.get("scope_id") or "")
        course_id = str(current.get("course_id") or "")
        section_id = str(current.get("id") or "")
        records = self.store.load_course(mode, scope_id, validate_sources=False)
        document = next(
            (item for item in records if item.get("record_type") == "document"),
            None,
        )
        section = next(
            (
                item
                for item in records
                if item.get("record_type") == "section" and item.get("id") == section_id
            ),
            None,
        )
        if document is None or section is None:
            raise CodeLearnerError("current course section is not persisted")
        sections = sorted(
            (item for item in records if item.get("record_type") == "section"),
            key=lambda item: (int(item.get("order") or 0), str(item.get("id") or "")),
        )
        horizontal_index = next(
            index for index, item in enumerate(sections) if item.get("id") == section_id
        )
        history = state.get("history", [])
        vertical_path = [
            str(item.get("course_id") or "")
            for item in (history if isinstance(history, list) else [])
            if isinstance(item, dict) and item.get("course_id")
        ]
        vertical_path.append(course_id)
        current_revision = repository_revision(self.root)
        linked_ids = {
            str(item)
            for field in (
                "knowledge_entity_ids",
                "relationship_ids",
                "runtime_flow_ids",
            )
            for item in section.get(field, [])
        }
        freshness = self.store.freshness()
        stale_ids = set(freshness.get("stale_ids", []))
        payload = {
            "schema_version": TUTOR_CONTEXT_SCHEMA_VERSION,
            "project_id": _required_text(project_id, "project ID"),
            "repository_revision": current_revision,
            "stale": (
                document.get("status") == "stale"
                or document.get("repository_revision") != current_revision
                or bool(linked_ids & stale_ids)
            ),
            "course": {
                "document_id": course_id,
                "mode": mode,
                "scope_id": scope_id,
                "section_id": section_id,
                "horizontal_index": horizontal_index,
                "vertical_path": vertical_path,
            },
            "selection": {
                "module_id": _module_id(mode, scope_id, section),
                "symbol_id": _symbol_id(mode, scope_id, section),
                "knowledge_entity_ids": list(section.get("knowledge_entity_ids", [])),
                "relationship_ids": list(section.get("relationship_ids", [])),
                "runtime_flow_ids": list(section.get("runtime_flow_ids", [])),
            },
            "source": _source_from_code_view(state.get("code_view")),
            "artifacts": {
                "course": self.store.course_path(mode, scope_id)
                .relative_to(self.root)
                .as_posix(),
                "knowledge_root": self.store.knowledge_root.relative_to(
                    self.root
                ).as_posix(),
            },
            "writer_id": _required_text(writer_id, "writer ID"),
        }
        return self._write(payload)

    def write_walkthrough(
        self,
        walkthrough: Walkthrough,
        *,
        project_id: str,
        writer_id: str,
        context_options: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Project a v1 walkthrough without persisting its source excerpt."""

        context = build_learner_context(
            self.root,
            walkthrough,
            **dict(context_options or {}),
        )
        step = walkthrough.current_step()
        if step is None:
            raise CodeLearnerError("walkthrough has no current step")
        source_status = context.get("source_status")
        source_ok = isinstance(source_status, dict) and source_status.get("ok") is True
        mode = walkthrough.learning_mode
        scope_id = walkthrough.mode_target or "repository.root"
        revision = repository_revision(self.root)
        known_ids = (
            self.store.knowledge_ids() if self.store.knowledge_root.exists() else set()
        )
        selected_id = scope_id if scope_id in known_ids else None
        payload = {
            "schema_version": TUTOR_CONTEXT_SCHEMA_VERSION,
            "project_id": _required_text(project_id, "project ID"),
            "repository_revision": revision,
            "stale": not source_ok or walkthrough.source_revision != revision,
            "course": {
                "document_id": walkthrough.id,
                "mode": mode,
                "scope_id": scope_id,
                "section_id": step.id,
                "horizontal_index": next(
                    index
                    for index, candidate in enumerate(walkthrough.steps)
                    if candidate.id == step.id
                ),
                "vertical_path": [walkthrough.id],
            },
            "selection": {
                "module_id": selected_id if mode == "module" else None,
                "symbol_id": selected_id if mode == "function" else None,
                "knowledge_entity_ids": [selected_id] if selected_id else [],
                "relationship_ids": [],
                "runtime_flow_ids": [],
            },
            "source": (
                {
                    "path": str(context["file_path"]),
                    "start_line": int(context["start_line"]),
                    "end_line": int(context["end_line"]),
                }
                if source_ok
                else None
            ),
            "artifacts": {
                "course": CodeLearnerStore(self.root)
                .corpus_path.relative_to(self.root)
                .as_posix(),
                "knowledge_root": self.store.knowledge_root.relative_to(
                    self.root
                ).as_posix(),
            },
            "writer_id": _required_text(writer_id, "writer ID"),
        }
        return self._write(payload)

    def _write(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._exclusive_lock():
            current = self.load(required=False)
            context = {
                **dict(payload),
                "context_version": int((current or {}).get("context_version") or 0) + 1,
                "updated_at": utc_now(),
            }
            try:
                normalized = validate_tutor_context(context, root=self.root)
            except ContractError as error:
                raise CodeLearnerError(
                    f"invalid tutor context update: {error}"
                ) from error
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps(normalized, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return normalized

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def tutor_bootstrap_prompt(root: Path | str, *, generation: str = "phase2") -> str:
    """Return the fixed, one-time instruction for a repository tutor."""

    repository = Path(root).expanduser().resolve()
    context_path = (
        PHASE3_TUTOR_CONTEXT_RELATIVE_PATH
        if generation == "phase3"
        else TUTOR_CONTEXT_RELATIVE_PATH
    )
    schema_version = 2 if generation == "phase3" else 1
    return "\n".join(
        (
            "You are the ElectroBoy Code Learner tutor for this repository.",
            "",
            "Stay in teaching mode. Explain code; do not modify files or run",
            "implementation commands unless the operator explicitly changes the task.",
            "",
            f"Repository root: {repository}",
            f"Tutor context: {context_path}",
            "",
            "Before answering every learner question, read the tutor context file.",
            f"Require schema_version {schema_version}, then treat the current",
            "context_version as",
            "authoritative, and do not substitute a location remembered from chat.",
            "If the file is missing, unreadable, incompatible, or stale, say so",
            "instead of guessing the learner's location.",
            "",
            "Read only the referenced current course section, directly referenced",
            "knowledge records and neighborhood, and source range needed to answer.",
            "Expand repository inspection only when those references are insufficient.",
            "Re-read context_version after loading evidence; if it changed, discard",
            "that evidence and retry once against the new context before answering.",
            "",
            "Ordinary questions must not mutate course, knowledge, source, or context",
            "files. You may propose durable follow-up analysis as a JSON object inside",
            "<code-learner-enrichment-request> tags, but do not apply it yourself.",
        )
    )


def require_repository_read_capability(command: list[str], root: Path | str) -> None:
    """Reject tutor runtimes that cannot read the attached repository."""

    repository = Path(root).expanduser().resolve()
    if not command or Path(command[0]).name != "codex":
        raise CodeLearnerError("tutor runtime does not declare repository reads")
    try:
        command_root = Path(command[command.index("--cd") + 1]).expanduser().resolve()
        sandbox = command[command.index("--sandbox") + 1]
    except (ValueError, IndexError) as error:
        raise CodeLearnerError(
            "tutor runtime is missing repository-scoped read capability"
        ) from error
    if command_root != repository or sandbox not in {
        "read-only",
        "workspace-write",
        "danger-full-access",
    }:
        raise CodeLearnerError(
            "tutor runtime cannot read the attached repository context"
        )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CodeLearnerError(f"{field} must be an object")
    return value


def _required_text(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CodeLearnerError(f"{field} is required")
    return normalized


def _module_id(mode: str, scope_id: str, section: Mapping[str, object]) -> str | None:
    if mode == "module":
        return scope_id
    related = section.get("related_module_ids", [])
    return str(related[0]) if isinstance(related, list) and related else None


def _symbol_id(mode: str, scope_id: str, section: Mapping[str, object]) -> str | None:
    if mode == "function":
        return scope_id
    related = section.get("related_symbol_ids", [])
    return str(related[0]) if isinstance(related, list) and related else None


def _source_from_code_view(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping) or not value.get("path"):
        return None
    start = value.get("selected_start_line") or value.get("visible_start_line")
    end = value.get("selected_end_line") or value.get("visible_end_line") or start
    if start is None:
        return None
    return {
        "path": str(value["path"]),
        "start_line": int(start),
        "end_line": int(end),
    }
