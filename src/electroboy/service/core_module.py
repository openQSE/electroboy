"""Core service module contribution."""

from __future__ import annotations

from http import HTTPStatus

from .registry import (
    RouteDefinition,
    ServiceModule,
    build_module_registry,
    build_workflow_registry,
    installed_workflow_factories,
    registry_payload,
)
from .routes import RouteRequest
from .workflow_config import (
    add_configured_workflow,
    configured_workflows,
    workflow_config_payload,
)


def _route(method: str, path: str, handler_name: str) -> RouteDefinition:
    return RouteDefinition(method, path, "core", handler_name)


def _conflict(request: RouteRequest, error: Exception) -> None:
    request.send_json({"error": str(error)}, status=HTTPStatus.CONFLICT)


def _index(request: RouteRequest) -> None:
    request.send_text(
        request.operations.service_index(),
        "text/html; charset=utf-8",
    )


def _health(request: RouteRequest) -> None:
    request.send_json(request.operations.health_payload())


def _create_context(request: RouteRequest) -> None:
    request.send_json(request.state.create_context())


def _project_payload(request: RouteRequest) -> None:
    try:
        payload = request.state.project_payload(request.context_id)
    except Exception as error:
        _conflict(request, error)
        return
    request.send_json(payload)


def _project_status(request: RouteRequest) -> None:
    try:
        payload = request.state.project_status_payload(request.context_id)
    except Exception as error:
        _conflict(request, error)
        return
    request.send_json(payload)


def _project_action(request: RouteRequest, method: str) -> None:
    try:
        payload = request.body()
        result = getattr(request.state, method)(
            request.context_id,
            str(payload.get("path") or ""),
        )
    except Exception as error:
        _conflict(request, error)
        return
    request.send_json(result)


def _open_project(request: RouteRequest) -> None:
    _project_action(request, "open_project")


def _create_project(request: RouteRequest) -> None:
    _project_action(request, "create_project")


def _deactivate_project(request: RouteRequest) -> None:
    try:
        payload = request.state.deactivate_project(request.context_id)
    except Exception as error:
        _conflict(request, error)
        return
    request.send_json(payload)


def _workflow_payload(request: RouteRequest) -> None:
    try:
        payload = request.state.workflow_payload(request.context_id)
    except Exception as error:
        _conflict(request, error)
        return
    request.send_json(payload)


def _set_workflow_stage(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.select_workflow_stage(
            request.context_id,
            str(payload.get("stage") or ""),
        )
    except Exception as error:
        _conflict(request, error)
        return
    request.send_json(result)


def _workflow_config(request: RouteRequest) -> None:
    request.send_json(workflow_config_payload(request.config.root))


def _registry(request: RouteRequest) -> None:
    modules = request.config.module_registry
    workflows = request.config.workflow_registry
    if modules is None or workflows is None:
        request.send_json(
            {"error": "service registry is not configured"},
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    request.send_json(
        {
            **registry_payload(modules, workflows),
            "frontend_bundles": request.operations.frontend_asset_payload(),
            "workflow_config": workflow_config_payload(request.config.root),
        }
    )


def _add_configured_workflow(request: RouteRequest) -> None:
    try:
        payload = request.body()
        workflow_id = str(payload.get("id") or "")
        factory = str(payload.get("factory") or "")
        workflow_config = add_configured_workflow(
            request.config.root,
            workflow_id,
            factory,
        )
        modules = request.config.module_registry or build_module_registry()
        request.config.workflow_registry = build_workflow_registry(
            modules,
            configured_workflows(
                request.config.root,
                installed_workflow_factories(),
            ),
        )
        request.state.bind_workflow_registry(request.config.workflow_registry)
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        _conflict(request, error)
        return
    request.send_json(
        {
            "status": "added",
            "workflow_config": workflow_config.payload(),
            "registry": registry_payload(
                modules,
                request.config.workflow_registry,
            ),
        }
    )


_HANDLERS = {
    "index": _index,
    "health": _health,
    "create_context": _create_context,
    "project_payload": _project_payload,
    "project_status": _project_status,
    "open_project": _open_project,
    "create_project": _create_project,
    "deactivate_project": _deactivate_project,
    "workflow_payload": _workflow_payload,
    "set_workflow_stage": _set_workflow_stage,
    "workflow_config": _workflow_config,
    "registry": _registry,
    "add_configured_workflow": _add_configured_workflow,
}


def module() -> ServiceModule:
    """Return the module that exposes the service shell and workflow registry."""

    return ServiceModule(
        id="core",
        label="Service Core",
        routes=(
            _route("GET", "/", "index"),
            _route("GET", "/index.html", "index"),
            _route("GET", "/api/health", "health"),
            _route("POST", "/api/contexts", "create_context"),
            _route("GET", "/api/project", "project_payload"),
            _route("GET", "/api/project/status", "project_status"),
            _route("POST", "/api/project/open", "open_project"),
            _route("POST", "/api/project/new", "create_project"),
            _route("POST", "/api/project/deactivate", "deactivate_project"),
            _route("GET", "/api/workflow", "workflow_payload"),
            _route("POST", "/api/workflow/stage", "set_workflow_stage"),
            _route("GET", "/api/workflows/config", "workflow_config"),
            _route("GET", "/api/registry", "registry"),
            _route(
                "POST",
                "/api/workflows/config/workflows",
                "add_configured_workflow",
            ),
        ),
        handlers=_HANDLERS,
        capabilities=frozenset({"context", "project", "workflow-registry"}),
        state_namespace="core",
    )
