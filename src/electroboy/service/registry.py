"""Backend module and workflow registry primitives for the browser service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


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
    return (
        _core_module(),
        _agent_sessions_module(),
        _markdown_documents_module(),
        _structured_documents_module(),
        _corkboard_module(),
        _binder_module(),
        _file_browser_module(),
        _progress_module(),
        _project_shell_module(),
        _review_reports_module(),
        _recent_projects_module(),
    )


def built_in_workflows() -> tuple[WorkflowDefinition, ...]:
    from electroboy.workflows.creative_writing import workflow as creative_workflow
    from electroboy.workflows.software import workflow as software_workflow

    return (
        software_workflow(),
        creative_workflow(),
    )


def _route(method: str, path: str, owner: str, handler_name: str) -> RouteDefinition:
    return RouteDefinition(method, path, owner, handler_name)


def _core_module() -> ServiceModule:
    return ServiceModule(
        id="core",
        label="Service Core",
        routes=(
            _route("GET", "/", "core", "index"),
            _route("GET", "/api/health", "core", "health"),
            _route("POST", "/api/contexts", "core", "create_context"),
            _route("GET", "/api/project", "core", "project_payload"),
            _route("POST", "/api/project/open", "core", "open_project"),
            _route("POST", "/api/project/new", "core", "create_project"),
            _route("POST", "/api/project/deactivate", "core", "deactivate_project"),
            _route("GET", "/api/workflow", "core", "workflow_payload"),
            _route("POST", "/api/workflow/stage", "core", "set_workflow_stage"),
        ),
        capabilities=frozenset({"context", "project", "workflow-registry"}),
        state_namespace="core",
    )


def _agent_sessions_module() -> ServiceModule:
    return ServiceModule(
        id="agent_sessions",
        label="Agent Sessions",
        routes=(
            _route("GET", "/api/sessions", "agent_sessions", "list_sessions"),
            _route(
                "GET",
                "/api/session-registry",
                "agent_sessions",
                "session_registry",
            ),
            _route("POST", "/api/sessions/attach", "agent_sessions", "attach"),
            _route("POST", "/api/sessions/message", "agent_sessions", "message"),
            _route("POST", "/api/sessions/key", "agent_sessions", "key"),
            _route("POST", "/api/sessions/raw", "agent_sessions", "raw"),
            _route("POST", "/api/sessions/interrupt", "agent_sessions", "interrupt"),
            _route("POST", "/api/sessions/resize", "agent_sessions", "resize"),
            _route("GET", "/api/sessions/events", "agent_sessions", "events"),
            _route("GET", "/api/sessions/export", "agent_sessions", "export"),
        ),
        capabilities=frozenset({"terminal", "sse", "transcript-export"}),
        state_namespace="sessions",
    )


def _markdown_documents_module() -> ServiceModule:
    return ServiceModule(
        id="markdown_documents",
        label="Markdown Documents",
        routes=(
            _route("GET", "/artifacts/document", "markdown_documents", "preview"),
            _route("GET", "/api/documents/export", "markdown_documents", "export"),
            _route("GET", "/api/artifacts/events", "markdown_documents", "events"),
        ),
        capabilities=frozenset({"markdown-preview", "markdown-edit", "export"}),
        state_namespace="markdown_documents",
    )


def _structured_documents_module() -> ServiceModule:
    return ServiceModule(
        id="structured_documents",
        label="Structured Documents",
        routes=(
            _route("GET", "/artifacts/edit", "structured_documents", "editor"),
            _route("POST", "/api/artifacts/edit", "structured_documents", "save"),
            _route("GET", "/artifacts/requirements", "structured_documents", "view"),
            _route("GET", "/artifacts/design", "structured_documents", "view"),
            _route("GET", "/artifacts/implementation-plan", "structured_documents", "view"),
            _route("GET", "/artifacts/test-plan", "structured_documents", "view"),
        ),
        capabilities=frozenset({"jsonl-source", "markdown-render", "schema-edit"}),
        state_namespace="structured_documents",
    )


def _corkboard_module() -> ServiceModule:
    return ServiceModule(
        id="corkboard",
        label="Corkboard",
        routes=(
            _route("GET", "/artifacts/creative-corkboard", "corkboard", "view"),
            _route("POST", "/api/creative/corkboard", "corkboard", "save"),
            _route("POST", "/api/creative/corkboards", "corkboard", "create"),
        ),
        capabilities=frozenset({"folder-corkboard", "freeform-corkboard"}),
        state_namespace="corkboard",
    )


def _binder_module() -> ServiceModule:
    return ServiceModule(
        id="binder",
        label="Binder",
        routes=(
            _route("GET", "/api/creative/tree", "binder", "tree"),
            _route("POST", "/api/creative/folders", "binder", "create_folder"),
            _route("POST", "/api/creative/documents", "binder", "create_document"),
            _route("POST", "/api/creative/rename", "binder", "rename"),
            _route("POST", "/api/creative/delete", "binder", "delete"),
        ),
        capabilities=frozenset({"filesystem-tree", "creative-documents"}),
        state_namespace="binder",
    )


def _file_browser_module() -> ServiceModule:
    return ServiceModule(
        id="file_browser",
        label="File Browser",
        routes=(
            _route("GET", "/file-browser", "file_browser", "window"),
            _route("GET", "/api/files/browse", "file_browser", "browse"),
        ),
        capabilities=frozenset({"directory-picker", "file-picker"}),
        state_namespace="file_browser",
    )


def _progress_module() -> ServiceModule:
    return ServiceModule(
        id="progress",
        label="Progress",
        routes=(
            _route("GET", "/api/progress/events", "progress", "events"),
            _route("GET", "/api/progress/export", "progress", "export"),
        ),
        capabilities=frozenset({"progress-stream", "issue-announcements"}),
        state_namespace="progress",
    )


def _project_shell_module() -> ServiceModule:
    return ServiceModule(
        id="project_shell",
        label="Project Shell",
        routes=(
            _route("POST", "/api/shell/start", "project_shell", "start"),
            _route("POST", "/api/shell/input", "project_shell", "input"),
            _route("POST", "/api/shell/resize", "project_shell", "resize"),
            _route("POST", "/api/shell/stop", "project_shell", "stop"),
            _route("GET", "/api/shell/events", "project_shell", "events"),
        ),
        capabilities=frozenset({"shell", "terminal"}),
        state_namespace="project_shell",
    )


def _review_reports_module() -> ServiceModule:
    return ServiceModule(
        id="review_reports",
        label="Review Reports",
        routes=(
            _route("GET", "/artifacts/design-review", "review_reports", "view"),
        ),
        capabilities=frozenset({"review-summary", "issue-metadata"}),
        state_namespace="review_reports",
    )


def _recent_projects_module() -> ServiceModule:
    return ServiceModule(
        id="recent_projects",
        label="Recent Projects",
        capabilities=frozenset({"recent-projects"}),
        state_namespace="recent_projects",
    )


def registry_payload(
    module_registry: ModuleRegistry,
    workflow_registry: WorkflowRegistry,
) -> dict[str, object]:
    return {
        "modules": module_registry.payload(),
        "workflows": workflow_registry.payload(),
    }
