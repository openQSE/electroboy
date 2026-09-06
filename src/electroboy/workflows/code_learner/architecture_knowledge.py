"""Repository-wide horizontal and vertical Phase 3 Architecture knowledge."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from electroboy.adapters.base import AgentInvocation, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .domain import CodeLearnerError
from .knowledge import Phase3KnowledgeContext
from .phase3_contract_catalog import (
    ARCHITECTURE_HORIZONTAL_FIELDS,
    ARCHITECTURE_HORIZONTAL_MODULE_FIELDS,
    ARCHITECTURE_KNOWLEDGE_REQUIRED_FIELDS,
    ARCHITECTURE_STEP_FIELDS,
    ARCHITECTURE_VERTICAL_SLICE_FIELDS,
    missing_required_fields,
)
from .phase3_contracts import parse_phase3_jsonl
from .phase3_prompts import architecture_knowledge_prompt
from .phase3_store import Phase3Store

ARCHITECTURE_ROLE = "code_learner_analysis"
class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


class ArchitectureKnowledgeService:
    """Generate and validate one repository-breadth Architecture artifact."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Phase3Store | None = None,
        runtime_factory: RuntimeFactory | None = None,
        symbol_resolver=None,
        max_attempts: int = 2,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.runtime_factory = runtime_factory or _runtime_factory
        self.symbol_resolver = symbol_resolver
        self.max_attempts = max(1, max_attempts)
        self.path = self.store.knowledge_root / "architecture.jsonl"

    def generate(self, *, analysis_run_id: str) -> dict[str, object]:
        context = Phase3KnowledgeContext(
            self.root, store=self.store, symbol_resolver=self.symbol_resolver
        )
        runtime = self.runtime_factory(ARCHITECTURE_ROLE, self.root)
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            prompt = architecture_knowledge_prompt(
                self.root,
                analysis_run_id=analysis_run_id,
                repository_revision=context.revision,
                source_manifest_path=context.source_service.manifest_path,
                component_manifest_path=context.component_service.manifest_path,
                module_manifest_path=context.module_service.manifest_path,
                relationships_path=context.relationship_service.relationships_path,
                schema_path=Path(__file__).with_name("schemas") / "phase3.schema.json",
            )
            if last_error:
                prompt += f"\n\nPrevious output error:\n- {last_error}"
            result = runtime.invoke(
                AgentInvocation(
                    role=ARCHITECTURE_ROLE,
                    prompt=prompt,
                    context_paths=self._context_paths(context),
                )
            )
            self.store.write_json(
                self.store.attempts_root / "knowledge" / f"architecture-{attempt}.json",
                {
                    "attempt": attempt,
                    "output": result.final_message,
                    "error": result.error or "",
                    "recorded_at": utc_now(),
                },
            )
            if not result.ok:
                last_error = result.error or "Architecture runtime failed"
                continue
            try:
                records = parse_phase3_jsonl(
                    result.final_message, artifact="Architecture knowledge"
                )
                if len(records) != 1:
                    raise CodeLearnerError(
                        "Architecture generation must return exactly one record"
                    )
                return self.ingest(records[0], context=context)
            except CodeLearnerError as error:
                last_error = str(error)
        raise CodeLearnerError(
            f"Architecture knowledge failed after {self.max_attempts} attempts: "
            f"{last_error}"
        )

    def ingest(
        self,
        record: Mapping[str, object],
        *,
        context: Phase3KnowledgeContext | None = None,
    ) -> dict[str, object]:
        context = context or Phase3KnowledgeContext(
            self.root, store=self.store, symbol_resolver=self.symbol_resolver
        )
        payload = dict(record)
        context.validate_common(payload)
        if payload.get("record_type") != "architecture_knowledge":
            raise CodeLearnerError("expected architecture_knowledge")
        self._require_fields(
            payload, ARCHITECTURE_KNOWLEDGE_REQUIRED_FIELDS, "Architecture"
        )
        horizontal = payload.get("horizontal")
        if not isinstance(horizontal, Mapping):
            raise CodeLearnerError("Architecture horizontal knowledge is required")
        for field in ARCHITECTURE_HORIZONTAL_FIELDS:
            if field not in horizontal:
                raise CodeLearnerError(f"Architecture horizontal.{field} is required")
        generated_id = str(payload["id"])
        payload["generated_id"] = generated_id
        payload["id"] = "architecture:current"
        covered_modules = set(payload.get("module_ids", []))
        if covered_modules != set(context.modules):
            raise CodeLearnerError("Architecture must cover every frozen module")
        module_entries = self._normalize_horizontal_modules(
            horizontal.get("modules", []), context=context
        )
        horizontal["modules"] = module_entries
        horizontal_modules = {str(item["module_id"]) for item in module_entries}
        if horizontal_modules != set(context.modules):
            missing_ids = sorted(set(context.modules) - horizontal_modules)
            unknown_ids = sorted(horizontal_modules - set(context.modules))
            raise CodeLearnerError(
                "Architecture horizontal modules do not cover the manifest; "
                f"missing={missing_ids}; unknown={unknown_ids}"
            )
        horizontal_edges = {str(item) for item in horizontal.get("relationships", [])}
        if horizontal_edges != set(context.relationships):
            raise CodeLearnerError(
                "Architecture horizontal relationships do not cover accepted edges"
            )
        cross_module_ordered = False
        for slice_index, vertical in enumerate(payload.get("vertical_slices", [])):
            if not isinstance(vertical, Mapping):
                raise CodeLearnerError("vertical_slices must contain objects")
            self._require_fields(
                vertical,
                ARCHITECTURE_VERTICAL_SLICE_FIELDS,
                f"vertical_slices[{slice_index}]",
            )
            for field in ("id", "title"):
                if not str(vertical.get(field) or "").strip():
                    raise CodeLearnerError(
                        f"vertical_slices[{slice_index}].{field} is required"
                    )
            steps = vertical.get("ordered_steps", [])
            if not isinstance(steps, list) or not steps:
                raise CodeLearnerError(
                    f"vertical_slices[{slice_index}].ordered_steps must not be empty"
                )
            modules_in_flow = set()
            for step_index, step in enumerate(steps):
                if not isinstance(step, Mapping):
                    raise CodeLearnerError("ordered_steps must contain objects")
                self._require_fields(
                    step,
                    ARCHITECTURE_STEP_FIELDS,
                    f"vertical_slices[{slice_index}].ordered_steps[{step_index}]",
                )
                order = step.get("order")
                if not isinstance(order, int) or isinstance(order, bool) or order < 1:
                    raise CodeLearnerError("vertical step order must be positive")
                if not str(step.get("summary") or "").strip():
                    raise CodeLearnerError("vertical step summary is required")
                module_id = str(step.get("module_id") or "")
                if module_id not in context.modules:
                    raise CodeLearnerError("vertical step has an unknown module")
                modules_in_flow.add(module_id)
                component_ids = set(step.get("component_ids", []))
                if component_ids - set(context.components):
                    raise CodeLearnerError("vertical step has an unknown component")
                context.validate_source_refs(
                    step.get("source_refs", []),
                    path=(
                        f"vertical_slices[{slice_index}].ordered_steps"
                        f"[{step_index}].source_refs"
                    ),
                )
                step["symbol_locators"] = context.resolve_symbols(
                    step.get("symbol_locators", []),
                    path=(
                        f"vertical_slices[{slice_index}].ordered_steps"
                        f"[{step_index}].symbol_locators"
                    ),
                )
            cross_module_ordered |= len(modules_in_flow) > 1 and len(steps) > 1
            for field in (
                "alternate_flows",
                "error_flows",
                "dynamic_behavior",
                "unresolved",
            ):
                if field not in vertical:
                    raise CodeLearnerError(
                        f"vertical_slices[{slice_index}].{field} is required"
                    )
        diagrams = payload.get("diagrams", [])
        context.validate_diagrams(
            diagrams,
            require_component=True,
            require_sequence=cross_module_ordered,
        )
        context.validate_links(payload.get("deep_links", []))
        payload["validated_at"] = utc_now()
        self.store.write_jsonl(self.path, [payload])
        return payload

    def _normalize_horizontal_modules(
        self,
        entries: object,
        *,
        context: Phase3KnowledgeContext,
    ) -> list[dict[str, object]]:
        if not isinstance(entries, list):
            raise CodeLearnerError("Architecture horizontal.modules must be an array")
        normalized = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                raise CodeLearnerError(
                    f"Architecture horizontal.modules[{index}] must be an object"
                )
            item = dict(entry)
            if "module_id" not in item and str(item.get("id") or "") in context.modules:
                item["module_id"] = item["id"]
            missing = missing_required_fields(
                item, ARCHITECTURE_HORIZONTAL_MODULE_FIELDS
            )
            if missing:
                raise CodeLearnerError(
                    f"Architecture horizontal.modules[{index}] is missing required "
                    "fields: " + ", ".join(missing)
                )
            for field in ("module_id", "name", "summary"):
                if not str(item.get(field) or "").strip():
                    raise CodeLearnerError(
                        f"Architecture horizontal.modules[{index}].{field} is required"
                    )
            component_ids = item.get("component_ids")
            if not isinstance(component_ids, list) or any(
                not isinstance(value, str) for value in component_ids
            ):
                raise CodeLearnerError(
                    f"Architecture horizontal.modules[{index}].component_ids "
                    "must be an array of strings"
                )
            normalized.append(item)
        return normalized

    @staticmethod
    def _require_fields(
        record: Mapping[str, object], fields: tuple[str, ...], path: str
    ) -> None:
        missing = missing_required_fields(record, fields)
        if missing:
            raise CodeLearnerError(
                f"{path} is missing required fields: {', '.join(missing)}"
            )

    def load(self) -> dict[str, object] | None:
        records = self.store.read_jsonl(self.path)
        return records[0] if records else None

    def _context_paths(self, context: Phase3KnowledgeContext) -> list[str]:
        return [
            path.relative_to(self.root).as_posix()
            for path in (
                context.source_service.manifest_path,
                context.component_service.manifest_path,
                context.component_service.components_path,
                context.module_service.manifest_path,
                context.module_service.modules_path,
                context.relationship_service.relationships_path,
            )
            if path.is_file()
        ]


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
