"""Phase 3 course construction, rendering, target state, and navigation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from electroboy.adapters.base import AgentInvocation, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role
from electroboy.structured_artifacts import RenderResult, render_artifact

from .architecture_knowledge import ArchitectureKnowledgeService
from .contracts import parse_jsonl, validate_course_records
from .domain import CodeLearnerError
from .function_knowledge import FunctionKnowledgeService
from .knowledge import Phase3KnowledgeContext
from .module_knowledge import ModuleKnowledgeService
from .phase3_store import Phase3Store
from .skills import skill_prompt_reference, validate_packaged_skill

COURSE_ROLE = "code_learner_course"
TARGET_STATES = frozenset(
    {"missing", "generating", "ready", "stale", "failed", "unresolved"}
)
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


class Phase3CourseService:
    """Build scoped courses from validated Phase 3 knowledge only."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Phase3Store | None = None,
        runtime_factory: RuntimeFactory | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.runtime_factory = runtime_factory or _runtime_factory
        self.max_attempts = max(1, max_attempts)
        self.index_path = self.store.courses_root / "index.json"
        self.navigation_path = self.store.courses_root / "navigation.json"

    def build(
        self,
        mode: str,
        scope_id: str,
        *,
        analysis_run_id: str,
        audience: str = "software engineer",
    ) -> dict[str, object]:
        validate_packaged_skill("code-learner-course")
        context = Phase3KnowledgeContext(self.root, store=self.store)
        knowledge_path, knowledge = self._knowledge(mode, scope_id)
        self.record_status(mode, scope_id, "generating")
        runtime = self.runtime_factory(COURSE_ROLE, self.root)
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            prompt = self._prompt(
                mode,
                scope_id,
                analysis_run_id=analysis_run_id,
                audience=audience,
                knowledge_path=knowledge_path,
                revision=context.revision,
            )
            if last_error:
                prompt += f"\n\nPrevious course output error:\n- {last_error}"
            result = runtime.invoke(
                AgentInvocation(
                    role=COURSE_ROLE,
                    prompt=prompt,
                    context_paths=self._context_paths(context, knowledge_path),
                )
            )
            self.store.write_json(
                self.store.attempts_root
                / "courses"
                / f"{mode}-{_safe(scope_id)}-{attempt}.json",
                {
                    "mode": mode,
                    "scope_id": scope_id,
                    "attempt": attempt,
                    "output": result.final_message,
                    "error": result.error or "",
                    "recorded_at": utc_now(),
                },
            )
            if not result.ok:
                last_error = result.error or "course runtime failed"
                continue
            try:
                records = parse_jsonl(result.final_message, artifact="Phase 3 course")
                path, rendered = self.save(mode, scope_id, records)
                return {
                    "mode": mode,
                    "scope_id": scope_id,
                    "document_id": _document_id(mode, scope_id),
                    "jsonl_path": path.relative_to(self.root).as_posix(),
                    "markdown_path": rendered.markdown_path,
                    "record_count": len(records),
                    "knowledge_id": knowledge["id"],
                }
            except CodeLearnerError as error:
                last_error = str(error)
        message = f"{mode.title()} course failed: {last_error}"
        self.record_status(mode, scope_id, "failed", error=message)
        raise CodeLearnerError(message)

    def save(
        self,
        mode: str,
        scope_id: str,
        records: Sequence[Mapping[str, object]],
    ) -> tuple[Path, RenderResult]:
        context = Phase3KnowledgeContext(self.root, store=self.store)
        normalized = validate_course_records(
            records,
            knowledge_ids=self._known_knowledge_ids(context),
            root=self.root,
        )
        document = next(
            item for item in normalized if item.get("record_type") == "document"
        )
        if document.get("id") != _document_id(mode, scope_id):
            raise CodeLearnerError("course document ID does not match Phase 3 target")
        if document.get("course_mode") != mode or document.get("scope_id") != scope_id:
            raise CodeLearnerError("course document mode or scope is incorrect")
        if document.get("repository_revision") != context.revision:
            raise CodeLearnerError("course revision is stale")
        sections = sorted(
            (item for item in normalized if item.get("record_type") == "section"),
            key=lambda item: (int(item.get("order") or 0), str(item.get("id") or "")),
        )
        if not sections:
            raise CodeLearnerError("course requires at least one section")
        self._validate_sections(mode, scope_id, document, sections, context)
        path = self.course_path(mode, scope_id)
        self.store.write_jsonl(path, normalized)
        rendered = render_artifact(
            self.root,
            "course",
            jsonl_path=path.relative_to(self.root).as_posix(),
            markdown_path=self.markdown_path(mode, scope_id)
            .relative_to(self.root)
            .as_posix(),
        )
        self.record_status(
            mode,
            scope_id,
            "ready",
            path=path.relative_to(self.root).as_posix(),
        )
        return path, rendered

    def load(self, mode: str, scope_id: str) -> list[dict[str, object]]:
        path = self.course_path(mode, scope_id)
        if not path.is_file():
            return []
        context = Phase3KnowledgeContext(self.root, store=self.store)
        return validate_course_records(
            parse_jsonl(
                path.read_text(encoding="utf-8"),
                artifact=path.relative_to(self.root).as_posix(),
            ),
            knowledge_ids=self._known_knowledge_ids(context),
            root=self.root,
        )

    def course_path(self, mode: str, scope_id: str) -> Path:
        if mode == "architecture":
            return self.store.courses_root / "architecture.jsonl"
        if mode not in {"module", "function"}:
            raise CodeLearnerError(f"unknown course mode: {mode}")
        return self.store.courses_root / f"{mode}s" / f"{_safe(scope_id)}.jsonl"

    def markdown_path(self, mode: str, scope_id: str) -> Path:
        return self.course_path(mode, scope_id).with_suffix(".md")

    def index(self) -> dict[str, object]:
        return self.store.read_json(self.index_path) or {
            "schema_version": 1,
            "targets": {},
        }

    def record_status(
        self,
        mode: str,
        scope_id: str,
        status: str,
        *,
        path: str = "",
        error: str = "",
    ) -> None:
        if status not in TARGET_STATES:
            raise CodeLearnerError(f"unsupported course target status: {status}")
        index = self.index()
        targets = index.setdefault("targets", {})
        targets[_document_id(mode, scope_id)] = {
            "mode": mode,
            "scope_id": scope_id,
            "status": status,
            "path": path,
            "error": error,
            "updated_at": utc_now(),
        }
        self.store.write_json(self.index_path, index)

    def target_status(self, document_id: str) -> str:
        target = self.index().get("targets", {}).get(document_id, {})
        if isinstance(target, Mapping) and target.get("status") in TARGET_STATES:
            return str(target["status"])
        return "missing" if self._known_document_id(document_id) else "unresolved"

    def _validate_sections(
        self,
        mode: str,
        scope_id: str,
        document: Mapping[str, object],
        sections: Sequence[Mapping[str, object]],
        context: Phase3KnowledgeContext,
    ) -> None:
        section_ids = [str(item["id"]) for item in sections]
        if any(item.get("parent_id") != document.get("id") for item in sections):
            raise CodeLearnerError("course sections must belong to the scoped document")
        for index, section in enumerate(sections):
            expected_previous = section_ids[index - 1] if index else None
            expected_next = (
                section_ids[index + 1] if index + 1 < len(sections) else None
            )
            if section.get("previous_section_id") not in {None, "", expected_previous}:
                raise CodeLearnerError("Previous navigation leaves horizontal order")
            if section.get("next_section_id") not in {None, "", expected_next}:
                raise CodeLearnerError("Next navigation leaves horizontal order")
            section["previous_section_id"] = expected_previous
            section["next_section_id"] = expected_next
            for target in section.get("deep_dive_ids", []):
                if not self._known_document_id(str(target), context=context):
                    raise CodeLearnerError(
                        f"course has an unknown deep-dive target: {target}"
                    )
            for target in section.get("deep_dive_targets", []):
                if not isinstance(target, Mapping):
                    raise CodeLearnerError("deep_dive_targets must contain objects")
                target_type = str(target.get("target_type") or "")
                target_id = str(target.get("target_id") or "")
                catalogs = {
                    "architecture": {"architecture:current"},
                    "module": set(context.modules),
                    "component": set(context.components),
                    "function": set(context.symbols),
                }
                if target_id not in catalogs.get(target_type, set()):
                    raise CodeLearnerError("course has an unknown vertical target")
            for related in section.get("related_module_ids", []):
                if related not in context.modules:
                    raise CodeLearnerError("course has an unknown related module")
            for related in section.get("related_symbol_ids", []):
                if related not in context.symbols:
                    raise CodeLearnerError("course has an unknown related symbol")
        expected_detail = mode
        if any(item.get("detail_level") != expected_detail for item in sections):
            raise CodeLearnerError("course section detail level does not match mode")

    def _knowledge(self, mode: str, scope_id: str) -> tuple[Path, dict[str, object]]:
        if mode == "architecture":
            service = ArchitectureKnowledgeService(self.root, store=self.store)
            path, value = service.path, service.load()
        elif mode == "module":
            service = ModuleKnowledgeService(self.root, store=self.store)
            path, value = service._path(scope_id), service.load(scope_id)
        elif mode == "function":
            service = FunctionKnowledgeService(self.root, store=self.store)
            resolution = service.resolve(scope_id)
            if resolution.symbol is None or resolution.status == "ambiguous":
                raise CodeLearnerError("Function course target is unresolved")
            canonical = str(resolution.symbol["canonical_key"])
            path, value = (
                service._path(service._context().revision, canonical),
                service.load(canonical),
            )
        else:
            raise CodeLearnerError(f"unknown course mode: {mode}")
        if value is None:
            raise CodeLearnerError(f"{mode.title()} knowledge is missing: {scope_id}")
        return path, value

    def _known_knowledge_ids(self, context: Phase3KnowledgeContext) -> set[str]:
        ids = (
            set(context.modules)
            | set(context.components)
            | set(context.symbols)
            | set(context.relationships)
        )
        architecture = ArchitectureKnowledgeService(self.root, store=self.store).load()
        if architecture:
            ids.add(str(architecture["id"]))
        module_service = ModuleKnowledgeService(self.root, store=self.store)
        for module_id in context.modules:
            value = module_service.load(module_id)
            if value:
                ids.add(str(value["id"]))
        function_service = FunctionKnowledgeService(self.root, store=self.store)
        for symbol_id in context.symbols:
            value = function_service.load(symbol_id)
            if value:
                ids.add(str(value["id"]))
        return ids

    def _known_document_id(
        self,
        document_id: str,
        *,
        context: Phase3KnowledgeContext | None = None,
    ) -> bool:
        context = context or Phase3KnowledgeContext(self.root, store=self.store)
        known = {_document_id("architecture", "architecture:current")}
        known.update(_document_id("module", item) for item in context.modules)
        known.update(_document_id("function", item) for item in context.symbols)
        return document_id in known

    def _prompt(
        self,
        mode: str,
        scope_id: str,
        *,
        analysis_run_id: str,
        audience: str,
        knowledge_path: Path,
        revision: str,
    ) -> str:
        context = Phase3KnowledgeContext(self.root, store=self.store)
        return f"""You are building one ElectroBoy Phase 3 {mode.title()} course.

{skill_prompt_reference("code-learner-course")}

Repository root: {self.root}
Analysis run ID: {analysis_run_id}
Repository revision: {revision}
Course mode: {mode}
Course scope ID: {scope_id}
Required document ID: {_document_id(mode, scope_id)}
Audience: {audience}
Course schema: {Path(__file__).with_name("schemas") / "course.schema.json"}
Source manifest: {context.source_service.manifest_path}
Component manifest: {context.component_service.manifest_path}
Module manifest: {context.module_service.manifest_path}
Relationships: {context.relationship_service.relationships_path}
Scoped layered knowledge: {knowledge_path}

Return one document followed by ordered slide-sized section records as strict
JSONL. Use Markdown and fenced Mermaid in section bodies. Previous/Next stay in
this {mode} course. Deep-dive targets use known Phase 3 course document IDs;
record component targets in deep_dive_targets. Preserve source links,
uncertainty, and return targets. Do not restart discovery, reconciliation,
module synthesis, relationship generation, or knowledge generation.
""".strip()

    def _context_paths(
        self, context: Phase3KnowledgeContext, knowledge_path: Path
    ) -> list[str]:
        return [
            path.relative_to(self.root).as_posix()
            for path in (
                context.source_service.manifest_path,
                context.component_service.manifest_path,
                context.component_service.components_path,
                context.module_service.manifest_path,
                context.module_service.modules_path,
                context.relationship_service.relationships_path,
                knowledge_path,
            )
            if path.exists()
        ]


