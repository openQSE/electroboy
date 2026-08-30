"""Backend module and workflow registry primitives for the browser service."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .http import ServiceResponse
    from .routes import RouteRequest
    from .services import ServiceServices

MODULE_ENTRY_POINT_GROUP = "electroboy.modules"
WORKFLOW_ENTRY_POINT_GROUP = "electroboy.workflows"

_SOURCE_MODULE_FACTORIES = {
    "core": "electroboy.service.core_module:module",
    "agent_sessions": "electroboy.modules.agent_sessions:module",
    "agenda": "electroboy.modules.agenda:module",
    "calendar": "electroboy.modules.calendar:module",
    "binder": "electroboy.modules.binder:module",
    "corkboard": "electroboy.modules.corkboard:module",
    "file_browser": "electroboy.modules.file_browser:module",
    "markdown_documents": "electroboy.modules.markdown_documents:module",
    "mind_map": "electroboy.modules.mind_map:module",
    "progress": "electroboy.modules.progress:module",
    "project_shell": "electroboy.modules.project_shell:module",
    "recent_projects": "electroboy.modules.recent_projects:module",
    "review_reports": "electroboy.modules.review_reports:module",
    "structured_documents": "electroboy.modules.structured_documents:module",
}

_SOURCE_WORKFLOW_FACTORIES = {
    "software": "electroboy.workflows.software.plugin:workflow",
    "creative-writing": "electroboy.workflows.creative_writing.plugin:workflow",
}


class WorkflowController(Protocol):
    """Executable workflow behavior bound to one service runtime."""

    workflow_id: str


WorkflowControllerFactory = Callable[["ServiceServices"], WorkflowController]
RouteHandler = Callable[["RouteRequest"], "ServiceResponse"]
StageOperationsFactory = Callable[[str, Path | str | None], list[str]]


@dataclass(frozen=True)
class CliCommandDefinition:
    """Serializable command metadata contributed by a plugin."""

    id: str
    label: str
    description: str = ""

    def payload(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "description": self.description}


@dataclass(frozen=True)
class DocumentSchemaDefinition:
    """Structured document schema metadata contributed by a plugin."""

    id: str
    label: str
    version: int = 1
    source_format: str = "jsonl"

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "version": self.version,
            "source_format": self.source_format,
        }


@dataclass(frozen=True)
class AgentRuleDefinition:
    """Agent-facing rule content contributed by a module or workflow."""

    id: str
    label: str
    content: str
    priority: int = 100
    version: int = 1

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "priority": self.priority,
            "version": self.version,
        }


@dataclass(frozen=True)
class RuntimeRoleDefinition:
    """Agent runtime role metadata contributed by a plugin."""

    id: str
    label: str
    interactive: bool = False
    mutating: bool = False

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "interactive": self.interactive,
            "mutating": self.mutating,
        }


@dataclass(frozen=True)
class RouteDefinition:
    """HTTP route metadata owned by a core service or capability module."""

    method: str
    path: str
    owner: str
    handler_name: str

    def payload(self) -> dict[str, str]:
        return {
            "method": self.method,
            "path": self.path,
            "owner": self.owner,
            "handler": self.handler_name,
        }


@dataclass(frozen=True)
class ServiceModule:
    """Reusable backend capability registered with the service core."""

    id: str
    label: str
    routes: tuple[RouteDefinition, ...] = ()
    handlers: dict[str, RouteHandler] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    assets: tuple[str, ...] = ()
    asset_package: str | None = None
    asset_root: str = "assets"
    capabilities: frozenset[str] = frozenset()
    commands: tuple[CliCommandDefinition, ...] = ()
    document_schemas: tuple[DocumentSchemaDefinition, ...] = ()
    agent_rules: tuple[AgentRuleDefinition, ...] = ()
    runtime_roles: tuple[RuntimeRoleDefinition, ...] = ()
    state_namespace: str | None = None
    provider: str = "electroboy"
    entry_point: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "routes": [route.payload() for route in self.routes],
            "assets": list(self.assets),
            "asset_package": self.asset_package,
            "capabilities": sorted(self.capabilities),
            "commands": [entry.payload() for entry in self.commands],
            "document_schemas": [entry.payload() for entry in self.document_schemas],
            "agent_rules": [entry.payload() for entry in self.agent_rules],
            "runtime_roles": [entry.payload() for entry in self.runtime_roles],
            "state_namespace": self.state_namespace,
            "provider": self.provider,
            "entry_point": self.entry_point,
        }


@dataclass(frozen=True)
class WorkflowStage:
    """Command-facing workflow stage metadata."""

    id: str
    label: str
    command: str | None
    documents: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    next_stage: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "command": self.command,
            "documents": list(self.documents),
            "actions": list(self.actions),
            "next_stage": self.next_stage,
        }


@dataclass(frozen=True)
class WorkflowDefinition:
    """Installable workflow metadata for the browser service."""

    id: str
    label: str
    modules: tuple[str, ...]
    stages: tuple[WorkflowStage, ...]
    project_kinds: tuple[str, ...]
    backend_package: str
    frontend_bundle: str
    asset_package: str | None = None
    asset_root: str = "assets"
    asset_resource: str = "frontend.js"
    frontend_stylesheets: tuple[str, ...] = ()
    routes: tuple[RouteDefinition, ...] = ()
    handlers: dict[str, RouteHandler] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    controller_factory: WorkflowControllerFactory | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    stage_operations_factory: StageOperationsFactory | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    commands: tuple[CliCommandDefinition, ...] = ()
    document_schemas: tuple[DocumentSchemaDefinition, ...] = ()
    agent_rules: tuple[AgentRuleDefinition, ...] = ()
    runtime_roles: tuple[RuntimeRoleDefinition, ...] = ()
    provider: str = "electroboy"
    entry_point: str | None = None
    workspace_policy: str = "exclusive"

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "modules": list(self.modules),
            "stages": [stage.payload() for stage in self.stages],
            "project_kinds": list(self.project_kinds),
            "backend_package": self.backend_package,
            "frontend_bundle": self.frontend_bundle,
            "asset_package": self.asset_package,
            "asset_resource": self.asset_resource,
            "frontend_stylesheets": list(self.frontend_stylesheets),
            "routes": [route.payload() for route in self.routes],
            "commands": [entry.payload() for entry in self.commands],
            "document_schemas": [entry.payload() for entry in self.document_schemas],
            "agent_rules": [entry.payload() for entry in self.agent_rules],
            "runtime_roles": [entry.payload() for entry in self.runtime_roles],
            "provider": self.provider,
            "entry_point": self.entry_point,
            "workspace_policy": self.workspace_policy,
        }


@dataclass(frozen=True)
class InstalledFactory:
    """A definition factory discovered from installed package metadata."""

    id: str
    group: str
    provider: str
    reference: str
    factory: Callable[[], object] = field(repr=False, compare=False)

    def __call__(self) -> ServiceModule | WorkflowDefinition:
        definition = self.factory()
        expected_type = (
            ServiceModule
            if self.group == MODULE_ENTRY_POINT_GROUP
            else WorkflowDefinition
        )
        if not isinstance(definition, expected_type):
            raise TypeError(
                f"entry point {self.reference} did not return "
                f"{expected_type.__name__}"
            )
        if definition.id != self.id:
            raise ValueError(
                "entry point name does not match definition id: "
                f"{self.id} != {definition.id}"
            )
        return replace(
            definition,
            provider=self.provider,
            entry_point=self.reference,
        )


@dataclass
class ModuleRegistry:
    """Registry for reusable backend service modules."""

    _modules: dict[str, ServiceModule] = field(default_factory=dict)

    def register(self, module: ServiceModule) -> None:
        if module.id in self._modules:
            raise ValueError(f"service module is already registered: {module.id}")
        _validate_contribution_metadata(module)
        self._modules[module.id] = module

    def get(self, module_id: str) -> ServiceModule:
        return self._modules[module_id]

    def values(self) -> tuple[ServiceModule, ...]:
        return tuple(self._modules.values())

    def payload(self) -> list[dict[str, object]]:
        return [module.payload() for module in self.values()]


@dataclass
class WorkflowRegistry:
    """Registry for installed workflows."""

    modules: ModuleRegistry
    _workflows: dict[str, WorkflowDefinition] = field(default_factory=dict)

    def register(self, workflow: WorkflowDefinition) -> None:
        if workflow.id in self._workflows:
            raise ValueError(f"workflow is already registered: {workflow.id}")
        missing = [
            module_id
            for module_id in workflow.modules
            if module_id not in self.modules._modules
        ]
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(
                f"workflow {workflow.id} requires missing modules: {missing_list}"
            )
        if workflow.workspace_policy not in {"exclusive", "shared-singleton"}:
            raise ValueError(
                f"workflow {workflow.id} has invalid workspace policy: "
                f"{workflow.workspace_policy}"
            )
        _validate_contribution_metadata(workflow)
        self._workflows[workflow.id] = workflow

    def get(self, workflow_id: str) -> WorkflowDefinition:
        return self._workflows[workflow_id]

    def values(self) -> tuple[WorkflowDefinition, ...]:
        return tuple(self._workflows.values())

    def payload(self) -> list[dict[str, object]]:
        return [workflow.payload() for workflow in self.values()]

    def create_controllers(
        self,
        services: ServiceServices,
    ) -> dict[str, WorkflowController]:
        """Bind every executable workflow to a service runtime."""
        controllers: dict[str, WorkflowController] = {}
        for workflow in self.values():
            if workflow.controller_factory is None:
                continue
            controller = workflow.controller_factory(services)
            if controller.workflow_id != workflow.id:
                raise ValueError(
                    "workflow controller id does not match its definition: "
                    f"{controller.workflow_id} != {workflow.id}"
                )
            controllers[workflow.id] = controller
        return controllers


def _validate_contribution_metadata(
    contribution: ServiceModule | WorkflowDefinition,
) -> None:
    for field_name in (
        "commands",
        "document_schemas",
        "agent_rules",
        "runtime_roles",
    ):
        entries = getattr(contribution, field_name)
        identifiers = [entry.id.strip() for entry in entries]
        if any(not identifier for identifier in identifiers):
            raise ValueError(
                f"{contribution.id} has an empty {field_name} identifier"
            )
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(
                f"{contribution.id} has duplicate {field_name} identifiers"
            )
        if field_name == "agent_rules" and any(
            not entry.content.strip() for entry in entries
        ):
            raise ValueError(f"{contribution.id} has empty agent rule content")


def build_module_registry(
    modules: Iterable[ServiceModule] | None = None,
) -> ModuleRegistry:
    registry = ModuleRegistry()
    selected_modules = built_in_service_modules() if modules is None else modules
    for module in selected_modules:
        registry.register(module)
    return registry


def build_workflow_registry(
    module_registry: ModuleRegistry,
    workflows: Iterable[WorkflowDefinition] | None = None,
) -> WorkflowRegistry:
    registry = WorkflowRegistry(module_registry)
    selected_workflows = built_in_workflows() if workflows is None else workflows
    for workflow in selected_workflows:
        registry.register(workflow)
    return registry


def built_in_service_modules() -> tuple[ServiceModule, ...]:
    """Return all installed service module contributions.

    The historical function name remains as a compatibility API. Discovery is
    now driven by installed package entry points.
    """

    return tuple(factory() for factory in installed_module_factories().values())


def built_in_workflows() -> tuple[WorkflowDefinition, ...]:
    return tuple(factory() for factory in built_in_workflow_factories().values())


def built_in_workflow_factories() -> dict[str, Callable[[], WorkflowDefinition]]:
    """Return installed workflow factories through the compatibility API."""

    return dict(installed_workflow_factories())


def installed_module_factories(
    entry_points: Iterable[object] | None = None,
) -> dict[str, InstalledFactory]:
    """Discover installed backend module factories."""

    return _installed_factories(
        MODULE_ENTRY_POINT_GROUP,
        _SOURCE_MODULE_FACTORIES,
        entry_points,
    )


def installed_workflow_factories(
    entry_points: Iterable[object] | None = None,
) -> dict[str, InstalledFactory]:
    """Discover installed workflow factories."""

    return _installed_factories(
        WORKFLOW_ENTRY_POINT_GROUP,
        _SOURCE_WORKFLOW_FACTORIES,
        entry_points,
    )


def _installed_factories(
    group: str,
    source_fallbacks: dict[str, str],
    entry_points: Iterable[object] | None,
) -> dict[str, InstalledFactory]:
    discovered: dict[str, InstalledFactory] = {}
    candidates = (
        tuple(entry_points)
        if entry_points is not None
        else _entry_points_for_group(group)
    )
    for entry_point in candidates:
        name = str(getattr(entry_point, "name", "")).strip()
        reference = str(getattr(entry_point, "value", "")).strip()
        if not name or not reference:
            raise ValueError(f"invalid entry point in {group}")
        if name in discovered:
            if discovered[name].reference == reference:
                continue
            raise ValueError(f"duplicate {group} entry point: {name}")
        factory = entry_point.load()
        if not callable(factory):
            raise TypeError(f"entry point is not callable: {reference}")
        discovered[name] = InstalledFactory(
            id=name,
            group=group,
            provider=_entry_point_provider(entry_point),
            reference=reference,
            factory=factory,
        )

    # Source checkouts do not always have refreshed wheel metadata. This
    # fallback uses import strings only when the corresponding package exists.
    for name, reference in source_fallbacks.items():
        if name in discovered or not _factory_reference_available(reference):
            continue
        discovered[name] = InstalledFactory(
            id=name,
            group=group,
            provider="electroboy-source",
            reference=reference,
            factory=_load_factory_reference(reference),
        )
    return discovered


def _entry_points_for_group(group: str) -> tuple[object, ...]:
    available = metadata.entry_points()
    if hasattr(available, "select"):
        return tuple(available.select(group=group))
    return tuple(available.get(group, ()))


def _entry_point_provider(entry_point: object) -> str:
    distribution = getattr(entry_point, "dist", None)
    distribution_metadata = getattr(distribution, "metadata", None)
    if distribution_metadata is not None:
        provider = str(distribution_metadata.get("Name") or "").strip()
        if provider:
            return provider
    return "installed-package"


def _factory_reference_available(reference: str) -> bool:
    module_name, separator, _attribute = reference.partition(":")
    if not separator:
        return False
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _load_factory_reference(reference: str) -> Callable[[], object]:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("factory must use the form module.path:callable")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise TypeError(f"factory is not callable: {reference}")
    return factory

def registry_payload(
    module_registry: ModuleRegistry,
    workflow_registry: WorkflowRegistry,
) -> dict[str, object]:
    return {
        "modules": module_registry.payload(),
        "workflows": workflow_registry.payload(),
    }
