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
        max_attempts: int = 2,
        retry_delay: float = 0.0,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = KnowledgeStore(self.root)
        self.selector = KnowledgeSubgraphSelector(self.store)
        self.runtime_factory = runtime_factory or _default_runtime_factory
        self.max_attempts = max(1, max_attempts)
        self.retry_delay = max(0.0, retry_delay)

    def build_architecture(
        self,
        *,
        audience: str = "",
        progress_callback: ProgressCallback | None = None,
    ) -> CourseBuildResult:
        validate_packaged_skill("code-learner-course")
        scope = self.selector.architecture()
        input_path = self._write_scope(scope)
        runtime = self.runtime_factory(COURSE_ROLE, self.root)
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            self._progress(
                "architecture_course",
                94,
                f"Generating Architecture course ({attempt}/{self.max_attempts}).",
                progress_callback,
            )
            result = runtime.invoke(
                AgentInvocation(
                    role=COURSE_ROLE,
                    prompt=course_prompt(
                        self.root,
                        scope,
                        input_path=input_path,
                        audience=audience,
                    ),
                    context_paths=[input_path.relative_to(self.root).as_posix()],
                )
            )
            try:
                records = self._accept_course(scope, result)
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
                "architecture_ready",
                98,
                "Architecture course validated and rendered.",
                progress_callback,
            )
            return CourseBuildResult(
                mode=scope.mode,
                scope_id=scope.scope_id,
                jsonl_path=jsonl_path.relative_to(self.root).as_posix(),
                markdown_path=rendered.markdown_path,
                record_count=len(records),
            )
        raise CodeLearnerError(
            f"Architecture course generation failed after {self.max_attempts} "
            f"attempts: {last_error}"
        )

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
            raise CodeLearnerError(
                "course generation requested targeted knowledge enrichment"
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
        return validated

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
        self.store.append_progress(event)
        if callback:
            callback(event)


def _diagram_type(diagram: Mapping[str, object]) -> str:
    return re.sub(r"[^a-z-]", "", str(diagram.get("type") or "").lower())


def _validate_mermaid_fences(markdown: str) -> None:
    blocks = re.findall(r"```mermaid\s*\n(.*?)```", markdown, flags=re.DOTALL)
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


def _safe_scope(scope_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", scope_id).strip(".-") or "course"


def _default_runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
