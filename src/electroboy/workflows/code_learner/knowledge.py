"""Shared validation context for Phase 3 layered knowledge artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .component_manifest import ComponentManifestService
from .ctags_evidence import SymbolLocatorResolver
from .domain import CodeLearnerError
from .modules import ModuleSynthesisService
from .phase3_contract_catalog import (
    DIAGRAM_REQUIRED_FIELDS,
    LINK_REQUIRED_FIELDS,
    missing_required_fields,
)
from .phase3_contracts import SymbolLocator, validate_knowledge_artifacts
from .phase3_store import Phase3Store
from .relationships import ModuleRelationshipService
from .source_manifest import SourceManifestService


class Phase3KnowledgeContext:
    """Resolve all canonical catalogs used by knowledge generation."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Phase3Store | None = None,
        symbol_resolver=None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.source_service = SourceManifestService(self.root)
        self.component_service = ComponentManifestService(self.root, store=self.store)
        self.module_service = ModuleSynthesisService(self.root, store=self.store)
        self.relationship_service = ModuleRelationshipService(
            self.root, store=self.store
        )
        self.symbol_resolver = symbol_resolver or SymbolLocatorResolver(
            self.root, source=self.source_service
        )
        source = self.source_service.load()
        components = self.component_service.load()
        modules = self.module_service.load()
        if source is None or components is None or modules is None:
            raise CodeLearnerError(
                "frozen source, component, and module manifests precede knowledge"
            )
        self.source = source
        self.component_snapshot = components
        self.module_snapshot = modules
        self.files = source.by_id()
        self.components = {str(item["id"]): item for item in components.components}
        self.modules = {str(item["id"]): item for item in modules.modules}
        self.relationships = {
            str(item["id"]): item
            for item in self.store.read_jsonl(
                self.relationship_service.relationships_path
            )
        }
        self.symbols = {
            str(symbol.get("canonical_key") or ""): symbol
            for component in components.components
            for symbol in component.get("symbols", [])
            if isinstance(symbol, Mapping) and symbol.get("canonical_key")
        }

    @property
    def revision(self) -> str:
        return self.source.revision

    def validate_common(self, record: Mapping[str, object]) -> dict[str, object]:
        return validate_knowledge_artifacts(
            [record],
            repository_revision=self.revision,
            component_ids=set(self.components),
            module_ids=set(self.modules),
        )[0]

    def validate_source_refs(
        self, references: Sequence[Mapping[str, object]], *, path: str
    ) -> None:
        for index, reference in enumerate(references):
            file_id = str(reference.get("file_id") or "")
            if file_id not in self.files:
                raise CodeLearnerError(f"{path}[{index}] cites an unknown file")
            start = int(reference.get("start_line") or 0)
            end = int(reference.get("end_line") or 0)
            if start < 1 or end < start:
                raise CodeLearnerError(f"{path}[{index}] has an invalid range")
            if not str(reference.get("reason") or "").strip():
                raise CodeLearnerError(f"{path}[{index}] needs a reason")

    def resolve_symbols(
        self,
        locators: Sequence[Mapping[str, object]],
        *,
        path: str,
        require_confirmation: bool = False,
        warning_callback: Callable[[str], None] | None = None,
    ) -> list[dict[str, object]]:
        resolved = []
        for index, locator in enumerate(locators):
            canonical = str(locator.get("canonical_key") or "")
            if canonical and canonical in self.symbols:
                resolved.append(dict(self.symbols[canonical]))
                continue
            result = self.symbol_resolver.resolve(locator)
            if result.status != "exact":
                message = f"{path}[{index}] is {result.status}: {result.message}"
                if require_confirmation:
                    raise CodeLearnerError(message)
                accepted = SymbolLocator.from_mapping(result.locator)
                file = self.files.get(accepted.file_id)
                if file is None:
                    raise CodeLearnerError(
                        f"{path}[{index}] cites an unknown source file"
                    )
                if accepted.start_line < 1 or accepted.end_line < accepted.start_line:
                    raise CodeLearnerError(f"{path}[{index}] has an invalid range")
                preserved = accepted.to_dict()
                preserved["canonical_key"] = canonical or accepted.canonical_key(
                    self.revision, str(file["path"])
                )
                preserved["validated_by"] = "ai-authored"
                preserved["confirmation_status"] = result.status
                resolved.append(preserved)
                if warning_callback is not None:
                    warning_callback(message)
                continue
            resolved.append(
                {
                    **result.locator,
                    "canonical_key": result.canonical_key,
                    "validated_by": result.provenance,
                }
            )
        return resolved

    def validate_diagrams(
        self,
        diagrams: Sequence[Mapping[str, object]],
        *,
        require_component: bool = False,
        require_sequence: bool = False,
        additional_node_ids: Sequence[str] = (),
    ) -> None:
        types = {str(diagram.get("type") or "") for diagram in diagrams}
        if require_component and not types & {"component", "flowchart", "graph"}:
            raise CodeLearnerError("Architecture needs a component/flowchart diagram")
        if require_sequence and "sequence" not in types:
            raise CodeLearnerError("ordered cross-module flow needs a sequence diagram")
        valid_nodes = (
            set(self.modules) | set(self.components) | set(additional_node_ids)
        )
        for index, diagram in enumerate(diagrams):
            if not isinstance(diagram, Mapping):
                raise CodeLearnerError(f"diagrams[{index}] must be an object")
            missing = missing_required_fields(diagram, DIAGRAM_REQUIRED_FIELDS)
            if missing:
                raise CodeLearnerError(
                    f"diagrams[{index}] is missing required fields: "
                    + ", ".join(missing)
                )
            for field in ("id", "type", "mermaid"):
                if not str(diagram.get(field) or "").strip():
                    raise CodeLearnerError(f"diagrams[{index}].{field} is required")
            for field in ("node_ids", "relationship_ids"):
                values = diagram.get(field)
                if not isinstance(values, list) or any(
                    not isinstance(value, str) for value in values
                ):
                    raise CodeLearnerError(
                        f"diagrams[{index}].{field} must be an array of strings"
                    )
            mermaid = str(diagram.get("mermaid") or "")
            node_ids = [str(item) for item in diagram.get("node_ids", [])]
            edge_ids = [str(item) for item in diagram.get("relationship_ids", [])]
            unknown_nodes = set(node_ids) - valid_nodes
            unknown_edges = set(edge_ids) - set(self.relationships)
            if unknown_nodes or unknown_edges:
                raise CodeLearnerError(
                    f"diagrams[{index}] references stale canonical graph IDs"
                )
            missing_tokens = [
                item for item in node_ids + edge_ids if item not in mermaid
            ]
            if missing_tokens:
                raise CodeLearnerError(
                    f"diagrams[{index}] Mermaid omits declared IDs: "
                    + ", ".join(missing_tokens)
                )

    def validate_links(
        self,
        links: Sequence[Mapping[str, object]],
        *,
        warning_callback: Callable[[str], None] | None = None,
    ) -> None:
        catalogs = {
            "module": set(self.modules),
            "component": set(self.components),
            "function": set(self.symbols),
            "architecture": {"architecture:current"},
        }
        for index, link in enumerate(links):
            if not isinstance(link, Mapping):
                raise CodeLearnerError(f"deep_links[{index}] must be an object")
            missing = missing_required_fields(link, LINK_REQUIRED_FIELDS)
            if missing:
                raise CodeLearnerError(
                    f"deep_links[{index}] is missing required fields: "
                    + ", ".join(missing)
                )
            target_type = str(link.get("target_type") or "").lower()
            target_id = str(link.get("target_id") or "")
            if not target_type or not target_id:
                raise CodeLearnerError(
                    f"deep_links[{index}] needs target_type and target_id"
                )
            if isinstance(link, dict):
                link["target_type"] = target_type
            if target_id not in catalogs.get(target_type, set()):
                if warning_callback is not None:
                    warning_callback(
                        f"deep_links[{index}] target is not in the canonical catalog; "
                        "preserving the AI-authored link"
                    )
