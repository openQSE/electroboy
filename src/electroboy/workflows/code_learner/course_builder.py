"""Evidence selection and AI orchestration for layered Code Learner courses."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Protocol
from uuid import uuid4

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .contracts import parse_jsonl, validate_course_records
from .course_artifacts import render_saved_course
from .domain import CodeLearnerError
from .knowledge_store import KnowledgeStore
from .knowledge_validation import EnrichmentController
from .progress import AgentActivityReporter, InvocationHeartbeat
from .skills import skill_prompt_reference, validate_packaged_skill

COURSE_ROLE = "code_learner_course"
ProgressCallback = Callable[[dict[str, object]], None]


@dataclass(frozen=True)
class CourseScope:
    """Selected evidence and identity for one course invocation."""

    mode: str
    scope_id: str
    records: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class CourseBuildResult:
    """Persisted result of one validated course build."""

    mode: str
    scope_id: str
    jsonl_path: str
    markdown_path: str
    record_count: int


@dataclass(frozen=True)
class CourseBatchResult:
    """Independent results from building a catalog of module courses."""

    completed: tuple[CourseBuildResult, ...]
    failed: Mapping[str, str]


@dataclass(frozen=True)
class FunctionResolution:
    """Resolution of user-entered text against durable symbol entities."""

    status: str
    symbol: Mapping[str, object] | None = None
    candidates: tuple[Mapping[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "symbol": dict(self.symbol) if self.symbol else None,
            "candidates": [dict(item) for item in self.candidates],
        }


class CourseEnrichmentRequired(CodeLearnerError):
    """Signal that a course pass emitted targeted knowledge requests."""

    def __init__(self, request_ids: list[str]) -> None:
        self.request_ids = tuple(request_ids)
        super().__init__("course generation requested targeted knowledge enrichment")


class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


class KnowledgeSubgraphSelector:
    """Select bounded course evidence independently from AI prompting."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def architecture(self) -> CourseScope:
        records = self.store.load_knowledge()
        if not records:
            raise CodeLearnerError("Code Learner knowledge has not been initialized")
        selected = [
            record
            for record in records
            if record.get("record_type")
            in {
                "knowledge_manifest",
                "entity",
                "relationship",
                "runtime_flow",
                "diagnostic",
            }
            and record.get("status") != "deprecated"
        ]
        return CourseScope("architecture", "repository.root", tuple(selected))

    def module(self, module_id: str) -> CourseScope:
        records = self.store.load_knowledge()
        by_id = {str(record["id"]): record for record in records}
        module = by_id.get(module_id)
        if not module or module.get("record_type") != "entity" or module.get(
            "kind"
        ) != "module":
            raise CodeLearnerError(f"unknown module: {module_id}")
        selected_ids = {"knowledge.manifest", module_id}
        for record in records:
            if record.get("record_type") == "entity" and record.get(
                "parent_id"
            ) == module_id:
                selected_ids.add(str(record["id"]))
        direct_relationships = [
            record
            for record in records
            if record.get("record_type") == "relationship"
            and (
                record.get("from_id") in selected_ids
                or record.get("to_id") in selected_ids
            )
        ]
        for relationship in direct_relationships:
            selected_ids.update(
                {
                    str(relationship["id"]),
                    str(relationship["from_id"]),
                    str(relationship["to_id"]),
                }
            )
        attributes = module.get("attributes")
        family_id = (
            str(attributes.get("extension_family_id") or "")
            if isinstance(attributes, dict)
            else ""
        )
        if family_id and family_id in by_id:
            selected_ids.add(family_id)
            family_attributes = by_id[family_id].get("attributes")
            if isinstance(family_attributes, dict):
                selected_ids.update(
                    str(item)
                    for item in family_attributes.get("implementation_module_ids", [])
                )
        for record in records:
            if record.get("record_type") == "runtime_flow" and set(
                record.get("participant_ids", [])
            ) & selected_ids:
                selected_ids.add(str(record["id"]))
            if record.get("record_type") == "diagnostic":
                diagnostic_attributes = record.get("attributes")
                related = (
                    set(diagnostic_attributes.get("related_record_ids", []))
                    if isinstance(diagnostic_attributes, dict)
                    else set()
                )
                if related & selected_ids:
                    selected_ids.add(str(record["id"]))
        selected = [
            record
            for record in records
            if record.get("id") in selected_ids and record.get("status") != "deprecated"
        ]
        return CourseScope("module", module_id, tuple(selected))

    def module_ids(self) -> tuple[str, ...]:
        records = self.store.load_knowledge()
        manifest = next(
            record
            for record in records
            if record.get("record_type") == "knowledge_manifest"
        )
        attributes = manifest.get("attributes")
        catalog = (
            attributes.get("module_catalog")
            if isinstance(attributes, dict)
            else None
        )
        if isinstance(catalog, dict) and isinstance(
            catalog.get("major_module_ids"), list
        ):
            return tuple(str(item) for item in catalog["major_module_ids"])
        return tuple(
            str(record["id"])
            for record in records
            if record.get("record_type") == "entity"
            and record.get("kind") == "module"
        )

    def function(self, symbol_id: str) -> CourseScope:
        records = self.store.load_knowledge()
        by_id = {str(record["id"]): record for record in records}
        symbol = by_id.get(symbol_id)
        if not symbol or symbol.get("record_type") != "entity" or symbol.get(
            "kind"
        ) != "symbol":
            raise CodeLearnerError(f"unknown symbol: {symbol_id}")
        selected_ids = {"knowledge.manifest", symbol_id}
        owner_id = str(symbol.get("parent_id") or "")
        if owner_id:
            selected_ids.add(owner_id)
        for record in records:
            if record.get("record_type") == "relationship" and (
                record.get("from_id") in selected_ids
                or record.get("to_id") in selected_ids
            ):
                selected_ids.update(
                    {
                        str(record["id"]),
                        str(record["from_id"]),
                        str(record["to_id"]),
                    }
                )
        for record in records:
            if record.get("record_type") == "runtime_flow" and set(
                record.get("participant_ids", [])
            ) & selected_ids:
                selected_ids.add(str(record["id"]))
            if record.get("record_type") == "diagnostic":
                attributes = record.get("attributes")
                related = (
                    set(attributes.get("related_record_ids", []))
                    if isinstance(attributes, dict)
                    else set()
                )
                if related & selected_ids:
                    selected_ids.add(str(record["id"]))
        return CourseScope(
            "function",
            symbol_id,
            tuple(
                record
                for record in records
                if record.get("id") in selected_ids
                and record.get("status") != "deprecated"
            ),
        )


