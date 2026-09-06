"""Independent horizontal and vertical Phase 3 Module knowledge."""

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
    MODULE_HORIZONTAL_FIELDS,
    MODULE_KNOWLEDGE_REQUIRED_FIELDS,
    MODULE_VERTICAL_COMPONENT_FIELDS,
    MODULE_VERTICAL_FIELDS,
    missing_required_fields,
)
from .phase3_contracts import parse_phase3_jsonl
from .phase3_prompts import module_knowledge_prompt
from .phase3_store import Phase3Store

MODULE_KNOWLEDGE_ROLE = "code_learner_analysis"
class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


class ModuleKnowledgeService:
    """Generate one durable knowledge artifact per canonical module."""

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
        self.root_path = self.store.knowledge_root / "modules"

    def generate_all(self, *, analysis_run_id: str) -> list[dict[str, object]]:
        context = self._context()
        results = []
        for module_id in sorted(context.modules):
            results.append(
                self.generate(
                    module_id, analysis_run_id=analysis_run_id, context=context
                )
            )
        return results

    def generate(
        self,
        module_id: str,
        *,
        analysis_run_id: str,
        context: Phase3KnowledgeContext | None = None,
    ) -> dict[str, object]:
        context = context or self._context()
        if module_id not in context.modules:
            raise CodeLearnerError(f"unknown Module knowledge target: {module_id}")
        cached = self.load(module_id)
        if cached and cached.get("repository_revision") == context.revision:
            return cached
        runtime = self.runtime_factory(MODULE_KNOWLEDGE_ROLE, self.root)
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            prompt = module_knowledge_prompt(
                self.root,
                analysis_run_id=analysis_run_id,
                repository_revision=context.revision,
                module_id=module_id,
                source_manifest_path=context.source_service.manifest_path,
                component_manifest_path=context.component_service.manifest_path,
                module_manifest_path=context.module_service.manifest_path,
                relationships_path=context.relationship_service.relationships_path,
                schema_path=Path(__file__).with_name("schemas")
                / "phase3.schema.json",
            )
            if last_error:
                prompt += f"\n\nPrevious output error:\n- {last_error}"
            result = runtime.invoke(
                AgentInvocation(
                    role=MODULE_KNOWLEDGE_ROLE,
                    prompt=prompt,
                    context_paths=self._context_paths(context),
                )
            )
            self.store.write_json(
                self.store.attempts_root
                / "knowledge"
                / "modules"
                / f"{_safe(module_id)}-{attempt}.json",
                {
                    "module_id": module_id,
                    "attempt": attempt,
                    "output": result.final_message,
                    "error": result.error or "",
                    "recorded_at": utc_now(),
                },
            )
            if not result.ok:
                last_error = result.error or "Module knowledge runtime failed"
                continue
            try:
                records = parse_phase3_jsonl(
                    result.final_message, artifact=f"Module knowledge {module_id}"
                )
                if len(records) != 1:
                    raise CodeLearnerError(
                        "Module knowledge must return exactly one record"
                    )
                return self.ingest(module_id, records[0], context=context)
            except CodeLearnerError as error:
                last_error = str(error)
        raise CodeLearnerError(
            f"Module knowledge {module_id} failed after "
            f"{self.max_attempts} attempts: {last_error}"
        )

    def ingest(
        self,
        module_id: str,
        record: Mapping[str, object],
        *,
        context: Phase3KnowledgeContext | None = None,
    ) -> dict[str, object]:
        context = context or self._context()
        if module_id not in context.modules:
            raise CodeLearnerError(f"unknown Module knowledge scope: {module_id}")
        payload = dict(record)
        context.validate_common(payload)
        if payload.get("record_type") != "module_knowledge":
            raise CodeLearnerError("expected module_knowledge")
        missing = missing_required_fields(payload, MODULE_KNOWLEDGE_REQUIRED_FIELDS)
        if missing:
            raise CodeLearnerError(
                "Module knowledge is missing required fields: " + ", ".join(missing)
            )
        if payload.get("module_id") != module_id:
            raise CodeLearnerError("Module knowledge changed its bounded scope")
        if set(payload.get("module_ids", [])) != {module_id}:
            raise CodeLearnerError("Module knowledge module_ids must match scope")
        member_ids = set(context.modules[module_id].get("component_ids", []))
        if set(payload.get("component_ids", [])) != member_ids:
            raise CodeLearnerError("Module knowledge must cover every member component")
        horizontal = payload.get("horizontal")
        vertical = payload.get("vertical")
        if not isinstance(horizontal, Mapping) or not isinstance(vertical, Mapping):
            raise CodeLearnerError(
                "Module horizontal and vertical knowledge are required"
            )
        for field in MODULE_HORIZONTAL_FIELDS:
            if field not in horizontal:
                raise CodeLearnerError(f"Module horizontal.{field} is required")
        for field in MODULE_VERTICAL_FIELDS:
            if field not in vertical:
                raise CodeLearnerError(f"Module vertical.{field} is required")
        valid_edges = {
            relationship_id
            for relationship_id, relationship in context.relationships.items()
            if module_id
            in {
                relationship.get("from_module_id"),
                relationship.get("to_module_id"),
            }
        }
        if set(horizontal.get("relationship_ids", [])) != valid_edges:
            raise CodeLearnerError(
                "Module horizontal relationships must match canonical neighbors"
            )
        component_entries = self._normalize_vertical_components(
            vertical.get("components", []), context=context
        )
        vertical["components"] = component_entries
        vertical_ids = {
            str(item.get("component_id") or "")
            for item in component_entries
            if isinstance(item, Mapping)
        }
        if vertical_ids != member_ids:
            raise CodeLearnerError(
                "Module vertical components must cover every module member"
            )
        vertical["important_functions"] = context.resolve_symbols(
            vertical.get("important_functions", []),
            path="vertical.important_functions",
        )
        context.validate_diagrams(payload.get("diagrams", []))
        for diagram in payload.get("diagrams", []):
            if set(diagram.get("relationship_ids", [])) - valid_edges:
                raise CodeLearnerError("Module diagram uses a non-neighbor edge")
        context.validate_links(payload.get("peer_links", []))
        context.validate_links(payload.get("deep_links", []))
        peer_targets = {
            str(link.get("target_id") or "")
            for link in payload.get("peer_links", [])
            if isinstance(link, Mapping)
        }
        vertical_targets = {
            str(link.get("target_id") or "")
            for link in payload.get("deep_links", [])
            if isinstance(link, Mapping)
        }
        if peer_targets & vertical_targets:
            raise CodeLearnerError(
                "horizontal peer links and vertical deep links must be independent"
            )
        payload["validated_at"] = utc_now()
        self.store.write_jsonl(self._path(module_id), [payload])
        return payload

    @staticmethod
    def _normalize_vertical_components(
        entries: object,
        *,
        context: Phase3KnowledgeContext,
    ) -> list[dict[str, object]]:
        if not isinstance(entries, list):
            raise CodeLearnerError("Module vertical.components must be an array")
        normalized = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                raise CodeLearnerError(
                    f"Module vertical.components[{index}] must be an object"
                )
            item = dict(entry)
            if (
                "component_id" not in item
                and str(item.get("id") or "") in context.components
            ):
                item["component_id"] = item["id"]
            missing = missing_required_fields(item, MODULE_VERTICAL_COMPONENT_FIELDS)
            if missing:
                raise CodeLearnerError(
                    f"Module vertical.components[{index}] is missing required fields: "
                    + ", ".join(missing)
                )
            for field in MODULE_VERTICAL_COMPONENT_FIELDS:
                if not str(item.get(field) or "").strip():
                    raise CodeLearnerError(
                        f"Module vertical.components[{index}].{field} is required"
                    )
            normalized.append(item)
        return normalized

    def load(self, module_id: str) -> dict[str, object] | None:
        records = self.store.read_jsonl(self._path(module_id))
        return records[0] if records else None

    def _context(self) -> Phase3KnowledgeContext:
        return Phase3KnowledgeContext(
            self.root, store=self.store, symbol_resolver=self.symbol_resolver
        )

    def _path(self, module_id: str) -> Path:
        return self.root_path / f"{_safe(module_id)}.jsonl"

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


def _safe(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value)


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
