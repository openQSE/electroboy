"""Backend module and workflow registry primitives for the browser service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol


class WorkflowController(Protocol):
    """Executable workflow behavior bound to one service runtime."""

    workflow_id: str


WorkflowControllerFactory = Callable[[object], WorkflowController]


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
    assets: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()
    state_namespace: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "routes": [route.payload() for route in self.routes],
            "assets": list(self.assets),
            "capabilities": sorted(self.capabilities),
            "state_namespace": self.state_namespace,
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
    controller_factory: WorkflowControllerFactory | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "modules": list(self.modules),
            "stages": [stage.payload() for stage in self.stages],
            "project_kinds": list(self.project_kinds),
            "backend_package": self.backend_package,
            "frontend_bundle": self.frontend_bundle,
        }


@dataclass
class ModuleRegistry:
    """Registry for reusable backend service modules."""

    _modules: dict[str, ServiceModule] = field(default_factory=dict)

    def register(self, module: ServiceModule) -> None:
        if module.id in self._modules:
            raise ValueError(f"service module is already registered: {module.id}")
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
        self._workflows[workflow.id] = workflow

    def get(self, workflow_id: str) -> WorkflowDefinition:
        return self._workflows[workflow_id]

    def values(self) -> tuple[WorkflowDefinition, ...]:
        return tuple(self._workflows.values())

    def payload(self) -> list[dict[str, object]]:
        return [workflow.payload() for workflow in self.values()]

    def create_controllers(
        self,
        runtime: object,
    ) -> dict[str, WorkflowController]:
        """Bind every executable workflow to a service runtime."""
        controllers: dict[str, WorkflowController] = {}
        for workflow in self.values():
            if workflow.controller_factory is None:
                continue
            controller = workflow.controller_factory(runtime)
            if controller.workflow_id != workflow.id:
                raise ValueError(
                    "workflow controller id does not match its definition: "
                    f"{controller.workflow_id} != {workflow.id}"
                )
            controllers[workflow.id] = controller
        return controllers


def build_module_registry(
    modules: Iterable[ServiceModule] | None = None,
) -> ModuleRegistry:
    registry = ModuleRegistry()
    for module in modules or built_in_service_modules():
        registry.register(module)
    return registry


def build_workflow_registry(
    module_registry: ModuleRegistry,
    workflows: Iterable[WorkflowDefinition] | None = None,
) -> WorkflowRegistry:
    registry = WorkflowRegistry(module_registry)
    for workflow in workflows or built_in_workflows():
        registry.register(workflow)
    return registry


def built_in_service_modules() -> tuple[ServiceModule, ...]:
    from electroboy.modules.agent_sessions import module as agent_sessions_module
    from electroboy.modules.binder import module as binder_module
    from electroboy.modules.core import module as core_module
    from electroboy.modules.corkboard import module as corkboard_module
    from electroboy.modules.file_browser import module as file_browser_module
    from electroboy.modules.markdown_documents import module as markdown_documents_module
    from electroboy.modules.progress import module as progress_module
    from electroboy.modules.project_shell import module as project_shell_module
    from electroboy.modules.recent_projects import module as recent_projects_module
    from electroboy.modules.review_reports import module as review_reports_module
    from electroboy.modules.structured_documents import (
        module as structured_documents_module,
    )

    return (
        core_module(),
        agent_sessions_module(),
        markdown_documents_module(),
        structured_documents_module(),
        corkboard_module(),
        binder_module(),
        file_browser_module(),
        progress_module(),
        project_shell_module(),
        review_reports_module(),
        recent_projects_module(),
    )


def built_in_workflows() -> tuple[WorkflowDefinition, ...]:
    return tuple(factory() for factory in built_in_workflow_factories().values())


def built_in_workflow_factories() -> dict[str, Callable[[], WorkflowDefinition]]:
    from electroboy.workflows.creative_writing import workflow as creative_workflow
    from electroboy.workflows.software import workflow as software_workflow

    return {
        "software": software_workflow,
        "creative-writing": creative_workflow,
    }

def registry_payload(
    module_registry: ModuleRegistry,
    workflow_registry: WorkflowRegistry,
) -> dict[str, object]:
    return {
        "modules": module_registry.payload(),
        "workflows": workflow_registry.payload(),
    }