def course_prompt(
    root: Path,
    scope: CourseScope,
    *,
    input_path: Path,
    audience: str = "",
) -> str:
    """Build a focused explicit course-skill invocation."""

    schema = Path(__file__).with_name("schemas") / "course.schema.json"
    manifest = next(
        record
        for record in scope.records
        if record.get("record_type") == "knowledge_manifest"
    )
    return f"""{skill_prompt_reference("code-learner-course")}

Repository root: {root}
Course mode: {scope.mode}
Course scope ID: {scope.scope_id}
Intended audience: {audience or "software engineer new to this repository"}
Analysis run ID: {manifest.get("analysis_run_id")}
Repository revision: {manifest.get("repository_revision")}
Canonical course schema: {schema}
Validated knowledge subgraph: {input_path.relative_to(root).as_posix()}

Generate one evidence-grounded {scope.mode} course for the exact scope above.
Read the supplied subgraph as the factual boundary and inspect only source
references it names when clarification is required. Return strict JSONL only,
with one document followed by hierarchical sections. Do not wrap output in a
Markdown fence or add prose outside the JSONL records.

If required evidence is missing, return only knowledge_request records. Never
mix request records with document or section records.
""".strip()


class CourseBuilder:
    """Generate, validate, persist, and render one course scope."""

    def __init__(
        self,
        root: Path | str,
        *,
        runtime_factory: RuntimeFactory | None = None,
        enrichment_factory: Callable[[Path], EnrichmentController] | None = None,
        max_attempts: int = 2,
        retry_delay: float = 0.0,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = KnowledgeStore(self.root)
        self.selector = KnowledgeSubgraphSelector(self.store)
        self.runtime_factory = runtime_factory or _default_runtime_factory
        self.enrichment_factory = enrichment_factory or EnrichmentController
        self.max_attempts = max(1, max_attempts)
        self.retry_delay = max(0.0, retry_delay)

    def build_architecture(
        self,
        *,
        audience: str = "",
        progress_callback: ProgressCallback | None = None,
    ) -> CourseBuildResult:
        return self._build_scope(
            self.selector.architecture(),
            audience=audience,
            progress_callback=progress_callback,
        )

    def build_module(
        self,
        module_id: str,
        *,
        audience: str = "",
        progress_callback: ProgressCallback | None = None,
    ) -> CourseBuildResult:
        return self._build_scope(
            self.selector.module(module_id),
            audience=audience,
            progress_callback=progress_callback,
        )

    def build_all_modules(
        self,
        *,
        audience: str = "",
        progress_callback: ProgressCallback | None = None,
    ) -> CourseBatchResult:
        completed: list[CourseBuildResult] = []
        failed: dict[str, str] = {}
        for module_id in self.selector.module_ids():
            try:
                completed.append(
                    self.build_module(
                        module_id,
                        audience=audience,
                        progress_callback=progress_callback,
                    )
                )
            except CodeLearnerError as error:
                failed[module_id] = str(error)
        return CourseBatchResult(tuple(completed), failed)

    def resolve_function(self, query: str) -> FunctionResolution:
        requested = str(query or "").strip().lower()
        if not requested:
            return FunctionResolution("missing")
        symbols = [
            record
            for record in self.store.load_knowledge()
            if record.get("record_type") == "entity"
            and record.get("kind") == "symbol"
            and record.get("status") != "deprecated"
        ]
        id_matches = [
            symbol
            for symbol in symbols
            if str(symbol.get("id") or "").lower() == requested
        ]
        if len(id_matches) == 1:
            return FunctionResolution("exact", id_matches[0], tuple(id_matches))
        qualified = [
            symbol
            for symbol in symbols
            if str(_symbol_attribute(symbol, "qualified_name")).lower() == requested
        ]
        if len(qualified) == 1:
            return FunctionResolution("qualified", qualified[0], tuple(qualified))
        if len(qualified) > 1:
            return FunctionResolution("ambiguous", candidates=tuple(qualified[:20]))
        exact = [
            symbol
            for symbol in symbols
            if str(symbol.get("name") or "").lower() == requested
        ]
        if len(exact) == 1:
            return FunctionResolution("exact", exact[0], tuple(exact))
        if len(exact) > 1:
            return FunctionResolution("ambiguous", candidates=tuple(exact[:20]))
        partial = [
            symbol
            for symbol in symbols
            if requested in str(_symbol_attribute(symbol, "qualified_name")).lower()
            or requested in str(symbol.get("name") or "").lower()
        ]
        if len(partial) == 1:
            return FunctionResolution("partial", partial[0], tuple(partial))
        if partial:
            return FunctionResolution("ambiguous", candidates=tuple(partial[:20]))
        return FunctionResolution("missing")

    def build_function(
        self,
        query: str,
        *,
        audience: str = "",
        progress_callback: ProgressCallback | None = None,
    ) -> CourseBuildResult:
        resolution = self.resolve_function(query)
        if resolution.status == "missing":
            raise CodeLearnerError(f"function symbol was not found: {query}")
        if resolution.status == "ambiguous":
            names = ", ".join(
                str(_symbol_attribute(item, "qualified_name") or item.get("name"))
                for item in resolution.candidates
            )
            raise CodeLearnerError(f"function symbol is ambiguous: {query}: {names}")
        symbol = dict(resolution.symbol or {})
        symbol_id = str(symbol["id"])
        cached = self.store.load_course("function", symbol_id)
        if cached and cached[0].get("status") == "ready":
            manifest = self.store.get("knowledge.manifest")
            if cached[0].get("repository_revision") == manifest.get(
                "repository_revision"
            ):
                return CourseBuildResult(
                    mode="function",
                    scope_id=symbol_id,
                    jsonl_path=self.store.course_path(
                        "function", symbol_id
                    ).relative_to(self.root).as_posix(),
                    markdown_path=self.store.course_markdown_path(
                        "function", symbol_id
                    ).relative_to(self.root).as_posix(),
                    record_count=len(cached),
                )
        if _function_evidence_missing(symbol):
            request = self._function_request(symbol)
            self.store.merge_knowledge([request])
            self._progress(
                "function_analyzing",
                92,
                f"Enriching function evidence for {symbol_id}.",
                progress_callback,
            )
            self.enrichment_factory(self.root).run_request_ids(
                [str(request["id"])], progress_callback
            )
            symbol = self.store.get(symbol_id)
            if _function_evidence_missing(symbol):
                raise CodeLearnerError(
                    "function evidence remains incomplete after enrichment: "
                    f"{symbol_id}"
                )
        return self._build_scope(
            self.selector.function(symbol_id),
            audience=audience,
            progress_callback=progress_callback,
        )

    def _build_scope(
        self,
        scope: CourseScope,
        *,
        audience: str,
        progress_callback: ProgressCallback | None,
    ) -> CourseBuildResult:
        validate_packaged_skill("code-learner-course")
        input_path = self._write_scope(scope)
        runtime = self.runtime_factory(COURSE_ROLE, self.root)
        self.store.record_course_status(scope.mode, scope.scope_id, "generating")
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            self._progress(
                f"{scope.mode}_course",
                94,
                f"Generating {scope.mode.title()} course for {scope.scope_id} "
                f"({attempt}/{self.max_attempts}).",
                progress_callback,
            )
            activity_reporter = AgentActivityReporter(
                lambda event: self._emit_event(event, progress_callback),
                phase=f"{scope.mode}_course",
                percent=94,
                scope_ids=[scope.scope_id],
            )
            invocation = AgentInvocation(
                role=COURSE_ROLE,
                prompt=course_prompt(
                    self.root,
                    scope,
                    input_path=input_path,
                    audience=audience,
                ),
                context_paths=[input_path.relative_to(self.root).as_posix()],
                event_callback=activity_reporter,
            )
            with InvocationHeartbeat(
                lambda event: self._emit_event(event, progress_callback),
                {
                    "record_type": "progress",
                    "phase": f"{scope.mode}_course",
                    "percent": 94,
                    "message": (
                        f"Still generating {scope.mode.title()} course for "
                        f"{scope.scope_id}; waiting for structured output."
                    ),
                    "scope_ids": [scope.scope_id],
                },
            ):
                result = runtime.invoke(invocation)
            try:
                records = self._accept_course(scope, result)
            except CourseEnrichmentRequired as error:
                last_error = str(error)
                self.enrichment_factory(self.root).run_request_ids(
                    error.request_ids,
                    progress_callback,
                )
                scope = self._refresh_scope(scope)
                input_path = self._write_scope(scope)
                continue
            except (CodeLearnerError, ValueError) as error:
                last_error = str(error)
                if attempt < self.max_attempts and self.retry_delay:
                    sleep(self.retry_delay)
                continue
            jsonl_path = self.store.save_course(
                scope.mode, scope.scope_id, records
            )
            rendered = render_saved_course(
                self.root, scope.mode, scope.scope_id
            )
            self._progress(
                f"{scope.mode}_ready",
                98,
                f"{scope.mode.title()} course validated and rendered.",
                progress_callback,
            )
            self.store.record_course_status(
                scope.mode,
                scope.scope_id,
                "ready",
                path=jsonl_path.relative_to(self.root).as_posix(),
            )
            if scope.mode == "function":
                self._link_function_course(scope, records)
            return CourseBuildResult(
                mode=scope.mode,
                scope_id=scope.scope_id,
                jsonl_path=jsonl_path.relative_to(self.root).as_posix(),
                markdown_path=rendered.markdown_path,
                record_count=len(records),
            )
        message = (
            f"{scope.mode.title()} course generation failed after "
            f"{self.max_attempts} attempts: {last_error}"
        )
        self.store.record_course_status(
            scope.mode, scope.scope_id, "failed", error=message
        )
        raise CodeLearnerError(message)

    def _accept_course(
        self, scope: CourseScope, result: AgentResult
    ) -> list[dict[str, object]]:
        if not result.ok:
            raise CodeLearnerError(
                result.error or result.final_message or "course runtime failed"
            )
        records = parse_jsonl(result.final_message, artifact=f"{scope.mode} course")
        record_types = {record.get("record_type") for record in records}
        if record_types <= {"knowledge_request"}:
            self.store.merge_knowledge(records)
            raise CourseEnrichmentRequired(
                [str(record.get("id") or "") for record in records]
            )
        if not record_types <= {"document", "section"}:
            raise CodeLearnerError(
                "course output cannot mix course and knowledge-request records"
            )
        validated = validate_course_records(
            records,
            knowledge_ids=self.store.knowledge_ids(),
            root=self.root,
        )
        self._validate_identity(scope, validated)
        if scope.mode == "architecture":
            self._validate_architecture(scope, validated)
        elif scope.mode == "module":
            self._validate_module(scope, validated)
        elif scope.mode == "function":
            self._validate_function(scope, validated)
        return validated

    def _refresh_scope(self, scope: CourseScope) -> CourseScope:
        if scope.mode == "architecture":
            return self.selector.architecture()
        if scope.mode == "module":
            return self.selector.module(scope.scope_id)
        return self.selector.function(scope.scope_id)

    def _validate_identity(
        self, scope: CourseScope, records: list[dict[str, object]]
    ) -> None:
        manifest = next(
            record
            for record in scope.records
            if record.get("record_type") == "knowledge_manifest"
        )
        document = next(
            record for record in records if record.get("record_type") == "document"
        )
        expected_id = f"course.{scope.mode}.{scope.scope_id}"
        if document.get("id") != expected_id:
            raise CodeLearnerError(
                f"generated course document ID must be {expected_id}"
            )
        if document.get("course_mode") != scope.mode:
            raise CodeLearnerError("generated course mode does not match request")
        if document.get("scope_id") != scope.scope_id:
            raise CodeLearnerError("generated course scope does not match request")
        for record in records:
            if record.get("analysis_run_id") != manifest.get("analysis_run_id"):
                raise CodeLearnerError(
                    "course analysis run ID does not match knowledge"
                )
            if record.get("repository_revision") != manifest.get(
                "repository_revision"
            ):
                raise CodeLearnerError(
                    "course repository revision does not match knowledge"
                )

    def _validate_architecture(
        self, scope: CourseScope, records: list[dict[str, object]]
    ) -> None:
        sections = [
            record for record in records if record.get("record_type") == "section"
        ]
        if any(not record.get("source_refs") for record in sections):
            raise CodeLearnerError(
                "every Architecture section requires source references"
            )
        diagram_types = {
            _diagram_type(diagram)
            for section in sections
            for diagram in section.get("diagrams", [])
            if isinstance(diagram, dict)
        }
        component_types = {
            "architecture",
            "architecture-beta",
            "component",
            "flowchart",
        }
        if not diagram_types & component_types:
            raise CodeLearnerError(
                "Architecture course requires a Mermaid component diagram"
            )
        if "sequencediagram" not in diagram_types:
            raise CodeLearnerError(
                "Architecture course requires a Mermaid sequence diagram"
            )
        bodies = "\n".join(str(section.get("body") or "") for section in sections)
        _validate_mermaid_fences(bodies)
        required_entity_ids = {
            str(record.get("id"))
            for record in scope.records
            if record.get("record_type") == "entity"
            and record.get("kind")
            in {
                "module",
                "extension-family",
                "implementation",
                "entry-point",
                "interface",
                "state-store",
                "process",
                "external-system",
                "test-surface",
                "build-target",
            }
        }
        covered_entity_ids = {
            str(item)
            for section in sections
            for field in ("knowledge_entity_ids", "related_module_ids")
            for item in section.get(field, [])
        }
        missing_entities = required_entity_ids - covered_entity_ids
        if missing_entities:
            raise CodeLearnerError(
                "Architecture course omits architectural entities: "
                + ", ".join(sorted(missing_entities))
            )
        for record_type, field, label in (
            ("relationship", "relationship_ids", "relationships"),
            ("runtime_flow", "runtime_flow_ids", "runtime flows"),
            ("diagnostic", "diagnostic_ids", "diagnostics"),
        ):
            required = {
                str(record.get("id"))
                for record in scope.records
                if record.get("record_type") == record_type
            }
            covered = {
                str(item) for section in sections for item in section.get(field, [])
            }
            missing = required - covered
            if missing:
                raise CodeLearnerError(
                    f"Architecture course omits {label}: "
                    + ", ".join(sorted(missing))
                )

    def _validate_module(
        self, scope: CourseScope, records: list[dict[str, object]]
    ) -> None:
        document = next(
            record for record in records if record.get("record_type") == "document"
        )
        sections = [
            record for record in records if record.get("record_type") == "section"
        ]
        required_topics = {
            "purpose",
            "interfaces",
            "dependencies",
            "internals",
            "state",
            "flows",
            "tests",
            "changes",
            "risks",
        }
        coverage = set(document.get("coverage_topics", []))
        section_topics = {str(section.get("topic") or "") for section in sections}
        if required_topics - coverage or required_topics - section_topics:
            missing = (required_topics - coverage) | (required_topics - section_topics)
            raise CodeLearnerError(
                "Module course omits required topics: "
                + ", ".join(sorted(missing))
            )
        if any(not section.get("source_refs") for section in sections):
            raise CodeLearnerError("every Module section requires source references")
        covered_entities = {
            str(item)
            for section in sections
            for field in ("knowledge_entity_ids", "related_module_ids")
            for item in section.get(field, [])
        }
        required_entities = {
            str(record["id"])
            for record in scope.records
            if record.get("record_type") == "entity"
            and record.get("kind")
            in {"module", "extension-family", "implementation", "interface"}
        }
        if missing_entities := required_entities - covered_entities:
            raise CodeLearnerError(
                "Module course omits related entities: "
                + ", ".join(sorted(missing_entities))
            )
        relationships = {
            str(record["id"])
            for record in scope.records
            if record.get("record_type") == "relationship"
        }
        covered_relationships = {
            str(item)
            for section in sections
            for item in section.get("relationship_ids", [])
        }
        if missing_relationships := relationships - covered_relationships:
            raise CodeLearnerError(
                "Module course omits direct relationships: "
                + ", ".join(sorted(missing_relationships))
            )
        if len(relationships) >= 2:
            diagrams = [
                diagram
                for section in sections
                for diagram in section.get("diagrams", [])
                if isinstance(diagram, dict)
            ]
            bodies = "\n".join(str(section.get("body") or "") for section in sections)
            if not diagrams or not _mermaid_blocks(bodies):
                raise CodeLearnerError(
                    "connected Module course requires an evidence-grounded diagram"
                )

    def _write_scope(self, scope: CourseScope) -> Path:
        path = (
            self.store.analysis_root
            / "course-inputs"
            / f"{scope.mode}-{_safe_scope(scope.scope_id)}.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                "".join(
                    json.dumps(record, sort_keys=True) + "\n"
                    for record in scope.records
                ),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def _function_request(self, symbol: Mapping[str, object]) -> dict[str, object]:
        manifest = self.store.get("knowledge.manifest")
        symbol_id = str(symbol["id"])
        return {
            "schema_version": 1,
            "record_type": "knowledge_request",
            "id": f"request.function-evidence.{_safe_scope(symbol_id)}",
            "analysis_run_id": manifest["analysis_run_id"],
            "repository_revision": manifest["repository_revision"],
            "scope_id": symbol_id,
            "missing_facts": (
                "Inspect this symbol's contract, callers, callees, control flow, "
                "state access, side effects, errors, tests, and dynamic dispatch."
            ),
            "related_record_ids": [symbol_id],
            "status": "open",
            "source_refs": list(symbol.get("source_refs", [])),
            "attributes": {
                "gap_code": "function-evidence",
                "suggested_paths": [
                    str(reference.get("path"))
                    for reference in symbol.get("source_refs", [])
                    if isinstance(reference, dict) and reference.get("path")
                ],
                "blocks_course": True,
            },
        }

    def _validate_function(
        self, scope: CourseScope, records: list[dict[str, object]]
    ) -> None:
        document = next(
            record for record in records if record.get("record_type") == "document"
        )
        sections = [
            record for record in records if record.get("record_type") == "section"
        ]
        required_topics = {
            "contract",
            "control-flow",
            "calls",
            "side-effects",
            "errors",
            "tests",
        }
        coverage = set(document.get("coverage_topics", []))
        section_topics = {str(section.get("topic") or "") for section in sections}
        if missing := (required_topics - coverage) | (required_topics - section_topics):
            raise CodeLearnerError(
                "Function course omits required topics: "
                + ", ".join(sorted(missing))
            )
        if any(not section.get("source_refs") for section in sections):
            raise CodeLearnerError("every Function section requires source references")
        symbol = next(
            record for record in scope.records if record.get("id") == scope.scope_id
        )
        attributes = symbol.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        edge_ids = set(attributes.get("caller_ids", [])) | set(
            attributes.get("callee_ids", [])
        )
        if edge_ids:
            diagrams = [
                diagram
                for section in sections
                for diagram in section.get("diagrams", [])
                if isinstance(diagram, dict)
            ]
            diagram_types = {_diagram_type(diagram) for diagram in diagrams}
            bodies = "\n".join(str(section.get("body") or "") for section in sections)
            has_call_graph = bool(
                diagram_types & {"flowchart", "graph", "callgraph"}
            ) and bool(_mermaid_blocks(bodies))
            if not has_call_graph:
                raise CodeLearnerError(
                    "Function course requires a Mermaid call graph for known edges"
                )
            preserved = next(
                (
                    section.get("call_edge_confidence")
                    for section in sections
                    if isinstance(section.get("call_edge_confidence"), dict)
                ),
                None,
            )
            if preserved != attributes.get("call_edge_confidence"):
                raise CodeLearnerError(
                    "Function course must preserve call-edge confidence"
                )

    def _link_function_course(
        self, scope: CourseScope, records: list[dict[str, object]]
    ) -> None:
        document = next(
            record for record in records if record.get("record_type") == "document"
        )
        target_id = str(document["id"])
        symbol = self.store.get(scope.scope_id)
        owner_id = str(symbol.get("parent_id") or "")
        for path in sorted(self.store.courses_root.rglob("*.jsonl")):
            if path == self.store.course_path("function", scope.scope_id):
                continue
            course = parse_jsonl(
                path.read_text(encoding="utf-8"),
                artifact=path.relative_to(self.root).as_posix(),
            )
            changed = False
            for section in course:
                if section.get("record_type") != "section":
                    continue
                if scope.scope_id not in section.get(
                    "related_symbol_ids", []
                ) and owner_id not in section.get("related_module_ids", []):
                    continue
                links = list(section.get("deep_dive_ids", []))
                if target_id not in links:
                    links.append(target_id)
                    section["deep_dive_ids"] = links
                    changed = True
            if not changed:
                continue
            course_document = next(
                item for item in course if item.get("record_type") == "document"
            )
            mode = str(course_document["course_mode"])
            course_scope = str(course_document["scope_id"])
            self.store.save_course(mode, course_scope, course)
            render_saved_course(self.root, mode, course_scope)

    def _progress(
        self,
        phase: str,
        percent: int,
        message: str,
        callback: ProgressCallback | None,
    ) -> None:
        event = {
            "record_type": "progress",
            "phase": phase,
            "percent": percent,
            "message": message,
            "updated_at": utc_now(),
        }
        self._emit_event(event, callback)

    def _emit_event(
        self,
        event: dict[str, object],
        callback: ProgressCallback | None,
    ) -> None:
        event.setdefault("updated_at", utc_now())
        self.store.append_progress(event)
        if callback:
            callback(event)


def _diagram_type(diagram: Mapping[str, object]) -> str:
    return re.sub(r"[^a-z-]", "", str(diagram.get("type") or "").lower())


def _validate_mermaid_fences(markdown: str) -> None:
    blocks = _mermaid_blocks(markdown)
    if len(blocks) < 2:
        raise CodeLearnerError(
            "Architecture course must contain component and sequence Mermaid fences"
        )
    if not any(
        re.search(r"^\s*(?:flowchart|graph|architecture-beta)\b", block)
        for block in blocks
    ):
        raise CodeLearnerError("Architecture component Mermaid syntax is missing")
    if not any(re.search(r"^\s*sequenceDiagram\b", block) for block in blocks):
        raise CodeLearnerError("Architecture sequence Mermaid syntax is missing")


def _mermaid_blocks(markdown: str) -> list[str]:
    return re.findall(r"```mermaid\s*\n(.*?)```", markdown, flags=re.DOTALL)


def _safe_scope(scope_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", scope_id).strip(".-") or "course"


def _symbol_attribute(symbol: Mapping[str, object], field: str) -> object:
    attributes = symbol.get("attributes")
    return attributes.get(field, "") if isinstance(attributes, dict) else ""


def _function_evidence_missing(symbol: Mapping[str, object]) -> bool:
    attributes = symbol.get("attributes")
    if not isinstance(attributes, dict):
        return True
    return any(
        field not in attributes
        for field in (
            "signature",
            "caller_ids",
            "callee_ids",
            "state_access_ids",
            "side_effects",
            "analysis_limitations",
            "call_edge_confidence",
        )
    )


def _default_runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
