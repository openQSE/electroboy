"""Important and on-demand exact-symbol Function knowledge for Phase 3."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from electroboy.adapters.base import AgentInvocation, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .architecture_knowledge import ArchitectureKnowledgeService
from .domain import CodeLearnerError
from .knowledge import Phase3KnowledgeContext
from .module_knowledge import ModuleKnowledgeService
from .phase3_contract_catalog import (
    CALL_CONFIDENCE_VALUES,
    CALL_EDGE_REQUIRED_FIELDS,
    FUNCTION_DETAIL_FIELDS,
    FUNCTION_KNOWLEDGE_REQUIRED_FIELDS,
    missing_required_fields,
)
from .phase3_contracts import parse_phase3_jsonl
from .phase3_prompts import (
    function_knowledge_prompt,
    important_function_selection_prompt,
)
from .phase3_store import Phase3Store

FUNCTION_ROLE = "code_learner_analysis"
class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


@dataclass(frozen=True)
class FunctionResolution:
    status: str
    symbol: dict[str, object] | None = None
    candidates: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "candidates": list(self.candidates),
        }


class FunctionKnowledgeService:
    """Resolve, generate, and cache Function knowledge independently."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Phase3Store | None = None,
        runtime_factory: RuntimeFactory | None = None,
        symbol_resolver=None,
        eager_budget: int = 24,
        max_attempts: int = 2,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.runtime_factory = runtime_factory or _runtime_factory
        self.symbol_resolver = symbol_resolver
        self.eager_budget = max(0, eager_budget)
        self.max_attempts = max(1, max_attempts)
        self.root_path = self.store.knowledge_root / "functions"
        self.selection_path = self.store.knowledge_root / "important-functions.json"
        self.links_path = self.store.knowledge_root / "function-links.jsonl"

    def resolve(self, query: str) -> FunctionResolution:
        context = self._context()
        requested = str(query or "").strip().lower()
        if not requested:
            return FunctionResolution("missing")
        symbols = list(context.symbols.values())
        canonical = [
            symbol
            for key, symbol in context.symbols.items()
            if key.lower() == requested
        ]
        if len(canonical) == 1:
            return FunctionResolution("exact", dict(canonical[0]), tuple(canonical))
        qualified = [
            symbol
            for symbol in symbols
            if symbol.get("scope") and _qualified_name(symbol).lower() == requested
        ]
        if len(qualified) == 1:
            return FunctionResolution(
                "qualified", dict(qualified[0]), tuple(map(dict, qualified))
            )
        exact = [
            symbol
            for symbol in symbols
            if str(symbol.get("name") or "").lower() == requested
        ]
        if len(exact) == 1:
            return FunctionResolution("exact", dict(exact[0]), tuple(map(dict, exact)))
        if len(exact) > 1 or len(qualified) > 1:
            matches = exact or qualified
            return FunctionResolution("ambiguous", candidates=tuple(map(dict, matches)))
        partial = [
            symbol for symbol in symbols if requested in _qualified_name(symbol).lower()
        ]
        if len(partial) == 1:
            return FunctionResolution(
                "partial", dict(partial[0]), tuple(map(dict, partial))
            )
        if partial:
            return FunctionResolution(
                "ambiguous", candidates=tuple(map(dict, partial[:20]))
            )
        return FunctionResolution("missing")

    def select_important(self, text: str) -> list[dict[str, object]]:
        """Validate AI rankings against exact symbols and the eager budget."""

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise CodeLearnerError(f"invalid important-function selection: {error}")
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("selections"), list
        ):
            raise CodeLearnerError("important-function selections must be an array")
        context = self._context()
        selected = []
        seen = set()
        for index, item in enumerate(payload["selections"]):
            if not isinstance(item, Mapping):
                raise CodeLearnerError(f"selections[{index}] must be an object")
            key = str(item.get("canonical_key") or "")
            if key not in context.symbols:
                raise CodeLearnerError(
                    f"selections[{index}] is not an exact canonical symbol"
                )
            importance = int(item.get("importance") or 0)
            reason = str(item.get("reason") or "").strip()
            if not 1 <= importance <= 100 or not reason:
                raise CodeLearnerError(
                    f"selections[{index}] needs importance and reason"
                )
            if key not in seen:
                selected.append(
                    {
                        "canonical_key": key,
                        "importance": importance,
                        "reason": reason,
                    }
                )
                seen.add(key)
        selected.sort(
            key=lambda item: (-int(item["importance"]), item["canonical_key"])
        )
        selected = selected[: self.eager_budget]
        self.store.write_json(
            self.selection_path,
            {
                "schema_version": 1,
                "repository_revision": context.revision,
                "budget": self.eager_budget,
                "selections": selected,
                "selected_at": utc_now(),
            },
        )
        return selected

    def eager_generate(
        self,
        *,
        analysis_run_id: str,
        selection_runtime: AgentRuntime | None = None,
    ) -> list[dict[str, object]]:
        context = self._context()
        if not self.eager_budget:
            return []
        runtime = selection_runtime or self.runtime_factory(FUNCTION_ROLE, self.root)
        prompt = important_function_selection_prompt(
            self.root,
            repository_revision=context.revision,
            component_manifest_path=context.component_service.manifest_path,
            module_manifest_path=context.module_service.manifest_path,
            architecture_knowledge_path=ArchitectureKnowledgeService(
                self.root, store=self.store
            ).path,
            module_knowledge_path=ModuleKnowledgeService(
                self.root, store=self.store
            ).root_path,
            budget=self.eager_budget,
        )
        result = runtime.invoke(
            AgentInvocation(
                role=FUNCTION_ROLE,
                prompt=prompt,
                context_paths=self._context_paths(context),
            )
        )
        if not result.ok:
            raise CodeLearnerError(
                result.error or "important-function selection failed"
            )
        selections = self.select_important(result.final_message)
        return [
            self.generate(selection["canonical_key"], analysis_run_id=analysis_run_id)
            for selection in selections
        ]

    def generate(self, query: str, *, analysis_run_id: str) -> dict[str, object]:
        """Generate one resolved function without touching initialization state."""

        resolution = self.resolve(query)
        if resolution.status == "ambiguous":
            names = ", ".join(_qualified_name(item) for item in resolution.candidates)
            raise CodeLearnerError(
                f"function symbol is ambiguous; choose one canonical target: {names}"
            )
        if resolution.symbol is None:
            raise CodeLearnerError(f"function symbol was not found: {query}")
        symbol = resolution.symbol
        cached = self.load(str(symbol["canonical_key"]))
        if cached is not None:
            return cached
        context = self._context()
        component_ids, module_ids = self._ownership(context, symbol)
        runtime = self.runtime_factory(FUNCTION_ROLE, self.root)
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            prompt = function_knowledge_prompt(
                self.root,
                analysis_run_id=analysis_run_id,
                repository_revision=context.revision,
                symbol=symbol,
                component_ids=component_ids,
                module_ids=module_ids,
                source_manifest_path=context.source_service.manifest_path,
                component_manifest_path=context.component_service.manifest_path,
                module_manifest_path=context.module_service.manifest_path,
                architecture_knowledge_path=ArchitectureKnowledgeService(
                    self.root, store=self.store
                ).path,
                module_knowledge_path=ModuleKnowledgeService(
                    self.root, store=self.store
                ).root_path,
                schema_path=Path(__file__).with_name("schemas")
                / "phase3.schema.json",
            )
            if last_error:
                prompt += f"\n\nPrevious output error:\n- {last_error}"
            result = runtime.invoke(
                AgentInvocation(
                    role=FUNCTION_ROLE,
                    prompt=prompt,
                    context_paths=self._context_paths(context),
                )
            )
            if not result.ok:
                last_error = result.error or "Function knowledge runtime failed"
                continue
            try:
                records = parse_phase3_jsonl(
                    result.final_message, artifact="Function knowledge"
                )
                if len(records) != 1:
                    raise CodeLearnerError(
                        "Function knowledge must return exactly one record"
                    )
                return self.ingest(
                    str(symbol["canonical_key"]),
                    records[0],
                    context=context,
                )
            except CodeLearnerError as error:
                last_error = str(error)
        raise CodeLearnerError(
            f"Function knowledge failed after {self.max_attempts} attempts: "
            f"{last_error}"
        )

    def ingest(
        self,
        canonical_key: str,
        record: Mapping[str, object],
        *,
        context: Phase3KnowledgeContext | None = None,
    ) -> dict[str, object]:
        context = context or self._context()
        expected = context.symbols.get(canonical_key)
        if expected is None:
            raise CodeLearnerError("Function knowledge target is not canonical")
        payload = dict(record)
        context.validate_common(payload)
        if payload.get("record_type") != "function_knowledge":
            raise CodeLearnerError("expected function_knowledge")
        missing = missing_required_fields(payload, FUNCTION_KNOWLEDGE_REQUIRED_FIELDS)
        if missing:
            raise CodeLearnerError(
                "Function knowledge is missing required fields: "
                + ", ".join(missing)
            )
        symbol = payload.get("symbol")
        if not isinstance(symbol, Mapping):
            raise CodeLearnerError("Function knowledge symbol is required")
        resolved = context.resolve_symbols([symbol], path="symbol")[0]
        if resolved.get("canonical_key") != canonical_key:
            raise CodeLearnerError("Function knowledge changed its exact symbol target")
        payload["symbol"] = resolved
        component_ids, module_ids = self._ownership(context, resolved)
        if set(payload.get("component_ids", [])) != set(component_ids):
            raise CodeLearnerError("Function component context is incomplete")
        if set(payload.get("module_ids", [])) != set(module_ids):
            raise CodeLearnerError("Function module context is incomplete")
        for field in FUNCTION_DETAIL_FIELDS:
            if field not in payload:
                raise CodeLearnerError(f"Function {field} is required")
        related_symbols = [canonical_key]
        for field in ("callers", "callees"):
            payload[field] = context.resolve_symbols(payload[field], path=field)
            related_symbols.extend(
                str(item["canonical_key"]) for item in payload[field]
            )
        for index, edge in enumerate(payload.get("call_edges", [])):
            if not isinstance(edge, Mapping):
                raise CodeLearnerError(f"call_edges[{index}] must be an object")
            missing = missing_required_fields(edge, CALL_EDGE_REQUIRED_FIELDS)
            if missing:
                raise CodeLearnerError(
                    f"call_edges[{index}] is missing required fields: "
                    + ", ".join(missing)
                )
            if edge.get("confidence") not in CALL_CONFIDENCE_VALUES:
                raise CodeLearnerError(
                    f"call_edges[{index}] needs "
                    "direct/inferred/dynamic/unresolved confidence"
                )
            for field in ("from_symbol_key", "to_symbol_key", "summary"):
                if not str(edge.get(field) or "").strip():
                    raise CodeLearnerError(f"call_edges[{index}].{field} is required")
            related_symbols.extend(
                str(edge[field]) for field in ("from_symbol_key", "to_symbol_key")
            )
        context.validate_diagrams(
            payload.get("diagrams", []), additional_node_ids=related_symbols
        )
        payload["cache_key"] = self._cache_key(context.revision, canonical_key)
        payload["validated_at"] = utc_now()
        self.store.write_jsonl(self._path(context.revision, canonical_key), [payload])
        self._save_links(canonical_key, component_ids, module_ids)
        return payload

    def load(self, canonical_key: str) -> dict[str, object] | None:
        context = self._context()
        records = self.store.read_jsonl(self._path(context.revision, canonical_key))
        if not records:
            return None
        record = records[0]
        return record if record.get("repository_revision") == context.revision else None

    def _ownership(
        self, context: Phase3KnowledgeContext, symbol: Mapping[str, object]
    ) -> tuple[list[str], list[str]]:
        key = str(symbol.get("canonical_key") or "")
        component_ids = sorted(
            component_id
            for component_id, component in context.components.items()
            if any(
                item.get("canonical_key") == key
                for item in component.get("symbols", [])
                if isinstance(item, Mapping)
            )
        )
        module_ids = sorted(
            module_id
            for module_id, module in context.modules.items()
            if set(module.get("component_ids", [])) & set(component_ids)
        )
        return component_ids, module_ids

    def _save_links(
        self, canonical_key: str, component_ids: list[str], module_ids: list[str]
    ) -> None:
        current = {
            str(item.get("canonical_key") or ""): item
            for item in self.store.read_jsonl(self.links_path)
        }
        current[canonical_key] = {
            "canonical_key": canonical_key,
            "architecture_target_id": "architecture:current",
            "component_ids": component_ids,
            "module_ids": module_ids,
            "function_path": self._path(self._context().revision, canonical_key)
            .relative_to(self.root)
            .as_posix(),
        }
        self.store.write_jsonl(
            self.links_path, [current[key] for key in sorted(current)]
        )

    def _path(self, revision: str, canonical_key: str) -> Path:
        return self.root_path / f"{self._cache_key(revision, canonical_key)}.jsonl"

    def _cache_key(self, revision: str, canonical_key: str) -> str:
        return hashlib.sha256(f"{revision}\0{canonical_key}".encode()).hexdigest()

    def _context(self) -> Phase3KnowledgeContext:
        return Phase3KnowledgeContext(
            self.root, store=self.store, symbol_resolver=self.symbol_resolver
        )

    def _context_paths(self, context: Phase3KnowledgeContext) -> list[str]:
        candidates = [
            context.source_service.manifest_path,
            context.component_service.manifest_path,
            context.component_service.components_path,
            context.module_service.manifest_path,
            context.module_service.modules_path,
            ArchitectureKnowledgeService(self.root, store=self.store).path,
            ModuleKnowledgeService(self.root, store=self.store).root_path,
        ]
        return [
            path.relative_to(self.root).as_posix()
            for path in candidates
            if path.exists()
        ]


def _qualified_name(symbol: Mapping[str, object]) -> str:
    scope = str(symbol.get("scope") or "")
    name = str(symbol.get("name") or "")
    return f"{scope}.{name}" if scope else name


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