class Phase3CourseNavigator:
    """Persist horizontal and vertical course position with source selection."""

    def __init__(self, root: Path | str, *, service: Phase3CourseService | None = None):
        self.service = service or Phase3CourseService(root)
        self.root = self.service.root
        self.store = self.service.store

    def open(self, mode: str, scope_id: str) -> dict[str, object]:
        records = self.service.load(mode, scope_id)
        if not records:
            raise CodeLearnerError("course target is missing")
        section = _sections(records)[0]
        state = {
            "schema_version": 1,
            "current": {
                "mode": mode,
                "scope_id": scope_id,
                "document_id": _document_id(mode, scope_id),
                "section_id": section["id"],
            },
            "history": [],
            "code_view": _code_view(section),
            "target": {},
            "updated_at": utc_now(),
        }
        self.store.write_json(self.service.navigation_path, state)
        return self.state()

    def move(self, direction: str) -> dict[str, object]:
        if direction not in {"previous", "next"}:
            raise CodeLearnerError("navigation direction must be previous or next")
        state = self._load()
        records, current = self._current(state)
        target_id = current.get(f"{direction}_section_id")
        if not target_id:
            return self.state()
        target = next(item for item in _sections(records) if item["id"] == target_id)
        state["current"]["section_id"] = target["id"]
        state["code_view"] = _code_view(target)
        state["updated_at"] = utc_now()
        self.store.write_json(self.service.navigation_path, state)
        return self.state()

    def deep_dive(self, document_id: str) -> dict[str, object]:
        state = self._load()
        _, current = self._current(state)
        if document_id not in current.get("deep_dive_ids", []):
            raise CodeLearnerError("deep-dive target is not linked from this section")
        status = self.service.target_status(document_id)
        if status != "ready":
            state["target"] = {"id": document_id, "status": status}
            self.store.write_json(self.service.navigation_path, state)
            return self.state()
        target = self.service.index()["targets"][document_id]
        records = self.service.load(str(target["mode"]), str(target["scope_id"]))
        section = _sections(records)[0]
        state["history"].append(
            {"current": dict(state["current"]), "code_view": state["code_view"]}
        )
        state["current"] = {
            "mode": target["mode"],
            "scope_id": target["scope_id"],
            "document_id": document_id,
            "section_id": section["id"],
        }
        state["code_view"] = _code_view(section)
        state["target"] = {}
        self.store.write_json(self.service.navigation_path, state)
        return self.state()

    def back(self) -> dict[str, object]:
        state = self._load()
        if not state["history"]:
            return self.state()
        previous = state["history"].pop()
        state["current"] = previous["current"]
        state["code_view"] = previous["code_view"]
        state["target"] = {}
        self.store.write_json(self.service.navigation_path, state)
        return self.state()

    def state(self) -> dict[str, object]:
        state = self._load()
        _, section = self._current(state)
        return {**state, "section": section}

    def _load(self) -> dict[str, object]:
        state = self.store.read_json(self.service.navigation_path)
        if state is None:
            raise CodeLearnerError("course navigation is not initialized")
        return state

    def _current(self, state: Mapping[str, object]):
        current = state.get("current", {})
        records = self.service.load(str(current["mode"]), str(current["scope_id"]))
        section = next(
            item for item in _sections(records) if item["id"] == current["section_id"]
        )
        return records, section


def _sections(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return sorted(
        (dict(item) for item in records if item.get("record_type") == "section"),
        key=lambda item: (int(item.get("order") or 0), str(item["id"])),
    )


def _code_view(section: Mapping[str, object]) -> dict[str, object]:
    references = section.get("source_refs", [])
    reference = references[0] if references else {}
    return {
        "path": reference.get("path", ""),
        "start_line": reference.get("start_line", 1),
        "end_line": reference.get("end_line", 1),
    }


def _document_id(mode: str, scope_id: str) -> str:
    return f"course:{mode}:{scope_id}"


def _safe(value: str) -> str:
    return _SAFE.sub("-", value).strip(".-")


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
